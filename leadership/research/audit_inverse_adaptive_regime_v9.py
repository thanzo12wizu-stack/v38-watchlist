from __future__ import annotations
import argparse, io, json, os, sys
from pathlib import Path
import numpy as np
import pandas as pd
import requests
import yfinance as yf

import audit_inverse_full_v38_v4 as v4

MAP={0:'Red',1:'Yellow',2:'Green',3:'Blue'}
FREEZE=pd.Timestamp('2026-03-20')
RECENT_START=pd.Timestamp('2026-03-23')
INV_COSTS=[5,40,80]


def safe(x):
    if isinstance(x,dict): return {str(k):safe(v) for k,v in x.items()}
    if isinstance(x,(list,tuple)): return [safe(v) for v in x]
    if isinstance(x,(np.integer,)): return int(x)
    if isinstance(x,(np.floating,float)): return None if not np.isfinite(float(x)) else float(x)
    if isinstance(x,(pd.Timestamp,)): return str(x)
    return x


def norm(x):
    z=pd.DatetimeIndex(pd.to_datetime(x))
    if z.tz is not None: z=z.tz_convert('America/New_York').tz_localize(None)
    return z.normalize()


def cooldown(cond,c=10):
    x=cond.fillna(False).astype(bool); raw=x & ~x.shift(1,fill_value=False)
    out=np.zeros(len(x),bool); last=-10**9
    for i,z in enumerate(raw.to_numpy(bool)):
        if z and i-last>c: out[i]=1; last=i
    return pd.Series(out,index=x.index)


def wilder_rsi(s,n=14):
    a=pd.to_numeric(s,errors='coerce').to_numpy(float); d=np.diff(a,prepend=np.nan)
    up=np.where(d>0,d,0.); dn=np.where(d<0,-d,0.)
    au=np.full(len(a),np.nan); ad=np.full(len(a),np.nan)
    if len(a)>n:
        au[n]=np.nanmean(up[1:n+1]); ad[n]=np.nanmean(dn[1:n+1])
        for i in range(n+1,len(a)):
            au[i]=(au[i-1]*(n-1)+up[i])/n; ad[i]=(ad[i-1]*(n-1)+dn[i])/n
    rs=au/ad; r=100-100/(1+rs); r[(ad==0)&np.isfinite(au)]=100.; r[(au==0)&(ad==0)]=50.
    return pd.Series(r,index=s.index)


def adx(c,h,l,n=14):
    c=pd.to_numeric(c,errors='coerce'); h=pd.to_numeric(h,errors='coerce'); l=pd.to_numeric(l,errors='coerce')
    up=h.diff(); dn=-l.diff(); plus=np.where((up>dn)&(up>0),up,0.); minus=np.where((dn>up)&(dn>0),dn,0.)
    tr=pd.concat([(h-l).abs(),(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    atr=tr.ewm(alpha=1/n,adjust=False,min_periods=n).mean()
    pdi=100*pd.Series(plus,index=c.index).ewm(alpha=1/n,adjust=False,min_periods=n).mean()/atr
    mdi=100*pd.Series(minus,index=c.index).ewm(alpha=1/n,adjust=False,min_periods=n).mean()/atr
    dx=100*(pdi-mdi).abs()/(pdi+mdi).replace(0,np.nan)
    ax=dx.ewm(alpha=1/n,adjust=False,min_periods=n).mean()
    return ax,pdi-mdi


def dl_daily(symbols,start='2010-01-01'):
    x=yf.download(symbols,start=start,end=(pd.Timestamp.utcnow().tz_localize(None)+pd.Timedelta(days=2)).date().isoformat(),auto_adjust=True,actions=False,progress=False,threads=False,group_by='column')
    if x.empty: raise RuntimeError('daily market download empty')
    if not isinstance(x.columns,pd.MultiIndex):
        x.columns=pd.MultiIndex.from_product([x.columns,[symbols[0] if isinstance(symbols,list) else symbols]])
    x.index=norm(x.index)
    return x


def fred(series):
    url=f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}'
    try:
        r=requests.get(url,timeout=30); r.raise_for_status(); d=pd.read_csv(io.StringIO(r.text))
        d.columns=['date',series]; d['date']=pd.to_datetime(d.date,errors='coerce'); d[series]=pd.to_numeric(d[series],errors='coerce')
        return d.dropna().drop_duplicates('date').set_index('date')[series].sort_index()
    except Exception as e:
        print('[fred fail]',series,repr(e),flush=True); return pd.Series(dtype=float,name=series)


def market_features(idx):
    syms=['QQQ','^VIX','HYG','LQD','RSP','SPY','IWM','SOXX','TLT','UUP','XLY','XLP']
    x=dl_daily(syms,'2010-01-01')
    def field(f,s): return pd.to_numeric(x[f][s],errors='coerce')
    q=field('Close','QQQ'); h=field('High','QQQ'); l=field('Low','QQQ')
    out=pd.DataFrame(index=x.index)
    out['qqq_ret20']=q.pct_change(20); out['qqq_ret63']=q.pct_change(63)
    out['qqq_rv20']=q.pct_change().rolling(20).std()*np.sqrt(252)
    out['qqq_adx14'],out['qqq_dmi_spread']=adx(q,h,l,14)
    v=field('Close','^VIX'); out['vix']=v; out['vix_chg10']=v.pct_change(10)
    pairs=[('hyg_lqd','HYG','LQD'),('rsp_spy','RSP','SPY'),('iwm_qqq','IWM','QQQ'),('soxx_qqq','SOXX','QQQ'),('tlt_qqq','TLT','QQQ'),('xly_xlp','XLY','XLP')]
    for nm,a,b in pairs: out[nm+'_mom20']=(field('Close',a)/field('Close',b)).pct_change(20)
    out['uup_ret20']=field('Close','UUP').pct_change(20)
    # Pre-specified market-only persistence score. No era dates or return fitting enter this definition.
    out['axis_trend']=((out.qqq_adx14>=20)&(out.qqq_dmi_spread<0)).astype(int)
    out['axis_momentum']=(out.qqq_ret20<0).astype(int)
    out['axis_vol']=(out.vix_chg10>0).astype(int)
    out['axis_credit']=(out.hyg_lqd_mom20<0).astype(int)
    out['axis_breadthproxy']=(out.rsp_spy_mom20<0).astype(int)
    out['axis_semi']=(out.soxx_qqq_mom20<0).astype(int)
    out['persist_score']=out[[c for c in out.columns if c.startswith('axis_')]].sum(axis=1)
    # Macro is descriptive only: one-session lag after calendar alignment.
    f=pd.DataFrame(index=out.index)
    for s in ['DGS2','DGS10','DFII10','NFCI','BAMLH0A0HYM2','WALCL','WTREGEN','RRPONTSYD']:
        z=fred(s); f[s]=z.reindex(out.index).ffill(limit=10).shift(1)
    f['curve_2s10s']=f.DGS10-f.DGS2
    f['real10_chg5']=f.DFII10.diff(5); f['dgs2_chg5']=f.DGS2.diff(5); f['hy_oas_chg20']=f.BAMLH0A0HYM2.diff(20)
    f['netliq']=f.WALCL*1000-f.WTREGEN-f.RRPONTSYD*1000
    f['netliq_chg60_pct']=f.netliq.pct_change(60)
    out=out.join(f)
    return out.reindex(idx)


def hourly_touch30():
    # Yahoo 60m is used only for the post-freeze Stage56 guard extension. Convert explicitly to NY before RTH bucketing.
    end=(pd.Timestamp.utcnow().tz_localize(None)+pd.Timedelta(days=2)).date().isoformat()
    start=(pd.Timestamp.utcnow().tz_localize(None)-pd.Timedelta(days=690)).date().isoformat()
    x=yf.download('QQQ',start=start,end=end,interval='60m',auto_adjust=True,actions=False,prepost=False,progress=False,threads=False)
    if x.empty: return pd.Series(dtype=bool),pd.DataFrame()
    if isinstance(x.columns,pd.MultiIndex): x.columns=x.columns.get_level_values(0)
    z=pd.DatetimeIndex(x.index)
    if z.tz is None: z=z.tz_localize('UTC').tz_convert('America/New_York')
    else: z=z.tz_convert('America/New_York')
    x=x.copy(); x['dt_et']=z; mins=x.dt_et.dt.hour*60+x.dt_et.dt.minute
    x=x[(mins>=570)&(mins<960)].copy(); mins=x.dt_et.dt.hour*60+x.dt_et.dt.minute
    x['date']=x.dt_et.dt.tz_localize(None).dt.normalize(); x['slot']=np.where(mins<810,0,1)
    b=x.groupby(['date','slot'],sort=True).agg(Open=('Open','first'),High=('High','max'),Low=('Low','min'),Close=('Close','last'),n=('Close','size')).reset_index()
    b=b[b.n>=2].sort_values(['date','slot']).reset_index(drop=True); b['rsi14']=wilder_rsi(b.Close,14).to_numpy()
    r=b.rsi14.to_numpy(float); b['touch30']=(r<=30)&np.r_[False,r[:-1]>30]
    return b.groupby('date').touch30.max().astype(bool),b


def approximate_stage56(d,vix,touch):
    seed=(pd.to_numeric(d.s50a,errors='coerce')<=-.5)&(vix>=23)&(pd.to_numeric(d.dd10,errors='coerce')<=-.02)
    rawbear=(~d.a200.astype(bool))&(~d.a252.astype(bool)); mc=pd.to_numeric(d.mc57,errors='coerce')
    t=touch.reindex(d.index).fillna(False).astype(bool)
    out=np.zeros(len(d),bool); age=10**9; active=False; entry=-1; consumed=-1
    seedv=seed.fillna(False).to_numpy(bool); tv=t.to_numpy(bool); rb=rawbear.to_numpy(bool); m=mc.to_numpy(float)
    for i in range(len(d)):
        age=0 if seedv[i] else age+1; recent=age<=30
        last=np.flatnonzero(seedv[:i+1]); sid=int(last[-1]) if len(last) else -1
        if (not active) and recent and tv[i] and np.isfinite(m[i]) and m[i]>=20 and sid>consumed:
            active=True; entry=i; consumed=sid
        if active:
            if seedv[i]: consumed=max(consumed,i)
            held=i-entry; done=held>=10; bad=(np.isfinite(m[i]) and m[i]<20) or (rb[i] and held>=10) or done or held>=20
            if bad: active=False; entry=-1
            else: out[i]=True
    return pd.Series(out,index=d.index),seed


def qid_returns(idx):
    x=dl_daily(['QID'],'2010-01-01'); op=pd.to_numeric(x['Open']['QID'],errors='coerce').reindex(idx)
    return op.shift(-1)/op-1


def adaptive_flags(events):
    # Every eligible signal can be observed ex post even when not traded, so the monitor learns while OFF.
    rows=[]
    vals=[]; dates=[]
    for _,r in events.sort_values('signal_date').iterrows():
        v=np.asarray(vals,float); sd=pd.Timestamp(r.signal_date)
        last3=v[-3:] if len(v)>=3 else np.array([]); last5=v[-5:] if len(v)>=5 else np.array([])
        if len(v)>=3:
            ages=np.arange(len(v)-1,-1,-1); w=.5**(ages/3.0); ew=float(np.sum(w*v)/np.sum(w))
        else: ew=np.nan
        trailing=[vals[j] for j,d0 in enumerate(dates) if pd.Timestamp(d0)>=sd-pd.DateOffset(years=3)]
        flags={
            'G_LAST3_MEAN':len(last3)==3 and float(np.mean(last3))>0,
            'G_LAST5_MEAN':len(last5)==5 and float(np.mean(last5))>0,
            'G_LAST5_MEDIAN':len(last5)==5 and float(np.median(last5))>0,
            'G_LAST5_WIN60':len(last5)==5 and float(np.mean(last5>0))>=.60,
            'G_EWMA_HL3':len(v)>=3 and ew>0,
            'G_TRAIL3Y_MEAN':len(trailing)>=3 and float(np.mean(trailing))>0,
        }
        rows.append({'signal_date':sd,'prior_n':len(v),'prior3_mean':float(np.mean(last3)) if len(last3) else np.nan,'prior5_mean':float(np.mean(last5)) if len(last5) else np.nan,'prior_ewma_hl3':ew,**flags})
        if pd.notna(r.qid2): vals.append(float(r.qid2)); dates.append(sd)
    return pd.DataFrame(rows)


def gate_summary(ev,gate):
    z=ev[ev[gate].fillna(False)].copy(); a=pd.to_numeric(z.qid2,errors='coerce').dropna()
    return {'gate':gate,'events':len(a),'mean_qid2':float(a.mean()) if len(a) else np.nan,'median_qid2':float(a.median()) if len(a) else np.nan,'win':float((a>0).mean()) if len(a) else np.nan,'cum_qid30':float(np.prod(1+.30*a)-1) if len(a) else 0.}


def corrected_variant(d,invret,active,inv_cost_bp):
    t,inv=v4.overlay_positions(d,active,'QID_CASH30')
    ret=d.o_contrib.to_numpy(float)+d.r_contrib.to_numpy(float)+t*d.tqqq_ret.to_numpy(float)
    tt=np.zeros(len(d)); tt[1:]=np.abs(np.diff(t)); ret-=tt*(5/10000)
    w=inv['QID']; rp=pd.to_numeric(invret['QID'],errors='coerce').fillna(0).to_numpy(float); ret+=w*rp
    tr=np.zeros(len(d)); tr[1:]=np.abs(np.diff(w)); ret-=tr*(inv_cost_bp/10000)
    return pd.Series(ret,index=d.index)


def portfolio_gate_test(a,gate_map,outdir):
    feat=pd.read_csv(a.v2_features,compression='gzip',parse_dates=['date']).sort_values('date')
    ordinary=pd.read_csv(Path(a.gross100)/'gross100_final_reset_components/ordinary_PEAK30_PART25_R3_daily.csv.gz',compression='gzip',parse_dates=['date']).rename(columns={'gross_exposure':'gross_exposure_ord','return':'return_ord'})
    reset=pd.read_csv(Path(a.gross100)/'gross100_final_reset_components/rsi_RESET_RISE30_S029_P4_H20_daily.csv.gz',compression='gzip',parse_dates=['date']).rename(columns={'gross_exposure':'gross_exposure_rsi','return':'return_rsi'})
    tq=pd.read_csv(a.tqqq,compression='gzip',parse_dates=['date'])
    d=v4.baseline_components(ordinary,reset,tq,feat); d['date']=norm(d.date); bm=v4.metrics(d.baseline_ret)
    if abs(bm['cagr']-0.470025795426962)>5e-6: raise RuntimeError('Gross100 baseline mismatch')
    sig=v4.signal_defs(d)['CORE_MC']; guard=v4.guards(d)['PANIC_OR_STAGE56']; baseev=v4.cooldown_events(sig,10)&~guard
    inv=v4.price_returns(norm(d.date),str(d.date.min().date()),str(d.date.max().date())); inv.index=d.index
    rows=[]
    gates=['UNGATED']+sorted(gate_map.columns.drop('signal_date').tolist())
    periods={'TRAIN_2016_2021':('2016-01-04','2021-12-31'),'HOLDOUT_2022_2026':('2022-01-03','2026-03-20'),'2016_2019':('2016-01-04','2019-12-31'),'2020_2021':('2020-01-01','2021-12-31'),'2022_2023':('2022-01-03','2023-12-29'),'2024_2026':('2024-01-02','2026-03-20')}
    mp=gate_map.set_index(pd.to_datetime(gate_map.signal_date).dt.normalize())
    for g in gates:
        sel=baseev.copy()
        if g!='UNGATED':
            allow=d.date.map(mp[g]).fillna(False).to_numpy(bool); sel=sel & pd.Series(allow,index=sel.index)
        for cost in INV_COSTS:
            act,_=v4.build_active(sel,2,guard); r=corrected_variant(d,inv,act,cost); mm=v4.metrics(r)
            row={'gate':g,'inverse_cost_bp':cost,'events':int(sel.sum()),'cagr':mm['cagr'],'mdd':mm['mdd'],'delta_cagr':mm['cagr']-bm['cagr'],'delta_mdd':mm['mdd']-bm['mdd']}
            for lab,(aa,bb) in periods.items():
                m=(d.date>=aa)&(d.date<=bb); x=v4.metrics(r.loc[m]); b=v4.metrics(d.baseline_ret.loc[m]); row[lab+'_delta_cagr']=x['cagr']-b['cagr']; row[lab+'_delta_mdd']=x['mdd']-b['mdd']
            rows.append(row)
    pd.DataFrame(rows).to_csv(outdir/'adaptive_gross100.csv',index=False)
    return bm,rows


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--legacy-dir',required=True); ap.add_argument('--legacy-state',required=True); ap.add_argument('--v2-features',required=True); ap.add_argument('--gross100',required=True); ap.add_argument('--tqqq',required=True); ap.add_argument('--output',required=True)
    a=ap.parse_args(); out=Path(a.output); out.mkdir(parents=True,exist_ok=True)
    # Dynamic Stage34 reconstruction, same lineage already validated by V6 against frozen V2.
    root=Path(a.legacy_dir).resolve(); cwd=os.getcwd(); sys.path.insert(0,str(root)); os.chdir(root)
    try:
        ns={}; src=Path('research/tqqq_stage36_goal_first_taxaware.py').read_text(); prefix=src.split('print("\\n=== STAGE36')[0]; exec(compile(prefix,'stage36-prefix','exec'),ns)
    finally:
        os.chdir(cwd); sys.path.pop(0)
    A=ns['A']; F=ns['F']; qqq=ns['qqq']; dates=norm(F['date'])
    dyn=pd.DataFrame(index=dates); dyn['nq_color']=pd.Series(np.asarray(A['nq'],int),index=dates).map(MAP); dyn['mc57']=np.asarray(A['mc'],float); dyn['mc_chg5']=dyn.mc57.diff(5)
    for k in ['panic','a200','a252','s50a','dd10']: dyn[k]=np.asarray(A[k])
    qc=pd.to_numeric(qqq.Close,errors='coerce').copy(); qc.index=norm(qc.index); qc=qc.reindex(dates); sma50=qc.rolling(50,min_periods=50).mean(); dyn['qqq_dist_sma50']=qc/sma50-1; dyn['sma50_slope10']=sma50.pct_change(10)
    dyn['core_mc']=dyn.nq_color.eq('Red')&(dyn.qqq_dist_sma50<0)&(dyn.sma50_slope10<0)&(dyn.mc_chg5<-3)
    frozen=pd.read_csv(a.legacy_state,compression='gzip',parse_dates=['date']).set_index('date').sort_index(); frozen.index=norm(frozen.index)
    tq=pd.read_csv(a.tqqq,compression='gzip',parse_dates=['date']).set_index('date').sort_index(); tq.index=norm(tq.index)
    exact_stage56=(tq.target_M30_TOUCH30_F80_D10>tq.target_CURRENT30+1e-9).reindex(dyn.index).fillna(False)
    touch,b4=hourly_touch30(); mf=market_features(dyn.index); vix=mf.vix
    approx56,seed=approximate_stage56(dyn,vix,touch)
    # Diagnostics of recent-hourly approximation against frozen exact Stage56 before using it after the freeze.
    vv=pd.DataFrame({'exact':exact_stage56,'approx':approx56}).loc['2025-01-01':FREEZE].dropna()
    act=vv.exact.astype(bool); app=vv.approx.astype(bool)
    stage_diag={'days':len(vv),'exact_match':float((act==app).mean()) if len(vv) else None,'exact_active_days':int(act.sum()),'approx_active_days':int(app.sum()),'active_recall':float((app&act).sum()/max(1,act.sum())),'active_precision':float((app&act).sum()/max(1,app.sum())),'bars4h':len(b4)}
    # Full reconstructed cooldown is used across the freeze boundary. Frozen events remain authoritative through 2026-03-20.
    rawcd=cooldown(dyn.core_mc,10); recent_guard=(approx56|dyn.panic.astype(bool)); recent_ev=rawcd & ~recent_guard
    all_ev=pd.Series(False,index=dyn.index); common=frozen.index.intersection(all_ev.index); all_ev.loc[common]=frozen.event.reindex(common).fillna(False).astype(bool); all_ev.loc[all_ev.index>FREEZE]=recent_ev.loc[recent_ev.index>FREEZE]
    # Check dynamic core/cooldown consistency over frozen history.
    ov=dyn.join(frozen[['core_mc','event']],how='inner',lsuffix='_dyn',rsuffix='_frozen')
    core_match=float(ov.core_mc_dyn.eq(ov.core_mc_frozen).mean())
    qret=qid_returns(dyn.index); rows=[]
    for i in np.flatnonzero(all_ev.to_numpy(bool)):
        z=qret.iloc[i+1:i+3]; q2=float(np.prod(1+z)-1) if len(z)==2 and z.notna().all() else np.nan
        rows.append({'signal_date':dyn.index[i],'qid2':q2,'period':'RECENT_OOS' if dyn.index[i]>=RECENT_START else ('PRE_2011_2015' if dyn.index[i]<=pd.Timestamp('2015-12-31') else 'POST_2016'),'guard_exact':bool(dyn.index[i]<=FREEZE),'stage56_approx_signal':bool(approx56.iloc[i]),'legacy_panic_signal':bool(dyn.panic.iloc[i])})
    ev=pd.DataFrame(rows).sort_values('signal_date').reset_index(drop=True)
    af=adaptive_flags(ev); ev=ev.merge(af,on='signal_date',how='left')
    ef=mf.reindex(pd.to_datetime(ev.signal_date)).reset_index(drop=True); ef.columns=[c if c!='index' else 'feature_date' for c in ef.columns]; ev=pd.concat([ev.reset_index(drop=True),ef.reset_index(drop=True)],axis=1)
    ev['G_STRUCT3']=ev.persist_score>=3; ev['G_STRUCT4']=ev.persist_score>=4; ev['G_STRUCT5']=ev.persist_score>=5
    ev['G_EWMA_STRUCT4']=ev.G_EWMA_HL3 & ev.G_STRUCT4
    ev.to_csv(out/'adaptive_event_ledger.csv',index=False)
    gates=['G_LAST3_MEAN','G_LAST5_MEAN','G_LAST5_MEDIAN','G_LAST5_WIN60','G_EWMA_HL3','G_TRAIL3Y_MEAN','G_STRUCT3','G_STRUCT4','G_STRUCT5','G_EWMA_STRUCT4']
    gs=[]
    periods={'ALL':(ev.signal_date.min(),ev.signal_date.max()),'PRE_2011_2015':(pd.Timestamp('2011-01-03'),pd.Timestamp('2015-12-31')),'POST_2016':(pd.Timestamp('2016-01-01'),ev.signal_date.max()),'POST_2022':(pd.Timestamp('2022-01-01'),ev.signal_date.max()),'POST_2024':(pd.Timestamp('2024-01-01'),ev.signal_date.max()),'RECENT_OOS':(RECENT_START,ev.signal_date.max())}
    for p,(aa,bb) in periods.items():
        z=ev[(ev.signal_date>=aa)&(ev.signal_date<=bb)].copy()
        for g in gates: gs.append({'period':p,**gate_summary(z,g)})
        base=pd.to_numeric(z.qid2,errors='coerce').dropna(); gs.append({'period':p,'gate':'UNGATED','events':len(base),'mean_qid2':float(base.mean()) if len(base) else np.nan,'median_qid2':float(base.median()) if len(base) else np.nan,'win':float((base>0).mean()) if len(base) else np.nan,'cum_qid30':float(np.prod(1+.30*base)-1) if len(base) else 0.})
    pd.DataFrame(gs).to_csv(out/'adaptive_gate_event_summary.csv',index=False)
    # Era diagnostics are descriptive, never used to pick a live cutoff.
    featcols=['persist_score','qqq_adx14','qqq_dmi_spread','qqq_ret20','qqq_ret63','qqq_rv20','vix','vix_chg10','hyg_lqd_mom20','rsp_spy_mom20','iwm_qqq_mom20','soxx_qqq_mom20','tlt_qqq_mom20','uup_ret20','DGS2','DGS10','DFII10','curve_2s10s','dgs2_chg5','real10_chg5','NFCI','BAMLH0A0HYM2','hy_oas_chg20','netliq_chg60_pct']
    er=[]
    for c in featcols:
        if c not in ev: continue
        a0=pd.to_numeric(ev.loc[ev.signal_date<=pd.Timestamp('2015-12-31'),c],errors='coerce').dropna(); b0=pd.to_numeric(ev.loc[(ev.signal_date>=pd.Timestamp('2016-01-01'))&(ev.signal_date<=FREEZE),c],errors='coerce').dropna()
        sp=np.sqrt(((len(a0)-1)*a0.var(ddof=1)+(len(b0)-1)*b0.var(ddof=1))/max(1,len(a0)+len(b0)-2)) if len(a0)>1 and len(b0)>1 else np.nan
        er.append({'feature':c,'old_n':len(a0),'new_n':len(b0),'old_mean':float(a0.mean()) if len(a0) else np.nan,'new_mean':float(b0.mean()) if len(b0) else np.nan,'old_median':float(a0.median()) if len(a0) else np.nan,'new_median':float(b0.median()) if len(b0) else np.nan,'cohen_d_new_minus_old':float((b0.mean()-a0.mean())/sp) if np.isfinite(sp) and sp>0 else np.nan})
    pd.DataFrame(er).sort_values('cohen_d_new_minus_old',key=lambda s:s.abs(),ascending=False).to_csv(out/'era_feature_differences.csv',index=False)
    # Feed only adaptive gate decisions into the already-audited Gross100 machinery through the frozen endpoint.
    gm=ev[['signal_date']+gates].copy(); gm['signal_date']=pd.to_datetime(gm.signal_date).dt.normalize(); bm,prows=portfolio_gate_test(a,gm,out)
    # Current monitor state uses only completed prior event outcomes; if the most recent event is incomplete, ignore it.
    complete=ev.dropna(subset=['qid2']).copy(); curflags=adaptive_flags(complete)
    current={}
    if len(complete):
        dummy=pd.DataFrame([{'signal_date':dyn.index.max()+pd.Timedelta(days=1),'qid2':np.nan}]); tmp=pd.concat([complete[['signal_date','qid2']],dummy],ignore_index=True); current=adaptive_flags(tmp).iloc[-1].to_dict()
    latest_features=mf.dropna(how='all').iloc[-1].to_dict() if len(mf.dropna(how='all')) else {}
    recent=ev[ev.signal_date>=RECENT_START].to_dict('records')
    summary={'status':'RESEARCH_ONLY_NO_PRODUCTION_CHANGE','dynamic_latest':str(dyn.index.max().date()),'frozen_end':str(FREEZE.date()),'core_daily_match_vs_frozen':core_match,'stage56_hourly_extension_diagnostic':stage_diag,'events_total':len(ev),'events_recent_oos':len(recent),'recent_oos':recent,'current_adaptive_monitor':current,'latest_market_features':latest_features,'gross100_baseline':bm,'notes':['Adaptive gates use only prior completed eligible-event QID outcomes; no calendar-era cutoff is used.','Market persistence score is pre-specified from trend/momentum/volatility/credit/breadth-proxy/semiconductor signs and is not fitted to QID returns.','Macro features are one-session-lagged diagnostics only and are not used as live gates in V9.','Post-freeze Stage56 guard is reconstructed from explicitly NY-timezone-converted Yahoo 60m QQQ bars; its overlap precision/recall versus frozen exact Stage56 is reported and limits confidence if weak.','No production/main/site files are changed.']}
    (out/'summary_v9.json').write_text(json.dumps(safe(summary),ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(safe(summary),ensure_ascii=False,indent=2),flush=True)

if __name__=='__main__': main()
