from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf

PRODUCTS=['PSQ','QID','SQQQ']
PERIODS={
 'TRAIN_2016_2021':('2016-01-04','2021-12-31'),
 'HOLDOUT_2022_2026':('2022-01-03','2026-03-20'),
 '2022':('2022-01-03','2022-12-30'),
 '2023':('2023-01-03','2023-12-29'),
 '2024':('2024-01-02','2024-12-31'),
 '2025_2026':('2025-01-02','2026-03-20'),
}

def safe(x:Any)->Any:
 if isinstance(x,dict):return {str(k):safe(v) for k,v in x.items()}
 if isinstance(x,(list,tuple)):return [safe(v) for v in x]
 if isinstance(x,(np.integer,)):return int(x)
 if isinstance(x,(np.floating,float)):
  v=float(x);return v if np.isfinite(v) else None
 return x

def norm(idx):
 x=pd.DatetimeIndex(pd.to_datetime(idx));
 if x.tz is not None:x=x.tz_convert(None)
 return x.normalize()

def product_opens(idx,start,end):
 warm=str((pd.Timestamp(start)-pd.Timedelta(days=30)).date()); ee=str((pd.Timestamp(end)+pd.Timedelta(days=15)).date())
 raw=yf.download(PRODUCTS,start=warm,end=ee,auto_adjust=True,actions=False,progress=False,threads=False)
 if raw.empty:raise RuntimeError('inverse ETF download empty')
 if isinstance(raw.columns,pd.MultiIndex):
  op=raw['Open'].copy()
 else:
  op=raw[['Open']].copy();op.columns=[PRODUCTS[0]]
 op.index=norm(op.index);return op.reindex(idx).ffill(limit=1)

def perf(r):
 x=pd.to_numeric(r,errors='coerce').fillna(0.0); n=len(x)
 nav=(1+x).cumprod(); yrs=n/252; dd=nav/nav.cummax()-1; sd=x.std()
 return {'n':n,'cagr':float(nav.iloc[-1]**(1/yrs)-1) if yrs>0 and nav.iloc[-1]>0 else None,'maxdd':float(dd.min()),'sharpe':float(x.mean()/sd*np.sqrt(252)) if sd>0 else None,'final_nav':float(nav.iloc[-1]),'worst_day':float(x.min()),'best_day':float(x.max())}

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--base',required=True);ap.add_argument('--output',required=True);ap.add_argument('--start',default='2016-01-04');ap.add_argument('--end',default='2026-03-20');a=ap.parse_args()
 out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
 f=pd.read_csv(a.base,compression='infer',parse_dates=['date']).set_index('date').sort_index();f.index=norm(f.index);f=f.loc[(f.index>=a.start)&(f.index<=a.end)]
 opens=product_opens(f.index,a.start,a.end)
 bear200=pd.to_numeric(f.qqq_dist_sma200,errors='coerce')<0
 breadth50=pd.to_numeric(f.breadth50,errors='coerce')<50
 slope50=pd.to_numeric(f.sma50_slope10,errors='coerce')<0
 nred=f.nq_color.eq('Red')
 vback=pd.to_numeric(f.vix_term_ratio,errors='coerce')>1
 realshock=pd.to_numeric(f.real10_chg5_z252,errors='coerce')>=.75
 panic=f.panic_episode.eq(1) | ((pd.to_numeric(f.qqq_rsi14,errors='coerce')<=28)&(pd.to_numeric(f.vix,errors='coerce')>=28)&(pd.to_numeric(f.qqq_dd20,errors='coerce')<=-.08))
 rules={
  'NQSAR_RED':nred,
  'QQQ_BELOW200':bear200,
  'QQQ_BELOW200_BREADTH_LT50':bear200&breadth50,
  'QQQ_BELOW200_BREADTH_LT50_NQSAR_RED':bear200&breadth50&nred,
  'QQQ_BELOW200_BREADTH_LT50_50SLOPE_DOWN':bear200&breadth50&slope50,
  'QQQ_BELOW200_BREADTH_LT50_VIX_BACKWARD':bear200&breadth50&vback,
  'QQQ_BELOW200_BREADTH_LT50_REAL10_SHOCK':bear200&breadth50&realshock,
 }
 rows=[]
 for rn,basecond in rules.items():
  for guard in [False,True]:
   cond=basecond & (~panic if guard else True)
   for p in PRODUCTS:
    oo=opens[p].shift(-1)/opens[p]-1
    for w in [.15,.30]:
     pos=cond.astype(float)*w;eff=pos.shift(1).fillna(0);turn=pos.diff().abs().shift(1).fillna(0)
     for cost in [0,5,10]:
      ret=eff*oo-turn*(cost/10000)
      for period,(s,e) in PERIODS.items():
       pm=(ret.index>=s)&(ret.index<=e);rr=ret.loc[pm];pp=eff.loc[pm]
       rec={'rule':rn,'guard':'PANIC' if guard else 'NONE','product':p,'weight':w,'cost_bp_side':cost,'period':period,'holding_days':int((pp>0).sum()),'entries':int(((pp>0)&~(pp.shift(1)>0)).sum()),**perf(rr)};rows.append(rec)
 df=pd.DataFrame(rows);df.to_csv(out/'structural_rule_performance.csv',index=False)
 tr=df[df.period.eq('TRAIN_2016_2021')].set_index(['rule','guard','product','weight','cost_bp_side'])
 ho=df[df.period.eq('HOLDOUT_2022_2026')].set_index(['rule','guard','product','weight','cost_bp_side'])
 comp=tr[['cagr','maxdd','sharpe','holding_days','entries']].add_prefix('train_').join(ho[['cagr','maxdd','sharpe','holding_days','entries']].add_prefix('hold_')).reset_index();comp['min_cagr']=comp[['train_cagr','hold_cagr']].min(axis=1);comp['stable_positive']=(comp.train_cagr>0)&(comp.hold_cagr>0);comp.to_csv(out/'structural_rule_comparison.csv',index=False)
 best=comp.sort_values(['min_cagr','hold_sharpe'],ascending=False).head(40)
 summary={'status':'RESEARCH_ONLY_NO_PRODUCTION_CHANGE','mechanics':{'signal':'close; position from next session open','exit':'position is removed next open when the same structural state no longer holds','guard':'optional existing panic episode or deep RSI/VIX/DD oversold guard','products':'actual PSQ/QID/SQQQ open-to-open returns','costs':'0/5/10 bp per side'},'stable_count':int(comp.stable_positive.sum()),'best':best.to_dict('records')}
 (out/'summary.json').write_text(json.dumps(safe(summary),ensure_ascii=False,indent=2))
 print('===STRUCTURAL_INVERSE_SUMMARY===');print(json.dumps(safe(summary),ensure_ascii=False,separators=(',',':')));print('===END===')
if __name__=='__main__':main()
