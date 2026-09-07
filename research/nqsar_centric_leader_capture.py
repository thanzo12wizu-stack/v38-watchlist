from __future__ import annotations

import argparse, json, math
from pathlib import Path
import numpy as np
import pandas as pd

from research import nqsar_centric_broad_scan as scan
from research import audit_stock_nqsar_theme30_pit as audit

VARIANTS=['CURRENT_WEEK_PRIORITY','WEEK_BULL_STRUCT_RS63','WEEK_BLUE_FIRST_RS63','WEEK_BULL_DAILY_NOT_RED_RS63','EARLY1_WEEK_BULL','PIONEER_WEEK_BULL']


def safe(x):
    if isinstance(x,dict): return {str(k):safe(v) for k,v in x.items()}
    if isinstance(x,(list,tuple)): return [safe(v) for v in x]
    if isinstance(x,np.integer): return int(x)
    if isinstance(x,(np.floating,float)):
        z=float(x); return z if math.isfinite(z) else None
    return x


def select_top12(d,m,v):
    old=scan.DDV_ENTRY
    try:
        scan.DDV_ENTRY=0.0
        raw=scan.score_mask(d,m,v)
    finally:
        scan.DDV_ENTRY=old
    out=[]
    for s in raw:
        try: x=float(m['ddv'].at[d,s])
        except Exception: continue
        if np.isfinite(x) and x>=20_000_000: out.append(s)
    return out


def build_events(m,idx):
    c=m['close']; prior_low=c.shift(1).rolling(126,min_periods=60).min()
    events=[]
    for s in c.columns:
        z=c[s]
        # Require a full 126-session forward window; labels are evaluation-only.
        for i,d in enumerate(idx):
            gi=c.index.get_loc(d)
            if not isinstance(gi,(int,np.integer)) or gi+126>=len(c): continue
            if not bool(m['pool'].at[d,s]): continue
            fut=z.iloc[gi+1:gi+127].dropna()
            p0=z.iloc[gi]
            if pd.isna(p0) or p0<=0 or len(fut)<100: continue
            peak=float(fut.max()/p0-1)
            if peak<1.0: continue
            # Event start = first day of a contiguous future-2x label run. Avoid daily duplication.
            if i>0:
                pd0=idx[i-1]; gprev=c.index.get_loc(pd0)
                if isinstance(gprev,(int,np.integer)) and gprev+126<len(c) and bool(m['pool'].at[pd0,s]):
                    pf=z.iloc[gprev+1:gprev+127].dropna(); pp=z.iloc[gprev]
                    if pd.notna(pp) and pp>0 and len(pf)>=100 and float(pf.max()/pp-1)>=1.0: continue
            peak_date=pd.Timestamp(fut.idxmax())
            pl=prior_low.at[d,s]
            events.append({'symbol':s,'start_date':pd.Timestamp(d),'peak_date':peak_date,'future_peak_return':peak,'start_vs_prior126_low':float(p0/pl-1) if pd.notna(pl) and pl>0 else None})
    return pd.DataFrame(events)


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--root',default='.'); ap.add_argument('--output',required=True); ap.add_argument('--batch-size',type=int,default=100); a=ap.parse_args()
    root=Path(a.root); out=root/a.output; out.mkdir(parents=True,exist_ok=True)
    symbols,bio=audit.load_universe(root/'universe.csv'); warm=str((scan.START-pd.Timedelta(days=1600)).date()); end='2026-09-05'
    ohlcv,diag=audit.download_ohlcv(symbols,warm,end,a.batch_size); m=scan.build_inputs(ohlcv,bio)
    nq=audit.market_nqsar(str((scan.START-pd.Timedelta(days=120)).date()),end).reindex(m['close'].index).ffill(limit=2)
    idx=m['close'].index[(m['close'].index>=scan.START)&(m['close'].index<=scan.END)]
    print('BUILD EVENTS',flush=True); events=build_events(m,idx); print('EVENTS',len(events),flush=True)
    selection_cache={}
    for k,d in enumerate(idx):
        color=str(nq.at[d,'nq_color']) if d in nq.index and pd.notna(nq.at[d,'nq_color']) else ''
        mm=audit.mode(color,m['breadth'].get(d,np.nan))
        if mm not in {'ATTACK','SELECTIVE'}: continue
        for v in VARIANTS: selection_cache[(v,pd.Timestamp(d))]=set(select_top12(pd.Timestamp(d),m,v))
        if k%250==0: print('SELECT',k,len(idx),flush=True)
    c=m['close']; low126=c.shift(1).rolling(126,min_periods=60).min(); pos={pd.Timestamp(d):i for i,d in enumerate(idx)}; rows=[]
    for ei,e in enumerate(events.itertuples(index=False)):
        st=pd.Timestamp(e.start_date); pk=pd.Timestamp(e.peak_date); i0=pos.get(st); ip=pos.get(pk)
        if i0 is None: continue
        ip=min(ip if ip is not None else i0+126,i0+126,len(idx)-1)
        for v in VARIANTS:
            hit=None
            for j in range(i0,ip+1):
                d=pd.Timestamp(idx[j])
                if e.symbol in selection_cache.get((v,d),set()): hit=d; break
            rec={'event_id':ei,'variant':v,'symbol':e.symbol,'start_date':st,'peak_date':pk,'future_peak_return':e.future_peak_return,'captured':hit is not None}
            if hit is not None:
                j=pos[hit]; entryd=pd.Timestamp(idx[j+1]) if j+1<len(idx) else hit
                ep=m['open'].at[entryd,e.symbol] if e.symbol in m['open'].columns else np.nan
                p0=c.at[st,e.symbol]; pl=low126.at[hit,e.symbol]
                rec['signal_date']=hit; rec['entry_date']=entryd; rec['delay_sessions']=j-i0
                rec['gain_from_event_start']=float(ep/p0-1) if pd.notna(ep) and pd.notna(p0) and p0>0 else None
                rec['gain_from_prior126_low']=float(ep/pl-1) if pd.notna(ep) and pd.notna(pl) and pl>0 else None
            rows.append(rec)
    det=pd.DataFrame(rows); det.to_csv(out/'leader_capture_events.csv',index=False)
    sums=[]
    for period,maskp in [('FULL',pd.Series(True,index=det.index)),('DISCOVERY',det.start_date<=scan.DISC_END),('CONFIRMATION',det.start_date>=scan.CONF_START)]:
        for target in (1.0,2.0,4.0):
            for v in VARIANTS:
                g=det[maskp & (det.variant==v) & (det.future_peak_return>=target)]; h=g[g.captured]
                sums.append({'period':period,'future_peak_threshold':target,'variant':v,'events':len(g),'captured':len(h),'capture_rate':len(h)/len(g) if len(g) else None,
                             'median_delay_sessions':float(h.delay_sessions.median()) if len(h) else None,
                             'median_gain_from_event_start':float(h.gain_from_event_start.median()) if len(h) else None,
                             'median_gain_from_prior126_low':float(h.gain_from_prior126_low.median()) if len(h) else None,
                             'captured_by_50pct_from_prior_low':float((h.gain_from_prior126_low<=.50).mean()) if len(h) else None,
                             'captured_by_100pct_from_prior_low':float((h.gain_from_prior126_low<=1.0).mean()) if len(h) else None})
    pd.DataFrame(sums).to_csv(out/'leader_capture_summary.csv',index=False)
    (out/'summary.json').write_text(json.dumps(safe({'method':'Independent leader-event audit: event starts at first tradable day whose next126-session max is >=2x; actionable Top12 only in current ATTACK/SELECTIVE; capture timing also measured vs prior126-session low','coverage':diag,'variants':VARIANTS,'events':len(events),'limitations':['evaluation labels use future outcomes by design; labels are not signals','current-universe survivorship/current structural classification bias']}),indent=2),encoding='utf-8')

if __name__=='__main__': main()
