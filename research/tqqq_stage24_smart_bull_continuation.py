from __future__ import annotations
from pathlib import Path
import json, numpy as np, pandas as pd

src=Path('research/tqqq_stage17_hierarchy_crisis_fix.py').read_text()
prefix=src.split('NEW={')[0]
exec(compile(prefix,'stage17-prefix','exec'),globals())
print('\n=== STAGE24 SMART BULL CONTINUATION ===',flush=True)
YEARS=[2013,2017,2020,2021,2023,2024]
BASEP={'base':.30,'fast_dd':-.065,'fast_rec':4,'rg_slow':.50,'rg_fast':.80,'gb':.90,'rg_mc_slow':40,'cooldown':20,'panic':1.0}
dates=pd.to_datetime(F.date).reset_index(drop=True); qqq_close=qqq.Close.reindex(pd.DatetimeIndex(dates)).to_numpy(float)

def metrics_window(sr,mask):
    x=np.asarray(sr,float)[mask]; x=x[np.isfinite(x)]
    return metrics(x) if len(x)>10 else {'cagr':np.nan,'mdd':np.nan,'end':np.nan}

def trace_smart(A,p):
    ret=A['ret']; mcv=A['mc']; nq=A['nq']; panic=A['panic']; a50=A['a50']; a63=A['a63']; a200=A['a200']; a252=A['a252']; gte10=A['gte10']; lte21=A['lte21']; s50x=A['s50a']; dd=A['dd10']
    n=len(ret); rawbear=(~a200)&(~a252); bear5=np.zeros(n,bool)
    for i in range(4,n): bear5[i]=rawbear[i-4:i+1].all()
    score3=(a50.astype(int)+a63.astype(int)+(mcv>=35).astype(int)+(nq!=0).astype(int))>=3
    fr=int(p['fast_rec']); rec=np.zeros(n,bool)
    for i in range(fr-1,n): rec[i]=gte10[i-fr+1:i+1].all()
    arm=np.empty(n,float)
    for i in range(n): arm[i]=np.min(s50x[max(0,i-19):i+1])
    slowA=np.zeros(n,bool); fastA=np.zeros(n,bool); mcA=np.zeros(n,bool); slow=fast=mclock=False
    for i in range(n):
        if bear5[i]: slow=True
        if slow and (not rawbear[i]) and score3[i] and mcv[i]>=35: slow=False
        if mcv[i]<25: mclock=True
        if mclock and mcv[i]>=35 and score3[i] and nq[i]!=0: mclock=False
        if dd[i]<=p['fast_dd'] and lte21[i]: fast=True
        if fast and rec[i]: fast=False
        slowA[i]=slow; fastA[i]=fast; mcA[i]=mclock
    risklock=slowA|fastA|mcA

    # Smart Bull latch: stronger structure than Stage23 broad floor.
    raw_latch=(~risklock)&a200&a50&a63&(~lte21)&(mcv>=p.get('latch_mc',999))&(nq!=0)
    if p.get('latch_need_ema10',False): raw_latch &= gte10
    lc=int(p.get('latch_confirm',3)); latch_ready=np.zeros(n,bool)
    if p.get('latch_exp',0)>0:
        for i in range(lc-1,n): latch_ready[i]=raw_latch[i-lc+1:i+1].all()

    base=np.zeros(n,float); strong=np.zeros(n,bool); panicA=np.zeros(n,bool)
    for i in range(n):
        x=0. if risklock[i] else p['base']
        if x>0 and latch_ready[i]: x=max(x,p.get('latch_exp',0.0))
        if x>0 and mcv[i]>=65 and nq[i]==3 and a50[i] and a63[i] and s50x[i]<=2.5:
            x=1.; strong[i]=True
        if panic[i] and s50x[i]<=-2:
            x=max(x,p.get('panic',1.)); panicA[i]=True
        base[i]=min(1.,x)

    t=base.copy(); active=0; entry=0; seen_blue=False; cool_until=0; ext_entry=0
    sleeve=np.zeros(n,np.int8) # 1 RG, 2 GB, 3 GB continuation
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
                else: total=p['rg_slow'] if slowA[i] else p['rg_fast']
                if base[i]>=.999: total=1.
                t[i]=max(base[i],total); sleeve[i]=active
        elif active==2:
            hold=max(0,i-(entry-1)); bad=risklock[i] or trBG or trBY or nq[i]==0
            if bad: active=0
            elif hold>=20:
                # Only after a proven 20d GB run, optionally downgrade into a continuation sleeve.
                cont_ok=(not risklock[i]) and a200[i] and a50[i] and a63[i] and (not lte21[i]) and nq[i]!=0 and mcv[i]>=p.get('ext_mc',35)
                if p.get('ext_exp',0)>0 and cont_ok:
                    active=3; ext_entry=i; total=p['ext_exp']; t[i]=max(base[i],total); sleeve[i]=3
                else: active=0
            else:
                total=p['gb'];
                if base[i]>=.999: total=1.
                t[i]=max(base[i],total); sleeve[i]=2
        elif active==3:
            ext_hold=i-ext_entry
            bad=risklock[i] or nq[i]==0 or lte21[i] or (not a200[i]) or (not a50[i]) or (not a63[i]) or mcv[i]<p.get('ext_mc',35) or ext_hold>=p.get('ext_max',40)
            if bad: active=0
            else:
                total=p['ext_exp'];
                if base[i]>=.999: total=1.
                t[i]=max(base[i],total); sleeve[i]=3

    eff=np.zeros(n); eff[2:]=t[:-2]; turn=np.zeros(n); turn[2:]=np.abs(np.diff(t))[:-1]; sr=eff*ret-turn*COST
    m=metrics(sr[2:]); m['avg_exp']=float(t.mean()); m['turnover']=float(np.abs(np.diff(t)).sum())
    ismask=(dates.dt.year.to_numpy()<=2018); oosmask=(dates.dt.year.to_numpy()>=2019)
    mi=metrics_window(sr,ismask); mo=metrics_window(sr,oosmask)
    m.update({'is_cagr':mi['cagr'],'is_mdd':mi['mdd'],'oos_cagr':mo['cagr'],'oos_mdd':mo['mdd']})
    return {'metrics':m,'target':t,'effective':eff,'strategy_ret':sr,'risklock':risklock,'strong':strong,'latch':latch_ready,'sleeve':sleeve}

def prodret(x):
    x=np.asarray(x,float); x=x[np.isfinite(x)]; return float(np.prod(1+x)-1) if len(x) else np.nan

def bull_capture(T):
    rows=[]
    for y in YEARS:
        ids=np.flatnonzero(dates.dt.year.to_numpy()==y); q=qqq_close[ids]; i0=int(ids[int(np.nanargmin(q))]); tail=qqq_close[i0:int(ids[-1])+1]; i1=i0+int(np.nanargmax(tail)); i1=int(ids[-1]) if i1<=i0 else i1
        sl=slice(min(i0+1,len(dates)-1),min(i1,len(dates)-1)+1); bh=prodret(A['ret'][sl]); st=prodret(T['strategy_ret'][sl]); eff=T['effective'][i0:i1+1]
        rows.append({'year':y,'bh':bh,'strategy':st,'capture':st/bh if bh>0 else np.nan,'avg_exp':float(np.mean(eff)),'pct_ge50':float(np.mean(eff>=.50)),'pct_ge60':float(np.mean(eff>=.60)),'pct_ge70':float(np.mean(eff>=.70)),'pct_ge90':float(np.mean(eff>=.90))})
    R=pd.DataFrame(rows); return R, {'bull_capture_median':float(R.capture.median()),'bull_capture_mean':float(R.capture.mean()),'bull_avg_exp_median':float(R.avg_exp.median())}

CANDS={'CURRENT':{**BASEP,'latch_exp':0,'latch_mc':999,'latch_confirm':3,'ext_exp':0,'ext_mc':35,'ext_max':40}}
# Targeted GB continuation only.
for ex in (.50,.60,.70):
    for mx in (40,60): CANDS[f'E{int(ex*100)}_M{mx}']={**BASEP,'latch_exp':0,'latch_mc':999,'latch_confirm':3,'ext_exp':ex,'ext_mc':35,'ext_max':mx}
# Strong-structure Bull latch; no broad Bull floor.
for lx in (.50,.60,.70):
    CANDS[f'L{int(lx*100)}_21_C3']={**BASEP,'latch_exp':lx,'latch_mc':35,'latch_confirm':3,'latch_need_ema10':False,'ext_exp':0,'ext_mc':35,'ext_max':40}
    CANDS[f'L{int(lx*100)}_10_C3']={**BASEP,'latch_exp':lx,'latch_mc':35,'latch_confirm':3,'latch_need_ema10':True,'ext_exp':0,'ext_mc':35,'ext_max':40}
# Conservative hybrids: modest structure latch plus GB continuation.
for lx,ex in ((.50,.50),(.50,.60),(.60,.50)):
    CANDS[f'H_L{int(lx*100)}_E{int(ex*100)}']={**BASEP,'latch_exp':lx,'latch_mc':35,'latch_confirm':3,'latch_need_ema10':False,'ext_exp':ex,'ext_mc':35,'ext_max':40}

hist=[]; caps=[]
for name,p in CANDS.items():
    T=trace_smart(A,p); R,ag=bull_capture(T); hist.append({'candidate':name,**T['metrics'],**ag,'latch_days':int(T['latch'].sum()),'ext_days':int(np.sum(T['sleeve']==3))}); R.insert(0,'candidate',name); caps.append(R)
H=pd.DataFrame(hist); C=pd.concat(caps,ignore_index=True)
# Do not reward solutions that buy Bull capture by blowing out MDD.
H['score']=H.cagr + .12*H.bull_capture_median - 1.2*np.maximum(0,(-H.mdd)-.23) - .00005*H.turnover
H=H.sort_values(['score','cagr'],ascending=False); H.to_csv('tqqq_stage24_screen.csv',index=False); C.to_csv('tqqq_stage24_bull_capture.csv',index=False)
print('\n=== SMART BULL SCREEN ==='); print(H[['candidate','cagr','mdd','is_cagr','is_mdd','oos_cagr','oos_mdd','avg_exp','turnover','bull_capture_median','bull_capture_mean','bull_avg_exp_median','latch_days','ext_days','score']].to_string(index=False))
print('\n=== TOP 8 BULL YEARS ===')
for n in H.head(8).candidate:
    print('\n',n); print(C[C.candidate==n][['year','bh','strategy','capture','avg_exp','pct_ge50','pct_ge60','pct_ge70','pct_ge90']].to_string(index=False))
Path('tqqq_stage24_summary.json').write_text(json.dumps({'years':YEARS,'candidates':CANDS,'screen':H.to_dict('records'),'note':'Risk-off rules unchanged. Stage24 tests targeted GB continuation after a proven 20-day GB run, and a stricter Bull latch requiring no risk lock + QQQ above SMA200/SMA50/VWAP63/EMA21 + MC>=35 + NQSAR non-Red.'},ensure_ascii=False,indent=2,default=str))
