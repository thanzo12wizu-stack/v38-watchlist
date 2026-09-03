from __future__ import annotations
import argparse, json
from pathlib import Path
import numpy as np
import pandas as pd

import audit_ordinary_stock_market_mode_robustness as base
import audit_ordinary_stock_theme_leave_one_out as loo
import audit_ordinary_stock_exit_trail as ex
import audit_five_year_leader_capture as lc
import audit_core_emerging_leader_mix as cem

CORE_ABS = cem.CORE_DVOL_ABS
CORE_PCT = cem.CORE_DVOL_PCT
MEGA = cem.MEGA_DVOL

def size_features(matrices):
    dvol=matrices["dvol"]
    dvol_pct=dvol.rank(axis=1,pct=True)*100.0
    core_size=(dvol>=CORE_ABS)|(dvol_pct>=CORE_PCT)
    return dvol_pct, core_size

def durable_true_emerging(rolling, matrices, dvol_pct, core_size):
    close,dvol=matrices["close"],matrices["dvol"]
    a=[]; r=[]
    for _,rr in rolling.iterrows():
        x=dict(rr); sym=str(x["symbol"]); start=pd.Timestamp(x["start_date"]); peak=pd.Timestamp(x["peak_date"])
        if sym not in close.columns or start not in close.index or bool(core_size.at[start,sym]): continue
        dates=close.index[(close.index>start)&(close.index<=peak)]
        if len(dates)<20: continue
        dv=pd.to_numeric(dvol.loc[dates,sym],errors="coerce"); dp=pd.to_numeric(dvol_pct.loc[dates,sym],errors="coerce")
        ash=float((dv>=MEGA).mean()) if dv.notna().any() else 0.0; rsh=float((dp>=90).mean()) if dp.notna().any() else 0.0
        ar=dv.rolling(20,min_periods=15).median(); rrmed=dp.rolling(20,min_periods=15).median(); ad=ar.index[ar>=MEGA]; rd=rrmed.index[rrmed>=90]
        x["start_dvol"]=float(dvol.at[start,sym]) if pd.notna(dvol.at[start,sym]) else np.nan; x["start_dvol_pct"]=float(dvol_pct.at[start,sym]) if pd.notna(dvol_pct.at[start,sym]) else np.nan
        x["future_abs_share"]=ash; x["future_rel_share"]=rsh; x["abs_graduation_date"]=pd.Timestamp(ad[0]) if len(ad) else pd.NaT; x["rel_graduation_date"]=pd.Timestamp(rd[0]) if len(rd) else pd.NaT
        if ash>=0.25 and len(ad): a.append(dict(x))
        if rsh>=0.25 and len(rd): r.append(dict(x))
    return pd.DataFrame(a),pd.DataFrame(r)

def first_date(mask):
    z=mask.fillna(False)
    return pd.Timestamp(z.index[z.to_numpy(bool)][0]) if bool(z.any()) else pd.NaT

def event_diagnostic(row, matrices, meta, peer_ctx, dvol_pct, core_size, sim):
    sym=str(row["symbol"]); start=pd.Timestamp(row["start_date"]); peak=pd.Timestamp(row["peak_date"]); idx=meta["analysis_idx"]; dates=idx[(idx>=start)&(idx<=peak)]
    out={k:row[k] for k in row.index}; out["start_size_core"]=bool(core_size.at[start,sym]) if start in core_size.index and sym in core_size.columns else False
    if sym not in matrices["close"].columns or len(dates)==0: out["blocker"]="OUT_OF_UNIVERSE"; return out
    elig=matrices["new_eligible"].loc[dates,sym].fillna(False); out["first_eligible"]=first_date(elig)
    relaxed=(matrices["close"].loc[dates,sym]>=5)&(matrices["dvol"].loc[dates,sym]>=base.DVOL_FLOOR)&(matrices["sma50"].loc[dates,sym]>matrices["sma200"].loc[dates,sym])&(matrices["close"].loc[dates,sym]>matrices["sma200"].loc[dates,sym])&(matrices["rs189"].loc[dates,sym]>=85)&(matrices["rs63"].loc[dates,sym]>=75)
    out["first_relaxed_rs63_75"]=first_date(relaxed)
    market_dates=[]; rank_dates=[]
    for d in dates:
        color=str(meta["nq"].at[d,"nq_color"]) if d in meta["nq"].index and pd.notna(meta["nq"].at[d,"nq_color"]) else ""; b=float(meta["breadth"].loc[d]) if d in meta["breadth"].index and pd.notna(meta["breadth"].loc[d]) else np.nan; bucket=base.breadth_bucket(b)
        if color not in ("Blue","Green") or bucket<1: continue
        if bool(matrices["new_eligible"].at[d,sym]):
            market_dates.append(d); n=base.N_PORT if bucket==2 else 4; names=[s for s,_ in lc.current_candidates(d,matrices,peer_ctx,bucket,True,base.N_PORT)[:n]]
            if sym in names: rank_dates.append(d)
    out["first_market_eligible"]=pd.Timestamp(market_dates[0]) if market_dates else pd.NaT; out["first_rank_ready"]=pd.Timestamp(rank_dates[0]) if rank_dates else pd.NaT
    ann=lc.annotate_capture(pd.DataFrame([row]),sim,matrices,meta,peer_ctx,True)
    if len(ann): q=ann.iloc[0]; out["captured"]=bool(q["captured"]); out["capture_date"]=q["capture_date"]; out["capture_progress"]=q["capture_progress"]
    else: out["captured"]=False; out["capture_date"]=pd.NaT; out["capture_progress"]=np.nan
    if out["captured"]: out["blocker"]="CAPTURED"
    elif pd.isna(out["first_eligible"]): out["blocker"]="ELIGIBILITY"
    elif pd.isna(out["first_market_eligible"]): out["blocker"]="MARKET_GATE"
    elif pd.isna(out["first_rank_ready"]): out["blocker"]="RANKING"
    else: out["blocker"]="SLOT_OR_TIMING"
    return out

def summarize_diag(df):
    if df.empty:return {"n":0}
    return {"n":int(len(df)),"captured":int(df["captured"].sum()),"hit_rate":float(df["captured"].mean()),"blockers":{str(k):int(v) for k,v in df["blocker"].value_counts().items()}}

def days_between(a,b):
    return (pd.to_datetime(b,errors="coerce")-pd.to_datetime(a,errors="coerce")).dt.days

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--root",default=".");ap.add_argument("--output",required=True);ap.add_argument("--analysis-start",default="2020-01-02");ap.add_argument("--analysis-end",default="2026-09-02");ap.add_argument("--leader-start",default="2021-01-04");ap.add_argument("--max-tickers",type=int,default=6000);ap.add_argument("--batch-size",type=int,default=75);args=ap.parse_args()
    root=Path(args.root);out=root/args.output;out.mkdir(parents=True,exist_ok=True)
    meta,matrices=ex.build_inputs_ext(root,args.analysis_start,args.analysis_end,args.max_tickers,args.batch_size); peer_ctx=loo.build_leave_one_out_scores(root,matrices); sim=lc.simulate_current_with_entries(meta,matrices,peer_ctx,True); validation=lc.validate_simulation(meta,matrices,peer_ctx,sim)
    dvol_pct,core_size=size_features(matrices); rolling=lc.build_rolling_superleaders(matrices,pd.Timestamp(args.leader_start),pd.Timestamp(args.analysis_end)); true_abs,true_rel=durable_true_emerging(rolling,matrices,dvol_pct,core_size)
    rows=[event_diagnostic(r,matrices,meta,peer_ctx,dvol_pct,core_size,sim) for _,r in rolling.iterrows()]; diag=pd.DataFrame(rows); diag["elig_lag_days"]=days_between(diag["start_date"],diag["first_eligible"]); diag["relaxed_lag_days"]=days_between(diag["start_date"],diag["first_relaxed_rs63_75"]); diag["rank_lag_days"]=days_between(diag["start_date"],diag["first_rank_ready"])
    core=diag.loc[diag["start_size_core"].astype(bool)].copy(); em=diag.loc[~diag["start_size_core"].astype(bool)].copy(); names={"NVDA","PLTR","SMCI","APP","VRT","VST","CRWD","HOOD","MU","MSTR","SNDK"}; named=diag.loc[diag["symbol"].astype(str).isin(names)].copy()
    def lag_summary(x,col):
        z=pd.to_numeric(x[col],errors="coerce").dropna(); return {"n":int(len(z)),"median_days":float(z.median()) if len(z) else None,"p75_days":float(z.quantile(.75)) if len(z) else None}
    result={"status":"LEADER_REENTRY_TRUE_EMERGING_DIAGNOSTIC","analysis_window":{"start":args.analysis_start,"end":args.analysis_end,"leader_start":args.leader_start,"downloaded":int(meta["downloaded"])},"baseline_validation":validation,"corrected_size_definition":"Core-size is contemporaneous DDV>=100M OR DDV cross-sectional percentile>=85, independent of eligibility/RS/trend.","true_emerging_durable":{"absolute_n":int(len(true_abs)),"relative_n":int(len(true_rel))},"rolling_all":summarize_diag(diag),"rolling_start_core":summarize_diag(core),"rolling_start_noncore":summarize_diag(em),"lag":{"core_current_eligibility":lag_summary(core,"elig_lag_days"),"core_relaxed_rs63_75":lag_summary(core,"relaxed_lag_days"),"core_rank_ready":lag_summary(core,"rank_lag_days"),"noncore_current_eligibility":lag_summary(em,"elig_lag_days")},"note":"Relaxed RS63>=75 is diagnostic only; no production or portfolio rule is changed."}
    diag.to_csv(out/"rolling_superleader_blockers.csv",index=False);core.to_csv(out/"core_superleader_blockers.csv",index=False);em.to_csv(out/"noncore_superleader_blockers.csv",index=False);named.to_csv(out/"named_leader_blockers.csv",index=False);true_abs.to_csv(out/"true_emerging_durable_abs.csv",index=False);true_rel.to_csv(out/"true_emerging_durable_rel.csv",index=False);(out/"summary_leader_reentry_true_emerging.json").write_text(json.dumps(base.safe(result),ensure_ascii=False,indent=2),encoding="utf-8");print("=== LEADER_REENTRY_TRUE_EMERGING_JSON ===");print(json.dumps(base.safe(result),ensure_ascii=False,indent=2));print("=== END_LEADER_REENTRY_TRUE_EMERGING_JSON ===")

if __name__=="__main__":main()
