#!/usr/bin/env python3
"""Run the guarded V38 sleeve refresh with a narrow target-session OHLC fallback.

This does not change any trading rule.  The existing resilient downloader is
left untouched for RSI Reset / large-universe requests.  For the small Normal
Stock request only, a symbol whose completed target session is missing either
Open or Close is re-fetched through the existing Yahoo Chart fallback before
the audited sleeve builder runs.
"""
from __future__ import annotations

import math

import pandas as pd

import build_v38_sleeve_refresh as refresh

_BASE_RESILIENT = refresh.download_adjusted_ohlc_resilient


def _finite_positive(value: object) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and number > 0


def _target_valid(op: pd.DataFrame, cl: pd.DataFrame, symbol: str, target: pd.Timestamp) -> bool:
    try:
        return (
            target in op.index
            and target in cl.index
            and symbol in op.columns
            and symbol in cl.columns
            and _finite_positive(op.at[target, symbol])
            and _finite_positive(cl.at[target, symbol])
        )
    except Exception:
        return False


def download_adjusted_ohlc_live(
    symbols: list[str], start: str, end: str, batch_size: int = 150
):
    requested = list(dict.fromkeys(str(s).strip().upper() for s in symbols if str(s).strip()))
    op, cl, quality = _BASE_RESILIENT(requested, start, end, batch_size)

    # RSI Reset keeps the existing cache / batch-retry implementation exactly as-is.
    if len(requested) > refresh.RESET_LARGE_REQUEST_THRESHOLD:
        return op, cl, quality

    op = refresh._normalize(op) if not op.empty else op
    cl = refresh._normalize(cl) if not cl.empty else cl
    target = pd.Timestamp(end).normalize() - pd.Timedelta(days=1)
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    missing_target = [s for s in requested if not _target_valid(op, cl, s, target)]

    target_fallback_used: list[str] = []
    target_fallback_failed: dict[str, str] = {}
    for symbol in missing_target:
        try:
            frame = refresh._normalize(refresh.download_yahoo_chart(symbol, start=start))
            frame = frame.loc[(frame.index >= start_ts) & (frame.index < end_ts)]
            if target not in frame.index:
                raise RuntimeError(f"target session missing: {target.date()}")
            if "Open" not in frame.columns or "Close" not in frame.columns:
                raise RuntimeError("fallback missing OHLC")
            open_value = frame.at[target, "Open"]
            close_value = frame.at[target, "Close"]
            if not _finite_positive(open_value) or not _finite_positive(close_value):
                raise RuntimeError("fallback target OHLC invalid")

            fresh_op = pd.DataFrame({symbol: pd.to_numeric(frame["Open"], errors="coerce")})
            fresh_cl = pd.DataFrame({symbol: pd.to_numeric(frame["Close"], errors="coerce")})
            op = refresh._merge_non_null(op, fresh_op)
            cl = refresh._merge_non_null(cl, fresh_cl)
            target_fallback_used.append(symbol)
            print(f"SLEEVE_NORMAL_TARGET_FALLBACK {symbol} YAHOO_CHART {target.date()}", flush=True)
        except Exception as exc:
            target_fallback_failed[symbol] = f"{type(exc).__name__}: {exc}"
            print(
                f"SLEEVE_NORMAL_TARGET_FALLBACK_FAILED {symbol} "
                f"{target_fallback_failed[symbol]}",
                flush=True,
            )

    quality = dict(quality or {})
    quality["target_session"] = str(target.date())
    quality["target_fallback_used"] = target_fallback_used
    quality["target_fallback_failed"] = target_fallback_failed
    return refresh._normalize(op), refresh._normalize(cl), quality


def main() -> None:
    refresh.download_adjusted_ohlc_resilient = download_adjusted_ohlc_live
    refresh.main(continue_with_previous_ready=True)


if __name__ == "__main__":
    main()
