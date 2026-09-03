from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import audit_major_leader_entry_delay as delay
import audit_ordinary_stock_market_mode_robustness as base
import audit_ordinary_stock_exit_trail as ex


def first_condition_stats(events: pd.DataFrame, cond: pd.DataFrame, close: pd.DataFrame) -> dict[str, Any]:
    gains: list[float] = []
    hits = 0
    for ev in events.itertuples(index=False):
        sym = str(ev.symbol)
        a = pd.Timestamp(ev.anchor_date)
        e = pd.Timestamp(ev.final_date)
        if sym not in cond.columns:
            continue
        z = cond.loc[(cond.index >= a) & (cond.index <= e), sym].fillna(False)
        h = z.index[z]
        if not len(h):
            continue
        d = pd.Timestamp(h[0])
        ap = delay.px(close, a, sym, None)
        dp = delay.px(close, d, sym, None)
        if ap is None or dp is None:
            continue
        hits += 1
        gains.append(float(dp / ap - 1.0))
    n = len(events)
    arr = np.asarray(gains, dtype=float) if gains else np.asarray([], dtype=float)
    return {
        "n": int(n),
        "reached": int(hits),
        "reach_rate": float(hits / n) if n else None,
        "within_20pct_all": float(np.sum(arr <= 0.20) / n) if n else None,
        "within_30pct_all": float(np.sum(arr <= 0.30) / n) if n else None,
        "within_50pct_all": float(np.sum(arr <= 0.50) / n) if n else None,
        "before_100pct_all": float(np.sum(arr < 1.00) / n) if n else None,
        "gain_median_reached": float(np.median(arr)) if len(arr) else None,
        "gain_p75_reached": float(np.quantile(arr, 0.75)) if len(arr) else None,
    }


def pack(events: pd.DataFrame, conditions: dict[str, pd.DataFrame], close: pd.DataFrame) -> dict[str, Any]:
    return {name: first_condition_stats(events, cond, close) for name, cond in conditions.items()}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--output", required=True)
    ap.add_argument("--analysis-start", default="2016-01-04")
    ap.add_argument("--analysis-end", default="2026-09-02")
    ap.add_argument("--max-tickers", type=int, default=6000)
    ap.add_argument("--batch-size", type=int, default=75)
    args = ap.parse_args()
    root = Path(args.root)
    out = root / args.output
    out.mkdir(parents=True, exist_ok=True)

    print("BUILD INPUTS", flush=True)
    meta, matrices = ex.build_inputs_ext(root, args.analysis_start, args.analysis_end, args.max_tickers, args.batch_size)
    close = matrices["close"]
    pool = delay.current_base_pool(root, matrices)
    rsm = delay.rs_matrices(close, pool)

    radar = (
        pool.fillna(False)
        & close.gt(matrices["sma50"]).fillna(False)
        & ((rsm[21] >= 85.0) | (rsm[42] >= 85.0) | (rsm[63] >= 85.0))
    ).fillna(False)
    rs21 = (pool & close.ge(close.ewm(span=21, adjust=False, min_periods=15).mean()) & (rsm[21] >= 85.0)).fillna(False)
    current_elig = matrices["new_eligible"].fillna(False)

    idx = pd.DatetimeIndex(meta["analysis_idx"])
    nq = meta["nq"].reindex(idx)
    breadth = meta["breadth"].reindex(idx)
    allowed = nq["nq_color"].isin(["Blue", "Green"]) & breadth.ge(50.0)
    allowed_df = pd.DataFrame(
        np.repeat(allowed.to_numpy(bool)[:, None], close.shape[1], axis=1),
        index=idx, columns=close.columns,
    ).reindex(close.index, fill_value=False)

    conditions = {
        "RADAR_IGNORE_MARKET": radar,
        "RADAR_WITH_CURRENT_MARKET_GATE": radar & allowed_df,
        "RS21_EARLY_IGNORE_MARKET": rs21,
        "RS21_EARLY_WITH_CURRENT_MARKET_GATE": rs21 & allowed_df,
        "CURRENT_ELIG_IGNORE_MARKET": current_elig,
        "CURRENT_ELIG_WITH_CURRENT_MARKET_GATE": current_elig & allowed_df,
    }

    events = delay.annual_leader_events(close, pool, idx, include_partial_2026=False)
    complete = events[events["complete_year"]].copy()
    top5 = complete[complete["top5"]]
    plus400 = complete[complete["cohort_400plus"]]
    plus200_400 = complete[complete["cohort_200_400"]]

    groups = {
        "TOP5_2016_2025": top5,
        "TOP5_DISC_2016_2020": top5[top5["year"] <= 2020],
        "TOP5_CONF_2021_2025": top5[top5["year"] >= 2021],
        "PLUS400_2016_2025": plus400,
        "PLUS200_400_2016_2025": plus200_400,
    }
    result = {
        "status": "EARLY_ENTRY_ORACLE_BOUNDS",
        "scope": "research only; ignores portfolio slot competition and therefore represents an optimistic upper bound for each signal/gate combination",
        "market_gate": "Blue/Green and ordinary-stock breadth>=50; Yellow/Red or breadth<50 blocks new Early entries",
        "target": "capture >=80% of major leaders, with majority entered by +25-30%",
        "groups": {name: pack(g, conditions, close) for name, g in groups.items()},
    }
    (out / "summary_early_entry_oracle_bounds.json").write_text(json.dumps(base.safe(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== EARLY_ENTRY_ORACLE_BOUNDS_JSON ===", flush=True)
    print(json.dumps(base.safe(result), ensure_ascii=False, indent=2), flush=True)
    print("=== END_EARLY_ENTRY_ORACLE_BOUNDS_JSON ===", flush=True)


if __name__ == "__main__":
    main()
