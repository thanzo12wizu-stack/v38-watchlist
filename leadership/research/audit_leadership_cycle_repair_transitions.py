from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import audit_leadership_cycle as lc
import audit_leadership_cycle_combinations as cb
import audit_ordinary_stock_market_mode_robustness as base


def recent_state(cond: pd.Series, n: int) -> pd.Series:
    return cond.shift(1).fillna(False).astype(int).rolling(n, min_periods=1).max().astype(bool)


def recent_event(ev: pd.Series, n: int) -> pd.Series:
    return ev.shift(1).fillna(False).astype(int).rolling(n, min_periods=1).max().astype(bool)


def event_pool(ev: pd.Series, cooldown: int = 5) -> pd.Series:
    dates = lc.eventize(ev, cooldown=cooldown)
    out = pd.Series(False, index=ev.index)
    if dates:
        out.loc[dates] = True
    return out


def build(sig: pd.DataFrame, breadth: pd.Series, nq: pd.Series) -> tuple[dict[str, tuple[pd.Series, str]], dict[str, pd.Series]]:
    f2h = (sig.f2 >= .40).fillna(False)
    f3h = (sig.f3 >= .60).fillna(False)
    exh = (sig.leader_temp <= 15.0).fillna(False)
    expansion = sig.run_health.astype(str).eq("expansion")

    gate = nq.isin(["Blue", "Green"]) & (breadth >= 50)
    attack = nq.isin(["Blue", "Green"]) & (breadth >= 60)

    f2_clear = (~f2h) & f2h.shift(1, fill_value=False)
    f3_clear = (~f3h) & f3h.shift(1, fill_value=False)
    exh_exit = (~exh) & exh.shift(1, fill_value=False)
    temp30_recover = (sig.leader_temp > 30.0) & (sig.leader_temp.shift(1) <= 30.0) & recent_state(exh, 40)
    expansion_on = expansion & ~expansion.shift(1, fill_value=False)
    gate_rec = gate & ~gate.shift(1, fill_value=False)
    attack_rec = attack & ~attack.shift(1, fill_value=False)

    pools = {
        "F2_CLEAR": event_pool(f2_clear),
        "F3_CLEAR": event_pool(f3_clear),
        "EXH_EXIT": event_pool(exh_exit),
        "TEMP30_RECOVER": event_pool(temp30_recover),
        "EXPANSION_ONSET": event_pool(expansion_on),
        "GATE_RECOVERY": event_pool(gate_rec),
        "ATTACK_RECOVERY": event_pool(attack_rec),
    }

    repair_count = (
        recent_event(f2_clear, 20).astype(int)
        + recent_event(f3_clear, 20).astype(int)
        + recent_event(exh_exit, 20).astype(int)
        + recent_event(expansion_on, 20).astype(int)
    )

    candidates = {
        "F2_CLEAR_GATE_ON": (f2_clear & gate, "F2_CLEAR"),
        "F3_CLEAR_GATE_ON": (f3_clear & gate, "F3_CLEAR"),
        "EXH_EXIT_GATE_ON": (exh_exit & gate, "EXH_EXIT"),
        "TEMP30_RECOVER_GATE_ON": (temp30_recover & gate, "TEMP30_RECOVER"),
        "F2_CLEAR_AFTER_EXH20": (f2_clear & recent_state(exh, 20), "F2_CLEAR"),
        "F3_CLEAR_AFTER_EXH20": (f3_clear & recent_state(exh, 20), "F3_CLEAR"),
        "EXPANSION_AFTER_F2_CLEAR20": (expansion_on & recent_event(f2_clear, 20), "EXPANSION_ONSET"),
        "EXPANSION_AFTER_F3_CLEAR20": (expansion_on & recent_event(f3_clear, 20), "EXPANSION_ONSET"),
        "GATE_RECOVERY_AFTER_F2_CLEAR20": (gate_rec & recent_event(f2_clear, 20), "GATE_RECOVERY"),
        "GATE_RECOVERY_AFTER_F3_CLEAR20": (gate_rec & recent_event(f3_clear, 20), "GATE_RECOVERY"),
        "GATE_RECOVERY_AFTER_EXH_EXIT20": (gate_rec & recent_event(exh_exit, 20), "GATE_RECOVERY"),
        "GATE_RECOVERY_AFTER_EXPANSION20": (gate_rec & recent_event(expansion_on, 20), "GATE_RECOVERY"),
        "GATE_REPAIR_2PLUS": (gate_rec & (repair_count >= 2), "GATE_RECOVERY"),
        "GATE_REPAIR_3PLUS": (gate_rec & (repair_count >= 3), "GATE_RECOVERY"),
        "ATTACK_REPAIR_2PLUS": (attack_rec & (repair_count >= 2), "ATTACK_RECOVERY"),
    }
    return candidates, pools


def apply_fdr(rows: list[dict[str, Any]]) -> None:
    for split in ("DISCOVERY", "CONFIRMATION"):
        ids = [i for i, r in enumerate(rows) if r["split"] == split and r["cooldown"] == 20]
        for key in ("matched_q60", "matched_xs60", "matched_mdd60", "matched_dd10_60"):
            p = [rows[i].get(key, {}).get("p_boot_two_sided") for i in ids]
            q = cb.bh_qvalues(p)
            for i, qq in zip(ids, q):
                rows[i][key]["bh_q"] = qq


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--output", required=True)
    ap.add_argument("--analysis-start", default="2016-01-04")
    ap.add_argument("--analysis-end", default="2026-08-31")
    ap.add_argument("--max-tickers", type=int, default=6000)
    ap.add_argument("--batch-size", type=int, default=75)
    args = ap.parse_args()

    root = Path(args.root); out = root / args.output; out.mkdir(parents=True, exist_ok=True)
    meta, matrices = base.build_inputs(root, args.analysis_start, args.analysis_end, args.max_tickers, args.batch_size)
    idx = pd.DatetimeIndex(meta["analysis_idx"])
    sig = lc.build_leadership_series(matrices).reindex(idx)
    breadth = meta["breadth"].reindex(idx)
    nq = meta["nq"]["nq_color"].reindex(idx)
    market = lc.download_market(str((idx.min() - pd.Timedelta(days=400)).date()), str((idx.max() + pd.Timedelta(days=100)).date()))

    candidates, pools = build(sig, breadth, nq)
    rows: list[dict[str, Any]] = []
    for name, (mask, pool_name) in candidates.items():
        for cd in (20, 40):
            dates = lc.eventize(mask, cooldown=cd)
            rows += cb.evaluate(name, dates, pool_name, pools[pool_name], sig, market, nq, breadth, cd)
    apply_fdr(rows)

    finalists = []
    for r in rows:
        if r["split"] != "CONFIRMATION" or r["cooldown"] != 20 or r.get("n", 0) < 8:
            continue
        d = next((x for x in rows if x["candidate"] == r["candidate"] and x["split"] == "DISCOVERY" and x["cooldown"] == 20), None)
        if not d or d.get("n", 0) < 8:
            continue
        reasons = []
        for key in ("matched_q60", "matched_xs60", "matched_mdd60"):
            a, b = r.get(key, {}), d.get(key, {})
            if a.get("mean_diff") is None or b.get("mean_diff") is None:
                continue
            same = np.sign(a["mean_diff"]) == np.sign(b["mean_diff"]) and np.sign(a["mean_diff"]) != 0
            ci = a.get("ci025"); hi = a.get("ci975"); excl = ci is not None and hi is not None and (ci > 0 or hi < 0)
            if same and excl and a.get("bh_q") is not None and a["bh_q"] <= .10:
                reasons.append({"metric": key, "confirmation": a, "discovery_diff": b["mean_diff"]})
        a, b = r.get("matched_dd10_60", {}), d.get("matched_dd10_60", {})
        if a.get("prob_diff") is not None and b.get("prob_diff") is not None:
            same = np.sign(a["prob_diff"]) == np.sign(b["prob_diff"]) and np.sign(a["prob_diff"]) != 0
            ci = a.get("ci025"); hi = a.get("ci975"); excl = ci is not None and hi is not None and (ci > 0 or hi < 0)
            if same and excl and a.get("bh_q") is not None and a["bh_q"] <= .10:
                reasons.append({"metric": "matched_dd10_60", "confirmation": a, "discovery_diff": b["prob_diff"]})
        if reasons:
            finalists.append({"candidate": r["candidate"], "reasons": reasons})

    result = {
        "status": "LEADERSHIP_REPAIR_TRANSITION_AUDIT_COMPLETE",
        "candidate_count": len(candidates),
        "method": "Repair/regeneration transitions only. Candidate is compared with matched controls drawn from the same base transition family, then Discovery/Confirmation direction, 95% bootstrap CI and BH FDR q<=0.10 are required.",
        "finalists": finalists,
        "decision": "Use only finalists as independent combination evidence; otherwise keep repair/regeneration descriptive only.",
    }
    (out / "repair_transition_results.json").write_text(json.dumps(lc.safe(rows), ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "summary_repair_transitions.json").write_text(json.dumps(lc.safe(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(lc.safe(result), ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
