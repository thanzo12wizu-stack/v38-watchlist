#!/usr/bin/env python3
"""Run the audited sleeve builder with a narrow Normal-price fallback.

The underlying strategy and Reset universe are unchanged. Only small Normal
Stock OHLC requests (<=50 symbols) get a crumb-free Yahoo Chart retry when
`yfinance` loses a symbol or its shared sqlite/cookie state locks. The large
Reset download keeps the original bulk path so this wrapper cannot explode into
thousands of per-symbol fallback requests.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
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


def _reset_display_candidate(row: dict[str, Any]) -> bool:
    """Keep only strong, still-actionable Reset names in the published monitor."""
    status = str(row.get("status") or "")
    if status in {"ACTIVE_POSITION", "SIGNAL_TODAY_NEXT_OPEN"}:
        return True
    if status == "SIGNAL_OCCURRED" or row.get("current_theme_rs63_top3") is not True:
        return False
    try:
        days_left = int(row.get("signal_window_days_left"))
        distance = float(row.get("distance_to_30"))
    except (TypeError, ValueError):
        return False
    return days_left > 0 and math.isfinite(distance) and distance <= 10.0


def _filter_reset_monitor(path: Path) -> None:
    state = json.loads(path.read_text(encoding="utf-8"))
    reset = state.get("rsi_reset")
    if not isinstance(reset, dict) or not isinstance(reset.get("monitor"), list):
        return

    visible = [row for row in reset["monitor"] if isinstance(row, dict) and _reset_display_candidate(row)]
    reset["monitor"] = visible
    reset["monitor_summary"] = {
        "active_positions": sum(str(row.get("status") or "") == "ACTIVE_POSITION" for row in visible),
        "signal_today": sum(str(row.get("status") or "") == "SIGNAL_TODAY_NEXT_OPEN" for row in visible),
        "touched_wait_rise": sum(str(row.get("status") or "") == "RSI30_TOUCHED_WAIT_RISE" for row in visible),
        "within_5pt": sum(
            math.isfinite(float(row.get("distance_to_30"))) and float(row.get("distance_to_30")) <= 5.0
            for row in visible
            if row.get("distance_to_30") is not None
        ),
        "within_10pt": sum(
            math.isfinite(float(row.get("distance_to_30"))) and float(row.get("distance_to_30")) <= 10.0
            for row in visible
            if row.get("distance_to_30") is not None
        ),
        "watch_count": len(visible),
    }
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"SLEEVE_RESET_DISPLAY_FILTER {len(visible)} strong actionable names", flush=True)


def _output_path() -> Path:
    try:
        idx = sys.argv.index("--out")
        return Path(sys.argv[idx + 1])
    except (ValueError, IndexError):
        return Path("v38-sleeve-state.json")


def main() -> None:
    live.download_adjusted_ohlc = download_adjusted_ohlc_resilient
    live.main()
    _filter_reset_monitor(_output_path())


if __name__ == "__main__":
    main()
