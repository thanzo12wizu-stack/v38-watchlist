from __future__ import annotations
from pathlib import Path
import json, numpy as np, pandas as pd

# Load Stage17 hierarchy function + identical source state data, but do NOT inject adversarial episodes.
src=Path('research/tqqq_stage17_hierarchy_crisis_fix.py').read_text()
prefix=src.split('NEW={')[0]
exec(compile(prefix,'stage17-prefix','exec'),globals())
print('\n=== STAGE19 FINAL CANDIDATE NORMAL MC ===',flush=True)
NSIM=1000; H=2520; BLOCK=120; SEED=190827

OLD={
 'OLD_D35': {'base':.35,'fast_dd':-.065,'fast_rec':4,'rg':.80,'gb':.90,'bull_mc':65,'bull_exp':1.0,'panic_exp':1.0},
 'OLD_Balanced': {'base':.35,'fast_dd':-.075,'fast_rec':3,'rg':.70,'gb':1.0,'bull_mc':65,'bull_exp':1.0,'panic_exp':1.0},
}
NEW={
 'H30_MC40': {'base':.30,'fast_dd':-.065,'fast_rec':4,'rg_slow':.50,'rg_fast':.80,'gb':.90,'rg_mc_slow':40,'cooldown':20,'panic':1.0},
 'H35_MC40': {'base':.35,'fast_dd':-.065,'fast_rec':4,'rg_slow':.50,'rg_fast':.80,'gb':.90,'rg_mc_slow':40,'cooldown':20,'panic':1.0},
}

hist=[]
for name,p in OLD.items(): hist.append({'candidate':name,**run_strategy_old(A,p)})
for name,p in NEW.items(): hist.append({'candidate':name,**run_hierarchy(A,p)})
HIST=pd.DataFrame(hist); HIST.to_csv('tqqq_stage19_historical.csv',index=False)
print('\n=== HISTORICAL ==='); print(HIST[['candidate','cagr','mdd','avg_exp','turnover']].to_string(index=False))

rng=np.random.default_rng(SEED); nblocks=int(np.ceil(H/BLOCK)); starts=rng.integers(0,L-BLOCK+1,size=(NSIM,nblocks)); offs=np.arange(BLOCK); paths=(starts[:,:,None]+offs).reshape(NSIM,-1)[:,:H]
rows=[]
for sim in range(NSIM):
    ix=paths[sim]; B={k:A[k][ix].copy() for k in KEYS}
    for name,p in OLD.items(): rows.append({'sim':sim,'candidate':name,**run_strategy_old(B,p)})
    for name,p in NEW.items(): rows.append({'sim':sim,'candidate':name,**run_hierarchy(B,p)})
D=pd.DataFrame(rows); D.to_csv('tqqq_stage19_mc.csv',index=False)
def summ(g):
    cg=g.cagr.to_numpy(); md=g.mdd.to_numpy(); en=g.end.to_numpy(); q=lambda x,p:float(np.quantile(x,p)); cbin=np.floor(cg/.02)*.02; mbin=np.floor((-md)/.02)*.02
    return {'n':len(g),'cagr_mode_lo':float(pd.Series(cbin).value_counts().idxmax()),'cagr_mode_hi':float(pd.Series(cbin).value_counts().idxmax()+.02),'mdd_mode_abs_lo':float(pd.Series(mbin).value_counts().idxmax()),'mdd_mode_abs_hi':float(pd.Series(mbin).value_counts().idxmax()+.02),'cagr_p05':q(cg,.05),'cagr_p25':q(cg,.25),'cagr_median':q(cg,.5),'cagr_p75':q(cg,.75),'cagr_p95':q(cg,.95),'mdd_p05':q(md,.05),'mdd_p25':q(md,.25),'mdd_median':q(md,.5),'mdd_p75':q(md,.75),'mdd_p95':q(md,.95),'end_p05':q(en,.05),'end_median':q(en,.5),'end_p95':q(en,.95),'prob_mdd30plus':float(np.mean(md<-.30)),'prob_mdd35plus':float(np.mean(md<-.35)),'prob_cagr20below':float(np.mean(cg<.20)),'prob_cagr25_mdd25':float(np.mean((cg>=.25)&(md>=-.25))),'prob_cagr28_mdd22':float(np.mean((cg>=.28)&(md>=-.22)))}
S=[]
for cand,g in D.groupby('candidate'): S.append({'candidate':cand,**summ(g)})
S=pd.DataFrame(S); hm=HIST.set_index('candidate'); S['hist_cagr']=S.candidate.map(hm.cagr); S['hist_mdd']=S.candidate.map(hm.mdd); S.to_csv('tqqq_stage19_summary.csv',index=False)
print('\n=== NORMAL 1000-PATH SUMMARY ==='); print(S[['candidate','hist_cagr','hist_mdd','cagr_mode_lo','cagr_mode_hi','cagr_p05','cagr_median','mdd_mode_abs_lo','mdd_mode_abs_hi','mdd_median','mdd_p05','prob_mdd30plus','prob_mdd35plus','prob_cagr20below','prob_cagr25_mdd25','prob_cagr28_mdd22']].to_string(index=False))
Path('tqqq_stage19_summary.json').write_text(json.dumps({'seed':SEED,'nsim':NSIM,'block':BLOCK,'horizon_days':H,'historical':HIST.to_dict('records'),'summary':S.to_dict('records'),'note':'Unmodified 120-day joint-state moving-block bootstrap. No adversarial episode injection. Same state hierarchy as Stage17: GB cannot override Slow/Fast/MC locks; RG is the sole risk-off tactical exception, with Slow-Bear MC>=40, 50% sizing, 20-day cooldown after failed RG, Fast/MC-only RG 80%, GB90% after all locks clear.'},ensure_ascii=False,indent=2))
