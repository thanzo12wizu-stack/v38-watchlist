#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
DAILY=ROOT/'market_conditions_alpha_context_15y_daily.csv'
OUT=ROOT/'market_conditions_false_detection_context.json'

TRAIN_END=pd.Timestamp('2023-12-31')
HOLD_START=pd.Timestamp('2024-01-01')


def maxdd_forward(s:pd.Series,h:int)->pd.Series:
    arr=s.to_numpy(float); out=np.full(len(arr),np.nan)
    for i in range(len(arr)):
        z=arr[i:min(len(arr),i+h+1)]
        if len(z)>=2 and np.isfinite(z[0]): out[i]=np.nanmin(z/z[0]-1)
    return pd.Series(out,index=s.index)


def dd_from_high(s:pd.Series,w:int)->pd.Series:
    hi=s.rolling(w,min_periods=max(20,w//3)).max(); return s/hi-1


def event_rows(d:pd.DataFrame,th:int)->pd.DataFrame:
    mc=d['mc075']
    cross=(mc<th)&(mc.shift(1)>=th)
    rows=d.loc[cross].copy()
    rows['threshold']=th
    rows['future21_dd']=maxdd_forward(d['QQQ'],21).reindex(rows.index)
    rows['true_deterioration']=(rows['future21_dd']<=-.05)|(rows['qqq_dd63']<=-.05)
    return rows


def score_rule(df:pd.DataFrame,k:int,ddq:float,dds:float,vix_on:bool,nq_on:bool):
    votes=pd.DataFrame(index=df.index)
    votes['q']=df['qqq_dd63']<=ddq
    votes['s']=df['spy_dd63']<=dds
    votes['v']=df['vix_elevated'] if vix_on else False
    votes['n']=df['nq_riskoff'] if nq_on else False
    confirmed=votes.sum(axis=1)>=k
    y=df['true_deterioration'].astype(bool)
    tp=int((confirmed&y).sum()); fn=int((~confirmed&y).sum()); fp=int((confirmed&~y).sum()); tn=int((~confirmed&~y).sum())
    recall=tp/(tp+fn) if tp+fn else np.nan
    precision=tp/(tp+fp) if tp+fp else np.nan
    specificity=tn/(tn+fp) if tn+fp else np.nan
    bal=np.nanmean([recall,specificity])
    return {'k':k,'ddq':ddq,'dds':dds,'vix_on':vix_on,'nq_on':nq_on,'tp':tp,'fn':fn,'fp':fp,'tn':tn,
            'recall':float(recall),'precision':float(precision),'specificity':float(specificity),'balanced_accuracy':float(bal)}


def eval_rule(df,r):
    votes=(df['qqq_dd63']<=r['ddq']).astype(int)+(df['spy_dd63']<=r['dds']).astype(int)
    if r['vix_on']: votes += df['vix_elevated'].astype(int)
    if r['nq_on']: votes += df['nq_riskoff'].astype(int)
    pred=votes>=r['k']; y=df['true_deterioration'].astype(bool)
    tp=int((pred&y).sum()); fn=int((~pred&y).sum()); fp=int((pred&~y).sum()); tn=int((~pred&~y).sum())
    return {'n':int(len(df)),'true_n':int(y.sum()),'confirmed_n':int(pred.sum()),'tp':tp,'fn':fn,'fp':fp,'tn':tn,
            'recall':tp/(tp+fn) if tp+fn else None,'precision':tp/(tp+fp) if tp+fp else None,'specificity':tn/(tn+fp) if tn+fp else None,
            'events':[{'date':str(i.date()),'mc':float(df.loc[i,'mc075']),'qqq_dd63_pct':float(df.loc[i,'qqq_dd63']*100),
                       'spy_dd63_pct':float(df.loc[i,'spy_dd63']*100),'nqsar':str(df.loc[i,'nqsar_proxy']),'vix_context':str(df.loc[i,'vix_context']),
                       'future21_dd_pct':float(df.loc[i,'future21_dd']*100),'truth':bool(y.loc[i]),'confirmed':bool(pred.loc[i])} for i in df.index]}


def episode_capture(d:pd.DataFrame,r):
    q=d['QQQ']; hi=q.cummax(); dd=q/hi-1
    eps=[]; active=False; peak=None; trough=None; min_dd=0
    for dt,val in dd.items():
        if not active and val<=-.08:
            active=True; peak=q.loc[:dt].idxmax(); trough=dt; min_dd=val
        elif active:
            if val<min_dd: min_dd=val; trough=dt
            if val>=-.02:
                eps.append((peak,trough,dt,min_dd)); active=False
    if active: eps.append((peak,trough,q.index[-1],min_dd))
    votes=(d['qqq_dd63']<=r['ddq']).astype(int)+(d['spy_dd63']<=r['dds']).astype(int)
    if r['vix_on']: votes += d['vix_elevated'].astype(int)
    if r['nq_on']: votes += d['nq_riskoff'].astype(int)
    conf=(votes>=r['k'])&(d['mc075']<65)
    rows=[]
    for p,t,e,mdd in eps:
        z=conf.loc[(conf.index>=p)&(conf.index<=t)]
        hits=z[z]
        first=hits.index[0] if len(hits) else None
        rows.append({'peak':str(p.date()),'trough':str(t.date()),'dd_pct':float(mdd*100),'captured':first is not None,
                     'first_confirmed':str(first.date()) if first is not None else None,
                     'sessions_from_peak':int(d.loc[p:first].shape[0]-1) if first is not None else None})
    return {'episodes':len(rows),'captured':sum(x['captured'] for x in rows),'rows':rows}


def benign_year_days(d:pd.DataFrame,r):
    votes=(d['qqq_dd63']<=r['ddq']).astype(int)+(d['spy_dd63']<=r['dds']).astype(int)
    if r['vix_on']: votes += d['vix_elevated'].astype(int)
    if r['nq_on']: votes += d['nq_riskoff'].astype(int)
    pred=votes>=r['k']
    out=[]
    for y in (2013,2017):
        z=d[d.index.year==y]
        weak=z['mc075']<55
        out.append({'year':y,'mc_lt55_days':int(weak.sum()),'confirmed_days':int((weak&pred.reindex(z.index,fill_value=False)).sum()),
                    'rotation_warning_days':int((weak&~pred.reindex(z.index,fill_value=False)).sum())})
    return out


def main():
    d=pd.read_csv(DAILY,parse_dates=['date']).set_index('date').sort_index()
    d=d.rename(columns={'mc_alpha_0.75':'mc075','alpha_0.75':'mc075'})
    if 'mc075' not in d.columns:
        if 'candidate_mc' in d.columns: d['mc075']=d['candidate_mc']
        else: raise RuntimeError(f'mc075 missing; columns={list(d.columns)}')
    d['qqq_dd63']=dd_from_high(d['QQQ'],63)
    old=ROOT/'market_conditions_15y_index_compare_daily.csv'
    if old.exists():
        o=pd.read_csv(old,parse_dates=['date']).set_index('date'); d['SPY']=o['SPY'].reindex(d.index)
    if 'SPY' not in d.columns: raise RuntimeError('SPY missing')
    d['spy_dd63']=dd_from_high(d['SPY'],63)
    d['nq_riskoff']=d['nqsar_proxy'].isin(['Yellow','Red'])
    d['vix_elevated']=d['vix_context'].isin(['ELEVATED','EXTREME'])

    ev=pd.concat([event_rows(d,55),event_rows(d,45)]).sort_index()
    ev=ev[~ev.index.duplicated(keep='last')]
    train=ev[ev.index<=TRAIN_END]; hold=ev[ev.index>=HOLD_START]
    rules=[]
    for k in (1,2,3):
      for ddq in (-.02,-.03,-.04,-.05):
       for dds in (-.02,-.03,-.04):
        for v in (True,False):
         for n in (True,False):
          if (2+int(v)+int(n))<k: continue
          r=score_rule(train,k,ddq,dds,v,n)
          if r['recall']>=.85: rules.append(r)
    rules=sorted(rules,key=lambda x:(x['balanced_accuracy'],x['specificity'],x['precision']),reverse=True)
    best=rules[0]
    result={'definition':{'event':'alpha0.75 MC crosses below 55 or 45','truth_for_validation':'QQQ future 21-session max drawdown <= -5% OR current QQQ drawdown from 63d high <= -5%',
                          'context_votes':'QQQ DD63, SPY DD63, VIX>=20, NQSAR Yellow/Red','train':'2011-2023','holdout':'2024-2026-08-24'},
            'best_rule':best,'train':eval_rule(train,best),'holdout':eval_rule(hold,best),'all':eval_rule(ev,best),
            'major_drawdown_capture':episode_capture(d,best),'benign_bull_2013_2017':benign_year_days(d,best),'top_rules':rules[:10]}
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('train','holdout','all')},ensure_ascii=False,indent=2))

if __name__=='__main__': main()
