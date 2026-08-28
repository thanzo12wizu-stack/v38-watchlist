from __future__ import annotations

import argparse,json,math
from pathlib import Path
import numpy as np
import pandas as pd

import audit_rsi_reset_robust as market_base
import audit_rsi_reset_portfolio as port
import audit_strong_stock_micro_pullback as micro

DISC_END=pd.Timestamp('2021-12-31'); CONF_START=pd.Timestamp('2022-01-03'); END=pd.Timestamp('2026-06-30')


def safe(x):
    if isinstance(x,dict):return {str(k):safe(v) for k,v in x.items()}
    if isinstance(x,(list,tuple)):return [safe(v) for v in x]
    if isinstance(x,np.integer):return int(x)
    if isinstance(x,(np.floating,float)):
        z=float(x);return z if math.isfinite(z) else None
    return x


def prep_shallow(events,up=False,sector_cap=False):
    q=events[(events.cohort=='MATURE')&(events.method=='M10_RSI60_DD075')&(events.mc>=20)&(events.mc<50)&(events.sector_rs63_pct>=70)].copy()
    if up:q=q[q.mc_up1.astype(bool)]
    q['theme']=q.sector if sector_cap else q.symbol
    q['rank_priority']=(100-q.rs189_signal)*100+(100-q.sector_rs63_pct)
    q['source']='shallow'
    return q


def prep_deep(path,sector_cap=False):
    q=pd.read_csv(path,compression='gzip',parse_dates=['signal_date','entry_date','touch_date'])
    q=q[q.method=='C_RSI30_MARKET'].copy(); q['theme']=q.sector if sector_cap else q.symbol
    q['rank_priority']=(100-q.rs189_signal)*100+(100-q.sector_rs63_pct.fillna(0)); q['source']='deep'
    return q


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',default='.');ap.add_argument('--deep-events',required=True);ap.add_argument('--output',required=True);ap.add_argument('--asof',default='2026-08-28');args=ap.parse_args()
    root=Path(args.root);out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    market=market_base.rebuild_market(root,'2016-01-04','2026-06-30',6000,75,3);cl,op,active=market['close'],market['open'],market['active'];ema21=cl.ewm(span=21,adjust=False).mean();cal=cl.index
    events=micro.generate(market,root,args.asof); events['signal_date']=pd.to_datetime(events.signal_date);events['entry_date']=pd.to_datetime(events.entry_date)
    variants={'SHALLOW':prep_shallow(events,False,False),'SHALLOW_UP':prep_shallow(events,True,False),'SHALLOW_UP_SEC2':prep_shallow(events,True,True),'DEEP_RSI30':prep_deep(Path(args.deep_events),False)}
    rows=[]
    for period,lo,hi in [('DISCOVERY',pd.Timestamp('2016-01-04'),DISC_END),('CONFIRM',CONF_START,END)]:
      ix=cal[(cal>=lo)&(cal<=hi)]
      for name,q0 in variants.items():
        q=q0[q0.entry_date.isin(ix)&q0.symbol.isin(cl.columns)].copy()
        for mp in (1,2,4):
          m,_=port.simulate(ix,op,cl,active,ema21,q,0.029,mp,20,'full',False)
          rows.append({'period':period,'variant':name,'max_pos':mp,'input_signals':int(len(q)),**m})
    r=pd.DataFrame(rows);r.to_csv(out/'portfolio_summary.csv',index=False)
    result={'status':'SHALLOW_PULLBACK_PORTFOLIO_AUDIT','slot':0.029,'hold':20,'priority':'higher RS189, then stronger sector; next-open; mark-to-market daily via shared simulator','rows':r.to_dict('records'),'download':market['diag'],
      'limitations':['Current-universe/current-sector classification survivorship bias remains.','No historical market-cap gate or tax model.','2022+ is confirmation, not untouched OOS.']}
    (out/'summary.json').write_text(json.dumps(safe(result),ensure_ascii=False,indent=2),encoding='utf-8');print(r.to_string(index=False),flush=True)

if __name__=='__main__':main()
