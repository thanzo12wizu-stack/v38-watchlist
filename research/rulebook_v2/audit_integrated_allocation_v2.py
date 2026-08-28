from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# The v1 audit reconstructs the expensive market/stock/TQQQ inputs.  This
# wrapper keeps that machinery but replaces the allocation layer with an
# explicit shared-capital allocator so no sleeve can push gross exposure
# above 100%.
from research.rulebook import audit_integrated_allocation as base


CAP_TOL = 1.0000001


def strategy_return_v2(
    data: pd.DataFrame,
    tqqq_target: pd.Series,
    core_cap: pd.Series,
    include_panic: bool,
) -> tuple[pd.Series, pd.DataFrame]:
    panic_exposure = (
        pd.to_numeric(data.panic_exposure, errors="coerce").fillna(0.0).clip(lower=0.0)
        if include_panic
        else pd.Series(0.0, index=data.index)
    )
    panic_return = data.panic_return if include_panic else pd.Series(0.0, index=data.index)
    raw_target = pd.to_numeric(tqqq_target, errors="coerce").fillna(0.0).clip(0.0, 1.0)
    cap = pd.to_numeric(core_cap, errors="coerce").fillna(0.0).clip(0.0, 1.0)

    # Capital priority for the final rulebook:
    # 1) already-open Panic Reset positions are honored;
    # 2) TQQQ receives its requested target only up to the remaining capital;
    # 3) Core12 receives the residual, subject to its regime cap.
    # This is operationally preferable to liquidating existing stock positions
    # merely because the TQQQ hierarchy asks for 100% on the same day.
    tqqq_effective = np.minimum(raw_target, np.maximum(0.0, 1.0 - panic_exposure))
    core_weight = np.minimum(cap, np.maximum(0.0, 1.0 - tqqq_effective - panic_exposure))

    core_turnover = (
        core_weight.diff().abs().fillna(0.0)
        * data.core_exposure.shift(1).fillna(0.0)
        * base.COST
    )
    tqqq_return = base.tqqq_contribution(data.tqqq_ret, tqqq_effective)
    total = core_weight * data.core_return - core_turnover + panic_return + tqqq_return
    total_exposure = core_weight * data.core_exposure + tqqq_effective + panic_exposure
    if bool((total_exposure > CAP_TOL).any()):
        raise RuntimeError(f"shared capital cap breached: {float(total_exposure.max()):.8f}")

    detail = pd.DataFrame(
        {
            "return": total,
            "core_weight": core_weight,
            "raw_tqqq_target": raw_target,
            "tqqq_weight": tqqq_effective,
            "panic_exposure": panic_exposure,
            "total_exposure": total_exposure,
        },
        index=data.index,
    )
    return total, detail


def build_strategies_v2(data: pd.DataFrame) -> tuple[dict[str, pd.Series], dict[str, pd.DataFrame]]:
    tactical = data.exact_rebound.astype(bool)
    normal_core_cap = pd.Series(0.70, index=data.index)

    # Direct allocation comparisons only change the exact Stage56 rebound
    # window. Outside it all candidates use the same CURRENT30 TQQQ hierarchy
    # and the same 70% Core12 cap. This isolates the user's allocation question.
    tq80_cap = pd.Series(np.where(tactical, 0.80, data.tq_current), index=data.index)
    balanced50 = pd.Series(np.where(tactical, 0.50, data.tq_current), index=data.index)
    stock20 = pd.Series(np.where(tactical, 0.20, data.tq_current), index=data.index)
    balanced_core_cap = pd.Series(np.where(tactical, 0.50, 0.70), index=data.index)
    stock_core_cap = pd.Series(np.where(tactical, 0.80, 0.70), index=data.index)

    specs = {
        "BASE_CORE70_CURRENT30": (data.tq_current, normal_core_cap, True),
        # Original Stage56 candidate is a floor, not an 80% maximum. Keep it as
        # a diagnostic so the rulebook does not silently conflate floor and cap.
        "EXACT_REBOUND_STAGE56_FLOOR80": (data.tq_exact80, normal_core_cap, True),
        "EXACT_REBOUND_TQQQ80_CAP": (tq80_cap, normal_core_cap, True),
        "EXACT_REBOUND_BALANCED50": (balanced50, balanced_core_cap, True),
        "EXACT_REBOUND_STOCK80": (stock20, stock_core_cap, True),
        "EXACT_REBOUND_TQQQ80_CAP_NO_PANIC": (tq80_cap, normal_core_cap, False),
        "AGGRESSIVE_TQQQ_NORMAL": (data.tq_aggressive, normal_core_cap, True),
    }

    returns: dict[str, pd.Series] = {}
    details: dict[str, pd.DataFrame] = {}
    for name, (target, cap, include_panic) in specs.items():
        returns[name], details[name] = strategy_return_v2(data, target, cap, include_panic)
    return returns, details


def output_path_from_argv() -> Path | None:
    try:
        i = sys.argv.index("--output")
    except ValueError:
        return None
    if i + 1 >= len(sys.argv):
        return None
    return Path(sys.argv[i + 1])


def patch_summary_after_run() -> None:
    out = output_path_from_argv()
    if out is None:
        return
    path = out / "summary.json"
    if not path.exists():
        return
    summary = json.loads(path.read_text(encoding="utf-8"))
    summary["status"] = "INTEGRATED_RULEBOOK_ALLOCATION_AUDIT_V2"
    summary["allocation_v2"] = {
        "shared_cap": "100% gross exposure hard cap",
        "capital_priority": "existing Panic Reset exposure first, then TQQQ up to residual capital, then Core12 up to its regime cap",
        "exact_rebound_comparison": {
            "base": "CURRENT30 + Core12 cap70",
            "stage56_floor80": "original Stage56 F80 target; can exceed 80% because F80 is a floor",
            "tqqq80_cap": "exact rebound TQQQ fixed at 80%; Core12 receives residual",
            "balanced50": "exact rebound TQQQ 50%; Core12 cap50",
            "stock80": "exact rebound TQQQ 20%; Core12 cap80",
        },
    }
    summary["definitions"]["capital_priority"] = summary["allocation_v2"]["capital_priority"]
    summary["limitations"].append(
        "V2 explicitly distinguishes the original Stage56 80% floor from the new direct-comparison 80% cap."
    )
    path.write_text(json.dumps(base.safe(summary), ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    base.strategy_return = strategy_return_v2
    base.build_strategies = build_strategies_v2
    base.main()
    patch_summary_after_run()
