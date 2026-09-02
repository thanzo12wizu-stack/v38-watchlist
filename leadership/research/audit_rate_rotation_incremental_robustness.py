from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path

import numpy as np
import pandas as pd

GICS=["XLB","XLC","XLE","XLF","XLI","XLK","XLP","XLRE","XLU","XLV","XLY"]
TOP=["XLF","XLE"]
BOTTOM=["XLRE","XLV"]
TRAIN_END=pd.Timestamp("2023-12-31")
HOLD_START=pd.Timestamp("2024-01-01")
END=pd.Timestamp("2026-03-20")
FEATURE_SPECS={
    "PRICE_ONLY":["price_score_xrank","price_rs63_rank_xrank","price_rs189_rank_xrank"],
    "PRICE_INTERNAL":["price_score_xrank","price_rs63_rank_xrank","price_rs189_rank_xrank","internal_score_xrank","internal_delta20_xrank"],
    "PRICE_INTERNAL_FLOW":["price_score_xrank","price_rs63_rank_xrank","price_rs189_rank_xrank","internal_score_xrank","internal_delta20_xrank","flow20_pct_aum_xrank"],
    "FULL_WITH_RRG":["price_score_xrank","price_rs63_rank_xrank","price_rs189_rank_xrank","internal_score_xrank","internal_delta20_xrank","flow20_pct_aum_xrank","rrg_trend_xrank","rrg_momentum_xrank","rrg_accel_xrank"],
}


def safe(x):
    if isinstance(x,dict): return {str(k):safe(v) for k,v in x.items()}
    if isinstance(x,list): return [safe(v) for v in x]
    if isinstance(x,(np.integer,)): return int(x)
    if isinstance(x,(np.floating,float)):
        z=float(x); return z if np.isfinite(z) else None
    if isinstance(x,pd.Timestamp): return x.isoformat()
    return x


def boot(series:pd.Series,calendar:pd.DatetimeIndex,reps:int=10000,seed:int=38,block:int=20)->dict:
    s=series.reindex(pd.DatetimeIndex(calendar)); b=np.arange(len(s))//block
    z=pd.DataFrame({"x":pd.to_numeric(s,errors="coerce").to_numpy(),"b":b}).dropna()
    if z.empty:return {"n":0}
    a=z.groupby("b",observed=True).x.agg(["sum","count"]); sums=a["sum"].to_numpy(float); counts=a["count"].to_numpy(float)
    rng=np.random.default_rng(seed); n=len(a); draws=np.empty(reps)
    for i in range(reps):
        ix=rng.integers(0,n,n); draws[i]=sums[ix].sum()/counts[ix].sum()
    lo,hi=np.quantile(draws,[.025,.975]); p=2*min(float((draws<=0).mean()),float((draws>=0).mean()))
    return {"n":int(len(z)),"blocks":int(n),"mean":float(z.x.mean()),"lo":float(lo),"hi":float(hi),"p_two":float(min(1,p))}


def design(d:pd.DataFrame,features:list[str])->np.ndarray:
    x=d[features].to_numpy(float); dum=np.column_stack([(d.sector.to_numpy()==s).astype(float) for s in GICS[1:]])
    return np.column_stack([np.ones((len(d),1)),x,dum])


def fit(train:pd.DataFrame,features:list[str])->np.ndarray:
    z=train.dropna(subset=features+["rel_fwd1_cs"]).copy()
    return np.linalg.lstsq(design(z,features),z.rel_fwd1_cs.to_numpy(float),rcond=None)[0]


def residualize(d:pd.DataFrame,features:list[str],beta:np.ndarray)->pd.DataFrame:
    z=d.dropna(subset=features+["rel_fwd1_cs"]).copy(); z["pred"]=design(z,features)@beta; z["resid"]=z.rel_fwd1_cs-z.pred
    return z


def state_by_date(d:pd.DataFrame,cut:float)->pd.Series:
    r=d.groupby("date",observed=True).duration_shock_z5.first().sort_index()
    return pd.Series(np.where(r>=cut,1,np.where(r<=-cut,-1,0)),index=r.index)


def directional(d:pd.DataFrame,value:str,top:list[str],bottom:list[str],state:pd.Series)->pd.Series:
    q=d[d.sector.isin(top+bottom)].pivot(index="date",columns="sector",values=value).sort_index(); st=state.reindex(q.index)
    return ((q[top].mean(axis=1)-q[bottom].mean(axis=1))*st).where(st.ne(0))


def threshold_spec_robustness(train:pd.DataFrame,hold:pd.DataFrame)->list[dict]:
    rows=[]; cal=pd.DatetimeIndex(sorted(hold.date.unique()))
    for spec,features in FEATURE_SPECS.items():
        beta=fit(train,features); h=residualize(hold,features,beta)
        for cut in (.50,.75,1.00,1.25):
            st=state_by_date(h,cut); s=directional(h,"resid",TOP,BOTTOM,st); b=boot(s,cal,10000,1000+int(cut*100)+len(features))
            rows.append({"spec":spec,"cut":cut,"mean_bps":float(s.mean()*1e4),**b})
    return rows


def permutation_specificity(train:pd.DataFrame,hold:pd.DataFrame)->dict:
    features=FEATURE_SPECS["FULL_WITH_RRG"]; beta=fit(train,features); h=residualize(hold,features,beta); st=state_by_date(h,.75)
    q=h.pivot(index="date",columns="sector",values="resid").sort_index(); active=st.ne(0)
    vals=[]
    for top in itertools.combinations(GICS,2):
        remain=[s for s in GICS if s not in top]
        for bottom in itertools.combinations(remain,2):
            s=((q[list(top)].mean(axis=1)-q[list(bottom)].mean(axis=1))*st).where(active)
            vals.append((top,bottom,float(s.mean())))
    observed=next(v[2] for v in vals if set(v[0])==set(TOP) and set(v[1])==set(BOTTOM))
    arr=np.array([v[2] for v in vals]); rank=int((arr>observed).sum()+1)
    return {"ordered_disjoint_2v2_groups":int(len(arr)),"observed_mean_bps":float(observed*1e4),"rank_high_to_low":rank,"percentile":float((arr<observed).mean()),"empirical_fraction_ge_observed":float((arr>=observed).mean()),"max_mean_bps":float(arr.max()*1e4)}


def episode_starts(state:pd.Series)->pd.DatetimeIndex:
    prev=state.shift(1).fillna(0); return pd.DatetimeIndex(state[(state.ne(0))&(state.ne(prev))].index)


def event_start_test(train:pd.DataFrame,hold:pd.DataFrame)->dict:
    features=FEATURE_SPECS["FULL_WITH_RRG"]; beta=fit(train,features); h=residualize(hold,features,beta); st=state_by_date(h,.75); starts=episode_starts(st)
    cal=pd.DatetimeIndex(sorted(h.date.unique())); out={"event_starts":int(len(starts))}
    for value in ["rel_fwd1","resid"]:
        q=h[h.sector.isin(TOP+BOTTOM)].pivot(index="date",columns="sector",values=value).sort_index()
        s=(q[TOP].mean(axis=1)-q[BOTTOM].mean(axis=1))*st.reindex(q.index); s=s.where(pd.Series(q.index.isin(starts),index=q.index))
        b=boot(s,cal,10000,2000+len(value)); out[value]={"mean_bps":float(s.mean()*1e4),**b}
    return out


def feature_catchup(panel:pd.DataFrame)->dict:
    h=panel[(panel.date>=HOLD_START)&(panel.date<=END)].copy(); st=state_by_date(h,.75); starts=episode_starts(st)
    calendar=pd.DatetimeIndex(sorted(h.date.unique())); pos={d:i for i,d in enumerate(calendar)}; out={}
    for feat in FEATURE_SPECS["FULL_WITH_RRG"]:
        q=h.pivot(index="date",columns="sector",values=feat).sort_index(); rows=[]
        for d in starts:
            i=pos.get(d); state=int(st.loc[d]);
            if i is None or d not in q.index: continue
            g0=(q.loc[d,TOP].mean()-q.loc[d,BOTTOM].mean())*state; rec={"date":d,"g0":g0}
            for off in (1,3,5):
                if i+off<len(calendar) and calendar[i+off] in q.index:
                    dd=calendar[i+off]; g=(q.loc[dd,TOP].mean()-q.loc[dd,BOTTOM].mean())*state; rec[f"delta{off}"]=g-g0
            rows.append(rec)
        z=pd.DataFrame(rows).set_index("date"); block={"n_events":int(len(z)),"gap_t0_mean":float(z.g0.mean())}
        for off in (1,3,5):
            b=boot(z[f"delta{off}"],calendar,5000,3000+off+len(feat)); block[f"delta_t{off}"]={"mean":float(z[f"delta{off}"].mean()),**b}
        out[feat]=block
    return out


def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--panel",required=True); ap.add_argument("--output",required=True)
    args=ap.parse_args(); out=Path(args.output); out.mkdir(parents=True,exist_ok=True)
    p=pd.read_csv(args.panel,parse_dates=["date"]); p=p[p.date<=END].copy()
    train=p[(p.date>=pd.Timestamp("2022-04-18"))&(p.date<=TRAIN_END)].copy(); hold=p[(p.date>=HOLD_START)&(p.date<=END)].copy()
    rows=threshold_spec_robustness(train,hold); pd.DataFrame(rows).to_csv(out/"threshold_spec_robustness.csv",index=False)
    result={
        "status":"RESEARCH_ONLY_NO_RULE_CHANGE",
        "frozen_primary":{"factor":"duration_shock_z5","base_cut":.75,"tightening_favor":TOP,"easing_favor":BOTTOM},
        "train":"2022-04-18..2023-12-31","holdout":"2024-01-01..2026-03-20",
        "threshold_and_baseline_spec":rows,
        "group_permutation_holdout":permutation_specificity(train,hold),
        "event_start_holdout":event_start_test(train,hold),
        "feature_catchup_after_event_start_holdout":feature_catchup(p),
        "interpretation_guardrail":"Event-start feature changes distinguish true lead from redundancy: positive future gap means that existing indicator moves toward the frozen rate direction after the shock. RRG may already be aligned, so do not call the rate signal universally leading if RRG catch-up is absent.",
    }
    (out/"summary.json").write_text(json.dumps(safe(result),ensure_ascii=False,indent=2),encoding="utf-8")
    print("===RATE_ROTATION_INCREMENTAL_ROBUSTNESS==="); print(json.dumps(safe(result),ensure_ascii=False,separators=(",",":"))); print("===END===")

if __name__=="__main__":main()
