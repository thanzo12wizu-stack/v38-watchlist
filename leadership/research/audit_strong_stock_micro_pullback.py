from __future__ import annotations

import argparse, json
from pathlib import Path
import numpy as np
import pandas as pd

import audit_strong_stock_shallow_pullback as broad
import audit_market_rs189_context as ctx
import audit_rsi30_mc_nqsar as state_audit
import audit_rsi_reset_robust as market_base
import validate_rsi_divergence_strong as rsi_base

DISC_END=pd.Timestamp('2021-12-31'); CONF_START=pd.Timestamp('2022-01-03')
COOLDOWN=20; WINDOW=4
METHODS={
 'M5_RSI65_DD075': {'ema':5,'rsi':65.0,'ddatr':0.75},
 'M10_RSI65_DD075': {'ema':10,'rsi':65.0,'ddatr':0.75},
 'M10_RSI60_DD075': {'ema':10,'rsi':60.0,'ddatr':0.75},
 'M10_RSI55_DD075': {'ema':10,'rsi':55.0,'ddatr':0.75},
}


def generate(market:dict,root:Path,asof:str)->pd.DataFrame:
    cl,op,hi,lo=market['close'],market['open'],market['high'],market['low']; cal=cl.index
    age=cl.notna().cumsum(); rsi=rsi_base.rsi(cl,14)
    e5=cl.ewm(span=5,adjust=False).mean(); e10=cl.ewm(span=10,adjust=False).mean(); e21=cl.ewm(span=21,adjust=False).mean(); e50=cl.ewm(span=50,adjust=False).mean()
    r63=cl.pct_change(63,fill_method=None); r189=cl.pct_change(189,fill_method=None)
    rs63=r63.rank(axis=1,pct=True,method='average')*100; rs189=r189.rank(axis=1,pct=True,method='average')*100
    sec_pct,_b,sec_map=ctx.build_sector_state(cl,root); mc=state_audit.build_mc(asof)
    prev=cl.shift(1); tr=(hi-lo).combine((hi-prev).abs(),np.maximum).combine((lo-prev).abs(),np.maximum); atr=tr.rolling(14,min_periods=14).mean()
    high10=hi.rolling(10,min_periods=5).max()
    rows=[]
    for k,sym in enumerate(cl.columns,start=1):
        sec=sec_map.get(sym,'UNMAPPED'); sp=sec_pct[sec].reindex(cal) if sec in sec_pct.columns else pd.Series(np.nan,index=cal)
        c=cl[sym]; l=lo[sym]; rr=rsi[sym]; a=atr[sym]; rise=rr>rr.shift(1)
        mature=(age[sym]>=189)&(rs189[sym]>=85)&(rs63[sym]>=80)
        young=(age[sym]>=63)&(age[sym]<189)&(rs63[sym]>=90)
        structural=(sp>=50)&(c>e21[sym])&(e21[sym]>e50[sym])
        eligible=(mature|young)&structural
        cohort=np.where(young.to_numpy(),'YOUNG','MATURE')
        ddrop=(high10[sym]-l)/a
        for method,cfg in METHODS.items():
            ma=e5[sym] if cfg['ema']==5 else e10[sym]
            touch=eligible&(rr<=cfg['rsi'])&(l<=ma+0.25*a)&(ddrop>=cfg['ddatr'])
            sigok=eligible&rise&(c>=ma)
            last=-999; scan=0
            for ti in np.flatnonzero(touch.fillna(False).to_numpy()):
                if ti<scan: continue
                found=None
                for j in range(ti,min(ti+WINDOW,len(cal)-2)+1):
                    if bool(sigok.iat[j]): found=j; break
                if found is None or found-last<COOLDOWN: continue
                d=cal[found]
                rec={'method':method,'symbol':sym,'sector':sec,'cohort':cohort[found],'touch_date':cal[ti],'signal_date':d,'entry_date':cal[found+1],
                     'listing_age_sessions':int(age[sym].iat[found]),'rsi_touch':float(rr.iat[ti]),'rsi_signal':float(rr.iat[found]),
                     'rs63_signal':float(rs63[sym].iat[found]),'rs189_signal':float(rs189[sym].iat[found]) if pd.notna(rs189[sym].iat[found]) else np.nan,
                     'sector_rs63_pct':float(sp.iat[found]),'mc':float(mc.mc.get(d,np.nan)),'mc_up1':bool(mc.mc_up1.get(d,False)),
                     'drawdown_atr_touch':float(ddrop.iat[ti]),'ema_distance_atr':float((c.iat[found]-ma.iat[found])/a.iat[found]) if pd.notna(a.iat[found]) and a.iat[found]>0 else np.nan}
                rec.update(broad.trade_outcomes(op,cl,hi,lo,sym,found)); rows.append(rec); last=found; scan=found+COOLDOWN
        if k%500==0 or k==len(cl.columns): print(f'MICRO_SCAN {k}/{len(cl.columns)}',flush=True)
    return pd.DataFrame(rows)


def runner(events:pd.DataFrame,market:dict,root:Path):
    cl,op=market['close'],market['open']; cal=cl.index; age=cl.notna().cumsum()
    r63=cl.pct_change(63,fill_method=None); r189=cl.pct_change(189,fill_method=None)
    rs63=r63.rank(axis=1,pct=True,method='average')*100; rs189=r189.rank(axis=1,pct=True,method='average')*100
    e21=cl.ewm(span=21,adjust=False).mean(); e50=cl.ewm(span=50,adjust=False).mean(); sec_pct,_b,sec_map=ctx.build_sector_state(cl,root)
    ev_by={(m,s):g.sort_values('signal_date') for (m,s),g in events.groupby(['method','symbol'],observed=True)}
    rows=[]
    for k,sym in enumerate(cl.columns,start=1):
        sec=sec_map.get(sym,'UNMAPPED'); sp=sec_pct[sec].reindex(cal) if sec in sec_pct.columns else pd.Series(np.nan,index=cal)
        mature=(age[sym]>=189)&(rs189[sym]>=85)&(rs63[sym]>=80); young=(age[sym]>=63)&(age[sym]<189)&(rs63[sym]>=90)
        eligible=(mature|young)&(sp>=50)&(cl[sym]>e21[sym])&(e21[sym]>e50[sym])
        starts=np.flatnonzero((eligible&~eligible.shift(1,fill_value=False)).fillna(False).to_numpy()); last=-999
        for i in starts:
            if i-last<63 or i+1>=len(cal): continue
            e=op.iat[i+1,op.columns.get_loc(sym)]; end=min(i+126,len(cal)-1)
            if pd.isna(e) or e<=0: continue
            mx=float(pd.to_numeric(cl[sym].iloc[i+1:end+1],errors='coerce').max()/e-1)
            rec={'symbol':sym,'sector':sec,'cohort':'YOUNG' if bool(young.iat[i]) else 'MATURE','episode_start':cal[i],'listing_age_sessions':int(age[sym].iat[i]),
                 'rs63_start':float(rs63[sym].iat[i]),'rs189_start':float(rs189[sym].iat[i]) if pd.notna(rs189[sym].iat[i]) else np.nan,'forward126_max':mx,
                 'period':'DISCOVERY' if cal[i]<=DISC_END else 'CONFIRM'}
            for method in sorted(events.method.unique()):
                g=ev_by.get((method,sym)); hit=None
                if g is not None:
                    q=g[(g.signal_date>=cal[i])&(g.signal_date<=cal[min(i+63,len(cal)-1)])]
                    if not q.empty: hit=pd.Timestamp(q.iloc[0].signal_date)
                rec[f'{method}_days']=np.nan if hit is None else int(cal.get_loc(hit)-i)
            rows.append(rec); last=i
        if k%500==0 or k==len(cl.columns): print(f'MICRO_RUNNER {k}/{len(cl.columns)}',flush=True)
    epi=pd.DataFrame(rows); cov=[]
    for period in ('DISCOVERY','CONFIRM'):
      for cohort in ('ALL','YOUNG','MATURE'):
        p=epi[epi.period==period] if cohort=='ALL' else epi[(epi.period==period)&(epi.cohort==cohort)]
        for thr in (.50,.80,1.00):
          q=p[p.forward126_max>=thr]
          for method in sorted(events.method.unique()):
            col=f'{method}_days'; cov.append({'period':period,'cohort':cohort,'runner_threshold':thr,'method':method,'episodes':len(q),
             'covered_63d':int(q[col].notna().sum()),'coverage_rate':float(q[col].notna().mean()) if len(q) else np.nan,
             'median_days_to_entry':float(q[col].dropna().median()) if q[col].notna().any() else np.nan})
    examples=pd.concat([epi[epi.period=='CONFIRM'].nlargest(35,'forward126_max'),epi[epi.symbol=='SNDK']],ignore_index=True).drop_duplicates(['symbol','episode_start'])
    return epi,pd.DataFrame(cov),examples


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--root',default='.'); ap.add_argument('--output',required=True); ap.add_argument('--asof',default='2026-08-28'); args=ap.parse_args()
    root=Path(args.root); out=Path(args.output); out.mkdir(parents=True,exist_ok=True)
    market=market_base.rebuild_market(root,'2016-01-04','2026-06-30',6000,75,3); events=generate(market,root,args.asof)
    events['signal_date']=pd.to_datetime(events.signal_date); events['entry_date']=pd.to_datetime(events.entry_date); events.to_csv(out/'event_rows.csv.gz',index=False,compression='gzip')
    rows=[]; cal=market['close'].index
    for pidx,(period,start,end) in enumerate([('DISCOVERY',pd.Timestamp('2016-01-04'),DISC_END),('CONFIRM',CONF_START,pd.Timestamp('2026-06-30'))]):
      p=events[events.signal_date.between(start,end)]
      for cohort in ('ALL','YOUNG','MATURE'):
       q=p if cohort=='ALL' else p[p.cohort==cohort]
       for midx,(method,g) in enumerate(q.groupby('method',observed=True)):
        rows.append({'period':period,'cohort':cohort,'method':method,**broad.event_stats(g,cal,9100+pidx*100+midx)})
    sm=pd.DataFrame(rows); sm.to_csv(out/'event_summary.csv',index=False)
    broad.summarize_context(events).to_csv(out/'context_summary.csv',index=False); broad.gap_summary(events,cal).to_csv(out/'opportunity_summary.csv',index=False)
    epi,cov,examples=runner(events,market,root); cov.to_csv(out/'runner_coverage.csv',index=False); examples.to_csv(out/'runner_examples.csv',index=False)
    result={'status':'STRONG_STOCK_MICRO_PULLBACK_AUDIT','research_only':True,
      'eligibility':{'mature':'age>=189, RS189>=85, RS63>=80','young':'age 63-188, RS63>=90','common':'sector RS63 percentile>=50, close>EMA21>EMA50'},
      'entry':'EMA5/10 touch within +0.25ATR; RSI cap; at least 0.75ATR pullback from 10d high; first RSI rise within 4 sessions; close reclaims/holds EMA; next-open; 20d cooldown',
      'methods':sm.to_dict('records'),'download':market.get('diag',{}),
      'limitations':['Current-universe/current-classification survivorship bias remains.','2022+ is confirmation, not pristine OOS.','Future runner returns are diagnostic only.','No tax model.']}
    (out/'summary.json').write_text(json.dumps(broad.safe(result),ensure_ascii=False,indent=2),encoding='utf-8'); print(sm.to_string(index=False),flush=True); print(cov.to_string(index=False),flush=True); print(examples.to_string(index=False),flush=True)

if __name__=='__main__': main()
