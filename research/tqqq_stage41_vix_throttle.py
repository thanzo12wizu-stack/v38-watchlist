from __future__ import annotations
from pathlib import Path
import json, numpy as np, pandas as pd

src=Path('research/tqqq_stage36_goal_first_taxaware.py').read_text()
prefix=src.split('SPECS = [{"name":"CURRENT"}')[0]
exec(compile(prefix,'stage36-prefix','exec'),globals())

print('\n=== STAGE41 VIX THROTTLE ===',flush=True)
NSIM=1000; TAXSIM=300; H=2520; BLOCK=120; SEEDN=410827
# Align signal-time VIX close to the exact Stage36 date frame.
VIXLVL=vix['Close'].astype(float).reindex(pd.DatetimeIndex(DTS)).ffill().to_numpy(float)

# Exact Stage38 best target.
def stage38_target(B,cur=None):
    if cur is None: cur=current_trace(B)
    t=cur['target'].copy(); normal=(~cur['risklock'])&np.isclose(t,.30,atol=1e-9)
    x=np.full(len(t),.80); x[B['lte21']]=np.minimum(x[B['lte21']],.45)
    weak=(~B['a50'])&(~B['a63']); x[weak]=np.minimum(x[weak],.35)
    pre=(B['dd10']<=-.04)&B['lte21']; x[pre]=np.minimum(x[pre],.35)
    t[normal]=np.maximum(t[normal],x[normal])
    hit=normal&(B['a200']&B['a252']&(B['mc']>=35)); t[hit]=np.maximum(t[hit],.90)
    return np.clip(t,0,1)

def target41(B,vx,s,cur=None):
    if s['name']=='CURRENT': return (cur if cur is not None else current_trace(B))['target'].copy()
    if s['name']=='BUYHOLD': return np.ones(len(B['ret']),float)
    t=stage38_target(B,cur)
    if s['name']=='STAGE38': return t
    # Cap only the exposure that Stage38 raised above the defensive hierarchy base; never interfere with RG/GB/Panic/StrongBull explicit sleeves.
    if cur is None: cur=current_trace(B)
    normal=(~cur['risklock'])&np.isclose(cur['target'],.30,atol=1e-9)
    hot=normal & (vx>=s['vix'])
    t[hot]=np.minimum(t[hot],s['cap'])
    # Optional stronger cap when VIX is another 5 points higher.
    if s['cap2']<s['cap']:
        hotter=normal & (vx>=s['vix']+5)
        t[hotter]=np.minimum(t[hotter],s['cap2'])
    return np.clip(t,0,1)

SPECS=[{'name':'CURRENT'},{'name':'BUYHOLD'},{'name':'STAGE38'}]
for th in (18.,20.,22.,24.,26.,28.,30.):
  for cap in (.40,.50,.60,.70):
    for cap2 in (.30,.40,.50,.60):
      if cap2>cap: continue
      nm=f'V{int(th)}_C{int(cap*100)}_H{int(cap2*100)}'
      SPECS.append({'name':nm,'vix':th,'cap':cap,'cap2':cap2})

curA=current_trace(A); hist=[]; targets={}
for s in SPECS:
    t=target41(A,VIXLVL,s,curA); targets[s['name']]=t; m,_,_=from_target(A,t,COST); pre=account_end(A['ret'],t,COST,0.,DTS); aft=account_end(A['ret'],t,COST,TAX,DTS)
    hist.append({'candidate':s['name'],'vix':s.get('vix',np.nan),'cap':s.get('cap',np.nan),'cap2':s.get('cap2',np.nan),'pre_cagr':pre['cagr'],'pre_mdd':pre['mdd'],'tax_cagr':aft['cagr'],'tax_end':aft['end'],'avg_exp':m['avg_exp'],'turnover':m['turnover']})
HIST=pd.DataFrame(hist); HIST.to_csv('tqqq_stage41_scan.csv',index=False)

sel=['CURRENT','BUYHOLD','STAGE38']
for capdd in (.30,.325,.35,.375,.40):
    g=HIST[(HIST.candidate.str.startswith('V'))&(HIST.pre_mdd>=-capdd)].sort_values(['tax_cagr','pre_mdd'],ascending=[False,False]); sel+=g.head(3).candidate.tolist()
g=HIST[(HIST.candidate.str.startswith('V'))&(HIST.tax_cagr>=.30)&(HIST.pre_mdd>=-.40)].sort_values(['pre_mdd','tax_cagr'],ascending=[False,False]); sel+=g.head(8).candidate.tolist()
sel=list(dict.fromkeys(sel)); SMAP={s['name']:s for s in SPECS if s['name'] in sel}; print('SELECTED',sel,flush=True)

PER=[('2011-2015',2011,2015),('2016-2018',2016,2018),('2019-2021',2019,2021),('2022-2024',2022,2024),('2025-2026',2025,2026)]
wf=[]
for nm in sel:
    t=targets[nm]
    for lab,a,b in PER:
        ids=np.flatnonzero((YY>=a)&(YY<=b)); rr=A['ret'][ids]; tt=t[ids]; dd=DTS.iloc[ids].reset_index(drop=True); pre=account_end(rr,tt,COST,0.,dd); aft=account_end(rr,tt,COST,TAX,dd); wf.append({'candidate':nm,'period':lab,'pre_cagr':pre['cagr'],'pre_mdd':pre['mdd'],'tax_cagr':aft['cagr']})
WF=pd.DataFrame(wf); WF.to_csv('tqqq_stage41_subperiods.csv',index=False)
cc=[]
for nm in sel:
    t=targets[nm]
    for bps in (5,10,20):
        c=bps/10000.; pre=account_end(A['ret'],t,c,0.,DTS); aft=account_end(A['ret'],t,c,TAX,DTS); cc.append({'candidate':nm,'cost_bps':bps,'pre_cagr':pre['cagr'],'pre_mdd':pre['mdd'],'tax_cagr':aft['cagr']})
COSTS=pd.DataFrame(cc); COSTS.to_csv('tqqq_stage41_costs.csv',index=False)

# Normal matched-state moving-block bootstrap. VIX is bootstrapped with the same indices as market state/returns.
L=len(A['ret']); nb=int(np.ceil(H/BLOCK)); offs=np.arange(BLOCK); rng=np.random.default_rng(SEEDN); starts=rng.integers(0,L-BLOCK+1,size=(NSIM,nb)); paths=(starts[:,:,None]+offs).reshape(NSIM,-1)[:,:H]
normal=[]; ntax=[]
for z in range(NSIM):
    ix=paths[z]; B={k:A[k][ix].copy() for k in KEYS}; vx=VIXLVL[ix].copy(); cur=current_trace(B)
    for nm,s in SMAP.items():
        t=target41(B,vx,s,cur); m,_,_=from_target(B,t,COST); normal.append({'sim':z,'candidate':nm,**m})
        if z<TAXSIM:
            pre=account_end(B['ret'],t,COST,0.,None); aft=account_end(B['ret'],t,COST,TAX,None); ntax.append({'sim':z,'candidate':nm,'tax_cagr':aft['cagr'],'pre_mdd':pre['mdd']})
    if (z+1)%100==0: print('[normal41]',z+1,'/',NSIM,flush=True)
NORMAL=pd.DataFrame(normal); NORMAL.to_csv('tqqq_stage41_normal_mc.csv',index=False); NTAX=pd.DataFrame(ntax); NTAX.to_csv('tqqq_stage41_normal_tax_mc.csv',index=False)

def q(x,p):return float(np.quantile(np.asarray(x,float),p))
SUM=[]
for nm,g in NORMAL.groupby('candidate'):SUM.append({'candidate':nm,'cagr_p05':q(g.cagr,.05),'cagr_median':q(g.cagr,.5),'mdd_p05':q(g.mdd,.05),'mdd_median':q(g.mdd,.5),'p_mdd35':float(np.mean(g.mdd<-.35)),'p_mdd40':float(np.mean(g.mdd<-.40))})
SUM=pd.DataFrame(SUM); SUM.to_csv('tqqq_stage41_mc_summary.csv',index=False)
TS=[]
for nm,g in NTAX.groupby('candidate'):TS.append({'candidate':nm,'tax_p05':q(g.tax_cagr,.05),'tax_median':q(g.tax_cagr,.5),'prob_tax30':float(np.mean(g.tax_cagr>=.30)),'mdd_p05':q(g.pre_mdd,.05),'mdd_median':q(g.pre_mdd,.5)})
TAXMC=pd.DataFrame(TS); TAXMC.to_csv('tqqq_stage41_tax_mc_summary.csv',index=False)
rank=[]
for nm in sel:
    h=HIST[HIST.candidate.eq(nm)].iloc[0]; tx=TAXMC[TAXMC.candidate.eq(nm)].iloc[0]; sm=SUM[SUM.candidate.eq(nm)].iloc[0]
    score=h.tax_cagr+.8*tx.tax_median+.15*tx.tax_p05-2.2*max(0.,-h.pre_mdd-.35)-.8*max(0.,-sm.mdd_median-.40)
    rank.append({'candidate':nm,'hist_tax_cagr':h.tax_cagr,'hist_pre_cagr':h.pre_cagr,'hist_mdd':h.pre_mdd,'tax_mc_median':tx.tax_median,'tax_mc_p05':tx.tax_p05,'prob_tax30':tx.prob_tax30,'normal_mdd_median':sm.mdd_median,'normal_mdd_p05':tx.mdd_p05,'score':score})
R=pd.DataFrame(rank).sort_values('score',ascending=False); R.to_csv('tqqq_stage41_final_rank.csv',index=False)
print('\n=== HIST ===');print(HIST[HIST.candidate.isin(sel)][['candidate','pre_cagr','pre_mdd','tax_cagr','avg_exp','turnover']].sort_values(['pre_mdd','tax_cagr'],ascending=[False,False]).to_string(index=False));print('\n=== TAX MC ===');print(TAXMC.sort_values('tax_median',ascending=False).to_string(index=False));print('\n=== FINAL ===');print(R.to_string(index=False))
Path('tqqq_stage41_summary.json').write_text(json.dumps({'selected':sel,'historical':HIST[HIST.candidate.isin(sel)].to_dict('records'),'subperiods':WF.to_dict('records'),'costs':COSTS.to_dict('records'),'mc':SUM.to_dict('records'),'tax_mc':TAXMC.to_dict('records'),'final':R.to_dict('records'),'rule':'Stage38 plus VIX throttle on exact normal-30% sleeve only; VIX threshold 18-30 caps exposure 40-70%, with optional stronger cap at threshold+5. Explicit RG/GB/Panic/StrongBull sleeves and risk locks are not altered.','caveats':['VIX close is signal-time data aligned to the same date; synthetic Bear stress omitted because injected episodes do not contain coherent VIX paths.','MC57 PIT/survivorship audit unresolved.','NQSAR history proxy.','USDJPY/dividend tax not modeled.']},ensure_ascii=False,indent=2,default=str))
