from __future__ import annotations

import argparse
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


PRICE_ACC_PCT: pd.DataFrame | None = None
PRICE_RATIO20: pd.DataFrame | None = None
SHARE_ACC_PCT: pd.DataFrame | None = None
SHARE_RATIO20: pd.DataFrame | None = None
BANNED_SYMBOLS: set[str] = set()


def _v(frame: pd.DataFrame | None, d: pd.Timestamp, sym: str, default: float = np.nan) -> float:
    if frame is None:
        return default
    try:
        x = float(frame.at[d, sym])
        return x if np.isfinite(x) else default
    except Exception:
        return default


def pxshare_flags(d: pd.Timestamp, sym: str, profile: str) -> tuple[bool, bool]:
    p = rel.PROFILES[profile]
    pa = _v(PRICE_ACC_PCT, d, sym)
    pr = _v(PRICE_RATIO20, d, sym)
    sa = _v(SHARE_ACC_PCT, d, sym)
    sr = _v(SHARE_RATIO20, d, sym)
    price = np.isfinite(pa) and np.isfinite(pr) and pa >= p["dvol_acc_pct"] and pr >= p["dvol_ratio"]
    share = np.isfinite(sa) and np.isfinite(sr) and sa >= p["dvol_acc_pct"] and sr >= p["dvol_ratio"]
    return bool(price), bool(share)


def signal_ok(d: pd.Timestamp, sym: str, matrices, features, variant: rel.Variant) -> bool:
    if sym in BANNED_SYMBOLS:
        return False
    if variant.rule == "NONE":
        return False
    r, h, t, dv, _ = rel.component_flags(d, sym, matrices, features, variant.profile)
    p, s = pxshare_flags(d, sym, variant.profile)
    if variant.rule == "THREE4":
        return int(r) + int(h) + int(t) + int(dv) >= 3
    if variant.rule == "HT_ONLY":
        return h and t
    if variant.rule == "HT_R_OR_D":
        return h and t and (r or dv)
    if variant.rule == "HT_R_OR_P":
        return h and t and (r or p)
    if variant.rule == "HT_R_OR_S":
        return h and t and (r or s)
    if variant.rule == "HT_R_OR_PS":
        return h and t and (r or (p and s))
    if variant.rule == "HT_P":
        return h and t and p
    if variant.rule == "HT_S":
        return h and t and s
    if variant.rule == "HT_D":
        return h and t and dv
    raise ValueError(f"unknown rule {variant.rule}")


def run_variant(meta, matrices, peer_ctx, features, name: str, rule: str, profile: str = "BASE", cost_bps: float = 0.0):
    return rel.run(meta, matrices, peer_ctx, features, rel.Variant(name, rule, profile), cost_bps)


def period_metrics(eq: pd.Series) -> dict[str, Any]:
    def m(start: str, end: str | None = None):
        x = eq.loc[eq.index >= pd.Timestamp(start)]
        if end is not None:
            x = x.loc[x.index <= pd.Timestamp(end)]
        return base.metrics(x)
    return {
        "2021_plus": m("2021-01-04"),
        "2022_plus": m("2022-01-03"),
        "2022_2023": m("2022-01-03", "2023-12-29"),
        "2024_plus": m("2024-01-02"),
    }


def summarize(sim, core_roll, matrices):
    cap = cem.simple_capture(core_roll, sim["intervals"], matrices["close"])
    return {
        "metrics": base.slice_metrics(sim["equity"]),
        "period_metrics": period_metrics(sim["equity"]),
        "calendar_returns": fal.calendar_returns(sim["equity"]),
        "trade_stats": rt.trade_stats(sim["trades"]),
        "core_capture": cem.summarize_capture_ext(cap),
        "priority_forward": rel.priority_forward_stats(sim["entries"], matrices["close"]),
    }


def priority_component_stats(sim, matrices, features, profile="BASE"):
    ent = sim["entries"]
    if ent.empty or "relead_priority" not in ent:
        return {}
    e = ent.loc[ent["relead_priority"].fillna(False).astype(bool)]
    rows = []
    close = matrices["close"]
    idx = close.index
    ipos = {pd.Timestamp(d): i for i, d in enumerate(idx)}
    for _, z in e.iterrows():
        d = pd.Timestamp(z["signal_date"]); sym = str(z["symbol"])
        r,h,t,dv,_ = rel.component_flags(d, sym, matrices, features, profile)
        p,s = pxshare_flags(d, sym, profile)
        i = ipos.get(d); p0 = _v(close, d, sym)
        ret20 = np.nan
        if i is not None and np.isfinite(p0) and p0 > 0:
            j = min(i + 20, len(idx)-1); p1 = _v(close, pd.Timestamp(idx[j]), sym)
            if np.isfinite(p1) and p1 > 0: ret20 = p1 / p0 - 1.0
        rows.append({"R":r,"H":h,"T":t,"D":dv,"P":p,"S":s,"ret20":ret20})
    df = pd.DataFrame(rows)
    out = {"n": int(len(df))}
    if df.empty: return out
    for key, mask in {
        "D": df.D,
        "P": df.P,
        "S": df.S,
        "D_and_P": df.D & df.P,
        "D_and_S": df.D & df.S,
        "D_and_P_and_S": df.D & df.P & df.S,
        "D_only_vs_PS": df.D & ~df.P & ~df.S,
    }.items():
        g = df.loc[mask]
        out[key] = {
            "n": int(len(g)),
            "share": float(len(g)/len(df)),
            "ret20_mean": float(g.ret20.mean()) if len(g) else None,
            "ret20_median": float(g.ret20.median()) if len(g) else None,
            "ret20_positive": float((g.ret20 > 0).mean()) if len(g) else None,
        }
    return out


def named_diagnosis(symbol, start, peak, meta, matrices, peer_ctx, features, variant, sim):
    dates = [pd.Timestamp(d) for d in meta["analysis_idx"] if start <= pd.Timestamp(d) <= peak]
    sig_days = []; prio_days = []
    for d in dates:
        color = str(meta["nq"].at[d,"nq_color"]) if d in meta["nq"].index and pd.notna(meta["nq"].at[d,"nq_color"]) else ""
        breadth = float(meta["breadth"].loc[d]) if d in meta["breadth"].index and pd.notna(meta["breadth"].loc[d]) else np.nan
        bucket = base.breadth_bucket(breadth)
        if color not in ("Blue","Green") or bucket <= 0: continue
        cmap = cem.base_candidate_map(d, matrices, peer_ctx, bucket)
        if symbol not in cmap: continue
        try: core = bool(features["core_mask"].at[d,symbol])
        except Exception: core = False
        if not core: continue
        if signal_ok(d,symbol,matrices,features,variant):
            sig_days.append(d)
            ss=[]
            for s in cmap:
                try:
                    if not bool(features["core_mask"].at[d,s]): continue
                except Exception: continue
                if signal_ok(d,s,matrices,features,variant): ss.append(s)
            if ss:
                winner=max(ss,key=lambda s:float(cmap[s].get("rank_score") or cmap[s].get("stock_rs189") or 0.0))
                if winner==symbol: prio_days.append(d)
    ent=sim["entries"]
    actual=pd.DataFrame()
    if not ent.empty:
        actual=ent.loc[(ent.symbol.astype(str)==symbol)&(pd.to_datetime(ent.signal_date)>=start)&(pd.to_datetime(ent.signal_date)<=peak)]
    return {
        "symbol":symbol,"start":str(start.date()),"peak":str(peak.date()),
        "signal_days":len(sig_days),"first_signal":str(sig_days[0].date()) if sig_days else None,
        "priority_days":len(prio_days),"first_priority":str(prio_days[0].date()) if prio_days else None,
        "actual_entry":not actual.empty,
        "actual_entry_date":str(pd.Timestamp(actual.iloc[0].entry_date).date()) if not actual.empty else None,
    }


def main():
    global PRICE_ACC_PCT, PRICE_RATIO20, SHARE_ACC_PCT, SHARE_RATIO20, BANNED_SYMBOLS
    ap=argparse.ArgumentParser(); ap.add_argument("--root",default="."); ap.add_argument("--output",required=True)
    ap.add_argument("--analysis-start",default="2020-01-02"); ap.add_argument("--analysis-end",default="2026-09-02")
    ap.add_argument("--leader-start",default="2021-01-04"); ap.add_argument("--max-tickers",type=int,default=6000); ap.add_argument("--batch-size",type=int,default=75)
    args=ap.parse_args(); root=Path(args.root); out=root/args.output; out.mkdir(parents=True,exist_ok=True)

    print("BUILD shared PIT inputs",flush=True)
    meta,matrices=ex.build_inputs_ext(root,args.analysis_start,args.analysis_end,args.max_tickers,args.batch_size)
    peer_ctx=loo.build_leave_one_out_scores(root,matrices); features=cem.build_features(matrices)
    print(f"UNIVERSE downloaded={meta['downloaded']}",flush=True)
    print("VALIDATE current 9+3 reference",flush=True)
    current=hyb.run_variant(meta,matrices,peer_ctx,features,"CURRENT_BEST",9,3,"MILD",1,0.0)

    print("BUILD Re-Leadership and volume decomposition features",flush=True)
    rel.EXT,_=rel.build_extended_features(root,matrices,features)
    rel.signal_ok=signal_ok
    PRICE_ACC_PCT=features["ret20_pct"].astype(np.float32)
    PRICE_RATIO20=(matrices["close"]/matrices["close"].shift(20)).astype(np.float32)
    SHARE_ACC_PCT,SHARE_RATIO20=fal.build_share_volume_features(matrices,features)

    specs=[
        ("THREE4_BASE","THREE4","BASE"),
        ("HT_ONLY_BASE","HT_ONLY","BASE"),
        ("HT_R_OR_D_LOOSE","HT_R_OR_D","LOOSE"),
        ("HT_R_OR_D_BASE","HT_R_OR_D","BASE"),
        ("HT_R_OR_D_STRICT","HT_R_OR_D","STRICT"),
        ("HT_R_OR_P_BASE","HT_R_OR_P","BASE"),
        ("HT_R_OR_S_BASE","HT_R_OR_S","BASE"),
        ("HT_R_OR_PS_BASE","HT_R_OR_PS","BASE"),
        ("HT_D_BASE","HT_D","BASE"),
        ("HT_P_BASE","HT_P","BASE"),
        ("HT_S_BASE","HT_S","BASE"),
    ]
    sims={"CURRENT_BEST":current}
    BANNED_SYMBOLS=set()
    for name,rule,profile in specs:
        print(f"SIM {name}",flush=True); sims[name]=run_variant(meta,matrices,peer_ctx,features,name,rule,profile)

    core_roll=fal.build_core_roll(matrices,args.leader_start,args.analysis_end)
    result={
        "status":"CORE_RELEADERSHIP_VOLUME_DECOMPOSITION_AUDIT",
        "analysis_window":{"start":args.analysis_start,"end":args.analysis_end,"leader_start":args.leader_start,"downloaded":int(meta["downloaded"])},
        "design":{
            "unchanged":"9 Core + 3 Emerging; SELECTIVE 3+1; existing V38 tie-break; one priority only on vacant Core fill; no forced sale.",
            "identity":"Dollar-volume20 = Close * rolling-20 average share volume. Therefore its 20-session ratio equals price ratio * share-volume ratio.",
            "primary_structural_candidate":"HT_R_OR_D_BASE = High & Theme & (RS or Dollar-volume), derived from the two strongest THREE4 triple branches; not selected after this run.",
            "decomposition":"Replace Dollar-volume support with price-only or share-volume-only thresholds using the same percentile and ratio cutoffs as Dollar-volume.",
        },
        "variants":{},"reality_check":{},"primary_outlier_stress":{},"priority_component_overlap":{},"cost10bps":{},"named_diagnostics":[]
    }
    for name,sim in sims.items():
        result["variants"][name]=summarize(sim,core_roll,matrices)
        sim["equity"].rename("equity").to_csv(out/f"equity_{name}.csv")
        sim["entries"].to_csv(out/f"entries_{name}.csv",index=False)
        sim["trades"].to_csv(out/f"trades_{name}.csv",index=False)

    names=["CURRENT_BEST"]+[x[0] for x in specs]
    result["reality_check"]=fal.reality_check(sims,"CURRENT_BEST",names,start="2021-01-04",block=20,reps=5000,seed=96317)
    result["priority_component_overlap"]["THREE4_BASE"]=priority_component_stats(sims["THREE4_BASE"],matrices,features)
    result["priority_component_overlap"]["HT_R_OR_D_BASE"]=priority_component_stats(sims["HT_R_OR_D_BASE"],matrices,features)

    primary="HT_R_OR_D_BASE"; ptdf=fal.priority_trade_frame(sims[primary]); result["primary_outlier_stress"]["priority_trade_returns"]=fal.trimmed_trade_stats(ptdf)
    top=[]
    if not ptdf.empty and "return" in ptdf: top=[str(s) for s in ptdf.groupby("symbol")["return"].sum().sort_values(ascending=False).index[:5]]
    result["primary_outlier_stress"]["top_priority_profit_symbols"]=top
    for k in (1,3,5):
        banned=set(top[:k])
        if not banned: continue
        BANNED_SYMBOLS=banned; name=f"HT_R_OR_D_BAN_TOP{k}_SYMBOLS"; print(f"SIM {name} banned={sorted(banned)}",flush=True)
        sim=run_variant(meta,matrices,peer_ctx,features,name,"HT_R_OR_D","BASE")
        result["primary_outlier_stress"][name]=summarize(sim,core_roll,matrices); sim["equity"].rename("equity").to_csv(out/f"equity_{name}.csv")
    BANNED_SYMBOLS=set()

    for name,rule in [("THREE4_BASE","THREE4"),("HT_R_OR_D_BASE","HT_R_OR_D"),("HT_R_OR_P_BASE","HT_R_OR_P")]:
        print(f"SIM COST10 {name}",flush=True); sc=run_variant(meta,matrices,peer_ctx,features,name+"_COST10",rule,"BASE",cem.TCOST_BPS)
        result["cost10bps"][name]={"period_metrics":period_metrics(sc["equity"]),"full_cagr_drag":float(base.metrics(sc["equity"])["cagr"]-base.metrics(sims[name]["equity"])["cagr"])}

    episodes=fal.choose_named_episodes(core_roll); primary_variant=rel.Variant(primary,"HT_R_OR_D","BASE")
    for sym,start,peak in episodes: result["named_diagnostics"].append(named_diagnosis(sym,start,peak,meta,matrices,peer_ctx,features,primary_variant,sims[primary]))

    summary=out/"summary_core_releadership_volume_decomposition.json"; summary.write_text(json.dumps(base.safe(result),ensure_ascii=False,indent=2),encoding="utf-8")
    print("=== CORE_RELEADERSHIP_VOLUME_DECOMPOSITION_JSON ===",flush=True); print(json.dumps(base.safe(result),ensure_ascii=False,indent=2),flush=True); print("=== END_CORE_RELEADERSHIP_VOLUME_DECOMPOSITION_JSON ===",flush=True)


if __name__=="__main__": main()
