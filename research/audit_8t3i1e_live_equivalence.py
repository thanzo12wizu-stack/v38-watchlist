from __future__ import annotations

import argparse, json, math
from pathlib import Path
import numpy as np
import pandas as pd

import build_dashboard as bd
import build_v38_sleeve_live as sleeve
import build_v38_early1_live as earlylive
from research import audit_stock_nqsar_theme30_pit as audit
from research import nqsar_centric_broad_scan as broad
from research import nqsar_hybrid_three_role_exact as hybrid

END = pd.Timestamp('2026-09-04')
START = pd.Timestamp('2024-01-02')
DDV_POOL = 10_000_000.0
PATTERN = ['T','T','T','I','T','T','T','I','T','T','I','T']


def safe(x):
    if isinstance(x, dict): return {str(k): safe(v) for k,v in x.items()}
    if isinstance(x, (list,tuple)): return [safe(v) for v in x]
    if isinstance(x, np.integer): return int(x)
    if isinstance(x, (np.floating,float)):
        z=float(x); return z if math.isfinite(z) else None
    if isinstance(x, pd.Timestamp): return str(x.date())
    return x


def pct(v, pool):
    return v.where(pool & v.notna()).rank(axis=1, pct=True, method='average') * 100.0


def features(ohlcv, bio):
    h,l,c,v=(ohlcv[k] for k in ('high','low','close','volume'))
    ddv=c*v.rolling(20,min_periods=20).mean(); pool=(c>=5.0)&(ddv>=DDV_POOL)
    ex=[s for s in bio if s in pool.columns]
    if ex: pool.loc[:,ex]=False
    sma50=c.rolling(50,min_periods=50).mean(); sma200=c.rolling(200,min_periods=200).mean(); struct=pool&(sma50>sma200)&(c>sma200)
    q21=pct(c/c.shift(21)-1,pool); q42=pct(c/c.shift(42)-1,pool); q63=pct(c/c.shift(63)-1,pool); q189=pct(c/c.shift(189)-1,pool)
    high63=pct(c/c.shift(1).rolling(63,min_periods=40).max(),pool); acc21=pct(q21-q21.shift(20),pool); early_score=.50*q21+.25*high63+.25*acc21
    radar=(pool&((q21>=85)|(q42>=85)|(q63>=85))).fillna(False); fresh=(radar&~radar.shift(1).fillna(False)).fillna(False); radar_active=fresh.astype(int).rolling(5,min_periods=1).max().astype(bool)
    wh,wl,wc=broad.period_ohlc(h,l,c,'W-FRI'); ws0=broad.exact_states(wh,wl,wc,30); wb=broad.to_daily(ws0,c.index).astype(np.int8)>=2
    return dict(high=h,low=l,close=c,ddv=ddv,pool=pool,struct=struct,sma50=sma50,sma200=sma200,q21=q21,q42=q42,q63=q63,q189=q189,early_score=early_score,radar_active=radar_active,wb=wb)


def reference_view(m):
    return dict(close=m['close'],ddv=m['ddv'],pool=m['pool'],struct=m['struct'],q={21:m['q21'],42:m['q42'],63:m['q63'],189:m['q189']},early_score=m['early_score'],radar_active=m['radar_active'],wb=m['wb'])


def independent_rows(d,m):
    pool=m['pool'].loc[d].fillna(False); struct=m['struct'].loc[d].fillna(False); wb=m['wb'].loc[d].fillna(False)
    q63=pd.to_numeric(m['q63'].loc[d],errors='coerce'); ddv=pd.to_numeric(m['ddv'].loc[d],errors='coerce')
    trend=q63.where(pool&struct&wb).dropna().sort_values(ascending=False).index.tolist()
    ign=pd.to_numeric(m['early_score'].loc[d],errors='coerce').where(pool&wb&m['radar_active'].loc[d].fillna(False)).dropna().sort_values(ascending=False).index.tolist()
    lists={'T':trend,'I':ign}; ptr={'T':0,'I':0}; chosen=[]; sources=[]
    for src in PATTERN:
        arr=lists[src]
        while ptr[src]<len(arr) and arr[ptr[src]] in chosen: ptr[src]+=1
        if ptr[src]>=len(arr): continue
        s=arr[ptr[src]]; ptr[src]+=1; chosen.append(s); sources.append(src)
    return [{'ticker':str(s),'source':'IGNITION' if src=='I' else 'TREND','daily_dollar_volume_m':float(ddv.get(s,np.nan))/1e6 if pd.notna(ddv.get(s,np.nan)) else None} for s,src in zip(chosen[:12],sources[:12])]


def state_one_weekly_asof(h,l,c,sym,d,calendar):
    z=pd.DataFrame({'h':h[sym],'l':l[sym],'c':c[sym]}).dropna(); z=z.loc[z.index<=d]
    if z.empty: return None
    curp=pd.Timestamp(d).to_period('W-FRI'); later=calendar[(calendar>d)&(calendar.to_period('W-FRI')==curp)]
    if len(later): z=z.loc[z.index.to_period('W-FRI')<curp]
    if z.empty: return None
    p=z.index.to_period('W-FRI'); hh=z.h.groupby(p).max(); ll=z.l.groupby(p).min(); cc=z.c.groupby(p).last()
    if len(cc)<30: return None
    hv=hh.to_numpy(float); lv=ll.to_numpy(float); cv=cc.to_numpy(float); sar=bd._psar(hv,lv,cv,step=.02,mx=.08)
    ema=pd.Series(cv).ewm(span=21,adjust=False).mean().to_numpy(float); ds=pd.Series(cv).diff(); up=ds.clip(lower=0); dn=-ds.clip(upper=0)
    ru=up.ewm(alpha=1/14,adjust=False).mean(); rd=dn.ewm(alpha=1/14,adjust=False).mean(); rsi=(100.0-100.0/(1.0+ru/rd.replace(0,np.nan))).to_numpy(float)
    bd._onimine_state(cv,sar,ema,rsi); colors=list(bd._LAST_ONIMINE_SERIES or [])
    return str(colors[-1]) in {'Blue','Green'} if colors else None


def engine_tests(sample_rows):
    out={}
    out['market_mode']=(audit.mode('Blue',60)=='ATTACK' and audit.mode('Green',50)=='SELECTIVE' and audit.mode('Blue',49.99)=='STOP' and audit.mode('Yellow',80)=='STOP' and audit.mode('Red',80)=='DEFENSE')
    rows=[{'ticker':f'X{i:02d}','final_rank':i,'daily_dollar_volume_m':10.0 if i==4 else 30.0} for i in range(1,16)]
    p=sleeve._normal_pending({'positions':[]},{'asof':'2026-09-04','market':{'mode':'ATTACK'},'candidates':rows,'early1':{'status':'READY','entry_allowed_now':False,'candidates':[]}},{})
    core=[x['symbol'] for x in p['entries'] if x.get('sleeve')=='CORE']; out['top12_ddv20_no_refill']=('X04' not in core and 'X13' not in core and len(core)==11)
    base=sample_rows[:12]; crows=[{'ticker':r['ticker'],'final_rank':i,'daily_dollar_volume_m':30.0} for i,r in enumerate(base,1)]
    p=sleeve._normal_pending({'positions':[]},{'asof':'2026-09-04','market':{'mode':'SELECTIVE'},'candidates':crows,'early1':{'status':'READY','entry_allowed_now':True,'candidates':[{'ticker':'EARLY_TEST','score':99,'rank':1}]}},{})
    cores=[x['symbol'] for x in p['entries'] if x.get('sleeve')=='CORE']; early=[x['symbol'] for x in p['entries'] if x.get('sleeve')=='EARLY']
    out['selective_3_plus_1']=(len(cores)==3 and len(early)==1 and early[0]=='EARLY_TEST'); out['selective_first3_are_trend']=len(base)>=3 and all(str(r.get('source'))=='TREND' for r in base[:3])
    pos=[{'symbol':'STOP','shares':1.0,'entry_price':100.0,'entry_date':'2026-01-01','peak_close':100.0,'partial_done':False,'sleeve':'CORE','early_sessions':0},{'symbol':'PART','shares':1.0,'entry_price':100.0,'entry_date':'2026-01-01','peak_close':124.0,'partial_done':False,'sleeve':'CORE','early_sessions':0},{'symbol':'TRAIL','shares':1.0,'entry_price':100.0,'entry_date':'2026-01-01','peak_close':200.0,'partial_done':True,'sleeve':'CORE','early_sessions':0},{'symbol':'EARLYX','shares':1.0,'entry_price':100.0,'entry_date':'2026-01-01','peak_close':105.0,'partial_done':False,'sleeve':'EARLY','early_sessions':10}]
    p=sleeve._normal_pending({'positions':pos},{'asof':'2026-09-04','market':{'mode':'ATTACK'},'candidates':[],'early1':{'status':'READY','entry_allowed_now':False,'candidates':[]}},{'STOP':92.0,'PART':124.0,'TRAIL':140.0,'EARLYX':101.0})
    ex={x['symbol']:x['reason'] for x in p['full_exits']}; par={x['symbol'] for x in p['partial25']}; out['exit_minus8_close']=ex.get('STOP')=='INITIAL_OR_PEAK30_STOP'; out['partial_plus24']=('PART' in par); out['winner_peak30']=ex.get('TRAIL')=='INITIAL_OR_PEAK30_STOP'; out['early_d10_expiry']=ex.get('EARLYX')=='EARLY_EXPIRY_D10'
    return out


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--root',default='.'); ap.add_argument('--output',required=True); ap.add_argument('--batch-size',type=int,default=100); a=ap.parse_args(); root=Path(a.root); out=root/a.output; out.mkdir(parents=True,exist_ok=True)
    symbols,bio=audit.load_universe(root/'universe.csv'); print('DOWNLOAD',flush=True); ohlcv,diag=audit.download_ohlcv(symbols,'2022-01-01','2026-09-05',a.batch_size)
    if diag['coverage']<.85: raise RuntimeError(diag)
    print('BUILD FEATURES + WEEKLY NQSAR',flush=True); m=features(ohlcv,bio); ref=reference_view(m); idx=ref['close'].index[(ref['close'].index>=START)&(ref['close'].index<=END)]
    mism=[]; source_mism=[]; latest_rows=[]
    for n,d0 in enumerate(idx):
        d=pd.Timestamp(d0); rr=hybrid.hybrid_rows(d,ref,'HYBRID8T3I_E1'); ii=independent_rows(d,m); rt=[x['ticker'] for x in rr]; it=[x['ticker'] for x in ii]; rs=[x.get('source') for x in rr]; isrc=[x.get('source') for x in ii]
        if rt!=it: mism.append({'date':d,'reference':'|'.join(rt),'independent':'|'.join(it)})
        if rs!=isrc: source_mism.append({'date':d,'reference':'|'.join(map(str,rs)),'independent':'|'.join(map(str,isrc))})
        latest_rows=ii
    calendar=pd.DatetimeIndex(ref['close'].index); samples=list(pd.Series(idx,index=idx.to_period('M')).groupby(level=0).max().values)
    for x in ('2024-03-28','2025-07-03','2026-04-02','2026-07-02'):
        t=pd.Timestamp(x)
        if t in idx: samples.append(t)
    samples=sorted(set(pd.Timestamp(x) for x in samples)); weekly_checks=[]; h,l,c=ohlcv['high'],ohlcv['low'],ohlcv['close']; rng=np.random.default_rng(20260908)
    for d in samples:
        rr=hybrid.hybrid_rows(d,ref,'HYBRID8T3I_E1'); syms=[x['ticker'] for x in rr[:12]]; pool=list(ref['pool'].columns[ref['pool'].loc[d].fillna(False)])
        if pool: syms += list(rng.choice(pool,size=min(5,len(pool)),replace=False))
        for s in dict.fromkeys(syms):
            pit=state_one_weekly_asof(h,l,c,s,d,calendar); r=bool(ref['wb'].at[d,s]) if s in ref['wb'].columns else None
            if pit is not None: weekly_checks.append({'date':d,'ticker':s,'reference_bull':r,'pit_bull':pit,'match':r==pit})
    wc=pd.DataFrame(weekly_checks); cal=calendar[(calendar>=START)&(calendar<=END)]; ends=pd.DataFrame({'d':cal,'p':cal.to_period('W-FRI')}).groupby('p')['d'].max(); shortened=[str(pd.Timestamp(d).date()) for d in ends if pd.Timestamp(d).weekday()<4]
    allowed=earlylive._industry_symbols(root/'industry_map.json'); latest=pd.Timestamp(idx[-1]); latest_ref=hybrid.hybrid_rows(latest,ref,'HYBRID8T3I_E1'); core_outside_allowed=[x['ticker'] for x in latest_ref if allowed and x['ticker'] not in allowed]
    tests=engine_tests(latest_rows); eq_pass=(len(mism)==0 and len(source_mism)==0); pit_pass=(not wc.empty and bool(wc['match'].all())); engine_pass=all(bool(v) for v in tests.values()); live_exists=(root/'build_v38_8t3i1e_live.py').is_file()
    legacy_elig=m['pool']&(m['sma50']>m['sma200'])&(m['close']>m['sma200'])&(m['q63']>=85)&(m['q189']>=85); intended=set(pd.to_numeric(ref['q'][63].loc[latest],errors='coerce').where(ref['pool'].loc[latest]&ref['struct'].loc[latest]&ref['wb'].loc[latest]).dropna().index); legacy_week=set(legacy_elig.index[legacy_elig.loc[latest].fillna(False)&m['wb'].loc[latest].fillna(False)]); legacy_missing=sorted(intended-legacy_week)
    pd.DataFrame(mism).to_csv(out/'candidate_mismatches.csv',index=False); pd.DataFrame(source_mism).to_csv(out/'source_mismatches.csv',index=False); wc.to_csv(out/'weekly_pit_checks.csv',index=False)
    summary={'method':'2024-2026 full-session 8T3I candidate replay plus independent PIT weekly rebuild at every month-end and shortened-week probes; current sleeve invariant tests.','coverage':diag,'sessions_compared':len(idx),'candidate_mismatch_sessions':len(mism),'source_mismatch_sessions':len(source_mism),'candidate_equivalence_pass':eq_pass,'weekly_pit_checks':len(wc),'weekly_pit_mismatches':int((~wc['match']).sum()) if not wc.empty else None,'weekly_no_lookahead_pass':pit_pass,'engine_tests':tests,'engine_invariants_pass':engine_pass,'shortened_week_last_sessions':shortened,'shortened_week_count':len(shortened),'early_industry_allowed_count':len(allowed),'latest_core_candidates_outside_early_industry_map':core_outside_allowed,'core_industry_map_leak_absent':bool(core_outside_allowed) if allowed else True,'current_dedicated_8t3i1e_live_builder_exists':live_exists,'legacy_generic_eligibility_missing_intended_trend_count_latest':len(legacy_missing),'legacy_generic_eligibility_missing_examples':legacy_missing[:20],'implementation_blockers':[x for x in [None if eq_pass else 'candidate reconstruction mismatch',None if pit_pass else 'weekly PIT timing mismatch',None if engine_pass else 'existing sleeve invariant mismatch','dedicated 8T3I1E live candidate builder not yet present' if not live_exists else None,'do not reuse legacy build_stock_inputs eligible: it hard-gates RS63 and RS189 >=85' if legacy_missing else None,'live weekly release must use known NYSE trading calendar so shortened Friday-holiday weeks release after the actual final session' if shortened else None] if x],'audit_verdict':'IMPLEMENTABLE_AFTER_GUARDED_LIVE_PORT' if eq_pass and pit_pass and engine_pass else 'NOT_READY','production_changed':False}
    (out/'summary.json').write_text(json.dumps(safe(summary),ensure_ascii=False,indent=2),encoding='utf-8'); print('DONE',json.dumps(safe(summary),ensure_ascii=False),flush=True)

if __name__=='__main__': main()
