from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from research.rulebook_v2 import audit_market_stop_reentry as ms
from research.rulebook_v3 import audit_custom_market_modes_v2 as v2


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
    if isinstance(x, pd.Timestamp):
        return x.isoformat()
    return x


def candidate_stats(frame: pd.DataFrame, mask: pd.Series, period: str) -> dict:
    if period == "DISCOVERY":
        pm = frame.index <= v2.DISCOVERY_END
    elif period == "CONFIRM":
        pm = frame.index >= v2.CONFIRM_START
    else:
        pm = pd.Series(True, index=frame.index)
    z = frame.loc[pd.Series(mask, index=frame.index).fillna(False) & pd.Series(pm, index=frame.index) & frame.basket_20.notna(), "basket_20"]
    if z.empty:
        return {"n": 0}
    gp = float(z[z > 0].sum())
    gl = float(-z[z < 0].sum())
    return {
        "n": int(len(z)),
        "mean20": float(z.mean()),
        "median20": float(z.median()),
        "win20": float((z > 0).mean()),
        "pf20": None if gl <= 0 else gp / gl,
        "p10_20": float(z.quantile(0.10)),
        "p90_20": float(z.quantile(0.90)),
    }


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
        "max_positions": int(q.positions.max()),
        "permission_rate": float(q.permission_signal.mean()),
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
    if "above50" not in frame.columns:
        raise RuntimeError("daily MC frame missing existing-dashboard above50 field")

    bg = frame.nq_color.isin(["Blue", "Green"])
    not_red = ~frame.nq_color.eq("Red")

    gate_masks = {
        "NQ_BG": bg,
        "ETF50_GE50": bg & (frame.above50 >= 50),
        "ETF50_GE60": bg & (frame.above50 >= 60),
        "ETF50_GE65": bg & (frame.above50 >= 65),
        "ETF50_GE70": bg & (frame.above50 >= 70),
        "ETF50_GE75": bg & (frame.above50 >= 75),
        "ETF50_GE80": bg & (frame.above50 >= 80),
        "ETF65_STOCK50": bg & (frame.above50 >= 65) & (frame.stock_pa50 >= 0.50),
        "ETF65_STOCK60": bg & (frame.above50 >= 65) & (frame.stock_pa50 >= 0.60),
        "ETF70_STOCK50": bg & (frame.above50 >= 70) & (frame.stock_pa50 >= 0.50),
        "ETF65_MC30": bg & (frame.above50 >= 65) & (frame.mc >= 30),
        "ETF65_MC35": bg & (frame.above50 >= 65) & (frame.mc >= 35),
    }

    candidate_rows = []
    gate_rows = []
    for name, mask in gate_masks.items():
        for period in ("DISCOVERY", "CONFIRM"):
            candidate_rows.append({"rule": name, "period": period, **candidate_stats(frame, mask, period)})
        _meta, daily = ms.simulate_core(market, signal, v2.v1.permission_from_mask(frame, mask), force_exit_red=True)
        for period, vals in ms.period_metrics(daily).items():
            if period in ("ALL", "DISCOVERY", "CONFIRM", "2018Q4", "COVID2020", "BEAR2022"):
                gate_rows.append({"rule": name, "period": period, **vals, **period_extras(daily, period)})

    restart_masks = {
        "RESTART_NQ_BG": bg,
        "RESTART_ETF50": not_red & (frame.above50 >= 50),
        "RESTART_ETF60": not_red & (frame.above50 >= 60),
        "RESTART_ETF65": not_red & (frame.above50 >= 65),
        "RESTART_ETF70": not_red & (frame.above50 >= 70),
    }
    restart_rows = []
    for name, trigger in restart_masks.items():
        _meta, daily = ms.simulate_core(market, signal, v2.v1.reentry_permission(frame, trigger), force_exit_red=True)
        for period, vals in ms.period_metrics(daily).items():
            if period in ("ALL", "DISCOVERY", "CONFIRM", "2018Q4", "COVID2020", "BEAR2022"):
                restart_rows.append({"rule": name, "period": period, **vals, **period_extras(daily, period)})

    corr = frame[["above50", "stock_pa50", "breadth_level", "mc"]].corr(method="spearman", min_periods=100)
    corr.to_csv(out / "breadth_correlations.csv")
    pd.DataFrame(candidate_rows).to_csv(out / "candidate_outcomes.csv", index=False)
    pd.DataFrame(gate_rows).to_csv(out / "gate_simulations.csv", index=False)
    pd.DataFrame(restart_rows).to_csv(out / "restart_simulations.csv", index=False)

    summary = {
        "status": "ETF_BREADTH_NORMAL_MODES_V5",
        "scope": "normal stock only",
        "existing_dashboard_field": "above50 from the existing 57ETF Market Conditions daily frame",
        "frozen_tests": {
            "attack_thresholds_pct": [50, 60, 65, 70, 75, 80],
            "restart_thresholds_pct": [50, 60, 65, 70],
            "cross_checks": ["ETF65+stock50", "ETF65+stock60", "ETF70+stock50", "ETF65+MC30", "ETF65+MC35"],
        },
        "purpose": "Check whether the normal-stock breadth effect survives on the existing 57ETF breadth measure and is not only a current-universe stock-breadth artifact.",
        "limitations": [
            "Normal-stock sleeve remains the comparison reconstruction, not the missing exact production ledger.",
            "Stock outcome universe still has current-universe survivorship bias, but the 57ETF breadth state itself avoids the 3596-stock historical membership problem.",
            "2022+ is robustness confirmation, not pristine OOS.",
            "No RSI30, shallow-pullback, TQQQ, main-branch, or dashboard rules are changed.",
        ],
    }
    (out / "summary.json").write_text(json.dumps(safe(summary), ensure_ascii=False, indent=2), encoding="utf-8")
    print("ETF_BREADTH_NORMAL_MODES_V5_DONE", flush=True)


if __name__ == "__main__":
    main()
