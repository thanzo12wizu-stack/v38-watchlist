from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import fisher_exact
from sklearn.tree import DecisionTreeClassifier

import discover_stock_interactions as old
import validate_early_rotation as er
import validate_confirmed_leadership as cl
import validate_ignition_quality as iq
import validate_sector_stock_stack as ss

ANALYSIS_START = pd.Timestamp("2016-01-04")
ANALYSIS_END = pd.Timestamp("2026-07-28")
DISCOVERY_END = pd.Timestamp("2021-12-31")
VALIDATION_START = pd.Timestamp("2022-01-01")
VALIDATION_END = pd.Timestamp("2024-12-31")
OPENED_START = pd.Timestamp("2025-01-01")
COOLDOWN = 20
MIN_LEAF = 250
MAX_DEPTH = 3

NEW_PRESSURE_FEATURES = [
    "rel_eff5", "rel_eff10", "rel_eff20",
    "rel_pos_frac10", "rel_pos_frac20",
    "rel_dv_balance10", "upper_close_frac10",
    "chaikin_mf10", "gap_acceptance5",
]
BASE_FEATURES = list(old.FEATURES)
ALL_FEATURES = BASE_FEATURES + NEW_PRESSURE_FEATURES
MODEL_FEATURES = {
    "FULL": ALL_FEATURES,
    "PRESSURE_ONLY": NEW_PRESSURE_FEATURES,
    "NO_LIFECYCLE": [f for f in ALL_FEATURES if f not in {"dist_52w_high", "w30_slope4", "w30_distance"}],
    "NO_FLOW": [f for f in ALL_FEATURES if not (f.startswith("flow_") or f.startswith("theme_hhi"))],
}


def safe(v: Any) -> Any:
    if isinstance(v, dict): return {str(k): safe(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)): return [safe(x) for x in v]
    if isinstance(v, np.integer): return int(v)
    if isinstance(v, (np.floating, float)):
        x=float(v); return x if math.isfinite(x) else None
    if isinstance(v, pd.Timestamp): return v.isoformat()
    return v


def clean_series(frame: pd.DataFrame, feature: str) -> pd.Series:
    return pd.to_numeric(frame[feature],errors="coerce").replace([np.inf,-np.inf],np.nan).clip(-1_000_000,1_000_000)


def is_symbol_holdout(symbol: str) -> bool:
    h=int(hashlib.sha1(symbol.encode("utf-8")).hexdigest()[:8],16)
    return h % 4 == 0


def future_window_extreme(df: pd.DataFrame, window: int, how: str) -> pd.DataFrame:
    rev=df.shift(-1).iloc[::-1]
    out=rev.rolling(window,min_periods=1).max() if how=="max" else rev.rolling(window,min_periods=1).min()
    return out.iloc[::-1]


def weekly_state(close: pd.DataFrame) -> tuple[pd.DataFrame,pd.DataFrame]:
    return old.weekly_state(close)


def rel_efficiency(rel_daily: pd.DataFrame, n: int) -> pd.DataFrame:
    logs=np.log1p(rel_daily.clip(lower=-0.95))
    net=np.expm1(logs.rolling(n,min_periods=max(3,n//2)).sum())
    path=rel_daily.abs().rolling(n,min_periods=max(3,n//2)).sum().replace(0,np.nan)
    return net/path


def build_candidates(root: Path,max_tickers:int,batch_size:int,min_members:int)->tuple[pd.DataFrame,dict[str,Any]]:
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
    open_=ohlcv["open"][stock_cols]; close=close_all[stock_cols]; high=ohlcv["high"][stock_cols]; low=ohlcv["low"][stock_cols]; volume=ohlcv["volume"][stock_cols]
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
    tr=iq.true_range(high,low,close); atr14=tr.rolling(14,min_periods=10).mean()
    day_range=(high-low).replace(0,np.nan); mfm=((2*close-high-low)/day_range).clip(-1,1); chaikin=(mfm*volume).rolling(10,min_periods=6).sum()/volume.rolling(10,min_periods=6).sum().replace(0,np.nan)
    gap=open_/close.shift(1)-1.0; gap_accept=(np.sign(gap)*(close-open_)/atr14.replace(0,np.nan)).rolling(5,min_periods=3).mean()
    upper_close=(base["close_location"]>=0.70).astype(float).rolling(10,min_periods=6).mean()

    rows=[]; start=ANALYSIS_START; end=ANALYSIS_END
    for ti,t in enumerate(common_themes):
        if t not in momentum.columns: continue
        qdates=momentum.index[(momentum[t].fillna(False))&(momentum.index>=start)&(momentum.index<=end)]
        members=[s for s in theme_members.get(t,[]) if s in stock_cols]
        if len(qdates)==0 or len(members)<min_members: continue
        nS=len(members); idx=pd.MultiIndex.from_product([qdates,members],names=["entry_date","symbol"])
        part=pd.DataFrame(index=idx).reset_index(); part["theme"]=t
        def put(name:str,mat:pd.DataFrame)->None:
            part[name]=mat.reindex(index=qdates,columns=members).to_numpy(float).reshape(-1)
        r21=old.theme_rank(p21[members]); r63=old.theme_rank(p63[members]); r252=old.theme_rank(p252[members])
        put("rs21_pct",r21); put("rs63_pct",r63); put("rs252_pct",r252)
        put("rs21_delta5",r21-r21.shift(5)); put("rs21_delta10",r21-r21.shift(10)); put("rs21_delta20",r21-r21.shift(20)); put("rs63_delta20",r63-r63.shift(20))
        put("term21_63",r21-r63); put("term21_252",r21-r252); put("rs21_ignition",((r21>=2/3)&(r21.shift(1)<2/3)).astype(float))
        block_dv=dv[members]; shares=block_dv.div(block_dv.sum(axis=1,min_count=1).replace(0,np.nan),axis=0)
        for win,name in ((3,"flow_share_ratio_3v20"),(5,"flow_share_ratio_5v20"),(10,"flow_share_ratio_10v20")):
            cur,prior=old.rolling_prior_mean(shares,win,20); put(name,cur/prior.replace(0,np.nan))
        put("flow_share_change5",shares/shares.shift(5).replace(0,np.nan))
        hhi=(shares*shares).sum(axis=1,min_count=1); hcur=hhi.rolling(5,min_periods=3).mean(); hprior=hhi.shift(5).rolling(20,min_periods=10).mean(); hv=(hcur/hprior.replace(0,np.nan)).reindex(qdates).to_numpy(float); part["theme_hhi_ratio_5v20"]=np.repeat(hv,nS)
        ex5=p5[members].sub(er.period_return(theme_ret[[t]],5)[t],axis=0); ex10=p10[members].sub(er.period_return(theme_ret[[t]],10)[t],axis=0); put("stock_excess5",ex5); put("stock_excess10",ex10)
        for name,mat in (("rvol20",base["rvol20"]),("signed_rvol20",base["signed_rvol20"]),("close_location",base["close_location"]),("ema21_atr",base["ema21_atr"]),("sma50_atr",base["sma50_atr"]),("dist_prior_high20",base["dist_prior_high20"]),("dist_prior_high63",base["dist_prior_high63"]),("compression_5v20",base["compression_5v20"]),("gap_pct",base["gap_pct"]),("dist_52w_high",dist52),("vol_dry_5v20",vol_dry),("up_down_dv_balance10",ud10),("accum_dist_count10",ad10),("w30_slope4",w30_slope),("w30_distance",w30_dist)):
            put(name,mat)
        for name,series in (("theme_rs63",theme_pct[t]),("theme_rs_delta20",theme_pct[t]-theme_pct[t].shift(20)),("industry_rs",parent_industry[t]),("sector_rs",parent_sector[t]),("breadth",breadth[t]),("momentum_age",old.momentum_run_age(momentum[t]))):
            vals=series.reindex(qdates).to_numpy(float); part[name]=np.repeat(vals,nS)

        # Direction/pressure features are calculated relative to the current subtheme.
        td=theme_ret[t]
        rel_daily=(1.0+stock_ret[members]).div(1.0+td,axis=0)-1.0
        put("rel_eff5",rel_efficiency(rel_daily,5)); put("rel_eff10",rel_efficiency(rel_daily,10)); put("rel_eff20",rel_efficiency(rel_daily,20))
        put("rel_pos_frac10",(rel_daily>0).astype(float).rolling(10,min_periods=6).mean()); put("rel_pos_frac20",(rel_daily>0).astype(float).rolling(20,min_periods=12).mean())
        rel_dvb=(np.sign(rel_daily)*block_dv).rolling(10,min_periods=6).sum()/block_dv.rolling(10,min_periods=6).sum().replace(0,np.nan); put("rel_dv_balance10",rel_dvb)
        put("upper_close_frac10",upper_close[members]); put("chaikin_mf10",chaikin[members]); put("gap_acceptance5",gap_accept[members])

        for h in (5,10,20):
            fb=fwd[h][members]; sums=fb.sum(axis=1,min_count=2); cnt=fb.count(axis=1); peers=fb.rsub(sums,axis=0).div((cnt-1).replace(0,np.nan),axis=0); put(f"stock_minus_peers_{h}",fb-peers)
        put("mfe20",mfe20); put("mae20",mae20)
        peer20=pd.to_numeric(part["stock_minus_peers_20"],errors="coerce")
        part["clean_up"]=((peer20>=0.10)&(part["mfe20"]>=0.15)&(part["mae20"]>-0.10)).astype(float)
        part["failure"]=((peer20<=-0.10)|(part["mae20"]<=-0.15)).astype(float)
        valid=peer20.notna()&part["rs21_pct"].notna()
        rows.append(part.loc[valid])
        if (ti+1)%25==0: print(f"THEMES {ti+1}/{len(common_themes)} rows={sum(len(x) for x in rows)}",flush=True)
    frame=pd.concat(rows,ignore_index=True)
    diag={"selected_stocks":len(stock_cols),"candidate_rows":len(frame),"dates":int(frame.entry_date.nunique()),"themes":int(frame.theme.nunique()),"download":download_diag,"taxonomy":taxonomy_candidates}
    return frame,diag


def fit_tree(discovery:pd.DataFrame,features:list[str],seed:int):
    med={}; X={}
    for f in features:
        s=clean_series(discovery,f); m=float(s.median()) if s.notna().any() else 0.0; med[f]=m; X[f]=s.fillna(m)
    model=DecisionTreeClassifier(max_depth=MAX_DEPTH,min_samples_leaf=MIN_LEAF,min_samples_split=MIN_LEAF*2,random_state=seed)
    model.fit(pd.DataFrame(X),discovery["clean_up"].astype(int))
    return model,med,old.extract_leaf_rules(model,features)


def apply_tree(model,frame:pd.DataFrame,features:list[str],med:dict[str,float])->np.ndarray:
    return model.apply(pd.DataFrame({f:clean_series(frame,f).fillna(med[f]) for f in features}))


def eventize_selected(frame:pd.DataFrame,selected:pd.Series)->pd.DataFrame:
    x=frame.copy(); x["_sel"]=selected.reindex(frame.index,fill_value=False).astype(bool).to_numpy(); x["entry_date"]=pd.to_datetime(x.entry_date)
    dates=np.sort(frame.entry_date.unique()); pos={pd.Timestamp(d):i for i,d in enumerate(dates)}; x["_ord"]=x.entry_date.map(pos)
    x=x.sort_values(["symbol","theme","entry_date"])
    prev=x.groupby(["symbol","theme"],observed=True)["_sel"].shift(1); prevord=x.groupby(["symbol","theme"],observed=True)["_ord"].shift(1)
    cand=x[x._sel & (prev.isna()|(~prev.fillna(False))|((x._ord-prevord)>1))]
    keep=[]
    for _,g in cand.groupby(["symbol","theme"],observed=True,sort=False):
        last=-10**9
        for idx,row in g.iterrows():
            o=int(row._ord)
            if o-last>COOLDOWN: keep.append(idx); last=o
    return cand.loc[keep]


def rate_summary(frame:pd.DataFrame)->dict[str,Any]:
    if frame.empty: return {"n":0}
    p=pd.to_numeric(frame.stock_minus_peers_20,errors="coerce"); mfe=pd.to_numeric(frame.mfe20,errors="coerce"); mae=pd.to_numeric(frame.mae20,errors="coerce")
    return {"n":len(frame),"clean_up_rate":float(frame.clean_up.mean()),"failure_rate":float(frame.failure.mean()),"up10_rate":float((p>=0.10).mean()),"down10_rate":float((p<=-0.10).mean()),"peer20_mean":float(p.mean()),"mfe20_mean":float(mfe.mean()),"mae20_mean":float(mae.mean())}


def run_model(name:str,features:list[str],train_frames:dict[str,pd.DataFrame],holdout:pd.DataFrame,seed:int)->dict[str,Any]:
    # Fit only where outcome is clearly Clean-Up or Failure; ambiguous rows do not train direction quality.
    d0=train_frames["DISCOVERY_2016_2021"]; d=d0[(d0.clean_up>0)|(d0.failure>0)].copy()
    v0=train_frames["VALIDATION_2022_2024"]; v=v0[(v0.clean_up>0)|(v0.failure>0)].copy()
    model,med,rules=fit_tree(d,features,seed)
    dl=apply_tree(model,d,features,med); vl=apply_tree(model,v,features,med)
    dbase=float(d.clean_up.mean()); vbase=float(v.clean_up.mean())
    leaf_table=[]; validated=[]
    for leaf in sorted(rules):
        md=dl==leaf; mv=vl==leaf
        dr=float(d.loc[md,"clean_up"].mean()) if md.sum() else None; vr=float(v.loc[mv,"clean_up"].mean()) if mv.sum() else None
        rec={"leaf":int(leaf),"rule":rules[leaf],"discovery":{"n":int(md.sum()),"clean_rate":dr,"lift_pp":100*(dr-dbase) if dr is not None else None},"validation":{"n":int(mv.sum()),"clean_rate":vr,"lift_pp":100*(vr-vbase) if vr is not None else None}}
        leaf_table.append(rec)
        if rec["discovery"]["n"]>=MIN_LEAF and rec["validation"]["n"]>=100 and rec["discovery"]["lift_pp"] is not None and rec["validation"]["lift_pp"] is not None and rec["discovery"]["lift_pp"]>=5.0 and rec["validation"]["lift_pp"]>=3.0:
            validated.append(int(leaf))
    evals={}
    for key,fr in {**train_frames,"SYMBOL_HOLDOUT_ALL":holdout,"SYMBOL_HOLDOUT_2022_PLUS":holdout[pd.to_datetime(holdout.entry_date)>=VALIDATION_START]}.items():
        leaves=apply_tree(model,fr,features,med); raw=pd.Series(np.isin(leaves,validated),index=fr.index)
        ev=eventize_selected(fr,raw)
        other=fr.loc[~raw]
        evals[key]={"raw_selected":rate_summary(fr.loc[raw]),"event_selected":rate_summary(ev),"raw_other":rate_summary(other)}
    return {"features":features,"tree_depth":int(model.get_depth()),"leaves":int(model.get_n_leaves()),"validated_leaves":validated,"rules_selected":[{"leaf":x,"rule":rules[x]} for x in validated],"leaf_table":leaf_table,"evaluation":evals}


def main()->None:
    ap=argparse.ArgumentParser(); ap.add_argument("--root",default="."); ap.add_argument("--output",required=True); ap.add_argument("--max-tickers",type=int,default=6000); ap.add_argument("--batch-size",type=int,default=75); ap.add_argument("--min-members",type=int,default=3); args=ap.parse_args()
    root=Path(args.root); outdir=root/args.output; outdir.mkdir(parents=True,exist_ok=True)
    frame,diag=build_candidates(root,args.max_tickers,args.batch_size,args.min_members); frame["entry_date"]=pd.to_datetime(frame.entry_date)
    hold_sym=frame.symbol.astype(str).map(is_symbol_holdout); train=frame[~hold_sym].copy(); hold=frame[hold_sym].copy()
    train_frames={"DISCOVERY_2016_2021":train[(train.entry_date>=ANALYSIS_START)&(train.entry_date<=DISCOVERY_END)],"VALIDATION_2022_2024":train[(train.entry_date>=VALIDATION_START)&(train.entry_date<=VALIDATION_END)],"OPENED_2025_PLUS":train[train.entry_date>=OPENED_START]}
    result={"status":"PRELIMINARY_FIXED_CURRENT_TAXONOMY_UPWARD_QUALITY","design":{"population":"all stock-days in frozen Subtheme Momentum; no RS21/Hidden gate","target":{"clean_up":"20d stock-minus-theme peers >=10%, absolute MFE20>=15%, MAE20>-10%","failure":"20d stock-minus-theme peers <=-10% OR MAE20<=-15%"},"symbol_holdout":"sha1(symbol) mod 4 == 0; excluded from all tree fitting and validation rows","tree":{"max_depth":MAX_DEPTH,"min_leaf":MIN_LEAF,"validation_rule":"Discovery clean-rate lift >=5pp AND Validation >=3pp AND validation n>=100"},"new_pressure_features":NEW_PRESSURE_FEATURES},"coverage":diag,"symbols":{"train":int(train.symbol.nunique()),"holdout":int(hold.symbol.nunique())},"base_rates":{"train_discovery_clean":float(train_frames["DISCOVERY_2016_2021"].clean_up.mean()),"train_validation_clean":float(train_frames["VALIDATION_2022_2024"].clean_up.mean()),"symbol_holdout_clean":float(hold.clean_up.mean())},"models":{}}
    for i,(name,features) in enumerate(MODEL_FEATURES.items()):
        print(f"UPWARD {name}",flush=True); result["models"][name]=run_model(name,features,train_frames,hold,41000+i*100)
    (outdir/"summary.json").write_text(json.dumps(safe(result),ensure_ascii=False,indent=2),encoding="utf-8")
    print("=== UPWARD_QUALITY_RESULT_JSON ===",flush=True); print(json.dumps(safe(result),ensure_ascii=False,indent=2),flush=True); print("=== END_UPWARD_QUALITY_RESULT_JSON ===",flush=True)

if __name__=="__main__": main()
