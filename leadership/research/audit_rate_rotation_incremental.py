from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

GICS = ["XLB","XLC","XLE","XLF","XLI","XLK","XLP","XLRE","XLU","XLV","XLY"]
TOP = ["XLF","XLE"]
BOTTOM = ["XLRE","XLV"]
LOAD = {"XLF":1.0,"XLE":1.0,"XLRE":-1.0,"XLV":-1.0}
CUT = 0.75
TRAIN_END = pd.Timestamp("2023-12-31")
HOLD_START = pd.Timestamp("2024-01-01")
END = pd.Timestamp("2026-03-20")
BASE_FEATURES = [
    "price_score_xrank",
    "price_rs63_rank_xrank",
    "price_rs189_rank_xrank",
    "internal_score_xrank",
    "internal_delta20_xrank",
    "flow20_pct_aum_xrank",
    "rrg_trend_xrank",
    "rrg_momentum_xrank",
    "rrg_accel_xrank",
]


def safe(x):
    if isinstance(x, dict): return {str(k): safe(v) for k,v in x.items()}
    if isinstance(x, list): return [safe(v) for v in x]
    if isinstance(x, (np.integer,)): return int(x)
    if isinstance(x, (np.floating, float)):
        z=float(x); return z if np.isfinite(z) else None
    if isinstance(x, pd.Timestamp): return x.isoformat()
    return x


def block_boot_active(series: pd.Series, calendar: pd.DatetimeIndex, reps: int=10000, seed: int=38, block: int=20) -> dict:
    idx=pd.DatetimeIndex(calendar)
    s=series.reindex(idx)
    b=np.arange(len(idx))//block
    z=pd.DataFrame({"x":pd.to_numeric(s,errors="coerce").to_numpy(),"b":b}).dropna()
    if z.empty: return {"n":0}
    agg=z.groupby("b",observed=True).x.agg(["sum","count"])
    sums=agg["sum"].to_numpy(float); counts=agg["count"].to_numpy(float)
    rng=np.random.default_rng(seed); n=len(agg); draws=np.empty(reps)
    for i in range(reps):
        ix=rng.integers(0,n,n)
        draws[i]=sums[ix].sum()/counts[ix].sum()
    obs=float(z.x.mean()); lo,hi=np.quantile(draws,[.025,.975])
    p=2*min(float((draws<=0).mean()),float((draws>=0).mean()))
    return {"n":int(len(z)),"blocks":int(n),"mean":obs,"lo":float(lo),"hi":float(hi),"p_two":float(min(1,p))}


def add_rrg(panel: pd.DataFrame) -> pd.DataFrame:
    p=panel.copy()
    epx=p.pivot(index="date",columns="sector",values="etf_close").sort_index()
    spx=p.groupby("date",observed=True).spy_close.first().sort_index()
    eret=epx.pct_change(fill_method=None); sret=spx.pct_change(fill_method=None)
    rel=np.log1p(eret.clip(lower=-.999999)).sub(np.log1p(sret.clip(lower=-.999999)),axis=0).fillna(0.0).cumsum()
    slow=rel.ewm(span=63,adjust=False,min_periods=30).mean()
    scale=rel.diff().rolling(63,min_periods=30).std()*math.sqrt(63)
    trend=((rel-slow)/scale.replace(0,np.nan)).clip(-5,5)
    mom=trend-trend.shift(5); accel=mom-mom.shift(5)
    rrg=pd.concat({"rrg_trend":trend.stack(),"rrg_momentum":mom.stack(),"rrg_accel":accel.stack()},axis=1).reset_index()
    rrg.columns=["date","sector","rrg_trend","rrg_momentum","rrg_accel"]
    return p.merge(rrg,on=["date","sector"],how="left",validate="one_to_one")


def add_outcomes(panel: pd.DataFrame) -> pd.DataFrame:
    p=panel.copy()
    epx=p.pivot(index="date",columns="sector",values="etf_close").sort_index()
    spx=p.groupby("date",observed=True).spy_close.first().sort_index()
    ratio=epx.div(spx,axis=0)
    outs={
        "rel_fwd1":ratio.shift(-1)/ratio-1.0,
        "rel_d2_5":ratio.shift(-5)/ratio.shift(-1)-1.0,
        "rel_d6_10":ratio.shift(-10)/ratio.shift(-5)-1.0,
        "rel_fwd5_ratio":ratio.shift(-5)/ratio-1.0,
        "rel_fwd10_ratio":ratio.shift(-10)/ratio-1.0,
    }
    z=pd.concat({k:v.stack() for k,v in outs.items()},axis=1).reset_index()
    z.columns=["date","sector",*outs.keys()]
    return p.merge(z,on=["date","sector"],how="left",validate="one_to_one")


def build_panel(pit_path: str, proxy_path: str, rates_path: str) -> pd.DataFrame:
    pit=pd.read_csv(pit_path,parse_dates=["date"])
    proxy=pd.read_csv(proxy_path,parse_dates=["date"])
    rates=pd.read_csv(rates_path,parse_dates=["date"])
    pit=pit[(pit.date<=END)&pit.sector.isin(GICS)].copy()
    pure=proxy[["date","sector","etf_close","spy_close","price_rs63_rank","price_rs189_rank"]].drop_duplicates(["date","sector"])
    p=pit.merge(pure,on=["date","sector"],how="left",validate="one_to_one")
    if p[["etf_close","spy_close","price_rs63_rank","price_rs189_rank"]].isna().any().any():
        raise RuntimeError("pure-price merge has missing values")
    p=add_rrg(p)
    p=add_outcomes(p)
    p=p.sort_values(["sector","date"])
    p["internal_delta20"]=p.groupby("sector",observed=True).internal_score.diff(20)
    rank_cols=["price_score","price_rs63_rank","price_rs189_rank","internal_score","internal_delta20","flow20_pct_aum","rrg_trend","rrg_momentum","rrg_accel"]
    for c in rank_cols:
        p[c+"_xrank"]=p.groupby("date",observed=True)[c].rank(pct=True)-.5
    p=p.merge(rates[["date","duration_shock_z5"]],on="date",how="left",validate="many_to_one")
    p["sector_rate_loading"]=p.sector.map(LOAD).fillna(0.0)
    z=pd.to_numeric(p.duration_shock_z5,errors="coerce")
    p["shock_state"]=np.where(z>=CUT,1,np.where(z<=-CUT,-1,0))
    p["rate_overlay"]=p.sector_rate_loading*p.shock_state
    for c in ["rel_fwd1","rel_fwd5_ratio","rel_fwd10_ratio"]:
        p[c+"_cs"]=p[c]-p.groupby("date",observed=True)[c].transform("mean")
    return p.sort_values(["date","sector"]).reset_index(drop=True)


def design(data: pd.DataFrame, add_rate: bool=False) -> np.ndarray:
    x=data[BASE_FEATURES].to_numpy(float)
    dummies=np.column_stack([(data.sector.to_numpy()==s).astype(float) for s in GICS[1:]])
    mats=[np.ones((len(data),1)),x,dummies]
    if add_rate: mats.append(data[["rate_overlay"]].to_numpy(float))
    return np.column_stack(mats)


def fit(train: pd.DataFrame, outcome: str, add_rate: bool=False) -> np.ndarray:
    cols=BASE_FEATURES+[outcome]+(["rate_overlay"] if add_rate else [])
    z=train.dropna(subset=cols).copy()
    return np.linalg.lstsq(design(z,add_rate),z[outcome].to_numpy(float),rcond=None)[0]


def daily_rank_ic(z: pd.DataFrame, y: str, pred: str) -> float:
    vals=[]
    for _,g in z.groupby("date",observed=True):
        if len(g)<5: continue
        vals.append(g[y].rank().corr(g[pred].rank()))
    return float(np.nanmean(vals)) if vals else np.nan


def model_metrics(data: pd.DataFrame, outcome: str, b0: np.ndarray, b1: np.ndarray) -> dict:
    z=data.dropna(subset=BASE_FEATURES+[outcome]).copy()
    y=z[outcome].to_numpy(float); p0=design(z,False)@b0; p1=design(z,True)@b1
    z["p0"]=p0; z["p1"]=p1
    active=z.sector.isin(TOP+BOTTOM)&z.shock_state.ne(0)
    return {
        "n":int(len(z)),
        "baseline_mse":float(np.mean((y-p0)**2)),
        "augmented_mse":float(np.mean((y-p1)**2)),
        "mse_change_pct":float((np.mean((y-p1)**2)/np.mean((y-p0)**2)-1)*100),
        "baseline_daily_rank_ic":daily_rank_ic(z,outcome,"p0"),
        "augmented_daily_rank_ic":daily_rank_ic(z,outcome,"p1"),
        "active_four_baseline_mse":float(np.mean((y[active]-p0[active])**2)),
        "active_four_augmented_mse":float(np.mean((y[active]-p1[active])**2)),
        "active_four_mse_change_pct":float((np.mean((y[active]-p1[active])**2)/np.mean((y[active]-p0[active])**2)-1)*100),
    }


def directional_series(z: pd.DataFrame, value: str) -> pd.Series:
    q=z[z.sector.isin(TOP+BOTTOM)].pivot(index="date",columns="sector",values=value).sort_index()
    st=z.groupby("date",observed=True).shock_state.first().reindex(q.index)
    return ((q[TOP].mean(axis=1)-q[BOTTOM].mean(axis=1))*st).where(st.ne(0))


def feature_alignment(z: pd.DataFrame) -> dict:
    out={}
    for feat in BASE_FEATURES:
        s=directional_series(z,feat).dropna()
        out[feat]={"n":int(len(s)),"mean_directional_gap":float(s.mean()),"aligned_fraction":float((s>0).mean())}
    return out


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--pit",required=True); ap.add_argument("--proxy",required=True); ap.add_argument("--rates",required=True); ap.add_argument("--output",required=True)
    args=ap.parse_args(); out=Path(args.output); out.mkdir(parents=True,exist_ok=True)
    p=build_panel(args.pit,args.proxy,args.rates)
    p.to_csv(out/"rate_rotation_incremental_panel.csv.gz",index=False,compression="gzip")
    train=p[(p.date>=pd.Timestamp("2022-04-18"))&(p.date<=TRAIN_END)].copy()
    hold=p[(p.date>=HOLD_START)&(p.date<=END)].copy()
    outcome="rel_fwd1_cs"
    b0=fit(train,outcome,False); b1=fit(train,outcome,True)

    residual_tests={}
    raw_leadlag={}
    for name,z in [("TRAIN_2022_2023",train),("HOLDOUT_2024_2026",hold)]:
        zz=z.dropna(subset=BASE_FEATURES+[outcome]).copy()
        zz["baseline_pred"]=design(zz,False)@b0
        zz["residual"]=zz[outcome]-zz.baseline_pred
        cal=pd.DatetimeIndex(sorted(zz.date.unique()))
        rs=directional_series(zz,"residual")
        residual_tests[name]={**block_boot_active(rs,cal,reps=10000,seed=38),"mean_bps":float(rs.mean()*1e4)}
        raw_leadlag[name]={}
        for col in ["rel_fwd1","rel_d2_5","rel_d6_10","rel_fwd5_ratio","rel_fwd10_ratio"]:
            s=directional_series(zz,col)
            b=block_boot_active(s,cal,reps=10000,seed=100+len(col))
            raw_leadlag[name][col]={**b,"mean_bps":float(s.mean()*1e4)}

    # Does the rate signal work before/against the existing Rotation stack?
    hz=hold.dropna(subset=BASE_FEATURES+[outcome]).copy()
    hz["baseline_pred"]=design(hz,False)@b0
    actual=directional_series(hz,"rel_fwd1")
    pred=directional_series(hz,"baseline_pred")
    al=pd.DataFrame({"actual":actual,"pred":pred}).dropna()
    al["aligned"]=al.pred>0
    calh=pd.DatetimeIndex(sorted(hz.date.unique()))
    alignment={}
    for flag,label in [(False,"BASELINE_OPPOSED"),(True,"BASELINE_ALIGNED")]:
        s=al.actual.where(al.aligned.eq(flag))
        b=block_boot_active(s,calh,reps=10000,seed=501 if flag else 500)
        alignment[label]={**b,"mean_bps":float(s.mean()*1e4)}

    yearly={}
    hz["residual"]=hz[outcome]-hz.baseline_pred
    for year,g in hz.groupby(hz.date.dt.year,observed=True):
        s=directional_series(g,"residual"); cal=pd.DatetimeIndex(sorted(g.date.unique()))
        b=block_boot_active(s,cal,reps=5000,seed=1000+int(year))
        yearly[str(int(year))]={**b,"mean_bps":float(s.mean()*1e4)}

    direction={}
    for state,label in [(1,"TIGHTENING"),(-1,"EASING")]:
        g=hz[hz.shock_state.eq(state)].copy(); s=directional_series(g,"residual"); cal=pd.DatetimeIndex(sorted(g.date.unique()))
        b=block_boot_active(s,cal,reps=5000,seed=2000+state)
        direction[label]={**b,"mean_bps":float(s.mean()*1e4)}

    result={
        "status":"RESEARCH_ONLY_NO_RULE_CHANGE",
        "data":{
            "pit":"audited cov80 PIT panel: official SSGA shares-outstanding-derived flow + historical-GICS dynamic constituent internals",
            "rrg":"independent RRG-like price-relative vector, same formula as validate_rrg_tail_system.py; not proprietary JdK formula",
            "rate":"Duration Shock 5D = mean(z252 5d change in 10Y nominal, z252 5d change in 10Y real)",
            "signal_cut":CUT,
            "frozen_sector_loading":{"tightening_favor":TOP,"easing_favor":BOTTOM},
            "signal_timing":"date-t close information only; outcomes begin after date-t close",
        },
        "train":"2022-04-18..2023-12-31",
        "holdout":"2024-01-01..2026-03-20",
        "baseline_features":BASE_FEATURES,
        "primary_residual_test":residual_tests,
        "lead_lag":raw_leadlag,
        "baseline_alignment_holdout":alignment,
        "feature_alignment_holdout":feature_alignment(hz),
        "model_metrics":{
            "train":model_metrics(train,outcome,b0,b1),
            "holdout":model_metrics(hold,outcome,b0,b1),
            "train_rate_overlay_coef_bps":float(b1[-1]*1e4),
        },
        "holdout_residual_by_year":yearly,
        "holdout_residual_by_rate_direction":direction,
        "decision_rule":"Rate overlay is incremental only if holdout residual signed spread remains positive with 20-day block-bootstrap support and is not confined to baseline-aligned dates. No production adoption from this audit alone.",
    }
    (out/"summary.json").write_text(json.dumps(safe(result),ensure_ascii=False,indent=2),encoding="utf-8")
    print("===RATE_ROTATION_INCREMENTAL===")
    print(json.dumps(safe(result),ensure_ascii=False,separators=(",",":")))
    print("===END===")

if __name__=="__main__": main()
