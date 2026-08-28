from __future__ import annotations

import argparse, json, math
from pathlib import Path
import numpy as np
import pandas as pd

import audit_rsi_reset_robust as market_base
import audit_market_rs189_context as ctx
import audit_rsi30_mc_nqsar as state_audit
import validate_rsi_divergence_strong as rsi_base
import validate_post_ignition_leaders as post

DISC_END = pd.Timestamp('2021-12-31')
CONF_START = pd.Timestamp('2022-01-03')
COST = 5.0 / 10000.0
EPISODE_COOLDOWN = 63
SIGNAL_WINDOW = 4
METHODS = {
    'NOW': {'kind':'now'},
    'M5_RSI65_DD050': {'kind':'pull','ema':5,'rsi':65.0,'ddatr':0.50},
    'M10_RSI65_DD075': {'kind':'pull','ema':10,'rsi':65.0,'ddatr':0.75},
    'M10_RSI60_DD075': {'kind':'pull','ema':10,'rsi':60.0,'ddatr':0.75},
    'M10_RSI55_DD075': {'kind':'pull','ema':10,'rsi':55.0,'ddatr':0.75},
    'M21_RSI55_DD100': {'kind':'pull','ema':21,'rsi':55.0,'ddatr':1.00},
}


def safe(x):
    if isinstance(x, dict): return {str(k): safe(v) for k,v in x.items()}
    if isinstance(x, (list,tuple)): return [safe(v) for v in x]
    if isinstance(x, np.integer): return int(x)
    if isinstance(x, (np.floating,float)):
        z=float(x); return z if math.isfinite(z) else None
    if isinstance(x,pd.Timestamp): return x.isoformat()
    return x


def pf(s):
    x=pd.to_numeric(s,errors='coerce').dropna()
    if x.empty: return None
    gp=float(x[x>0].sum()); gl=float(-x[x<0].sum())
    return None if gl<=0 else gp/gl


def cluster_ci(df, cluster, seed, reps=2000):
    z=df[[cluster,'ret20']].dropna()
    if len(z)<2: return [None,None]
    a=z.groupby(cluster,observed=True).ret20.mean().to_numpy(float)
    if len(a)<2: return [None,None]
    rng=np.random.default_rng(seed)
    d=rng.choice(a,size=(reps,len(a)),replace=True).mean(axis=1)
    q=np.quantile(d,[.025,.975]); return [float(q[0]),float(q[1])]


def stats(g, calendar, seed):
    z=g.dropna(subset=['ret20']).copy()
    if z.empty: return {'n':0}
    pos=pd.Series(np.arange(len(calendar)),index=calendar)
    p=pos.reindex(pd.to_datetime(z.signal_date)).to_numpy(float)
    ok=np.isfinite(p); z=z.loc[ok].copy(); p=p[ok]
    z['block20']=np.floor(p/20).astype('int64')
    r=pd.to_numeric(z.ret20,errors='coerce')
    top5=r.quantile(.95); tr=r[r<=top5]
    return {
        'n':int(len(z)), 'episodes':int(z.episode_id.nunique()), 'signal_dates':int(z.signal_date.nunique()),
        'symbols':int(z.symbol.nunique()), 'mean20':float(r.mean()), 'median20':float(r.median()),
        'win20':float((r>0).mean()), 'pf20':pf(r), 'mae20':float(pd.to_numeric(z.mae20,errors='coerce').mean()),
        'mfe20':float(pd.to_numeric(z.mfe20,errors='coerce').mean()), 'p10_20':float(r.quantile(.10)),
        'top5_removed_mean20':float(tr.mean()) if len(tr) else None, 'top5_removed_pf20':pf(tr),
        'delay_median':float(pd.to_numeric(z.delay,errors='coerce').median()),
        'date_ci95':cluster_ci(z,'signal_date',seed), 'block20_ci95':cluster_ci(z,'block20',seed+1000),
        'symbol_ci95':cluster_ci(z,'symbol',seed+2000), 'sector_ci95':cluster_ci(z,'sector',seed+3000),
    }


def outcome(op,cl,hi,lo,sym,sig_i):
    ei=sig_i+1
    if ei>=len(cl): return {}
    e=op.at[cl.index[ei],sym]
    if pd.isna(e) or e<=0: return {}
    out={}
    for h in (5,10,20):
        end=sig_i+h
        if end>=len(cl): out[f'ret{h}']=np.nan; continue
        c=cl.at[cl.index[end],sym]
        out[f'ret{h}']=float(c/e-1-2*COST) if pd.notna(c) else np.nan
    end=min(sig_i+20,len(cl)-1); ix=cl.index[ei:end+1]
    hs=pd.to_numeric(hi.loc[ix,sym],errors='coerce').dropna(); ls=pd.to_numeric(lo.loc[ix,sym],errors='coerce').dropna()
    out['mfe20']=float(hs.max()/e-1) if len(hs) else np.nan
    out['mae20']=float(ls.min()/e-1) if len(ls) else np.nan
    out['entry_px']=float(e)
    return out


def load_volume(symbols,start,end,batch):
    if not symbols: return pd.DataFrame()
    ohlcv,diag=post.rtv2.download_ohlcvo(symbols,start,end,batch)
    return ohlcv.get('volume',pd.DataFrame()),diag


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--root',default='.'); ap.add_argument('--output',required=True)
    ap.add_argument('--asof',default='2026-08-28'); ap.add_argument('--start',default='2016-01-04'); ap.add_argument('--end',default='2026-06-30')
    args=ap.parse_args(); root=Path(args.root); out=Path(args.output); out.mkdir(parents=True,exist_ok=True)

    market=market_base.rebuild_market(root,args.start,args.end,6000,75,3)
    cl,op,hi,lo=market['close'],market['open'],market['high'],market['low']; cal=cl.index
    age=cl.notna().cumsum(); rsi=rsi_base.rsi(cl,14)
    e5=cl.ewm(span=5,adjust=False).mean(); e10=cl.ewm(span=10,adjust=False).mean(); e21=cl.ewm(span=21,adjust=False).mean(); e50=cl.ewm(span=50,adjust=False).mean()
    r63=cl.pct_change(63,fill_method=None); r189=cl.pct_change(189,fill_method=None)
    rs63=r63.rank(axis=1,pct=True,method='average')*100; rs189=r189.rank(axis=1,pct=True,method='average')*100
    sec_pct,_breadth,sec_map=ctx.build_sector_state(cl,root); mc=state_audit.build_mc(args.asof)
    mc_s=mc.mc.reindex(cal)
    prev=cl.shift(1); tr=(hi-lo).combine((hi-prev).abs(),np.maximum).combine((lo-prev).abs(),np.maximum); atr=tr.rolling(14,min_periods=14).mean()
    high10=hi.rolling(10,min_periods=5).max()

    episode_rows=[]; trade_rows=[]
    analysis_mask=(cal>=pd.Timestamp(args.start))&(cal<=pd.Timestamp(args.end))
    for k,sym in enumerate(cl.columns,start=1):
        sec=sec_map.get(sym,'UNMAPPED'); sp=sec_pct[sec].reindex(cal) if sec in sec_pct.columns else pd.Series(np.nan,index=cal)
        c=cl[sym]; rr=rsi[sym]; a=atr[sym]
        mature=(age[sym]>=189)&(rs189[sym]>=85)&(rs63[sym]>=80)
        young=(age[sym]>=63)&(age[sym]<189)&(rs63[sym]>=90)
        structural=(sp>=50)&(c>e21[sym])&(e21[sym]>e50[sym])
        eligible=(mature|young)&structural
        good=eligible&(mc_s>=50)&analysis_mask
        starts=np.flatnonzero((good&~good.shift(1,fill_value=False)).fillna(False).to_numpy())
        last=-999
        for ei in starts:
            if ei-last<EPISODE_COOLDOWN: continue
            if ei+1>=len(cal): continue
            cohort='YOUNG' if bool(young.iat[ei]) else 'MATURE'; ep_id=f'{sym}|{cal[ei].date()}'
            epx=op.at[cal[ei+1],sym]
            if pd.isna(epx) or epx<=0: continue
            end126=min(ei+126,len(cal)-1); mx=pd.to_numeric(cl[sym].iloc[ei+1:end126+1],errors='coerce').max()
            fmax=float(mx/epx-1) if pd.notna(mx) else np.nan
            ep={'episode_id':ep_id,'symbol':sym,'sector':sec,'cohort':cohort,'episode_start':cal[ei],
                'mc_start':float(mc_s.iat[ei]),'rs63_start':float(rs63[sym].iat[ei]),
                'rs189_start':float(rs189[sym].iat[ei]) if pd.notna(rs189[sym].iat[ei]) else np.nan,
                'sector_start':float(sp.iat[ei]),'forward126_max':fmax,'listing_age':int(age[sym].iat[ei])}
            episode_rows.append(ep)
            rec={**ep,'method':'NOW','touch_date':cal[ei],'signal_date':cal[ei],'entry_date':cal[ei+1],'delay':0,
                 'mc_signal':float(mc_s.iat[ei]),'sector_signal':float(sp.iat[ei]),'rs63_signal':float(rs63[sym].iat[ei]),
                 'rs189_signal':float(rs189[sym].iat[ei]) if pd.notna(rs189[sym].iat[ei]) else np.nan,
                 'rsi_touch':float(rr.iat[ei]) if pd.notna(rr.iat[ei]) else np.nan,'rsi_signal':float(rr.iat[ei]) if pd.notna(rr.iat[ei]) else np.nan,
                 'drawdown_atr_touch':float((high10[sym].iat[ei]-lo[sym].iat[ei])/a.iat[ei]) if pd.notna(a.iat[ei]) and a.iat[ei]>0 else np.nan}
            rec.update(outcome(op,cl,hi,lo,sym,ei)); trade_rows.append(rec)
            stop=min(ei+63,len(cal)-2)
            bad=np.flatnonzero((mc_s.iloc[ei:stop+1]<50).fillna(True).to_numpy())
            if len(bad): stop=min(stop,ei+int(bad[0])-1)
            if stop>=ei:
                rise=rr>rr.shift(1); dd=(high10[sym]-lo[sym])/a
                for method,cfg in METHODS.items():
                    if method=='NOW': continue
                    ma={5:e5[sym],10:e10[sym],21:e21[sym]}[cfg['ema']]
                    touch=eligible&(mc_s>=50)&(rr<=cfg['rsi'])&(lo[sym]<=ma+0.25*a)&(dd>=cfg['ddatr'])
                    sigok=eligible&(mc_s>=50)&rise&(c>=ma)
                    found=None; touch_i=None
                    for ti in range(ei,stop+1):
                        if not bool(touch.iat[ti]): continue
                        for sj in range(ti,min(ti+SIGNAL_WINDOW,stop)+1):
                            if bool(sigok.iat[sj]): found=sj; touch_i=ti; break
                        if found is not None: break
                    if found is None or found+1>=len(cal): continue
                    rec={**ep,'method':method,'touch_date':cal[touch_i],'signal_date':cal[found],'entry_date':cal[found+1],
                         'delay':int(found-ei),'mc_signal':float(mc_s.iat[found]),'sector_signal':float(sp.iat[found]),
                         'rs63_signal':float(rs63[sym].iat[found]),'rs189_signal':float(rs189[sym].iat[found]) if pd.notna(rs189[sym].iat[found]) else np.nan,
                         'rsi_touch':float(rr.iat[touch_i]),'rsi_signal':float(rr.iat[found]),'drawdown_atr_touch':float(dd.iat[touch_i])}
                    rec.update(outcome(op,cl,hi,lo,sym,found)); trade_rows.append(rec)
            last=ei
        if k%500==0 or k==len(cl.columns): print(f'GOOD_MARKET_SCAN {k}/{len(cl.columns)}',flush=True)

    epi=pd.DataFrame(episode_rows); trd=pd.DataFrame(trade_rows)
    if trd.empty: raise RuntimeError('no trades')
    syms=sorted(trd.symbol.unique())
    vol,vdiag=load_volume(syms,str((pd.Timestamp(args.start)-pd.Timedelta(days=80)).date()),str((pd.Timestamp(args.end)+pd.Timedelta(days=5)).date()),75)
    avgvol=vol.rolling(20,min_periods=15).mean() if not vol.empty else pd.DataFrame()
    adr=((hi-lo)/cl.replace(0,np.nan)*100).rolling(20,min_periods=15).mean()
    price=[]; av=[]; ad=[]
    for r in trd.itertuples(index=False):
        d=pd.Timestamp(r.signal_date); s=r.symbol
        price.append(float(cl.at[d,s]) if d in cl.index and s in cl.columns and pd.notna(cl.at[d,s]) else np.nan)
        av.append(float(avgvol.at[d,s]) if d in avgvol.index and s in avgvol.columns and pd.notna(avgvol.at[d,s]) else np.nan)
        ad.append(float(adr.at[d,s]) if d in adr.index and s in adr.columns and pd.notna(adr.at[d,s]) else np.nan)
    trd['price_signal']=price; trd['avgvol20']=av; trd['adr20_pct']=ad
    trd['liquid']=(trd.price_signal>=5)&(trd.avgvol20>=1_000_000)&trd.adr20_pct.between(3,15,inclusive='both')
    trd['period']=np.where(trd.signal_date<=DISC_END,'DISCOVERY','CONFIRM')
    trd['mc_band']=pd.cut(trd.mc_signal,[50,65,80,np.inf],right=False,labels=['50_65','65_80','GE80'])
    trd['year']=pd.to_datetime(trd.signal_date).dt.year
    trd.to_csv(out/'trade_rows.csv.gz',index=False,compression='gzip'); epi.to_csv(out/'episodes.csv.gz',index=False,compression='gzip')

    rows=[]; seed=10000
    for period in ('DISCOVERY','CONFIRM'):
        p=trd[trd.period==period]
        for cohort in ('MATURE','YOUNG'):
            q0=p[p.cohort==cohort]
            for liquid in (False,True):
                q1=q0[q0.liquid] if liquid else q0
                for mcband in ('50_65','65_80','GE80','GE50'):
                    q2=q1 if mcband=='GE50' else q1[q1.mc_band.astype(str)==mcband]
                    for sect in (50,70,80):
                        q3=q2[q2.sector_signal>=sect]
                        for method,g in q3.groupby('method',observed=True):
                            if len(g)<10: continue
                            s=stats(g,cal,seed); seed+=10
                            rows.append({'period':period,'cohort':cohort,'liquid':liquid,'mc_band':mcband,'sector_min':sect,'method':method,**s})
    summary=pd.DataFrame(rows); summary.to_csv(out/'event_summary.csv',index=False)

    pair=[]
    now=trd[trd.method=='NOW'][['episode_id','ret20','mae20','entry_px','entry_date']].rename(columns={'ret20':'now_ret20','mae20':'now_mae20','entry_px':'now_entry_px','entry_date':'now_entry_date'})
    z=trd.merge(now,on='episode_id',how='left')
    z=z[z.method!='NOW'].copy(); z['ret_delta_vs_now']=z.ret20-z.now_ret20; z['mae_delta_vs_now']=z.mae20-z.now_mae20
    z['price_missed_before_entry']=z.entry_px/z.now_entry_px-1
    for period in ('DISCOVERY','CONFIRM'):
      for cohort in ('MATURE','YOUNG'):
       p=z[(z.period==period)&(z.cohort==cohort)&z.liquid&(z.sector_signal>=70)]
       for mcband in ('50_65','65_80','GE50'):
        q=p if mcband=='GE50' else p[p.mc_band.astype(str)==mcband]
        for method,g in q.groupby('method',observed=True):
            if len(g)<10: continue
            pair.append({'period':period,'cohort':cohort,'mc_band':mcband,'method':method,'n':len(g),
                         'ret_delta_vs_now_mean':float(g.ret_delta_vs_now.mean()),'ret_delta_vs_now_median':float(g.ret_delta_vs_now.median()),
                         'mae_improvement_vs_now_mean':float(g.mae_delta_vs_now.mean()),
                         'missed_move_to_entry_mean':float(g.price_missed_before_entry.mean()),'delay_median':float(g.delay.median())})
    pd.DataFrame(pair).to_csv(out/'paired_vs_now.csv',index=False)

    cover=[]
    for period,start,end in [('DISCOVERY',pd.Timestamp(args.start),DISC_END),('CONFIRM',CONF_START,pd.Timestamp(args.end))]:
      e=epi[pd.to_datetime(epi.episode_start).between(start,end)]
      for cohort in ('MATURE','YOUNG'):
       ec=e[e.cohort==cohort]
       for thr in (.50,.80,1.00):
        erun=ec[ec.forward126_max>=thr]
        for method in METHODS:
            hits=trd[(trd.method==method)&trd.episode_id.isin(erun.episode_id)&trd.liquid]
            cover.append({'period':period,'cohort':cohort,'runner_threshold':thr,'method':method,'episodes':len(erun),
                          'covered_liquid':int(hits.episode_id.nunique()),'coverage_rate':float(hits.episode_id.nunique()/len(erun)) if len(erun) else np.nan,
                          'median_delay':float(hits.delay.median()) if len(hits) else np.nan})
    pd.DataFrame(cover).to_csv(out/'runner_coverage.csv',index=False)

    yr=[]
    p=trd[(trd.cohort=='MATURE')&trd.liquid&(trd.sector_signal>=70)]
    for (year,band,method),g in p.groupby(['year','mc_band','method'],observed=True):
        if len(g)<5: continue
        r=g.ret20.dropna(); yr.append({'year':year,'mc_band':str(band),'method':method,'n':len(r),'mean20':float(r.mean()),'median20':float(r.median()),'pf20':pf(r),'mae20':float(g.mae20.mean())})
    pd.DataFrame(yr).to_csv(out/'year_summary.csv',index=False)

    result={'status':'TRUE_SHALLOW_GOOD_MARKET_AUDIT','research_only':True,
            'market_definition':'signal-day production MC57 >=50; primary bands 50-65 and 65-80; MC<50 excluded from shallow study',
            'mature':'age>=189, RS189>=85, RS63>=80, sector>=50, close>EMA21>EMA50',
            'young':'age 63-188, RS63>=90, sector>=50, close>EMA21>EMA50; reported separately',
            'liquidity':'price>=5, AvgVol20>=1M, ADR20 3-15%', 'methods':METHODS,
            'episode_count':int(len(epi)),'trade_count':int(len(trd)),'download':market.get('diag',{}),'volume_download':vdiag,
            'limitations':['Current-universe/current-sector survivorship bias remains.','2022+ is confirmation, not pristine OOS.','MC57 is current 57ETF/12-metric historical reconstruction.','No tax model.']}
    (out/'summary.json').write_text(json.dumps(safe(result),ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(safe(result),ensure_ascii=False,indent=2),flush=True)
    print(summary[(summary.cohort=='MATURE')&summary.liquid&(summary.sector_min==70)&summary.mc_band.isin(['50_65','65_80','GE50'])].to_string(index=False),flush=True)

if __name__=='__main__': main()
