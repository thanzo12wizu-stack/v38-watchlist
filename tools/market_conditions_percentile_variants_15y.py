#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
import market_conditions_simple_variants_15y as base

ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/'market_conditions_percentile_variants_15y.json'

def rolling_pct(s,window,minp):
    return s.rolling(window,min_periods=minp).rank(pct=True)*100.0

def make_scores(m):
    x=m[base.METRICS]; raw=x.mean(axis=1)
    out={}
    for years in (3,5,10):
        w=252*years; minp=252*2 if years>=3 else 252
        p=pd.DataFrame({c:rolling_pct(x[c],w,minp) for c in x.columns})
        eq=p.mean(axis=1)
        mom=p[['ret5','ret21','ret63','ret252']].mean(axis=1); br=p[['above10','above20','above50','above200']].mean(axis=1); tr=p[['ma20_gt50','ma50_gt200']].mean(axis=1); dmg=p[['dd_score','within10']].mean(axis=1)
        fam=pd.concat([mom,br,tr,dmg],axis=1).mean(axis=1)
        out[f'pct{years}y_eq12']=eq.ewm(span=2,adjust=False).mean()
        out[f'pct{years}y_family25']=fam.ewm(span=2,adjust=False).mean()
        if years==5:
            out['hybrid_raw50_pct5y50']=(0.5*raw+0.5*eq).ewm(span=2,adjust=False).mean()
            out['hybrid_raw25_pct5y75']=(0.25*raw+0.75*eq).ewm(span=2,adjust=False).mean()
    return out

def main():
    px,failed=base.download(); px=px.loc[:base.EVAL_END]; m=base.build(px); scores=make_scores(m)
    q=px.QQQ.loc[base.EVAL_START:base.EVAL_END].dropna(); spy=px.SPY.reindex(q.index); iwm=px.IWM.reindex(q.index); eps=base.drawdown_episodes(q)
    report={}
    for name,s0 in scores.items():
        s=s0.reindex(q.index)
        r={'target_2026_08_21':float(s.loc[pd.Timestamp('2026-08-21')]),'latest':float(s.dropna().iloc[-1]),'corr_qqq21':float(s.corr(q/q.shift(21)-1)),'corr_qqq63':float(s.corr(q/q.shift(63)-1)),'corr_qqq126':float(s.corr(q/q.shift(126)-1)),'corr_spy63':float(s.corr(spy/spy.shift(63)-1)),'corr_iwm63':float(s.corr(iwm/iwm.shift(63)-1)),'daily_abs_change':float(s.diff().abs().mean()),'benign_2013':base.year_stats(s,2013),'benign_2017':base.year_stats(s,2017),'year_2022':base.year_stats(s,2022)}
        r.update(base.quality(s,q,eps)); r['focus_episodes']=base.episode_focus(s,eps); report[name]=r
    # Snapshot of 5y percentiles for factor decomposition
    x=m[base.METRICS]; p5=pd.DataFrame({c:rolling_pct(x[c],1260,504) for c in x.columns})
    snap={c:float(p5.loc[pd.Timestamp('2026-08-21'),c]) for c in base.METRICS}
    out={'definition':{'universe_count':len(base.UNIVERSE),'metrics':base.METRICS,'normalization':'each metric converted to rolling percentile of its own historical breadth before equal aggregation','no_lookahead':'rolling window ends on current date','vix_nqsar':'outside score'},'failed':failed,'episodes':len(eps),'pct5_snapshot_2026_08_21':snap,'variants':report}
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps(out,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
