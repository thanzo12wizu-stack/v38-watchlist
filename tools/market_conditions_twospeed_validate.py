#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
DAILY=ROOT/'market_conditions_alpha_context_15y_daily.csv'
OLD=ROOT/'market_conditions_15y_index_compare_daily.csv'
EPJSON=ROOT/'market_conditions_15y_index_compare.json'
OUT=ROOT/'market_conditions_twospeed_validate.json'
TRAIN_END=pd.Timestamp('2023-12-31')
HOLD_START=pd.Timestamp('2024-01-01')


def dd_from_high(s,w=63): return s/s.rolling(w,min_periods=20).max()-1

def load():
    d=pd.read_csv(DAILY,parse_dates=['date']).set_index('date').sort_index()
    d=d.rename(columns={'mc_alpha_0.0':'core','mc_alpha_0.75':'fast'})
    o=pd.read_csv(OLD,parse_dates=['date']).set_index('date')
    d['SPY']=o['SPY'].reindex(d.index)
    d['qqq_dd63']=dd_from_high(d['QQQ']); d['spy_dd63']=dd_from_high(d['SPY'])
    d['nq_off']=d['nqsar_proxy'].isin(['Yellow','Red']); d['vix_elev']=d['vix_context'].isin(['ELEVATED','EXTREME'])
    d['gap']=d['core']-d['fast']
    eps=json.loads(EPJSON.read_text(encoding='utf-8'))['episodes']
    d['major_phase']=False
    for e in eps:
        p=pd.Timestamp(e['peak']); t=pd.Timestamp(e['trough']); d.loc[(d.index>=p)&(d.index<=t),'major_phase']=True
    return d,eps


def pred_for(d,base_th,k,qth,sth,use_nq,use_vix):
    votes=(d['qqq_dd63']<=qth).astype(int)+(d['spy_dd63']<=sth).astype(int)
    if use_nq: votes += d['nq_off'].astype(int)
    if use_vix: votes += d['vix_elev'].astype(int)
    return (d['core']<base_th)|(votes>=k)


def metrics(z,p):
    y=z['major_phase'].astype(bool); tp=int((p&y).sum()); fn=int((~p&y).sum()); fp=int((p&~y).sum()); tn=int((~p&~y).sum())
    rec=tp/(tp+fn) if tp+fn else np.nan; spec=tn/(tn+fp) if tn+fp else np.nan; prec=tp/(tp+fp) if tp+fp else np.nan
    return {'n':int(len(z)),'true_days':int(y.sum()),'tp':tp,'fn':fn,'fp':fp,'tn':tn,'recall':float(rec),'specificity':float(spec),'precision':float(prec),'balanced':float(np.nanmean([rec,spec]))}


def episode_capture(d,eps,pred):
    rows=[]
    for e in eps:
        p=pd.Timestamp(e['peak']); t=pd.Timestamp(e['trough']); z=pred.loc[(pred.index>=p)&(pred.index<=t)]; h=z[z]
        first=h.index[0] if len(h) else None
        rows.append({'peak':e['peak'],'trough':e['trough'],'dd_pct':e['QQQ_dd_pct'],'captured':first is not None,
                     'first':str(first.date()) if first is not None else None,
                     'sessions':int(d.loc[p:first].shape[0]-1) if first is not None else None})
    vals=[x['sessions'] for x in rows if x['sessions'] is not None]
    return {'episodes':len(rows),'captured':sum(x['captured'] for x in rows),'mean_sessions':float(np.mean(vals)) if vals else None,'median_sessions':float(np.median(vals)) if vals else None,'rows':rows}


def benign(d,pred):
    out=[]
    for y in (2013,2017):
        z=d[d.index.year==y]; weak=z['fast']<55; p=pred.reindex(z.index,fill_value=False)
        out.append({'year':y,'fast_lt55_days':int(weak.sum()),'confirmed_days':int((weak&p).sum()),'rotation_days':int((weak&~p).sum())})
    return out


def current_context(d,best):
    r=d.iloc[-1]; pred=pred_for(d,best['base_th'],best['k'],best['qth'],best['sth'],best['use_nq'],best['use_vix']).iloc[-1]
    # high-core / high-gap + NQ-off is a deterioration warning, not a Bear relabel.
    warn=bool(r['core']>=65 and r['gap']>=4 and r['nq_off'])
    if r['fast']<55:
        state='CONFIRMED DETERIORATION' if pred else 'ROTATION / TACTICAL WEAKNESS'
    elif warn: state='BULL / DETERIORATING / TACTICAL RISK-OFF'
    else: state='CORE STATE'
    return {'date':str(d.index[-1].date()),'core':float(r['core']),'fast':float(r['fast']),'gap':float(r['gap']),'nqsar':str(r['nqsar_proxy']),'vix':str(r['vix_context']),'state':state}


def main():
    d,eps=load(); weak=d[d['fast']<55].copy(); train=weak[weak.index<=TRAIN_END]; hold=weak[weak.index>=HOLD_START]
    candidates=[]
    for b in (55,60,65,70):
      for k in (1,2,3):
       for q in (-.03,-.04,-.05):
        for s in (-.03,-.04,-.05):
         for nq in (True,False):
          for vx in (True,False):
           nsignals=2+int(nq)+int(vx)
           if k>nsignals: continue
           p=pred_for(train,b,k,q,s,nq,vx)
           m=metrics(train,p)
           if m['recall']>=.90:
               candidates.append({'base_th':b,'k':k,'qth':q,'sth':s,'use_nq':nq,'use_vix':vx,**m})
    candidates=sorted(candidates,key=lambda r:(r['balanced'],r['specificity'],r['precision']),reverse=True)
    best=candidates[0]
    allpred=pred_for(d,best['base_th'],best['k'],best['qth'],best['sth'],best['use_nq'],best['use_vix'])
    res={'definition':{'core':'alpha0 / original 15-55-20-10','fast':'alpha0.75 deterioration-sensitive score','confirmed':'when fast<55, confirm using slow core + market context','truth':'day lies between peak and trough of one of the 21 objective QQQ drawdowns >=8%','train':'2011-2023','holdout':'2024-2026-08-24'},
         'best_rule':best,
         'train':metrics(train,pred_for(train,best['base_th'],best['k'],best['qth'],best['sth'],best['use_nq'],best['use_vix'])),
         'holdout':metrics(hold,pred_for(hold,best['base_th'],best['k'],best['qth'],best['sth'],best['use_nq'],best['use_vix'])),
         'all_weak_days':metrics(weak,pred_for(weak,best['base_th'],best['k'],best['qth'],best['sth'],best['use_nq'],best['use_vix'])),
         'episode_capture':episode_capture(d,eps,allpred & (d['fast']<65)),
         'benign_2013_2017':benign(d,allpred),
         'current':current_context(d,best),
         'top_rules':candidates[:12]}
    OUT.write_text(json.dumps(res,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(res,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
