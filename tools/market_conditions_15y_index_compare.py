#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

import market_conditions_deterioration_validate as base
import market_conditions_deterioration_smoothing_validate as smooth

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "market_conditions_15y_index_compare.json"
OUT_DAILY = ROOT / "market_conditions_15y_index_compare_daily.csv"

# Full warm-up before the requested ~15y evaluation window.
base.START = "2009-01-01"
base.END = "2026-08-25"  # exclusive; includes 2026-08-24
EVAL_START = pd.Timestamp("2011-01-01")
EVAL_END = pd.Timestamp("2026-08-24")

INDEXES = ["QQQ", "SPY", "IWM"]


def baseline_frame(m: pd.DataFrame) -> pd.DataFrame:
    raw = .15*m["short"] + .55*m["medium_level"] + .20*m["long"] + .10*m["damage"]
    f = m.copy()
    f["medium"] = m["medium_level"]
    f["penalty"] = 0.0
    f["raw"] = raw
    f["score"] = raw.ewm(span=2, adjust=False).mean()
    return f


def candidate_frame(m: pd.DataFrame) -> pd.DataFrame:
    # Preferred candidate from the prior deterioration validation:
    # deterioration-only penalty, alpha=1.25, EWM3 smoothing of penalty input.
    return smooth.candidate(m, 1.25, 3)


def trailing_corr(score: pd.Series, idx: pd.Series) -> dict:
    d = pd.DataFrame({"s": score, "x": idx}).dropna()
    out = {}
    for h in (5, 10, 21, 63, 126, 252):
        r = d["x"] / d["x"].shift(h) - 1
        out[f"ret{h}"] = float(d["s"].corr(r))
    return out


def forward_by_band(score: pd.Series, idx: pd.Series) -> dict:
    d = pd.DataFrame({"s": score, "x": idx}).dropna()
    labels = pd.Series([base.band(float(v)) for v in d["s"]], index=d.index)
    out = {}
    for b in ["STRONG BEAR","BEAR","WEAK BEAR","NEUTRAL","WEAK BULL","BULL","STRONG BULL"]:
        mask = labels.eq(b)
        row = {"sessions": int(mask.sum())}
        for h in (21, 63):
            fwd = d["x"].shift(-h) / d["x"] - 1
            vals = fwd[mask].dropna()
            row[f"fwd{h}_mean_pct"] = float(vals.mean()*100) if len(vals) else None
            row[f"fwd{h}_median_pct"] = float(vals.median()*100) if len(vals) else None
            row[f"fwd{h}_positive_pct"] = float((vals>0).mean()*100) if len(vals) else None
        out[b] = row
    return out


def max_drawdown(s: pd.Series) -> float:
    z = s.dropna()
    if z.empty:
        return np.nan
    return float((z/z.cummax()-1).min())


def annual_summary(frame: pd.DataFrame, px: pd.DataFrame) -> list[dict]:
    rows=[]
    for year in range(EVAL_START.year, EVAL_END.year+1):
        a=max(EVAL_START,pd.Timestamp(f"{year}-01-01")); b=min(EVAL_END,pd.Timestamp(f"{year}-12-31"))
        f=frame.loc[(frame.index>=a)&(frame.index<=b),"score"].dropna()
        if f.empty: continue
        row={"year":year,"mc_start":float(f.iloc[0]),"mc_end":float(f.iloc[-1]),"mc_min":float(f.min()),"mc_max":float(f.max())}
        for t in INDEXES:
            s=px[t].loc[(px.index>=a)&(px.index<=b)].dropna()
            row[f"{t}_return_pct"]=float((s.iloc[-1]/s.iloc[0]-1)*100) if len(s)>=2 else None
            row[f"{t}_maxdd_pct"]=float(max_drawdown(s)*100) if len(s) else None
        rows.append(row)
    return rows


def index_window_dd(s: pd.Series, start: pd.Timestamp, end: pd.Timestamp) -> float|None:
    z=s.loc[(s.index>=start)&(s.index<=end)].dropna()
    if z.empty: return None
    first=float(z.iloc[0]); return float((z.min()/first-1)*100)


def threshold_dates(frame: pd.DataFrame, qidx: pd.DatetimeIndex, peak: pd.Timestamp, trough: pd.Timestamp) -> dict:
    out={}
    for th in (65,55,45):
        d=base.first_cross(frame,peak,trough,"score",th,"below")
        out[f"below{th}_date"]=str(d.date()) if d is not None else None
        out[f"below{th}_sessions_from_peak"]=base.sessions_between(qidx,peak,d) if d is not None else None
    recover_end=qidx[min(qidx.get_indexer([trough],method="nearest")[0]+80,len(qidx)-1)]
    for th in (45,55,65):
        d=base.first_cross(frame,trough,recover_end,"score",th,"above")
        out[f"recover{th}_date"]=str(d.date()) if d is not None else None
        out[f"recover{th}_sessions_from_trough"]=base.sessions_between(qidx,trough,d) if d is not None else None
    return out


def episode_compare(basef: pd.DataFrame, candf: pd.DataFrame, px: pd.DataFrame) -> list[dict]:
    q=px["QQQ"].loc[(px.index>=EVAL_START)&(px.index<=EVAL_END)].dropna()
    eps=base.drawdown_episodes(q,trigger=-.08,exit_dd=-.02)
    qidx=q.index
    rows=[]
    for e in eps:
        peak=e["peak"]; trough=e["trough"]
        row={
            "peak":str(peak.date()),"trough":str(trough.date()),"end":str(e["end"].date()),
            "QQQ_dd_pct":float(e["dd"]*100),
            "SPY_dd_same_window_pct":index_window_dd(px["SPY"],peak,trough),
            "IWM_dd_same_window_pct":index_window_dd(px["IWM"],peak,trough),
            "baseline":threshold_dates(basef,qidx,peak,trough),
            "candidate":threshold_dates(candf,qidx,peak,trough),
        }
        rows.append(row)
    return rows


def aggregate_episode(rows:list[dict], which:str)->dict:
    out={}
    for k in ["below65_sessions_from_peak","below55_sessions_from_peak","below45_sessions_from_peak",
              "recover45_sessions_from_trough","recover55_sessions_from_trough","recover65_sessions_from_trough"]:
        vals=[r[which][k] for r in rows if r[which].get(k) is not None]
        out[k+"_coverage"]=len(vals)
        out[k+"_mean"]=float(np.mean(vals)) if vals else None
        out[k+"_median"]=float(np.median(vals)) if vals else None
    return out


def coverage_summary(px:pd.DataFrame)->dict:
    available=px[base.UNIVERSE].notna().sum(axis=1)
    out={}
    for year in [2011,2012,2013,2014,2015,2016,2020,2022,2025,2026]:
        z=available.loc[available.index.year==year]
        if len(z):
            out[str(year)]={"min":int(z.min()),"median":float(z.median()),"max":int(z.max())}
    return out


def high_but_weakening(frame:pd.DataFrame, idx:pd.Series)->dict:
    d=pd.DataFrame({"s":frame["score"],"x":idx}).dropna()
    hi=d["x"].rolling(252,min_periods=200).max()
    near_high=d["x"]>=.97*hi
    cross=(d["s"]<65)&(d["s"].shift(1)>=65)&near_high
    dates=d.index[cross.fillna(False)]
    vals=[]
    for dt in dates:
        loc=d.index.get_loc(dt)
        fut=d["x"].iloc[loc:min(loc+22,len(d))]
        if len(fut)<2: continue
        vals.append(float((fut.min()/fut.iloc[0]-1)*100))
    return {"events":len(vals),"future21_worst_mean_pct":float(np.mean(vals)) if vals else None,
            "future21_worst_median_pct":float(np.median(vals)) if vals else None,
            "future21_worst_le_minus3_pct_share":float(np.mean(np.array(vals)<=-3)*100) if vals else None}


def main():
    px,failed=base.download_prices()
    px=px.loc[:EVAL_END]
    m=base.build_metrics(px)
    basef=baseline_frame(m); candf=candidate_frame(m)
    mask=(m.index>=EVAL_START)&(m.index<=EVAL_END)
    base_s=basef["score"].where(mask).dropna(); cand_s=candf["score"].where(mask).dropna()
    latest=cand_s.index[-1]

    episodes=episode_compare(basef,candf,px)
    result={
        "scope":{
            "evaluation":"2011-01-01..2026-08-24",
            "download_warmup_start":"2009-01-01",
            "universe_n":len(base.UNIVERSE),
            "failed_tickers":failed,
            "baseline":"Short15 / Medium55 / Long20 / Damage10; EMA2",
            "candidate":"baseline + deterioration-only penalty: 1.25 * EWM3(0.5*max(0,-breadth_delta10)+0.5*(rolling20 breadth peak-current)); penalty applied only to Medium",
            "note":"ETF inception dates mean fewer than 43 live instruments in early years; calculations use valid observations with Broad/Sector/Industry family balancing. Coverage is reported explicitly."
        },
        "coverage_available_tickers":coverage_summary(px),
        "current":{
            "date":str(latest.date()),
            "baseline_score":float(basef.loc[latest,"score"]),"baseline_band":base.band(float(basef.loc[latest,"score"])),
            "candidate_score":float(candf.loc[latest,"score"]),"candidate_band":base.band(float(candf.loc[latest,"score"])),
            "candidate_penalty":float(candf.loc[latest,"penalty"]),"breadth_core":float(candf.loc[latest,"breadth_core"]),
            "breadth_delta10":float(candf.loc[latest,"breadth_delta10"]),
        },
        "correlations":{},
        "band_forward_returns":{},
        "noise":{
            "baseline":{"mean_abs_daily_change":float(base_s.diff().abs().mean()),**base.band_flip_stats(base_s)},
            "candidate":{"mean_abs_daily_change":float(cand_s.diff().abs().mean()),**base.band_flip_stats(cand_s)},
        },
        "high_but_weakening":{},
        "episodes":episodes,
        "episode_aggregate":{
            "baseline":aggregate_episode(episodes,"baseline"),
            "candidate":aggregate_episode(episodes,"candidate")
        },
        "annual":{
            "baseline":annual_summary(basef,px),
            "candidate":annual_summary(candf,px),
        }
    }
    for t in INDEXES:
        idx=px[t].loc[(px.index>=EVAL_START)&(px.index<=EVAL_END)]
        result["correlations"][t]={"baseline":trailing_corr(base_s,idx),"candidate":trailing_corr(cand_s,idx)}
        result["band_forward_returns"][t]={"baseline":forward_by_band(base_s,idx),"candidate":forward_by_band(cand_s,idx)}
        result["high_but_weakening"][t]={"baseline":high_but_weakening(basef.loc[mask],idx),"candidate":high_but_weakening(candf.loc[mask],idx)}

    daily=pd.DataFrame(index=m.index)
    daily["baseline_mc"]=basef["score"]
    daily["candidate_mc"]=candf["score"]
    daily["candidate_penalty"]=candf["penalty"]
    daily["breadth_core"]=m["breadth_core"]
    for t in INDEXES: daily[t]=px[t]
    daily.loc[mask].to_csv(OUT_DAILY,index_label="date")
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
