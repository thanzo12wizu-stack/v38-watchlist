from __future__ import annotations
from pathlib import Path
import json, numpy as np, pandas as pd

# Reuse exact Stage34 current hierarchy and adversarial builders, without running Stage34 validations.
src=Path('research/tqqq_stage34_final_gb_runner_validation.py').read_text()
prefix=src.split('# ---------- historical exact validation ----------')[0]
exec(compile(prefix,'stage34-prefix','exec'),globals())
print('\n=== STAGE35 YELLOW / BY PULLBACK OVERLAY ===',flush=True)

NSIM=1000; H=2520; BLOCK=120; SEED_NORMAL=350827; SEED_BEAR=350828

# Recompute returns from an altered target using the exact same signal-close -> t+1 open convention.
def from_target(B,t,cost=.0005):
    n=len(t); eff=np.zeros(n); eff[2:]=t[:-2]; turn=np.zeros(n); turn[2:]=np.abs(np.diff(t))[:-1]; sr=eff*B['ret']-turn*cost
    m=metrics(sr[2:]); m['avg_exp']=float(np.mean(t)); m['turnover']=float(np.abs(np.diff(t)).sum())
    return m,sr,eff

def overlay(B,kind='yellow',floor=.40,cost=.0005,trace=False):
    cur=simulate(B,PCUR,cost,True); t0=cur['target']; t=t0.copy(); risk=cur['risklock']; n=len(t)
    elig=(~risk)&np.isclose(t0,.30,atol=1e-9)&B['a200']&B['a50']&B['a63']&(~B['lte21'])&(B['mc']>=35)
    on=np.zeros(n,bool)
    if kind=='yellow':
        on=elig&(B['nq']==1)
    elif kind=='by5':
        active=False; left=0
        for i in range(1,n):
            trBY=(B['nq'][i-1]==3 and B['nq'][i]==1)
            if (not active) and trBY and elig[i]: active=True; left=5
            if active:
                if (not elig[i]) or B['nq'][i]!=1 or left<=0: active=False
                else: on[i]=True; left-=1
    else: raise ValueError(kind)
    t[on]=np.maximum(t[on],floor)
    m,sr,eff=from_target(B,t,cost); m['overlay_days']=int(on.sum())
    if trace:return {'metrics':m,'strategy_ret':sr,'effective':eff,'target':t,'on':on,'base':cur}
    return m

CANDS={'CURRENT':('current',.30),'Y40':('yellow',.40),'Y50':('yellow',.50),'Y60':('yellow',.60),'BY40_5D':('by5',.40),'BY50_5D':('by5',.50)}
def run_one(B,name,cost=.0005,trace=False):
    if name=='CURRENT': return simulate(B,PCUR,cost,trace)
    kind,floor=CANDS[name]; return overlay(B,kind,floor,cost,trace)

# Historical + IS/OOS + subperiods.
DTS=pd.to_datetime(F.date).reset_index(drop=True); yy=DTS.dt.year.to_numpy()
def wm(sr,mask):
    x=np.asarray(sr)[mask]; x=x[np.isfinite(x)]; return metrics(x) if len(x)>10 else {'cagr':np.nan,'mdd':np.nan,'end':np.nan}
H=[]; traces={}
for nm in CANDS:
    T=run_one(A,nm,.0005,True); traces[nm]=T; H.append({'candidate':nm,**T['metrics']})
H=pd.DataFrame(H).sort_values('cagr',ascending=False); H.to_csv('tqqq_stage35_historical.csv',index=False)
PER=[('2011-2015',2011,2015),('2016-2018',2016,2018),('2019-2021',2019,2021),('2022-2024',2022,2024),('2025-2026',2025,2026)]
WF=[]
for nm,T in traces.items():
    for lab,a,b in PER: WF.append({'candidate':nm,'period':lab,**wm(T['strategy_ret'],(yy>=a)&(yy<=b))})
WF=pd.DataFrame(WF); WF.to_csv('tqqq_stage35_walkforward.csv',index=False)
ANN=[]
for nm,T in traces.items():
    for y in sorted(np.unique(yy)):
        m=wm(T['strategy_ret'],yy==y); ANN.append({'candidate':nm,'year':int(y),**m,'avg_exp':float(np.mean(T['effective'][yy==y]))})
ANN=pd.DataFrame(ANN); ANN.to_csv('tqqq_stage35_annual.csv',index=False)
COSTS=[]
for nm in CANDS:
    for bps in (5,10,20): COSTS.append({'candidate':nm,'cost_bps':bps,**run_one(A,nm,bps/10000.0,False)})
COSTS=pd.DataFrame(COSTS); COSTS.to_csv('tqqq_stage35_costs.csv',index=False)

# Normal block bootstrap. Compute base trace once per path, then overlays through run_one (small enough for final validation).
L=len(A['ret']); rng=np.random.default_rng(SEED_NORMAL); nb=int(np.ceil(H/BLOCK)); starts=rng.integers(0,L-BLOCK+1,size=(NSIM,nb)); offs=np.arange(BLOCK); paths=(starts[:,:,None]+offs).reshape(NSIM,-1)[:,:H]
normal=[]
for s in range(NSIM):
    ix=paths[s]; B={k:A[k][ix].copy() for k in KEYS}
    for nm in CANDS: normal.append({'sim':s,'candidate':nm,**run_one(B,nm,.0005,False)})
    if (s+1)%100==0:print('[normal]',s+1,'/',NSIM,flush=True)
NORMAL=pd.DataFrame(normal); NORMAL.to_csv('tqqq_stage35_normal_mc.csv',index=False)

# Adversarial Bear paths.
rng=np.random.default_rng(SEED_BEAR); starts=rng.integers(0,L-BLOCK+1,size=(NSIM,nb)); paths=(starts[:,:,None]+offs).reshape(NSIM,-1)[:,:H]
families=np.array((['dotcom_like']*250)+(['gfc_like']*250)+(['covid_like']*250)+(['2022_like']*250),dtype=object); rng.shuffle(families)
bear=[]
for s in range(NSIM):
    ix=paths[s]; B={k:A[k][ix].copy() for k in KEYS}; fam=str(families[s]); ep=make_episode(fam,rng); le=len(ep['ret'])
    if le>=H-504:
        cut=(le-(H-504))//2; ep={k:v[cut:cut+(H-504)] for k,v in ep.items()}; le=len(ep['ret'])
    pos=int(rng.integers(252,max(253,H-le-252)))
    for k in KEYS:B[k][pos:pos+le]=ep[k]
    for nm in CANDS: bear.append({'sim':s,'family':fam,'candidate':nm,**run_one(B,nm,.0005,False)})
    if (s+1)%100==0:print('[bear]',s+1,'/',NSIM,flush=True)
BEAR=pd.DataFrame(bear); BEAR.to_csv('tqqq_stage35_bear_mc.csv',index=False)

def summ(g):
    q=lambda x,p:float(np.quantile(np.asarray(x,float),p)); cg=g.cagr; md=g.mdd
    return {'n':len(g),'cagr_p05':q(cg,.05),'cagr_median':q(cg,.5),'cagr_p95':q(cg,.95),'mdd_p05':q(md,.05),'mdd_median':q(md,.5),'prob_mdd25plus':float(np.mean(md<-.25)),'prob_mdd30plus':float(np.mean(md<-.30)),'prob_mdd35plus':float(np.mean(md<-.35)),'prob_cagr20below':float(np.mean(cg<.20)),'prob_cagr25_mdd25':float(np.mean((cg>=.25)&(md>=-.25)))}
S=[]
for typ,df in [('normal',NORMAL),('bear',BEAR)]:
    for nm,g in df.groupby('candidate'):S.append({'test':typ,'candidate':nm,'family':'ALL',**summ(g)})
    if typ=='bear':
        for (nm,fam),g in df.groupby(['candidate','family']):S.append({'test':typ,'candidate':nm,'family':fam,**summ(g)})
S=pd.DataFrame(S); S.to_csv('tqqq_stage35_mc_summary.csv',index=False)

def pair(df,nm):
    p=df.pivot(index='sim',columns='candidate',values=['cagr','mdd']); dc=p[('cagr',nm)]-p[('cagr','CURRENT')]; dm=p[('mdd',nm)]-p[('mdd','CURRENT')]
    return {'delta_cagr_median':float(np.median(dc)),'delta_cagr_p05':float(np.quantile(dc,.05)),'prob_cagr_better':float(np.mean(dc>0)),'delta_mdd_median':float(np.median(dm)),'delta_mdd_p05':float(np.quantile(dm,.05)),'prob_mdd_no_worse':float(np.mean(dm>=-1e-12)),'prob_both':float(np.mean((dc>0)&(dm>=-1e-12)))}
PAIR={typ:{nm:pair(df,nm) for nm in CANDS if nm!='CURRENT'} for typ,df in [('normal',NORMAL),('bear',BEAR)]}

print('\n=== HISTORICAL ===');print(H.to_string(index=False))
print('\n=== WALK FORWARD ===');print(WF.to_string(index=False))
print('\n=== MC ALL ===');print(S[S.family.eq('ALL')].to_string(index=False))
print('\n=== PAIRWISE ===');print(json.dumps(PAIR,indent=2))
print('\n=== KEY YEARS ===');print(ANN[ANN.year.isin([2011,2017,2018,2020,2021,2022,2023,2024,2025,2026])].to_string(index=False))

out={'historical':H.to_dict('records'),'walkforward':WF.to_dict('records'),'costs':COSTS.to_dict('records'),'mc_summary':S.to_dict('records'),'pairwise':PAIR,'annual_key':ANN[ANN.year.isin([2011,2017,2018,2020,2021,2022,2023,2024,2025,2026])].to_dict('records'),'rules':{'Y40/Y50/Y60':'Only when exact CURRENT target is 30%, all risk locks are off, QQQ>SMA200/SMA50/VWAP63/EMA21, MC57>=35, and NQSAR is Yellow, raise total TQQQ target to 40/50/60% for that signal day.','BY40_5D/BY50_5D':'Same structural eligibility, but activate only on a Blue->Yellow transition and for at most 5 Yellow signal days; exit immediately when eligibility or Yellow state ends.'},'caveats':['MC57 PIT/survivorship audit remains unresolved.','NQSAR historical state is reconstruction proxy, not authoritative full history.','Bear stress intentionally breaks exact state/return consistency and is not a forecast distribution.']}
Path('tqqq_stage35_summary.json').write_text(json.dumps(out,ensure_ascii=False,indent=2,default=str))
