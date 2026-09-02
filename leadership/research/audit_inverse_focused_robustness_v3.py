from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

import audit_inverse_etf_regime_scan as base
import audit_inverse_event_engine_v2 as v2

PRODUCTS=['PSQ','QID','SQQQ']
HORIZONS=[1,2,3,4,5,7,10]
CANDIDATES=['TREND_NQSAR','TREND_RATE_SHOCK','EXTENDED_TOP_BREADTH_FADE','FRESH50_NQSAR','BELOW200_NOTDEEP','TREND_MC_BREADTH','FAILED_RALLY']
PERIODS={
 'TRAIN_2016_2021':('2016-01-04','2021-12-31'),
 'HOLDOUT_2022_2026':('2022-01-03','2026-03-20'),
 '2016_2019':('2016-01-04','2019-12-31'),
 '2020_2021':('2020-01-01','2021-12-31'),
 '2022_2023':('2022-01-03','2023-12-29'),
 '2024_2026':('2024-01-02','2026-03-20'),
}

def download_opens(idx,start,end):
    a=str((pd.Timestamp(start)-pd.Timedelta(days=30)).date())
    b=str((pd.Timestamp(end)+pd.Timedelta(days=45)).date())
    raw=yf.download(PRODUCTS,start=a,end=b,auto_adjust=True,actions=False,progress=False,threads=False,group_by='column')
    if raw.empty or not isinstance(raw.columns,pd.MultiIndex): raise RuntimeError('product download failed')
    opn=raw['Open'].copy(); opn.index=base.norm_idx(opn.index)
    return opn.reindex(idx).ffill(limit=2)

def cooldown_events(cond:pd.Series,cooldown:int=10)->pd.Series:
    raw=base.event_mask(cond).fillna(False).to_numpy(bool); out=np.zeros(len(raw),dtype=bool); last=-10**9
    for i,x in enumerate(raw):
        if x and i-last>cooldown:
            out[i]=True; last=i
    return pd.Series(out,index=cond.index)

def event_return(op:pd.Series,i:int,h:int,cost_bp_side:float=5.0):
    if i+1>=len(op) or i+1+h>=len(op): return np.nan
    a=op.iloc[i+1]; b=op.iloc[i+1+h]
    if pd.isna(a) or pd.isna(b) or a<=0:return np.nan
    return float(b/a-1.0-2*cost_bp_side/10000.0)

def event_return_panic_exit(op:pd.Series,panic:pd.Series,i:int,h:int,cost_bp_side:float=5.0):
    entry=i+1
    if entry>=len(op):return np.nan,0
    exit_i=min(entry+h,len(op)-1)
    # panic observed at a close after entry; exit next open, never before entry open
    for j in range(entry, min(entry+h,len(op)-1)):
        if bool(panic.iloc[j]):
            exit_i=min(j+1,len(op)-1); break
    a=op.iloc[entry]; b=op.iloc[exit_i]
    if pd.isna(a) or pd.isna(b) or a<=0:return np.nan,0
    return float(b/a-1.0-2*cost_bp_side/10000.0), int(exit_i-entry)

def stats(x:pd.Series):
    x=pd.to_numeric(x,errors='coerce').dropna()
    if len(x)==0:return {'n':0}
    arr=np.sort(x.to_numpy(float)); k=int(np.floor(.10*len(arr)))
    trim=arr[k:len(arr)-k] if k>0 and len(arr)-2*k>0 else arr
    top1=x.drop(x.idxmax()) if len(x)>1 else pd.Series(dtype=float)
    top2=x.drop(x.nlargest(min(2,len(x))).index) if len(x)>2 else pd.Series(dtype=float)
    return {'n':int(len(x)),'mean':float(x.mean()),'median':float(x.median()),'win':float((x>0).mean()),
            'trim10':float(np.mean(trim)),'worst':float(x.min()),'best':float(x.max()),
            'mean_ex_top1':float(top1.mean()) if len(top1) else np.nan,'mean_ex_top2':float(top2.mean()) if len(top2) else np.nan}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--features',required=True); ap.add_argument('--output',required=True)
    ap.add_argument('--start',default='2016-01-04'); ap.add_argument('--end',default='2026-03-20'); a=ap.parse_args()
    out=Path(a.output); out.mkdir(parents=True,exist_ok=True)
    feat=pd.read_csv(a.features,parse_dates=['date']).set_index('date').sort_index(); feat.index=base.norm_idx(feat.index)
    feat=feat.loc[(feat.index>=pd.Timestamp(a.start))&(feat.index<=pd.Timestamp(a.end))].copy()
    hyp,_=v2.build_hypotheses(feat); hyp={k:hyp[k] for k in CANDIDATES if k in hyp}
    opn=download_opens(feat.index,a.start,a.end)
    panic=(feat.panic_episode>0)|(feat.vix_term_ratio>1.05)|(feat.qqq_rsi14<=30)|(feat.qqq_atr_dist50<=-2.5)
    ledger=[]
    for name,cond in hyp.items():
      events=cooldown_events(cond,10)
      positions=np.flatnonzero(events.to_numpy(bool))
      for prod in PRODUCTS:
        for h in HORIZONS:
          for i in positions:
            r=event_return(opn[prod],i,h,5)
            rp,held=event_return_panic_exit(opn[prod],panic,i,h,5)
            ledger.append({'date':feat.index[i],'year':int(feat.index[i].year),'hypothesis':name,'product':prod,'horizon':h,
                           'ret_net10bp':r,'ret_panic_exit_net10bp':rp,'panic_exit_held_days':held,
                           'panic_at_signal':bool(panic.iloc[i]),'nqsar':feat.nq_color.iloc[i],
                           'qqq_rsi14':feat.qqq_rsi14.iloc[i],'qqq_dist_sma50':feat.qqq_dist_sma50.iloc[i],
                           'breadth50':feat.breadth50.iloc[i],'real10_chg5_z252':feat.real10_chg5_z252.iloc[i]})
    led=pd.DataFrame(ledger); led.to_csv(out/'event_ledger.csv',index=False)
    rows=[]
    for (name,prod,h),g in led.groupby(['hypothesis','product','horizon']):
      row={'hypothesis':name,'product':prod,'horizon':h}
      for mode,col in [('FIXED','ret_net10bp'),('PANIC_EXIT','ret_panic_exit_net10bp')]:
        for period,(aa,bb) in PERIODS.items():
          x=g.loc[(g.date>=aa)&(g.date<=bb),col]; st=stats(x)
          for k,v in st.items(): row[f'{mode}_{period}_{k}']=v
        # leave-one-year-out minimum mean across years with observations
        vals=[]
        for yr in sorted(g.year.unique()):
          x=g.loc[g.year!=yr,col].dropna()
          if len(x): vals.append(float(x.mean()))
        row[f'{mode}_loyo_min_mean']=min(vals) if vals else np.nan
        # Explicit crisis-dependence checks
        for yr in [2020,2022]:
          x=g.loc[g.year!=yr,col].dropna(); row[f'{mode}_ex{yr}_mean']=float(x.mean()) if len(x) else np.nan
      rows.append(row)
    res=pd.DataFrame(rows)
    # Strict primary qualification uses QID only to avoid treating leverage translations as independent discoveries.
    qid=res[res.product.eq('QID')].copy()
    for mode in ['FIXED','PANIC_EXIT']:
      qid[f'{mode}_strict']=(qid[f'{mode}_TRAIN_2016_2021_n']>=10)&(qid[f'{mode}_HOLDOUT_2022_2026_n']>=10)&\
        (qid[f'{mode}_TRAIN_2016_2021_mean']>0)&(qid[f'{mode}_HOLDOUT_2022_2026_mean']>0)&\
        (qid[f'{mode}_TRAIN_2016_2021_median']>0)&(qid[f'{mode}_HOLDOUT_2022_2026_median']>0)&\
        (qid[f'{mode}_TRAIN_2016_2021_mean_ex_top1']>0)&(qid[f'{mode}_HOLDOUT_2022_2026_mean_ex_top1']>0)&\
        (qid[f'{mode}_loyo_min_mean']>0)&(qid[f'{mode}_ex2020_mean']>0)&(qid[f'{mode}_ex2022_mean']>0)
    res.to_csv(out/'focused_robustness.csv',index=False); qid.to_csv(out/'qid_primary.csv',index=False)
    strict_fixed=qid[qid.FIXED_strict].sort_values(['FIXED_HOLDOUT_2022_2026_mean','FIXED_TRAIN_2016_2021_mean'],ascending=False)
    strict_panic=qid[qid.PANIC_EXIT_strict].sort_values(['PANIC_EXIT_HOLDOUT_2022_2026_mean','PANIC_EXIT_TRAIN_2016_2021_mean'],ascending=False)
    summary={'status':'RESEARCH_ONLY_NO_PRODUCTION_CHANGE','cooldown_sessions':10,'roundtrip_cost_bp':10,
             'candidates':list(hyp.keys()),'horizons':HORIZONS,'ledger_rows':len(led),
             'strict_fixed_count':int(qid.FIXED_strict.sum()),'strict_panic_exit_count':int(qid.PANIC_EXIT_strict.sum()),
             'strict_fixed':strict_fixed.to_dict('records'),'strict_panic_exit':strict_panic.to_dict('records'),
             'qualification':'QID: train/hold n>=10; both mean+median positive; remove best event stays positive; leave-one-year-out minimum positive; excluding 2020 and excluding 2022 positive.',
             'note':'V2 holdout has already been inspected; V3 is robustness stress testing, not a fresh untouched holdout.'}
    (out/'summary_v3.json').write_text(json.dumps(base.safe(summary),ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(base.safe(summary),ensure_ascii=False))

if __name__=='__main__':main()
