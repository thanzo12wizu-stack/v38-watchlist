#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
import market_conditions_deterioration_validate as base

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'market_conditions_quantile_vote_15y.json'
base.START='2009-01-01'; base.END='2026-08-25'
EVAL_START=pd.Timestamp('2011-01-01'); EVAL_END=pd.Timestamp('2026-08-24')
TRAIN_END=pd.Timestamp('2023-12-31'); TARGET=pd.Timestamp('2026-08-21')

METRICS=['ret5','ret21','ret63','ytd','ret252','above10','above20','above50','above200','ma20_gt_50','ma50_gt_200','ma50_rising']


def add_metrics(px,m):
    c=px.reindex(columns=[x for x in base.UNIVERSE if x in px.columns]); m=m.copy()
    m['ret252']=base.metric_ret_positive(c,252)
    yf=c.groupby(c.index.year).transform('first'); valid=c.notna()&yf.notna(); m['ytd']=base.participation((c/yf-1).gt(0),valid)
    return m

def score(m,quantile:float,damage_mode:str='median_dd'):
    tr=m.loc[(m.index>=EVAL_START)&(m.index<=TRAIN_END)]
    thresholds={c:float(tr[c].quantile(quantile)) for c in METRICS}
    votes=[m[c].ge(thresholds[c]).astype(float).rename(c) for c in METRICS]
    if damage_mode=='median_dd':
        th=float(tr['median_dd_pct'].quantile(1-quantile)) # less negative is stronger; use complementary q so q=.5 is median
        votes.append(m['median_dd_pct'].ge(th).astype(float).rename('median_dd'))
        thresholds['median_dd_pct']=th
    elif damage_mode=='within10':
        th=float(tr['within10'].quantile(quantile)); votes.append(m['within10'].ge(th).astype(float).rename('within10')); thresholds['within10']=th
    raw=pd.concat(votes,axis=1).mean(axis=1)*100
    return raw.ewm(span=2,adjust=False).mean(),thresholds

def assess(name,s,q,eps):
    s=s.loc[(s.index>=EVAL_START)&(s.index<=EVAL_END)].dropna(); q=q.reindex(s.index).dropna(); s=s.reindex(q.index); idx=q.index
    ans={'name':name,'target':float(s.loc[TARGET]),'latest':float(s.iloc[-1])}
    for th in (65,55,45):
        a=[]
        for e in eps:
            z=s.loc[(s.index>=e['peak'])&(s.index<=e['trough'])]; h=z[z<th]
            if len(h): a.append(base.sessions_between(idx,e['peak'],h.index[0]))
        ans[f'below{th}_coverage']=len(a); ans[f'below{th}_mean']=float(np.mean(a)) if a else None
    rec=[]
    for e in eps:
        pos=idx.get_indexer([e['trough']],method='nearest')[0]; end=idx[min(pos+80,len(idx)-1)]; z=s.loc[(s.index>=e['trough'])&(s.index<=end)]; h=z[z>=65]
        if len(h): rec.append(base.sessions_between(idx,e['trough'],h.index[0]))
    ans['recover65_mean']=float(np.mean(rec)) if rec else None
    benign=[]
    for y in (2013,2017):
        z=s[s.index.year==y]; benign.append({'year':y,'min':float(z.min()),'lt55':int((z<55).sum()),'le45':int((z<=45).sum())})
    ans['benign']=benign; ans['benign_lt55']=sum(x['lt55'] for x in benign); ans['benign_le45']=sum(x['le45'] for x in benign)
    ans['corr']={f'ret{h}':float(s.corr(q/q.shift(h)-1)) for h in (5,21,63,126,252)}
    labels=s.map(lambda x:base.band(float(x))); years=(idx[-1]-idx[0]).days/365.25
    ans['daily_change']=float(s.diff().abs().mean()); ans['flips_year']=float(((labels!=labels.shift()).sum()-1)/years)
    # holdout stats separate
    hs=s[s.index>=pd.Timestamp('2024-01-01')]; hq=q.reindex(hs.index)
    ans['holdout_corr63']=float(hs.corr(hq/hq.shift(63)-1))
    return ans

def main():
    px,failed=base.download_prices(); px=px.loc[:EVAL_END]; m=add_metrics(px,base.build_metrics(px)); q=px['QQQ'].loc[(px.index>=EVAL_START)&(px.index<=EVAL_END)].dropna(); eps=base.drawdown_episodes(q,-.08,-.02)
    rows=[]; thresholds={}
    for quant in (.40,.45,.50,.55,.60,.65):
        for dmg in ('median_dd','within10'):
            s,th=score(m,quant,dmg); name=f'qvote_{int(quant*100)}_{dmg}'; rows.append(assess(name,s,q,eps)); thresholds[name]=th
    # Rank: target 50-60 + high drawdown coverage + benign bull + medium correlation + sane noise. No single-point fitting.
    for r in rows:
        t=r['target']; target_pen=0 if 50<=t<=60 else min(abs(t-50),abs(t-60))*1.0
        r['penalty']=target_pen+(21-r['below65_coverage'])*8+(20-r['below55_coverage'])*4+(19-r['below45_coverage'])*2+r['benign_lt55']*.3+r['benign_le45']*.8+max(.58-r['corr']['ret63'],0)*100+max(r['daily_change']-5,0)*2
    rows.sort(key=lambda x:x['penalty'])
    feasible=[r for r in rows if 50<=r['target']<=60 and r['below65_coverage']>=20 and r['benign_lt55']<=15 and r['corr']['ret63']>=.55]
    out={'scope':{'evaluation':'2011-2026-08-24','train_thresholds':'2011-2023 only','holdout':'2024-2026-08-24','failed_etfs':failed,'episodes':len(eps),'metrics':METRICS},'ranked':rows,'feasible':feasible,'thresholds':{r['name']:thresholds[r['name']] for r in rows[:5]}}
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'top':rows[:8],'feasible':feasible},ensure_ascii=False,indent=2))

if __name__=='__main__': main()
