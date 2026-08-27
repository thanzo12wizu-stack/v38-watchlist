from __future__ import annotations
from pathlib import Path
import json, numpy as np, pandas as pd

src=Path('research/tqqq_stage46_crash_seed_refinement.py').read_text()
prefix=src.split('SPECS=[]')[0]
exec(compile(prefix,'stage46-prefix','exec'),globals())
print('\n=== STAGE48 LOWER CRASH-SEED BOUNDARY ===',flush=True)
NSIM=1000; H=2520; BLOCK=120; SEED48=480827
SPECS=[]
for vth in (21.,22.,23.,24.):
  for s50 in (-.50,-.75,-1.00,-1.25):
    for ddcut in (-.02,-.025,-.03,-.035):
      for look in (30,40,50):
        nm=f'V{int(vth)}_S{int(abs(s50)*100)}_D{int(abs(ddcut)*1000)}_L{look}'
        SPECS.append({'name':nm,'vth':vth,'s50':s50,'ddcut':ddcut,'lookback':look,'rec':'R10','maxd':80})
curA=current_trace(A); rows=[]; targets={'AGGR':target_aggr(A,curA),'BUYHOLD':np.ones(len(A['ret']))}
for nm,t in targets.items():
    m,_,_=from_target(A,t,COST); pre=account_end(A['ret'],t,COST,0.,DTS); aft=account_end(A['ret'],t,COST,TAX,DTS)
    rows.append({'candidate':nm,'vth':np.nan,'s50':np.nan,'ddcut':np.nan,'lookback':np.nan,'pre_cagr':pre['cagr'],'pre_mdd':pre['mdd'],'tax_cagr':aft['cagr'],'tax_end':aft['end'],'avg_exp':m['avg_exp'],'turnover':m['turnover']})
for s in SPECS:
    t=runner46(A,VIXLVL,s,curA); targets[s['name']]=t
    m,_,_=from_target(A,t,COST); pre=account_end(A['ret'],t,COST,0.,DTS); aft=account_end(A['ret'],t,COST,TAX,DTS)
    rows.append({'candidate':s['name'],**{k:s[k] for k in ['vth','s50','ddcut','lookback']},'pre_cagr':pre['cagr'],'pre_mdd':pre['mdd'],'tax_cagr':aft['cagr'],'tax_end':aft['end'],'avg_exp':m['avg_exp'],'turnover':m['turnover']})
HIST=pd.DataFrame(rows); HIST.to_csv('tqqq_stage48_scan.csv',index=False)
R=HIST[~HIST.candidate.isin(['AGGR','BUYHOLD'])]; sel=['AGGR','BUYHOLD']+R.sort_values(['tax_cagr','pre_mdd'],ascending=[False,False]).head(15).candidate.tolist(); sel=list(dict.fromkeys(sel)); SM={s['name']:s for s in SPECS}
print('SELECTED',sel,flush=True)
L=len(A['ret']); nb=int(np.ceil(H/BLOCK)); offs=np.arange(BLOCK); rng=np.random.default_rng(SEED48); starts=rng.integers(0,L-BLOCK+1,size=(NSIM,nb)); paths=(starts[:,:,None]+offs).reshape(NSIM,-1)[:,:H]
mc=[]
for z in range(NSIM):
    ix=paths[z]; B={k:A[k][ix].copy() for k in KEYS}; vx=VIXLVL[ix].copy(); cur=current_trace(B)
    for nm in sel:
        if nm=='BUYHOLD': t=np.ones(len(B['ret']))
        elif nm=='AGGR': t=target_aggr(B,cur)
        else: t=runner46(B,vx,SM[nm],cur)
        pre=account_end(B['ret'],t,COST,0.,None); aft=account_end(B['ret'],t,COST,TAX,None)
        mc.append({'sim':z,'candidate':nm,'tax_cagr':aft['cagr'],'tax_end':aft['end'],'pre_mdd':pre['mdd']})
    if (z+1)%50==0: print('[mc48]',z+1,'/',NSIM,flush=True)
MC=pd.DataFrame(mc); MC.to_csv('tqqq_stage48_mc.csv',index=False)
def q(x,p):return float(np.quantile(np.asarray(x,float),p))
S=[]
for nm,g in MC.groupby('candidate'):
    S.append({'candidate':nm,'tax_end_mean':float(g.tax_end.mean()),'tax_end_median':q(g.tax_end,.5),'tax_end_p05':q(g.tax_end,.05),'tax_cagr_median':q(g.tax_cagr,.5),'tax_cagr_p05':q(g.tax_cagr,.05),'mdd_median':q(g.pre_mdd,.5),'mdd_p05':q(g.pre_mdd,.05),'p_tax30':float(np.mean(g.tax_cagr>=.30)),'p_mdd50':float(np.mean(g.pre_mdd<-.50))})
SUM=pd.DataFrame(S); p=MC.pivot(index='sim',columns='candidate',values=['tax_end','pre_mdd']); PA=[]
for nm in sel:
    if nm=='AGGR': continue
    ratio=p[('tax_end',nm)]/p[('tax_end','AGGR')]; dm=p[('pre_mdd',nm)]-p[('pre_mdd','AGGR')]
    PA.append({'candidate':nm,'p_end_better_than_aggr':float(np.mean(ratio>1)),'end_ratio_median':float(np.median(ratio)),'end_ratio_p05':q(ratio,.05),'p_mdd_no_worse':float(np.mean(dm>=0)),'mdd_delta_median':float(np.median(dm))})
PAIR=pd.DataFrame(PA); FINAL=HIST[HIST.candidate.isin(sel)].merge(SUM,on='candidate').merge(PAIR,on='candidate',how='left').sort_values('tax_end_mean',ascending=False)
SUM.to_csv('tqqq_stage48_mc_summary.csv',index=False); PAIR.to_csv('tqqq_stage48_pairwise.csv',index=False); FINAL.to_csv('tqqq_stage48_final_rank.csv',index=False)
print('\n=== STAGE48 FINAL ===');print(FINAL[['candidate','pre_cagr','pre_mdd','tax_cagr','tax_end_mean','tax_end_median','tax_cagr_median','mdd_median','mdd_p05','p_end_better_than_aggr','end_ratio_median','end_ratio_p05']].head(20).to_string(index=False))
Path('tqqq_stage48_summary.json').write_text(json.dumps({'selected':sel,'final':FINAL.to_dict('records'),'caveats':['MC57 PIT/survivorship audit unresolved.','NQSAR historical proxy.','USDJPY/dividend tax not modeled.','Moving-block Monte Carlo is not a forecast distribution.']},ensure_ascii=False,indent=2,default=str))
