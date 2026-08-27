from __future__ import annotations
from pathlib import Path
import json, numpy as np, pandas as pd

# Reuse Stage17 setup/data/stress definitions, stop before its candidate grid.
src=Path('research/tqqq_stage17_hierarchy_crisis_fix.py').read_text()
prefix=src.split('NEW={')[0]
exec(compile(prefix,'stage17-prefix','exec'),globals())
print('\n=== STAGE18 REGIME-SIZED REENTRY ===',flush=True)
SEED=160827; NSIM=1000; H=2520; BLOCK=120; COST=.0005

def slow_rg_size(mc,p):
    # MC-confidence ramp while Slow Bear is still latched.
    if mc < p['slow_mc1']: return 0.0
    if mc < p['slow_mc2']: return p['slow_x1']
    if mc < p['slow_mc3']: return p['slow_x2']
    return p['slow_x3']

def run_ramp(A,p):
    ret=A['ret']; mcv=A['mc']; nq=A['nq']; panic=A['panic']; a50=A['a50']; a63=A['a63']; a200=A['a200']; a252=A['a252']; gte10=A['gte10']; lte21=A['lte21']; s50x=A['s50a']; dd=A['dd10']
    n=len(ret); rawbear=(~a200)&(~a252); bear5=np.zeros(n,bool)
    for i in range(4,n): bear5[i]=rawbear[i-4:i+1].all()
    score3=(a50.astype(int)+a63.astype(int)+(mcv>=35).astype(int)+(nq!=0).astype(int))>=3
    fr=int(p['fast_rec']); rec=np.zeros(n,bool)
    for i in range(fr-1,n): rec[i]=gte10[i-fr+1:i+1].all()
    arm=np.empty(n,float)
    for i in range(n): arm[i]=np.min(s50x[max(0,i-19):i+1])
    base=np.zeros(n,float); slowA=np.zeros(n,bool); fastA=np.zeros(n,bool); mcA=np.zeros(n,bool)
    slow=fast=mclock=False
    for i in range(n):
        if bear5[i]: slow=True
        if slow and (not rawbear[i]) and score3[i] and mcv[i]>=35: slow=False
        if mcv[i]<25: mclock=True
        if mclock and mcv[i]>=35 and score3[i] and nq[i]!=0: mclock=False
        if dd[i]<=p['fast_dd'] and lte21[i]: fast=True
        if fast and rec[i]: fast=False
        slowA[i]=slow; fastA[i]=fast; mcA[i]=mclock
        x=0. if (slow or fast or mclock) else p['base']
        if x>0 and mcv[i]>=65 and nq[i]==3 and a50[i] and a63[i] and s50x[i]<=2.5: x=1.0
        if panic[i] and s50x[i]<=-2:
            px=p['panic_slow'] if slow else p['panic_fast']
            x=max(x,px)
        base[i]=min(1.,x)
    risklock=slowA|fastA|mcA
    t=base.copy(); active=0; entry=0; seen_blue=False; cool_until=0
    for i in range(1,n):
        trRG=nq[i-1]==0 and nq[i]==2; trGB=nq[i-1]==2 and nq[i]==3; trBG=nq[i-1]==3 and nq[i]==2; trBY=nq[i-1]==3 and nq[i]==1
        if active==0:
            sz=slow_rg_size(mcv[i],p) if slowA[i] else p['fast_rg']
            if trRG and arm[i]<=-2 and risklock[i] and i>=cool_until and mcv[i]>=35 and sz>0:
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
                    total=slow_rg_size(mcv[i],p) if slowA[i] else p['fast_rg']
                    if total<=0: active=0; continue
                if base[i]>=.999: total=1.
                t[i]=max(base[i],total)
        elif active==2:
            hold=max(0,i-(entry-1)); ex=risklock[i] or trBG or trBY or nq[i]==0 or hold>=20
            if ex: active=0
            else:
                total=p['gb'];
                if base[i]>=.999: total=1.
                t[i]=max(base[i],total)
    eff=np.zeros(n); eff[2:]=t[:-2]; turn=np.zeros(n); turn[2:]=np.abs(np.diff(t))[:-1]
    sr=eff*ret-turn*COST; m=metrics(sr[2:]); m['avg_exp']=float(t.mean()); m['turnover']=float(np.abs(np.diff(t)).sum()); return m

CANDS={
 'R30_bal': {'base':.30,'fast_dd':-.065,'fast_rec':4,'fast_rg':.80,'gb':.90,'slow_mc1':40,'slow_mc2':45,'slow_mc3':50,'slow_x1':.25,'slow_x2':.50,'slow_x3':.70,'cooldown':20,'panic_slow':.80,'panic_fast':1.0},
 'R35_bal': {'base':.35,'fast_dd':-.065,'fast_rec':4,'fast_rg':.80,'gb':.90,'slow_mc1':40,'slow_mc2':45,'slow_mc3':50,'slow_x1':.25,'slow_x2':.50,'slow_x3':.70,'cooldown':20,'panic_slow':.80,'panic_fast':1.0},
 'R30_con': {'base':.30,'fast_dd':-.065,'fast_rec':4,'fast_rg':.70,'gb':.90,'slow_mc1':45,'slow_mc2':50,'slow_mc3':55,'slow_x1':.25,'slow_x2':.40,'slow_x3':.60,'cooldown':20,'panic_slow':.80,'panic_fast':1.0},
 'R35_con': {'base':.35,'fast_dd':-.065,'fast_rec':4,'fast_rg':.70,'gb':.90,'slow_mc1':45,'slow_mc2':50,'slow_mc3':55,'slow_x1':.25,'slow_x2':.40,'slow_x3':.60,'cooldown':20,'panic_slow':.80,'panic_fast':1.0},
 'R30_noslow': {'base':.30,'fast_dd':-.065,'fast_rec':4,'fast_rg':.80,'gb':.90,'slow_mc1':101,'slow_mc2':102,'slow_mc3':103,'slow_x1':0.,'slow_x2':0.,'slow_x3':0.,'cooldown':20,'panic_slow':.80,'panic_fast':1.0},
 'R35_noslow': {'base':.35,'fast_dd':-.065,'fast_rec':4,'fast_rg':.80,'gb':.90,'slow_mc1':101,'slow_mc2':102,'slow_mc3':103,'slow_x1':0.,'slow_x2':0.,'slow_x3':0.,'cooldown':20,'panic_slow':.80,'panic_fast':1.0},
 'R30_bal_p100': {'base':.30,'fast_dd':-.065,'fast_rec':4,'fast_rg':.80,'gb':.90,'slow_mc1':40,'slow_mc2':45,'slow_mc3':50,'slow_x1':.25,'slow_x2':.50,'slow_x3':.70,'cooldown':20,'panic_slow':1.0,'panic_fast':1.0},
 'R35_bal_p100': {'base':.35,'fast_dd':-.065,'fast_rec':4,'fast_rg':.80,'gb':.90,'slow_mc1':40,'slow_mc2':45,'slow_mc3':50,'slow_x1':.25,'slow_x2':.50,'slow_x3':.70,'cooldown':20,'panic_slow':1.0,'panic_fast':1.0},
}
REF={
 'OLD_D35': {'base':.35,'fast_dd':-.065,'fast_rec':4,'rg':.80,'gb':.90,'bull_mc':65,'bull_exp':1.0,'panic_exp':1.0},
 'OLD_Balanced': {'base':.35,'fast_dd':-.075,'fast_rec':3,'rg':.70,'gb':1.0,'bull_mc':65,'bull_exp':1.0,'panic_exp':1.0},
}
hist=[]
for name,p in REF.items(): hist.append({'candidate':name,**run_strategy_old(A,p)})
for name,p in CANDS.items(): hist.append({'candidate':name,**run_ramp(A,p)})
HIST=pd.DataFrame(hist); HIST.to_csv('tqqq_stage18_historical.csv',index=False); print('\n=== HISTORICAL ==='); print(HIST[['candidate','cagr','mdd','avg_exp','turnover']].to_string(index=False))

rng=np.random.default_rng(SEED); nblocks=int(np.ceil(H/BLOCK)); starts=rng.integers(0,L-BLOCK+1,size=(NSIM,nblocks)); offs=np.arange(BLOCK); paths=(starts[:,:,None]+offs).reshape(NSIM,-1)[:,:H]
families=np.array((['dotcom_like']*250)+(['gfc_like']*250)+(['covid_like']*250)+(['2022_like']*250),dtype=object); rng.shuffle(families)
rows=[]
for sim in range(NSIM):
    ix=paths[sim]; B={k:A[k][ix].copy() for k in KEYS}; fam=str(families[sim]); ep=make_episode(fam,rng); le=len(ep['ret'])
    if le>=H-504:
        cut=(le-(H-504))//2; ep={k:v[cut:cut+(H-504)] for k,v in ep.items()}; le=len(ep['ret'])
    pos=int(rng.integers(252,max(253,H-le-252)))
    for k in KEYS: B[k][pos:pos+le]=ep[k]
    for name,p in REF.items(): rows.append({'sim':sim,'family':fam,'candidate':name,**run_strategy_old(B,p)})
    for name,p in CANDS.items(): rows.append({'sim':sim,'family':fam,'candidate':name,**run_ramp(B,p)})
    if (sim+1)%100==0: print('[stage18]',sim+1,'/',NSIM,flush=True)
D=pd.DataFrame(rows); D.to_csv('tqqq_stage18_mc.csv',index=False)
def summ(g):
    cg=g.cagr.to_numpy(); md=g.mdd.to_numpy(); q=lambda x,p:float(np.quantile(x,p))
    return {'n':len(g),'cagr_p05':q(cg,.05),'cagr_p25':q(cg,.25),'cagr_median':q(cg,.5),'cagr_p75':q(cg,.75),'mdd_p05':q(md,.05),'mdd_p25':q(md,.25),'mdd_median':q(md,.5),'mdd_p75':q(md,.75),'prob_mdd30plus':float(np.mean(md<-.30)),'prob_mdd35plus':float(np.mean(md<-.35)),'prob_mdd40plus':float(np.mean(md<-.40)),'prob_cagr20below':float(np.mean(cg<.20)),'prob_cagr25_mdd25':float(np.mean((cg>=.25)&(md>=-.25)))}
S=[]
for cand,g in D.groupby('candidate'):
    S.append({'candidate':cand,'family':'ALL',**summ(g)})
    for fam,hg in g.groupby('family'): S.append({'candidate':cand,'family':fam,**summ(hg)})
S=pd.DataFrame(S); S.to_csv('tqqq_stage18_summary.csv',index=False)
ALL=S[S.family=='ALL'].copy(); hm=HIST.set_index('candidate'); ALL['hist_cagr']=ALL.candidate.map(hm.cagr); ALL['hist_mdd']=ALL.candidate.map(hm.mdd); ALL['robust_score']=ALL.cagr_median+.35*ALL.cagr_p05-.30*ALL.prob_mdd30plus-.20*ALL.prob_mdd35plus; ALL=ALL.sort_values('robust_score',ascending=False); ALL.to_csv('tqqq_stage18_ranked.csv',index=False)
print('\n=== STAGE18 ALL ==='); print(ALL[['candidate','hist_cagr','hist_mdd','cagr_p05','cagr_median','mdd_median','mdd_p05','prob_mdd30plus','prob_mdd35plus','prob_cagr20below','prob_cagr25_mdd25','robust_score']].to_string(index=False)); print('\n=== FAMILY MDD30+ ==='); print(S.pivot(index='candidate',columns='family',values='prob_mdd30plus').to_string())
Path('tqqq_stage18_summary.json').write_text(json.dumps({'seed':SEED,'nsim':NSIM,'historical':HIST.to_dict('records'),'all':ALL.to_dict('records'),'family':S[S.family!='ALL'].to_dict('records'),'note':'Stage18 sizes RG differently by regime. During latched Slow Bear, RG exposure ramps with MC confidence; during Fast/MC-only risk locks it uses a separate fast-RG size. GB can only run after all locks clear. Slow-bear panic is also capped separately. Same Stage16 adversarial scenarios and seed.'},ensure_ascii=False,indent=2))
