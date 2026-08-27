from __future__ import annotations
from pathlib import Path
import json, numpy as np, pandas as pd

src=Path('research/tqqq_stage17_hierarchy_crisis_fix.py').read_text()
prefix=src.split('NEW={')[0]
exec(compile(prefix,'stage17-prefix','exec'),globals())
print('\n=== STAGE26 EVENT-DRIVEN BULL ===',flush=True)

YEARS=[2013,2017,2020,2021,2023,2024]
P0={'base':.30,'fast_dd':-.065,'fast_rec':4,'rg_slow':.50,'rg_fast':.80,'gb':.90,'rg_mc_slow':40,'cooldown':20,'panic':1.0}
dates=pd.to_datetime(F.date).reset_index(drop=True)
qqq_close=qqq.Close.reindex(pd.DatetimeIndex(dates)).to_numpy(float)

def msub(sr,mask):
    x=np.asarray(sr,float)[mask]; x=x[np.isfinite(x)]
    if len(x)<20: return {'cagr':np.nan,'mdd':np.nan,'end':np.nan}
    return metrics(x)

def trace_event(A,p):
    ret=A['ret']; mcv=A['mc']; nq=A['nq']; panic=A['panic']; a50=A['a50']; a63=A['a63']; a200=A['a200']; a252=A['a252']; gte10=A['gte10']; lte21=A['lte21']; s50x=A['s50a']; dd=A['dd10']
    n=len(ret); rawbear=(~a200)&(~a252); bear5=np.zeros(n,bool)
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

    # Base and strict Strong Bull are unchanged.
    base=np.zeros(n,float); strong=np.zeros(n,bool); panicA=np.zeros(n,bool)
    for i in range(n):
        x=0. if risklock[i] else p['base']
        if x>0 and mcv[i]>=65 and nq[i]==3 and a50[i] and a63[i] and s50x[i]<=2.5:
            x=1.; strong[i]=True
        if panic[i] and s50x[i]<=-2:
            x=max(x,p.get('panic',1.)); panicA[i]=True
        base[i]=min(1.,x)

    # Existing crisis RG / dip-GB sleeve, exactly same hierarchy as Stage17.
    t=base.copy(); active=0; entry=0; seen_blue=False; cool_until=0
    tactical=np.zeros(n,np.int8)
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
                t[i]=max(t[i],total); tactical[i]=active
        elif active==2:
            hold=max(0,i-(entry-1)); ex=risklock[i] or trBG or trBY or nq[i]==0 or hold>=20
            if ex: active=0
            else:
                total=p['gb'];
                if base[i]>=.999: total=1.
                t[i]=max(t[i],total); tactical[i]=2

    # Event-driven Bull Trend Event (BTE): fresh Green->Blue only; never daily state re-entry.
    bte=np.zeros(n,bool); bactive=False
    for i in range(1,n):
        trGB=nq[i-1]==2 and nq[i]==3
        if not bactive:
            entry_ok=trGB and (not risklock[i]) and a200[i] and a50[i] and a63[i] and (not lte21[i]) and mcv[i]>=p.get('bte_mc',999)
            if p.get('bte_exp',0)>0 and entry_ok: bactive=True
        if bactive:
            if p.get('bte_exit','yellow')=='yellow':
                bad=risklock[i] or nq[i] in (0,1) or lte21[i] or (not a200[i]) or (not a50[i]) or (not a63[i])
            else:
                # Loose exit allows Yellow but not Red; price deterioration still exits.
                bad=risklock[i] or nq[i]==0 or lte21[i] or (not a200[i]) or (not a50[i]) or (not a63[i])
            if bad: bactive=False
            else:
                t[i]=max(t[i],p.get('bte_exp',0.0)); bte[i]=True

    # Strong-Bull hysteresis: strict condition opens 100%; losing only the strict/overheat gate
    # steps down to a runner rather than all the way to 30%. Fresh strict trigger required after exit.
    sbh=np.zeros(n,bool); sactive=False
    for i in range(n):
        if not sactive and p.get('sbh_exp',0)>0 and strong[i] and (not risklock[i]): sactive=True
        if sactive:
            if p.get('sbh_exit','blue')=='blue':
                healthy=(not risklock[i]) and nq[i]==3 and a200[i] and a50[i] and a63[i] and (not lte21[i]) and mcv[i]>=35
            else:
                healthy=(not risklock[i]) and nq[i]!=0 and a200[i] and a50[i] and a63[i] and (not lte21[i]) and mcv[i]>=35
            if not healthy: sactive=False
            elif strong[i]: t[i]=max(t[i],1.0); sbh[i]=True
            else: t[i]=max(t[i],p.get('sbh_exp',0.0)); sbh[i]=True

    eff=np.zeros(n); eff[2:]=t[:-2]
    turn=np.zeros(n); turn[2:]=np.abs(np.diff(t))[:-1]
    sr=eff*ret-turn*COST
    m=metrics(sr[2:]); m['avg_exp']=float(t.mean()); m['turnover']=float(np.abs(np.diff(t)).sum())
    y=dates.dt.year.to_numpy(); mi=msub(sr,y<=2018); mo=msub(sr,y>=2019)
    m.update({'is_cagr':mi['cagr'],'is_mdd':mi['mdd'],'oos_cagr':mo['cagr'],'oos_mdd':mo['mdd']})
    return {'metrics':m,'target':t,'effective':eff,'strategy_ret':sr,'risklock':risklock,'strong':strong,'bte':bte,'sbh':sbh}

def prodret(x):
    x=np.asarray(x,float); x=x[np.isfinite(x)]; return float(np.prod(1+x)-1) if len(x) else np.nan

def bull_capture(T):
    rows=[]
    for y in YEARS:
        ids=np.flatnonzero(dates.dt.year.to_numpy()==y); q=qqq_close[ids]; i0=int(ids[int(np.nanargmin(q))]); tail=qqq_close[i0:int(ids[-1])+1]; i1=i0+int(np.nanargmax(tail)); i1=int(ids[-1]) if i1<=i0 else i1
        sl=slice(min(i0+1,len(dates)-1),min(i1,len(dates)-1)+1); bh=prodret(A['ret'][sl]); st=prodret(T['strategy_ret'][sl]); eff=T['effective'][i0:i1+1]
        rows.append({'year':y,'bh':bh,'strategy':st,'capture':st/bh if bh>0 else np.nan,'avg_exp':float(np.mean(eff)),'pct_ge60':float(np.mean(eff>=.60)),'pct_ge70':float(np.mean(eff>=.70)),'pct_ge80':float(np.mean(eff>=.80)),'pct_ge90':float(np.mean(eff>=.90)),'pct_100':float(np.mean(eff>=.999))})
    R=pd.DataFrame(rows); return R, {'bull_capture_median':float(R.capture.median()),'bull_capture_mean':float(R.capture.mean()),'bull_avg_exp_median':float(R.avg_exp.median())}

CANDS={'CURRENT':{**P0,'bte_exp':0,'bte_mc':999,'bte_exit':'yellow','sbh_exp':0,'sbh_exit':'blue'}}
for ex in (.60,.70,.80):
    for mc in (35,45):
        for xt in ('yellow','red'):
            CANDS[f"BTE{int(ex*100)}_MC{mc}_{'Y' if xt=='yellow' else 'R'}"]={**P0,'bte_exp':ex,'bte_mc':mc,'bte_exit':xt,'sbh_exp':0,'sbh_exit':'blue'}
for ex in (.70,.80):
    for xt in ('blue','nonred'):
        CANDS[f"SBH{int(ex*100)}_{'B' if xt=='blue' else 'NR'}"]={**P0,'bte_exp':0,'bte_mc':999,'bte_exit':'yellow','sbh_exp':ex,'sbh_exit':xt}
# Limited hybrids, only event-driven layers.
for be,se in ((.60,.70),(.70,.70),(.70,.80)):
    CANDS[f"HY_BTE{int(be*100)}_SBH{int(se*100)}"]={**P0,'bte_exp':be,'bte_mc':35,'bte_exit':'yellow','sbh_exp':se,'sbh_exit':'blue'}

hist=[]; caps=[]
for name,p in CANDS.items():
    T=trace_event(A,p); R,ag=bull_capture(T)
    hist.append({'candidate':name,**T['metrics'],**ag,'bte_days':int(T['bte'].sum()),'sbh_days':int(T['sbh'].sum())})
    R.insert(0,'candidate',name); caps.append(R)
H=pd.DataFrame(hist); C=pd.concat(caps,ignore_index=True)
H['score']=H.cagr + .18*H.bull_capture_median - 1.5*np.maximum(0,(-H.mdd)-.22) - .00005*H.turnover
H=H.sort_values(['score','cagr'],ascending=False); H.to_csv('tqqq_stage26_screen.csv',index=False); C.to_csv('tqqq_stage26_bull_capture.csv',index=False)
print('\n=== EVENT-DRIVEN BULL SCREEN ===')
print(H[['candidate','cagr','mdd','is_cagr','is_mdd','oos_cagr','oos_mdd','avg_exp','turnover','bull_capture_median','bull_capture_mean','bull_avg_exp_median','bte_days','sbh_days','score']].to_string(index=False))
print('\n=== TOP 10 BULL YEARS ===')
for n in H.head(10).candidate:
    print('\n',n); print(C[C.candidate==n][['year','bh','strategy','capture','avg_exp','pct_ge60','pct_ge70','pct_ge80','pct_ge90','pct_100']].to_string(index=False))
Path('tqqq_stage26_summary.json').write_text(json.dumps({'candidates':CANDS,'screen':H.to_dict('records'),'note':'Risk-off hierarchy is unchanged. Bull Trend Event enters only on a fresh Green->Blue transition in healthy structure and requires a fresh event after exit. Strong-Bull hysteresis opens only on the existing strict 100% trigger, then can step down to a runner. Both are event-driven; neither is a persistent daily-state floor.'},ensure_ascii=False,indent=2,default=str))
