#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

import market_conditions_deterioration_validate as base

OUT_FULL = Path("market_conditions_deterioration_penalty_validation.json")
OUT_COMPACT = Path("market_conditions_deterioration_penalty_validation_compact.json")
OUT_DAILY = Path("market_conditions_deterioration_penalty_daily_2026.csv")


def make_candidates(m: pd.DataFrame) -> dict[str,pd.DataFrame]:
    peak20 = m["breadth_core"].rolling(20,min_periods=5).max()
    peak_drop20 = m["breadth_core"] - peak20
    d10_bad = (-m["breadth_delta10"]).clip(lower=0)
    peak_bad = (-peak_drop20).clip(lower=0)
    combo_bad = .5*d10_bad + .5*peak_bad

    specs = {
        "baseline_15552010": ("none",0.0),
        "d10_penalty_0p5": ("d10",0.5),
        "d10_penalty_1p0": ("d10",1.0),
        "peak20_penalty_0p75": ("peak",0.75),
        "combo_penalty_0p75": ("combo",0.75),
        "combo_penalty_1p0": ("combo",1.0),
        "combo_penalty_1p25": ("combo",1.25),
    }
    out={}
    for name,(kind,alpha) in specs.items():
        if kind=="none": bad=pd.Series(0.0,index=m.index)
        elif kind=="d10": bad=d10_bad
        elif kind=="peak": bad=peak_bad
        else: bad=combo_bad
        # Penalty only: improvement does not boost Market Conditions.
        penalty=(alpha*bad).clip(0,30)
        medium=(m["medium_level"]-penalty).clip(0,100)
        raw=.15*m["short"]+.55*medium+.20*m["long"]+.10*m["damage"]
        score=raw.ewm(span=2,adjust=False).mean()
        f=m.copy()
        f["peak_drop20"]=peak_drop20
        f["d10_bad"]=d10_bad
        f["peak_bad"]=peak_bad
        f["combo_bad"]=combo_bad
        f["deterioration_penalty"]=penalty
        f["medium"]=medium; f["raw"]=raw; f["score"]=score
        out[name]=f
    return out


def main():
    px,failed=base.download_prices(); px=px.loc[:base.EVAL_END]
    m=base.build_metrics(px); qqq=px["QQQ"]
    candidates=make_candidates(m)
    episodes=base.drawdown_episodes(qqq.loc[qqq.index>=base.EVAL_START])
    eval_mask=(m.index>=base.EVAL_START)&(m.index<=base.EVAL_END)
    latest_date=m.loc[eval_mask].dropna(subset=["breadth_core"]).index[-1]

    result={
        "scope":{
            "evaluation":"2016-01-01..2026-08-24",
            "failed_tickers":failed,
            "base":"Short15 / Medium55 / Long20 / Damage10; EMA2; fixed 43 ETF family-balanced universe",
            "penalty_only":"positive breadth change never boosts score; only deterioration subtracts from Medium",
            "d10":"max(0, -10-session change in breadth_core)",
            "peak20":"max(0, rolling20 max(breadth_core) - breadth_core)",
            "combo":"50% d10 + 50% peak20; alpha multiplies penalty in Medium points",
        },
        "candidates":{}
    }

    for name,f in candidates.items():
        s=f["score"].where(eval_mask).dropna()
        eps=base.episode_stats(f,qqq,episodes)
        selected=[r for r in eps if pd.Timestamp(r["trough"]).year in (2022,2025,2026)]
        cur=f.loc[latest_date]
        result["candidates"][name]={
            "current":{
                "date":str(latest_date.date()),
                "score":float(cur["score"]),"band":base.band(float(cur["score"])),
                "short":float(cur["short"]),"medium_level":float(cur["medium_level"]),"medium_used":float(cur["medium"]),
                "long":float(cur["long"]),"damage":float(cur["damage"]),
                "breadth_core":float(cur["breadth_core"]),"breadth_delta10":float(cur["breadth_delta10"]),"breadth_delta20":float(cur["breadth_delta20"]),
                "peak_drop20":float(cur["peak_drop20"]),"deterioration_penalty":float(cur["deterioration_penalty"]),
            },
            "timescale_corr":base.trailing_corr(s,qqq),
            "noise":{"mean_abs_daily_change":float(s.diff().abs().mean()),**base.band_flip_stats(s)},
            "nqsar_overlap":base.gate_overlap(s),
            "all_drawdowns":base.avg_episode(eps),
            "case_2022_2025_2026":selected,
        }

    OUT_FULL.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    compact={"scope":result["scope"],"candidates":result["candidates"]}
    OUT_COMPACT.write_text(json.dumps(compact,ensure_ascii=False,indent=2),encoding="utf-8")
    daily=pd.DataFrame(index=m.index)
    daily["qqq"]=qqq; daily["breadth_core"]=m["breadth_core"]; daily["breadth_delta10"]=m["breadth_delta10"]
    anyf=next(iter(candidates.values())); daily["peak_drop20"]=anyf["peak_drop20"]
    for name,f in candidates.items(): daily[name]=f["score"]
    daily.loc[daily.index>=pd.Timestamp("2026-01-01")].to_csv(OUT_DAILY,index_label="date")
    print(json.dumps(compact,ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
