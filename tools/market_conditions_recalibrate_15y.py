#!/usr/bin/env python3
from __future__ import annotations
import json, math
from pathlib import Path
import numpy as np
import pandas as pd

import market_conditions_deterioration_validate as base

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'market_conditions_recalibrate_15y.json'
DAILY=ROOT/'market_conditions_recalibrate_15y_daily.csv'
base.START='2009-01-01'; base.END='2026-08-25'
EVAL_START=pd.Timestamp('2011-01-01'); EVAL_END=pd.Timestamp('2026-08-24')
TARGET_DATE=pd.Timestamp('2026-08-21')


def add_metrics(px:pd.DataFrame,m:pd.DataFrame)->pd.DataFrame:
    c=px.reindex(columns=[x for x in base.UNIVERSE if x in px.columns])
    # 1Y breadth and YTD breadth, matching the spirit of Oratnek's multi-horizon inputs.
    m=m.copy()
    m['ret252']=base.metric_ret_positive(c,252)
    year_first=c.groupby(c.index.year).transform('first')
    valid=c.notna()&year_first.notna(); m['ytd']=base.participation((c/year_first-1).gt(0),valid)
    return m


def ema2(x:pd.Series)->pd.Series: return x.ewm(span=2,adjust=False).mean()

def continuous_model(m:pd.DataFrame,weights:tuple[float,float,float,float])->pd.Series:
    s,md,l,d=weights
    return ema2(s*m['short']+md*m['medium_level']+l*m['long']+d*m['damage'])


def equal_cont(m:pd.DataFrame)->pd.Series:
    cols=['ret5','ret21','ret63','ytd','ret252','above10','above20','above50','above200','ma20_gt_50','ma50_gt_200','ma50_rising','dd_score','within10']
    return ema2(m[cols].mean(axis=1))


def vote_model(m:pd.DataFrame,t:float,dd_th:float,include_dir:bool=False,include_ret63:bool=False)->pd.Series:
    # Binary metric voting deliberately avoids allowing 90%-breadth long-term metrics to swamp recent deterioration.
    cols=['ret5','ret21','ytd','ret252','above10','above20','above50','above200','ma20_gt_50','ma50_gt_200']
    if include_dir: cols.append('ma50_rising')
    if include_ret63: cols.append('ret63')
    votes=[m[c].ge(t).astype(float) for c in cols]
    votes.append(m['median_dd_pct'].ge(dd_th).astype(float))
    raw=pd.concat(votes,axis=1).mean(axis=1)*100.0
    return ema2(raw)


def band(x:float)->str: return base.band(float(x))

def drawdown_episodes(q:pd.Series): return base.drawdown_episodes(q,trigger=-.08,exit_dd=-.02)

def first_below(s:pd.Series,a,b,th):
    z=s.loc[(s.index>=a)&(s.index<=b)].dropna(); z=z[z<th]
    return z.index[0] if len(z) else None

def first_above(s:pd.Series,a,b,th):
    z=s.loc[(s.index>=a)&(s.index<=b)].dropna(); z=z[z>=th]
    return z.index[0] if len(z) else None


def assess(name:str,s:pd.Series,q:pd.Series,episodes:list[dict])->dict:
    s=s.loc[(s.index>=EVAL_START)&(s.index<=EVAL_END)].dropna(); q=q.reindex(s.index).dropna(); s=s.reindex(q.index)
    idx=q.index
    det=[]; det55=[]; det45=[]; rec=[]
    for e in episodes:
        p,t=e['peak'],e['trough']
        for th,arr in [(65,det),(55,det55),(45,det45)]:
            d=first_below(s,p,t,th)
            if d is not None: arr.append(base.sessions_between(idx,p,d))
        pos=idx.get_indexer([t],method='nearest')[0]; end=idx[min(pos+80,len(idx)-1)]
        d=first_above(s,t,end,65)
        if d is not None: rec.append(base.sessions_between(idx,t,d))
    benign=[]; benign_lt55=0; benign_le45=0
    for y in (2013,2017):
        z=s[s.index.year==y]; qq=q[q.index.year==y]
        benign.append({'year':y,'mc_min':float(z.min()),'days_lt55':int((z<55).sum()),'days_le45':int((z<=45).sum()),'qqq_return_pct':float((qq.iloc[-1]/qq.iloc[0]-1)*100),'qqq_maxdd_pct':float((qq/qq.cummax()-1).min()*100)})
        benign_lt55 += int((z<55).sum()); benign_le45 += int((z<=45).sum())
    cor={}
    for h in (5,21,63,126,252): cor[f'ret{h}']=float(s.corr(q/q.shift(h)-1))
    labels=s.map(band); flips=int((labels!=labels.shift()).sum()-1); years=(idx[-1]-idx[0]).days/365.25
    target=float(s.loc[TARGET_DATE]) if TARGET_DATE in s.index else None
    now=float(s.iloc[-1])
    out={'name':name,'target_2026_08_21':target,'target_band':band(target) if target is not None else None,'latest_2026_08_24':now,'latest_band':band(now),
         'below65_coverage':len(det),'below65_mean':float(np.mean(det)) if det else None,
         'below55_coverage':len(det55),'below55_mean':float(np.mean(det55)) if det55 else None,
         'below45_coverage':len(det45),'below45_mean':float(np.mean(det45)) if det45 else None,
         'recover65_mean':float(np.mean(rec)) if rec else None,'benign':benign,'benign_lt55_days':benign_lt55,'benign_le45_days':benign_le45,
         'corr':cor,'mean_abs_daily_change':float(s.diff().abs().mean()),'flips_per_year':float(flips/years)}
    # ranking objective: do not optimize to Oratnek alone. Reward drawdown coverage + medium correlation + benign-bull stability; target 50-60 is one constraint.
    target_pen=0 if target is not None and 50<=target<=60 else (min(abs(target-50),abs(target-60)) if target is not None else 50)
    cov_pen=(21-len(det))*8+(20-len(det55))*4+(19-len(det45))*2
    speed_pen=max((np.mean(det) if det else 30)-7,0)*1.5
    benign_pen=benign_lt55*0.35+benign_le45*0.8
    corr63=cor['ret63']; corr_pen=max(.62-corr63,0)*100
    noise_pen=max(out['mean_abs_daily_change']-3.5,0)*4+max(out['flips_per_year']-65,0)*.2
    recovery_pen=max((out['recover65_mean'] or 40)-22,0)
    out['objective_penalty']=float(target_pen*1.2+cov_pen+speed_pen+benign_pen+corr_pen+noise_pen+recovery_pen)
    return out


def main():
    px,failed=base.download_prices(); px=px.loc[:EVAL_END]
    m=add_metrics(px,base.build_metrics(px))
    q=px['QQQ'].loc[(px.index>=EVAL_START)&(px.index<=EVAL_END)].dropna(); episodes=drawdown_episodes(q)
    models={}
    models['current_15_55_20_10']=continuous_model(m,(.15,.55,.20,.10))
    # Continuous reweighting candidates: less duplicated medium/long dominance.
    for w in [(.25,.40,.20,.15),(.30,.35,.20,.15),(.30,.30,.20,.20),(.35,.30,.20,.15),(.30,.40,.15,.15)]:
        models[f"cont_{int(w[0]*100)}_{int(w[1]*100)}_{int(w[2]*100)}_{int(w[3]*100)}"]=continuous_model(m,w)
    models['equal14_cont']=equal_cont(m)
    # Oratnek-like binary vote family, without VIX. Search common participation thresholds + median-DD threshold.
    for t in (50,55,60,65,70):
        for dd in (-8,-10,-12,-15):
            for idir,iret in ((False,False),(True,False),(False,True),(True,True)):
                nm=f"vote_t{t}_dd{abs(dd)}_dir{int(idir)}_r63{int(iret)}"
                models[nm]=vote_model(m,t,dd,idir,iret)
    rows=[assess(n,s,q,episodes) for n,s in models.items()]
    rows=sorted(rows,key=lambda x:x['objective_penalty'])
    top=rows[:20]
    # Add a Pareto-style set that satisfies hard desiderata if available.
    feasible=[r for r in rows if 50<=r['target_2026_08_21']<=60 and r['below65_coverage']>=20 and r['benign_lt55_days']<=10 and r['corr']['ret63']>=.60]
    result={'scope':{'evaluation':'2011-01-01..2026-08-24','failed_etfs':failed,'objective':'8/21 target 50-60 is only one constraint; also major-DD detection, benign 2013/2017, 63d correlation, noise, recovery','episodes':len(episodes)},
            'top20':top,'feasible':feasible[:20],'current':next(r for r in rows if r['name']=='current_15_55_20_10')}
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    df=pd.DataFrame(index=q.index)
    for r in [result['current']]+top[:8]:
        if r['name'] not in df.columns: df[r['name']]=models[r['name']].reindex(df.index)
    df['QQQ']=q
    df.to_csv(DAILY,index_label='date')
    print(json.dumps({'scope':result['scope'],'top10':top[:10],'feasible_n':len(feasible)},ensure_ascii=False,indent=2))

if __name__=='__main__': main()
