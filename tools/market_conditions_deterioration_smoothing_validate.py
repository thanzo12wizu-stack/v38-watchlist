#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

import market_conditions_deterioration_validate as base

OUT = Path("market_conditions_deterioration_smoothing_validation.json")
OUT_DAILY = Path("market_conditions_deterioration_smoothing_daily_2026.csv")


def candidate(m: pd.DataFrame, alpha: float, span: int) -> pd.DataFrame:
    peak20=m["breadth_core"].rolling(20,min_periods=5).max()
    d10_bad=(-m["breadth_delta10"]).clip(lower=0)
    peak_bad=(peak20-m["breadth_core"]).clip(lower=0)
    bad=.5*d10_bad+.5*peak_bad
    if span>1:
        bad=bad.ewm(span=span,adjust=False).mean()
    penalty=(alpha*bad).clip(0,30)
    medium=(m["medium_level"]-penalty).clip(0,100)
    raw=.15*m["short"]+.55*medium+.20*m["long"]+.10*m["damage"]
    f=m.copy(); f["bad_smoothed"]=bad; f["penalty"]=penalty; f["medium"]=medium; f["raw"]=raw
    f["score"]=raw.ewm(span=2,adjust=False).mean()
    return f


def transient_downgrades(score: pd.Series, qqq: pd.Series) -> dict:
    d=pd.DataFrame({"s":score,"q":qqq}).dropna()
    s=d["s"]; q=d["q"]
    events=[]
    # Cross below 65 after at least 5 consecutive prior sessions >=65.
    for i in range(5,len(d)):
        if s.iloc[i] >= 65 or not (s.iloc[i-5:i] >=65).all():
            continue
        # avoid repeated event until a reclaim has happened
        if events and i <= events[-1].get("reclaim_i",events[-1]["i"]):
            continue
        future=s.iloc[i:min(i+11,len(s))]
        hit=np.flatnonzero((future>=65).to_numpy())
        reclaim_i=(i+int(hit[0])) if len(hit) else None
        qfuture=q.iloc[i:min(i+11,len(q))]
        mae=float(qfuture.min()/q.iloc[i]-1) if len(qfuture) else np.nan
        transient=bool(reclaim_i is not None and reclaim_i-i<=10 and mae>-.03)
        events.append({"i":i,"date":str(s.index[i].date()),"reclaim_i":reclaim_i,
                       "reclaim_sessions":(reclaim_i-i) if reclaim_i is not None else None,
                       "qqq_worst10_pct":mae*100,"transient":transient})
    years=max((s.index[-1]-s.index[0]).days/365.25,1)
    return {"events":len(events),"events_per_year":len(events)/years,
            "transient":sum(int(e["transient"]) for e in events),
            "transient_per_year":sum(int(e["transient"]) for e in events)/years}


def main():
    px,failed=base.download_prices(); px=px.loc[:base.EVAL_END]
    m=base.build_metrics(px); qqq=px["QQQ"]
    specs={
        "baseline":None,
        "combo1p0_raw":(1.0,1),
        "combo1p0_ema3":(1.0,3),
        "combo1p25_raw":(1.25,1),
        "combo1p25_ema3":(1.25,3),
        "combo1p25_ema5":(1.25,5),
    }
    frames={}
    raw0=.15*m["short"]+.55*m["medium_level"]+.20*m["long"]+.10*m["damage"]
    b=m.copy(); b["medium"]=m["medium_level"]; b["penalty"]=0.0; b["score"]=raw0.ewm(span=2,adjust=False).mean(); frames["baseline"]=b
    for name,sp in specs.items():
        if sp is not None: frames[name]=candidate(m,*sp)
    episodes=base.drawdown_episodes(qqq.loc[qqq.index>=base.EVAL_START])
    mask=(m.index>=base.EVAL_START)&(m.index<=base.EVAL_END); latest=m.loc[mask].dropna(subset=["breadth_core"]).index[-1]
    res={"scope":{"evaluation":"2016-01-01..2026-08-24","failed_tickers":failed,
                  "definition":"penalty-only combo = 50% max(0,-breadth delta10) + 50% drawdown of breadth_core from rolling20 peak; test raw vs EWM3/EWM5 before alpha"},"candidates":{}}
    daily=pd.DataFrame(index=m.index); daily["qqq"]=qqq; daily["breadth_core"]=m["breadth_core"]
    for name,f in frames.items():
        s=f["score"].where(mask).dropna(); eps=base.episode_stats(f,qqq,episodes)
        cur=f.loc[latest]
        res["candidates"][name]={
            "current":{"score":float(cur["score"]),"band":base.band(float(cur["score"])),"medium":float(cur["medium"]),"penalty":float(cur["penalty"]),"breadth_core":float(cur["breadth_core"]),"delta10":float(cur["breadth_delta10"])},
            "timescale_corr":base.trailing_corr(s,qqq),
            "noise":{"mean_abs_daily_change":float(s.diff().abs().mean()),**base.band_flip_stats(s)},
            "transient_downgrades":transient_downgrades(s,qqq),
            "nqsar_overlap":base.gate_overlap(s),
            "all_drawdowns":base.avg_episode(eps),
            "case_2022_2025_2026":[r for r in eps if pd.Timestamp(r["trough"]).year in (2022,2025,2026)],
        }
        daily[name]=f["score"]
    OUT.write_text(json.dumps(res,ensure_ascii=False,indent=2),encoding="utf-8")
    OUT_DAILY.parent.mkdir(parents=True,exist_ok=True)
    daily.loc[daily.index>=pd.Timestamp("2026-01-01")].to_csv(OUT_DAILY,index_label="date")
    print(json.dumps(res,ensure_ascii=False,indent=2))

if __name__=="__main__": main()
