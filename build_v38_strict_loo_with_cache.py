#!/usr/bin/env python3
"""Run strict LOO while exporting the same Yahoo batch as a temporary OHLC cache.

The strict LOO calculation itself is unchanged.  This wrapper replaces only its
market-data downloader so the already-paid Yahoo request can also supply
split-adjusted Open/Close history to the Normal/RSI Reset sleeve builder later
in the same Actions job.
"""
from __future__ import annotations

import math
import os
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

import build_v38_strict_loo_live as base

CACHE_PATH = Path(os.environ.get("V38_SHARED_PRICE_CACHE", "v38-shared-price-cache.pkl"))


def _adjusted_open(part: pd.DataFrame) -> pd.Series | None:
    if "Open" not in part.columns:
        return None
    raw_open = pd.to_numeric(part["Open"], errors="coerce")
    if "Adj Close" in part.columns and "Close" in part.columns:
        adj_close = pd.to_numeric(part["Adj Close"], errors="coerce")
        raw_close = pd.to_numeric(part["Close"], errors="coerce").replace(0.0, np.nan)
        return raw_open * (adj_close / raw_close)
    return raw_open


def download_adjusted_close_with_cache(
    symbols: list[str], start: str, end: str, batch_size: int = 200
) -> tuple[pd.DataFrame, dict[str, object]]:
    requested = list(dict.fromkeys(symbols))
    close_frames: list[pd.DataFrame] = []
    open_frames: list[pd.DataFrame] = []
    failed_batches = 0

    for pos in range(0, len(requested), batch_size):
        batch = requested[pos:pos + batch_size]
        names = [base.yahoo_symbol(symbol) for symbol in batch]
        reverse = {base.yahoo_symbol(symbol): symbol for symbol in batch}
        try:
            raw = yf.download(
                names,
                start=start,
                end=end,
                auto_adjust=False,
                actions=False,
                progress=False,
                group_by="ticker",
                threads=True,
                timeout=30,
            )
        except Exception as exc:
            print(f"LOO_DOWNLOAD_BATCH_FAILED pos={pos} error={type(exc).__name__}", flush=True)
            failed_batches += 1
            continue
        if raw is None or raw.empty:
            failed_batches += 1
            continue

        close_cols: dict[str, pd.Series] = {}
        open_cols: dict[str, pd.Series] = {}
        if isinstance(raw.columns, pd.MultiIndex):
            level0 = set(str(x) for x in raw.columns.get_level_values(0))
            for name in names:
                if name not in level0:
                    continue
                part = raw[name]
                field = "Adj Close" if "Adj Close" in part.columns else (
                    "Close" if "Close" in part.columns else None
                )
                if field:
                    close_cols[reverse[name]] = pd.to_numeric(part[field], errors="coerce")
                op = _adjusted_open(part)
                if op is not None:
                    open_cols[reverse[name]] = op
        elif len(batch) == 1:
            field = "Adj Close" if "Adj Close" in raw.columns else (
                "Close" if "Close" in raw.columns else None
            )
            if field:
                close_cols[batch[0]] = pd.to_numeric(raw[field], errors="coerce")
            op = _adjusted_open(raw)
            if op is not None:
                open_cols[batch[0]] = op

        if close_cols:
            close_frames.append(pd.DataFrame(close_cols))
        if open_cols:
            open_frames.append(pd.DataFrame(open_cols))
        print(
            f"LOO_DOWNLOAD {min(pos + batch_size, len(requested))}/{len(requested)} "
            f"columns={sum(frame.shape[1] for frame in close_frames)}",
            flush=True,
        )

    if not close_frames:
        raise RuntimeError("Yahoo download returned no usable adjusted-close data")

    close = pd.concat(close_frames, axis=1)
    close = close.loc[:, ~close.columns.duplicated()].sort_index()
    close.index = pd.to_datetime(close.index).tz_localize(None).normalize()
    close = close.replace([np.inf, -np.inf], np.nan)

    if open_frames:
        open_ = pd.concat(open_frames, axis=1)
        open_ = open_.loc[:, ~open_.columns.duplicated()].sort_index()
        open_.index = pd.to_datetime(open_.index).tz_localize(None).normalize()
        open_ = open_.replace([np.inf, -np.inf], np.nan)
        open_ = open_.reindex(index=close.index, columns=close.columns)
    else:
        open_ = pd.DataFrame(index=close.index, columns=close.columns, dtype=float)

    quality: dict[str, object] = {
        "requested": len(requested),
        "downloaded": int(close.shape[1]),
        "rows": int(close.shape[0]),
        "failed_batches": failed_batches,
    }
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    pd.to_pickle(
        {
            "schema": "v38-shared-price-cache-1",
            "start": start,
            "end": end,
            "open": open_,
            "close": close,
            "quality": quality,
        },
        CACHE_PATH,
    )
    print(
        f"SHARED_PRICE_CACHE wrote={CACHE_PATH} rows={len(close)} cols={close.shape[1]} "
        f"open_nonnull={int(open_.notna().sum().sum())}",
        flush=True,
    )
    return close, quality


base.download_adjusted_close = download_adjusted_close_with_cache

if __name__ == "__main__":
    base.main()
