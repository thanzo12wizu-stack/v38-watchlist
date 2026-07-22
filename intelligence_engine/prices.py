from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .utils import finite_or_none


def _normalize_frame(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    if isinstance(out.columns, pd.MultiIndex):
        raise ValueError("single-ticker frame must not have MultiIndex columns")
    out.columns = [str(c).lower().replace(" ", "_") for c in out.columns]
    out = out.rename(columns={"adj_close": "close", "adjclose": "close"})
    required = {"close", "high", "low", "volume"}
    if not required.issubset(out.columns):
        raise ValueError(f"price frame missing columns: {sorted(required - set(out.columns))}")
    return out.sort_index()


def load_price_map(path: Path) -> dict[str, pd.DataFrame]:
    obj: Any = pd.read_pickle(path)
    if not isinstance(obj, Mapping):
        raise TypeError("price cache must be a mapping of ticker to DataFrame")
    return {
        str(t).upper(): _normalize_frame(f)
        for t, f in obj.items()
        if isinstance(f, pd.DataFrame) and not f.empty
    }


def _split_yfinance_download(raw: pd.DataFrame, tickers: Sequence[str]) -> dict[str, pd.DataFrame]:
    if raw.empty:
        return {}
    requested = [str(t).upper() for t in tickers]
    result: dict[str, pd.DataFrame] = {}
    if not isinstance(raw.columns, pd.MultiIndex):
        if len(requested) == 1:
            result[requested[0]] = _normalize_frame(raw)
        return result
    level0 = {str(x) for x in raw.columns.get_level_values(0)}
    fields = {"Open", "High", "Low", "Close", "Adj Close", "Volume"}
    field_first = bool(level0 & fields)
    for ticker in requested:
        try:
            frame = raw.xs(ticker, axis=1, level=1 if field_first else 0, drop_level=True)
            if not frame.empty:
                result[ticker] = _normalize_frame(frame.dropna(how="all"))
        except (KeyError, ValueError):
            continue
    return result


def download_price_map(
    tickers: Sequence[str],
    *,
    period: str = "18mo",
    batch_size: int = 200,
) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    try:
        import yfinance as yf
    except ImportError as exc:
        raise RuntimeError("yfinance is required when no price cache exists") from exc

    normalized = sorted({str(t).strip().upper() for t in tickers if str(t).strip()})
    prices: dict[str, pd.DataFrame] = {}
    failed_batches: list[dict[str, Any]] = []
    for start in range(0, len(normalized), batch_size):
        batch = normalized[start : start + batch_size]
        try:
            raw = yf.download(
                tickers=batch,
                period=period,
                interval="1d",
                auto_adjust=False,
                actions=False,
                group_by="column",
                threads=True,
                progress=False,
                timeout=30,
            )
            prices.update(_split_yfinance_download(raw, batch))
        except Exception as exc:  # network/provider errors must be reported, not hidden
            failed_batches.append({"start": start, "count": len(batch), "error": type(exc).__name__})
    diagnostics = {
        "source": "yfinance",
        "requested": len(normalized),
        "received": len(prices),
        "coverage": len(prices) / len(normalized) if normalized else 0.0,
        "failed_batches": failed_batches,
    }
    return prices, diagnostics


def compute_price_features(frame: pd.DataFrame, benchmark: pd.Series | None = None) -> dict[str, float | None]:
    f = _normalize_frame(frame)
    close = pd.to_numeric(f["close"], errors="coerce").dropna()
    high = pd.to_numeric(f["high"], errors="coerce")
    low = pd.to_numeric(f["low"], errors="coerce")
    volume = pd.to_numeric(f["volume"], errors="coerce")
    if len(close) < 30:
        return {}
    latest = float(close.iloc[-1])
    prev = close.shift(1)
    tr = pd.concat([(high - low), (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    out = {
        "price": finite_or_none(latest),
        "adr_pct": finite_or_none(tr.rolling(20).mean().iloc[-1] / latest * 100 if latest else np.nan),
        "dollar_volume_20d": finite_or_none((close * volume).rolling(20).mean().iloc[-1]),
        "volume_ratio_20d": finite_or_none(volume.rolling(5).mean().iloc[-1] / volume.rolling(20).mean().iloc[-1]),
        "distance_52w_high_pct": finite_or_none((latest / close.tail(252).max() - 1) * 100),
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
