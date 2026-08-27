from __future__ import annotations
from pathlib import Path
import json, numpy as np, pandas as pd

# Reuse Stage24 trace because it exposes exact current target, risk locks, and tactical GB state.
src=Path('research/tqqq_stage24_smart_bull_continuation.py').read_text()
prefix=src.split("CANDS={'CURRENT'")[0]
exec(compile(prefix,'stage24-prefix','exec'),globals())
print('\n=== STAGE30 DUAL BULL REGIMES ===',flush=True)

P0={'base':.30,'fast_dd':-.065,'fast_rec':4,'rg_slow':.50,'rg_fast':.80,'gb':.90,'rg_mc_slow':40,'cooldown':20,'panic':1.0,'latch_exp':0,'latch_mc':999,'latch_confirm':3,'ext_exp':0,'ext_mc':35,'ext_max':40}
CUR=trace_smart(A,P0); base_t=CUR['target'].copy(); risklock=CUR['risklock'].copy(); sleeve=CUR['sleeve'].copy(); n=len(base_t)
MC=A['mc']; nq=A['nq']; a50=A['a50']; a63=A['a63']; a200=A['a200']; lte21=A['lte21']

# Point-in-time QQQ maturity features.
qc=qqq.Close.astype(float); qr=qc.pct_change(); rv20=qr.rolling(20).std()*np.sqrt(252); s50q=qc.rolling(50).mean(); s200q=qc.rolling(200).mean(); sl50=s50q/s50q.shift(20)-1; sl200=s200q/s200q.shift(20)-1
idx_dates=pd.DatetimeIndex(dates); align=lambda s:s.reindex(idx_dates).ffill().to_numpy(float)
RV=align(rv20); SL50=align(sl50); SL200=align(sl200)
# Days since latest risk lock in the actual state machine.
DS=np.full(n,999,dtype=int); last=-999
for i in range(n):
    if risklock[i]: last=i; DS[i]=0
    else: DS[i]=i-last if last>-900 else 999
# TQQQ close and EMA10 for profit-funded runner.
tqc=tq.Close.astype(float); tqe10=tqc.ewm(span=10,adjust=False).mean(); TQC=align(tqc); TQ10=(tqc>tqe10).reindex(idx_dates).ffill().fillna(False).to_numpy(bool)

# GB spell extraction from the exact current tactical sleeve.
spells=[]; i=0
while i<n:
    if sleeve[i]!=2: i+=1; continue
    a=i
    while i+1<n and sleeve[i+1]==2: i+=1
    b=i; spells.append((a,b,b-a+1,float(TQC[b]/TQC[a]-1) if TQC[a]>0 else np.nan)); i+=1
print('GB spells',len(spells),'long>=15',sum(1 for x in spells if x[2]>=15),flush=True)

def run_variant(p):
    t=base_t.copy(); mature=np.zeros(n,bool); runner=np.zeros(n,bool)
    # A) Mature Bull floor: only after a long period with no risk lock and a calm, upward long-term structure.
    if p.get('mat_exp',0)>0:
        raw=(~risklock)&a200&a50&a63&(~lte21)&(nq!=0)&(MC>=35)&(DS>=p['mat_days'])&(RV<p['mat_rv'])&(SL50>0)&(SL200>0)
        cf=3; ready=np.zeros(n,bool)
        for k in range(cf-1,n): ready[k]=raw[k-cf+1:k+1].all()
        mature=ready; t[ready]=np.maximum(t[ready],p['mat_exp'])
    # B) Recovery runner: only after an EXISTING tactical GB has already lasted and earned enough profit.
    if p.get('run_exp',0)>0:
        for a,b,dur,gain in spells:
            if dur<p['run_min_days'] or not np.isfinite(gain) or gain<p['run_gain']: continue
            age=0
            for k in range(b+1,min(n,b+1+p['run_max'])):
                bad=risklock[k] or nq[k]==0 or (not a200[k]) or (not a50[k]) or (not a63[k]) or (not TQ10[k])
                if bad: break
                t[k]=max(t[k],p['run_exp']); runner[k]=True; age+=1
    eff=np.zeros(n); eff[2:]=t[:-2]; turn=np.zeros(n); turn[2:]=np.abs(np.diff(t))[:-1]; sr=eff*A['ret']-turn*COST
    m=metrics(sr[2:]); m['avg_exp']=float(t.mean()); m['turnover']=float(np.abs(np.diff(t)).sum()); m['mature_days']=int(mature.sum()); m['runner_days']=int(runner.sum())
    y=dates.dt.year.to_numpy(); mi=metrics_window(sr,y<=2018); mo=metrics_window(sr,y>=2019); m.update({'is_cagr':mi['cagr'],'is_mdd':mi['mdd'],'oos_cagr':mo['cagr'],'oos_mdd':mo['mdd']})
    eq=np.cumprod(1+np.nan_to_num(sr,nan=0.)); pk=np.maximum.accumulate(eq); dd=eq/pk-1; j=int(np.argmin(dd)); ii=int(np.argmax(eq[:j+1])); m['dd_peak']=str(dates.iloc[ii].date()); m['dd_trough']=str(dates.iloc[j].date())
    return {'target':t,'effective':eff,'strategy_ret':sr,'metrics':m,'mature':mature,'runner':runner}

def cap(T): return bull_capture(T)

CANDS={'CURRENT':{'mat_exp':0,'run_exp':0}}
# Mature clean Bull alone.
for ex in (.50,.60,.70):
    for d in (60,90):
        CANDS[f'M{int(ex*100)}_D{d}']={'mat_exp':ex,'mat_days':d,'mat_rv':.25,'run_exp':0}
# Profit-funded recovery runner alone.
for ex in (.60,.70):
    for gain in (.10,.15):
        for mx in (40,60):
            CANDS[f'R{int(ex*100)}_G{int(gain*100)}_M{mx}']={'mat_exp':0,'run_exp':ex,'run_gain':gain,'run_min_days':15,'run_max':mx}
# Small set of hybrids; no additional thresholds.
for mex,md,rex,rg,rm in [(.50,60,.60,.10,40),(.60,60,.60,.10,40),(.50,90,.60,.10,60),(.60,90,.60,.10,60),(.50,60,.70,.10,40),(.50,60,.60,.15,60)]:
    CANDS[f'H_M{int(mex*100)}D{md}_R{int(rex*100)}G{int(rg*100)}M{rm}']={'mat_exp':mex,'mat_days':md,'mat_rv':.25,'run_exp':rex,'run_gain':rg,'run_min_days':15,'run_max':rm}

rows=[]; caps=[]
R0,ag0=cap(CUR); rows.append({'candidate':'CURRENT',**CUR['metrics'],**ag0,'mature_days':0,'runner_days':0,'dd_peak':'','dd_trough':''}); R0.insert(0,'candidate','CURRENT'); caps.append(R0)
for name,p in CANDS.items():
    if name=='CURRENT': continue
    T=run_variant(p); R,ag=cap(T); rows.append({'candidate':name,**T['metrics'],**ag}); R.insert(0,'candidate',name); caps.append(R)
H=pd.DataFrame(rows); C=pd.concat(caps,ignore_index=True)
H['acceptable']=(H.mdd>=-.23)&(H.cagr>=.276)&(H.bull_capture_median>=.37)
H['score']=H.cagr+.20*H.bull_capture_median-1.8*np.maximum(0,(-H.mdd)-.22)-.00005*H.turnover
H=H.sort_values(['acceptable','score','cagr'],ascending=False); H.to_csv('tqqq_stage30_screen.csv',index=False); C.to_csv('tqqq_stage30_bull_capture.csv',index=False)
print('\n=== DUAL BULL SCREEN ==='); print(H[['candidate','cagr','mdd','is_cagr','is_mdd','oos_cagr','oos_mdd','avg_exp','turnover','bull_capture_median','bull_capture_mean','bull_avg_exp_median','mature_days','runner_days','dd_peak','dd_trough','acceptable','score']].to_string(index=False))
print('\n=== TOP BULL YEARS ===')
for nm in H.head(10).candidate:
    print('\n',nm); print(C[C.candidate==nm][['year','bh','strategy','capture','avg_exp','pct_ge50','pct_ge60','pct_ge70','pct_ge90']].to_string(index=False))
print('\n=== GB SPELLS >=15D ===')
for a,b,d,g in spells:
    if d>=15: print(str(dates.iloc[a].date()),str(dates.iloc[b].date()),d,round(g,4))
Path('tqqq_stage30_summary.json').write_text(json.dumps({'candidates':CANDS,'screen':H.to_dict('records'),'spells':[{'start':str(dates.iloc[a].date()),'end':str(dates.iloc[b].date()),'days':d,'gain':g} for a,b,d,g in spells],'note':'Dual-regime Bull study. Mature floor requires >=60/90 days since last risk lock, no current lock, QQQ above SMA200/SMA50/VWAP63/EMA21, NQSAR non-Red, MC>=35, RV20<25%, and positive 20d slopes of SMA50/SMA200. Recovery runner is allowed only after the existing GB90 sleeve has already lasted >=15 days and earned >=10/15%; it exits on TQQQ EMA10 or risk/structure failure. Risk side is unchanged.'},ensure_ascii=False,indent=2,default=str))
