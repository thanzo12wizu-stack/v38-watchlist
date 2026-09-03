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
import audit_core_releadership_priority as rel
import audit_core_releadership_falsification as fal
import audit_core_releadership_volume_decomposition as vd
import audit_five_year_leader_capture as lc


PRIORITY_K: int | None = 1
ORIG_CLASSIFIER = rel.classifier
MODES = ("P1", "P2", "P3", "PALL")
DEV_END = pd.Timestamp("2023-12-31")
OOS_START = pd.Timestamp("2024-01-01")


def safe(v: Any) -> Any:
    return base.safe(v)


def _v(frame: pd.DataFrame, d: pd.Timestamp, sym: str, default=np.nan) -> float:
    try:
        x=float(frame.at[d,sym]); return x if np.isfinite(x) else default
    except Exception: return default


def breadth_classifier(d, matrices, peer_ctx, features, bucket, enhanced):
    cmap=cem.base_candidate_map(d,matrices,peer_ctx,bucket)
    core=[]; emerging=[]; sigs=[]
    variant=rel.ACTIVE_VARIANT
    for sym in cmap:
        try:
            is_core=bool(features["core_mask"].at[d,sym]); is_em=bool(features["emerging_mask"].at[d,sym])
        except Exception: continue
        if not (is_core or is_em): continue
        if is_core and vd.signal_ok(d,sym,matrices,features,variant): sigs.append(sym)
    sigs=sorted(sigs,key=lambda s:float(cmap[s].get("rank_score") or cmap[s].get("stock_rs189") or 0.0),reverse=True)
    priority=set(sigs if PRIORITY_K is None else sigs[:PRIORITY_K])
    for sym,c0 in cmap.items():
        try:
            is_core=bool(features["core_mask"].at[d,sym]); is_em=bool(features["emerging_mask"].at[d,sym])
        except Exception: continue
        if not (is_core or is_em): continue
        layer="CORE" if is_core else "EMERGING"; c=dict(c0)
        bs=float(c.get("rank_score") or c.get("stock_rs189") or 0.0)
        score=bs if layer=="CORE" else rel.mild_emerging_score(d,sym,c,matrices,features)
        is_sig=bool(layer=="CORE" and sym in sigs)
        c.update({
            "relead_signal":is_sig,"relead_priority":bool(sym in priority),"relead_priority_breadth":"ALL" if PRIORITY_K is None else int(PRIORITY_K),
            "relead_signal_rank":(sigs.index(sym)+1) if sym in sigs else np.nan,
            "layer":layer,"layer_score":score+(1000.0 if sym in priority else 0.0),
            "dvol":_v(matrices["dvol"],d,sym),"dvol_pct":_v(features["dvol_pct"],d,sym),
            "rs63":_v(matrices["rs63"],d,sym),"rs_acc_pct":_v(features["rs_acc_pct"],d,sym),
        })
        (core if layer=="CORE" else emerging).append((sym,c))
    core.sort(key=lambda x:x[1]["layer_score"],reverse=True); emerging.sort(key=lambda x:x[1]["layer_score"],reverse=True)
    return core,emerging


def run_mode(meta,matrices,peer_ctx,features,mode,cost_bps=0.0):
    global PRIORITY_K
    PRIORITY_K={"P1":1,"P2":2,"P3":3,"PALL":None}[mode]
    rel.classifier=breadth_classifier
    return vd.run_variant(meta,matrices,peer_ctx,features,f"THREE4_{mode}","THREE4","BASE",cost_bps)


def freeze_labels(out,annual,rolling):
    a=annual.copy();r=rolling.copy();a["evaluation_set"]="ANNUAL_LIQUID";r["evaluation_set"]="ROLLING_126_SUPERLEADER"
    cols=sorted(set(a.columns)|set(r.columns));f=pd.concat([a.reindex(columns=cols),r.reindex(columns=cols)],ignore_index=True)
    f=f.sort_values([c for c in ["evaluation_set","period","rank","symbol","start_date"] if c in f.columns],na_position="last").reset_index(drop=True)
    p=out/"leader_labels_frozen.csv";f.to_csv(p,index=False);h=hashlib.sha256(p.read_bytes()).hexdigest();(out/"leader_labels_sha256.txt").write_text(h+"\n")
    return {"rows":int(len(f)),"sha256":h}


def overlap(intervals,sym,start,peak):
    if intervals.empty:return intervals
    z=intervals.loc[intervals.symbol.astype(str)==sym].copy()
    if z.empty:return z
    z["entry_date"]=pd.to_datetime(z.entry_date);z["exit_date"]=pd.to_datetime(z.exit_date,errors="coerce")
    return z.loc[(z.entry_date<=peak)&(z.exit_date.isna()|(z.exit_date>start))].sort_values("entry_date")


def annotate(leaders,sim,matrices):
    rows=[];close=matrices["close"]
    for _,rr in leaders.iterrows():
        z=dict(rr);sym=str(z["symbol"]);start=pd.Timestamp(z["start_date"]);peak=pd.Timestamp(z["peak_date"]);ov=overlap(sim["intervals"],sym,start,peak);hit=not ov.empty
        z.update({"captured":bool(hit),"capture_date":pd.NaT,"capture_progress":np.nan,"remaining_upside":np.nan})
        if hit:
            ent=pd.Timestamp(ov.iloc[0].entry_date)
            if ent<=start:z["capture_date"]=start;z["capture_progress"]=0.0;z["remaining_upside"]=float(z["peak_return"])
            else:
                ep=_v(close,ent,sym);sp=float(z["start_price"]);pp=float(z["peak_price"]);total=pp/sp-1
                z["capture_date"]=ent
                if np.isfinite(ep) and ep>0 and total>0:z["capture_progress"]=float((ep/sp-1)/total);z["remaining_upside"]=float(pp/ep-1)
        rows.append(z)
    return pd.DataFrame(rows)


def phase(df,which,top10=False):
    z=df.copy();d=pd.to_datetime(z.start_date);z=z.loc[d<=DEV_END] if which=="DEV" else z.loc[d>=OOS_START]
    if top10:z=z.loc[pd.to_numeric(z["rank"],errors="coerce")<=10]
    return z


def stats(df):
    if df.empty:return {"n":0,"hit_n":0,"early_n":0}
    hit=df.captured.astype(bool);prog=pd.to_numeric(df.capture_progress,errors="coerce");early=hit&(prog<=1/3)
    return {"n":int(len(df)),"hit_n":int(hit.sum()),"hit_rate":float(hit.mean()),"early_n":int(early.sum()),"early_rate_all":float(early.mean()),"median_capture_progress":float(prog.loc[hit].median()) if hit.any() else None}


def evaluate(ac,rc,which):
    return {"annual_top10":stats(phase(ac,which,True)),"annual_top20":stats(phase(ac,which,False)),"rolling126":stats(phase(rc,which,False))}


def dev_key(ev,mode):
    a=ev["annual_top10"];r=ev["rolling126"]
    return (a["early_n"],r["early_n"],a["hit_n"],r["hit_n"],1 if mode=="P1" else 0,-MODES.index(mode))


def metrics(eq,start): return base.metrics(eq.loc[eq.index>=pd.Timestamp(start)])


def paired(a,b,which,top10=False):
    aa=phase(a,which,top10).copy();bb=phase(b,which,top10).copy();keys=["leader_type","period","symbol","start_date","peak_date"]
    for x in (aa,bb):x["start_date"]=pd.to_datetime(x.start_date);x["peak_date"]=pd.to_datetime(x.peak_date)
    m=aa[keys+["captured","capture_progress"]].merge(bb[keys+["captured","capture_progress"]],on=keys,suffixes=("_sel","_base"));hs=m.captured_sel.astype(bool);hb=m.captured_base.astype(bool)
    es=hs&(pd.to_numeric(m.capture_progress_sel,errors="coerce")<=1/3);eb=hb&(pd.to_numeric(m.capture_progress_base,errors="coerce")<=1/3)
    return {"n":int(len(m)),"hit_selected_only":int((hs&~hb).sum()),"hit_baseline_only":int((hb&~hs).sum()),"early_selected_only":int((es&~eb).sum()),"early_baseline_only":int((eb&~es).sum())}


def named(symbol,start,peak,sim):
    s=pd.Timestamp(start);p=pd.Timestamp(peak);e=sim["entries"];z=pd.DataFrame()
    if not e.empty:z=e.loc[(e.symbol.astype(str)==symbol)&(pd.to_datetime(e.signal_date)>=s)&(pd.to_datetime(e.signal_date)<=p)]
    return {"symbol":symbol,"start":start,"peak":peak,"actual_entry":not z.empty,"actual_entry_date":str(pd.Timestamp(z.iloc[0].entry_date).date()) if not z.empty else None,"priority_rank":float(z.iloc[0].get("relead_signal_rank",np.nan)) if not z.empty else None}


def main():
    ap=argparse.ArgumentParser();ap.add_argument("--root",default=".");ap.add_argument("--output",required=True);ap.add_argument("--analysis-start",default="2020-01-02");ap.add_argument("--analysis-end",default="2026-09-02");ap.add_argument("--leader-start",default="2021-01-04");ap.add_argument("--max-tickers",type=int,default=6000);ap.add_argument("--batch-size",type=int,default=75);args=ap.parse_args()
    root=Path(args.root);out=root/args.output;out.mkdir(parents=True,exist_ok=True)
    print("BUILD PIT inputs",flush=True);meta,matrices=ex.build_inputs_ext(root,args.analysis_start,args.analysis_end,args.max_tickers,args.batch_size);peer_ctx=loo.build_leave_one_out_scores(root,matrices);features=cem.build_features(matrices);print(f"UNIVERSE downloaded={meta['downloaded']}",flush=True)
    print("FREEZE leader labels",flush=True);annual=lc.build_annual_leaders(matrices,pd.Timestamp(args.leader_start),pd.Timestamp(args.analysis_end));rolling=lc.build_rolling_superleaders(matrices,pd.Timestamp(args.leader_start),pd.Timestamp(args.analysis_end));freeze=freeze_labels(out,annual,rolling);annual.to_csv(out/"annual_leaders_frozen.csv",index=False);rolling.to_csv(out/"rolling_126_leaders_frozen.csv",index=False)
    print("BUILD fixed THREE4 features",flush=True);rel.EXT,_=rel.build_extended_features(root,matrices,features);rel.signal_ok=vd.signal_ok;vd.PRICE_ACC_PCT=features["ret20_pct"].astype(np.float32);vd.PRICE_RATIO20=(matrices["close"]/matrices["close"].shift(20)).astype(np.float32);vd.SHARE_ACC_PCT,vd.SHARE_RATIO20=fal.build_share_volume_features(matrices,features);vd.BANNED_SYMBOLS=set()
    rel.classifier=ORIG_CLASSIFIER;ref=vd.run_variant(meta,matrices,peer_ctx,features,"THREE4_REF","THREE4","BASE")
    sims={};acs={};rcs={};evs={}
    for mode in MODES:
        print(f"SIM {mode}",flush=True);sim=run_mode(meta,matrices,peer_ctx,features,mode);sims[mode]=sim;ac=annotate(annual,sim,matrices);rc=annotate(rolling,sim,matrices);acs[mode]=ac;rcs[mode]=rc;evs[mode]={"DEV":evaluate(ac,rc,"DEV"),"OOS":evaluate(ac,rc,"OOS")};ac.to_csv(out/f"annual_capture_{mode}.csv",index=False);rc.to_csv(out/f"rolling126_capture_{mode}.csv",index=False);sim["equity"].rename("equity").to_csv(out/f"equity_{mode}.csv");sim["entries"].to_csv(out/f"entries_{mode}.csv",index=False);sim["trades"].to_csv(out/f"trades_{mode}.csv",index=False)
    a,b=sims["P1"]["equity"].align(ref["equity"],join="inner");maxdiff=float(np.nanmax(np.abs(a.to_numpy(float)-b.to_numpy(float))));
    if maxdiff>1e-10:raise RuntimeError(f"P1 reproduction mismatch {maxdiff}")
    selected=max(MODES,key=lambda m:dev_key(evs[m]["DEV"],m));print(f"DEV_SELECTED {selected} {dev_key(evs[selected]['DEV'],selected)}",flush=True)
    ms=metrics(sims[selected]["equity"],"2024-01-02");mb=metrics(sims["P1"]["equity"],"2024-01-02");boot=base.bootstrap_block_win(sims[selected]["equity"].loc[lambda x:x.index>=OOS_START],sims["P1"]["equity"].loc[lambda x:x.index>=OOS_START],block=20,reps=5000,seed=98641)
    guard={"annual_hit_not_worse":evs[selected]["OOS"]["annual_top10"]["hit_n"]>=evs["P1"]["OOS"]["annual_top10"]["hit_n"],"annual_early_not_worse":evs[selected]["OOS"]["annual_top10"]["early_n"]>=evs["P1"]["OOS"]["annual_top10"]["early_n"],"rolling_hit_not_worse":evs[selected]["OOS"]["rolling126"]["hit_n"]>=evs["P1"]["OOS"]["rolling126"]["hit_n"],"rolling_early_not_worse":evs[selected]["OOS"]["rolling126"]["early_n"]>=evs["P1"]["OOS"]["rolling126"]["early_n"],"cagr_not_worse_by_gt_1pp":float(ms["cagr"])>=float(mb["cagr"])-0.01,"mdd_not_worse_by_gt_2pp":float(ms["mdd"])>=float(mb["mdd"])-0.02}
    cost={}
    if selected!="P1":
        sc=run_mode(meta,matrices,peer_ctx,features,selected,cem.TCOST_BPS);cost={"selected_10bps":metrics(sc["equity"],"2024-01-02"),"cagr_drag":float(metrics(sc["equity"],"2024-01-02")["cagr"]-ms["cagr"])}
    eps=[("NVDA","2023-12-22","2024-06-18"),("PLTR","2024-05-09","2024-11-07"),("HOOD","2024-01-02","2024-12-31"),("CAVA","2024-01-02","2024-12-31"),("SE","2024-01-02","2024-12-31"),("MU","2025-01-02","2025-12-31"),("STX","2025-01-02","2025-12-31"),("RVMD","2026-01-02","2026-09-02")]
    result={"status":"RELEADERSHIP_PRIORITY_BREADTH_WALKFORWARD_AUDIT","analysis_window":{"start":args.analysis_start,"end":args.analysis_end,"downloaded":int(meta["downloaded"])},"freeze":freeze,"design":{"fixed":"THREE4 signal, V38 ordering inside Re-Leadership group, portfolio/exits/market mode unchanged.","variants":"P1/P2/P3/PALL = number of simultaneous valid Core Re-Leadership signals promoted ahead of normal Core candidates on vacant fills only; no forced sale.","selection":"2021-2023 labels only; 2024-2026YTD not used to reselect."},"validation":{"p1_reproduction_max_abs_diff":maxdiff},"evaluations":evs,"dev_selected":selected,"selected_dev_key":list(dev_key(evs[selected]["DEV"],selected)),"oos_guardrails":guard,"oos_guardrails_all_pass":all(guard.values()),"oos_portfolio":{"selected":ms,"p1":mb,"bootstrap_vs_p1":boot},"oos_paired":{"annual_top10":paired(acs[selected],acs["P1"],"OOS",True),"rolling126":paired(rcs[selected],rcs["P1"],"OOS",False)},"calendar_returns":{m:fal.calendar_returns(sims[m]["equity"]) for m in MODES},"trade_stats":{m:rt.trade_stats(sims[m]["trades"]) for m in MODES},"cost10bps":cost,"named_diagnostics":{m:[named(sym,s,p,sims[m]) for sym,s,p in eps] for m in MODES}}
    (out/"summary_releadership_priority_breadth_walkforward.json").write_text(json.dumps(safe(result),ensure_ascii=False,indent=2),encoding="utf-8");print("=== PRIORITY_BREADTH_JSON ===",flush=True);print(json.dumps(safe(result),ensure_ascii=False,indent=2),flush=True);print("=== END_PRIORITY_BREADTH_JSON ===",flush=True);rel.classifier=ORIG_CLASSIFIER

if __name__=="__main__":main()
