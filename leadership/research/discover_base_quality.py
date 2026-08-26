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

BASE_QUALITY_FEATURES = [
    "base_vol5_vs_prior20",
    "base_vol10_vs_prior30",
    "base_tr5_vs_prior20",
    "base_atr10_vs50",
    "base_range20_pct",
    "base_range63_pct",
    "base_depth20",
    "base_depth63",
    "base_higher_low_atr",
    "base_support_ema21_10",
    "base_support_sma50_10",
    "base_down_vol10_vs_prior20",
    "base_up_down_dv_ratio10",
    "base_tight_tr_frac10",
    "base_rvol_vs_dry5",
]

FLOW_FEATURES = [
    "flow_share_ratio_3v20", "flow_share_ratio_5v20", "flow_share_ratio_10v20",
    "flow_share_change5", "theme_hhi_ratio_5v20",
]
RS_FEATURES = [
    "rs21_pct", "rs63_pct", "rs252_pct", "rs21_delta5", "rs21_delta10",
    "rs21_delta20", "rs63_delta20", "term21_63", "term21_252", "rs21_ignition",
]
MODEL_FEATURES = {
    "BASE_ONLY": BASE_QUALITY_FEATURES,
    "BASE_PLUS_FLOW": BASE_QUALITY_FEATURES + FLOW_FEATURES,
    "BASE_PLUS_RS": BASE_QUALITY_FEATURES + RS_FEATURES,
    "BASE_FULL": list(dict.fromkeys(BASE_QUALITY_FEATURES + list(old.FEATURES))),
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
    return pd.to_numeric(frame[feature], errors="coerce").replace([np.inf, -np.inf], np.nan).clip(-1_000_000, 1_000_000)


def is_symbol_holdout(symbol: str) -> bool:
    h=int(hashlib.sha1(symbol.encode("utf-8")).hexdigest()[:8],16)
    return h % 4 == 0


def future_window_extreme(df: pd.DataFrame, window: int, how: str) -> pd.DataFrame:
    rev=df.shift(-1).iloc[::-1]
    out=rev.rolling(window,min_periods=1).max() if how=="max" else rev.rolling(window,min_periods=1).min()
    return out.iloc[::-1]


def ratio_mean_nonoverlap(df: pd.DataFrame, cur_n: int, prior_n: int) -> pd.DataFrame:
    cur=df.shift(1).rolling(cur_n,min_periods=max(3,cur_n//2)).mean()
    prior=df.shift(cur_n+1).rolling(prior_n,min_periods=max(5,prior_n//2)).mean()
    return cur/prior.replace(0,np.nan)


def build_candidates(root: Path,max_tickers:int,batch_size:int,min_members:int)->tuple[pd.DataFrame,dict[str,Any]]:
    snapshot=er.load_json(root/"sector_snapshot.json")
    theme_members_all,taxonomy_candidates=er.extract_theme_members(snapshot)
    industry_map=er.read_industry_map(root/"industry_map.json")
    universe=er.read_universe_symbols(root/"universe.csv")
    allowed=set(industry_map)&universe
    selected=er.stratified_symbols(theme_members_all,allowed,max_tickers)
    requested=selected+(["SPY"] if "SPY" not in selected else [])
    ds=str((ANALYSIS_START-pd.Timedelta(days=1100)).date())
    de=str((ANALYSIS_END+pd.Timedelta(days=120)).date())
    ohlcv,download_diag=iq.download_ohlcv(requested,ds,de,batch_size)
    close_all=ohlcv["close"]
    stock_cols=[s for s in selected if s in close_all.columns]
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
    w30_slope,w30_dist=old.weekly_state(close)

    # Frozen base-quality feature set. Current day is used only where a close-of-day signal is intended.
    tr=iq.true_range(high,low,close); atr14=tr.rolling(14,min_periods=10).mean(); atr_pct=atr14/close.replace(0,np.nan)
    ema21=close.ewm(span=21,adjust=False,min_periods=15).mean(); sma50=close.rolling(50,min_periods=35).mean()
    bq:dict[str,pd.DataFrame]={}
    bq["base_vol5_vs_prior20"]=ratio_mean_nonoverlap(volume,5,20)
    bq["base_vol10_vs_prior30"]=ratio_mean_nonoverlap(volume,10,30)
    bq["base_tr5_vs_prior20"]=ratio_mean_nonoverlap(tr,5,20)
    bq["base_atr10_vs50"]=tr.shift(1).rolling(10,min_periods=6).mean()/tr.shift(1).rolling(50,min_periods=25).mean().replace(0,np.nan)
    bq["base_range20_pct"]=high.shift(1).rolling(20,min_periods=12).max()/low.shift(1).rolling(20,min_periods=12).min().replace(0,np.nan)-1.0
    bq["base_range63_pct"]=high.shift(1).rolling(63,min_periods=35).max()/low.shift(1).rolling(63,min_periods=35).min().replace(0,np.nan)-1.0
    ph20=high.shift(1).rolling(20,min_periods=12).max(); ph63=high.shift(1).rolling(63,min_periods=35).max()
    bq["base_depth20"]=close/ph20.replace(0,np.nan)-1.0
    bq["base_depth63"]=close/ph63.replace(0,np.nan)-1.0
    low5=low.shift(1).rolling(5,min_periods=4).min(); prior_low5=low.shift(6).rolling(5,min_periods=4).min()
    bq["base_higher_low_atr"]=(low5/prior_low5.replace(0,np.nan)-1.0)/atr_pct.replace(0,np.nan)
    bq["base_support_ema21_10"]=(close.shift(1)>=ema21.shift(1)).astype(float).rolling(10,min_periods=6).mean()
    bq["base_support_sma50_10"]=(close.shift(1)>=sma50.shift(1)).astype(float).rolling(10,min_periods=6).mean()
    down_vol=volume.where(stock_ret<0); up_dv=dv.where(stock_ret>0); down_dv=dv.where(stock_ret<0)
    bq["base_down_vol10_vs_prior20"]=down_vol.shift(1).rolling(10,min_periods=3).mean()/down_vol.shift(11).rolling(20,min_periods=5).mean().replace(0,np.nan)
    bq["base_up_down_dv_ratio10"]=up_dv.shift(1).rolling(10,min_periods=3).mean()/down_dv.shift(1).rolling(10,min_periods=3).mean().replace(0,np.nan)
    prior_med_tr=tr.shift(1).rolling(20,min_periods=10).median(); tight=(tr<prior_med_tr).astype(float)
    bq["base_tight_tr_frac10"]=tight.shift(1).rolling(10,min_periods=6).mean()
    bq["base_rvol_vs_dry5"]=volume/volume.shift(1).rolling(5,min_periods=4).mean().replace(0,np.nan)

    rows=[]
    for ti,t in enumerate(common_themes):
        if t not in momentum.columns: continue
        qdates=momentum.index[(momentum[t].fillna(False))&(momentum.index>=ANALYSIS_START)&(momentum.index<=ANALYSIS_END)]
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
        for name in BASE_QUALITY_FEATURES: put(name,bq[name])

        for h in (5,10,20):
            fb=fwd[h][members]; sums=fb.sum(axis=1,min_count=2); cnt=fb.count(axis=1); peers=fb.rsub(sums,axis=0).div((cnt-1).replace(0,np.nan),axis=0); put(f"stock_minus_peers_{h}",fb-peers)
        put("mfe20",mfe20); put("mae20",mae20)
        peer20=pd.to_numeric(part["stock_minus_peers_20"],errors="coerce")
        part["pioneer_winner10"]=(peer20>=0.10).astype(float)
        part["clean_up"]=((peer20>=0.10)&(part["mfe20"]>=0.15)&(part["mae20"]>-0.10)).astype(float)
        part["failure"]=((peer20<=-0.10)|(part["mae20"]<=-0.15)).astype(float)
        valid=peer20.notna()&part["rs21_pct"].notna()
        rows.append(part.loc[valid])
        if (ti+1)%25==0: print(f"THEMES {ti+1}/{len(common_themes)} rows={sum(len(x) for x in rows)}",flush=True)

    if not rows: raise RuntimeError("No candidate rows")
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


def eventize_mask(frame:pd.DataFrame, selected:pd.Series)->pd.DataFrame:
    x=frame.copy(); x["_sel"]=selected.reindex(frame.index,fill_value=False).astype(bool).to_numpy(); x["entry_date"]=pd.to_datetime(x.entry_date)
    dates=np.sort(x.entry_date.unique()); pos={pd.Timestamp(d):i for i,d in enumerate(dates)}; x["_ord"]=x.entry_date.map(pos)
    x=x.sort_values(["symbol","theme","entry_date"])
    prev=x.groupby(["symbol","theme"],observed=True)["_sel"].shift(1); prevord=x.groupby(["symbol","theme"],observed=True)["_ord"].shift(1)
    cand=x[x._sel & (prev.isna()|(~prev.fillna(False))|((x._ord-prevord)>1))]
    keep=[]
    for _,g in cand.groupby(["symbol","theme"],observed=True,sort=False):
        last=-10**9
        for idx,row in g.iterrows():
            o=int(row["_ord"])
            if o-last>COOLDOWN: keep.append(idx); last=o
    return cand.loc[keep].drop(columns=["_sel","_ord"],errors="ignore")


def cluster_diff_ci(a:pd.DataFrame,b:pd.DataFrame,value:str,cluster:str,seed:int,reps:int=1500)->list[float|None]:
    aa=a[[cluster,value]].dropna().groupby(cluster,observed=True)[value].mean(); bb=b[[cluster,value]].dropna().groupby(cluster,observed=True)[value].mean()
    rng=np.random.default_rng(seed); common=aa.index.intersection(bb.index)
    if len(common)>=5:
        d=(aa.loc[common]-bb.loc[common]).to_numpy(float)
        draws=rng.choice(d,size=(reps,len(d)),replace=True).mean(axis=1)
    else:
        av=aa.to_numpy(float); bv=bb.to_numpy(float)
        if len(av)<2 or len(bv)<2:return [None,None]
        draws=np.array([rng.choice(av,len(av),replace=True).mean()-rng.choice(bv,len(bv),replace=True).mean() for _ in range(reps)])
    q=np.quantile(draws,[.025,.975]); return [float(q[0]),float(q[1])]


def rate_summary(frame:pd.DataFrame)->dict[str,Any]:
    if frame.empty:return {"n":0}
    p=pd.to_numeric(frame.stock_minus_peers_20,errors="coerce")
    return {"n":len(frame),"clean_up_rate":float(frame.clean_up.mean()),"pioneer_rate":float(frame.pioneer_winner10.mean()),"failure_rate":float(frame.failure.mean()),"peer20_mean":float(p.mean()),"mfe20_mean":float(pd.to_numeric(frame.mfe20,errors="coerce").mean()),"mae20_mean":float(pd.to_numeric(frame.mae20,errors="coerce").mean())}


def event_compare(selected:pd.DataFrame,control:pd.DataFrame,seed:int)->dict[str,Any]:
    out={"selected":rate_summary(selected),"control":rate_summary(control)}
    if len(selected) and len(control):
        for col in ("clean_up","pioneer_winner10"):
            a=selected[col].astype(int); b=control[col].astype(int)
            _,p=fisher_exact([[int(a.sum()),len(a)-int(a.sum())],[int(b.sum()),len(b)-int(b.sum())]],alternative="greater")
            out[col]={"lift_pp":100*(float(a.mean())-float(b.mean())),"fisher_greater_p":float(p),"date_ci95":cluster_diff_ci(selected,control,col,"entry_date",seed),"theme_ci95":cluster_diff_ci(selected,control,col,"theme",seed+1000),"symbol_ci95":cluster_diff_ci(selected,control,col,"symbol",seed+2000)}
    return out


def run_model(name:str,features:list[str],train_frames:dict[str,pd.DataFrame],holdout:pd.DataFrame,seed:int)->dict[str,Any]:
    d0=train_frames["DISCOVERY_2016_2021"]; d=d0[(d0.clean_up>0)|(d0.failure>0)].copy()
    v0=train_frames["VALIDATION_2022_2024"]; v=v0[(v0.clean_up>0)|(v0.failure>0)].copy()
    model,med,rules=fit_tree(d,features,seed); dl=apply_tree(model,d,features,med); vl=apply_tree(model,v,features,med)
    dbase=float(d.clean_up.mean()); vbase=float(v.clean_up.mean()); leaf_table=[]; validated=[]
    for leaf in sorted(rules):
        md=dl==leaf; mv=vl==leaf; dr=float(d.loc[md,"clean_up"].mean()) if md.sum() else None; vr=float(v.loc[mv,"clean_up"].mean()) if mv.sum() else None
        rec={"leaf":int(leaf),"rule":rules[leaf],"discovery":{"n":int(md.sum()),"clean_rate":dr,"lift_pp":100*(dr-dbase) if dr is not None else None},"validation":{"n":int(mv.sum()),"clean_rate":vr,"lift_pp":100*(vr-vbase) if vr is not None else None}}
        leaf_table.append(rec)
        if rec["discovery"]["n"]>=MIN_LEAF and rec["validation"]["n"]>=100 and rec["discovery"]["lift_pp"] is not None and rec["validation"]["lift_pp"] is not None and rec["discovery"]["lift_pp"]>=5.0 and rec["validation"]["lift_pp"]>=3.0:
            validated.append(int(leaf))
    evals={}
    frames={**train_frames,"SYMBOL_HOLDOUT_ALL":holdout,"SYMBOL_HOLDOUT_2022_PLUS":holdout[pd.to_datetime(holdout.entry_date)>=VALIDATION_START]}
    for i,(key,fr) in enumerate(frames.items()):
        leaves=apply_tree(model,fr,features,med); mask=pd.Series(np.isin(leaves,validated),index=fr.index)
        sel_ev=eventize_mask(fr,mask); ctrl_ev=eventize_mask(fr,~mask)
        evals[key]={"raw_selected":rate_summary(fr.loc[mask]),"raw_other":rate_summary(fr.loc[~mask]),"event_compare":event_compare(sel_ev,ctrl_ev,seed+10000+i*100)}
    return {"features":features,"tree_depth":int(model.get_depth()),"leaves":int(model.get_n_leaves()),"validated_leaves":validated,"rules_selected":[{"leaf":x,"rule":rules[x]} for x in validated],"leaf_table":leaf_table,"evaluation":evals}


def eps_overlay(root:Path,frame:pd.DataFrame)->dict[str,Any]:
    p=root/"earnings.json"
    if not p.exists():return {"status":"missing"}
    obj=json.loads(p.read_text(encoding="utf-8")); chunks=[]
    for sym,g in frame.groupby("symbol",observed=True):
        rec=obj.get(str(sym),{}); eps=rec.get("eps",{}) if isinstance(rec,dict) else {}; ys=eps.get("yoy_series",[]) if isinstance(eps,dict) else []
        vals=[]
        for z in ys:
            try: vals.append((pd.Timestamp(z["date"]),float(z["yoy"])))
            except Exception: pass
        vals=sorted(vals)
        if len(vals)<2: continue
        dates=np.array([d.to_datetime64() for d,_ in vals]); yoy=np.array([v for _,v in vals],float); gd=pd.to_datetime(g.entry_date).to_numpy(dtype="datetime64[ns]"); ix=np.searchsorted(dates,gd,side="right")-1
        ok=ix>=1
        if not ok.any(): continue
        h=g.loc[ok].copy(); j=ix[ok]; h["eps_report_date"]=[pd.Timestamp(dates[k]) for k in j]; h["eps_latest_yoy"]=yoy[j]; h["eps_prior_yoy"]=yoy[j-1]; h["eps_accel_pp"]=yoy[j]-yoy[j-1]
        h["eps_accel_1"]=(h.eps_latest_yoy>h.eps_prior_yoy)&(h.eps_latest_yoy>0)
        acc2=np.zeros(len(h),dtype=bool); has3=j>=2; jj=j[has3]; acc2[has3]=(yoy[jj]>yoy[jj-1])&(yoy[jj-1]>yoy[jj-2])&(yoy[jj]>0); h["eps_accel_2"]=acc2
        chunks.append(h)
    if not chunks:return {"status":"no_coverage"}
    e=pd.concat(chunks,ignore_index=True); e=e.sort_values(["symbol","theme","eps_report_date","entry_date"]).groupby(["symbol","theme","eps_report_date"],observed=True,as_index=False).head(1)
    out={"status":"RECENT_POINT_IN_TIME_PROXY_ONLY_NOT_HISTORICAL_MODEL","events":len(e),"symbols":int(e.symbol.nunique()),"start":str(pd.to_datetime(e.entry_date).min().date()),"end":str(pd.to_datetime(e.entry_date).max().date()),"rules":{}}
    for name in ("eps_accel_1","eps_accel_2"):
        m=e[name].astype(bool); a=e.loc[m]; b=e.loc[~m]; rec={"selected":rate_summary(a),"control":rate_summary(b)}
        if len(a) and len(b):
            for target in ("clean_up","pioneer_winner10"):
                x=a[target].astype(int); y=b[target].astype(int); _,pv=fisher_exact([[int(x.sum()),len(x)-int(x.sum())],[int(y.sum()),len(y)-int(y.sum())]],alternative="greater")
                rec[target]={"lift_pp":100*(float(x.mean())-float(y.mean())),"fisher_greater_p":float(pv)}
        out["rules"][name]=rec
    return out


def main()->None:
    ap=argparse.ArgumentParser(); ap.add_argument("--root",default="."); ap.add_argument("--output",required=True); ap.add_argument("--max-tickers",type=int,default=6000); ap.add_argument("--batch-size",type=int,default=75); ap.add_argument("--min-members",type=int,default=3); args=ap.parse_args()
    root=Path(args.root); outdir=root/args.output; outdir.mkdir(parents=True,exist_ok=True)
    frame,diag=build_candidates(root,args.max_tickers,args.batch_size,args.min_members); frame["entry_date"]=pd.to_datetime(frame.entry_date)
    hold_sym=frame.symbol.astype(str).map(is_symbol_holdout); train=frame[~hold_sym].copy(); hold=frame[hold_sym].copy()
    train_frames={"DISCOVERY_2016_2021":train[(train.entry_date>=ANALYSIS_START)&(train.entry_date<=DISCOVERY_END)],"VALIDATION_2022_2024":train[(train.entry_date>=VALIDATION_START)&(train.entry_date<=VALIDATION_END)],"OPENED_2025_PLUS":train[train.entry_date>=OPENED_START]}
    result={"status":"PRELIMINARY_FIXED_CURRENT_TAXONOMY_BASE_QUALITY","design":{"population":"all stock-days in frozen Subtheme Momentum; no Hidden/RS21 gate","target":{"clean_up":"20d peer excess >=10%, MFE>=15%, MAE>-10%","failure":"20d peer excess <=-10% OR MAE<=-15%"},"symbol_holdout":"sha1(symbol) mod 4 == 0; never used for fit/validation","event_rule":"first day of selected state + 20 trading-day cooldown","tree":{"max_depth":MAX_DEPTH,"min_leaf":MIN_LEAF,"validation_rule":"Discovery clean lift >=5pp AND Validation >=3pp AND validation n>=100"},"base_quality_features":BASE_QUALITY_FEATURES,"eps":"excluded from historical model; recent as-of overlay only because earnings.json stores only recent YoY series"},"coverage":diag,"symbols":{"train":int(train.symbol.nunique()),"holdout":int(hold.symbol.nunique())},"base_rates":{"train_discovery_clean":float(train_frames["DISCOVERY_2016_2021"].clean_up.mean()),"train_validation_clean":float(train_frames["VALIDATION_2022_2024"].clean_up.mean()),"symbol_holdout_clean":float(hold.clean_up.mean())},"models":{}}
    for i,(name,features) in enumerate(MODEL_FEATURES.items()):
        print(f"BASEQUALITY {name}",flush=True); result["models"][name]=run_model(name,features,train_frames,hold,52000+i*100)
    print("EPS OVERLAY",flush=True); result["eps_overlay"]=eps_overlay(root,frame)
    (outdir/"summary.json").write_text(json.dumps(safe(result),ensure_ascii=False,indent=2),encoding="utf-8")
    print("=== BASE_QUALITY_RESULT_JSON ===",flush=True); print(json.dumps(safe(result),ensure_ascii=False,indent=2),flush=True); print("=== END_BASE_QUALITY_RESULT_JSON ===",flush=True)

if __name__=="__main__": main()
