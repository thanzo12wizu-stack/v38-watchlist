from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import fisher_exact

import validate_early_rotation as er
import validate_confirmed_leadership as cl
import validate_sector_stock_stack as ss
import validate_ignition_entry as ie
import validate_ignition_quality as iq
import validate_rs_periods as rs

HORIZONS = (5, 10, 20)
WINNER_EXCESS_20 = 0.10
TOP_THEME_CUTOFF = 0.80

# All definitions are frozen before this run. Weinstein labels below are
# operational proxies, not claimed to be exact canonical stage definitions.
BINARY_RULES = {
    "RS_LADDER_UP": "within-theme RS21 rank > RS63 rank > RS252 rank",
    "FLOW_ACCEL_1P25": "5d mean theme dollar-volume share / prior20d mean share >= 1.25",
    "FLOW_ACCEL_1P50": "same ratio >= 1.50",
    "STAGE2_PROXY": "last completed weekly close > rising 30-week SMA",
    "EARLY_STAGE2_PROXY": "STAGE2_PROXY and weekly close is 0-15% above 30-week SMA",
    "LATE_STAGE2_PROXY": "STAGE2_PROXY and weekly close >15% above 30-week SMA",
    "LOW_EFFORT_LEAD": "5d stock-minus-theme return >0 while dollar-volume-share acceleration <=1.0",
    "LADDER_FLOW": "RS_LADDER_UP and FLOW_ACCEL_1P25",
    "LADDER_EARLY_STAGE2": "RS_LADDER_UP and EARLY_STAGE2_PROXY",
}

CONTINUOUS_FACTORS = (
    "rs21_pct",
    "rs63_pct",
    "rs252_pct_recalc",
    "term21_63",
    "term63_252",
    "term21_252",
    "flow_share_ratio_5v20",
    "stock_excess5",
    "price_efficiency5",
    "w30_slope4",
    "w30_distance",
)


def safe(v: Any) -> Any:
    if isinstance(v, dict): return {str(k): safe(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)): return [safe(x) for x in v]
    if isinstance(v, np.integer): return int(v)
    if isinstance(v, (np.floating, float)):
        x = float(v); return x if math.isfinite(x) else None
    if isinstance(v, pd.Timestamp): return v.isoformat()
    return v


def cluster_diff_ci(frame: pd.DataFrame, mask_hi: pd.Series, mask_lo: pd.Series, value: str, cluster: str, seed: int, reps: int = 2500) -> list[float | None]:
    hi = frame.loc[mask_hi, [cluster, value]].dropna()
    lo = frame.loc[mask_lo, [cluster, value]].dropna()
    if hi.empty or lo.empty: return [None, None]
    a = hi.groupby(cluster, observed=True)[value].mean()
    b = lo.groupby(cluster, observed=True)[value].mean()
    common = a.index.intersection(b.index)
    if len(common) >= 5:
        d = (a.loc[common] - b.loc[common]).to_numpy(float)
    else:
        # Independent cluster resampling if overlap is sparse.
        av, bv = a.to_numpy(float), b.to_numpy(float)
        if len(av) < 2 or len(bv) < 2: return [None, None]
        rng = np.random.default_rng(seed)
        draws = []
        for _ in range(reps):
            draws.append(rng.choice(av, len(av), replace=True).mean() - rng.choice(bv, len(bv), replace=True).mean())
        q = np.quantile(draws, [0.025, 0.975]); return [float(q[0]), float(q[1])]
    if len(d) < 2: return [None, None]
    rng = np.random.default_rng(seed)
    draws = rng.choice(d, size=(reps, len(d)), replace=True).mean(axis=1)
    q = np.quantile(draws, [0.025, 0.975]); return [float(q[0]), float(q[1])]


def fisher_two_groups(frame: pd.DataFrame, hi: pd.Series, lo: pd.Series, label: str) -> dict[str, Any]:
    a = frame.loc[hi, label].dropna().astype(bool)
    b = frame.loc[lo, label].dropna().astype(bool)
    if len(a) and len(b):
        _, p = fisher_exact([[int(a.sum()), len(a)-int(a.sum())], [int(b.sum()), len(b)-int(b.sum())]], alternative="greater")
    else:
        p = np.nan
    return {
        "high_n": int(len(a)), "low_n": int(len(b)),
        "high_rate": float(a.mean()) if len(a) else None,
        "low_rate": float(b.mean()) if len(b) else None,
        "lift_pp": float(100.0*(a.mean()-b.mean())) if len(a) and len(b) else None,
        "fisher_greater_p": float(p) if np.isfinite(p) else None,
    }


def rank_within_theme_matrix(period_ret: pd.DataFrame, theme_members: dict[str, list[str]], rows: pd.DataFrame, name: str) -> pd.Series:
    cache: dict[tuple[str, pd.Timestamp], pd.Series] = {}
    out = []
    for r in rows.itertuples(index=False):
        d = pd.Timestamp(r.entry_date); t = str(r.theme); s = str(r.symbol); key=(t,d)
        if key not in cache:
            members = [x for x in theme_members.get(t, []) if x in period_ret.columns]
            if d in period_ret.index and len(members) >= 3:
                cache[key] = rs.rank_within(period_ret.loc[d, members])
            else:
                cache[key] = pd.Series(np.nan, index=members)
        v = cache[key].get(s, np.nan); out.append(float(v) if pd.notna(v) else np.nan)
    return pd.Series(out, index=rows.index, name=name)


def add_term_flow_stage_features(rows: pd.DataFrame, ohlcv: dict[str, pd.DataFrame], stock_ret: pd.DataFrame, theme_ret: pd.DataFrame, theme_members: dict[str, list[str]]) -> pd.DataFrame:
    out = rows.copy()
    close = ohlcv["close"][stock_ret.columns]
    volume = ohlcv["volume"][stock_ret.columns]

    p21 = er.period_return(stock_ret, 21); p63 = er.period_return(stock_ret, 63); p252 = er.period_return(stock_ret, 252)
    out["rs21_pct"] = rank_within_theme_matrix(p21, theme_members, out, "rs21_pct")
    out["rs63_pct"] = rank_within_theme_matrix(p63, theme_members, out, "rs63_pct")
    out["rs252_pct_recalc"] = rank_within_theme_matrix(p252, theme_members, out, "rs252_pct_recalc")
    out["term21_63"] = out["rs21_pct"] - out["rs63_pct"]
    out["term63_252"] = out["rs63_pct"] - out["rs252_pct_recalc"]
    out["term21_252"] = out["rs21_pct"] - out["rs252_pct_recalc"]

    # Capital concentration: stock dollar-volume share of its current theme.
    dv = close * volume
    share_by_theme: dict[str, pd.DataFrame] = {}
    for t, members0 in theme_members.items():
        members = [s for s in members0 if s in dv.columns]
        if len(members) < 3: continue
        block = dv[members]
        denom = block.sum(axis=1, min_count=1).replace(0.0, np.nan)
        share_by_theme[t] = block.div(denom, axis=0)

    theme5 = er.period_return(theme_ret, 5)
    stock5 = er.period_return(stock_ret, 5)
    share_ratio_vals=[]; excess5_vals=[]
    for r in out.itertuples(index=False):
        d=pd.Timestamp(r.entry_date); t=str(r.theme); s=str(r.symbol)
        sh=share_by_theme.get(t)
        if sh is not None and s in sh.columns and d in sh.index:
            pos=sh.index.get_loc(d)
            if isinstance(pos,(int,np.integer)):
                cur=sh.iloc[max(0,pos-4):pos+1][s].mean()
                prior=sh.iloc[max(0,pos-24):max(0,pos-4)][s].mean()
                ratio=float(cur/prior) if pd.notna(cur) and pd.notna(prior) and prior>0 else np.nan
            else: ratio=np.nan
        else: ratio=np.nan
        share_ratio_vals.append(ratio)
        sr=stock5.at[d,s] if d in stock5.index and s in stock5.columns else np.nan
        tr=theme5.at[d,t] if d in theme5.index and t in theme5.columns else np.nan
        excess5_vals.append(float(sr-tr) if pd.notna(sr) and pd.notna(tr) else np.nan)
    out["flow_share_ratio_5v20"] = share_ratio_vals
    out["stock_excess5"] = excess5_vals
    denom = pd.to_numeric(out["flow_share_ratio_5v20"], errors="coerce").clip(lower=0.5, upper=3.0)
    out["price_efficiency5"] = pd.to_numeric(out["stock_excess5"], errors="coerce") / denom

    # Weinstein-style weekly state proxy. Strictly prior completed Friday avoids partial-week lookahead.
    weekly_close = close.resample("W-FRI").last()
    w30 = weekly_close.rolling(30, min_periods=24).mean()
    w30_slope4 = w30 / w30.shift(4) - 1.0
    weekly_idx=weekly_close.index
    wc=[]; wm=[]; ws=[]
    for r in out.itertuples(index=False):
        d=pd.Timestamp(r.entry_date); s=str(r.symbol); pos=weekly_idx.searchsorted(d, side="left")-1
        if pos>=0 and s in weekly_close.columns:
            wd=weekly_idx[pos]; c=weekly_close.at[wd,s]; m=w30.at[wd,s]; sl=w30_slope4.at[wd,s]
        else: c=m=sl=np.nan
        wc.append(float(c) if pd.notna(c) else np.nan); wm.append(float(m) if pd.notna(m) else np.nan); ws.append(float(sl) if pd.notna(sl) else np.nan)
    out["weekly_close_prior"] = wc; out["w30"] = wm; out["w30_slope4"] = ws
    out["w30_distance"] = pd.to_numeric(out["weekly_close_prior"], errors="coerce") / pd.to_numeric(out["w30"], errors="coerce") - 1.0
    out["stage2_proxy"] = (out["weekly_close_prior"] > out["w30"]) & (out["w30_slope4"] > 0)
    out["stage4_proxy"] = (out["weekly_close_prior"] < out["w30"]) & (out["w30_slope4"] < 0)
    out["early_stage2_proxy"] = out["stage2_proxy"] & out["w30_distance"].between(0.0,0.15,inclusive="both")
    out["late_stage2_proxy"] = out["stage2_proxy"] & (out["w30_distance"] > 0.15)

    out["rs_ladder_up"] = (out["rs21_pct"] > out["rs63_pct"]) & (out["rs63_pct"] > out["rs252_pct_recalc"])
    out["flow_accel_1p25"] = out["flow_share_ratio_5v20"] >= 1.25
    out["flow_accel_1p50"] = out["flow_share_ratio_5v20"] >= 1.50
    out["low_effort_lead"] = (out["stock_excess5"] > 0) & (out["flow_share_ratio_5v20"] <= 1.0)
    out["ladder_flow"] = out["rs_ladder_up"] & out["flow_accel_1p25"]
    out["ladder_early_stage2"] = out["rs_ladder_up"] & out["early_stage2_proxy"]
    return out


def add_outcomes(rows: pd.DataFrame, close: pd.DataFrame, theme_members: dict[str, list[str]]) -> pd.DataFrame:
    out=rows.copy(); fwd20=close.shift(-20)/close-1.0
    ranks=[]
    for r in out.itertuples(index=False):
        d=pd.Timestamp(r.entry_date); t=str(r.theme); s=str(r.symbol)
        members=[x for x in theme_members.get(t,[]) if x in fwd20.columns]
        if d in fwd20.index and len(members)>=3:
            vals=fwd20.loc[d,members].dropna(); rank=vals.rank(pct=True,method="average").get(s,np.nan) if len(vals)>=3 else np.nan
        else: rank=np.nan
        ranks.append(float(rank) if pd.notna(rank) else np.nan)
    out["future_theme_rank20"] = ranks
    out["future_theme_top20"] = out["future_theme_rank20"] >= TOP_THEME_CUTOFF
    out["pioneer_winner10"] = pd.to_numeric(out["stock_minus_peers_20"],errors="coerce") >= WINNER_EXCESS_20
    return out


def binary_masks(frame: pd.DataFrame) -> dict[str,pd.Series]:
    return {
        "RS_LADDER_UP": frame["rs_ladder_up"].fillna(False),
        "FLOW_ACCEL_1P25": frame["flow_accel_1p25"].fillna(False),
        "FLOW_ACCEL_1P50": frame["flow_accel_1p50"].fillna(False),
        "STAGE2_PROXY": frame["stage2_proxy"].fillna(False),
        "EARLY_STAGE2_PROXY": frame["early_stage2_proxy"].fillna(False),
        "LATE_STAGE2_PROXY": frame["late_stage2_proxy"].fillna(False),
        "LOW_EFFORT_LEAD": frame["low_effort_lead"].fillna(False),
        "LADDER_FLOW": frame["ladder_flow"].fillna(False),
        "LADDER_EARLY_STAGE2": frame["ladder_early_stage2"].fillna(False),
    }


def group_summary(frame: pd.DataFrame, hi: pd.Series, lo: pd.Series, seed: int) -> dict[str,Any]:
    peer="stock_minus_peers_20"
    a=frame.loc[hi,peer].dropna(); b=frame.loc[lo,peer].dropna()
    return {
        "winner10": fisher_two_groups(frame,hi,lo,"pioneer_winner10"),
        "theme_top20": fisher_two_groups(frame,hi,lo,"future_theme_top20"),
        "peer20": {
            "high_n":int(len(a)),"low_n":int(len(b)),
            "high_mean":float(a.mean()) if len(a) else None,"low_mean":float(b.mean()) if len(b) else None,
            "diff":float(a.mean()-b.mean()) if len(a) and len(b) else None,
            "date_ci95":cluster_diff_ci(frame,hi,lo,peer,"entry_date",seed),
            "theme_ci95":cluster_diff_ci(frame,hi,lo,peer,"theme",seed+1000),
        }
    }


def evaluate_context(frame: pd.DataFrame, seed: int) -> dict[str,Any]:
    result={"n":int(len(frame)),"dates":int(frame["entry_date"].nunique()) if len(frame) else 0,"themes":int(frame["theme"].nunique()) if len(frame) else 0,"continuous":{},"binary":{}}
    for i,f in enumerate(CONTINUOUS_FACTORS):
        x=pd.to_numeric(frame[f],errors="coerce"); valid=x.notna()
        if valid.sum()<30: result["continuous"][f]={"n":int(valid.sum())}; continue
        q1,q2=x[valid].quantile([1/3,2/3]); hi=valid & (x>=q2); lo=valid & (x<=q1)
        result["continuous"][f]={"q33":float(q1),"q67":float(q2),**group_summary(frame,hi,lo,seed+i*100)}
    for j,(name,mask) in enumerate(binary_masks(frame).items()):
        comp=~mask
        result["binary"][name]=group_summary(frame,mask,comp,seed+5000+j*100)
    return result


def main()->None:
    ap=argparse.ArgumentParser(); ap.add_argument("--root",default="."); ap.add_argument("--output",required=True); ap.add_argument("--analysis-start",default="2016-01-04"); ap.add_argument("--analysis-end",default="2026-06-20"); ap.add_argument("--exclude-first",type=int,default=0); ap.add_argument("--max-tickers",type=int,default=1500); ap.add_argument("--batch-size",type=int,default=75); ap.add_argument("--min-members",type=int,default=3); args=ap.parse_args()
    root=Path(args.root); output=root/args.output; output.mkdir(parents=True,exist_ok=True)
    snapshot=er.load_json(root/"sector_snapshot.json"); theme_members_all,taxonomy_candidates=er.extract_theme_members(snapshot); industry_map=er.read_industry_map(root/"industry_map.json"); universe=er.read_universe_symbols(root/"universe.csv"); allowed=set(industry_map)&universe
    excluded=er.stratified_symbols(theme_members_all,allowed,args.exclude_first) if args.exclude_first>0 else []; selected=er.stratified_symbols(theme_members_all,allowed-set(excluded),args.max_tickers); requested=selected+(["SPY"] if "SPY" not in selected else [])
    ds=str((pd.Timestamp(args.analysis_start)-pd.Timedelta(days=1100)).date()); de=str((pd.Timestamp(args.analysis_end)+pd.Timedelta(days=120)).date()); ohlcv,download_diag=iq.download_ohlcv(requested,ds,de,args.batch_size)
    close=ohlcv["close"]; stock_cols=[s for s in selected if s in close.columns]; stock_close=close[stock_cols]; stock_high=ohlcv["high"][stock_cols]; stock_low=ohlcv["low"][stock_cols]; stock_ret=er.arithmetic_returns(stock_close); spy_ret=er.arithmetic_returns(close[["SPY"]])["SPY"]
    theme_members={t:[s for s in m if s in stock_cols] for t,m in theme_members_all.items()}; member_counts={t:len(m) for t,m in theme_members.items()}; theme_ret=er.grouped_equal_weight(stock_ret,theme_members,args.min_members)
    industry_groups={}; sector_groups={}
    for s in stock_cols:
        pair=industry_map.get(s)
        if not pair: continue
        sec,ind=pair
        if sec: sector_groups.setdefault(sec,[]).append(s)
        if ind: industry_groups.setdefault(ind,[]).append(s)
    industry_ret=er.grouped_equal_weight(stock_ret,industry_groups,args.min_members); sector_ret=er.grouped_equal_weight(stock_ret,sector_groups,args.min_members); industry_weights=er.build_parent_weights(theme_members_all,industry_map); sector_weights=ss.build_sector_weights(theme_members_all,industry_map)
    common_themes=sorted(set(theme_ret.columns)&set(industry_weights)&set(sector_weights)); theme_ret=theme_ret[common_themes]
    theme63=er.period_return(theme_ret,63); spy63=er.period_return(spy_ret,63); theme_pct=theme63.sub(spy63,axis=0).rank(axis=1,pct=True,method="average")*100.0
    industry63=er.period_return(industry_ret,63); industry_pct=industry63.sub(spy63,axis=0).rank(axis=1,pct=True,method="average")*100.0; parent_industry_pct=er.weighted_matrix(industry_pct,industry_weights,common_themes)
    sector63=er.period_return(sector_ret,63); sector_pct=sector63.sub(spy63,axis=0).rank(axis=1,pct=True,method="average")*100.0; parent_sector_pct=er.weighted_matrix(sector_pct,sector_weights,common_themes)
    breadth=er.breadth_above_ema21(stock_close,theme_members,args.min_members).reindex(columns=common_themes)
    start,end=pd.Timestamp(args.analysis_start),pd.Timestamp(args.analysis_end); momentum_mask=cl.momentum_mask(theme_pct,parent_industry_pct,breadth); events=er.extract_events(momentum_mask,theme_pct,parent_industry_pct,breadth,member_counts,start,end)
    stock21=er.period_return(stock_ret,21); rows=ie.build_entry_rows(events,momentum_mask,theme_members,stock_close,stock_high,stock_low,stock_ret,spy_ret,stock21,theme_pct,parent_industry_pct,parent_sector_pct,breadth)
    matrices=iq.compute_feature_matrices(ohlcv,stock_cols,stock_ret); rows=iq.enrich_rows(rows,matrices,theme_members); rows=rows[rows["continuous_momentum"].fillna(False)].copy(); rows=add_term_flow_stage_features(rows,ohlcv,stock_ret,theme_ret,theme_members); rows=add_outcomes(rows,stock_close,theme_members)
    hidden=(pd.to_numeric(rows["dist_prior_high20"],errors="coerce")<=-0.05)&(pd.to_numeric(rows["industry_rs"],errors="coerce")<80)
    contexts={"ALL_CONTINUOUS":rows,"HIDDEN_IGNITION":rows.loc[hidden].copy()}
    result={"status":"PRELIMINARY_FIXED_CURRENT_TAXONOMY_UNIQUE_STOCK_EDGE","frozen_definition":{"outcomes":{"pioneer_winner10":"20d stock-minus-theme-peers >= +10%","future_theme_top20":"20d forward stock return ranks in top20% of current theme members"},"factors":list(CONTINUOUS_FACTORS),"binary_rules":BINARY_RULES,"stage_note":"Weinstein-style operational proxy only: prior completed weekly close relative to 30-week SMA and 4-week slope; not exact canonical stage classification"},"coverage":{"excluded_first":len(excluded),"selected":len(stock_cols),"rows":len(rows)},"download":download_diag,"taxonomy_candidates":taxonomy_candidates,"contexts":{}}
    for k,frame in contexts.items(): result["contexts"][k]=evaluate_context(frame,70000+(0 if k=="ALL_CONTINUOUS" else 10000))
    rows.to_csv(output/"unique_stock_edge_rows.csv",index=False); (output/"summary.json").write_text(json.dumps(safe(result),ensure_ascii=False,indent=2),encoding="utf-8"); print("=== UNIQUE_STOCK_EDGE_RESULT_JSON ===",flush=True); print(json.dumps(safe(result),ensure_ascii=False,indent=2),flush=True); print("=== END_UNIQUE_STOCK_EDGE_RESULT_JSON ===",flush=True)

if __name__=="__main__": main()
