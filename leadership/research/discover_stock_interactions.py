from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import fisher_exact
from sklearn.tree import DecisionTreeClassifier, _tree

import validate_early_rotation as er
import validate_confirmed_leadership as cl
import validate_ignition_quality as iq
import validate_sector_stock_stack as ss

ANALYSIS_START = pd.Timestamp("2016-01-04")
ANALYSIS_END = pd.Timestamp("2026-06-20")
DISCOVERY_END = pd.Timestamp("2021-12-31")
VALIDATION_START = pd.Timestamp("2022-01-01")
VALIDATION_END = pd.Timestamp("2024-12-31")
HOLDOUT_START = pd.Timestamp("2025-01-01")
HOLDOUT_END = ANALYSIS_END
WINNER_EXCESS_20 = 0.10
TOP_THEME_CUTOFF = 0.80
MIN_LEAF = 250
MAX_DEPTH = 3

FEATURES = [
    "rs21_pct", "rs63_pct", "rs252_pct",
    "rs21_delta5", "rs21_delta10", "rs21_delta20", "rs63_delta20",
    "term21_63", "term21_252", "rs21_ignition",
    "flow_share_ratio_3v20", "flow_share_ratio_5v20", "flow_share_ratio_10v20",
    "flow_share_change5", "theme_hhi_ratio_5v20",
    "stock_excess5", "stock_excess10",
    "rvol20", "signed_rvol20", "close_location",
    "ema21_atr", "sma50_atr", "dist_prior_high20", "dist_prior_high63",
    "dist_52w_high", "compression_5v20", "gap_pct", "vol_dry_5v20",
    "up_down_dv_balance10", "accum_dist_count10",
    "theme_rs63", "theme_rs_delta20", "industry_rs", "sector_rs", "breadth",
    "momentum_age", "w30_slope4", "w30_distance",
]

MODEL_FEATURES = {
    "FULL": FEATURES,
    "NO_FLOW": [f for f in FEATURES if not (f.startswith("flow_") or f.startswith("theme_hhi"))],
    "NO_IGNITION": [f for f in FEATURES if f != "rs21_ignition"],
}


def safe(v: Any) -> Any:
    if isinstance(v, dict): return {str(k): safe(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)): return [safe(x) for x in v]
    if isinstance(v, np.integer): return int(v)
    if isinstance(v, (np.floating, float)):
        x=float(v); return x if math.isfinite(x) else None
    if isinstance(v, pd.Timestamp): return v.isoformat()
    return v


def theme_rank(block: pd.DataFrame) -> pd.DataFrame:
    return block.rank(axis=1, pct=True, method="average")


def rolling_prior_mean(df: pd.DataFrame, current_window: int, prior_window: int = 20) -> tuple[pd.DataFrame, pd.DataFrame]:
    cur=df.rolling(current_window, min_periods=max(2, current_window//2)).mean()
    prior=df.shift(current_window).rolling(prior_window, min_periods=max(10, prior_window//2)).mean()
    return cur, prior


def future_window_extreme(df: pd.DataFrame, window: int, how: str) -> pd.DataFrame:
    rev=df.shift(-1).iloc[::-1]
    if how == "max": out=rev.rolling(window, min_periods=1).max()
    else: out=rev.rolling(window, min_periods=1).min()
    return out.iloc[::-1]


def momentum_run_age(mask: pd.Series) -> pd.Series:
    b=mask.fillna(False).astype(bool)
    groups=(b != b.shift(1, fill_value=False)).cumsum()
    age=b.groupby(groups).cumcount()+1
    return age.where(b, 0).astype(float)


def weekly_state(close: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    weekly=close.resample("W-FRI").last()
    w30=weekly.rolling(30, min_periods=24).mean()
    slope=w30/w30.shift(4)-1.0
    dist=weekly/w30-1.0
    wi=weekly.index.to_numpy(dtype="datetime64[ns]")
    di=close.index.to_numpy(dtype="datetime64[ns]")
    pos=np.searchsorted(wi, di, side="left")-1
    valid=pos>=0
    slope_arr=np.full(close.shape, np.nan, dtype=float)
    dist_arr=np.full(close.shape, np.nan, dtype=float)
    if valid.any():
        s=slope.to_numpy(float); d=dist.to_numpy(float)
        slope_arr[valid,:]=s[pos[valid],:]
        dist_arr[valid,:]=d[pos[valid],:]
    return (
        pd.DataFrame(slope_arr,index=close.index,columns=close.columns),
        pd.DataFrame(dist_arr,index=close.index,columns=close.columns),
    )


def cluster_diff_ci(frame: pd.DataFrame, mask_hi: pd.Series, value: str, cluster: str, seed: int, reps: int=2500) -> list[float|None]:
    hi=frame.loc[mask_hi,[cluster,value]].dropna(); lo=frame.loc[~mask_hi,[cluster,value]].dropna()
    if hi.empty or lo.empty: return [None,None]
    a=hi.groupby(cluster,observed=True)[value].mean(); b=lo.groupby(cluster,observed=True)[value].mean()
    common=a.index.intersection(b.index)
    rng=np.random.default_rng(seed)
    if len(common)>=5:
        d=(a.loc[common]-b.loc[common]).to_numpy(float)
        if len(d)<2: return [None,None]
        draws=rng.choice(d,size=(reps,len(d)),replace=True).mean(axis=1)
    else:
        av=a.to_numpy(float); bv=b.to_numpy(float)
        if len(av)<2 or len(bv)<2: return [None,None]
        draws=np.array([rng.choice(av,len(av),replace=True).mean()-rng.choice(bv,len(bv),replace=True).mean() for _ in range(reps)])
    q=np.quantile(draws,[.025,.975]); return [float(q[0]),float(q[1])]


def outcome_summary(frame: pd.DataFrame, mask: pd.Series, seed: int) -> dict[str,Any]:
    mask=mask.reindex(frame.index,fill_value=False).astype(bool)
    a=frame.loc[mask,"pioneer_winner10"].dropna().astype(bool); b=frame.loc[~mask,"pioneer_winner10"].dropna().astype(bool)
    if len(a) and len(b):
        _,p=fisher_exact([[int(a.sum()),len(a)-int(a.sum())],[int(b.sum()),len(b)-int(b.sum())]],alternative="greater")
    else: p=np.nan
    out={
        "selected_n":int(mask.sum()), "other_n":int((~mask).sum()),
        "winner_rate":float(a.mean()) if len(a) else None,
        "other_winner_rate":float(b.mean()) if len(b) else None,
        "winner_lift_pp":float(100*(a.mean()-b.mean())) if len(a) and len(b) else None,
        "fisher_greater_p":float(p) if np.isfinite(p) else None,
        "winner_date_ci95":cluster_diff_ci(frame,mask,"pioneer_winner10","entry_date",seed),
        "winner_theme_ci95":cluster_diff_ci(frame,mask,"pioneer_winner10","theme",seed+1000),
    }
    for h in (5,10,20):
        col=f"stock_minus_peers_{h}"; x=frame.loc[mask,col].dropna(); y=frame.loc[~mask,col].dropna()
        out[f"peer{h}"]={
            "selected_mean":float(x.mean()) if len(x) else None,
            "other_mean":float(y.mean()) if len(y) else None,
            "diff":float(x.mean()-y.mean()) if len(x) and len(y) else None,
            "date_ci95":cluster_diff_ci(frame,mask,col,"entry_date",seed+2000+h),
            "theme_ci95":cluster_diff_ci(frame,mask,col,"theme",seed+3000+h),
        }
    for col in ("future_theme_top20","mfe20","mae20"):
        x=pd.to_numeric(frame.loc[mask,col],errors="coerce").dropna(); y=pd.to_numeric(frame.loc[~mask,col],errors="coerce").dropna()
        out[col]={"selected_mean":float(x.mean()) if len(x) else None,"other_mean":float(y.mean()) if len(y) else None,"diff":float(x.mean()-y.mean()) if len(x) and len(y) else None}
    return out


def extract_leaf_rules(model: DecisionTreeClassifier, feature_names: list[str]) -> dict[int,list[str]]:
    tree=model.tree_; rules:dict[int,list[str]]={}
    def walk(node:int,path:list[str])->None:
        if tree.feature[node] != _tree.TREE_UNDEFINED:
            f=feature_names[tree.feature[node]]; th=tree.threshold[node]
            walk(tree.children_left[node],path+[f"{f} <= {th:.6g}"])
            walk(tree.children_right[node],path+[f"{f} > {th:.6g}"])
        else: rules[int(node)]=path
    walk(0,[]); return rules


def build_candidates(root:Path, max_tickers:int, batch_size:int, min_members:int) -> tuple[pd.DataFrame,dict[str,Any]]:
    snapshot=er.load_json(root/"sector_snapshot.json")
    theme_members_all,taxonomy_candidates=er.extract_theme_members(snapshot)
    industry_map=er.read_industry_map(root/"industry_map.json")
    universe=er.read_universe_symbols(root/"universe.csv")
    allowed=set(industry_map)&universe
    selected=er.stratified_symbols(theme_members_all,allowed,max_tickers)
    requested=selected+(["SPY"] if "SPY" not in selected else [])
    ds=str((ANALYSIS_START-pd.Timedelta(days=1100)).date()); de=str((ANALYSIS_END+pd.Timedelta(days=120)).date())
    ohlcv,download_diag=iq.download_ohlcv(requested,ds,de,batch_size)
    close_all=ohlcv["close"]; stock_cols=[s for s in selected if s in close_all.columns]
    close=close_all[stock_cols]; high=ohlcv["high"][stock_cols]; low=ohlcv["low"][stock_cols]; volume=ohlcv["volume"][stock_cols]
    stock_ret=er.arithmetic_returns(close); spy_ret=er.arithmetic_returns(close_all[["SPY"]])["SPY"]
    theme_members={t:[s for s in m if s in stock_cols] for t,m in theme_members_all.items()}
    theme_ret=er.grouped_equal_weight(stock_ret,theme_members,min_members)
    industry_groups:dict[str,list[str]]={}; sector_groups:dict[str,list[str]]={}
    for s in stock_cols:
        pair=industry_map.get(s)
        if not pair: continue
        sec,ind=pair
        if sec: sector_groups.setdefault(sec,[]).append(s)
        if ind: industry_groups.setdefault(ind,[]).append(s)
    industry_ret=er.grouped_equal_weight(stock_ret,industry_groups,min_members)
    sector_ret=er.grouped_equal_weight(stock_ret,sector_groups,min_members)
    industry_weights=er.build_parent_weights(theme_members_all,industry_map)
    sector_weights=ss.build_sector_weights(theme_members_all,industry_map)
    common_themes=sorted(set(theme_ret.columns)&set(industry_weights)&set(sector_weights)); theme_ret=theme_ret[common_themes]
    theme63=er.period_return(theme_ret,63); spy63=er.period_return(spy_ret,63)
    theme_pct=theme63.sub(spy63,axis=0).rank(axis=1,pct=True,method="average")*100.0
    industry63=er.period_return(industry_ret,63); industry_pct=industry63.sub(spy63,axis=0).rank(axis=1,pct=True,method="average")*100.0
    sector63=er.period_return(sector_ret,63); sector_pct=sector63.sub(spy63,axis=0).rank(axis=1,pct=True,method="average")*100.0
    parent_industry=er.weighted_matrix(industry_pct,industry_weights,common_themes)
    parent_sector=er.weighted_matrix(sector_pct,sector_weights,common_themes)
    breadth=er.breadth_above_ema21(close,theme_members,min_members).reindex(columns=common_themes)
    momentum=cl.momentum_mask(theme_pct,parent_industry,breadth)

    base=iq.compute_feature_matrices(ohlcv,stock_cols,stock_ret)
    p5=er.period_return(stock_ret,5); p10=er.period_return(stock_ret,10); p21=er.period_return(stock_ret,21); p63=er.period_return(stock_ret,63); p252=er.period_return(stock_ret,252)
    fwd={h:close.shift(-h)/close-1.0 for h in (5,10,20)}
    future_high20=future_window_extreme(high,20,"max"); future_low20=future_window_extreme(low,20,"min")
    mfe20=future_high20/close-1.0; mae20=future_low20/close-1.0
    prior_high252=high.shift(1).rolling(252,min_periods=160).max(); dist52=close/prior_high252-1.0
    prior_vol20=volume.shift(1).rolling(20,min_periods=12).mean(); vol_dry=volume.shift(1).rolling(5,min_periods=4).mean()/prior_vol20.replace(0,np.nan)
    dv=close*volume; signed_dv=dv*np.sign(stock_ret); ud10=signed_dv.rolling(10,min_periods=6).sum()/dv.rolling(10,min_periods=6).sum().replace(0,np.nan)
    accum=((stock_ret>0)&(base["rvol20"]>=1.2)).astype(float); distrib=((stock_ret<0)&(base["rvol20"]>=1.2)).astype(float); ad10=(accum-distrib).rolling(10,min_periods=6).sum()
    w30_slope,w30_dist=weekly_state(close)

    rows=[]; start=ANALYSIS_START; end=ANALYSIS_END
    for ti,t in enumerate(common_themes):
        if t not in momentum.columns: continue
        qdates=momentum.index[(momentum[t].fillna(False))&(momentum.index>=start)&(momentum.index<=end)]
        members=[s for s in theme_members.get(t,[]) if s in stock_cols]
        if len(qdates)==0 or len(members)<min_members: continue
        nD=len(qdates); nS=len(members); idx=pd.MultiIndex.from_product([qdates,members],names=["entry_date","symbol"])
        part=pd.DataFrame(index=idx).reset_index(); part["theme"]=t
        def put(name:str,mat:pd.DataFrame)->None:
            part[name]=mat.reindex(index=qdates,columns=members).to_numpy(float).reshape(-1)
        r21=theme_rank(p21[members]); r63=theme_rank(p63[members]); r252=theme_rank(p252[members])
        put("rs21_pct",r21); put("rs63_pct",r63); put("rs252_pct",r252)
        put("rs21_delta5",r21-r21.shift(5)); put("rs21_delta10",r21-r21.shift(10)); put("rs21_delta20",r21-r21.shift(20)); put("rs63_delta20",r63-r63.shift(20))
        put("term21_63",r21-r63); put("term21_252",r21-r252)
        ign=(r21>=2/3)&(r21.shift(1)<2/3); put("rs21_ignition",ign.astype(float))
        block_dv=dv[members]; shares=block_dv.div(block_dv.sum(axis=1,min_count=1).replace(0,np.nan),axis=0)
        for win,name in ((3,"flow_share_ratio_3v20"),(5,"flow_share_ratio_5v20"),(10,"flow_share_ratio_10v20")):
            cur,prior=rolling_prior_mean(shares,win,20); put(name,cur/prior.replace(0,np.nan))
        put("flow_share_change5",shares/shares.shift(5).replace(0,np.nan))
        hhi=(shares*shares).sum(axis=1,min_count=1); hcur=hhi.rolling(5,min_periods=3).mean(); hprior=hhi.shift(5).rolling(20,min_periods=10).mean(); hv=(hcur/hprior.replace(0,np.nan)).reindex(qdates).to_numpy(float)
        part["theme_hhi_ratio_5v20"]=np.repeat(hv,nS)
        ex5=p5[members].sub(er.period_return(theme_ret[[t]],5)[t],axis=0); ex10=p10[members].sub(er.period_return(theme_ret[[t]],10)[t],axis=0)
        put("stock_excess5",ex5); put("stock_excess10",ex10)
        for name,mat in (("rvol20",base["rvol20"]),("signed_rvol20",base["signed_rvol20"]),("close_location",base["close_location"]),("ema21_atr",base["ema21_atr"]),("sma50_atr",base["sma50_atr"]),("dist_prior_high20",base["dist_prior_high20"]),("dist_prior_high63",base["dist_prior_high63"]),("compression_5v20",base["compression_5v20"]),("gap_pct",base["gap_pct"]),("dist_52w_high",dist52),("vol_dry_5v20",vol_dry),("up_down_dv_balance10",ud10),("accum_dist_count10",ad10),("w30_slope4",w30_slope),("w30_distance",w30_dist)):
            put(name,mat)
        for name,series in (("theme_rs63",theme_pct[t]),("theme_rs_delta20",theme_pct[t]-theme_pct[t].shift(20)),("industry_rs",parent_industry[t]),("sector_rs",parent_sector[t]),("breadth",breadth[t]),("momentum_age",momentum_run_age(momentum[t]))):
            vals=series.reindex(qdates).to_numpy(float); part[name]=np.repeat(vals,nS)
        for h in (5,10,20):
            fb=fwd[h][members]; sums=fb.sum(axis=1,min_count=2); cnt=fb.count(axis=1); peers=fb.rsub(sums,axis=0).div((cnt-1).replace(0,np.nan),axis=0); excess=fb-peers
            put(f"stock_minus_peers_{h}",excess)
        fb20=fwd[20][members]; rank20=theme_rank(fb20); put("future_theme_rank20",rank20)
        put("mfe20",mfe20); put("mae20",mae20)
        part["future_theme_top20"]=(part["future_theme_rank20"]>=TOP_THEME_CUTOFF).astype(float)
        part["pioneer_winner10"]=(part["stock_minus_peers_20"]>=WINNER_EXCESS_20).astype(float)
        valid=part["stock_minus_peers_20"].notna()&part["rs21_pct"].notna()
        rows.append(part.loc[valid])
        if (ti+1)%25==0: print(f"THEMES {ti+1}/{len(common_themes)} rows={sum(len(x) for x in rows)}",flush=True)
    if not rows: raise RuntimeError("No candidate rows")
    frame=pd.concat(rows,ignore_index=True)
    diag={"selected_stocks":len(stock_cols),"candidate_rows":len(frame),"dates":int(frame.entry_date.nunique()),"themes":int(frame.theme.nunique()),"download":download_diag,"taxonomy":taxonomy_candidates}
    return frame,diag


def split_frames(frame:pd.DataFrame)->dict[str,pd.DataFrame]:
    d=pd.to_datetime(frame.entry_date)
    return {
        "DISCOVERY_2016_2021":frame[(d>=ANALYSIS_START)&(d<=DISCOVERY_END)].copy(),
        "VALIDATION_2022_2024":frame[(d>=VALIDATION_START)&(d<=VALIDATION_END)].copy(),
        "HOLDOUT_2025_2026H1":frame[(d>=HOLDOUT_START)&(d<=HOLDOUT_END)].copy(),
    }


def fit_model(discovery:pd.DataFrame, features:list[str], seed:int)->tuple[DecisionTreeClassifier,dict[str,float],dict[int,list[str]]]:
    med={f:float(pd.to_numeric(discovery[f],errors="coerce").median()) for f in features}
    X=pd.DataFrame({f:pd.to_numeric(discovery[f],errors="coerce").fillna(med[f]) for f in features})
    y=discovery["pioneer_winner10"].astype(int)
    model=DecisionTreeClassifier(max_depth=MAX_DEPTH,min_samples_leaf=MIN_LEAF,min_samples_split=MIN_LEAF*2,random_state=seed,class_weight=None)
    model.fit(X,y); return model,med,extract_leaf_rules(model,features)


def leaf_ids(model:DecisionTreeClassifier, frame:pd.DataFrame, features:list[str], med:dict[str,float])->np.ndarray:
    X=pd.DataFrame({f:pd.to_numeric(frame[f],errors="coerce").fillna(med[f]) for f in features})
    return model.apply(X)


def run_model(name:str,frames:dict[str,pd.DataFrame],features:list[str],seed:int)->dict[str,Any]:
    discovery=frames["DISCOVERY_2016_2021"]
    model,med,rules=fit_model(discovery,features,seed)
    leaves_by_split={k:leaf_ids(model,v,features,med) for k,v in frames.items()}
    base={k:float(v.pioneer_winner10.mean()) for k,v in frames.items()}
    leaf_table=[]
    all_leaves=sorted(rules)
    for leaf in all_leaves:
        rec={"leaf":int(leaf),"rule":rules[leaf]}
        for sk,fr in frames.items():
            mask=pd.Series(leaves_by_split[sk]==leaf,index=fr.index)
            n=int(mask.sum()); rate=float(fr.loc[mask,"pioneer_winner10"].mean()) if n else None
            rec[sk]={"n":n,"winner_rate":rate,"lift_pp":100*(rate-base[sk]) if rate is not None else None}
        leaf_table.append(rec)
    validated=[]
    for rec in leaf_table:
        d=rec["DISCOVERY_2016_2021"]; v=rec["VALIDATION_2022_2024"]
        if d["n"]>=MIN_LEAF and v["n"]>=100 and d["lift_pp"] is not None and v["lift_pp"] is not None and d["lift_pp"]>=2.5 and v["lift_pp"]>=1.5:
            validated.append(rec["leaf"])
    evaluation={}
    for i,(sk,fr) in enumerate(frames.items()):
        mask=pd.Series(np.isin(leaves_by_split[sk],validated),index=fr.index)
        evaluation[sk]=outcome_summary(fr,mask,seed+10000+i*100)
    hold=evaluation["HOLDOUT_2025_2026H1"]
    raw_p=hold.get("fisher_greater_p"); bonf=min(1.0,float(raw_p)*3.0) if raw_p is not None else None
    hold["bonferroni_3_models_p"]=bonf
    ci_d=hold.get("winner_date_ci95") or [None,None]; ci_t=hold.get("winner_theme_ci95") or [None,None]
    hold["robust_both_cluster_ci_positive"]=bool(ci_d[0] is not None and ci_t[0] is not None and ci_d[0]>0 and ci_t[0]>0)
    return {"features":features,"tree_depth":int(model.get_depth()),"leaves":int(model.get_n_leaves()),"validated_leaves":validated,"leaf_table":leaf_table,"rules_selected":[{"leaf":x,"rule":rules[x]} for x in validated],"evaluation":evaluation}


def main()->None:
    ap=argparse.ArgumentParser(); ap.add_argument("--root",default="."); ap.add_argument("--output",required=True); ap.add_argument("--max-tickers",type=int,default=6000); ap.add_argument("--batch-size",type=int,default=75); ap.add_argument("--min-members",type=int,default=3); args=ap.parse_args()
    root=Path(args.root); outdir=root/args.output; outdir.mkdir(parents=True,exist_ok=True)
    frame,diag=build_candidates(root,args.max_tickers,args.batch_size,args.min_members)
    frames=split_frames(frame)
    result={"status":"PRELIMINARY_FIXED_CURRENT_TAXONOMY_FLAT_INTERACTION_DISCOVERY","design":{"population":"all stock-days inside frozen Subtheme Momentum; RS21 ignition is a feature, not a gate","splits":{"discovery":"2016-2021","validation":"2022-2024","final_holdout":"2025-2026H1"},"target":"20d stock-minus-theme-peers >= +10%","tree":{"max_depth":MAX_DEPTH,"min_leaf":MIN_LEAF,"validation_rule":"leaf discovery lift >=2.5pp AND validation lift >=1.5pp AND validation n>=100","model_families":list(MODEL_FEATURES)}},"coverage":diag,"split_coverage":{k:{"n":len(v),"dates":int(v.entry_date.nunique()),"themes":int(v.theme.nunique()),"winner_rate":float(v.pioneer_winner10.mean())} for k,v in frames.items()},"models":{}}
    for i,(name,features) in enumerate(MODEL_FEATURES.items()):
        print(f"FIT {name}",flush=True); result["models"][name]=run_model(name,frames,features,9100+i*100)
    cols=["entry_date","symbol","theme","pioneer_winner10","future_theme_top20","stock_minus_peers_5","stock_minus_peers_10","stock_minus_peers_20","mfe20","mae20"]+FEATURES
    frame[cols].to_csv(outdir/"interaction_candidate_rows.csv.gz",index=False,compression="gzip")
    (outdir/"summary.json").write_text(json.dumps(safe(result),ensure_ascii=False,indent=2),encoding="utf-8")
    print("=== FLAT_INTERACTION_RESULT_JSON ===",flush=True); print(json.dumps(safe(result),ensure_ascii=False,indent=2),flush=True); print("=== END_FLAT_INTERACTION_RESULT_JSON ===",flush=True)

if __name__=="__main__": main()
