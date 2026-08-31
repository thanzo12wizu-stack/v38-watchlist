"""Targeted shared Yahoo cache for the two audited V38 live builders.

Python imports sitecustomize automatically.  This module deliberately does
nothing for every process except these exact entry points:
- build_v38_strict_loo_live.py: cache adjusted Open/Close from its existing
  full-universe Yahoo batches without changing the returned data.
- build_v38_sleeve_live.py: serve its later OHLC requests from that local cache
  instead of issuing a second full-universe Yahoo download.

The cache is temporary runner state and is never part of V38_ARTIFACTS/public
export.  Trading/ranking rules are untouched.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

CACHE_PATH = Path(os.environ.get("V38_SHARED_PRICE_CACHE", "v38-shared-price-cache.pkl"))
CACHE_SCHEMA = "v38-shared-price-cache-1"
TARGET_STRICT = "build_v38_strict_loo_live.py"
TARGET_SLEEVE = "build_v38_sleeve_live.py"


def _names(tickers: Any) -> list[str]:
    if isinstance(tickers, str):
        return [x for x in tickers.replace(",", " ").split() if x]
    try:
        return [str(x) for x in tickers]
    except TypeError:
        return [str(tickers)]


def _extract_adjusted_ohlc(raw, tickers):
    import numpy as np
    import pandas as pd

    names = _names(tickers)
    close_cols: dict[str, pd.Series] = {}
    open_cols: dict[str, pd.Series] = {}

    def add(name: str, part: pd.DataFrame) -> None:
        if "Adj Close" in part.columns:
            adj_close = pd.to_numeric(part["Adj Close"], errors="coerce")
        elif "Close" in part.columns:
            adj_close = pd.to_numeric(part["Close"], errors="coerce")
        else:
            return
        close_cols[name] = adj_close
        if "Open" in part.columns:
            raw_open = pd.to_numeric(part["Open"], errors="coerce")
            if "Adj Close" in part.columns and "Close" in part.columns:
                raw_close = pd.to_numeric(part["Close"], errors="coerce").replace(0.0, np.nan)
                open_cols[name] = raw_open * (adj_close / raw_close)
            else:
                open_cols[name] = raw_open

    if raw is None or getattr(raw, "empty", True):
        return pd.DataFrame(), pd.DataFrame()
    if isinstance(raw.columns, pd.MultiIndex):
        level0 = set(str(x) for x in raw.columns.get_level_values(0))
        for name in names:
            if name in level0:
                add(name, raw[name])
    elif len(names) == 1:
        add(names[0], raw)

    close = pd.DataFrame(close_cols)
    open_ = pd.DataFrame(open_cols)
    for frame in (close, open_):
        if len(frame.index):
            frame.index = pd.to_datetime(frame.index).tz_localize(None).normalize()
            frame.replace([np.inf, -np.inf], np.nan, inplace=True)
    return open_, close


def _merge_cache(raw, tickers, start=None, end=None) -> None:
    import pandas as pd

    open_new, close_new = _extract_adjusted_ohlc(raw, tickers)
    if close_new.empty:
        return
    payload = None
    if CACHE_PATH.is_file():
        try:
            candidate = pd.read_pickle(CACHE_PATH)
            if isinstance(candidate, dict) and candidate.get("schema") == CACHE_SCHEMA:
                payload = candidate
        except Exception:
            payload = None
    if payload is None:
        open_all = open_new
        close_all = close_new
        calls = 1
    else:
        old_open = payload.get("open")
        old_close = payload.get("close")
        if not isinstance(old_open, pd.DataFrame) or not isinstance(old_close, pd.DataFrame):
            open_all = open_new
            close_all = close_new
            calls = 1
        else:
            close_all = pd.concat([old_close, close_new], axis=1)
            close_all = close_all.loc[:, ~close_all.columns.duplicated(keep="last")].sort_index()
            open_all = pd.concat([old_open, open_new], axis=1)
            open_all = open_all.loc[:, ~open_all.columns.duplicated(keep="last")].sort_index()
            open_all = open_all.reindex(index=close_all.index, columns=close_all.columns)
            calls = int(payload.get("calls") or 0) + 1
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    pd.to_pickle(
        {
            "schema": CACHE_SCHEMA,
            "open": open_all,
            "close": close_all,
            "calls": calls,
            "start": str(start) if start is not None else None,
            "end": str(end) if end is not None else None,
        },
        CACHE_PATH,
    )


def _serve_cache(tickers, start=None, end=None, group_by="ticker", **kwargs):
    import pandas as pd

    if not CACHE_PATH.is_file():
        raise RuntimeError(f"SLEEVE_SHARED_PRICE_CACHE_REQUIRED {CACHE_PATH}")
    payload = pd.read_pickle(CACHE_PATH)
    if not isinstance(payload, dict) or payload.get("schema") != CACHE_SCHEMA:
        raise RuntimeError("SLEEVE_SHARED_PRICE_CACHE_SCHEMA")
    source_open = payload.get("open")
    source_close = payload.get("close")
    if not isinstance(source_open, pd.DataFrame) or not isinstance(source_close, pd.DataFrame):
        raise RuntimeError("SLEEVE_SHARED_PRICE_CACHE_FRAMES_REQUIRED")

    names = _names(tickers)
    start_ts = pd.Timestamp(start) if start is not None else source_close.index.min()
    end_ts = pd.Timestamp(end) if end is not None else source_close.index.max() + pd.Timedelta(days=1)
    close = source_close.loc[(source_close.index >= start_ts) & (source_close.index < end_ts)]
    columns = [name for name in names if name in close.columns]
    if not columns or close.empty:
        raise RuntimeError(
            f"SLEEVE_SHARED_PRICE_CACHE_EMPTY requested={len(names)} rows={len(close)}"
        )
    close = close.reindex(columns=columns)
    open_ = source_open.reindex(index=close.index, columns=columns)
    usable = [name for name in columns if close[name].notna().any()]
    if not usable:
        raise RuntimeError("SLEEVE_SHARED_PRICE_CACHE_NO_USABLE_COLUMNS")

    parts = {
        name: pd.DataFrame({"Open": open_[name], "Close": close[name]}, index=close.index)
        for name in usable
    }
    raw = pd.concat(parts, axis=1)
    print(
        f"SLEEVE_SHARED_CACHE requested={len(names)} usable={len(usable)} rows={len(close)}",
        flush=True,
    )
    return raw


def _install() -> None:
    script = Path(sys.argv[0]).name
    if script not in {TARGET_STRICT, TARGET_SLEEVE}:
        return
    import yfinance as yf

    if script == TARGET_STRICT:
        original = yf.download

        def caching_download(tickers, *args, **kwargs):
            raw = original(tickers, *args, **kwargs)
            _merge_cache(raw, tickers, kwargs.get("start"), kwargs.get("end"))
            return raw

        yf.download = caching_download
        print(f"V38_SHARED_PRICE_CACHE strict writer={CACHE_PATH}", flush=True)
    else:
        yf.download = _serve_cache
        print(f"V38_SHARED_PRICE_CACHE sleeve reader={CACHE_PATH}", flush=True)


_install()
