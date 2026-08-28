from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from research.rulebook_v2 import audit_market_stop_reentry as ms
from research.rulebook_v3 import audit_custom_market_modes_v2 as v2
from research.rulebook_v3 import audit_normal_stock_tiered_modes_v4 as v4


def safe(x):
    if isinstance(x, dict):
        return {str(k): safe(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [safe(v) for v in x]
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, (np.floating, float)):
        z = float(x)
        return z if math.isfinite(z) else None
    return x


def period_extras(daily: pd.DataFrame, period: str) -> dict:
    spans = {
        "ALL": (v2.ANALYSIS_START, v2.ANALYSIS_END),
        "DISCOVERY": (v2.ANALYSIS_START, v2.DISCOVERY_END),
        "CONFIRM": (v2.CONFIRM_START, v2.ANALYSIS_END),
        "2018Q4": (pd.Timestamp("2018-10-01"), pd.Timestamp("2018-12-31")),
        "COVID2020": (pd.Timestamp("2020-02-19"), pd.Timestamp("2020-06-30")),
        "BEAR2022": (pd.Timestamp("2022-01-03"), pd.Timestamp("2022-12-30")),
    }
    a, b = spans[period]
    q = daily.loc[(daily.index >= a) & (daily.index <= b)]
    if q.empty:
        return {}
    return {
        "avg_exposure": float(q.exposure.mean()),
        "max_exposure": float(q.exposure.max()),
        "avg_positions": float(q.positions.mean()),
        "max_positions": int(q.positions.max()),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--output", required=True)
    ap.add_argument("--asof", default="2026-08-28")
    args = ap.parse_args()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    market, signal, frame = v2.build_frame(Path(args.root), args.asof)
    policies = [
        ("N4_REPAIR_ENTRY_ONLY", True, False),
        ("N4_NO_REPAIR_ENTRY_ONLY", False, False),
        ("N4_REPAIR_IMMEDIATE_TRIM", True, True),
        ("N4_NO_REPAIR_IMMEDIATE_TRIM", False, True),
    ]
    rows = []
    shares = []
    for name, repair, trim in policies:
        _meta, daily = v4.simulate_tiered(market, signal, frame, selective_n=4, allow_repair=repair, active_trim=trim)
        for period, vals in ms.period_metrics(daily).items():
            if period in ("ALL", "DISCOVERY", "CONFIRM", "2018Q4", "COVID2020", "BEAR2022"):
                rows.append({"rule": name, "period": period, **vals, **period_extras(daily, period)})
        shares.append({"rule": name, **v4.mode_shares(daily)})

    pd.DataFrame(rows).to_csv(out / "n4_repair_comparison.csv", index=False)
    pd.DataFrame(shares).to_csv(out / "mode_shares.csv", index=False)
    summary = {
        "status": "NORMAL_STOCK_N4_REPAIR_V4B",
        "scope": "normal stock only",
        "fixed_boundaries": {"attack_stock_pa50": 0.60, "selective_stock_pa50": [0.50, 0.60], "post_red_restart_stock_pa50": 0.50, "defense": "NQSAR Red"},
        "fixed_selective_capacity": "4 of 12 slots; each remains 1/12 sleeve NAV",
        "only_question": "whether Yellow/non-Red repair states with stock breadth >=50% may open the four-slot normal-stock sleeve, and whether mode downgrade should immediately trim",
        "note": "No threshold search. No RSI30, shallow, TQQQ, main, or dashboard changes.",
    }
    (out / "summary.json").write_text(json.dumps(safe(summary), ensure_ascii=False, indent=2), encoding="utf-8")
    print("NORMAL_STOCK_N4_REPAIR_V4B_DONE", flush=True)


if __name__ == "__main__":
    main()
