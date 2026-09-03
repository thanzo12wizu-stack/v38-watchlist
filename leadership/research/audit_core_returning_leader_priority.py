from __future__ import annotations
import argparse, json
from pathlib import Path
import numpy as np
import pandas as pd

import audit_ordinary_stock_market_mode_robustness as base
import audit_ordinary_stock_theme_leave_one_out as loo
import audit_ordinary_stock_exit_trail as ex
import audit_ordinary_stock_rebalance_vs_trail as rt
import audit_five_year_leader_capture as lc
import audit_core_emerging_leader_mix as cem
import audit_core_emerging_hybrid_refine as hyb

ACTIVE_MEMORY = 0
REQUIRE_RED = True
LEADER_LAST_POS = None
RED_CUM = None
DATE_POS = None


def mild_emerging_score(d,sym,c,matrices,features):
    bs=float(c.get("rank_score") or c.get("stock_rs189") or 0.0)
    def v(k):
        try:
            x=float(k.at[d,sym]); return x if np.isfinite(x) else 0.0
        except Exception:return 0.0
    return .70*bs+.15*v(matrices["rs63"])+.07*v(features["rs_acc_pct"])+.04*v(features["ret20_pct"])+.04*v(features["dvol_acc_pct"])


def returning_mask_for_date(d, symbols):
    if ACTIVE_MEMORY<=0 or LEADER_LAST_POS is None:return set()
    i=DATE_POS.get(pd.Timestamp(d));
    if i is None:return set()
    out=[]
    for sym in symbols:
        j=LEADER_LAST_POS.get(sym)
        if j is None:continue
        p=int(j[i])
        if p<0 or i-p>ACTIVE_MEMORY:continue
        if REQUIRE_RED and not (RED_CUM[i]>RED_CUM[p]):continue
        out.append(sym)
    return set(out)


def classifier(d,matrices,peer_ctx,features,bucket,enhanced):
    cmap=cem.base_candidate_map(d,matrices,peer_ctx,bucket); core=[]; em=[]
    core_syms=[]
    for sym,c0 in cmap.items():
        try:is_core=bool(features["core_mask"].at[d,sym]); is_em=bool(features["emerging_mask"].at[d,sym])
        except Exception:continue
        if not (is_core or is_em):continue
        if is_core:core_syms.append(sym)
    ret=returning_mask_for_date(d,core_syms)
    # Only one returning leader receives priority; among returners choose the best current V38 rank.
    priority=None
    if ret:
        priority=max(ret,key=lambda s:float(cmap[s].get("rank_score") or cmap[s].get("stock_rs189") or 0.0))
    for sym,c0 in cmap.items():
        try:is_core=bool(features["core_mask"].at[d,sym]); is_em=bool(features["emerging_mask"].at[d,sym])
        except Exception:continue
        if not (is_core or is_em):continue
        layer="CORE" if is_core else "EMERGING"; c=dict(c0); bs=float(c.get("rank_score") or c.get("stock_rs189") or 0.0)
        score=bs if layer=="CORE" else mild_emerging_score(d,sym,c,matrices,features)
        c["returning_leader"]=bool(layer=="CORE" and sym in ret); c["reentry_priority"]=bool(sym==priority)
        c["layer"]=layer; c["layer_score"]=score+(1000.0 if sym==priority else 0.0)
        c["dvol"]=float(matrices["dvol"].at[d,sym]) if pd.notna(matrices["dvol"].at[d,sym]) else np.nan
        c["dvol_pct"]=float(features["dvol_pct"].at[d,sym]) if pd.notna(features["dvol_pct"].at[d,sym]) else np.nan
        c["rs63"]=float(matrices["rs63"].at[d,sym]) if pd.notna(matrices["rs63"].at[d,sym]) else np.nan
        (core if layer=="CORE" else em).append((sym,c))
    core.sort(key=lambda x:x[1]["layer_score"],reverse=True); em.sort(key=lambda x:x[1]["layer_score"],reverse=True)
    return core,em


def build_former_leader_state(meta,matrices,peer_ctx):
    idx=meta["analysis_idx"]; syms=list(matrices["close"].columns); pos={s:k for k,s in enumerate(syms)}; top=np.zeros((len(idx),len(syms)),dtype=bool)
    for i,d0 in enumerate(idx):
        d=pd.Timestamp(d0); color=str(meta["nq"].at[d,"nq_color"]) if d in meta["nq"].index and pd.notna(meta["nq"].at[d,"nq_color"]) else ""; b=float(meta["breadth"].loc[d]) if d in meta["breadth"].index and pd.notna(meta["breadth"].loc[d]) else np.nan; bucket=base.breadth_bucket(b)
        if color not in ("Blue","Green") or bucket<1:continue
        n=base.N_PORT if bucket==2 else 4
        for s,_ in lc.current_candidates(d,matrices,peer_ctx,bucket,True,base.N_PORT)[:n]:
            j=pos.get(s)
            if j is not None:top[i,j]=True
    arr=np.where(top,np.arange(len(idx))[:,None],-1); last=np.maximum.accumulate(arr,axis=0)
    last_map={s:last[:,j] for j,s in enumerate(syms)}
    red=np.array([1 if (d in meta["nq"].index and pd.notna(meta["nq"].at[d,"nq_color"]) and str(meta["nq"].at[d,"nq_color"])=="Red") else 0 for d in idx],dtype=int)
    return last_map,np.cumsum(red),{pd.Timestamp(d):i for i,d in enumerate(idx)},int(top.sum())


def run(meta,matrices,peer_ctx,features,name,memory,require_red=True,cost=0.0):
    global ACTIVE_MEMORY,REQUIRE_RED
    ACTIVE_MEMORY=memory; REQUIRE_RED=require_red; cem.classified_candidates=classifier
    return cem.simulate_layered(meta,matrices,peer_ctx,features,cem.Variant(name,9,3,True,1),cost_bps=cost)


def exact_metrics(eq):
    return {"2021_plus":base.metrics(eq.loc[eq.index>="2021-01-04"]),"2022_plus":base.metrics(eq.loc[eq.index>="2022-01-03"]),"2024_plus":base.metrics(eq.loc[eq.index>="2024-01-02"])}


def main():
    ap=argparse.ArgumentParser();ap.add_argument("--root",default=".");ap.add_argument("--output",required=True);ap.add_argument("--analysis-start",default="2020-01-02");ap.add_argument("--analysis-end",default="2026-09-02");ap.add_argument("--leader-start",default="2021-01-04");ap.add_argument("--max-tickers",type=int,default=6000);ap.add_argument("--batch-size",type=int,default=75);args=ap.parse_args()
    root=Path(args.root);out=root/args.output;out.mkdir(parents=True,exist_ok=True)
    meta,matrices=ex.build_inputs_ext(root,args.analysis_start,args.analysis_end,args.max_tickers,args.batch_size);peer_ctx=loo.build_leave_one_out_scores(root,matrices);features=cem.build_features(matrices)
    print(f"UNIVERSE downloaded={meta['downloaded']}",flush=True)
    # Exact reference for the previously selected 9+3 / SELECTIVE 3+1 architecture.
    ref=hyb.run_variant(meta,matrices,peer_ctx,features,"REF_CURRENT_BEST",9,3,"MILD",1,0.0)
    global LEADER_LAST_POS,RED_CUM,DATE_POS
    print("BUILD former-leader state",flush=True);LEADER_LAST_POS,RED_CUM,DATE_POS,leader_marks=build_former_leader_state(meta,matrices,peer_ctx)
    cur=run(meta,matrices,peer_ctx,features,"CURRENT_BEST",0,True,0.0)
    a,b=cur["equity"].align(ref["equity"],join="inner");maxdiff=float(np.nanmax(np.abs(a.to_numpy(float)-b.to_numpy(float))))
    if maxdiff>1e-10:raise RuntimeError(f"current-best reproduction mismatch {maxdiff}")
    configs=[("REENTRY_RED_63",63,True),("REENTRY_RED_126",126,True),("REENTRY_RED_252",252,True),("FORMER_LEADER_126_CONTROL",126,False)]
    sims={"CURRENT_BEST":cur}
    for name,m,r in configs:
        print(f"SIM {name}",flush=True);sims[name]=run(meta,matrices,peer_ctx,features,name,m,r,0.0)
    rolling=lc.build_rolling_superleaders(matrices,pd.Timestamp(args.leader_start),pd.Timestamp(args.analysis_end)); dvol=matrices["dvol"];dp=dvol.rank(axis=1,pct=True)*100.0
    core_rows=[]
    for _,rr in rolling.iterrows():
        s=str(rr["symbol"]);d=pd.Timestamp(rr["start_date"])
        if s in dvol.columns and d in dvol.index and ((pd.notna(dvol.at[d,s]) and float(dvol.at[d,s])>=cem.CORE_DVOL_ABS) or (pd.notna(dp.at[d,s]) and float(dp.at[d,s])>=cem.CORE_DVOL_PCT)):core_rows.append(dict(rr))
    core_roll=pd.DataFrame(core_rows); annual=lc.build_annual_leaders(matrices,pd.Timestamp(args.leader_start),pd.Timestamp(args.analysis_end));core_ann=annual.loc[annual["mega_liquid"].astype(bool)].copy()
    result={"status":"CORE_RETURNING_LEADER_PRIORITY_AUDIT","analysis_window":{"start":args.analysis_start,"end":args.analysis_end,"leader_start":args.leader_start,"downloaded":int(meta["downloaded"])},"current_best_validation":{"status":"PASS","equity_max_abs_diff":maxdiff},"design":{"portfolio":"9 Core + 3 Emerging; SELECTIVE 3 Core + 1 Emerging; no forced trim","returning_leader":"currently standard-eligible size-Core, was previously in current V38 top candidate set, with a Red session after that former-leader observation and within the memory window","priority":"at most one returning Core leader gets first priority on a normal vacant Core fill; no position is sold to make room","unchanged":"Market Mode, eligibility thresholds, Theme/RS ranking inputs, total slots, exits, next-open execution"},"former_leader_marks":leader_marks,"variants":{},"bootstrap_vs_current":{},"cost10bps":{}}
    caps={}
    for name,sim in sims.items():
        ca=cem.simple_capture(core_ann,sim["intervals"],matrices["close"]);cr=cem.simple_capture(core_roll,sim["intervals"],matrices["close"]);caps[name]=cr;ent=sim["entries"];prio=int(ent.get("reentry_priority",pd.Series(dtype=bool)).fillna(False).astype(bool).sum()) if not ent.empty else 0
        result["variants"][name]={"metrics":base.slice_metrics(sim["equity"]),"exact_period_metrics":exact_metrics(sim["equity"]),"trade_stats":rt.trade_stats(sim["trades"]),"entries":int(len(ent)),"priority_entries":prio,"core_annual_capture":cem.summarize_capture_ext(ca),"core_rolling_capture":cem.summarize_capture_ext(cr)}
        sim["equity"].rename("equity").to_csv(out/f"equity_{name}.csv");sim["entries"].to_csv(out/f"entries_{name}.csv",index=False);sim["trades"].to_csv(out/f"trades_{name}.csv",index=False);cr.to_csv(out/f"capture_core_rolling_{name}.csv",index=False)
    cb=sims["CURRENT_BEST"]["equity"]
    for i,(name,sim) in enumerate(sims.items()):
        if name!="CURRENT_BEST":result["bootstrap_vs_current"][name]=base.bootstrap_block_win(sim["equity"],cb,block=20,reps=5000,seed=72000+i)
    for name,m,r in configs[:3]:
        sc=run(meta,matrices,peer_ctx,features,name+"_COST10",m,r,cem.TCOST_BPS);result["cost10bps"][name]={"exact_period_metrics":exact_metrics(sc["equity"]),"full_cagr_drag":float(base.metrics(sc["equity"])["cagr"]-base.metrics(sims[name]["equity"])["cagr"])}
    names={"NVDA","PLTR","SMCI","APP","CRWD","HOOD","MSTR","MU","VST","VRT","SNDK"};rows=[]
    for v,cf in caps.items():
        if cf.empty:continue
        z=cf.loc[cf["symbol"].astype(str).isin(names)]
        for _,x in z.iterrows():rows.append({"variant":v,"symbol":x["symbol"],"start_date":x["start_date"],"peak_date":x["peak_date"],"peak_return":x["peak_return"],"captured":x["captured"],"capture_date":x["capture_date"],"capture_progress":x["capture_progress"]})
    pd.DataFrame(rows).to_csv(out/"named_core_leader_capture.csv",index=False)
    (out/"summary_core_returning_leader_priority.json").write_text(json.dumps(base.safe(result),ensure_ascii=False,indent=2),encoding="utf-8");print("=== CORE_RETURNING_LEADER_PRIORITY_JSON ===",flush=True);print(json.dumps(base.safe(result),ensure_ascii=False,indent=2),flush=True);print("=== END_CORE_RETURNING_LEADER_PRIORITY_JSON ===",flush=True)

if __name__=="__main__":main()
