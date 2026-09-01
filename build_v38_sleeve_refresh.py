#!/usr/bin/env python3
"""Run the audited sleeve builder with a narrow Normal-price fallback.

The underlying strategy and Reset universe are unchanged. Only small Normal
Stock OHLC requests (<=50 symbols) get a crumb-free Yahoo Chart retry when
`yfinance` loses a symbol or its shared sqlite/cookie state locks. The large
Reset download keeps the original bulk path so this wrapper cannot explode into
thousands of per-symbol fallback requests.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

import build_v38_sleeve_live as live
from build_v38_tqqq_live import download_yahoo_chart

_BASE_DOWNLOAD = live.download_adjusted_ohlc


def _normalize(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out.index = pd.to_datetime(out.index)
    if out.index.tz is not None:
        out.index = out.index.tz_localize(None)
    out.index = out.index.normalize()
    return out.sort_index().replace([np.inf, -np.inf], np.nan)


def download_adjusted_ohlc_resilient(
    symbols: list[str], start: str, end: str, batch_size: int = 150
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    requested = list(dict.fromkeys(str(s).strip().upper() for s in symbols if str(s).strip()))

    # Never alter the large Reset route. Its partial-batch behavior is part of
    # the audited producer and individual fallback would multiply request load.
    if len(requested) > 50:
        return _BASE_DOWNLOAD(requested, start, end, batch_size)

    try:
        op, cl, quality = _BASE_DOWNLOAD(requested, start, end, batch_size)
    except RuntimeError as exc:
        if "SLEEVE_PRICE_DOWNLOAD_EMPTY" not in str(exc):
            raise
        op = pd.DataFrame()
        cl = pd.DataFrame()
        quality = {"requested": len(requested), "downloaded": 0, "failed_batches": 1}

    op = _normalize(op) if not op.empty else op
    cl = _normalize(cl) if not cl.empty else cl
    missing = [
        symbol for symbol in requested
        if symbol not in cl.columns or cl[symbol].dropna().empty
    ]
    fallback_used: list[str] = []
    fallback_failed: dict[str, str] = {}
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)

    for symbol in missing:
        try:
            frame = _normalize(download_yahoo_chart(symbol, start=start))
            frame = frame.loc[(frame.index >= start_ts) & (frame.index < end_ts)]
            if frame.empty:
                raise RuntimeError("empty fallback range")
            if "Open" not in frame.columns or "Close" not in frame.columns:
                raise RuntimeError("fallback missing OHLC")
            op[symbol] = pd.to_numeric(frame["Open"], errors="coerce")
            cl[symbol] = pd.to_numeric(frame["Close"], errors="coerce")
            if cl[symbol].dropna().empty:
                raise RuntimeError("fallback close empty")
            fallback_used.append(symbol)
            print(f"SLEEVE_NORMAL_FALLBACK {symbol} YAHOO_CHART", flush=True)
        except Exception as exc:
            fallback_failed[symbol] = f"{type(exc).__name__}: {exc}"
            print(
                f"SLEEVE_NORMAL_FALLBACK_FAILED {symbol} "
                f"{fallback_failed[symbol]}",
                flush=True,
            )

    if op.empty or cl.empty:
        raise RuntimeError("SLEEVE_NORMAL_PRICE_DOWNLOAD_EMPTY_AFTER_FALLBACK")

    quality = dict(quality or {})
    quality["fallback_used"] = fallback_used
    quality["fallback_failed"] = fallback_failed
    quality["downloaded"] = int(cl.shape[1])
    return _normalize(op), _normalize(cl), quality


def main() -> None:
    live.download_adjusted_ohlc = download_adjusted_ohlc_resilient
    live.main()


if __name__ == "__main__":
    main()
