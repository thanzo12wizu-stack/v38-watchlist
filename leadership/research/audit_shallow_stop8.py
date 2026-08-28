from __future__ import annotations

import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd

import audit_systematic_entry_exit as base

COST = base.COST


def sim(entry_date, sym, st, stop8):
    cl, op, hi = st['cl'], st['op'], st['hi']
    if entry_date not in cl.index or sym not in cl.columns:
        return None
    ei = cl.index.get_loc(entry_date)
    ep = base.price_at(op, entry_date, sym)
    if not np.isfinite(ep) or ep <= 0:
        return None
    buy = ep * (1 + COST)
    xi = min(ei + 20, len(cl.index) - 1)
    exit_reason = 'TIME20'
    if stop8:
        for i in range(ei + 1, xi):
            c = base.price_at(cl, cl.index[i], sym)
            if np.isfinite(c) and c / ep - 1 <= -0.08 and i + 1 < len(cl.index):
                xi = i + 1
                exit_reason = 'STOP8'
                break
    px = base.price_at(op, cl.index[xi], sym)
    if not np.isfinite(px):
        px = base.price_at(cl, cl.index[xi], sym)
    if not np.isfinite(px):
        return None
    h_end = min(ei + 20, len(cl.index)-1)
    hs = pd.to_numeric(hi[sym].iloc[ei:h_end+1], errors='coerce').dropna()
    mfe20 = float(hs.max()/ep-1) if len(hs) else np.nan
    return {'ret': px*(1-COST)/buy-1, 'hold_days': xi-ei, 'exit_reason': exit_reason, 'mfe40': mfe20, 'exit_date': cl.index[xi]}


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--root',default='.')
    ap.add_argument('--input',required=True)
    ap.add_argument('--output',required=True)
    ap.add_argument('--start',default='2016-01-04')
    ap.add_argument('--end',default='2026-06-30')
    ap.add_argument('--asof',default='2026-08-28')
    args=ap.parse_args()
    out=Path(args.output); out.mkdir(parents=True,exist_ok=True)
    st=base.build_market_states(Path(args.root),args.start,args.end,args.asof)
    t=pd.read_csv(args.input,compression='gzip',parse_dates=['signal_date','entry_date'])
    t=t[(t.cohort=='MATURE')&(t.liquid==True)&(pd.to_numeric(t.sector_signal,errors='coerce')>=70)&(t.method=='M5_RSI65_DD050')&(t.mc_band.astype(str).isin(['50_65','65_80']))&(pd.to_numeric(t.delay,errors='coerce')<=5)].copy()
    rows=[]
    for r in t.itertuples(index=False):
        for name,flag in [('FIX20',False),('FIX20_STOP8',True)]:
            z=sim(pd.Timestamp(r.entry_date),r.symbol,st,flag)
            if z:
                rows.append({'episode_id':r.episode_id,'symbol':r.symbol,'sector':r.sector,'period':r.period,'mc_band':str(r.mc_band),'signal_date':r.signal_date,'entry_date':r.entry_date,'exit':name,**z})
    rows=pd.DataFrame(rows)
    rows.to_csv(out/'rows.csv.gz',index=False,compression='gzip')
    sums=[]; seed=9000
    for period in ['DISCOVERY','CONFIRM']:
        for band in ['50_65','65_80']:
            q=rows[(rows.period==period)&(rows.mc_band==band)]
            for ex,g in q.groupby('exit',observed=True):
                s=base.summarize(g,st['cl'].index,seed); seed+=1
                s['stop_exit_rate']=float((g.exit_reason=='STOP8').mean()) if ex=='FIX20_STOP8' else 0.0
                if ex=='FIX20_STOP8':
                    stopped=g[g.exit_reason=='STOP8']
                    # Match by episode to no-stop outcome to measure false stops.
                    b=q[q.exit=='FIX20'][['episode_id','ret']].rename(columns={'ret':'raw_ret'})
                    ss=stopped.merge(b,on='episode_id',how='left')
                    s['stopped_eventual_winner_rate']=float((ss.raw_ret>0).mean()) if len(ss) else None
                sums.append({'period':period,'mc_band':band,'exit':ex,**s})
    sums=pd.DataFrame(sums); sums.to_csv(out/'summary.csv',index=False)
    meta={'status':'SHALLOW_STOP8_AUDIT','definition':'prior close <= -8% vs original entry -> next open; otherwise fixed 20 sessions','rows':int(len(rows)),'research_only':True}
    (out/'summary.json').write_text(json.dumps(base.safe(meta),ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(meta,ensure_ascii=False,indent=2)); print(sums.to_string(index=False))

if __name__=='__main__': main()
