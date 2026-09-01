#!/usr/bin/env python3
"""One-time exact replay of the missing 2026-08-31 Normal sleeve session.

Uses the persisted 2026-08-28 research seed and the Git-preserved audited
2026-08-31 companion state. No trading rule is changed; this only restores the
incremental state that failed to persist while the price route was broken.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from build_v38_sleeve_live import _normal_from_seed, advance_normal, download_adjusted_ohlc

TARGET_ASOF = "2026-08-31"


def main() -> None:
    seed = json.loads(Path("v38-normal-sleeve-seed.json").read_text(encoding="utf-8"))
    companion = json.loads(Path("/tmp/v38-live-state-20260831.json").read_text(encoding="utf-8"))
    if str(seed.get("asof")) != "2026-08-28":
        raise RuntimeError(f"UNEXPECTED_NORMAL_SEED_ASOF {seed.get('asof')}")
    if str(companion.get("asof")) != TARGET_ASOF:
        raise RuntimeError(f"HISTORICAL_COMPANION_ASOF_MISMATCH {companion.get('asof')}")
    if companion.get("market", {}).get("mode") != "STOP":
        raise RuntimeError(f"HISTORICAL_COMPANION_MODE_MISMATCH {companion.get('market', {}).get('mode')}")

    previous = _normal_from_seed(seed)
    symbols = sorted({str(p["symbol"]) for p in previous.get("positions", [])})
    start = "2026-08-27"
    end = "2026-09-01"
    op, cl, quality = download_adjusted_ohlc(symbols, start, end, batch_size=50)
    op = op.loc[op.index <= pd.Timestamp(TARGET_ASOF)]
    cl = cl.loc[cl.index <= pd.Timestamp(TARGET_ASOF)]
    normal = advance_normal(previous, companion, TARGET_ASOF, op, cl)
    if normal.get("status") != "READY" or normal.get("asof") != TARGET_ASOF:
        raise RuntimeError("NORMAL_RECOVERY_NOT_READY")
    normal["recovery"] = {
        "type": "EXACT_MISSING_SESSION_REPLAY",
        "from_asof": "2026-08-28",
        "to_asof": TARGET_ASOF,
        "companion_source": "git:c452b5faefac430d2376ab290709d33ee810d983:v38-live-state.json",
        "market_mode": companion.get("market", {}).get("mode"),
        "price_quality": quality,
        "rule_change": False,
    }

    payload = {
        "schema": "v38-sleeve-live-1",
        "asof": TARGET_ASOF,
        "status": "DATA REQUIRED",
        "reason": "NORMAL_RECOVERY_READY_RESET_REBUILD_REQUIRED",
        "normal_stock": normal,
        "rsi_reset": {"status": "DATA REQUIRED"},
        "recovery_note": "Normal 2026-08-31 restored exactly; canonical build must rebuild Reset and advance to current asof.",
    }
    Path("v38-sleeve-state.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"NORMAL_GAP_RECOVERY_READY asof={normal['asof']} positions={normal['position_count']} "
        f"desired_pct={normal['desired_pct']:.6f}",
        flush=True,
    )


if __name__ == "__main__":
    main()
