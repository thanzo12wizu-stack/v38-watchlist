from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .utils import finite_or_none

_FIELDS = {"open", "high", "low", "close", "adj_close", "adjclose", "volume"}


def _normalize_frame(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    if isinstance(out.columns, pd.MultiIndex):
        field_level = None
        for level in range(out.columns.nlevels):
            values = {str(v).lower().replace(" ", "_") for v in out.columns.get_level_values(level)}
            if values & _FIELDS:
                field_level = level
                break
        if field_level is not None:
            out.columns = out.columns.get_level_values(field_level)
        else:
            singleton = next((i for i in range(out.columns.nlevels) if len(set(out.columns.get_level_values(i))) == 1), None)
            if singleton is None:
                raise ValueError("ambiguous MultiIndex price columns")
            out.columns = out.columns.droplevel(singleton)
    out.columns = [str(c).lower().replace(" ", "_") for c in out.columns]
    out = out.rename(columns={"adj_close": "close", "adjclose": "close"})
    if out.columns.duplicated().any():
        merged: dict[str, pd.Series] = {}
        for name in dict.fromkeys(out.columns):
            selected = out.loc[:, out.columns == name]
            merged[name] = selected.bfill(axis=1).iloc[:, 0]
        out = pd.DataFrame(merged, index=out.index)
    required = {"close", "high", "low", "volume"}
    missing = required - set(out.columns)
    if missing:
        raise ValueError(f"price frame missing columns: {sorted(missing)}")
    for name in required | {"open"}:
        if name in out:
            out[name] = pd.to_numeric(out[name], errors="coerce")
    return out.sort_index().loc[~out.index.duplicated(keep="last")]


def load_price_map(path: Path) -> dict[str, pd.DataFrame]:
    obj: Any = pd.read_pickle(path)
    if not isinstance(obj, Mapping):
        raise TypeError("price cache must be a mapping of ticker to DataFrame")
    result: dict[str, pd.DataFrame] = {}
    for ticker, frame in obj.items():
        if isinstance(frame, pd.DataFrame) and not frame.empty:
            try:
                result[str(ticker).upper()] = _normalize_frame(frame)
            except (TypeError, ValueError):
                continue
    return result


def save_price_map(path: Path, prices: Mapping[str, pd.DataFrame]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    pd.to_pickle(dict(prices), tmp)
    tmp.replace(path)


def _split_yfinance_download(raw: pd.DataFrame, tickers: Sequence[str]) -> dict[str, pd.DataFrame]:
    if raw is None or raw.empty:
        return {}
    requested = [str(t).upper() for t in tickers]
    if not isinstance(raw.columns, pd.MultiIndex):
        if len(requested) != 1:
            return {}
        try:
            return {requested[0]: _normalize_frame(raw.dropna(how="all"))}
        except ValueError:
            return {}
    result: dict[str, pd.DataFrame] = {}
    for ticker in requested:
        for level in range(raw.columns.nlevels):
            try:
                frame = raw.xs(ticker, axis=1, level=level, drop_level=True).dropna(how="all")
                if not frame.empty:
                    result[ticker] = _normalize_frame(frame)
                    break
            except (KeyError, TypeError, ValueError):
                continue
    return result


def _download_once(yf: Any, batch: list[str], period: str) -> dict[str, pd.DataFrame]:
    raw = yf.download(
        tickers=batch, period=period, interval="1d", auto_adjust=False,
        actions=False, group_by="column", threads=False, progress=False, timeout=45,
    )
    return _split_yfinance_download(raw, batch)


def download_price_map(
    tickers: Sequence[str], *, period: str = "18mo", batch_size: int = 20, retries: int = 3
) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    try:
        import yfinance as yf
    except ImportError as exc:
        raise RuntimeError("yfinance is required when no price cache exists") from exc
    normalized = sorted({str(t).strip().upper() for t in tickers if str(t).strip()})
    ordered = (["QQQ"] if "QQQ" in normalized else []) + [t for t in normalized if t != "QQQ"]
    prices: dict[str, pd.DataFrame] = {}
    failures: list[dict[str, Any]] = []
    batches: list[list[str]] = [["QQQ"]] if ordered and ordered[0] == "QQQ" else []
    rest = ordered[1:] if batches else ordered
    batches.extend(rest[i:i + batch_size] for i in range(0, len(rest), batch_size))
    for batch_index, batch in enumerate(batches):
        received: dict[str, pd.DataFrame] = {}
        last_error = "empty_response"
        for attempt in range(1, retries + 1):
            try:
                received = _download_once(yf, batch, period)
                if received:
                    break
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {str(exc)[:120]}"
            time.sleep(min(30, 2 ** attempt + batch_index % 3))
        prices.update(received)
        missing = [ticker for ticker in batch if ticker not in received]
        if missing:
            failures.append({"batch": batch_index, "requested": len(batch), "missing": missing, "error": last_error})
        time.sleep(1.0)
    diagnostics = {
        "source": "yfinance", "requested": len(normalized), "received": len(prices),
        "coverage": len(prices) / len(normalized) if normalized else 0.0,
        "qqq_received": "QQQ" in prices, "failed_batches": failures,
    }
    return prices, diagnostics


def compute_price_features(frame: pd.DataFrame, benchmark: pd.Series | None = None) -> dict[str, float | bool | None]:
    f = _normalize_frame(frame)
    close = f["close"].dropna()
    high, low, volume = f["high"], f["low"], f["volume"]
    if len(close) < 30:
        return {}
    latest = float(close.iloc[-1])
    prev = close.shift(1)
    tr = pd.concat([(high - low), (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    atr14 = tr.rolling(14).mean(); sma10 = close.rolling(10).mean(); sma50 = close.rolling(50).mean()
    sma150 = close.rolling(150).mean(); sma200 = close.rolling(200).mean()
    ema21_low = low.ewm(span=21, adjust=False).mean(); pivot20 = high.shift(1).rolling(20).max()
    range5 = (high - low).rolling(5).mean(); range20 = (high - low).rolling(20).mean()
    down_volume = volume.where(close < prev).rolling(10).sum(); total_volume = volume.rolling(10).sum()
    atr = atr14.iloc[-1]
    stop = max(ema21_low.iloc[-1], sma10.iloc[-1]) if pd.notna(ema21_low.iloc[-1]) and pd.notna(sma10.iloc[-1]) else np.nan
    risk_pct = (latest - stop) / latest * 100 if latest and pd.notna(stop) else np.nan
    upside = (close.tail(252).max() - latest) / latest * 100 if latest else np.nan
    aligned = sum(latest > x for x in (sma10.iloc[-1], sma50.iloc[-1], sma150.iloc[-1], sma200.iloc[-1]) if pd.notna(x)) / 4
    out: dict[str, float | bool | None] = {
        "price": finite_or_none(latest),
        "adr_pct": finite_or_none(tr.rolling(20).mean().iloc[-1] / latest * 100 if latest else np.nan),
        "dollar_volume_20d": finite_or_none((close * volume).rolling(20).mean().iloc[-1]),
        "volume_ratio_20d": finite_or_none(volume.rolling(5).mean().iloc[-1] / volume.rolling(20).mean().iloc[-1]),
        "distance_52w_high_pct": finite_or_none((latest / close.tail(252).max() - 1) * 100),
        "sma10": finite_or_none(sma10.iloc[-1]), "sma50": finite_or_none(sma50.iloc[-1]),
        "sma150": finite_or_none(sma150.iloc[-1]), "sma200": finite_or_none(sma200.iloc[-1]),
        "stop_sma10": finite_or_none(sma10.iloc[-1]), "stop_ema21_low": finite_or_none(ema21_low.iloc[-1]),
        "pivot_20d": finite_or_none(pivot20.iloc[-1]),
        "distance_pivot_pct": finite_or_none((latest / pivot20.iloc[-1] - 1) * 100 if pd.notna(pivot20.iloc[-1]) else np.nan),
        "above_pivot": bool(pd.notna(pivot20.iloc[-1]) and latest > pivot20.iloc[-1]),
        "near_ema21_low": bool(pd.notna(ema21_low.iloc[-1]) and abs(latest / ema21_low.iloc[-1] - 1) <= .025),
        "extension_atr": finite_or_none((latest - sma50.iloc[-1]) / atr if pd.notna(sma50.iloc[-1]) and pd.notna(atr) and atr else np.nan),
        "stop_risk_pct": finite_or_none(risk_pct),
        "reward_risk_raw": finite_or_none(upside / risk_pct if pd.notna(risk_pct) and risk_pct > 0 else np.nan),
        "trend_alignment": finite_or_none(aligned),
        "contraction_score_raw": finite_or_none(1 - min(1.0, range5.iloc[-1] / range20.iloc[-1]) if pd.notna(range5.iloc[-1]) and pd.notna(range20.iloc[-1]) and range20.iloc[-1] else np.nan),
        "pivot_quality_raw": finite_or_none(max(0.0, 1 - abs(latest / pivot20.iloc[-1] - 1) / .10) if pd.notna(pivot20.iloc[-1]) else np.nan),
        "participation_score_raw": finite_or_none(min(2.0, volume.rolling(5).mean().iloc[-1] / volume.rolling(20).mean().iloc[-1]) / 2),
        "supply_risk_raw": finite_or_none(down_volume.iloc[-1] / total_volume.iloc[-1] if pd.notna(total_volume.iloc[-1]) and total_volume.iloc[-1] else np.nan),
        "hard_block": bool((pd.notna(sma150.iloc[-1]) and latest < sma150.iloc[-1]) or (len(sma150.dropna()) >= 21 and sma150.iloc[-1] < sma150.iloc[-21])),
    }
    b = benchmark.dropna() if benchmark is not None else None
    for window in (21, 63, 126, 189, 252):
        if len(close) <= window:
            continue
        stock_ret = close.iloc[-1] / close.iloc[-window - 1] - 1
        bench_ret = b.iloc[-1] / b.iloc[-window - 1] - 1 if b is not None and len(b) > window else 0
        raw = stock_ret - bench_ret
        out[f"rs_raw_{window}"] = finite_or_none(raw)
        if len(close) > window + 21:
            prior = close.iloc[-22] / close.iloc[-window - 22] - 1
            prior_b = b.iloc[-22] / b.iloc[-window - 22] - 1 if b is not None and len(b) > window + 21 else 0
            out[f"rs_change_raw_{window}"] = finite_or_none(raw - (prior - prior_b))
    return out
