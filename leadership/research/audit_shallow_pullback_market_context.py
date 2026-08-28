from __future__ import annotations

import argparse, json, math
from pathlib import Path
import numpy as np
import pandas as pd

import audit_rsi30_mc_nqsar as state
import audit_rsi30_vix_sequence as vx

DISC_END=pd.Timestamp('2021-12-31'); CONF_START=pd.Timestamp('2022-01-03'); END=pd.Timestamp('2026-06-30')


def safe(x):
    if isinstance(x,dict): return {str(k):safe(v) for k,v in x.items()}
    if isinstance(x,(list,tuple)): return [safe(v) for v in x]
    if isinstance(x,np.integer): return int(x)
    if isinstance(x,(np.floating,float)):
        z=float(x); return z if math.isfinite(z) else None
    return x


def pf(r):
    r=pd.to_numeric(r,errors='coerce').dropna(); gp=float(r[r>0].sum()); gl=float(-r[r<0].sum())
    return None if gl<=0 else gp/gl


def stats(g):
    r=pd.to_numeric(g.entry_20,errors='coerce').dropna()
    if r.empty:return {'n':0}
    mae=pd.to_numeric(g.loc[r.index,'mae_20'],errors='coerce')
    return {'n':int(len(r)),'signal_dates':int(g.loc[r.index,'signal_date'].nunique()),'symbols':int(g.loc[r.index,'symbol'].nunique()),
            'mean20':float(r.mean()),'median20':float(r.median()),'win20':float((r>0).mean()),'pf20':pf(r),
            'mae20':float(mae.mean()),'p10_20':float(r.quantile(.10)),'p90_20':float(r.quantile(.90))}


def tail5(g):
    r=pd.to_numeric(g.entry_20,errors='coerce').dropna().sort_values()
    if r.empty:return {'n':0}
    rr=r[r<=r.quantile(.95)]
    return {'n':int(len(rr)),'mean20':float(rr.mean()),'median20':float(rr.median()),'pf20':pf(rr)}


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--input',required=True); ap.add_argument('--output',required=True); ap.add_argument('--asof',default='2026-08-28'); args=ap.parse_args()
    out=Path(args.output); out.mkdir(parents=True,exist_ok=True)
    z=pd.read_csv(args.input,compression='gzip',parse_dates=['signal_date','entry_date','touch_date'])
    z=z[(z.cohort=='MATURE')&(z.method=='M10_RSI60_DD075')&(z.mc>=20)&(z.mc<50)&z.mc_up1.astype(bool)&(z.sector_rs63_pct>=70)].copy()
    z=z[z.signal_date.between(pd.Timestamp('2016-01-04'),END)].copy()

    nq=state.build_nqsar('2010-01-01',(pd.Timestamp(args.asof)+pd.Timedelta(days=1)).strftime('%Y-%m-%d'))
    nq2=nq.reset_index(); nq2.columns=['signal_date']+list(nq2.columns[1:])
    z=z.merge(nq2[['signal_date','nq_color','nq_bull','nq_not_red','nq_upgrade','nq_red_exit']],on='signal_date',how='left',validate='many_to_one')

    v= vx.add_expanding_sigma(vx.load_vix('1990-01-02',(pd.Timestamp(args.asof)+pd.Timedelta(days=1)).strftime('%Y-%m-%d')))
    v,events=vx.build_sequence(v)
    valid=vx.validate_recent(events)
    if not valid['all_match']: raise RuntimeError('VIX sequence validation failed')
    vm=v.reset_index().rename(columns={'Date':'signal_date','index':'signal_date','Close':'vix_close'})[['signal_date','vix_close','phase']]
    z=z.merge(vm,on='signal_date',how='left',validate='many_to_one')
    if z.nq_color.isna().mean()>0.02 or z.vix_close.isna().mean()>0.02: raise RuntimeError('market context coverage below 98%')

    masks={
      'BASE':pd.Series(True,index=z.index),
      'NQ_NOT_RED':z.nq_not_red.fillna(False),
      'NQ_BULL':z.nq_bull.fillna(False),
      'VIX_NOT_EVENT_ROLLOVER':~z.phase.isin(['EVENT','ROLLOVER']),
      'NQ_NOT_RED_AND_VIX_OK':z.nq_not_red.fillna(False)&~z.phase.isin(['EVENT','ROLLOVER']),
      'NQ_BULL_AND_VIX_OK':z.nq_bull.fillna(False)&~z.phase.isin(['EVENT','ROLLOVER']),
    }
    rows=[]; years=[]
    for rule,m in masks.items():
      for period,pm in [('DISCOVERY',z.signal_date<=DISC_END),('CONFIRM',(z.signal_date>=CONF_START)&(z.signal_date<=END)),('BAD_2022_23',z.signal_date.between('2022-01-01','2023-12-31'))]:
        g=z[m&pm]; rows.append({'rule':rule,'period':period,**stats(g),**{f'top5_removed_{k}':v for k,v in tail5(g).items()}})
      for y,g0 in z[m].groupby(z.loc[m,'signal_date'].dt.year):
        years.append({'rule':rule,'year':int(y),**stats(g0)})
    pd.DataFrame(rows).to_csv(out/'policy_summary.csv',index=False); pd.DataFrame(years).to_csv(out/'year_summary.csv',index=False)
    z.to_csv(out/'selected_trades_with_context.csv.gz',index=False,compression='gzip')
    result={'status':'SHALLOW_PULLBACK_MARKET_CONTEXT_AUDIT','base':'MATURE M10_RSI60_DD075 + MC20-50 up1 + sector>=70',
            'policies':pd.DataFrame(rows).to_dict('records'),'vix_validation':valid,
            'limitations':['NQSAR is reconstructed from Yahoo NQ=F history, not pristine historical production snapshots.','2022+ is confirmation, not untouched OOS.','Current-universe/current-sector classification survivorship bias remains.']}
    (out/'summary.json').write_text(json.dumps(safe(result),ensure_ascii=False,indent=2),encoding='utf-8')
    print(pd.DataFrame(rows).to_string(index=False),flush=True)

if __name__=='__main__':main()
