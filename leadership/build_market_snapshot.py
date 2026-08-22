from __future__ import annotations

import argparse
import csv
import json
import math
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf


@dataclass(frozen=True)
class UniverseRow:
    symbol: str
    price: float | None
    volume: float | None
    market_cap: float | None
    sector: str
    industry: str


def _num(value: Any) -> float | None:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def load_universe(path: Path, *, min_price: float, min_mcap: float, min_volume: float) -> list[UniverseRow]:
    rows: list[UniverseRow] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            symbol = str(row.get("シンボル") or row.get("symbol") or "").strip().upper()
            if not symbol or any(x in symbol for x in ("/P", "/", "^", "=")):
                continue
            sec_type = str(row.get("証券種別") or row.get("security_type") or "").strip().lower()
            subtype = str(row.get("証券サブタイプ") or row.get("security_subtype") or "").strip().lower()
            if sec_type and sec_type != "stock":
                continue
            if subtype and subtype not in {"common", "ordinary", "common stock"}:
                continue
            price = _num(row.get("価格") or row.get("price"))
            volume = _num(row.get("出来高, 1日") or row.get("volume"))
            mcap = _num(row.get("時価総額") or row.get("market_cap"))
            if price is None or price < min_price:
                continue
            if mcap is None or mcap < min_mcap:
                continue
            if volume is not None and volume < min_volume:
                continue
            rows.append(UniverseRow(
                symbol=symbol,
                price=price,
                volume=volume,
                market_cap=mcap,
                sector=str(row.get("セクター") or row.get("sector") or ""),
                industry=str(row.get("業種") or row.get("industry") or ""),
            ))
    rows.sort(key=lambda x: x.market_cap or 0, reverse=True)
    return rows


def _extract_ohlcv(downloaded: pd.DataFrame, symbol: str, batch_size: int) -> pd.DataFrame | None:
    if downloaded is None or downloaded.empty:
        return None
    try:
        if isinstance(downloaded.columns, pd.MultiIndex):
            level0 = set(map(str, downloaded.columns.get_level_values(0)))
            level1 = set(map(str, downloaded.columns.get_level_values(1)))
            if symbol in level0:
                frame = downloaded[symbol].copy()
            elif symbol in level1:
                frame = downloaded.xs(symbol, axis=1, level=1).copy()
            elif batch_size == 1:
                frame = downloaded.copy()
                if isinstance(frame.columns, pd.MultiIndex):
                    frame.columns = frame.columns.get_level_values(-1)
            else:
                return None
        else:
            if batch_size != 1:
                return None
            frame = downloaded.copy()
    except (KeyError, ValueError, TypeError):
        return None

    wanted = {str(c).lower(): c for c in frame.columns}
    if "close" not in wanted:
        return None
    frame = frame.rename(columns={v: k.title() for k, v in wanted.items()})
    cols = [c for c in ("Open", "High", "Low", "Close", "Volume") if c in frame.columns]
    frame = frame[cols].copy()
    frame = frame.apply(pd.to_numeric, errors="coerce")
    frame = frame.dropna(subset=["Close"])
    return frame if not frame.empty else None


def _atr14(frame: pd.DataFrame) -> float | None:
    if len(frame) < 20 or not {"High", "Low", "Close"}.issubset(frame.columns):
        return None
    prev_close = frame["Close"].shift(1)
    tr = pd.concat([
        frame["High"] - frame["Low"],
        (frame["High"] - prev_close).abs(),
        (frame["Low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    val = tr.rolling(14).mean().iloc[-1]
    return float(val) if pd.notna(val) else None


def _rolling_vwap(frame: pd.DataFrame, window: int) -> float | None:
    if len(frame) < window or "Volume" not in frame.columns:
        return None
    vol = frame["Volume"].tail(window)
    if vol.isna().all() or float(vol.fillna(0).sum()) <= 0:
        return None
    if {"High", "Low", "Close"}.issubset(frame.columns):
        price = (frame["High"] + frame["Low"] + frame["Close"]) / 3.0
    else:
        price = frame["Close"]
    p = price.tail(window)
    return float((p * vol).sum() / vol.sum())


def _ret(close: pd.Series, days: int) -> float | None:
    clean = close.dropna()
    if len(clean) <= days:
        return None
    start = float(clean.iloc[-days - 1])
    end = float(clean.iloc[-1])
    if start <= 0:
        return None
    return end / start - 1.0


def compute_raw_metrics(frame: pd.DataFrame) -> dict[str, float | None]:
    close = frame["Close"].dropna()
    if len(close) < 30:
        return {}
    price = float(close.iloc[-1])
    ema21 = float(close.ewm(span=21, adjust=False).mean().iloc[-1]) if len(close) >= 21 else None
    sma50 = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else None
    high52 = float(frame["High"].tail(252).max()) if "High" in frame.columns and len(frame) >= 50 else float(close.tail(252).max())
    from_high = 100.0 * (price / high52 - 1.0) if high52 > 0 else None
    pivot = None
    if "High" in frame.columns and len(frame) >= 22:
        pivot = float(frame["High"].iloc[-21:-1].max())
    elif len(close) >= 22:
        pivot = float(close.iloc[-21:-1].max())

    volume_ratio = None
    avg_volume20 = None
    avg_dollar_volume20 = None
    if "Volume" in frame.columns and len(frame) >= 21:
        v = frame["Volume"].astype(float)
        prior20 = v.iloc[-21:-1]
        avg_volume20 = float(prior20.mean()) if prior20.notna().any() else None
        latest_v = float(v.iloc[-1]) if pd.notna(v.iloc[-1]) else None
        if avg_volume20 and latest_v is not None and avg_volume20 > 0:
            volume_ratio = latest_v / avg_volume20
        c20 = frame["Close"].tail(20).astype(float)
        v20 = v.tail(20)
        avg_dollar_volume20 = float((c20 * v20).mean()) if v20.notna().any() else None

    return {
        "price": price,
        "ret21": _ret(close, 21),
        "ret63": _ret(close, 63),
        "ret189": _ret(close, 189),
        "ema21": ema21,
        "sma50": sma50,
        "vwap63": _rolling_vwap(frame, 63),
        "atr14": _atr14(frame),
        "pivot": pivot,
        "pct_from_52w_high": from_high,
        "volume_ratio": volume_ratio,
        "avg_volume20": avg_volume20,
        "avg_dollar_volume20": avg_dollar_volume20,
    }


def percentile_ranks(series: dict[str, float | None]) -> dict[str, float]:
    valid = {k: v for k, v in series.items() if v is not None and math.isfinite(v)}
    if not valid:
        return {}
    s = pd.Series(valid, dtype=float)
    ranks = s.rank(method="average", pct=True) * 100.0
    return {str(k): round(float(v), 2) for k, v in ranks.items()}


def enrich_relative_strength(raw: dict[str, dict[str, float | None]], benchmark: dict[str, float | None]) -> dict[str, dict[str, float | None]]:
    out = {sym: dict(vals) for sym, vals in raw.items()}
    for horizon in (21, 63, 189):
        key = f"ret{horizon}"
        bench = benchmark.get(key)
        excess: dict[str, float | None] = {}
        for sym, vals in out.items():
            r = vals.get(key)
            x = (r - bench) if r is not None and bench is not None else None
            vals[f"rel{horizon}"] = x
            excess[sym] = x
        ranks = percentile_ranks(excess)
        for sym, rank in ranks.items():
            out[sym][f"rs{horizon}"] = rank
    for vals in out.values():
        rs21 = vals.get("rs21")
        rs63 = vals.get("rs63")
        rs189 = vals.get("rs189")
        vals["rs_accel_fast"] = rs21 - rs63 if rs21 is not None and rs63 is not None else None
        vals["rs_accel_slow"] = rs63 - rs189 if rs63 is not None and rs189 is not None else None
    return out


def _download_batch(symbols: list[str], period: str) -> pd.DataFrame:
    return yf.download(
        tickers=symbols,
        period=period,
        interval="1d",
        auto_adjust=True,
        actions=False,
        progress=False,
        threads=True,
        group_by="ticker",
        timeout=20,
    )


def download_history(symbols: list[str], *, batch_size: int, period: str, pause: float) -> tuple[dict[str, pd.DataFrame], list[str]]:
    frames: dict[str, pd.DataFrame] = {}
    failed: list[str] = []
    for start in range(0, len(symbols), batch_size):
        batch = symbols[start:start + batch_size]
        try:
            data = _download_batch(batch, period)
        except Exception as exc:
            print(f"batch {start // batch_size + 1} failed: {exc}")
            failed.extend(batch)
            continue
        for symbol in batch:
            frame = _extract_ohlcv(data, symbol, len(batch))
            if frame is None or len(frame) < 30:
                failed.append(symbol)
            else:
                frames[symbol] = frame
        print(f"history {min(start + batch_size, len(symbols))}/{len(symbols)} valid={len(frames)} failed={len(failed)}")
        if pause:
            time.sleep(pause)
    return frames, failed


def to_metric_maps(metrics: dict[str, dict[str, float | None]]) -> dict[str, dict[str, float]]:
    keys = sorted({k for vals in metrics.values() for k in vals})
    maps: dict[str, dict[str, float]] = {}
    for key in keys:
        bucket: dict[str, float] = {}
        for sym, vals in metrics.items():
            val = vals.get(key)
            if val is not None and math.isfinite(float(val)):
                bucket[sym] = round(float(val), 6)
        maps[key] = bucket
    return maps


def main() -> None:
    parser = argparse.ArgumentParser(description="Build independent Leadership market snapshot from Yahoo daily bars")
    parser.add_argument("--universe", type=Path, default=Path("universe.csv"))
    parser.add_argument("--output", type=Path, default=Path("leadership/market_snapshot.json"))
    parser.add_argument("--benchmark", default="QQQ")
    parser.add_argument("--period", default="15mo")
    parser.add_argument("--batch-size", type=int, default=80)
    parser.add_argument("--pause", type=float, default=0.15)
    parser.add_argument("--min-price", type=float, default=5.0)
    parser.add_argument("--min-mcap", type=float, default=750_000_000)
    parser.add_argument("--min-volume", type=float, default=200_000)
    parser.add_argument("--max-symbols", type=int, default=0, help="0 = no cap after liquidity filter")
    args = parser.parse_args()

    universe = load_universe(
        args.universe,
        min_price=args.min_price,
        min_mcap=args.min_mcap,
        min_volume=args.min_volume,
    )
    if args.max_symbols > 0:
        universe = universe[:args.max_symbols]
    symbols = [row.symbol for row in universe if row.symbol != args.benchmark]
    print(f"leadership universe={len(symbols)}")

    benchmark_data = _download_batch([args.benchmark], args.period)
    benchmark_frame = _extract_ohlcv(benchmark_data, args.benchmark, 1)
    if benchmark_frame is None or len(benchmark_frame) < 190:
        raise RuntimeError(f"benchmark history unavailable: {args.benchmark}")
    benchmark_metrics = compute_raw_metrics(benchmark_frame)

    frames, failed = download_history(symbols, batch_size=args.batch_size, period=args.period, pause=args.pause)
    raw: dict[str, dict[str, float | None]] = {}
    for symbol, frame in frames.items():
        values = compute_raw_metrics(frame)
        if len(frame) < 190 or values.get("ret189") is None:
            continue
        adv = values.get("avg_dollar_volume20")
        avg_volume = values.get("avg_volume20")
        if adv is not None and adv < 10_000_000:
            continue
        if avg_volume is not None and avg_volume < 300_000:
            continue
        raw[symbol] = values

    enriched = enrich_relative_strength(raw, benchmark_metrics)
    metric_maps = to_metric_maps(enriched)
    metric_payload = {
        (key if key == "rs63" else f"metric_{key}"): values
        for key, values in metric_maps.items()
    }
    output = {
        "schema": 1,
        "source": "Yahoo Finance daily adjusted OHLCV (independent Leadership flow)",
        "asof": str(benchmark_frame.index[-1].date()),
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "benchmark": args.benchmark,
        "universe_requested": len(symbols),
        "universe_valid": len(enriched),
        "failed_sample": sorted(set(failed))[:100],
        **metric_payload,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(json.dumps({
        "asof": output["asof"],
        "requested": output["universe_requested"],
        "valid": output["universe_valid"],
        "rs21": len(metric_maps.get("rs21", {})),
        "rs63": len(metric_maps.get("rs63", {})),
        "rs189": len(metric_maps.get("rs189", {})),
        "entry_inputs": len(metric_maps.get("ema21", {})),
    }, indent=2))


if __name__ == "__main__":
    main()
