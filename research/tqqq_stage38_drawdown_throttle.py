from __future__ import annotations
from pathlib import Path
import json, numpy as np, pandas as pd

# Reuse exact Stage36 hierarchy/data + tax account machinery, without its grid.
src=Path('research/tqqq_stage36_goal_first_taxaware.py').read_text()
prefix=src.split('SPECS = [{"name":"CURRENT"}')[0]
exec(compile(prefix,'stage36-prefix','exec'),globals())

print('\n=== STAGE38 DRAWDOWN THROTTLE / GOAL-FIRST ===',flush=True)
NSIM=1000; TAXSIM=300; H=2520; BLOCK=120; SEEDN=380827; SEEDB=380828

# Goal: preserve >=30% after-tax growth potential while cutting Stage37 B80/F100 drawdown.
# Only exact CURRENT normal-30% days are altered. Existing risk locks/RG/GB/StrongBull/VIX Panic stay untouched.
def bullmask(B,mode):
    base=B['a200'] & B['a252'] & (B['mc']>=35)
    if mode=='A2': return base
    if mode=='E21': return base & (~B['lte21'])
    if mode=='MID': return base & (B['a50'] | B['a63'])
    if mode=='A4': return base & B['a50'] & B['a63']
    raise ValueError(mode)

def target38(B,spec,cur=None):
    if spec['name']=='CURRENT': return (cur if cur is not None else current_trace(B))['target'].copy()
    if spec['name']=='BUYHOLD': return np.ones(len(B['ret']),float)
    if spec['name']=='STAGE37':
        if cur is None: cur=current_trace(B)
        t=cur['target'].copy(); normal=(~cur['risklock']) & np.isclose(t,.30,atol=1e-9)
        t[normal]=np.maximum(t[normal],.80)
        hit=normal & (B['a200']&B['a252']&(B['mc']>=35)); t[hit]=1.0
        return np.clip(t,0,1)
    if cur is None: cur=current_trace(B)
    t=cur['target'].copy(); normal=(~cur['risklock']) & np.isclose(t,.30,atol=1e-9)
    x=np.full(len(t),spec['high'],float)
    # First throttle: below EMA21.
    x[B['lte21']]=np.minimum(x[B['lte21']],spec['mid'])
    # Second throttle: both medium-term supports lost.
    weak=(~B['a50']) & (~B['a63'])
    x[weak]=np.minimum(x[weak],spec['weak'])
    # Pre-crash throttle before the existing -6.5% Fast Crash lock fires.
    if spec['ddcut']<0:
        pre=(B['dd10']<=spec['ddcut']) & B['lte21']
        x[pre]=np.minimum(x[pre],spec['weak'])
    t[normal]=np.maximum(t[normal],x[normal])
    hit=normal & bullmask(B,spec['fullmode'])
    t[hit]=np.maximum(t[hit],spec['full'])
    return np.clip(t,0,1)

SPECS=[{'name':'CURRENT'},{'name':'BUYHOLD'},{'name':'STAGE37'}]
# Broad but structured frontier around the aggressive Stage37 solution.
for high in (.65,.70,.75,.80):
  for mid in (.45,.50,.55,.60,.65):
    if mid>high: continue
    for weak in (.30,.35,.40,.45,.50):
      if weak>mid: continue
      for full in (.90,1.00):
        for fullmode in ('A2','E21','MID'):
          for ddcut in (-.04,-.05):
            nm=f'H{int(high*100)}_M{int(mid*100)}_W{int(weak*100)}_F{int(full*100)}_{fullmode}_D{int(abs(ddcut)*100)}'
            SPECS.append({'name':nm,'high':high,'mid':mid,'weak':weak,'full':full,'fullmode':fullmode,'ddcut':ddcut})

curA=current_trace(A); rows=[]; targets={}
for s in SPECS:
    t=target38(A,s,curA); targets[s['name']]=t
    m,_,_=from_target(A,t,COST); pre=account_end(A['ret'],t,COST,0.0,DTS); aft=account_end(A['ret'],t,COST,TAX,DTS)
    rows.append({'candidate':s['name'],**{k:s.get(k,np.nan) for k in ['high','mid','weak','full','fullmode','ddcut']},'pre_cagr':pre['cagr'],'pre_mdd':pre['mdd'],'tax_cagr':aft['cagr'],'tax_end':aft['end'],'avg_exp':m['avg_exp'],'turnover':m['turnover']})
HIST=pd.DataFrame(rows); HIST.to_csv('tqqq_stage38_scan.csv',index=False)

# Pick candidates on the actual-history return/DD frontier. Explicitly favor <=40% and <=35% MDD while keeping tax growth high.
sel=['CURRENT','BUYHOLD','STAGE37']
for cap in (.30,.325,.35,.375,.40,.425,.45):
    g=HIST[(HIST.candidate.str.startswith('H'))&(HIST.pre_mdd>=-cap)].sort_values(['tax_cagr','pre_mdd'],ascending=[False,False])
    sel += g.head(2).candidate.tolist()
# Also preserve the highest after-tax candidates that clear historical 30% with MDD <=42.5%.
g=HIST[(HIST.candidate.str.startswith('H'))&(HIST.tax_cagr>=.30)&(HIST.pre_mdd>=-.425)].sort_values(['tax_cagr','pre_mdd'],ascending=[False,False])
sel += g.head(6).candidate.tolist()
sel=list(dict.fromkeys(sel)); SMAP={s['name']:s for s in SPECS if s['name'] in sel}
print('SELECTED',sel,flush=True)

# Historical subperiod stability.
PER=[('2011-2015',2011,2015),('2016-2018',2016,2018),('2019-2021',2019,2021),('2022-2024',2022,2024),('2025-2026',2025,2026)]
wf=[]
for nm in sel:
    t=targets[nm]
    for lab,a,b in PER:
        ids=np.flatnonzero((YY>=a)&(YY<=b)); rr=A['ret'][ids]; tt=t[ids]; dd=DTS.iloc[ids].reset_index(drop=True)
        pre=account_end(rr,tt,COST,0.0,dd); aft=account_end(rr,tt,COST,TAX,dd)
        wf.append({'candidate':nm,'period':lab,'pre_cagr':pre['cagr'],'pre_mdd':pre['mdd'],'tax_cagr':aft['cagr'],'tax_end':aft['end']})
WF=pd.DataFrame(wf); WF.to_csv('tqqq_stage38_subperiods.csv',index=False)

# Cost sensitivity.
cc=[]
for nm in sel:
    t=targets[nm]
    for bps in (5,10,20):
        c=bps/10000.; pre=account_end(A['ret'],t,c,0.0,DTS); aft=account_end(A['ret'],t,c,TAX,DTS)
        cc.append({'candidate':nm,'cost_bps':bps,'pre_cagr':pre['cagr'],'pre_mdd':pre['mdd'],'tax_cagr':aft['cagr'],'tax_end':aft['end']})
COSTS=pd.DataFrame(cc); COSTS.to_csv('tqqq_stage38_costs.csv',index=False)

# Normal 10y moving-block bootstrap; tax on 300 matched paths.
L=len(A['ret']); nb=int(np.ceil(H/BLOCK)); offs=np.arange(BLOCK); rng=np.random.default_rng(SEEDN)
starts=rng.integers(0,L-BLOCK+1,size=(NSIM,nb)); paths=(starts[:,:,None]+offs).reshape(NSIM,-1)[:,:H]
normal=[]; ntax=[]
for z in range(NSIM):
    ix=paths[z]; B={k:A[k][ix].copy() for k in KEYS}; cur=current_trace(B)
    for nm,s in SMAP.items():
        t=target38(B,s,cur); m,_,_=from_target(B,t,COST); normal.append({'sim':z,'candidate':nm,**m})
        if z<TAXSIM:
            pre=account_end(B['ret'],t,COST,0.0,None); aft=account_end(B['ret'],t,COST,TAX,None)
            ntax.append({'sim':z,'candidate':nm,'pre_cagr':pre['cagr'],'pre_mdd':pre['mdd'],'tax_cagr':aft['cagr'],'tax_end':aft['end']})
    if (z+1)%100==0: print('[normal38]',z+1,'/',NSIM,flush=True)
NORMAL=pd.DataFrame(normal); NORMAL.to_csv('tqqq_stage38_normal_mc.csv',index=False)
NTAX=pd.DataFrame(ntax); NTAX.to_csv('tqqq_stage38_normal_tax_mc.csv',index=False)

# Adversarial bear stress, for comparative fragility only.
rng=np.random.default_rng(SEEDB); starts=rng.integers(0,L-BLOCK+1,size=(NSIM,nb)); paths=(starts[:,:,None]+offs).reshape(NSIM,-1)[:,:H]
families=np.array((['dotcom_like']*250)+(['gfc_like']*250)+(['covid_like']*250)+(['2022_like']*250),dtype=object); rng.shuffle(families)
bear=[]
for z in range(NSIM):
    ix=paths[z]; B={k:A[k][ix].copy() for k in KEYS}; fam=str(families[z]); ep=make_episode(fam,rng); le=len(ep['ret'])
    if le>=H-504:
        cut=(le-(H-504))//2; ep={k:v[cut:cut+(H-504)] for k,v in ep.items()}; le=len(ep['ret'])
    pos=int(rng.integers(252,max(253,H-le-252)))
    for k in KEYS: B[k][pos:pos+le]=ep[k]
    cur=current_trace(B)
    for nm,s in SMAP.items():
        t=target38(B,s,cur); m,_,_=from_target(B,t,COST); bear.append({'sim':z,'family':fam,'candidate':nm,**m})
    if (z+1)%100==0: print('[bear38]',z+1,'/',NSIM,flush=True)
BEAR=pd.DataFrame(bear); BEAR.to_csv('tqqq_stage38_bear_mc.csv',index=False)

def summ(g):
    q=lambda x,p:float(np.quantile(np.asarray(x,float),p))
    return {'n':len(g),'cagr_p05':q(g.cagr,.05),'cagr_median':q(g.cagr,.5),'mdd_p05':q(g.mdd,.05),'mdd_median':q(g.mdd,.5),'prob_mdd35plus':float(np.mean(g.mdd<-.35)),'prob_mdd40plus':float(np.mean(g.mdd<-.40)),'prob_mdd45plus':float(np.mean(g.mdd<-.45)),'prob_cagr30plus':float(np.mean(g.cagr>=.30))}
SS=[]
for typ,df in [('normal',NORMAL),('bear',BEAR)]:
    for nm,g in df.groupby('candidate'): SS.append({'test':typ,'candidate':nm,**summ(g)})
SUM=pd.DataFrame(SS); SUM.to_csv('tqqq_stage38_mc_summary.csv',index=False)
TS=[]
for nm,g in NTAX.groupby('candidate'):
    TS.append({'candidate':nm,'n':len(g),'tax_p05':float(np.quantile(g.tax_cagr,.05)),'tax_median':float(np.quantile(g.tax_cagr,.5)),'tax_p95':float(np.quantile(g.tax_cagr,.95)),'prob_tax30plus':float(np.mean(g.tax_cagr>=.30)),'mdd_p05':float(np.quantile(g.pre_mdd,.05)),'mdd_median':float(np.quantile(g.pre_mdd,.5))})
TAXMC=pd.DataFrame(TS); TAXMC.to_csv('tqqq_stage38_tax_mc_summary.csv',index=False)

# Final rank: goal first, but penalize >40% historical/median normal DD hard.
mall=SUM.pivot(index='candidate',columns='test')
rank=[]
for nm in sel:
    h=HIST[HIST.candidate.eq(nm)].iloc[0]; tx=TAXMC[TAXMC.candidate.eq(nm)].iloc[0]
    nmd=float(mall.loc[nm,('mdd_median','normal')]); bmd=float(mall.loc[nm,('mdd_median','bear')])
    score=(h.tax_cagr+.7*tx.tax_median+.15*tx.tax_p05 - 1.5*max(0.,-h.pre_mdd-.40)-.7*max(0.,-nmd-.40))
    rank.append({'candidate':nm,'hist_tax_cagr':h.tax_cagr,'hist_pre_cagr':h.pre_cagr,'hist_mdd':h.pre_mdd,'tax_mc_median':tx.tax_median,'tax_mc_p05':tx.tax_p05,'prob_tax30plus':tx.prob_tax30plus,'normal_mdd_median':nmd,'normal_mdd_p05':tx.mdd_p05,'bear_mdd_median':bmd,'hist_tax30':bool(h.tax_cagr>=.30),'hist_mdd40':bool(h.pre_mdd>=-.40),'score':score})
R=pd.DataFrame(rank).sort_values('score',ascending=False); R.to_csv('tqqq_stage38_final_rank.csv',index=False)

print('\n=== HIST FRONTIER <=45% DD ==='); print(HIST[(HIST.candidate.isin(sel))][['candidate','pre_cagr','pre_mdd','tax_cagr','tax_end','avg_exp','turnover']].sort_values('tax_cagr',ascending=False).to_string(index=False))
print('\n=== TAX MC ==='); print(TAXMC.sort_values('tax_median',ascending=False).to_string(index=False))
print('\n=== FINAL ==='); print(R.to_string(index=False))
Path('tqqq_stage38_summary.json').write_text(json.dumps({'selected':sel,'historical':HIST[HIST.candidate.isin(sel)].to_dict('records'),'subperiods':WF.to_dict('records'),'costs':COSTS.to_dict('records'),'mc':SUM.to_dict('records'),'tax_mc':TAXMC.to_dict('records'),'final':R.to_dict('records'),'rule':'Only exact normal 30% days are raised. High exposure is throttled when QQQ falls below EMA21, cut further when both SMA50 and VWAP63 are lost or 10d drawdown reaches 4/5% while below EMA21; full bull floor requires long-trend A2+MC35 with optional short/mid confirmation. Existing locks and tactical sleeves unchanged.','caveats':['MC57 PIT/survivorship audit unresolved.','NQSAR historical state is proxy.','USDJPY FX/dividend tax not modeled.','Bear stress is adversarial, not a forecast distribution.']},ensure_ascii=False,indent=2,default=str))
