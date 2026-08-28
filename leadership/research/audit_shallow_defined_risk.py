from __future__ import annotations

import argparse, json, math
from pathlib import Path
import numpy as np
import pandas as pd

import audit_rsi_reset_robust as market_base

COST = 5.0 / 10000.0
METHODS = ('M5_RSI65_DD050','M10_RSI65_DD075')


def safe(x):
    if isinstance(x, dict): return {str(k): safe(v) for k,v in x.items()}
    if isinstance(x, (list,tuple)): return [safe(v) for v in x]
    if isinstance(x, np.integer): return int(x)
    if isinstance(x, (np.floating,float)):
        z=float(x); return z if math.isfinite(z) else None
    return x


def pf(x):
    z=pd.to_numeric(x,errors='coerce').dropna()
    if z.empty: return None
    gp=float(z[z>0].sum()); gl=float(-z[z<0].sum())
    return None if gl<=0 else gp/gl


def stop_outcome(r, cal, op, hi, lo, cl, atr):
    s=r.symbol
    try:
        ti=cal.get_loc(pd.Timestamp(r.touch_date)); ei=cal.get_loc(pd.Timestamp(r.entry_date))
    except KeyError:
        return None
    if s not in cl.columns or ei>=len(cal): return None
    entry=op.at[cal[ei],s]
    av=atr.at[cal[ti],s] if s in atr.columns else np.nan
    tl=lo.at[cal[ti],s] if s in lo.columns else np.nan
    if pd.isna(entry) or entry<=0 or pd.isna(av) or av<=0 or pd.isna(tl): return None
    stop=float(tl-0.25*av)
    if stop<=0: return None
    risk=float((entry-stop)/entry)
    gap_below=bool(entry<=stop)
    hit=False; exit_px=np.nan; exit_date=None
    end=min(ei+19,len(cal)-1)
    if not gap_below:
        for j in range(ei,end+1):
            o=op.at[cal[j],s]; l=lo.at[cal[j],s]
            if pd.isna(o) or pd.isna(l): continue
            if o<=stop:
                hit=True; exit_px=float(o); exit_date=cal[j]; break
            if l<=stop:
                hit=True; exit_px=float(stop); exit_date=cal[j]; break
    if hit:
        stopped=float(exit_px/entry-1-2*COST)
    else:
        c=cl.at[cal[end],s]
        stopped=float(c/entry-1-2*COST) if pd.notna(c) else np.nan
    return {'planned_stop':stop,'initial_risk':risk,'gap_below_stop':gap_below,'stop_hit':hit,
            'stop_exit_date':exit_date,'stop_ret20':stopped}


def summarize(g):
    if g.empty: return {'n':0}
    r=pd.to_numeric(g.stop_ret20,errors='coerce').dropna(); raw=pd.to_numeric(g.ret20,errors='coerce').dropna()
    hit=g.stop_hit.fillna(False)
    return {'n':int(len(g)),'signal_dates':int(g.signal_date.nunique()),'symbols':int(g.symbol.nunique()),
            'mean_initial_risk':float(g.initial_risk.mean()),'median_initial_risk':float(g.initial_risk.median()),
            'stop_hit_rate':float(hit.mean()),'stop_mean20':float(r.mean()),'stop_median20':float(r.median()),
            'stop_win20':float((r>0).mean()),'stop_pf20':pf(r),'stop_p10':float(r.quantile(.10)),
            'raw_mean20':float(raw.mean()),'raw_pf20':pf(raw),
            'eventual_winner_among_stopped':float((g.loc[hit,'ret20']>0).mean()) if hit.any() else None,
            'mean_raw20_if_stopped':float(g.loc[hit,'ret20'].mean()) if hit.any() else None}


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--root',default='.'); ap.add_argument('--input',required=True); ap.add_argument('--output',required=True)
    args=ap.parse_args(); root=Path(args.root); out=Path(args.output); out.mkdir(parents=True,exist_ok=True)
    tr=pd.read_csv(args.input,compression='gzip',parse_dates=['touch_date','signal_date','entry_date','episode_start'])
    tr=tr[(tr.cohort=='MATURE')&tr.liquid&tr.method.isin(METHODS)&(tr.mc_signal>=50)].copy()
    market=market_base.rebuild_market(root,'2016-01-04','2026-06-30',6000,75,3)
    cl,op,hi,lo=market['close'],market['open'],market['high'],market['low']; cal=cl.index
    prev=cl.shift(1)
    true_range=(hi-lo).combine((hi-prev).abs(),np.maximum).combine((lo-prev).abs(),np.maximum)
    atr=true_range.rolling(14,min_periods=14).mean()
    rows=[]
    for k,r in enumerate(tr.itertuples(index=False),start=1):
        z=stop_outcome(r,cal,op,hi,lo,cl,atr)
        if z is None: continue
        rec=r._asdict(); rec.update(z); rows.append(rec)
        if k%1000==0: print(f'STOP_SCAN {k}/{len(tr)}',flush=True)
    z=pd.DataFrame(rows)
    z=z[~z.gap_below_stop].copy()
    z['mc_band']=pd.cut(z.mc_signal,[50,65,80,np.inf],right=False,labels=['50_65','65_80','GE80'])
    z.to_csv(out/'stop_rows.csv.gz',index=False,compression='gzip')
    result=[]
    for period in ('DISCOVERY','CONFIRM'):
      for band in ('50_65','65_80','GE50'):
       for method in METHODS:
        b=z[(z.period==period)&(z.method==method)]
        if band!='GE50': b=b[b.mc_band.astype(str)==band]
        for secmin in (70,80):
         q=b[b.sector_signal>=secmin]
         for delay_cap in ('ALL',5):
          qq=q if delay_cap=='ALL' else q[q.delay<=delay_cap]
          for risk_cap in ('ALL',0.08,0.05):
           g=qq if risk_cap=='ALL' else qq[qq.initial_risk<=risk_cap]
           if len(g)<15: continue
           result.append({'period':period,'mc_band':band,'method':method,'sector_min':secmin,
                          'delay_cap':delay_cap,'risk_cap':risk_cap,**summarize(g)})
    sm=pd.DataFrame(result); sm.to_csv(out/'stop_summary.csv',index=False)
    meta={'status':'SHALLOW_DEFINED_RISK_AUDIT','research_only':True,
          'stop':'touch-day low - 0.25 ATR14, fixed for 20 sessions; gap below planned stop invalidates entry; intraday stop fill at stop, gap fill at open',
          'methods':list(METHODS),'input_rows':int(len(tr)),'valid_rows':int(len(z)),'download':market.get('diag',{}),
          'limitations':['Daily OHLC cannot model intraday ordering beyond open/low.','Current-universe/current-sector survivorship bias remains.','2022+ is confirmation, not pristine OOS.']}
    (out/'summary.json').write_text(json.dumps(safe(meta),ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(safe(meta),ensure_ascii=False,indent=2),flush=True)
    print(sm.to_string(index=False),flush=True)

if __name__=='__main__': main()
