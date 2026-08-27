from __future__ import annotations
from pathlib import Path
import json, numpy as np, pandas as pd

# Reuse Stage43 point-in-time VIX normalization + exact hierarchy/tax machinery, stop before its scan.
src=Path('research/tqqq_stage43_mc57_vix_2d_optimizer.py').read_text()
prefix=src.split('# ---------- historical scan ----------')[0]
exec(compile(prefix,'stage43-prefix','exec'),globals())

print('\n=== STAGE44 CONDITIONAL MC57 x VIX THROTTLE ===',flush=True)
NSIM=1000; TAXSIM=300; H=2520; BLOCK=120; SEED=440827

# Point-in-time MC deterioration features. For bootstrap they are sampled jointly with the source state.
MCD5=np.zeros(len(A['mc']),float); MCD10=np.zeros(len(A['mc']),float)
MCD5[5:]=A['mc'][5:]-A['mc'][:-5]; MCD10[10:]=A['mc'][10:]-A['mc'][:-10]

WARNSETS={
 'N': lambda B,d5,d10: np.zeros(len(B['mc']),bool),
 'L40': lambda B,d5,d10: B['mc']<40,
 'L45': lambda B,d5,d10: B['mc']<45,
 'D': lambda B,d5,d10: (d5<=-10)|(d10<=-15),
 'LD40': lambda B,d5,d10: (B['mc']<40)|(d5<=-10)|(d10<=-15),
 'LD45': lambda B,d5,d10: (B['mc']<45)|(d5<=-10)|(d10<=-15),
 'LD50S': lambda B,d5,d10: (B['mc']<50)|(d5<=-12)|(d10<=-18),
}
TRIGGERS={
 'A20': lambda vx,vp: vx>=20,
 'A22': lambda vx,vp: vx>=22,
 'P90': lambda vx,vp: vp>=.90,
 'A20P90': lambda vx,vp: (vx>=20)|(vp>=.90),
 'A22P90': lambda vx,vp: (vx>=22)|(vp>=.90),
}
CAPS={
 'C1':(.60,.50,.40),
 'C2':(.65,.50,.40),
 'C3':(.70,.50,.40),
 'C4':(.65,.55,.45),
 'C5':(.60,.45,.35),
}

def target44(B,s,cur,vx,vp,vz,d5,d10):
    if s['name']=='CURRENT': return cur['target'].copy()
    if s['name']=='BUYHOLD': return np.ones(len(B['ret']),float)
    if s['name']=='STAGE38': return make_target43(B,{'name':'STAGE38'},cur,vx,vp,vz)
    if s['name']=='VIX24_60': return make_target43(B,{'name':'VIX24_60'},cur,vx,vp,vz)
    t=make_target43(B,{'name':'STAGE38'},cur,vx,vp,vz)
    normal=(~cur['risklock'])&np.isclose(cur['target'],.30,atol=1e-9)
    warn=WARNSETS[s['warn']](B,d5,d10)
    trig=TRIGGERS[s['trig']](vx,vp)
    basecap,earlycap,severecap=CAPS[s['caps']]
    bc=np.full(len(t),basecap,float)
    if s['relax']:
        healthy=(B['mc']>=65)&(d5>=0)&(vp<.975)
        bc[healthy]=np.minimum(.80,bc[healthy]+.10)
    m=normal&(vx>=24); t[m]=np.minimum(t[m],bc[m])
    m=normal&warn&trig; t[m]=np.minimum(t[m],earlycap)
    severe=normal&((vx>=30)|(vp>=.975)); t[severe]=np.minimum(t[severe],severecap)
    return np.clip(t,0,1)

SPECS=[{'name':'CURRENT'},{'name':'BUYHOLD'},{'name':'STAGE38'},{'name':'VIX24_60'}]
for w in WARNSETS:
  for tr in TRIGGERS:
    for cp in CAPS:
      for relax in (False,True):
        SPECS.append({'name':f'{w}_{tr}_{cp}_R{int(relax)}','warn':w,'trig':tr,'caps':cp,'relax':relax})

curA=current_trace43(A); hist=[]; targets={}
for s in SPECS:
    t=target44(A,s,curA,VIXLVL,VIXPCT,VIXZ,MCD5,MCD10); targets[s['name']]=t
    m,_,_=from_target(A,t,COST); pre=account_end(A['ret'],t,COST,0.,DTS); aft=account_end(A['ret'],t,COST,TAX,DTS)
    ap=annual_dd_profile(strat_returns(A,t,COST),DTS)
    hist.append({'candidate':s['name'],'warn':s.get('warn',''),'trig':s.get('trig',''),'caps':s.get('caps',''),'relax':s.get('relax',False),
                 'pre_cagr':pre['cagr'],'pre_mdd':pre['mdd'],'tax_cagr':aft['cagr'],'tax_end':aft['end'],'avg_exp':m['avg_exp'],'turnover':m['turnover'],
                 'annual_mdd_mean':ap['annual_mdd_mean'],'annual_mdd_median':ap['annual_mdd_median'],'annual_dailydd_mean':ap['annual_dailydd_mean'],
                 'years_mdd20':ap['years_mdd20'],'years_mdd30':ap['years_mdd30']})
HIST=pd.DataFrame(hist); HIST.to_csv('tqqq_stage44_scan.csv',index=False)

# Select efficient frontier candidates, without demanding one exact DD target ex ante.
sel=['CURRENT','BUYHOLD','STAGE38','VIX24_60']
for capdd in (.30,.325,.35,.36,.375,.40):
    g=HIST[(~HIST.candidate.isin(sel))&(HIST.pre_mdd>=-capdd)].sort_values(['tax_cagr','annual_mdd_mean'],ascending=[False,False])
    sel+=g.head(4).candidate.tolist()
for capann in (.20,.21,.22,.23,.24):
    g=HIST[(~HIST.candidate.isin(sel))&(HIST.annual_mdd_mean>=-capann)].sort_values(['tax_cagr','pre_mdd'],ascending=[False,False])
    sel+=g.head(3).candidate.tolist()
scan=HIST[~HIST.candidate.eq('BUYHOLD')].copy()
scan['eff']=scan.tax_cagr-1.8*np.maximum(0.,-scan.pre_mdd-.35)-.75*np.maximum(0.,-scan.annual_mdd_mean-.23)-.25*np.maximum(0.,-scan.annual_mdd_median-.22)
sel+=scan.sort_values('eff',ascending=False).head(15).candidate.tolist(); sel=list(dict.fromkeys(sel))
SMAP={s['name']:s for s in SPECS if s['name'] in sel}; print('SELECTED',len(sel),sel,flush=True)

# Subperiods and costs.
YY=DTS.dt.year.to_numpy(); PER=[('2011-2015',2011,2015),('2016-2018',2016,2018),('2019-2021',2019,2021),('2022-2024',2022,2024),('2025-2026',2025,2026)]
WF=[]
for nm in sel:
  t=targets[nm]
  for lab,a,b in PER:
    ids=np.flatnonzero((YY>=a)&(YY<=b)); rr=A['ret'][ids]; tt=t[ids]; dd=DTS.iloc[ids].reset_index(drop=True)
    pre=account_end(rr,tt,COST,0.,dd); aft=account_end(rr,tt,COST,TAX,dd); WF.append({'candidate':nm,'period':lab,'pre_cagr':pre['cagr'],'pre_mdd':pre['mdd'],'tax_cagr':aft['cagr']})
WF=pd.DataFrame(WF); WF.to_csv('tqqq_stage44_subperiods.csv',index=False)
CC=[]
for nm in sel:
  t=targets[nm]
  for bps in (5,10,20):
    c=bps/10000.; pre=account_end(A['ret'],t,c,0.,DTS); aft=account_end(A['ret'],t,c,TAX,DTS); CC.append({'candidate':nm,'cost_bps':bps,'pre_cagr':pre['cagr'],'pre_mdd':pre['mdd'],'tax_cagr':aft['cagr']})
COSTS=pd.DataFrame(CC); COSTS.to_csv('tqqq_stage44_costs.csv',index=False)

# Normal matched-state moving-block bootstrap. MC deltas/VIX are sampled with the same historical indices.
L=len(A['ret']); nb=int(np.ceil(H/BLOCK)); offs=np.arange(BLOCK); rng=np.random.default_rng(SEED); starts=rng.integers(0,L-BLOCK+1,size=(NSIM,nb)); paths=(starts[:,:,None]+offs).reshape(NSIM,-1)[:,:H]
normal=[]; ntax=[]
for z in range(NSIM):
    ix=paths[z]; B={k:A[k][ix].copy() for k in KEYS}; vx=VIXLVL[ix]; vp=VIXPCT[ix]; vz=VIXZ[ix]; d5=MCD5[ix]; d10=MCD10[ix]; cur=current_trace43(B)
    for nm,s in SMAP.items():
        t=target44(B,s,cur,vx,vp,vz,d5,d10); m,_,_=from_target(B,t,COST); normal.append({'sim':z,'candidate':nm,**m})
        if z<TAXSIM:
            pre=account_end(B['ret'],t,COST,0.,None); aft=account_end(B['ret'],t,COST,TAX,None); ntax.append({'sim':z,'candidate':nm,'tax_cagr':aft['cagr'],'pre_mdd':pre['mdd']})
    if (z+1)%100==0: print('[normal44]',z+1,'/',NSIM,flush=True)
NORMAL=pd.DataFrame(normal); NORMAL.to_csv('tqqq_stage44_normal_mc.csv',index=False); NTAX=pd.DataFrame(ntax); NTAX.to_csv('tqqq_stage44_normal_tax_mc.csv',index=False)

def q(x,p):return float(np.quantile(np.asarray(x,float),p))
SUM=[]
for nm,g in NORMAL.groupby('candidate'):
    SUM.append({'candidate':nm,'cagr_p05':q(g.cagr,.05),'cagr_median':q(g.cagr,.5),'mdd_p05':q(g.mdd,.05),'mdd_median':q(g.mdd,.5),'p_mdd35':float(np.mean(g.mdd<-.35)),'p_mdd40':float(np.mean(g.mdd<-.40))})
SUM=pd.DataFrame(SUM); SUM.to_csv('tqqq_stage44_mc_summary.csv',index=False)
TS=[]
for nm,g in NTAX.groupby('candidate'):
    TS.append({'candidate':nm,'tax_p05':q(g.tax_cagr,.05),'tax_median':q(g.tax_cagr,.5),'tax_p95':q(g.tax_cagr,.95),'prob_tax30':float(np.mean(g.tax_cagr>=.30)),'mdd_p05':q(g.pre_mdd,.05),'mdd_median':q(g.pre_mdd,.5)})
TAXMC=pd.DataFrame(TS); TAXMC.to_csv('tqqq_stage44_tax_mc_summary.csv',index=False)

R=[]
for nm in sel:
    h=HIST[HIST.candidate.eq(nm)].iloc[0]; tx=TAXMC[TAXMC.candidate.eq(nm)].iloc[0]; sm=SUM[SUM.candidate.eq(nm)].iloc[0]
    score=(h.tax_cagr+.85*tx.tax_median+.15*tx.tax_p05-1.9*max(0.,-h.pre_mdd-.35)-.8*max(0.,-sm.mdd_median-.40)-.55*max(0.,-h.annual_mdd_mean-.23)-.2*max(0.,-h.annual_mdd_median-.22))
    R.append({'candidate':nm,'hist_tax_cagr':h.tax_cagr,'hist_pre_cagr':h.pre_cagr,'hist_mdd':h.pre_mdd,'annual_mdd_mean':h.annual_mdd_mean,'annual_mdd_median':h.annual_mdd_median,'annual_dailydd_mean':h.annual_dailydd_mean,'years_mdd20':int(h.years_mdd20),'years_mdd30':int(h.years_mdd30),'tax_mc_median':tx.tax_median,'tax_mc_p05':tx.tax_p05,'prob_tax30':tx.prob_tax30,'normal_mdd_median':sm.mdd_median,'normal_mdd_p05':sm.mdd_p05,'score':score})
R=pd.DataFrame(R).sort_values('score',ascending=False); R.to_csv('tqqq_stage44_final_rank.csv',index=False)
print('\n=== HIST EFFICIENT ===');print(HIST.sort_values('tax_cagr',ascending=False).head(40)[['candidate','pre_cagr','pre_mdd','tax_cagr','annual_mdd_mean','annual_mdd_median','years_mdd20','years_mdd30','avg_exp','turnover']].to_string(index=False));print('\n=== FINAL ===');print(R.to_string(index=False));print('\n=== TAX MC ===');print(TAXMC.sort_values('tax_median',ascending=False).to_string(index=False))
Path('tqqq_stage44_summary.json').write_text(json.dumps({'historical':HIST.to_dict('records'),'selected':sel,'subperiods':WF.to_dict('records'),'costs':COSTS.to_dict('records'),'mc_summary':SUM.to_dict('records'),'tax_mc_summary':TAXMC.to_dict('records'),'final_rank':R.to_dict('records'),'rule':'Stage38 remains the growth engine. VIX24 cap is conditioned/refined using MC57 level and 5/10-day deterioration plus point-in-time VIX percentile. Only the exact normal-30% sleeve is capped; risk locks, StrongBull, RG, GB and VIX Panic stay untouched.','caveats':['MC57 PIT/survivorship audit unresolved.','NQSAR history proxy.','USDJPY/dividend tax not modeled.','Bootstrap is robustness stress, not forecast probability.']},ensure_ascii=False,indent=2,default=str))
