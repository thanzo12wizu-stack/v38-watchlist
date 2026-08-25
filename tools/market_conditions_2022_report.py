#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
import market_conditions_deterioration_validate as base

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'market_conditions_2022_report.json'
base.START='2019-01-01'; base.END='2026-08-25'

def band(x): return base.band(float(x))

def first_below(s, th, start=None, end=None):
    z=s
    if start is not None: z=z[z.index>=start]
    if end is not None: z=z[z.index<=end]
    h=z[z<th]
    return str(h.index[0].date()) if len(h) else None

def band_days(s):
    labels=s.dropna().map(band)
    order=['STRONG BEAR','BEAR','WEAK BEAR','NEUTRAL','WEAK BULL','BULL','STRONG BULL']
    return {k:int((labels==k).sum()) for k in order}

def summary(s):
    z=s.loc['2022-01-01':'2022-12-31'].dropna()
    return {
      'start':float(z.iloc[0]), 'start_date':str(z.index[0].date()),
      'end':float(z.iloc[-1]), 'end_date':str(z.index[-1].date()),
      'min':float(z.min()), 'min_date':str(z.idxmin().date()),
      'max':float(z.max()), 'max_date':str(z.idxmax().date()),
      'mean':float(z.mean()), 'median':float(z.median()),
      'days_below65':int((z<65).sum()), 'days_below55':int((z<55).sum()), 'days_below45':int((z<45).sum()),
      'band_days':band_days(z),
    }

def main():
    px,failed=base.download_prices()
    px=px.loc[:'2026-08-24']
    m=base.build_metrics(px)
    q=px['QQQ'].dropna(); m=m.reindex(q.index)
    core=(.15*m.short+.55*m.medium_level+.20*m.long+.10*m.damage).ewm(span=2,adjust=False).mean()
    pen_base=.5*(-m.breadth_delta10).clip(lower=0)+.5*(m.breadth_core.rolling(20,min_periods=5).max()-m.breadth_core).clip(lower=0)
    pen3=pen_base.ewm(span=3,adjust=False).mean()
    alpha=3.0; floor=57.5; struct_th=60.0; release=-0.07
    unf=(core-.55*alpha*pen3).clip(0,100)
    structural=((m.long+m.damage)/2).ewm(span=2,adjust=False).mean()
    qdd=q/q.rolling(63,min_periods=20).max()-1
    guard=(structural>=struct_th)&(qdd>release)&(unf<floor)
    cand=unf.where(~guard,floor)

    q22=q.loc['2022-01-01':'2022-12-31']
    qret=float(q22.iloc[-1]/q22.iloc[0]-1)
    qpeak=q.loc[:'2022-12-31'].cummax()
    qdd_full=q/qpeak-1
    zdd=qdd_full.loc['2022-01-01':'2022-12-31']

    episodes=base.drawdown_episodes(q.loc['2020-01-01':'2024-12-31'],-.08,-.02)
    eps=[]
    for e in episodes:
        if e['trough'].year==2022 or e['peak'].year==2022 or (e['peak']<=pd.Timestamp('2022-12-31') and e['end']>=pd.Timestamp('2022-01-01')):
            row={'peak':str(e['peak'].date()),'start':str(e['start'].date()),'trough':str(e['trough'].date()),'end':str(e['end'].date()),'qqq_dd_pct':float(e['dd']*100)}
            for label,s in [('current',core),('candidate',cand)]:
                row[label]={
                  'score_at_peak':float(s.loc[e['peak']]) if e['peak'] in s.index and pd.notna(s.loc[e['peak']]) else None,
                  'first_below65':first_below(s,65,e['peak'],e['trough']),
                  'first_below55':first_below(s,55,e['peak'],e['trough']),
                  'first_below45':first_below(s,45,e['peak'],e['trough']),
                  'score_at_trough':float(s.loc[e['trough']]) if e['trough'] in s.index and pd.notna(s.loc[e['trough']]) else None,
                  'min_peak_to_trough':float(s.loc[e['peak']:e['trough']].min()),
                  'min_date':str(s.loc[e['peak']:e['trough']].idxmin().date()),
                }
            eps.append(row)

    dates=['2022-01-03','2022-01-24','2022-03-14','2022-06-16','2022-08-16','2022-10-13','2022-12-30']
    checkpoints=[]
    for ds in dates:
        dt=pd.Timestamp(ds)
        if dt in core.index:
            checkpoints.append({'date':ds,'qqq':float(q.loc[dt]),'current':float(core.loc[dt]),'candidate':float(cand.loc[dt]),'candidate_band':band(cand.loc[dt]),'structural':float(structural.loc[dt]),'deterioration_penalty':float((core-unf).loc[dt]),'guard':bool(guard.loc[dt])})

    out={
      'candidate':{'alpha':alpha,'floor':floor,'struct_th':struct_th,'release_dd_63d':release},
      'failed_etfs':failed,
      'qqq_2022':{'return_pct':qret*100,'max_drawdown_pct':float(zdd.min()*100),'max_drawdown_date':str(zdd.idxmin().date())},
      'current_mc_2022':summary(core),
      'candidate_mc_2022':summary(cand),
      'episodes_overlapping_2022':eps,
      'checkpoints':checkpoints,
      'guard_days_2022':int(guard.loc['2022-01-01':'2022-12-31'].sum()),
    }
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(out,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
