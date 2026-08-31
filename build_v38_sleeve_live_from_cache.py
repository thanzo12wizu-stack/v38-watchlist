#!/usr/bin/env python3
"""Run audited Normal/Reset live sleeves from the strict-LOO shared OHLC cache.

This removes the second full-universe Yahoo download from the daily workflow.
The underlying sleeve rules remain in build_v38_sleeve_live.py unchanged.
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd

import build_v38_sleeve_live as base

CACHE_PATH = Path(os.environ.get("V38_SHARED_PRICE_CACHE", "v38-shared-price-cache.pkl"))
_CACHE: dict | None = None


def _load_cache() -> dict:
    global _CACHE
    if _CACHE is None:
        if not CACHE_PATH.is_file():
            raise RuntimeError(f"SLEEVE_SHARED_PRICE_CACHE_REQUIRED {CACHE_PATH}")
        payload = pd.read_pickle(CACHE_PATH)
        if not isinstance(payload, dict) or payload.get("schema") != "v38-shared-price-cache-1":
            raise RuntimeError("SLEEVE_SHARED_PRICE_CACHE_SCHEMA")
        if not isinstance(payload.get("open"), pd.DataFrame) or not isinstance(payload.get("close"), pd.DataFrame):
            raise RuntimeError("SLEEVE_SHARED_PRICE_CACHE_FRAMES_REQUIRED")
        _CACHE = payload
    return _CACHE


def cached_adjusted_ohlc(
    symbols: list[str], start: str, end: str, batch_size: int = 150
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]]:
    payload = _load_cache()
    requested = list(dict.fromkeys(str(s).strip().upper() for s in symbols if str(s).strip()))
    source_open = payload["open"].copy()
    source_close = payload["close"].copy()
    for frame in (source_open, source_close):
        frame.index = pd.to_datetime(frame.index).tz_localize(None).normalize()
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    source_close = source_close.loc[(source_close.index >= start_ts) & (source_close.index < end_ts)]
    source_open = source_open.reindex(index=source_close.index)
    columns = [symbol for symbol in requested if symbol in source_close.columns]
    if not columns or source_close.empty:
        raise RuntimeError(
            f"SLEEVE_SHARED_PRICE_CACHE_EMPTY requested={len(requested)} rows={len(source_close)}"
        )
    close = source_close.reindex(columns=columns).replace([np.inf, -np.inf], np.nan)
    open_ = source_open.reindex(index=close.index, columns=columns).replace([np.inf, -np.inf], np.nan)
    usable = [symbol for symbol in columns if close[symbol].notna().any()]
    if not usable:
        raise RuntimeError("SLEEVE_SHARED_PRICE_CACHE_NO_USABLE_COLUMNS")
    close = close[usable]
    open_ = open_.reindex(columns=usable)
    quality: dict[str, object] = {
        "source": "STRICT_LOO_SHARED_CACHE",
        "requested": len(requested),
        "downloaded": len(usable),
        "rows": len(close),
        "failed_batches": 0,
        "cache_start": str(close.index.min().date()) if len(close) else None,
        "cache_end": str(close.index.max().date()) if len(close) else None,
        "cache_file": CACHE_PATH.name,
    }
    print(
        f"SLEEVE_SHARED_CACHE requested={len(requested)} usable={len(usable)} rows={len(close)}",
        flush=True,
    )
    return open_, close, quality


base.download_adjusted_ohlc = cached_adjusted_ohlc

if __name__ == "__main__":
    base.main()
