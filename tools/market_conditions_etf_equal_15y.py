#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
import market_conditions_simple_variants_15y as base

ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/'market_conditions_etf_equal_15y.json'

def mean_bool(a,valid): return a.where(valid).mean(axis=1,skipna=True)*100

def build_direct(px):
    c=px.reindex(columns=[x for x in base.UNIVERSE if x in px.columns])
    ma10=c.rolling(10,min_periods=10).mean(); ma20=c.rolling(20,min_periods=20).mean(); ma50=c.rolling(50,min_periods=50).mean(); ma200=c.rolling(200,min_periods=200).mean()
    m=pd.DataFrame(index=c.index)
    for n,h in [('ret5',5),('ret21',21),('ret63',63),('ret252',252)]:
        p=c.shift(h); m[n]=mean_bool((c/p-1)>0,c.notna()&p.notna())
    for n,ma in [('above10',ma10),('above20',ma20),('above50',ma50),('above200',ma200)]:m[n]=mean_bool(c>ma,c.notna()&ma.notna())
    m['ma20_gt50']=mean_bool(ma20>ma50,ma20.notna()&ma50.notna()); m['ma50_gt200']=mean_bool(ma50>ma200,ma50.notna()&ma200.notna())
    hi=c.rolling(252,min_periods=200).max(); dd=c/hi-1; ddscore=((dd+0.30)/0.25*100).clip(0,100)
    m['dd_score']=ddscore.mean(axis=1,skipna=True); m['within10']=mean_bool(dd>=-0.10,dd.notna())
    m['delta20']=(50+1.25*(m.above20-m.above20.shift(10))).clip(0,100); m['delta50']=(50+1.25*(m.above50-m.above50.shift(10))).clip(0,100)
    return m

def main():
    px,failed=base.download(); px=px.loc[:base.EVAL_END]; m=build_direct(px); q=px.QQQ.loc[base.EVAL_START:base.EVAL_END].dropna(); spy=px.SPY.reindex(q.index); iwm=px.IWM.reindex(q.index); eps=base.drawdown_episodes(q)
    raw={'etf_equal12':m[base.METRICS].mean(axis=1),'etf_equal_speed14':m[base.METRICS+['delta20','delta50']].mean(axis=1)}
    report={}
    for name,r0 in raw.items():
        s=r0.ewm(span=2,adjust=False).mean().reindex(q.index)
        r={'aug21':float(s.loc[pd.Timestamp('2026-08-21')]),'latest':float(s.dropna().iloc[-1]),'qqq21':float(s.corr(q/q.shift(21)-1)),'qqq63':float(s.corr(q/q.shift(63)-1)),'qqq126':float(s.corr(q/q.shift(126)-1)),'spy63':float(s.corr(spy/spy.shift(63)-1)),'iwm63':float(s.corr(iwm/iwm.shift(63)-1)),'daily':float(s.diff().abs().mean()),'y2013':base.year_stats(s,2013),'y2017':base.year_stats(s,2017),'y2022':base.year_stats(s,2022)}
        r.update(base.quality(s,q,eps)); r['focus']=base.episode_focus(s,eps); report[name]=r
    out={'definition':{'universe_count':len(base.UNIVERSE),'etf_weighting':'all available ETFs equal; no Broad/Sector/Industry family rebalance','metric_weighting':'all metrics equal','metrics':base.METRICS},'failed':failed,'snapshot_2026_08_21':{k:float(m.loc[pd.Timestamp('2026-08-21'),k]) for k in base.METRICS+['delta20','delta50']},'variants':report}
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps(out,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
