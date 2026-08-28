from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

import audit_strong_stock_shallow_pullback as broad
import audit_market_rs189_context as ctx
import audit_rsi30_mc_nqsar as state_audit
import audit_rsi_reset_robust as market_base
import validate_rsi_divergence_strong as rsi_base

DISC_END = pd.Timestamp('2021-12-31')
CONF_START = pd.Timestamp('2022-01-03')
COST = broad.COST
COOLDOWN = 20
TOUCH_WINDOW = 5
CUTS = (90.0, 95.0)


def generate(market: dict, root: Path, asof: str) -> pd.DataFrame:
    cl, op, hi, lo = market['close'], market['open'], market['high'], market['low']
    cal = cl.index
    age = cl.notna().cumsum()
    ret63 = cl.pct_change(63, fill_method=None)
    rs63 = ret63.rank(axis=1, pct=True, method='average') * 100.0
    rsi = rsi_base.rsi(cl, 14)
    ema10 = cl.ewm(span=10, adjust=False).mean(); ema21 = cl.ewm(span=21, adjust=False).mean(); ema50 = cl.ewm(span=50, adjust=False).mean()
    sec_pct, _b, sec_map = ctx.build_sector_state(cl, root)
    mc = state_audit.build_mc(asof)
    prev = cl.shift(1)
    tr = (hi - lo).combine((hi - prev).abs(), np.maximum).combine((lo - prev).abs(), np.maximum)
    atr = tr.rolling(14, min_periods=14).mean()
    rows=[]
    for k,sym in enumerate(cl.columns,start=1):
        sec=sec_map.get(sym,'UNMAPPED'); sp=sec_pct[sec].reindex(cal) if sec in sec_pct.columns else pd.Series(np.nan,index=cal)
        c=cl[sym]; l=lo[sym]; rr=rsi[sym]; a=atr[sym]; rise=rr>rr.shift(1)
        for cut in CUTS:
            young=(age[sym]>=63)&(age[sym]<189)&(rs63[sym]>=cut)&(sp>=50)&(c>ema21[sym])&(ema21[sym]>ema50[sym])
            touch=young&(rr<=55)&(l<=ema10[sym]+0.25*a)
            signal_ok=young&rise&(c>=ema10[sym])
            last=-999; scan_from=0
            for ti in np.flatnonzero(touch.fillna(False).to_numpy()):
                if ti<scan_from: continue
                found=None
                for j in range(ti,min(ti+TOUCH_WINDOW,len(cal)-2)+1):
                    if bool(signal_ok.iat[j]): found=j; break
                if found is None or found-last<COOLDOWN: continue
                d=cal[found]
                rec={'method':f'Y10_RSI55_RS63_{int(cut)}','symbol':sym,'sector':sec,'touch_date':cal[ti],'signal_date':d,'entry_date':cal[found+1],
                     'rsi_signal':float(rr.iat[found]),'rsi_touch':float(rr.iat[ti]),'rs63_signal':float(rs63[sym].iat[found]),'rs189_signal':np.nan,
                     'sector_rs63_pct':float(sp.iat[found]),'mc':float(mc.mc.get(d,np.nan)),'mc_up1':bool(mc.mc_up1.get(d,False)),
                     'listing_age_sessions':int(age[sym].iat[found]),
                     'ema_distance_atr':float((c.iat[found]-ema10[sym].iat[found])/a.iat[found]) if pd.notna(a.iat[found]) and a.iat[found]>0 else np.nan}
                rec.update(broad.trade_outcomes(op,cl,hi,lo,sym,found)); rows.append(rec); last=found; scan_from=found+COOLDOWN
        if k%500==0 or k==len(cl.columns): print(f'YOUNG_SIGNAL_SCAN {k}/{len(cl.columns)}',flush=True)
    return pd.DataFrame(rows)


def runner(events: pd.DataFrame, market: dict, root: Path):
    cl,op=market['close'],market['open']; cal=cl.index; age=cl.notna().cumsum()
    ret63=cl.pct_change(63,fill_method=None); rs63=ret63.rank(axis=1,pct=True,method='average')*100
    ema21=cl.ewm(span=21,adjust=False).mean(); ema50=cl.ewm(span=50,adjust=False).mean()
    sec_pct,_b,sec_map=ctx.build_sector_state(cl,root)
    ev_by={(m,s):g.sort_values('signal_date') for (m,s),g in events.groupby(['method','symbol'],observed=True)}
    rows=[]
    for k,sym in enumerate(cl.columns,start=1):
        sec=sec_map.get(sym,'UNMAPPED'); sp=sec_pct[sec].reindex(cal) if sec in sec_pct.columns else pd.Series(np.nan,index=cal)
        eligible=(age[sym]>=63)&(age[sym]<189)&(rs63[sym]>=90)&(sp>=50)&(cl[sym]>ema21[sym])&(ema21[sym]>ema50[sym])
        starts=np.flatnonzero((eligible&~eligible.shift(1,fill_value=False)).fillna(False).to_numpy()); last=-999
        for i in starts:
            if i-last<63 or i+1>=len(cal): continue
            end=min(i+126,len(cal)-1); e=op.iat[i+1,op.columns.get_loc(sym)]
            if pd.isna(e) or e<=0: continue
            mx=float(pd.to_numeric(cl[sym].iloc[i+1:end+1],errors='coerce').max()/e-1)
            rec={'symbol':sym,'sector':sec,'episode_start':cal[i],'listing_age_sessions':int(age[sym].iat[i]),'rs63_start':float(rs63[sym].iat[i]),
                 'forward126_max':mx,'period':'DISCOVERY' if cal[i]<=DISC_END else 'CONFIRM'}
            for method in sorted(events.method.unique()):
                g=ev_by.get((method,sym)); hit=None
                if g is not None:
                    q=g[(g.signal_date>=cal[i])&(g.signal_date<=cal[min(i+63,len(cal)-1)])]
                    if not q.empty: hit=pd.Timestamp(q.iloc[0].signal_date)
                rec[f'{method}_days']=np.nan if hit is None else int(cal.get_loc(hit)-i)
            rows.append(rec); last=i
        if k%500==0 or k==len(cl.columns): print(f'YOUNG_RUNNER_SCAN {k}/{len(cl.columns)}',flush=True)
    epi=pd.DataFrame(rows); cov=[]
    for period in ('DISCOVERY','CONFIRM'):
        p=epi[epi.period==period]
        for thr in (.50,.80,1.00):
            q=p[p.forward126_max>=thr]
            for method in sorted(events.method.unique()):
                col=f'{method}_days'; cov.append({'period':period,'runner_threshold':thr,'method':method,'episodes':len(q),'covered_63d':int(q[col].notna().sum()),
                    'coverage_rate':float(q[col].notna().mean()) if len(q) else np.nan,'median_days_to_entry':float(q[col].dropna().median()) if q[col].notna().any() else np.nan})
    examples=pd.concat([epi[epi.period=='CONFIRM'].nlargest(30,'forward126_max'),epi[epi.symbol=='SNDK']],ignore_index=True).drop_duplicates(['symbol','episode_start'])
    return epi,pd.DataFrame(cov),examples


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--root',default='.'); ap.add_argument('--output',required=True); ap.add_argument('--asof',default='2026-08-28'); args=ap.parse_args()
    root=Path(args.root); out=Path(args.output); out.mkdir(parents=True,exist_ok=True)
    market=market_base.rebuild_market(root,'2016-01-04','2026-06-30',6000,75,3)
    events=generate(market,root,args.asof); events['signal_date']=pd.to_datetime(events.signal_date); events['entry_date']=pd.to_datetime(events.entry_date)
    events.to_csv(out/'event_rows.csv.gz',index=False,compression='gzip')
    rows=[]; cal=market['close'].index
    for pidx,(period,start,end) in enumerate([('DISCOVERY',pd.Timestamp('2016-01-04'),DISC_END),('CONFIRM',CONF_START,pd.Timestamp('2026-06-30'))]):
        for midx,(method,g) in enumerate(events[events.signal_date.between(start,end)].groupby('method',observed=True)):
            rows.append({'period':period,'method':method,**broad.event_stats(g,cal,6200+pidx*100+midx)})
    sm=pd.DataFrame(rows); sm.to_csv(out/'event_summary.csv',index=False)
    broad.summarize_context(events).to_csv(out/'context_summary.csv',index=False)
    broad.gap_summary(events,cal).to_csv(out/'opportunity_summary.csv',index=False)
    epi,cov,examples=runner(events,market,root); cov.to_csv(out/'runner_coverage.csv',index=False); examples.to_csv(out/'runner_examples.csv',index=False)
    result={'status':'YOUNG_LEADER_SHALLOW_PULLBACK_AUDIT','research_only':True,
            'definition':'listing-age 63-188 sessions; cross-sectional RS63>=90/95; sector RS63 percentile>=50; close>EMA21>EMA50; RSI<=55 EMA10+0.25ATR touch; first RSI rise within 5 sessions; next-open',
            'methods':sm.to_dict('records'),'download':market.get('diag',{}),
            'limitations':['Current-universe/current-classification survivorship bias remains.','Listing age is observed-session count in downloaded history; analysis starts 2016 so pre-existing names are seasoned before evaluation.','2022+ is confirmation, not pristine OOS.','Future 126d runner return is diagnostic only.','No tax model.']}
    (out/'summary.json').write_text(json.dumps(broad.safe(result),ensure_ascii=False,indent=2),encoding='utf-8')
    print(sm.to_string(index=False),flush=True); print(cov.to_string(index=False),flush=True); print(examples.to_string(index=False),flush=True)

if __name__=='__main__': main()
