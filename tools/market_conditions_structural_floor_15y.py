#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'market_conditions_structural_floor_15y.json'
TARGET=pd.Timestamp('2026-08-21')

BANDS=[(-1e9,20,'STRONG BEAR'),(20,35,'BEAR'),(35,45,'WEAK BEAR'),(45,55,'NEUTRAL'),(55,65,'WEAK BULL'),(65,80,'BULL'),(80,1e9,'STRONG BULL')]
def band(x):
    for lo,hi,n in BANDS:
        if lo<=x<hi:return n
    return 'N/A'

def dd_from_high(s,w=63): return s/s.rolling(w,min_periods=20).max()-1

def episodes(q):
    peak=float(q.iloc[0]); pdte=q.index[0]; active=False; out=[]
    for dt,v0 in q.items():
        v=float(v0)
        if not active:
            if v>peak: peak=v; pdte=dt
            if v/peak-1<=-.08:
                active=True; ep=peak; epd=pdte; trough=v; td=dt
        else:
            if v<trough: trough=v; td=dt
            if v/ep-1>=-.02:
                out.append((epd,td,trough/ep-1)); active=False; peak=v; pdte=dt
    if active: out.append((epd,td,trough/ep-1))
    return out

def sessions(idx,a,b): return max(len(idx[(idx>=a)&(idx<=b)])-1,0)

def assess(name,s,d,floor_active,eps):
    q=d.QQQ; idx=q.index; out={'name':name,'target':float(s.loc[TARGET]),'target_band':band(float(s.loc[TARGET])),'latest':float(s.iloc[-1]),'latest_band':band(float(s.iloc[-1]))}
    for th in (65,55,45):
        arr=[]
        for p,t,_ in eps:
            z=s.loc[p:t]; h=z[z<th]
            if len(h): arr.append(sessions(idx,p,h.index[0]))
        out[f'below{th}_coverage']=len(arr); out[f'below{th}_mean']=float(np.mean(arr)) if arr else None
    benign=[]
    for y in (2013,2017):
        z=s[s.index.year==y]; benign.append({'year':y,'min':float(z.min()),'lt55':int((z<55).sum()),'le45':int((z<=45).sum())})
    out['benign']=benign; out['benign_lt55']=sum(x['lt55'] for x in benign); out['benign_le45']=sum(x['le45'] for x in benign)
    out['floor_days_pct']=float(floor_active.mean()*100)
    out['daily_change']=float(s.diff().abs().mean()); labels=s.map(band); years=(idx[-1]-idx[0]).days/365.25; out['flips_year']=float(((labels!=labels.shift()).sum()-1)/years)
    out['corr63']=float(s.corr(q/q.shift(63)-1)); out['corr21']=float(s.corr(q/q.shift(21)-1))
    hs=s[s.index>=pd.Timestamp('2024-01-01')]; hq=q.reindex(hs.index); out['holdout_corr63']=float(hs.corr(hq/hq.shift(63)-1))
    return out

def main():
    a=pd.read_csv(ROOT/'market_conditions_alpha_context_15y_daily.csv',parse_dates=['date']).set_index('date').sort_index()
    b=pd.read_csv(ROOT/'market_conditions_15y_index_compare_daily.csv',parse_dates=['date']).set_index('date').sort_index()
    d=a.join(b[['SPY']],how='inner').loc['2011-01-01':'2026-08-24'].copy()
    d=d.rename(columns={'mc_alpha_0.0':'core','mc_alpha_0.75':'fast075'})
    d['qqq_dd63']=dd_from_high(d.QQQ); d['spy_dd63']=dd_from_high(d.SPY)
    effect=(d.core-d.fast075)/.75
    eps=episodes(d.QQQ)
    rows=[]
    for alpha in (1.5,2.0,2.5,3.0,3.5,4.0):
      unf=(d.core-alpha*effect).clip(0,100)
      for floor in (50.0,52.5,55.0):
       for core_th in (65,70,75):
        for qth in (-.03,-.04,-.05,-.06):
         for sth in (-.02,-.03,-.04,-.05):
          active=(d.core>=core_th)&(d.qqq_dd63>qth)&(d.spy_dd63>sth)&(unf<floor)
          s=unf.where(~active,floor)
          name=f'a{alpha:g}_f{floor:g}_c{core_th}_q{abs(int(qth*100))}_s{abs(int(sth*100))}'
          r=assess(name,s,d,active,eps); r.update({'alpha':alpha,'floor':floor,'core_th':core_th,'qth':qth,'sth':sth})
          # Score constraints. Target 52-58 preferred; normal bull must not fall below45; major drawdowns should all cross65 and most cross55/45.
          target_pen=0 if 52<=r['target']<=58 else min(abs(r['target']-52),abs(r['target']-58))*1.5
          r['penalty']=target_pen+(21-r['below65_coverage'])*10+(20-r['below55_coverage'])*5+(18-r['below45_coverage'])*2+r['benign_lt55']*.4+r['benign_le45']*2+max(.60-r['corr63'],0)*100+max(r['daily_change']-4,0)*2+max(r['floor_days_pct']-12,0)*.2
          rows.append(r)
    rows.sort(key=lambda x:x['penalty'])
    feasible=[r for r in rows if 52<=r['target']<=58 and r['below65_coverage']==21 and r['below55_coverage']>=19 and r['below45_coverage']>=17 and r['benign_le45']==0 and r['benign_lt55']<=10 and r['corr63']>=.60]
    out={'definition':{'unfloored':'core - alpha * ((core-fast_alpha0.75)/0.75)','floor':'when structural core is strong and QQQ/SPY 63d drawdowns remain shallow, do not let deterioration penalty push MC below neutral floor','NQSAR_VIX':'not used in MC score; reserved for post-score context'},'episodes':len(eps),'top20':rows[:20],'feasible':feasible[:20]}
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'top10':rows[:10],'feasible_n':len(feasible),'feasible_top':feasible[:5]},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
