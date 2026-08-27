from __future__ import annotations
# Reuse Stage16 data/stress construction without re-copying it; only research branch.
from pathlib import Path
import json, numpy as np, pandas as pd

src=Path('research/tqqq_stage16_adversarial_bear_stress.py').read_text()
pre=src.split('# ---------- source data ----------')[0]
exec(compile(pre,'stage16-pre','exec'),globals())
run_strategy_old=run_strategy
# Load exactly the same source data construction used by Stage16.
data=src.split('# ---------- source data ----------')[1].split('CANDS={')[0]
exec(compile(data,'stage16-data','exec'),globals())
stress=src.split('# ---------- stress episode library ----------')[1].split('# ---------- 1000 adversarial 10-year paths ----------')[0]
exec(compile(stress,'stage16-stress','exec'),globals())

print('\n=== STAGE17 HIERARCHY / CRISIS FIX ===',flush=True)
SEED=160827; NSIM=1000; H=2520; BLOCK=120; COST=.0005

def run_hierarchy(A,p):
    ret=A['ret']; mcv=A['mc']; nq=A['nq']; panic=A['panic']; a50=A['a50']; a63=A['a63']; a200=A['a200']; a252=A['a252']; gte10=A['gte10']; lte21=A['lte21']; s50x=A['s50a']; dd=A['dd10']
    n=len(ret); rawbear=(~a200)&(~a252)
    bear5=np.zeros(n,bool)
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
        if panic[i] and s50x[i]<=-2: x=max(x,p.get('panic',1.0))
        base[i]=min(1.,x)

    risklock=slowA|fastA|mcA
    t=base.copy(); active=0; entry=0; seen_blue=False; cool_until=0
    for i in range(1,n):
        trRG=nq[i-1]==0 and nq[i]==2; trGB=nq[i-1]==2 and nq[i]==3; trBG=nq[i-1]==3 and nq[i]==2; trBY=nq[i-1]==3 and nq[i]==1
        if active==0:
            # RG is the ONLY tactical exception allowed while a risk lock is active.
            rgmc=p['rg_mc_slow'] if slowA[i] else 35
            if trRG and arm[i]<=-2 and mcv[i]>=rgmc and risklock[i] and i>=cool_until:
                active=1; entry=i+1; seen_blue=False
            # Independent GB may only start after all Slow/Fast/MC locks are cleared.
            elif trGB and arm[i]<=-1.5 and mcv[i]>=35 and (not risklock[i]):
                active=2; entry=i+1; seen_blue=True
        if active==1:
            if nq[i]==3: seen_blue=True
            hold=max(0,i-(entry-1)); ex=((nq[i] in (0,1)) or hold>=7)
            if ex:
                if (not seen_blue) and slowA[i] and p['cooldown']>0: cool_until=i+p['cooldown']
                active=0
            else:
                # Green->Blue cannot jump to full GB sizing while any lock is still active.
                if (not risklock[i]) and nq[i]==3:
                    active=2; entry=i+1
                    total=p['gb']
                else:
                    total=p['rg_slow'] if slowA[i] else p['rg_fast']
                if base[i]>=.999: total=1.
                t[i]=max(base[i],total)
        elif active==2:
            hold=max(0,i-(entry-1)); ex=risklock[i] or trBG or trBY or nq[i]==0 or hold>=20
            if ex: active=0
            else:
                total=p['gb']
                if base[i]>=.999: total=1.
                t[i]=max(base[i],total)

    eff=np.zeros(n); eff[2:]=t[:-2]
    turn=np.zeros(n); turn[2:]=np.abs(np.diff(t))[:-1]
    sr=eff*ret-turn*COST
    m=metrics(sr[2:]); m['avg_exp']=float(t.mean()); m['turnover']=float(np.abs(np.diff(t)).sum())
    return m

NEW={
 'H35_rg60': {'base':.35,'fast_dd':-.065,'fast_rec':4,'rg_slow':.60,'rg_fast':.80,'gb':.90,'rg_mc_slow':35,'cooldown':0,'panic':1.0},
 'H30_rg60': {'base':.30,'fast_dd':-.065,'fast_rec':4,'rg_slow':.60,'rg_fast':.80,'gb':.90,'rg_mc_slow':35,'cooldown':0,'panic':1.0},
 'H35_rg50': {'base':.35,'fast_dd':-.065,'fast_rec':4,'rg_slow':.50,'rg_fast':.80,'gb':.90,'rg_mc_slow':35,'cooldown':0,'panic':1.0},
 'H30_rg50': {'base':.30,'fast_dd':-.065,'fast_rec':4,'rg_slow':.50,'rg_fast':.80,'gb':.90,'rg_mc_slow':35,'cooldown':0,'panic':1.0},
 'H35_rg50_c20': {'base':.35,'fast_dd':-.065,'fast_rec':4,'rg_slow':.50,'rg_fast':.80,'gb':.90,'rg_mc_slow':35,'cooldown':20,'panic':1.0},
 'H30_rg50_c20': {'base':.30,'fast_dd':-.065,'fast_rec':4,'rg_slow':.50,'rg_fast':.80,'gb':.90,'rg_mc_slow':35,'cooldown':20,'panic':1.0},
 'H35_rg50_c20_mc40': {'base':.35,'fast_dd':-.065,'fast_rec':4,'rg_slow':.50,'rg_fast':.80,'gb':.90,'rg_mc_slow':40,'cooldown':20,'panic':1.0},
 'H30_rg50_c20_mc40': {'base':.30,'fast_dd':-.065,'fast_rec':4,'rg_slow':.50,'rg_fast':.80,'gb':.90,'rg_mc_slow':40,'cooldown':20,'panic':1.0},
}
OLD={
 'OLD_D35': {'base':.35,'fast_dd':-.065,'fast_rec':4,'rg':.80,'gb':.90,'bull_mc':65,'bull_exp':1.0,'panic_exp':1.0},
 'OLD_Balanced': {'base':.35,'fast_dd':-.075,'fast_rec':3,'rg':.70,'gb':1.0,'bull_mc':65,'bull_exp':1.0,'panic_exp':1.0},
}

hist=[]
for name,p in OLD.items(): hist.append({'candidate':name,**run_strategy_old(A,p)})
for name,p in NEW.items(): hist.append({'candidate':name,**run_hierarchy(A,p)})
HIST=pd.DataFrame(hist); HIST.to_csv('tqqq_stage17_historical.csv',index=False)
print('\n=== HISTORICAL ==='); print(HIST[['candidate','cagr','mdd','avg_exp','turnover']].to_string(index=False))

rng=np.random.default_rng(SEED); nblocks=int(np.ceil(H/BLOCK)); starts=rng.integers(0,L-BLOCK+1,size=(NSIM,nblocks)); offs=np.arange(BLOCK); paths=(starts[:,:,None]+offs).reshape(NSIM,-1)[:,:H]
families=np.array((['dotcom_like']*250)+(['gfc_like']*250)+(['covid_like']*250)+(['2022_like']*250),dtype=object); rng.shuffle(families)
rows=[]
for sim in range(NSIM):
    ix=paths[sim]; B={k:A[k][ix].copy() for k in KEYS}; fam=str(families[sim]); ep=make_episode(fam,rng); le=len(ep['ret'])
    if le>=H-504:
        cut=(le-(H-504))//2; ep={k:v[cut:cut+(H-504)] for k,v in ep.items()}; le=len(ep['ret'])
    pos=int(rng.integers(252,max(253,H-le-252)))
    for k in KEYS: B[k][pos:pos+le]=ep[k]
    for name,p in OLD.items(): rows.append({'sim':sim,'family':fam,'candidate':name,**run_strategy_old(B,p)})
    for name,p in NEW.items(): rows.append({'sim':sim,'family':fam,'candidate':name,**run_hierarchy(B,p)})
    if (sim+1)%100==0: print('[stage17]',sim+1,'/',NSIM,flush=True)
D=pd.DataFrame(rows); D.to_csv('tqqq_stage17_mc.csv',index=False)

def summ(g):
    cg=g.cagr.to_numpy(); md=g.mdd.to_numpy(); en=g.end.to_numpy(); q=lambda x,p:float(np.quantile(x,p))
    return {'n':len(g),'cagr_p05':q(cg,.05),'cagr_p25':q(cg,.25),'cagr_median':q(cg,.5),'cagr_p75':q(cg,.75),'mdd_p05':q(md,.05),'mdd_p25':q(md,.25),'mdd_median':q(md,.5),'mdd_p75':q(md,.75),'prob_mdd30plus':float(np.mean(md<-.30)),'prob_mdd35plus':float(np.mean(md<-.35)),'prob_mdd40plus':float(np.mean(md<-.40)),'prob_cagr20below':float(np.mean(cg<.20)),'prob_cagr25_mdd25':float(np.mean((cg>=.25)&(md>=-.25))),'end_median':q(en,.5)}
S=[]
for cand,g in D.groupby('candidate'):
    S.append({'candidate':cand,'family':'ALL',**summ(g)})
    for fam,hg in g.groupby('family'): S.append({'candidate':cand,'family':fam,**summ(hg)})
S=pd.DataFrame(S); S.to_csv('tqqq_stage17_summary.csv',index=False)
ALL=S[S.family=='ALL'].copy(); hm=HIST.set_index('candidate'); ALL['hist_cagr']=ALL.candidate.map(hm.cagr); ALL['hist_mdd']=ALL.candidate.map(hm.mdd)
ALL['robust_score']=ALL.cagr_median+.35*ALL.cagr_p05-.30*ALL.prob_mdd30plus-.20*ALL.prob_mdd35plus
ALL=ALL.sort_values('robust_score',ascending=False); ALL.to_csv('tqqq_stage17_ranked.csv',index=False)
print('\n=== STAGE17 ALL ==='); print(ALL[['candidate','hist_cagr','hist_mdd','cagr_p05','cagr_median','mdd_median','mdd_p05','prob_mdd30plus','prob_mdd35plus','prob_cagr20below','prob_cagr25_mdd25','robust_score']].to_string(index=False))
print('\n=== STAGE17 FAMILY MDD30+ ==='); print(S.pivot(index='candidate',columns='family',values='prob_mdd30plus').to_string())
Path('tqqq_stage17_summary.json').write_text(json.dumps({'seed':SEED,'nsim':NSIM,'historical':HIST.to_dict('records'),'all':ALL.to_dict('records'),'family':S[S.family!='ALL'].to_dict('records'),'note':'Stage17 fixes hierarchy: independent GB cannot override Slow/Fast/MC locks; RG remains the sole tactical risk-off exception, with reduced slow-bear sizing and optional failed-RG cooldown/MC threshold. Same Stage16 adversarial scenarios/seed for direct comparison.'},ensure_ascii=False,indent=2))
