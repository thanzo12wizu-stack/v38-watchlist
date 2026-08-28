from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from research.rulebook import audit_integrated_allocation as base
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
    if isinstance(x, pd.Timestamp):
        return x.isoformat()
    return x


def annual_table(dailies: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    years = range(v2.ANALYSIS_START.year, v2.ANALYSIS_END.year + 1)
    for name, daily in dailies.items():
        ret = daily.nav.pct_change(fill_method=None).fillna(0.0)
        for year in years:
            q = ret[ret.index.year == year]
            if q.empty:
                continue
            m = base.metrics(q)
            rows.append({"strategy": name, "year": year, **m})
    return pd.DataFrame(rows)


def rolling_summary(daily: pd.DataFrame, window: int = 252) -> dict:
    r = daily.nav.pct_change(fill_method=None).fillna(0.0)
    gross = (1.0 + r).rolling(window).apply(np.prod, raw=True) - 1.0
    z = gross.dropna()
    if z.empty:
        return {"n": 0}
    return {
        "n": int(len(z)),
        "median_252d": float(z.median()),
        "p10_252d": float(z.quantile(0.10)),
        "p25_252d": float(z.quantile(0.25)),
        "positive_252d": float((z > 0).mean()),
        "worst_252d": float(z.min()),
        "best_252d": float(z.max()),
    }


def paired_block_bootstrap(a: pd.DataFrame, b: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, seed: int) -> dict:
    ar = a.nav.pct_change(fill_method=None).fillna(0.0)
    br = b.nav.pct_change(fill_method=None).fillna(0.0)
    z = pd.concat([ar.rename("a"), br.rename("b")], axis=1).loc[start:end].dropna()
    if len(z) < 252:
        return {"n": int(len(z))}
    arr = z.to_numpy(float)
    n = len(arr)
    block = 20
    starts = np.arange(0, max(1, n - block + 1))
    n_blocks = int(np.ceil(n / block))
    rng = np.random.default_rng(seed)
    deltas = np.empty(2000, dtype=float)
    years = n / 252.0
    for i in range(2000):
        chosen = rng.choice(starts, size=n_blocks, replace=True)
        x = np.concatenate([arr[int(s):int(s) + block] for s in chosen], axis=0)[:n]
        ea = float(np.prod(1.0 + x[:, 0]) ** (1.0 / years) - 1.0)
        eb = float(np.prod(1.0 + x[:, 1]) ** (1.0 / years) - 1.0)
        deltas[i] = ea - eb
    return {
        "n": int(n),
        "median_cagr_delta": float(np.median(deltas)),
        "p05_cagr_delta": float(np.quantile(deltas, 0.05)),
        "p95_cagr_delta": float(np.quantile(deltas, 0.95)),
        "prob_a_beats_b": float((deltas > 0).mean()),
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
    bg = frame.nq_color.isin(["Blue", "Green"])

    _, final_daily = v4.simulate_tiered(market, signal, frame, selective_n=4, allow_repair=False, active_trim=False)
    _, pa60_daily = ms.simulate_core(market, signal, v2.v1.permission_from_mask(frame, bg & (frame.stock_pa50 >= 0.60)), force_exit_red=True)
    _, nq_daily = ms.simulate_core(market, signal, v2.v1.permission_from_mask(frame, bg), force_exit_red=True)
    dailies = {"FINAL_N4_NO_REPAIR": final_daily, "ATTACK_ONLY_PA60": pa60_daily, "BASE_NQ_BG": nq_daily}

    annual = annual_table(dailies)
    annual.to_csv(out / "annual_metrics.csv", index=False)

    rolling_rows = []
    for name, daily in dailies.items():
        rolling_rows.append({"strategy": name, **rolling_summary(daily)})
    pd.DataFrame(rolling_rows).to_csv(out / "rolling_252d.csv", index=False)

    comparisons = []
    spans = {
        "ALL": (v2.ANALYSIS_START, v2.ANALYSIS_END),
        "DISCOVERY": (v2.ANALYSIS_START, v2.DISCOVERY_END),
        "CONFIRM": (v2.CONFIRM_START, v2.ANALYSIS_END),
    }
    seed = 700
    for opponent in ("ATTACK_ONLY_PA60", "BASE_NQ_BG"):
        for period, (a, b) in spans.items():
            comparisons.append({"candidate": "FINAL_N4_NO_REPAIR", "opponent": opponent, "period": period, **paired_block_bootstrap(final_daily, dailies[opponent], a, b, seed)})
            seed += 1
    pd.DataFrame(comparisons).to_csv(out / "paired_block_bootstrap.csv", index=False)

    pivot = annual.pivot(index="year", columns="strategy", values="end")
    year_rows = []
    for year, row in pivot.iterrows():
        if all(k in row.index for k in ("FINAL_N4_NO_REPAIR", "ATTACK_ONLY_PA60", "BASE_NQ_BG")):
            year_rows.append({
                "year": int(year),
                "final_return": float(row["FINAL_N4_NO_REPAIR"] - 1.0),
                "pa60_return": float(row["ATTACK_ONLY_PA60"] - 1.0),
                "nq_return": float(row["BASE_NQ_BG"] - 1.0),
                "final_minus_pa60": float(row["FINAL_N4_NO_REPAIR"] - row["ATTACK_ONLY_PA60"]),
                "final_minus_nq": float(row["FINAL_N4_NO_REPAIR"] - row["BASE_NQ_BG"]),
            })
    pd.DataFrame(year_rows).to_csv(out / "annual_return_differences.csv", index=False)

    summary = {
        "status": "NORMAL_STOCK_FINAL_ROBUSTNESS_V6",
        "candidate": "NQSAR Blue/Green; stock breadth >=60% full 12 slots; 50-60% max 4 slots; <50% or Yellow no new normal-stock entries; NQSAR Red full exit; no immediate breadth-downgrade trim; no Yellow repair entries",
        "comparators": ["Blue/Green + stock breadth >=60% full only", "Blue/Green only"],
        "tests": ["calendar-year metrics", "rolling 252-session returns", "paired 20-session block bootstrap by ALL/DISCOVERY/CONFIRM"],
        "threshold_policy": "No threshold changes or new search in V6.",
        "limitations": [
            "Normal-stock sleeve is a comparison reconstruction, not the missing exact production ledger.",
            "Current-universe survivorship bias remains in stock breadth and stock returns; the separate V5 57ETF audit is the independent breadth-state corroboration.",
            "2022+ is robustness confirmation, not pristine OOS.",
            "No RSI30, shallow, TQQQ, main, or dashboard changes.",
        ],
    }
    (out / "summary.json").write_text(json.dumps(safe(summary), ensure_ascii=False, indent=2), encoding="utf-8")
    print("NORMAL_STOCK_FINAL_ROBUSTNESS_V6_DONE", flush=True)


if __name__ == "__main__":
    main()
