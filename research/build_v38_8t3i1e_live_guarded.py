#!/usr/bin/env python3
"""Guarded acquisition layer for the researched 8T+3I+1E live candidate builder.

This module deliberately does not change any strategy calculation.  It imports
``build_v38_8t3i1e_live`` as the canonical calculation engine and only hardens
its market-data acquisition path:

1. Download the full requested universe once.
2. Retry every missing symbol individually, up to three times.
3. Rebuild the common OHLCV matrix.
4. Fail closed if even one requested symbol is still unresolved.

The purpose is to prevent incomplete cross-sectional RS ranks from silently
becoming a READY production candidate set.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import pandas as pd

import build_v38_8t3i1e_live as core

SCHEMA = "v38-8t3i1e-guarded-acquisition-1"
MAX_INDIVIDUAL_RETRIES = 3


def _common_symbols(ohlcv: dict[str, pd.DataFrame], requested: list[str]) -> list[str]:
    return [
        s
        for s in requested
        if all(s in ohlcv[k].columns and ohlcv[k][s].notna().any() for k in ("open", "high", "low", "close", "volume"))
    ]


def _merge_symbol(base: dict[str, pd.DataFrame], extra: dict[str, pd.DataFrame], symbol: str) -> None:
    for key in ("open", "high", "low", "close", "volume"):
        if symbol not in extra[key].columns or not extra[key][symbol].notna().any():
            continue
        s = extra[key][symbol].copy()
        if base[key].empty:
            base[key] = pd.DataFrame({symbol: s})
        else:
            base[key] = base[key].drop(columns=[symbol], errors="ignore").join(s.rename(symbol), how="outer")
        base[key] = core._normalize(base[key])


def download_guarded(
    symbols: list[str],
    start: str,
    end: str,
    batch_size: int = 100,
    max_individual_retries: int = MAX_INDIVIDUAL_RETRIES,
    sleep_seconds: float = 1.0,
) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    requested = list(dict.fromkeys(symbols))
    ohlcv, initial_quality = core.download_adjusted_ohlcv(requested, start, end, batch_size)
    initial_common = _common_symbols(ohlcv, requested)
    missing = [s for s in requested if s not in set(initial_common)]
    recovered: list[str] = []
    retry_log: list[dict[str, Any]] = []

    for symbol in missing:
        recovered_this_symbol = False
        last_quality: dict[str, Any] = {}
        for attempt in range(1, max_individual_retries + 1):
            extra, q = core.download_adjusted_ohlcv([symbol], start, end, 1)
            last_quality = dict(q or {})
            ok = symbol in _common_symbols(extra, [symbol])
            retry_log.append({
                "ticker": symbol,
                "attempt": attempt,
                "success": bool(ok),
                "quality": last_quality,
            })
            if ok:
                _merge_symbol(ohlcv, extra, symbol)
                recovered.append(symbol)
                recovered_this_symbol = True
                break
            if attempt < max_individual_retries and sleep_seconds > 0:
                time.sleep(sleep_seconds)
        if not recovered_this_symbol:
            print(
                "8T3I_GUARD_UNRESOLVED "
                + json.dumps({"ticker": symbol, "last_quality": last_quality}, ensure_ascii=False),
                flush=True,
            )

    final_common = _common_symbols(ohlcv, requested)
    final_set = set(final_common)
    unresolved = [s for s in requested if s not in final_set]
    for key in ohlcv:
        ohlcv[key] = ohlcv[key].reindex(columns=final_common)

    quality = {
        "schema": SCHEMA,
        "requested": len(requested),
        "initial_downloaded_common": len(initial_common),
        "initial_coverage": len(initial_common) / max(1, len(requested)),
        "initial_failed_batches": int(initial_quality.get("failed_batches") or 0),
        "initial_missing": missing,
        "individual_retry_limit": int(max_individual_retries),
        "recovered_individually": recovered,
        "recovered_count": len(recovered),
        "unresolved": unresolved,
        "unresolved_count": len(unresolved),
        "downloaded_common": len(final_common),
        "coverage": len(final_common) / max(1, len(requested)),
        "complete_universe": len(unresolved) == 0,
        "retry_log": retry_log,
    }
    return ohlcv, quality


def build_guarded_live_state(
    root: Path,
    asof: str,
    *,
    batch_size: int = 100,
    lookback_days: int = 2200,
    max_individual_retries: int = MAX_INDIVIDUAL_RETRIES,
    sleep_seconds: float = 1.0,
) -> dict[str, Any]:
    target = pd.Timestamp(asof).normalize()
    symbols, bio = core._read_universe(root / "universe.csv")
    start = str((target - pd.Timedelta(days=lookback_days)).date())
    end = str((target + pd.Timedelta(days=1)).date())
    ohlcv, quality = download_guarded(
        symbols,
        start,
        end,
        batch_size,
        max_individual_retries=max_individual_retries,
        sleep_seconds=sleep_seconds,
    )
    if not quality["complete_universe"]:
        raise RuntimeError(
            "8T3I_FAIL_CLOSED_UNRESOLVED_SYMBOLS "
            + json.dumps({
                "unresolved_count": quality["unresolved_count"],
                "unresolved": quality["unresolved"],
                "coverage": quality["coverage"],
            }, ensure_ascii=False, sort_keys=True)
        )
    if target not in ohlcv["close"].index:
        raise RuntimeError(f"8T3I_ASOF_MARKET_SESSION_REQUIRED {target.date()}")
    state = core.build_state(ohlcv, bio, str(target.date()), quality)
    state["acquisition_guard"] = {
        "status": "PASS",
        "policy": "FULL_UNIVERSE_THEN_INDIVIDUAL_RETRY3_THEN_FAIL_CLOSED",
        "complete_universe_required": True,
        "unresolved_count": 0,
    }
    return state


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--asof", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--batch-size", type=int, default=100)
    ap.add_argument("--lookback-days", type=int, default=2200)
    ap.add_argument("--individual-retries", type=int, default=MAX_INDIVIDUAL_RETRIES)
    ap.add_argument("--retry-sleep", type=float, default=1.0)
    a = ap.parse_args()

    state = build_guarded_live_state(
        Path(a.root),
        a.asof,
        batch_size=a.batch_size,
        lookback_days=a.lookback_days,
        max_individual_retries=a.individual_retries,
        sleep_seconds=a.retry_sleep,
    )
    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(core._safe(state), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        "8T3I_GUARDED_READY "
        + json.dumps(core._safe({
            "asof": state["asof"],
            "rows": len(state["candidates"]),
            "source_counts": state["first11_source_counts"],
            "quality": state["quality"],
            "guard": state["acquisition_guard"],
        }), ensure_ascii=False),
        flush=True,
    )


if __name__ == "__main__":
    main()
