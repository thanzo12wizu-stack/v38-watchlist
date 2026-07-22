from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .utils import finite_or_none


def _normalize_frame(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
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
    return {str(t).upper(): _normalize_frame(f) for t, f in obj.items() if isinstance(f, pd.DataFrame) and not f.empty}


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
    tr = pd.concat([(high-low), (high-prev).abs(), (low-prev).abs()], axis=1).max(axis=1)
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
        stock_ret = close.iloc[-1] / close.iloc[-window-1] - 1
        bench_ret = b.iloc[-1] / b.iloc[-window-1] - 1 if b is not None and len(b) > window else 0
        raw = stock_ret - bench_ret
        out[f"rs_raw_{window}"] = finite_or_none(raw)
        if len(close) > window + 21:
            prior = close.iloc[-22] / close.iloc[-window-22] - 1
            prior_b = b.iloc[-22] / b.iloc[-window-22] - 1 if b is not None and len(b) > window + 21 else 0
            out[f"rs_change_raw_{window}"] = finite_or_none(raw - (prior - prior_b))
    return out
