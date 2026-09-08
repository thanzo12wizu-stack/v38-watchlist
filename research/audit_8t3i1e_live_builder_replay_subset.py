from __future__ import annotations

import argparse, json, math
from pathlib import Path
import numpy as np
import pandas as pd

import build_v38_8t3i1e_live as live
import build_v38_sleeve_live as sleeve
from research import audit_stock_nqsar_theme30_pit as audit
from research import nqsar_centric_broad_scan as broad
from research import nqsar_hybrid_three_role_exact as hybrid

START=pd.Timestamp('2024-01-02'); END=pd.Timestamp('2026-09-04'); WARM='2011-08-01'


def safe(x):
    if isinstance(x,dict): return {str(k):safe(v) for k,v in x.items()}
    if isinstance(x,(list,tuple)): return [safe(v) for v in x]
    if isinstance(x,np.integer): return int(x)
    if isinstance(x,(np.floating,float)):
        z=float(x); return z if math.isfinite(z) else None
    if isinstance(x,pd.Timestamp): return str(x.date())
    return x


def pct(v,pool): return v.where(pool&v.notna()).rank(axis=1,pct=True,method='average')*100.0


def reference_subset(ohlcv,bio):
    h,l,c,v=(ohlcv[k] for k in ('high','low','close','volume'))
    ddv=c*v.rolling(20,min_periods=20).mean(); pool=(c>=5)&(ddv>=10_000_000.0)
    ex=[s for s in bio if s in pool.columns]
    if ex: pool.loc[:,ex]=False
    sma50=c.rolling(50,min_periods=50).mean(); sma200=c.rolling(200,min_periods=200).mean(); struct=pool&(sma50>sma200)&(c>sma200)
    q={p:pct(c/c.shift(p)-1,pool) for p in (21,42,63,189)}
    high=pct(c/c.shift(1).rolling(63,min_periods=40).max(),pool); acc=pct(q[21]-q[21].shift(20),pool); early=.50*q[21]+.25*high+.25*acc
    radar=(pool&((q[21]>=85)|(q[42]>=85)|(q[63]>=85))).fillna(False); fresh=(radar&~radar.shift(1).fillna(False)).fillna(False); active=fresh.astype(int).rolling(5,min_periods=1).max().astype(bool)
    wh,wl,wc=broad.period_ohlc(h,l,c,'W-FRI'); ws0=broad.exact_states(wh,wl,wc,30); wb=broad.to_daily(ws0,c.index).astype(np.int8)>=2
    return {'close':c,'ddv':ddv,'pool':pool,'struct':struct,'q':q,'early_score':early,'radar_active':active,'wb':wb}


def lv(m): return {'close':m['close'],'ddv':m['ddv'],'pool':m['pool'],'struct':m['struct'],'q':{21:m['q21'],42:m['q42'],63:m['q63'],189:m['q189']},'early_score':m['early_score'],'radar_active':m['radar_active'],'wb':m['weekly_bull']}


def engine_tests(rows):
    out={}
    out['market_mode']=(audit.mode('Blue',60)=='ATTACK' and audit.mode('Green',50)=='SELECTIVE' and audit.mode('Blue',49.9)=='STOP' and audit.mode('Yellow',80)=='STOP' and audit.mode('Red',80)=='DEFENSE')
    x=[{'ticker':f'X{i:02d}','final_rank':i,'daily_dollar_volume_m':10 if i==4 else 30} for i in range(1,16)]
    p=sleeve._normal_pending({'positions':[]},{'asof':'2026-09-04','market':{'mode':'ATTACK'},'candidates':x,'early1':{'status':'READY','entry_allowed_now':False,'candidates':[]}},{})
    core=[e['symbol'] for e in p['entries'] if e.get('sleeve')=='CORE']; out['top12_ddv20_no_refill']=len(core)==11 and 'X04' not in core and 'X13' not in core
    c=[{'ticker':r['ticker'],'final_rank':i,'daily_dollar_volume_m':30} for i,r in enumerate(rows[:12],1)]
    p=sleeve._normal_pending({'positions':[]},{'asof':'2026-09-04','market':{'mode':'SELECTIVE'},'candidates':c,'early1':{'status':'READY','entry_allowed_now':True,'candidates':[{'ticker':'EARLY_TEST','score':99,'rank':1}]}},{})
    co=[e for e in p['entries'] if e.get('sleeve')=='CORE']; ea=[e for e in p['entries'] if e.get('sleeve')=='EARLY']; out['selective_3_plus_1']=len(co)==3 and len(ea)==1; out['selective_first3_trend']=len(rows)>=3 and all(r.get('source')=='TREND' for r in rows[:3])
    return out


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--root',default='.'); ap.add_argument('--output',required=True); ap.add_argument('--batch-size',type=int,default=100); a=ap.parse_args(); root=Path(a.root); out=root/a.output; out.mkdir(parents=True,exist_ok=True)
    syms,bio=audit.load_universe(root/'universe.csv'); print('DOWNLOAD LONG WARM',flush=True); ohlcv,diag=audit.download_ohlcv(syms,WARM,'2026-09-05',a.batch_size)
    if float(diag.get('coverage') or 0)<.85: raise RuntimeError(diag)
    print('REFERENCE SUBSET',flush=True); ref=reference_subset(ohlcv,bio)
    print('DEDICATED LIVE',flush=True); lm=live.build_feature_frames(ohlcv,bio,END); livev=lv(lm); idx=ref['close'].index[(ref['close'].index>=START)&(ref['close'].index<=END)]; cols=ref['close'].columns.intersection(livev['close'].columns)
    frame={}
    for name,a1,b1 in [('pool',ref['pool'],livev['pool']),('struct',ref['struct'],livev['struct']),('radar',ref['radar_active'],livev['radar_active']),('weekly_bull',ref['wb'],livev['wb'])]:
        aa=a1.reindex(index=idx,columns=cols).fillna(False).astype(bool).to_numpy(); bb=b1.reindex(index=idx,columns=cols).fillna(False).astype(bool).to_numpy(); n=int((aa!=bb).sum()); frame[name]={'mismatches':n,'cells':int(aa.size),'pass':n==0}
    for p in (21,42,63,189):
        aa=ref['q'][p].reindex(index=idx,columns=cols).to_numpy(float); bb=livev['q'][p].reindex(index=idx,columns=cols).to_numpy(float); same=np.isclose(aa,bb,rtol=0,atol=1e-10,equal_nan=True); n=int((~same).sum()); frame[f'q{p}']={'mismatches':n,'cells':int(same.size),'pass':n==0}
    mism=[]; counts=[]; low189=0; low63=0; ddvfail=0; latest=[]
    for i,d0 in enumerate(idx,1):
        d=pd.Timestamp(d0); rr=hybrid.hybrid_rows(d,ref,'HYBRID8T3I_E1'); lr=live.candidate_rows(d,lm); rt=[x['ticker'] for x in rr]; lt=[x['ticker'] for x in lr]; rs=[x.get('source') for x in rr]; ls=[x.get('source') for x in lr]
        if rt!=lt or rs!=ls: mism.append({'date':str(d.date()),'reference':'|'.join(rt),'live':'|'.join(lt),'reference_sources':'|'.join(map(str,rs)),'live_sources':'|'.join(map(str,ls))})
        f=lr[:11]; counts.append({'date':str(d.date()),'trend':sum(x['source']=='TREND' for x in f),'ignition':sum(x['source']=='IGNITION' for x in f),'rows':len(lr)})
        for r in lr:
            s=r['ticker']; q189=livev['q'][189].at[d,s]; q63=livev['q'][63].at[d,s]
            low189+=bool(pd.notna(q189) and float(q189)<85); low63+=bool(pd.notna(q63) and float(q63)<85); ddvfail+=not bool(r.get('entry_ddv20_pass'))
        latest=lr
        if i%100==0 or i==len(idx): print('REPLAY',i,len(idx),'mismatch',len(mism),flush=True)
    state=live.build_state(ohlcv,bio,str(END.date()),diag); state_exact=[x['ticker'] for x in state['candidates']]==[x['ticker'] for x in latest] and [x['source'] for x in state['candidates']]==[x['source'] for x in latest]
    cal=live.nyse_sessions(START,END); ends=pd.Series(cal,index=cal.to_period('W-FRI')).groupby(level=0).max(); short=[]
    for d in [pd.Timestamp(x) for x in ends if pd.Timestamp(x).weekday()<4]:
        if d not in idx: continue
        rr=hybrid.hybrid_rows(d,ref,'HYBRID8T3I_E1'); lr=live.candidate_rows(d,lm); short.append({'date':str(d.date()),'match':[x['ticker'] for x in rr]==[x['ticker'] for x in lr] and [x.get('source') for x in rr]==[x.get('source') for x in lr]})
    tests=engine_tests(latest); cdf=pd.DataFrame(counts); allpass=all(v['pass'] for v in frame.values()) and not mism and state_exact and bool(short) and all(x['match'] for x in short) and all(tests.values()) and (low189>0 or low63>0)
    pd.DataFrame(mism).to_csv(out/'daily_replay_mismatches.csv',index=False); cdf.to_csv(out/'source_counts.csv',index=False); pd.DataFrame(short).to_csv(out/'shortened_weeks.csv',index=False); (out/'latest_live_state.json').write_text(json.dumps(safe(state),ensure_ascii=False,indent=2),encoding='utf-8')
    summary={'method':'Exact research subset vs dedicated live builder; warm 2011-08, replay 2024-01-02..2026-09-04. Reference subset uses the exact Broad weekly NQSAR/RS/structure formulas used by HYBRID8T3I_E1 and omits unrelated Daily/Monthly NQSAR computation only.','coverage':diag,'sessions':len(idx),'frame_checks':frame,'daily_mismatch_sessions':len(mism),'latest_state_exact':state_exact,'shortened_week_checks':short,'engine_tests':tests,'selected_rows_below_rs189_85':int(low189),'selected_rows_below_rs63_85':int(low63),'top12_rows_failing_ddv20_retained':int(ddvfail),'exact_8T3I_first11_sessions':int(((cdf.trend==8)&(cdf.ignition==3)).sum()),'other_mix_sessions':int((~((cdf.trend==8)&(cdf.ignition==3))).sum()),'audit_verdict':'PASS_FOR_PRODUCTION_CHANGE_PROPOSAL' if allpass else 'FAIL_NOT_READY','production_changed':False,'production_change_proposal_allowed':bool(allpass)}
    (out/'summary.json').write_text(json.dumps(safe(summary),ensure_ascii=False,indent=2),encoding='utf-8'); print('DONE',json.dumps(safe(summary),ensure_ascii=False),flush=True)
    if not allpass: raise RuntimeError('8T3I1E_REPLAY_FAIL')

if __name__=='__main__': main()
