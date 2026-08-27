from __future__ import annotations
from pathlib import Path
import json, numpy as np, pandas as pd

# Reuse exact Stage17 source-data construction; risk-off side is unchanged.
src=Path('research/tqqq_stage17_hierarchy_crisis_fix.py').read_text()
prefix=src.split('NEW={')[0]
exec(compile(prefix,'stage17-prefix','exec'),globals())

print('\n=== STAGE23 BULL FLOOR SCREEN ===', flush=True)
YEARS=[2013,2017,2020,2021,2023,2024]
BASEP={'base':.30,'fast_dd':-.065,'fast_rec':4,'rg_slow':.50,'rg_fast':.80,'gb':.90,'rg_mc_slow':40,'cooldown':20,'panic':1.0}

def floor_nq_ok(nq,mode):
    if mode=='nonred': return nq!=0
    if mode=='green': return nq>=2
    if mode=='blue': return nq==3
    return np.ones(len(nq),bool)

def trace_variant(A,p):
    ret=A['ret']; mcv=A['mc']; nq=A['nq']; panic=A['panic']; a50=A['a50']; a63=A['a63']; a200=A['a200']; a252=A['a252']; gte10=A['gte10']; lte21=A['lte21']; s50x=A['s50a']; dd=A['dd10']
    n=len(ret); rawbear=(~a200)&(~a252)
    bear5=np.zeros(n,bool)
    for i in range(4,n): bear5[i]=rawbear[i-4:i+1].all()
    score3=(a50.astype(int)+a63.astype(int)+(mcv>=35).astype(int)+(nq!=0).astype(int))>=3
    fr=int(p['fast_rec']); rec=np.zeros(n,bool)
    for i in range(fr-1,n): rec[i]=gte10[i-fr+1:i+1].all()
    arm=np.empty(n,float)
    for i in range(n): arm[i]=np.min(s50x[max(0,i-19):i+1])

    slowA=np.zeros(n,bool); fastA=np.zeros(n,bool); mcA=np.zeros(n,bool)
    slow=fast=mclock=False
    for i in range(n):
        if bear5[i]: slow=True
        if slow and (not rawbear[i]) and score3[i] and mcv[i]>=35: slow=False
        if mcv[i]<25: mclock=True
        if mclock and mcv[i]>=35 and score3[i] and nq[i]!=0: mclock=False
        if dd[i]<=p['fast_dd'] and lte21[i]: fast=True
        if fast and rec[i]: fast=False
        slowA[i]=slow; fastA[i]=fast; mcA[i]=mclock
    risklock=slowA|fastA|mcA

    # Bull floor is allowed only after ALL risk locks are cleared.
    raw_floor=(~risklock)&a50&a63&(mcv>=p.get('floor_mc',999))&floor_nq_ok(nq,p.get('floor_nq','green'))
    cf=int(p.get('floor_confirm',1)); floor_ready=np.zeros(n,bool)
    if p.get('floor_exp',0)>0:
        for i in range(cf-1,n): floor_ready[i]=raw_floor[i-cf+1:i+1].all()

    base=np.zeros(n,float); strong=np.zeros(n,bool); panicA=np.zeros(n,bool)
    for i in range(n):
        x=0. if risklock[i] else p['base']
        if x>0 and floor_ready[i]: x=max(x,p.get('floor_exp',0.0))
        # Keep Strong Bull definition unchanged from current rule.
        if x>0 and mcv[i]>=65 and nq[i]==3 and a50[i] and a63[i] and s50x[i]<=2.5:
            x=1.0; strong[i]=True
        # Keep VIX panic-buy exception unchanged.
        if panic[i] and s50x[i]<=-2:
            x=max(x,p.get('panic',1.0)); panicA[i]=True
        base[i]=min(1.,x)

    # Same NQSAR tactical hierarchy as Stage17/20.
    t=base.copy(); active=0; entry=0; seen_blue=False; cool_until=0
    sleeve=np.zeros(n,np.int8)
    for i in range(1,n):
        trRG=nq[i-1]==0 and nq[i]==2; trGB=nq[i-1]==2 and nq[i]==3; trBG=nq[i-1]==3 and nq[i]==2; trBY=nq[i-1]==3 and nq[i]==1
        if active==0:
            rgmc=p['rg_mc_slow'] if slowA[i] else 35
            if trRG and arm[i]<=-2 and mcv[i]>=rgmc and risklock[i] and i>=cool_until:
                active=1; entry=i+1; seen_blue=False
            elif trGB and arm[i]<=-1.5 and mcv[i]>=35 and (not risklock[i]):
                active=2; entry=i+1; seen_blue=True
        if active==1:
            if nq[i]==3: seen_blue=True
            hold=max(0,i-(entry-1)); ex=((nq[i] in (0,1)) or hold>=7)
            if ex:
                if (not seen_blue) and slowA[i] and p['cooldown']>0: cool_until=i+p['cooldown']
                active=0
            else:
                if (not risklock[i]) and nq[i]==3:
                    active=2; entry=i+1; total=p['gb']
                else:
                    total=p['rg_slow'] if slowA[i] else p['rg_fast']
                if base[i]>=.999: total=1.
                t[i]=max(base[i],total); sleeve[i]=active
        elif active==2:
            hold=max(0,i-(entry-1)); ex=risklock[i] or trBG or trBY or nq[i]==0 or hold>=20
            if ex: active=0
            else:
                total=p['gb']
                if base[i]>=.999: total=1.
                t[i]=max(base[i],total); sleeve[i]=2

    eff=np.zeros(n); eff[2:]=t[:-2]
    turn=np.zeros(n); turn[2:]=np.abs(np.diff(t))[:-1]
    sr=eff*ret-turn*COST
    m=metrics(sr[2:]); m['avg_exp']=float(t.mean()); m['turnover']=float(np.abs(np.diff(t)).sum())
    return {'metrics':m,'target':t,'effective':eff,'strategy_ret':sr,'risklock':risklock,'strong':strong,'floor_ready':floor_ready,'slow':slowA,'fast':fastA,'mclock':mcA,'sleeve':sleeve}

def prodret(x):
    x=np.asarray(x,float); x=x[np.isfinite(x)]
    return float(np.prod(1+x)-1) if len(x) else np.nan

dates=pd.to_datetime(F.date).reset_index(drop=True)
qqq_close=qqq.Close.reindex(pd.DatetimeIndex(dates)).to_numpy(float)

def bull_capture(T):
    rows=[]
    for y in YEARS:
        ids=np.flatnonzero(dates.dt.year.to_numpy()==y)
        q=qqq_close[ids]; k0=int(np.nanargmin(q)); i0=int(ids[k0]); tail=qqq_close[i0:int(ids[-1])+1]; i1=i0+int(np.nanargmax(tail))
        if i1<=i0: i1=int(ids[-1])
        a=min(i0+1,len(dates)-1); b=min(i1,len(dates)-1); sl=slice(a,b+1)
        bh=prodret(A['ret'][sl]); st=prodret(T['strategy_ret'][sl]); eff=T['effective'][i0:i1+1]
        rows.append({'year':y,'bh':bh,'strategy':st,'capture':st/bh if bh>0 else np.nan,'avg_exp':float(np.mean(eff)),'pct_ge60':float(np.mean(eff>=.60)),'pct_ge70':float(np.mean(eff>=.70)),'pct_ge90':float(np.mean(eff>=.90)),'pct_100':float(np.mean(eff>=.999))})
    R=pd.DataFrame(rows)
    return R, {'bull_capture_median':float(R.capture.median()),'bull_capture_mean':float(R.capture.mean()),'bull_avg_exp_median':float(R.avg_exp.median()),'bull_pct_ge60_median':float(R.pct_ge60.median()),'bull_pct_ge90_median':float(R.pct_ge90.median()),'bull_pct_100_median':float(R.pct_100.median())}

CANDS={'CURRENT':{**BASEP,'floor_exp':0.0,'floor_mc':999,'floor_nq':'green','floor_confirm':1}}
for exp in (.50,.60,.70):
    for mc in (35,40):
        for nqmode in ('nonred','green'):
            for cf in (1,3):
                name=f"F{int(exp*100)}_MC{mc}_{'NR' if nqmode=='nonred' else 'G'}_C{cf}"
                CANDS[name]={**BASEP,'floor_exp':exp,'floor_mc':mc,'floor_nq':nqmode,'floor_confirm':cf}

hist=[]; caps=[]
for name,p in CANDS.items():
    T=trace_variant(A,p); bc,ag=bull_capture(T)
    hist.append({'candidate':name,**T['metrics'],**ag,'floor_days':int(T['floor_ready'].sum()),'strong_days':int(T['strong'].sum())})
    bc.insert(0,'candidate',name); caps.append(bc)
H=pd.DataFrame(hist); C=pd.concat(caps,ignore_index=True)
# Robust screen score: reward CAGR + bull capture, penalize DD beyond 23% and turnover.
H['screen_score']=H.cagr + .10*H.bull_capture_median - .80*np.maximum(0,(-H.mdd)-.23) - .00005*H.turnover
H=H.sort_values(['screen_score','cagr'],ascending=False)
H.to_csv('tqqq_stage23_screen.csv',index=False); C.to_csv('tqqq_stage23_bull_capture.csv',index=False)
print('\n=== TOP SCREEN ===')
print(H[['candidate','cagr','mdd','avg_exp','turnover','bull_capture_median','bull_capture_mean','bull_avg_exp_median','bull_pct_ge60_median','bull_pct_ge90_median','bull_pct_100_median','floor_days','strong_days','screen_score']].head(25).to_string(index=False))
print('\n=== BULL CAPTURE BY YEAR: TOP 8 ===')
for name in H.head(8).candidate:
    print('\n',name); print(C[C.candidate==name][['year','bh','strategy','capture','avg_exp','pct_ge60','pct_ge90','pct_100']].to_string(index=False))
Path('tqqq_stage23_summary.json').write_text(json.dumps({'years':YEARS,'candidates':CANDS,'screen':H.to_dict('records'),'note':'Stage23 changes only Bull-side exposure after all Slow/Fast/MC locks are cleared. Risk-off hierarchy, RG/GB rules, Strong Bull, and VIX panic buy are unchanged.'},ensure_ascii=False,indent=2,default=str))
