from __future__ import annotations
from pathlib import Path
import json, numpy as np, pandas as pd

# Reuse the exact Stage24 / Stage17 hierarchy, source data, and adversarial episode builders.
src=Path('research/tqqq_stage24_smart_bull_continuation.py').read_text()
prefix=src.split("CANDS={'CURRENT'")[0]
exec(compile(prefix,'stage24-prefix','exec'),globals())
print('\n=== STAGE34 FINAL GB RUNNER VALIDATION ===', flush=True)

NSIM=1000
H=2520
BLOCK=120
SEED_NORMAL=340827
SEED_BEAR=340828

PBASE={'base':.30,'fast_dd':-.065,'fast_rec':4,'rg_slow':.50,'rg_fast':.80,'gb':.90,'rg_mc_slow':40,'cooldown':20,'panic':1.0,
       'latch_exp':0,'latch_mc':999,'latch_confirm':3,'ext_exp':0,'ext_mc':35,'ext_max':40}
PCUR={**PBASE,'ext_exp':0,'ext_max':40}
P70={**PBASE,'ext_exp':.70,'ext_max':40}

# Standalone exact strategy function for arbitrary bootstrapped state paths and custom transaction cost.
def simulate(B,p,cost=.0005,return_trace=False):
    ret=B['ret']; mcv=B['mc']; nq=B['nq']; panic=B['panic']; a50=B['a50']; a63=B['a63']; a200=B['a200']; a252=B['a252']; gte10=B['gte10']; lte21=B['lte21']; s50x=B['s50a']; dd=B['dd10']
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
    base=np.zeros(n,float); strong=np.zeros(n,bool)
    for i in range(n):
        x=0. if risklock[i] else p['base']
        if x>0 and mcv[i]>=65 and nq[i]==3 and a50[i] and a63[i] and s50x[i]<=2.5:
            x=1.; strong[i]=True
        if panic[i] and s50x[i]<=-2: x=max(x,p.get('panic',1.0))
        base[i]=min(1.,x)
    t=base.copy(); sleeve=np.zeros(n,np.int8); active=0; entry=0; seen_blue=False; cool_until=0; ext_entry=0
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
                if (not risklock[i]) and nq[i]==3: active=2; entry=i+1; total=p['gb']
                else: total=p['rg_slow'] if slowA[i] else p['rg_fast']
                if base[i]>=.999: total=1.
                t[i]=max(base[i],total); sleeve[i]=active
        elif active==2:
            hold=max(0,i-(entry-1)); bad=risklock[i] or trBG or trBY or nq[i]==0
            if bad: active=0
            elif hold>=20:
                cont_ok=(not risklock[i]) and a200[i] and a50[i] and a63[i] and (not lte21[i]) and nq[i]!=0 and mcv[i]>=p.get('ext_mc',35)
                if p.get('ext_exp',0)>0 and cont_ok:
                    active=3; ext_entry=i; total=p['ext_exp']; t[i]=max(base[i],total); sleeve[i]=3
                else: active=0
            else:
                total=p['gb']
                if base[i]>=.999: total=1.
                t[i]=max(base[i],total); sleeve[i]=2
        elif active==3:
            ext_hold=i-ext_entry
            bad=risklock[i] or nq[i]==0 or lte21[i] or (not a200[i]) or (not a50[i]) or (not a63[i]) or mcv[i]<p.get('ext_mc',35) or ext_hold>=p.get('ext_max',40)
            if bad: active=0
            else:
                total=p['ext_exp']
                if base[i]>=.999: total=1.
                t[i]=max(base[i],total); sleeve[i]=3
    eff=np.zeros(n); eff[2:]=t[:-2]
    turn=np.zeros(n); turn[2:]=np.abs(np.diff(t))[:-1]
    sr=eff*ret-turn*cost
    m=metrics(sr[2:]); m['avg_exp']=float(t.mean()); m['turnover']=float(np.abs(np.diff(t)).sum()); m['ext_days']=int(np.sum(sleeve==3))
    if return_trace: return {'metrics':m,'strategy_ret':sr,'target':t,'effective':eff,'risklock':risklock,'sleeve':sleeve,'strong':strong}
    return m

# ---------- historical exact validation ----------
TCUR=simulate(A,PCUR,.0005,True); T70=simulate(A,P70,.0005,True)
assert abs(TCUR['metrics']['cagr']-trace_smart(A,PCUR)['metrics']['cagr'])<1e-12
assert abs(T70['metrics']['cagr']-trace_smart(A,P70)['metrics']['cagr'])<1e-12

DTS=pd.to_datetime(F.date).reset_index(drop=True)
def win_metrics(sr,mask):
    x=np.asarray(sr,float)[np.asarray(mask,bool)]; x=x[np.isfinite(x)]
    return metrics(x) if len(x)>10 else {'cagr':np.nan,'mdd':np.nan,'end':np.nan}

def annual_rows(name,T):
    out=[]
    yy=DTS.dt.year.to_numpy()
    for y in sorted(np.unique(yy)):
        m=win_metrics(T['strategy_ret'],yy==y)
        out.append({'candidate':name,'year':int(y),**m,'avg_exp':float(np.mean(T['effective'][yy==y])),'ext_days':int(np.sum((T['sleeve']==3)&(yy==y)))})
    return out
ANN=pd.DataFrame(annual_rows('CURRENT',TCUR)+annual_rows('E70_M40',T70))
ANN.to_csv('tqqq_stage34_annual.csv',index=False)

# Subperiod / pseudo walk-forward stability. Parameters are fixed ex ante; no refit inside windows.
periods=[('2011-2015',2011,2015),('2016-2018',2016,2018),('2019-2021',2019,2021),('2022-2024',2022,2024),('2025-2026',2025,2026)]
nearby={'CURRENT':PCUR}
for ex in (.50,.60,.70):
    for mx in (20,40,60): nearby[f'E{int(ex*100)}_M{mx}']={**PBASE,'ext_exp':ex,'ext_max':mx}
traces={k:simulate(A,p,.0005,True) for k,p in nearby.items()}
WF=[]; yy=DTS.dt.year.to_numpy()
for nm,T in traces.items():
    for lab,a,b in periods:
        m=win_metrics(T['strategy_ret'],(yy>=a)&(yy<=b)); WF.append({'candidate':nm,'period':lab,**m,'ext_days':int(np.sum((T['sleeve']==3)&(yy>=a)&(yy<=b)))})
WF=pd.DataFrame(WF); WF.to_csv('tqqq_stage34_walkforward.csv',index=False)

# Transaction-cost sensitivity.
COSTS=[]
for nm,p in [('CURRENT',PCUR),('E70_M40',P70)]:
    for bps in (5,10,20):
        m=simulate(A,p,bps/10000.0); COSTS.append({'candidate':nm,'cost_bps_oneway':bps,**m})
COSTS=pd.DataFrame(COSTS); COSTS.to_csv('tqqq_stage34_costs.csv',index=False)

# Drawdown episodes (top 8, including duration/recovery).
def dd_episodes(sr,dates,topn=8):
    r=np.asarray(sr,float); eq=np.cumprod(1+np.nan_to_num(r,nan=0.0)); peak=np.maximum.accumulate(eq); dd=eq/peak-1
    troughs=np.argsort(dd)[:max(topn*8,topn)]; used=[]; rows=[]
    for tr in troughs:
        pk=int(np.argmax(eq[:tr+1])); rec=None
        for j in range(tr+1,len(eq)):
            if eq[j]>=eq[pk]: rec=j; break
        # de-duplicate overlapping peak/trough episodes
        if any(abs(pk-x[0])<10 and abs(tr-x[1])<10 for x in used): continue
        used.append((pk,tr)); rows.append({'peak':str(pd.Timestamp(dates.iloc[pk]).date()),'trough':str(pd.Timestamp(dates.iloc[tr]).date()),'recovery':str(pd.Timestamp(dates.iloc[rec]).date()) if rec is not None else '', 'mdd':float(dd[tr]),'trading_days_to_trough':int(tr-pk),'trading_days_to_recovery':int(rec-pk) if rec is not None else None})
        if len(rows)>=topn: break
    return rows
DD=[]
for nm,T in [('CURRENT',TCUR),('E70_M40',T70)]:
    for x in dd_episodes(T['strategy_ret'],DTS,8): DD.append({'candidate':nm,**x})
DD=pd.DataFrame(DD); DD.to_csv('tqqq_stage34_drawdowns.csv',index=False)

# ---------- normal 1000-path moving-block bootstrap ----------
L=len(A['ret']); rng=np.random.default_rng(SEED_NORMAL); nblocks=int(np.ceil(H/BLOCK)); starts=rng.integers(0,L-BLOCK+1,size=(NSIM,nblocks)); offs=np.arange(BLOCK); paths=(starts[:,:,None]+offs).reshape(NSIM,-1)[:,:H]
normal=[]
for sim in range(NSIM):
    ix=paths[sim]; B={k:A[k][ix].copy() for k in KEYS}
    for nm,p in [('CURRENT',PCUR),('E70_M40',P70)]: normal.append({'sim':sim,'candidate':nm,**simulate(B,p,.0005)})
    if (sim+1)%100==0: print('[normal mc]',sim+1,'/',NSIM,flush=True)
NORMAL=pd.DataFrame(normal); NORMAL.to_csv('tqqq_stage34_normal_mc.csv',index=False)

# ---------- adversarial Bear 1000-path stress ----------
rng=np.random.default_rng(SEED_BEAR); starts=rng.integers(0,L-BLOCK+1,size=(NSIM,nblocks)); paths=(starts[:,:,None]+offs).reshape(NSIM,-1)[:,:H]
families=np.array((['dotcom_like']*250)+(['gfc_like']*250)+(['covid_like']*250)+(['2022_like']*250),dtype=object); rng.shuffle(families)
bear=[]
for sim in range(NSIM):
    ix=paths[sim]; B={k:A[k][ix].copy() for k in KEYS}; fam=str(families[sim]); ep=make_episode(fam,rng); le=len(ep['ret'])
    if le>=H-504:
        cut=(le-(H-504))//2; ep={k:v[cut:cut+(H-504)] for k,v in ep.items()}; le=len(ep['ret'])
    pos=int(rng.integers(252,max(253,H-le-252)))
    for k in KEYS: B[k][pos:pos+le]=ep[k]
    for nm,p in [('CURRENT',PCUR),('E70_M40',P70)]: bear.append({'sim':sim,'family':fam,'candidate':nm,**simulate(B,p,.0005)})
    if (sim+1)%100==0: print('[bear mc]',sim+1,'/',NSIM,flush=True)
BEAR=pd.DataFrame(bear); BEAR.to_csv('tqqq_stage34_bear_mc.csv',index=False)

def summ(g):
    q=lambda x,p:float(np.quantile(np.asarray(x,float),p)); cg=g.cagr; md=g.mdd
    return {'n':int(len(g)),'cagr_p05':q(cg,.05),'cagr_median':q(cg,.5),'cagr_p95':q(cg,.95),'mdd_p05':q(md,.05),'mdd_median':q(md,.5),'mdd_p95':q(md,.95),'prob_mdd25plus':float(np.mean(md<-.25)),'prob_mdd30plus':float(np.mean(md<-.30)),'prob_mdd35plus':float(np.mean(md<-.35)),'prob_cagr20below':float(np.mean(cg<.20)),'prob_cagr25_mdd25':float(np.mean((cg>=.25)&(md>=-.25)))}
SUM=[]
for typ,df in [('normal',NORMAL),('bear',BEAR)]:
    for cand,g in df.groupby('candidate'): SUM.append({'test':typ,'candidate':cand,'family':'ALL',**summ(g)})
    if typ=='bear':
        for (cand,fam),g in df.groupby(['candidate','family']): SUM.append({'test':typ,'candidate':cand,'family':fam,**summ(g)})
SUM=pd.DataFrame(SUM); SUM.to_csv('tqqq_stage34_mc_summary.csv',index=False)

# Pairwise Monte Carlo deltas on the exact same paths.
def pair(df):
    p=df.pivot(index='sim',columns='candidate',values=['cagr','mdd']); dc=p[('cagr','E70_M40')]-p[('cagr','CURRENT')]; dm=p[('mdd','E70_M40')]-p[('mdd','CURRENT')]
    return {'delta_cagr_median':float(np.median(dc)),'delta_cagr_p05':float(np.quantile(dc,.05)),'prob_cagr_better':float(np.mean(dc>0)),'delta_mdd_median':float(np.median(dm)),'delta_mdd_p05':float(np.quantile(dm,.05)),'prob_mdd_no_worse':float(np.mean(dm>=-1e-12)),'prob_both_better_or_equal':float(np.mean((dc>0)&(dm>=-1e-12)))}
PAIR={'normal':pair(NORMAL),'bear':pair(BEAR)}

# Historical headline and nearby robustness table.
HIST=[]
for nm,T in traces.items(): HIST.append({'candidate':nm,**T['metrics']})
HIST=pd.DataFrame(HIST).sort_values('cagr',ascending=False); HIST.to_csv('tqqq_stage34_historical.csv',index=False)

print('\n=== HISTORICAL / NEARBY ==='); print(HIST[['candidate','cagr','mdd','end','avg_exp','turnover','ext_days']].to_string(index=False))
print('\n=== WALK FORWARD ==='); print(WF.to_string(index=False))
print('\n=== COSTS ==='); print(COSTS.to_string(index=False))
print('\n=== MC SUMMARY ==='); print(SUM.to_string(index=False))
print('\n=== PAIRWISE ==='); print(json.dumps(PAIR,indent=2))
print('\n=== KEY YEARS ==='); print(ANN[ANN.year.isin([2011,2013,2017,2018,2020,2021,2022,2023,2024,2025,2026])].to_string(index=False))
print('\n=== DRAWDOWNS ==='); print(DD.to_string(index=False))

out={'historical':HIST.to_dict('records'),'walkforward':WF.to_dict('records'),'costs':COSTS.to_dict('records'),'mc_summary':SUM.to_dict('records'),'pairwise':PAIR,'annual_key':ANN[ANN.year.isin([2011,2013,2017,2018,2020,2021,2022,2023,2024,2025,2026])].to_dict('records'),'drawdowns':DD.to_dict('records'),'seeds':{'normal':SEED_NORMAL,'bear':SEED_BEAR},'nsim_each':NSIM,'horizon_days':H,'block_days':BLOCK,'candidate_rule':'After a GB tactical sleeve has survived 20 trading days, if all risk locks are off, QQQ remains above SMA200/SMA50/VWAP63/EMA21, NQSAR is non-Red, and MC57>=35, downgrade from GB90% to a 70% TQQQ continuation sleeve for at most 40 more trading days. Exit runner immediately on any risk lock, NQSAR Red, QQQ below EMA21/SMA200/SMA50/VWAP63, MC57<35, or max duration. Strong Bull 100%, RG, VIX panic, and all Bear/Risk-Off logic unchanged.','caveats':['MC57 fixed current 57-ETF historical universe still has point-in-time/survivorship risk and is not fully audited.','NQSAR historical colors are a reconstruction proxy, validated 41/42 against recent stored states, not authoritative full historical EXP_STATE_ID.','Adversarial Bear paths intentionally break exact state/return consistency to stress model risk; they are not a forecast distribution.']}
Path('tqqq_stage34_summary.json').write_text(json.dumps(out,ensure_ascii=False,indent=2,default=str))
