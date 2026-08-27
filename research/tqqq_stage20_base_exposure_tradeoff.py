from __future__ import annotations
from pathlib import Path
import json, numpy as np, pandas as pd

src=Path('research/tqqq_stage17_hierarchy_crisis_fix.py').read_text()
prefix=src.split('NEW={')[0]
exec(compile(prefix,'stage17-prefix','exec'),globals())
stress_defs=Path('research/tqqq_stage16_adversarial_bear_stress.py').read_text().split('# ---------- stress episode library ----------')[1].split('# ---------- 1000 adversarial 10-year paths ----------')[0]
exec(compile(stress_defs,'stage16-stress','exec'),globals())
print('\n=== STAGE20 BASE EXPOSURE TRADEOFF ===',flush=True)
H=2520; BLOCK=120; NSIM=1000
CANDS={
 'H30': {'base':.30,'fast_dd':-.065,'fast_rec':4,'rg_slow':.50,'rg_fast':.80,'gb':.90,'rg_mc_slow':40,'cooldown':20,'panic':1.0},
 'H32_5': {'base':.325,'fast_dd':-.065,'fast_rec':4,'rg_slow':.50,'rg_fast':.80,'gb':.90,'rg_mc_slow':40,'cooldown':20,'panic':1.0},
 'H35': {'base':.35,'fast_dd':-.065,'fast_rec':4,'rg_slow':.50,'rg_fast':.80,'gb':.90,'rg_mc_slow':40,'cooldown':20,'panic':1.0},
}
hist=[]
for n,p in CANDS.items(): hist.append({'candidate':n,**run_hierarchy(A,p)})
HIST=pd.DataFrame(hist); print('\nHIST'); print(HIST.to_string(index=False)); HIST.to_csv('tqqq_stage20_historical.csv',index=False)

def summarise(D,kind):
    out=[]
    for cand,g in D.groupby('candidate'):
        cg=g.cagr.to_numpy(); md=g.mdd.to_numpy(); q=lambda x,p:float(np.quantile(x,p))
        out.append({'set':kind,'candidate':cand,'cagr_p05':q(cg,.05),'cagr_median':q(cg,.5),'cagr_p95':q(cg,.95),'mdd_p05':q(md,.05),'mdd_median':q(md,.5),'mdd_p95':q(md,.95),'prob_mdd30plus':float(np.mean(md<-.30)),'prob_mdd35plus':float(np.mean(md<-.35)),'prob_cagr20below':float(np.mean(cg<.20)),'prob_cagr25_mdd25':float(np.mean((cg>=.25)&(md>=-.25))),'prob_cagr28_mdd22':float(np.mean((cg>=.28)&(md>=-.22)))})
    return pd.DataFrame(out)

# Normal joint-state bootstrap, same seed as Stage19 for exact H30/H35 cross-check.
rng=np.random.default_rng(190827); nblocks=int(np.ceil(H/BLOCK)); starts=rng.integers(0,L-BLOCK+1,size=(NSIM,nblocks)); offs=np.arange(BLOCK); paths=(starts[:,:,None]+offs).reshape(NSIM,-1)[:,:H]
r=[]
for sim in range(NSIM):
    B={k:A[k][paths[sim]].copy() for k in KEYS}
    for n,p in CANDS.items(): r.append({'sim':sim,'candidate':n,**run_hierarchy(B,p)})
NORMAL=pd.DataFrame(r); SN=summarise(NORMAL,'normal'); NORMAL.to_csv('tqqq_stage20_normal_mc.csv',index=False)

# Same adversarial family mix/seed as Stage17/18.
rng=np.random.default_rng(160827); starts=rng.integers(0,L-BLOCK+1,size=(NSIM,nblocks)); paths=(starts[:,:,None]+offs).reshape(NSIM,-1)[:,:H]
families=np.array((['dotcom_like']*250)+(['gfc_like']*250)+(['covid_like']*250)+(['2022_like']*250),dtype=object); rng.shuffle(families)
r=[]
for sim in range(NSIM):
    B={k:A[k][paths[sim]].copy() for k in KEYS}; fam=str(families[sim]); ep=make_episode(fam,rng); le=len(ep['ret'])
    if le>=H-504:
        cut=(le-(H-504))//2; ep={k:v[cut:cut+(H-504)] for k,v in ep.items()}; le=len(ep['ret'])
    pos=int(rng.integers(252,max(253,H-le-252)))
    for k in KEYS: B[k][pos:pos+le]=ep[k]
    for n,p in CANDS.items(): r.append({'sim':sim,'family':fam,'candidate':n,**run_hierarchy(B,p)})
    if (sim+1)%200==0: print('[adv]',sim+1,flush=True)
ADV=pd.DataFrame(r); SA=summarise(ADV,'adversarial'); ADV.to_csv('tqqq_stage20_adversarial_mc.csv',index=False)
# Family p(MDD>30)
fam=[]
for (cand,f),g in ADV.groupby(['candidate','family']): fam.append({'candidate':cand,'family':f,'prob_mdd30plus':float(np.mean(g.mdd.to_numpy()<-.30)),'cagr_median':float(np.median(g.cagr)),'mdd_median':float(np.median(g.mdd))})
FAM=pd.DataFrame(fam); FAM.to_csv('tqqq_stage20_family.csv',index=False)
S=pd.concat([SN,SA],ignore_index=True); hm=HIST.set_index('candidate'); S['hist_cagr']=S.candidate.map(hm.cagr); S['hist_mdd']=S.candidate.map(hm.mdd); S.to_csv('tqqq_stage20_summary.csv',index=False)
print('\nSUMMARY'); print(S[['set','candidate','hist_cagr','hist_mdd','cagr_p05','cagr_median','mdd_median','mdd_p05','prob_mdd30plus','prob_mdd35plus','prob_cagr20below','prob_cagr25_mdd25','prob_cagr28_mdd22']].to_string(index=False)); print('\nFAMILY P30'); print(FAM.pivot(index='candidate',columns='family',values='prob_mdd30plus').to_string())
Path('tqqq_stage20_summary.json').write_text(json.dumps({'historical':HIST.to_dict('records'),'summary':S.to_dict('records'),'family':FAM.to_dict('records'),'note':'Only base exposure differs: 30%, 32.5%, 35%. All other hierarchy/risk/NQSAR rules fixed. Normal MC uses Stage19 seed; adversarial MC uses Stage17/18 seed and identical synthetic Bear generation.'},ensure_ascii=False,indent=2))
