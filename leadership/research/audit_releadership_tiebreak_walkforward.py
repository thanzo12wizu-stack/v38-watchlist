from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import audit_ordinary_stock_market_mode_robustness as base
import audit_ordinary_stock_exit_trail as ex
import audit_ordinary_stock_theme_leave_one_out as loo
import audit_ordinary_stock_rebalance_vs_trail as rt
import audit_core_emerging_leader_mix as cem
import audit_core_emerging_hybrid_refine as hyb
import audit_core_releadership_priority as rel
import audit_core_releadership_falsification as fal
import audit_core_releadership_volume_decomposition as vd
import audit_five_year_leader_capture as lc


TIE_MODE = "V38"
PERSIST10: pd.DataFrame | None = None
ORIG_CLASSIFIER = rel.classifier
TIE_MODES = ("V38", "RS63", "THEME", "PRICE20", "PERSIST10", "CONSENSUS")
DEV_END = pd.Timestamp("2023-12-31")
OOS_START = pd.Timestamp("2024-01-01")


def safe(v: Any) -> Any:
    return base.safe(v)


def _v(frame: pd.DataFrame | None, d: pd.Timestamp, sym: str, default: float = np.nan) -> float:
    if frame is None:
        return default
    try:
        x = float(frame.at[d, sym])
        return x if np.isfinite(x) else default
    except Exception:
        return default


def build_persistence(matrices, features) -> pd.DataFrame:
    p = rel.PROFILES["BASE"]
    r = (
        (matrices["rs63"] >= p["rs63"])
        & (features["rs_acc_pct"] >= p["rs_acc_pct"])
        & rel.EXT["rs_turn"].astype(bool)
    )
    h = rel.EXT["high_ratio"] >= p["high_ratio"]
    t = (rel.EXT["theme_rank"] >= p["theme_rank"]) & (rel.EXT["theme_delta20"] >= p["theme_delta"])
    dv = (features["dvol_acc_pct"] >= p["dvol_acc_pct"]) & (rel.EXT["dvol_ratio20"] >= p["dvol_ratio"])
    sig = r.astype(np.int8) + h.astype(np.int8) + t.astype(np.int8) + dv.astype(np.int8) >= 3
    return sig.rolling(10, min_periods=1).sum().astype(np.float32)


def tie_values(d: pd.Timestamp, sym: str, cmap, matrices, features) -> dict[str, float]:
    return {
        "v38": float(cmap[sym].get("rank_score") or cmap[sym].get("stock_rs189") or 0.0),
        "rs63": _v(matrices["rs63"], d, sym, 0.0),
        "theme": _v(rel.EXT["theme_rank"], d, sym, 0.0),
        "price20": _v(features["ret20_pct"], d, sym, 0.0),
        "persist10": _v(PERSIST10, d, sym, 0.0),
    }


def choose_priority(d: pd.Timestamp, signal_syms: list[str], cmap, matrices, features) -> str | None:
    if not signal_syms:
        return None
    vals = {s: tie_values(d, s, cmap, matrices, features) for s in signal_syms}
    if TIE_MODE == "V38":
        return max(signal_syms, key=lambda s: (vals[s]["v38"], vals[s]["rs63"]))
    if TIE_MODE == "RS63":
        return max(signal_syms, key=lambda s: (vals[s]["rs63"], vals[s]["v38"]))
    if TIE_MODE == "THEME":
        return max(signal_syms, key=lambda s: (vals[s]["theme"], vals[s]["v38"]))
    if TIE_MODE == "PRICE20":
        return max(signal_syms, key=lambda s: (vals[s]["price20"], vals[s]["v38"]))
    if TIE_MODE == "PERSIST10":
        return max(signal_syms, key=lambda s: (vals[s]["persist10"], vals[s]["v38"]))
    if TIE_MODE == "CONSENSUS":
        df = pd.DataFrame(vals).T
        # Candidate-relative ranks only among already-valid THREE4 signals.
        score = pd.Series(0.0, index=df.index)
        for c in ("rs63", "theme", "price20", "persist10"):
            score += df[c].rank(pct=True, method="average")
        score /= 4.0
        best = score.max()
        tied = list(score.index[score == best])
        return max(tied, key=lambda s: vals[s]["v38"])
    raise ValueError(TIE_MODE)


def tie_classifier(d, matrices, peer_ctx, features, bucket, enhanced):
    cmap = cem.base_candidate_map(d, matrices, peer_ctx, bucket)
    core, emerging = [], []
    signal_syms: list[str] = []
    variant = rel.ACTIVE_VARIANT
    for sym in cmap:
        try:
            is_core = bool(features["core_mask"].at[d, sym])
            is_em = bool(features["emerging_mask"].at[d, sym])
        except Exception:
            continue
        if not (is_core or is_em):
            continue
        if is_core and vd.signal_ok(d, sym, matrices, features, variant):
            signal_syms.append(sym)

    priority = choose_priority(d, signal_syms, cmap, matrices, features)
    for sym, c0 in cmap.items():
        try:
            is_core = bool(features["core_mask"].at[d, sym])
            is_em = bool(features["emerging_mask"].at[d, sym])
        except Exception:
            continue
        if not (is_core or is_em):
            continue
        layer = "CORE" if is_core else "EMERGING"
        c = dict(c0)
        bs = float(c.get("rank_score") or c.get("stock_rs189") or 0.0)
        score = bs if layer == "CORE" else rel.mild_emerging_score(d, sym, c, matrices, features)
        is_sig = bool(layer == "CORE" and sym in signal_syms)
        tv = tie_values(d, sym, cmap, matrices, features)
        c.update({
            "relead_signal": is_sig,
            "relead_priority": bool(sym == priority),
            "relead_tie_mode": TIE_MODE,
            "relead_tie_v38": tv["v38"],
            "relead_tie_rs63": tv["rs63"],
            "relead_tie_theme": tv["theme"],
            "relead_tie_price20": tv["price20"],
            "relead_tie_persist10": tv["persist10"],
            "layer": layer,
            "layer_score": score + (1000.0 if sym == priority else 0.0),
            "dvol": _v(matrices["dvol"], d, sym),
            "dvol_pct": _v(features["dvol_pct"], d, sym),
            "rs63": _v(matrices["rs63"], d, sym),
            "rs_acc_pct": _v(features["rs_acc_pct"], d, sym),
        })
        (core if layer == "CORE" else emerging).append((sym, c))
    core.sort(key=lambda x: x[1]["layer_score"], reverse=True)
    emerging.sort(key=lambda x: x[1]["layer_score"], reverse=True)
    return core, emerging


def run_tie(meta, matrices, peer_ctx, features, mode: str, cost_bps: float = 0.0):
    global TIE_MODE
    TIE_MODE = mode
    rel.classifier = tie_classifier
    return vd.run_variant(meta, matrices, peer_ctx, features, f"THREE4_TIE_{mode}", "THREE4", "BASE", cost_bps)


def freeze_labels(out: Path, annual: pd.DataFrame, rolling: pd.DataFrame) -> dict[str, Any]:
    a = annual.copy(); r = rolling.copy()
    a["evaluation_set"] = "ANNUAL_LIQUID"; r["evaluation_set"] = "ROLLING_126_SUPERLEADER"
    cols = sorted(set(a.columns) | set(r.columns))
    f = pd.concat([a.reindex(columns=cols), r.reindex(columns=cols)], ignore_index=True)
    f = f.sort_values([c for c in ["evaluation_set", "period", "rank", "symbol", "start_date"] if c in f.columns], na_position="last").reset_index(drop=True)
    path = out / "leader_labels_frozen.csv"; f.to_csv(path, index=False)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    (out / "leader_labels_sha256.txt").write_text(digest + "\n", encoding="utf-8")
    return {"rows": int(len(f)), "sha256": digest}


def find_overlap(intervals: pd.DataFrame, sym: str, start: pd.Timestamp, peak: pd.Timestamp) -> pd.DataFrame:
    if intervals.empty:
        return intervals
    z = intervals.loc[intervals["symbol"].astype(str) == sym].copy()
    if z.empty:
        return z
    z["entry_date"] = pd.to_datetime(z["entry_date"]); z["exit_date"] = pd.to_datetime(z["exit_date"], errors="coerce")
    return z.loc[(z["entry_date"] <= peak) & (z["exit_date"].isna() | (z["exit_date"] > start))].sort_values("entry_date")


def annotate(leaders: pd.DataFrame, sim, matrices) -> pd.DataFrame:
    rows = []; close = matrices["close"]
    for _, rr in leaders.iterrows():
        z = dict(rr); sym = str(z["symbol"]); start = pd.Timestamp(z["start_date"]); peak = pd.Timestamp(z["peak_date"])
        ov = find_overlap(sim["intervals"], sym, start, peak); hit = not ov.empty
        z.update({"captured": bool(hit), "capture_date": pd.NaT, "capture_progress": np.nan, "remaining_upside": np.nan})
        if hit:
            ent = pd.Timestamp(ov.iloc[0]["entry_date"])
            if ent <= start:
                z["capture_date"] = start; z["capture_progress"] = 0.0; z["remaining_upside"] = float(z["peak_return"])
            else:
                ep = _v(close, ent, sym); sp = float(z["start_price"]); pp = float(z["peak_price"]); total = pp / sp - 1.0
                z["capture_date"] = ent
                if np.isfinite(ep) and ep > 0 and total > 0:
                    z["capture_progress"] = float((ep / sp - 1.0) / total)
                    z["remaining_upside"] = float(pp / ep - 1.0)
        rows.append(z)
    return pd.DataFrame(rows)


def slice_labels(df: pd.DataFrame, phase: str, top10: bool = False) -> pd.DataFrame:
    z = df.copy()
    start = pd.to_datetime(z["start_date"])
    if phase == "DEV": z = z.loc[start <= DEV_END]
    elif phase == "OOS": z = z.loc[start >= OOS_START]
    else: raise ValueError(phase)
    if top10 and "rank" in z:
        z = z.loc[pd.to_numeric(z["rank"], errors="coerce") <= 10]
    return z


def cap_stats(df: pd.DataFrame) -> dict[str, Any]:
    if df.empty: return {"n": 0, "hit_n": 0, "early_n": 0}
    hit = df["captured"].astype(bool); prog = pd.to_numeric(df["capture_progress"], errors="coerce")
    early = hit & (prog <= 1/3)
    return {
        "n": int(len(df)), "hit_n": int(hit.sum()), "hit_rate": float(hit.mean()),
        "early_n": int(early.sum()), "early_rate_all": float(early.mean()),
        "early_share_of_hits": float(early.sum()/hit.sum()) if hit.sum() else None,
        "median_capture_progress": float(prog.loc[hit].median()) if hit.any() else None,
    }


def eval_capture(ac: pd.DataFrame, rc: pd.DataFrame, phase: str) -> dict[str, Any]:
    return {
        "annual_top10": cap_stats(slice_labels(ac, phase, True)),
        "annual_top20": cap_stats(slice_labels(ac, phase, False)),
        "rolling126": cap_stats(slice_labels(rc, phase, False)),
    }


def dev_key(ev: dict[str, Any], mode: str) -> tuple:
    # Pre-registered lexicographic objective: leader timing first, then breadth.
    a = ev["annual_top10"]; r = ev["rolling126"]
    # Stable final tie-break prefers existing V38, then mode order.
    return (a["early_n"], r["early_n"], a["hit_n"], r["hit_n"], 1 if mode == "V38" else 0, -TIE_MODES.index(mode))


def period_metrics(eq: pd.Series, start: str, end: str | None = None) -> dict[str, Any]:
    x = eq.loc[eq.index >= pd.Timestamp(start)]
    if end: x = x.loc[x.index <= pd.Timestamp(end)]
    return base.metrics(x)


def paired_delta(a: pd.DataFrame, b: pd.DataFrame, phase: str, top10: bool = False) -> dict[str, Any]:
    aa = slice_labels(a, phase, top10).copy(); bb = slice_labels(b, phase, top10).copy()
    keys = ["leader_type", "period", "symbol", "start_date", "peak_date"]
    aa["start_date"] = pd.to_datetime(aa["start_date"]); aa["peak_date"] = pd.to_datetime(aa["peak_date"])
    bb["start_date"] = pd.to_datetime(bb["start_date"]); bb["peak_date"] = pd.to_datetime(bb["peak_date"])
    m = aa[keys + ["captured", "capture_progress"]].merge(bb[keys + ["captured", "capture_progress"]], on=keys, suffixes=("_sel", "_base"))
    hs = m["captured_sel"].astype(bool); hb = m["captured_base"].astype(bool)
    es = hs & (pd.to_numeric(m["capture_progress_sel"], errors="coerce") <= 1/3)
    eb = hb & (pd.to_numeric(m["capture_progress_base"], errors="coerce") <= 1/3)
    return {
        "n": int(len(m)),
        "hit_selected_only": int((hs & ~hb).sum()), "hit_baseline_only": int((hb & ~hs).sum()),
        "early_selected_only": int((es & ~eb).sum()), "early_baseline_only": int((eb & ~es).sum()),
    }


def named_diag(symbol: str, start: str, peak: str, mode: str, meta, matrices, peer_ctx, features, sim) -> dict[str, Any]:
    global TIE_MODE
    TIE_MODE = mode
    s0 = pd.Timestamp(start); p0 = pd.Timestamp(peak); sig_days=[]; winner_days=[]
    for d0 in meta["analysis_idx"]:
        d = pd.Timestamp(d0)
        if d < s0 or d > p0: continue
        color = str(meta["nq"].at[d,"nq_color"]) if d in meta["nq"].index and pd.notna(meta["nq"].at[d,"nq_color"]) else ""
        br = float(meta["breadth"].loc[d]) if d in meta["breadth"].index and pd.notna(meta["breadth"].loc[d]) else np.nan
        bucket = base.breadth_bucket(br)
        if color not in ("Blue","Green") or bucket <= 0: continue
        cmap = cem.base_candidate_map(d, matrices, peer_ctx, bucket)
        if symbol not in cmap: continue
        try:
            if not bool(features["core_mask"].at[d, symbol]): continue
        except Exception: continue
        variant = rel.Variant("X", "THREE4", "BASE")
        if not vd.signal_ok(d, symbol, matrices, features, variant): continue
        sig_days.append(d)
        valid=[]
        for x in cmap:
            try:
                if not bool(features["core_mask"].at[d,x]): continue
            except Exception: continue
            if vd.signal_ok(d,x,matrices,features,variant): valid.append(x)
        if choose_priority(d, valid, cmap, matrices, features) == symbol: winner_days.append(d)
    ent=sim["entries"]; actual=pd.DataFrame()
    if not ent.empty:
        actual=ent.loc[(ent["symbol"].astype(str)==symbol)&(pd.to_datetime(ent["signal_date"])>=s0)&(pd.to_datetime(ent["signal_date"])<=p0)]
    return {
        "symbol":symbol,"start":start,"peak":peak,"mode":mode,
        "signal_days":len(sig_days),"first_signal":str(sig_days[0].date()) if sig_days else None,
        "winner_days":len(winner_days),"first_winner":str(winner_days[0].date()) if winner_days else None,
        "actual_entry":not actual.empty,"actual_entry_date":str(pd.Timestamp(actual.iloc[0]["entry_date"]).date()) if not actual.empty else None,
    }


def main():
    global PERSIST10
    ap=argparse.ArgumentParser(); ap.add_argument("--root",default="."); ap.add_argument("--output",required=True)
    ap.add_argument("--analysis-start",default="2020-01-02"); ap.add_argument("--analysis-end",default="2026-09-02")
    ap.add_argument("--leader-start",default="2021-01-04"); ap.add_argument("--max-tickers",type=int,default=6000); ap.add_argument("--batch-size",type=int,default=75)
    args=ap.parse_args(); root=Path(args.root); out=root/args.output; out.mkdir(parents=True,exist_ok=True)

    print("BUILD PIT inputs",flush=True)
    meta,matrices=ex.build_inputs_ext(root,args.analysis_start,args.analysis_end,args.max_tickers,args.batch_size)
    peer_ctx=loo.build_leave_one_out_scores(root,matrices); features=cem.build_features(matrices)
    print(f"UNIVERSE downloaded={meta['downloaded']}",flush=True)

    print("FREEZE leader labels before tie-break simulations",flush=True)
    annual=lc.build_annual_leaders(matrices,pd.Timestamp(args.leader_start),pd.Timestamp(args.analysis_end))
    rolling=lc.build_rolling_superleaders(matrices,pd.Timestamp(args.leader_start),pd.Timestamp(args.analysis_end))
    freeze=freeze_labels(out,annual,rolling); annual.to_csv(out/"annual_leaders_frozen.csv",index=False); rolling.to_csv(out/"rolling_126_leaders_frozen.csv",index=False)
    print(f"LABEL_SHA256 {freeze['sha256']}",flush=True)

    print("BUILD fixed THREE4 signal features",flush=True)
    rel.EXT,_=rel.build_extended_features(root,matrices,features); rel.signal_ok=vd.signal_ok
    vd.PRICE_ACC_PCT=features["ret20_pct"].astype(np.float32); vd.PRICE_RATIO20=(matrices["close"]/matrices["close"].shift(20)).astype(np.float32)
    vd.SHARE_ACC_PCT,vd.SHARE_RATIO20=fal.build_share_volume_features(matrices,features); vd.BANNED_SYMBOLS=set()
    PERSIST10=build_persistence(matrices,features)

    print("SIM exact THREE4 V38 reference",flush=True)
    rel.classifier=ORIG_CLASSIFIER
    ref=vd.run_variant(meta,matrices,peer_ctx,features,"THREE4_REFERENCE","THREE4","BASE")

    sims={}; annual_caps={}; rolling_caps={}; evaluations={}
    for mode in TIE_MODES:
        print(f"SIM TIE {mode}",flush=True)
        sim=run_tie(meta,matrices,peer_ctx,features,mode); sims[mode]=sim
        ac=annotate(annual,sim,matrices); rc=annotate(rolling,sim,matrices)
        annual_caps[mode]=ac; rolling_caps[mode]=rc
        ac.to_csv(out/f"annual_capture_{mode}.csv",index=False); rc.to_csv(out/f"rolling126_capture_{mode}.csv",index=False)
        sim["equity"].rename("equity").to_csv(out/f"equity_{mode}.csv")
        sim["entries"].to_csv(out/f"entries_{mode}.csv",index=False); sim["trades"].to_csv(out/f"trades_{mode}.csv",index=False)
        evaluations[mode]={"DEV":eval_capture(ac,rc,"DEV"),"OOS":eval_capture(ac,rc,"OOS")}

    a,b=sims["V38"]["equity"].align(ref["equity"],join="inner")
    maxdiff=float(np.nanmax(np.abs(a.to_numpy(float)-b.to_numpy(float))))
    if maxdiff>1e-10: raise RuntimeError(f"V38 reproduction mismatch {maxdiff}")

    selected=max(TIE_MODES,key=lambda m:dev_key(evaluations[m]["DEV"],m))
    print(f"DEV_SELECTED {selected} key={dev_key(evaluations[selected]['DEV'],selected)}",flush=True)
    oos_eq_sel=sims[selected]["equity"].loc[lambda x:x.index>=OOS_START]
    oos_eq_base=sims["V38"]["equity"].loc[lambda x:x.index>=OOS_START]
    boot=base.bootstrap_block_win(oos_eq_sel,oos_eq_base,block=20,reps=5000,seed=97531)

    guard={
        "annual_top10_hit_not_worse": evaluations[selected]["OOS"]["annual_top10"]["hit_n"] >= evaluations["V38"]["OOS"]["annual_top10"]["hit_n"],
        "annual_top10_early_not_worse": evaluations[selected]["OOS"]["annual_top10"]["early_n"] >= evaluations["V38"]["OOS"]["annual_top10"]["early_n"],
        "rolling_hit_not_worse": evaluations[selected]["OOS"]["rolling126"]["hit_n"] >= evaluations["V38"]["OOS"]["rolling126"]["hit_n"],
        "rolling_early_not_worse": evaluations[selected]["OOS"]["rolling126"]["early_n"] >= evaluations["V38"]["OOS"]["rolling126"]["early_n"],
    }
    msel=period_metrics(sims[selected]["equity"],"2024-01-02"); mbase=period_metrics(sims["V38"]["equity"],"2024-01-02")
    guard["cagr_not_worse_by_gt_1pp"] = float(msel["cagr"]) >= float(mbase["cagr"]) - 0.01
    guard["mdd_not_worse_by_gt_2pp"] = float(msel["mdd"]) >= float(mbase["mdd"]) - 0.02
    pass_all=all(bool(x) for x in guard.values())

    named=[("NVDA","2023-12-22","2024-06-18"),("PLTR","2024-05-09","2024-11-07"),("CRWD","2023-08-18","2024-02-09"),("HOOD","2024-01-02","2024-12-31"),("MU","2025-07-01","2026-01-31")]
    result={
        "status":"RELEADERSHIP_TIEBREAK_WALKFORWARD_AUDIT",
        "analysis_window":{"start":args.analysis_start,"end":args.analysis_end,"leader_start":args.leader_start,"downloaded":int(meta["downloaded"])},
        "freeze":freeze,
        "design":{
            "signal":"THREE4 BASE fixed for every variant; only the tie-break among simultaneous valid Core Re-Leadership signals changes.",
            "dev":"2021-2023 leader labels select one tie-break by pre-registered lexicographic objective: annual Top10 early hits, rolling126 early hits, annual Top10 hits, rolling126 hits.",
            "oos":"2024-2026YTD is not used to reselect the tie-break. This is OOS for tie-break selection only, not a claim that the already-researched THREE4 signal itself is fully OOS.",
            "modes":list(TIE_MODES),
            "portfolio":"9 Core + 3 Emerging; SELECTIVE 3+1; one priority only on vacant Core fill; no forced sale; exits unchanged.",
        },
        "validation":{"v38_reproduction_max_abs_diff":maxdiff},
        "evaluations":evaluations,
        "dev_selected":selected,
        "selected_dev_key":list(dev_key(evaluations[selected]["DEV"],selected)),
        "oos_guardrails":guard,
        "oos_guardrails_all_pass":pass_all,
        "oos_portfolio":{"selected":msel,"v38":mbase,"block_bootstrap_vs_v38":boot},
        "oos_paired":{
            "annual_top10":paired_delta(annual_caps[selected],annual_caps["V38"],"OOS",True),
            "rolling126":paired_delta(rolling_caps[selected],rolling_caps["V38"],"OOS",False),
        },
        "calendar_returns":{m:fal.calendar_returns(sims[m]["equity"]) for m in TIE_MODES},
        "trade_stats":{m:rt.trade_stats(sims[m]["trades"]) for m in TIE_MODES},
        "named_diagnostics":{m:[named_diag(sym,s,p,m,meta,matrices,peer_ctx,features,sims[m]) for sym,s,p in named] for m in TIE_MODES},
    }
    (out/"summary_releadership_tiebreak_walkforward.json").write_text(json.dumps(safe(result),ensure_ascii=False,indent=2),encoding="utf-8")
    print("=== RELEADERSHIP_TIEBREAK_WALKFORWARD_JSON ===",flush=True); print(json.dumps(safe(result),ensure_ascii=False,indent=2),flush=True); print("=== END_RELEADERSHIP_TIEBREAK_WALKFORWARD_JSON ===",flush=True)
    rel.classifier=ORIG_CLASSIFIER


if __name__=="__main__": main()
