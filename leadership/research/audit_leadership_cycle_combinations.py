from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import audit_leadership_cycle as lc
import audit_leadership_cycle_robustness as rb
import audit_ordinary_stock_market_mode_robustness as base

DISC_END = lc.DISC_END
HORIZONS = (20, 40, 60)


def split_name(d: pd.Timestamp) -> str:
    return "DISCOVERY" if pd.Timestamp(d) <= DISC_END else "CONFIRMATION"


def add_market_outcomes(df: pd.DataFrame) -> pd.DataFrame:
    z = df.copy()
    for h in HORIZONS:
        q = pd.to_numeric(z.get(f"qqq_ret_{h}"), errors="coerce")
        s = pd.to_numeric(z.get(f"spy_ret_{h}"), errors="coerce")
        z[f"qqq_minus_spy_{h}"] = q - s
    return z


def bootstrap_diff(a: pd.Series, b: pd.Series, seed: int, reps: int = 10000) -> dict[str, Any]:
    aa = pd.to_numeric(a, errors="coerce").dropna().to_numpy(float)
    bb = pd.to_numeric(b, errors="coerce").dropna().to_numpy(float)
    out: dict[str, Any] = {"n_event": int(len(aa)), "n_control": int(len(bb))}
    if len(aa) < 5 or len(bb) < 5:
        return out
    rng = np.random.default_rng(seed)
    d = np.empty(reps, dtype=float)
    for i in range(reps):
        d[i] = rng.choice(aa, len(aa), replace=True).mean() - rng.choice(bb, len(bb), replace=True).mean()
    obs = float(aa.mean() - bb.mean())
    p2 = float(2.0 * min(np.mean(d <= 0), np.mean(d >= 0)))
    out.update({
        "mean_diff": obs,
        "ci025": float(np.quantile(d, .025)),
        "ci975": float(np.quantile(d, .975)),
        "prob_event_gt_control": float(np.mean(d > 0)),
        "p_boot_two_sided": min(1.0, p2),
    })
    return out


def bootstrap_binary_diff(a: pd.Series, b: pd.Series, cutoff: float, seed: int, reps: int = 10000) -> dict[str, Any]:
    aa = (pd.to_numeric(a, errors="coerce").dropna().to_numpy(float) <= cutoff).astype(float)
    bb = (pd.to_numeric(b, errors="coerce").dropna().to_numpy(float) <= cutoff).astype(float)
    out: dict[str, Any] = {"n_event": int(len(aa)), "n_control": int(len(bb))}
    if len(aa) < 5 or len(bb) < 5:
        return out
    rng = np.random.default_rng(seed)
    d = np.empty(reps, dtype=float)
    for i in range(reps):
        d[i] = rng.choice(aa, len(aa), replace=True).mean() - rng.choice(bb, len(bb), replace=True).mean()
    obs = float(aa.mean() - bb.mean())
    p2 = float(2.0 * min(np.mean(d <= 0), np.mean(d >= 0)))
    out.update({
        "event_prob": float(aa.mean()), "control_prob": float(bb.mean()),
        "prob_diff": obs, "ci025": float(np.quantile(d, .025)), "ci975": float(np.quantile(d, .975)),
        "p_boot_two_sided": min(1.0, p2),
    })
    return out


def bh_qvalues(pvals: list[float | None]) -> list[float | None]:
    valid = [(i, float(p)) for i, p in enumerate(pvals) if p is not None and np.isfinite(p)]
    if not valid:
        return [None] * len(pvals)
    valid.sort(key=lambda x: x[1])
    m = len(valid)
    qtmp = [0.0] * m
    running = 1.0
    for rank0 in range(m - 1, -1, -1):
        rank = rank0 + 1
        q = min(1.0, valid[rank0][1] * m / rank)
        running = min(running, q)
        qtmp[rank0] = running
    out: list[float | None] = [None] * len(pvals)
    for (slot, _), q in zip(valid, qtmp):
        out[slot] = q
    return out


def eventize_base(mask: pd.Series, cooldown: int) -> list[pd.Timestamp]:
    return lc.eventize(mask, cooldown=cooldown)


def recent(cond: pd.Series, n: int) -> pd.Series:
    return cond.shift(1).fillna(False).astype(int).rolling(n, min_periods=1).max().astype(bool)


def ordered_sequence_events(sig: pd.DataFrame, window: int = 60, cooldown: int = 40) -> list[pd.Timestamp]:
    f1 = (sig.f1 >= .30).fillna(False)
    f2 = (sig.f2 >= .40).fillna(False)
    f3 = (sig.f3 >= .60).fillna(False)
    exh = (sig.leader_temp <= 15.0).fillna(False)
    exh_cross = exh & ~exh.shift(1, fill_value=False)
    idx = sig.index
    hits: list[pd.Timestamp] = []
    last_pos = -10**9
    for pos, is_cross in enumerate(exh_cross.to_numpy(bool)):
        if not is_cross or pos - last_pos < cooldown:
            continue
        lo = max(0, pos - window)
        def first_pos(s: pd.Series) -> int | None:
            a = np.flatnonzero(s.iloc[lo:pos+1].to_numpy(bool))
            return (lo + int(a[0])) if len(a) else None
        p1, p2, p3 = first_pos(f1), first_pos(f2), first_pos(f3)
        if p1 is not None and p2 is not None and p3 is not None and p1 <= p2 <= p3 <= pos:
            hits.append(pd.Timestamp(idx[pos])); last_pos = pos
    return hits


def build_candidates(sig: pd.DataFrame, breadth: pd.Series, nq: pd.Series) -> tuple[dict[str, pd.Series], dict[str, pd.Series], dict[str, list[pd.Timestamp]]]:
    f1 = sig.f1 >= .30
    f2 = sig.f2 >= .40
    f3 = sig.f3 >= .60
    t15 = sig.leader_temp <= 15.0
    hot = sig.leader_temp >= 82.0
    expansion = sig.run_health.astype(str).eq("expansion")

    gate_on = nq.isin(["Blue", "Green"]) & (breadth >= 50)
    attack = nq.isin(["Blue", "Green"]) & (breadth >= 60)
    gate_recovery = gate_on & ~gate_on.shift(1, fill_value=False)
    attack_recovery = attack & ~attack.shift(1, fill_value=False)
    expansion_onset = expansion & ~expansion.shift(1, fill_value=False)

    states = {
        "F1_F3": f1 & f3,
        "F2_F3": f2 & f3,
        "F1_F2_F3": f1 & f2 & f3,
        "F1_TEMP15": f1 & t15,
        "F3_TEMP15": f3 & t15,
        "F1_F2_TEMP15": f1 & f2 & t15,
        "F2_F3_TEMP15": f2 & f3 & t15,
        "ALL4": f1 & f2 & f3 & t15,
        "FRAGILE_ATTACK_F1F2": attack & f1 & f2,
        "ATTACK_DAMAGE_F3": attack & f3,
        "HOT_ATTRITION": hot & f1,
        "EARLY_FADE_TEMP_GT30": f2 & (sig.leader_temp > 30),
        "LATE_FADE_TEMP15": f2 & t15,
        "EARLY_DAMAGE_TEMP_GT30": f3 & (sig.leader_temp > 30),
        "LATE_DAMAGE_TEMP15": f3 & t15,
        "F1RECENT40_TO_F2": f2 & recent(f1, 40),
        "F1RECENT40_TO_F3": f3 & recent(f1, 40),
        "F2RECENT40_TO_F3": f3 & recent(f2, 40),
        "F3RECENT40_TO_EXH": t15 & recent(f3, 40),
    }
    base_pools = {
        "ALL_DAYS": pd.Series(True, index=sig.index),
        "GATE_RECOVERY": gate_recovery,
        "ATTACK_RECOVERY": attack_recovery,
        "EXPANSION_ONSET": expansion_onset,
    }
    dated = {
        "GATE_RECOVERY_AFTER_EXH40": [d for d in eventize_base(gate_recovery, 10) if bool(recent(t15, 40).get(d, False))],
        "GATE_RECOVERY_AFTER_DAMAGE60": [d for d in eventize_base(gate_recovery, 10) if bool(recent(f3, 60).get(d, False))],
        "GATE_RECOVERY_AFTER_DAMAGE_EXH60": [d for d in eventize_base(gate_recovery, 10) if bool((recent(f3,60)&recent(t15,60)).get(d, False))],
        "ATTACK_RECOVERY_AFTER_EXH60": [d for d in eventize_base(attack_recovery, 10) if bool(recent(t15,60).get(d, False))],
        "EXPANSION_AFTER_EXH40": [d for d in eventize_base(expansion_onset, 10) if bool(recent(t15,40).get(d, False))],
        "EXPANSION_AFTER_DAMAGE40": [d for d in eventize_base(expansion_onset, 10) if bool(recent(f3,40).get(d, False))],
        "ORDERED_F1_F2_F3_EXH60": ordered_sequence_events(sig, 60, 40),
    }
    return states, base_pools, dated


def matched_controls_with_pool(sig: pd.DataFrame, events: list[pd.Timestamp], market: dict[str, pd.DataFrame], nq: pd.Series, breadth: pd.Series, cooldown: int, pool_mask: pd.Series) -> list[pd.Timestamp]:
    idx = sig.index.intersection(market["QQQ"].index)
    qqq = market["QQQ"]["Close"].reindex(idx)
    q20 = qqq.pct_change(20, fill_method=None)
    strata = pd.DataFrame(index=idx)
    strata["nq"] = nq.reindex(idx).astype(str)
    strata["bb"] = breadth.reindex(idx).map(rb.breadth_bucket)
    strata["q20"] = q20.map(rb.q20_bucket)
    strata["split"] = [split_name(d) for d in idx]
    allowed = pool_mask.reindex(idx).fillna(False).astype(bool)
    event_set = set(events)
    used: set[pd.Timestamp] = set()
    controls: list[pd.Timestamp] = []
    for e in events:
        if e not in strata.index:
            continue
        row = strata.loc[e]
        cand_idx = strata.index[allowed]
        cand = strata.loc[cand_idx]
        cand = cand[(cand.nq == row.nq) & (cand.bb == row.bb) & (cand.q20 == row.q20) & (cand.split == row.split)].index
        cands = [pd.Timestamp(d) for d in cand if d not in event_set and d not in used and abs((pd.Timestamp(d)-e).days) > cooldown]
        if not cands:
            continue
        cands.sort(key=lambda d: abs((d-e).days))
        pick = cands[0]; controls.append(pick); used.add(pick)
    return controls


def compact(z: pd.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {"n": int(len(z))}
    for h in HORIZONS:
        q = pd.to_numeric(z.get(f"qqq_ret_{h}"), errors="coerce").dropna()
        xs = pd.to_numeric(z.get(f"qqq_minus_spy_{h}"), errors="coerce").dropna()
        m = pd.to_numeric(z.get(f"qqq_mdd_{h}"), errors="coerce").dropna()
        out[f"qqq_ret{h}_mean"] = float(q.mean()) if len(q) else None
        out[f"qqq_ret{h}_median"] = float(q.median()) if len(q) else None
        out[f"qqq_minus_spy{h}_mean"] = float(xs.mean()) if len(xs) else None
        out[f"mdd{h}_mean"] = float(m.mean()) if len(m) else None
        out[f"dd10_{h}_prob"] = float((m <= -.10).mean()) if len(m) else None
    red = z.get("red_within_60", pd.Series(dtype=float)).dropna()
    out["red60_prob"] = float(red.astype(bool).mean()) if len(red) else None
    return out


def evaluate(name: str, events: list[pd.Timestamp], pool_name: str, pool_mask: pd.Series, sig: pd.DataFrame, market: dict[str, pd.DataFrame], nq: pd.Series, breadth: pd.Series, cooldown: int) -> list[dict[str, Any]]:
    controls = matched_controls_with_pool(sig, events, market, nq, breadth, cooldown, pool_mask)
    edf = add_market_outcomes(lc.outcome_rows(name, events, market["QQQ"], market["SPY"], nq))
    cdf = add_market_outcomes(lc.outcome_rows(name+"_CTRL", controls, market["QQQ"], market["SPY"], nq))
    rows: list[dict[str, Any]] = []
    for split in ("DISCOVERY", "CONFIRMATION"):
        e = edf[pd.to_datetime(edf.signal_date).map(split_name) == split] if len(edf) else edf
        c = cdf[pd.to_datetime(cdf.signal_date).map(split_name) == split] if len(cdf) else cdf
        seed = abs(hash((name, split, cooldown))) % (2**32)
        rec: dict[str, Any] = {"candidate": name, "pool": pool_name, "cooldown": cooldown, "split": split, **compact(e), "matched_n": int(len(c))}
        rec["matched_q60"] = bootstrap_diff(e.get("qqq_ret_60", pd.Series(dtype=float)), c.get("qqq_ret_60", pd.Series(dtype=float)), seed+1)
        rec["matched_xs60"] = bootstrap_diff(e.get("qqq_minus_spy_60", pd.Series(dtype=float)), c.get("qqq_minus_spy_60", pd.Series(dtype=float)), seed+2)
        rec["matched_mdd60"] = bootstrap_diff(e.get("qqq_mdd_60", pd.Series(dtype=float)), c.get("qqq_mdd_60", pd.Series(dtype=float)), seed+3)
        rec["matched_dd10_60"] = bootstrap_binary_diff(e.get("qqq_mdd_60", pd.Series(dtype=float)), c.get("qqq_mdd_60", pd.Series(dtype=float)), -.10, seed+4)
        rows.append(rec)
    return rows


def phase_contrast(name: str, a_mask: pd.Series, b_mask: pd.Series, sig: pd.DataFrame, market: dict[str, pd.DataFrame], nq: pd.Series, cooldown: int = 20) -> list[dict[str, Any]]:
    a_dates = lc.eventize(a_mask, cooldown=cooldown); b_dates = lc.eventize(b_mask, cooldown=cooldown)
    a = add_market_outcomes(lc.outcome_rows(name+"_A", a_dates, market["QQQ"], market["SPY"], nq))
    b = add_market_outcomes(lc.outcome_rows(name+"_B", b_dates, market["QQQ"], market["SPY"], nq))
    rows=[]
    for split in ("DISCOVERY","CONFIRMATION"):
        aa=a[pd.to_datetime(a.signal_date).map(split_name)==split] if len(a) else a
        bb=b[pd.to_datetime(b.signal_date).map(split_name)==split] if len(b) else b
        seed=abs(hash((name,split,cooldown)))%(2**32)
        rows.append({
            "contrast":name,"cooldown":cooldown,"split":split,"a_n":len(aa),"b_n":len(bb),
            "a":compact(aa),"b":compact(bb),
            "q60_a_minus_b":bootstrap_diff(aa.get("qqq_ret_60",pd.Series(dtype=float)),bb.get("qqq_ret_60",pd.Series(dtype=float)),seed+1),
            "xs60_a_minus_b":bootstrap_diff(aa.get("qqq_minus_spy_60",pd.Series(dtype=float)),bb.get("qqq_minus_spy_60",pd.Series(dtype=float)),seed+2),
            "mdd60_a_minus_b":bootstrap_diff(aa.get("qqq_mdd_60",pd.Series(dtype=float)),bb.get("qqq_mdd_60",pd.Series(dtype=float)),seed+3),
            "dd10_a_minus_b":bootstrap_binary_diff(aa.get("qqq_mdd_60",pd.Series(dtype=float)),bb.get("qqq_mdd_60",pd.Series(dtype=float)),-.10,seed+4),
        })
    return rows


def apply_fdr(rows: list[dict[str, Any]]) -> None:
    for split in ("DISCOVERY","CONFIRMATION"):
        ids=[i for i,r in enumerate(rows) if r["split"]==split and r["cooldown"]==20]
        for key in ("matched_q60","matched_xs60","matched_mdd60","matched_dd10_60"):
            p=[rows[i].get(key,{}).get("p_boot_two_sided") for i in ids]
            q=bh_qvalues(p)
            for i,qq in zip(ids,q): rows[i][key]["bh_q"] = qq


def main() -> None:
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",default="."); ap.add_argument("--output",required=True)
    ap.add_argument("--analysis-start",default="2016-01-04"); ap.add_argument("--analysis-end",default="2026-08-31")
    ap.add_argument("--max-tickers",type=int,default=6000); ap.add_argument("--batch-size",type=int,default=75)
    args=ap.parse_args(); root=Path(args.root); out=root/args.output; out.mkdir(parents=True,exist_ok=True)

    meta, matrices=base.build_inputs(root,args.analysis_start,args.analysis_end,args.max_tickers,args.batch_size)
    idx=pd.DatetimeIndex(meta["analysis_idx"])
    sig=lc.build_leadership_series(matrices).reindex(idx)
    breadth=meta["breadth"].reindex(idx); nq=meta["nq"]["nq_color"].reindex(idx)
    market=lc.download_market(str((idx.min()-pd.Timedelta(days=400)).date()),str((idx.max()+pd.Timedelta(days=100)).date()))

    states,pools,dated=build_candidates(sig,breadth,nq)
    rows: list[dict[str,Any]]=[]
    all_days=pools["ALL_DAYS"]
    for name,mask in states.items():
        for cd in (20,40):
            rows += evaluate(name,lc.eventize(mask,cooldown=cd),"ALL_DAYS",all_days,sig,market,nq,breadth,cd)
    dated_pool={
        "GATE_RECOVERY_AFTER_EXH40":"GATE_RECOVERY",
        "GATE_RECOVERY_AFTER_DAMAGE60":"GATE_RECOVERY",
        "GATE_RECOVERY_AFTER_DAMAGE_EXH60":"GATE_RECOVERY",
        "ATTACK_RECOVERY_AFTER_EXH60":"ATTACK_RECOVERY",
        "EXPANSION_AFTER_EXH40":"EXPANSION_ONSET",
        "EXPANSION_AFTER_DAMAGE40":"EXPANSION_ONSET",
        "ORDERED_F1_F2_F3_EXH60":"ALL_DAYS",
    }
    for name,dates in dated.items():
        pool_name=dated_pool[name]
        for cd in (20,40):
            # dated events already have their own transition cooldown; cd here controls matched-control separation.
            rows += evaluate(name,dates,pool_name,pools[pool_name],sig,market,nq,breadth,cd)
    apply_fdr(rows)

    f2=sig.f2>=.40; f3=sig.f3>=.60; t15=sig.leader_temp<=15.0
    contrasts=[]
    for cd in (20,40):
        contrasts += phase_contrast("F3_LATE_vs_EARLY","late", "early", sig, market, nq, cd) if False else []
        contrasts += phase_contrast("F3_TEMP15_vs_TEMP_GT30",f3&t15,f3&(sig.leader_temp>30),sig,market,nq,cd)
        contrasts += phase_contrast("F2_TEMP15_vs_TEMP_GT30",f2&t15,f2&(sig.leader_temp>30),sig,market,nq,cd)
        contrasts += phase_contrast("F3_WITH_F2_vs_WITHOUT_F2",f3&f2,f3&~f2,sig,market,nq,cd)

    (out/"combination_results.json").write_text(json.dumps(lc.safe(rows),ensure_ascii=False,indent=2),encoding="utf-8")
    (out/"phase_contrasts.json").write_text(json.dumps(lc.safe(contrasts),ensure_ascii=False,indent=2),encoding="utf-8")
    pd.DataFrame([{k:v for k,v in r.items() if not isinstance(v,dict)} for r in rows]).to_csv(out/"combination_index.csv",index=False)

    # Compact finalist list: confirmation, cd20, n>=8, direction agrees with discovery,
    # and either nominal 95% matched CI excludes zero or BH q <= .10 on a primary metric.
    finalists=[]
    conf=[r for r in rows if r["split"]=="CONFIRMATION" and r["cooldown"]==20 and r.get("n",0)>=8]
    for r in conf:
        d=next((x for x in rows if x["candidate"]==r["candidate"] and x["split"]=="DISCOVERY" and x["cooldown"]==20),None)
        if not d or d.get("n",0)<8: continue
        reasons=[]
        for key in ("matched_q60","matched_xs60","matched_mdd60","matched_dd10_60"):
            rr=r.get(key,{}); dd=d.get(key,{})
            if rr.get("mean_diff") is not None and dd.get("mean_diff") is not None:
                same=np.sign(rr["mean_diff"])==np.sign(dd["mean_diff"]) and np.sign(rr["mean_diff"])!=0
                ci=rr.get("ci025"); hi=rr.get("ci975"); excl=(ci is not None and hi is not None and (ci>0 or hi<0))
                q=rr.get("bh_q"); fdr=(q is not None and q<=.10)
                if same and (excl or fdr): reasons.append({"metric":key,"confirmation":rr,"discovery_diff":dd.get("mean_diff")})
            elif key=="matched_dd10_60" and rr.get("prob_diff") is not None and dd.get("prob_diff") is not None:
                same=np.sign(rr["prob_diff"])==np.sign(dd["prob_diff"]) and np.sign(rr["prob_diff"])!=0
                ci=rr.get("ci025"); hi=rr.get("ci975"); excl=(ci is not None and hi is not None and (ci>0 or hi<0))
                q=rr.get("bh_q"); fdr=(q is not None and q<=.10)
                if same and (excl or fdr): reasons.append({"metric":key,"confirmation":rr,"discovery_diff":dd.get("prob_diff")})
        if reasons: finalists.append({"candidate":r["candidate"],"reasons":reasons,"confirmation":{k:r.get(k) for k in ("n","qqq_ret60_mean","qqq_minus_spy60_mean","mdd60_mean","dd10_60_prob","red60_prob")},"discovery_n":d.get("n")})

    summary={
        "status":"LEADERSHIP_COMBINATION_AUDIT_COMPLETE",
        "prespecified_candidate_count":len(states)+len(dated),
        "method":"Fixed economic combinations; Discovery/Confirmation; 20/40 cooldown; controls matched on NQSAR color, stock breadth bucket, QQQ trailing-20d bucket and same split. Recovery/expansion candidates are matched only to the same type of recovery/expansion transition. BH FDR is applied across cd20 candidates per split/metric.",
        "finalists":finalists,
        "caution":"Exploratory research branch only. No production rule change is authorized. Current-universe survivorship remains.",
    }
    (out/"summary_combinations.json").write_text(json.dumps(lc.safe(summary),ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(lc.safe(summary),ensure_ascii=False,indent=2),flush=True)

if __name__=="__main__": main()
