#!/usr/bin/env python3
"""Build presentation-only OHLCV shards for the V38 inline chart.

Downstream-only by design:
- reads v38-live-state.json only to discover currently visible symbols,
- fetches daily OHLCV for rendering,
- never modifies V38 ranking, Market Mode, sleeves, or trading rules,
- preserves last-known chart rows per ticker when a refresh fails.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import shutil
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import yfinance as yf


SYMBOL_KEYS = {"ticker", "symbol"}


def _finite(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _bucket(ticker: str) -> str:
    first = (ticker or "").strip().upper()[:1]
    return first if first and "A" <= first <= "Z" else "OTHER"


def _looks_like_ticker(value: object) -> bool:
    text = str(value or "").strip().upper()
    if not text or len(text) > 10:
        return False
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-")
    return all(ch in allowed for ch in text) and any(ch.isalpha() for ch in text)


def _collect_symbols(node: object, out: set[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if str(key).lower() in SYMBOL_KEYS and _looks_like_ticker(value):
                out.add(str(value).strip().upper())
            _collect_symbols(value, out)
    elif isinstance(node, list):
        for value in node:
            _collect_symbols(value, out)


def _symbols(state: dict) -> list[str]:
    out: set[str] = {"QQQ", "TQQQ"}
    _collect_symbols(state, out)

    ranking = state.get("ranking") if isinstance(state, dict) else {}
    if isinstance(ranking, dict):
        for key, value in ranking.items():
            if not isinstance(value, list):
                continue
            if not any(token in str(key).lower() for token in ("top", "core", "reopen")):
                continue
            for item in value:
                if _looks_like_ticker(item):
                    out.add(str(item).strip().upper())

    early = state.get("early1") if isinstance(state, dict) else {}
    if isinstance(early, dict):
        for value in early.values():
            if isinstance(value, str) and _looks_like_ticker(value):
                out.add(value.strip().upper())
    return sorted(out)


def _bar_date(index) -> str:
    try:
        ts = index
        if getattr(ts, "tzinfo", None) is not None:
            ts = ts.tz_convert("America/New_York")
        return ts.date().isoformat()
    except Exception:
        return str(index)[:10]


def _yf_symbol(ticker: str) -> str:
    return ticker.replace(".", "-")


def _fetch_once(ticker: str, period: str, max_bars: int) -> dict:
    prices = yf.Ticker(_yf_symbol(ticker)).history(
        period=period,
        interval="1d",
        auto_adjust=False,
        actions=False,
    )
    if prices is None or prices.empty:
        raise RuntimeError("no price history")

    rows = []
    for index, row in prices.tail(max_bars).iterrows():
        o = _finite(row.get("Open"))
        h = _finite(row.get("High"))
        l = _finite(row.get("Low"))
        c = _finite(row.get("Close"))
        v = _finite(row.get("Volume"))
        if None in (o, h, l, c):
            continue
        if h < max(o, l, c) or l > min(o, h, c):
            continue
        rows.append(
            {
                "time": _bar_date(index),
                "open": round(o, 6),
                "high": round(h, 6),
                "low": round(l, 6),
                "close": round(c, 6),
                "volume": round(v or 0.0, 2),
            }
        )

    if len(rows) < 30:
        raise RuntimeError(f"insufficient bars: {len(rows)}")

    return {
        "ticker": ticker,
        "bars": rows,
        "history_session_date": rows[-1]["time"],
        "bar_count": len(rows),
        "source": "yfinance_daily_ohlcv_v38_presentation_only",
        "period": period,
        "interval": "1d",
        "stale": False,
    }


def _fetch(ticker: str, period: str, max_bars: int, attempts: int) -> dict:
    last = None
    for attempt in range(attempts):
        try:
            return _fetch_once(ticker, period, max_bars)
        except Exception as exc:  # pragma: no cover - network failures vary
            last = exc
            if attempt + 1 < attempts:
                time.sleep((attempt + 1) * 1.4 + random.uniform(0.0, 0.35))
    raise last or RuntimeError("chart fetch failed")


def _load_previous(directory: Path | None) -> dict[str, dict]:
    if directory is None or not directory.is_dir():
        return {}
    out: dict[str, dict] = {}
    for path in directory.glob("*.json"):
        if path.name == "index.json":
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        tickers = payload.get("tickers") if isinstance(payload, dict) else None
        if not isinstance(tickers, dict):
            continue
        for ticker, record in tickers.items():
            if isinstance(record, dict) and record.get("bars"):
                out[str(ticker).upper()] = record
    return out


def build(
    state_path: Path,
    output_dir: Path,
    previous_dir: Path | None,
    period: str,
    max_bars: int,
    workers: int,
    attempts: int,
) -> dict:
    state = json.loads(state_path.read_text(encoding="utf-8"))
    asof = str(state.get("asof") or "")[:10]
    if len(asof) != 10:
        raise RuntimeError("V38 live state as-of is missing")

    symbols = _symbols(state)
    if not symbols:
        raise RuntimeError("V38 live state contains no visible symbols")

    previous = _load_previous(previous_dir)
    records: dict[str, dict] = {}
    errors: dict[str, str] = {}

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {
            pool.submit(_fetch, ticker, period, max_bars, max(1, attempts)): ticker
            for ticker in symbols
        }
        for future in as_completed(futures):
            ticker = futures[future]
            try:
                records[ticker] = future.result()
            except Exception as exc:
                message = f"{type(exc).__name__}: {str(exc)[:180]}"
                errors[ticker] = message
                old = previous.get(ticker)
                if old and old.get("bars"):
                    keep = dict(old)
                    keep["ticker"] = ticker
                    keep["stale"] = True
                    keep["refresh_error"] = message
                    records[ticker] = keep

    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    by_bucket: dict[str, dict[str, dict]] = {}
    for ticker in symbols:
        record = records.get(ticker)
        if not record:
            continue
        by_bucket.setdefault(_bucket(ticker), {})[ticker] = record

    for bucket, tickers in sorted(by_bucket.items()):
        shard = {
            "schema_version": "1.0",
            "generated_at": generated_at,
            "session_date": asof,
            "source": "v38_visible_symbols_presentation_only",
            "tickers": {ticker: tickers[ticker] for ticker in sorted(tickers)},
        }
        (output_dir / f"{bucket}.json").write_text(
            json.dumps(shard, ensure_ascii=False, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )

    fresh = sum(1 for record in records.values() if not record.get("stale"))
    stale = sum(1 for record in records.values() if record.get("stale"))
    index = {
        "schema_version": "1.0",
        "generated_at": generated_at,
        "session_date": asof,
        "source": "v38_visible_symbols_presentation_only",
        "requested": len(symbols),
        "available": len(records),
        "fresh": fresh,
        "stale": stale,
        "failed_without_cache": max(0, len(symbols) - len(records)),
        "errors": errors,
        "shards": {bucket: len(tickers) for bucket, tickers in sorted(by_bucket.items())},
        "upstream_read_only": [str(state_path)],
    }
    (output_dir / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(index, ensure_ascii=False, indent=2))
    return index


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--period", default="1y")
    parser.add_argument("--max-bars", type=int, default=260)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--attempts", type=int, default=2)
    args = parser.parse_args()

    index = build(
        state_path=args.state,
        output_dir=args.output,
        previous_dir=args.previous,
        period=args.period,
        max_bars=max(180, args.max_bars),
        workers=max(1, args.workers),
        attempts=max(1, args.attempts),
    )
    requested = int(index.get("requested") or 0)
    available = int(index.get("available") or 0)
    if requested and available / requested < 0.80:
        raise SystemExit(f"V38 chart coverage too low: {available}/{requested}")


if __name__ == "__main__":
    main()
