from __future__ import annotations

import argparse, json, math
from pathlib import Path
import numpy as np
import pandas as pd

import validate_post_ignition_leaders as post

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
    return {'n':int(len(r)),'signal_dates':int(g.loc[r.index,'signal_date'].nunique()),'symbols':int(g.loc[r.index,'symbol'].nunique()),
            'mean20':float(r.mean()),'median20':float(r.median()),'win20':float((r>0).mean()),'pf20':pf(r),
            'mae20':float(pd.to_numeric(g.loc[r.index,'mae_20'],errors='coerce').mean()),'p10_20':float(r.quantile(.10)),
            'top5_removed_mean20':float(r[r<=r.quantile(.95)].mean()),'top5_removed_pf20':pf(r[r<=r.quantile(.95)])}


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--input',required=True); ap.add_argument('--output',required=True); args=ap.parse_args()
    out=Path(args.output); out.mkdir(parents=True,exist_ok=True)
    z=pd.read_csv(args.input,compression='gzip',parse_dates=['signal_date','entry_date','touch_date'])
    z=z[(z.cohort=='MATURE')&(z.method=='M10_RSI60_DD075')&(z.mc>=20)&(z.mc<50)&z.mc_up1.astype(bool)&(z.sector_rs63_pct>=70)&z.signal_date.between('2016-01-04',END)].copy()
    syms=sorted(z.symbol.astype(str).unique())
    ohlcv,diag=post.rtv2.download_ohlcvo(syms,'2015-11-01','2026-08-28',75)
    cl=ohlcv['close']; hi=ohlcv['high']; lo=ohlcv['low']; vol=ohlcv['volume']
    avgvol20=vol.rolling(20,min_periods=15).mean(); adr20=((hi-lo)/cl.replace(0,np.nan)*100).rolling(20,min_periods=15).mean(); dvol20=(cl*vol).rolling(20,min_periods=15).mean()
    price=[]; av=[]; adr=[]; dv=[]
    for r in z.itertuples(index=False):
        d=pd.Timestamp(r.signal_date); s=str(r.symbol)
        try:
            price.append(float(cl.at[d,s])); av.append(float(avgvol20.at[d,s])); adr.append(float(adr20.at[d,s])); dv.append(float(dvol20.at[d,s]))
        except Exception:
            price.append(np.nan); av.append(np.nan); adr.append(np.nan); dv.append(np.nan)
    z['price_signal']=price; z['avgvol20']=av; z['adr20_pct']=adr; z['dvol20']=dv
    if z.price_signal.notna().mean()<.98: raise RuntimeError('price coverage below 98%')
    masks={
      'BASE':pd.Series(True,index=z.index),
      'P5_VOL1M_ADR3_15':(z.price_signal>=5)&(z.avgvol20>=1_000_000)&z.adr20_pct.between(3,15),
      'P5_VOL500K_ADR3_15':(z.price_signal>=5)&(z.avgvol20>=500_000)&z.adr20_pct.between(3,15),
      'P5_DVOL20M_ADR3_15':(z.price_signal>=5)&(z.dvol20>=20_000_000)&z.adr20_pct.between(3,15),
      'P5_VOL1M_ADR2_20':(z.price_signal>=5)&(z.avgvol20>=1_000_000)&z.adr20_pct.between(2,20),
    }
    rows=[]; years=[]
    for rule,m in masks.items():
      for period,pm in [('DISCOVERY',z.signal_date<=DISC_END),('CONFIRM',(z.signal_date>=CONF_START)&(z.signal_date<=END)),('BAD_2022_23',z.signal_date.between('2022-01-01','2023-12-31'))]:
        rows.append({'rule':rule,'period':period,'accept_rate':float((m&pm).sum()/max(1,pm.sum())),**stats(z[m&pm])})
      for y,g in z[m].groupby(z.loc[m,'signal_date'].dt.year): years.append({'rule':rule,'year':int(y),**stats(g)})
    pd.DataFrame(rows).to_csv(out/'liquidity_summary.csv',index=False); pd.DataFrame(years).to_csv(out/'year_summary.csv',index=False)
    z.to_csv(out/'selected_trades_liquidity.csv.gz',index=False,compression='gzip')
    result={'status':'SHALLOW_PULLBACK_LIQUIDITY_AUDIT','base':'MATURE M10_RSI60_DD075 + MC20-50 up1 + sector>=70',
            'filters':pd.DataFrame(rows).to_dict('records'),'download':diag,
            'limitations':['No historical market-cap series; market-cap filter is not claimed.','Current-universe/current-sector classification survivorship bias remains.','2022+ is confirmation, not untouched OOS.']}
    (out/'summary.json').write_text(json.dumps(safe(result),ensure_ascii=False,indent=2),encoding='utf-8')
    print(pd.DataFrame(rows).to_string(index=False),flush=True)

if __name__=='__main__':main()
