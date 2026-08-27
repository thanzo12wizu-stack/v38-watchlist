from __future__ import annotations
from pathlib import Path
import json, numpy as np, pandas as pd

src=Path('research/tqqq_stage41_vix_throttle.py').read_text()
prefix=src.split("SPECS=[{'name':'CURRENT'}")[0]
exec(compile(prefix,'stage41-prefix', 'exec'), globals())
print('\n=== STAGE42 VIX FINE FRONTIER ===',flush=True)
NSIM42=1000; TAXSIM42=300; H42=2520; BLOCK42=120; SEED42=420827
SPECS42=[{'name':'CURRENT'},{'name':'BUYHOLD'},{'name':'STAGE38'}]
for th in (23.,24.,25.):
  for cap in (.50,.55,.60,.65,.70):
    for drop in (0.,.05,.10):
      cap2=max(.30,cap-drop)
      nm=f'V{int(th)}_C{int(cap*100)}_H{int(cap2*100)}'
      SPECS42.append({'name':nm,'vix':th,'cap':cap,'cap2':cap2})
# dedupe same names
d={s['name']:s for s in SPECS42}; SPECS42=list(d.values())
curA=current_trace(A); hist=[]; targets={}
for s in SPECS42:
    t=target41(A,VIXLVL,s,curA); targets[s['name']]=t; m,_,_=from_target(A,t,COST); pre=account_end(A['ret'],t,COST,0.,DTS); aft=account_end(A['ret'],t,COST,TAX,DTS)
    hist.append({'candidate':s['name'],'vix':s.get('vix',np.nan),'cap':s.get('cap',np.nan),'cap2':s.get('cap2',np.nan),'pre_cagr':pre['cagr'],'pre_mdd':pre['mdd'],'tax_cagr':aft['cagr'],'avg_exp':m['avg_exp'],'turnover':m['turnover']})
HIST=pd.DataFrame(hist); HIST.to_csv('tqqq_stage42_scan.csv',index=False)
sel=['CURRENT','BUYHOLD','STAGE38']
for capdd in (.35,.36,.37,.38,.39,.40):
    g=HIST[(HIST.candidate.str.startswith('V'))&(HIST.pre_mdd>=-capdd)].sort_values(['tax_cagr','pre_mdd'],ascending=[False,False]); sel+=g.head(3).candidate.tolist()
g=HIST[(HIST.candidate.str.startswith('V'))&(HIST.tax_cagr>=.30)&(HIST.pre_mdd>=-.38)].sort_values(['pre_mdd','tax_cagr'],ascending=[False,False]); sel+=g.head(10).candidate.tolist()
sel=list(dict.fromkeys(sel)); SMAP={s['name']:s for s in SPECS42 if s['name'] in sel}; print('SELECTED',sel,flush=True)
# costs
cc=[]
for nm in sel:
    t=targets[nm]
    for bps in (5,10,20):
        c=bps/10000.; pre=account_end(A['ret'],t,c,0.,DTS); aft=account_end(A['ret'],t,c,TAX,DTS); cc.append({'candidate':nm,'cost_bps':bps,'pre_cagr':pre['cagr'],'pre_mdd':pre['mdd'],'tax_cagr':aft['cagr']})
COSTS=pd.DataFrame(cc); COSTS.to_csv('tqqq_stage42_costs.csv',index=False)
# subperiods
PER=[('2011-2015',2011,2015),('2016-2018',2016,2018),('2019-2021',2019,2021),('2022-2024',2022,2024),('2025-2026',2025,2026)]
wf=[]
for nm in sel:
  t=targets[nm]
  for lab,a,b in PER:
    ids=np.flatnonzero((YY>=a)&(YY<=b)); rr=A['ret'][ids]; tt=t[ids]; dd=DTS.iloc[ids].reset_index(drop=True); pre=account_end(rr,tt,COST,0.,dd); aft=account_end(rr,tt,COST,TAX,dd); wf.append({'candidate':nm,'period':lab,'pre_cagr':pre['cagr'],'pre_mdd':pre['mdd'],'tax_cagr':aft['cagr']})
WF=pd.DataFrame(wf); WF.to_csv('tqqq_stage42_subperiods.csv',index=False)
# normal matched bootstrap
L=len(A['ret']); nb=int(np.ceil(H42/BLOCK42)); offs=np.arange(BLOCK42); rng=np.random.default_rng(SEED42); starts=rng.integers(0,L-BLOCK42+1,size=(NSIM42,nb)); paths=(starts[:,:,None]+offs).reshape(NSIM42,-1)[:,:H42]
normal=[]; ntax=[]
for z in range(NSIM42):
    ix=paths[z]; B={k:A[k][ix].copy() for k in KEYS}; vx=VIXLVL[ix].copy(); cur=current_trace(B)
    for nm,s in SMAP.items():
        t=target41(B,vx,s,cur); m,_,_=from_target(B,t,COST); normal.append({'sim':z,'candidate':nm,**m})
        if z<TAXSIM42:
            pre=account_end(B['ret'],t,COST,0.,None); aft=account_end(B['ret'],t,COST,TAX,None); ntax.append({'sim':z,'candidate':nm,'tax_cagr':aft['cagr'],'pre_mdd':pre['mdd']})
    if (z+1)%100==0:print('[normal42]',z+1,'/',NSIM42,flush=True)
NORMAL=pd.DataFrame(normal); NORMAL.to_csv('tqqq_stage42_normal_mc.csv',index=False); NTAX=pd.DataFrame(ntax); NTAX.to_csv('tqqq_stage42_normal_tax_mc.csv',index=False)
def q(x,p):return float(np.quantile(np.asarray(x,float),p))
SUM=[]
for nm,g in NORMAL.groupby('candidate'):SUM.append({'candidate':nm,'cagr_p05':q(g.cagr,.05),'cagr_median':q(g.cagr,.5),'mdd_p05':q(g.mdd,.05),'mdd_median':q(g.mdd,.5),'p_mdd35':float(np.mean(g.mdd<-.35)),'p_mdd40':float(np.mean(g.mdd<-.40))})
SUM=pd.DataFrame(SUM); SUM.to_csv('tqqq_stage42_mc_summary.csv',index=False)
TS=[]
for nm,g in NTAX.groupby('candidate'):TS.append({'candidate':nm,'tax_p05':q(g.tax_cagr,.05),'tax_median':q(g.tax_cagr,.5),'prob_tax30':float(np.mean(g.tax_cagr>=.30)),'mdd_p05':q(g.pre_mdd,.05),'mdd_median':q(g.pre_mdd,.5)})
TAXMC=pd.DataFrame(TS); TAXMC.to_csv('tqqq_stage42_tax_mc_summary.csv',index=False)
rank=[]
for nm in sel:
    h=HIST[HIST.candidate.eq(nm)].iloc[0]; tx=TAXMC[TAXMC.candidate.eq(nm)].iloc[0]; sm=SUM[SUM.candidate.eq(nm)].iloc[0]
    # Goal-first frontier: prefer hist tax >=30.7 and MC median >=30, then lowest DD.
    qualifies=bool((h.tax_cagr>=.307)&(tx.tax_median>=.30))
    score=h.tax_cagr+.8*tx.tax_median+.15*tx.tax_p05-2.3*max(0.,-h.pre_mdd-.35)-.7*max(0.,-sm.mdd_median-.40)+(.03 if qualifies else 0)
    rank.append({'candidate':nm,'hist_tax_cagr':h.tax_cagr,'hist_pre_cagr':h.pre_cagr,'hist_mdd':h.pre_mdd,'tax_mc_median':tx.tax_median,'tax_mc_p05':tx.tax_p05,'prob_tax30':tx.prob_tax30,'normal_mdd_median':sm.mdd_median,'normal_mdd_p05':tx.mdd_p05,'qualifies_goal':qualifies,'score':score})
R=pd.DataFrame(rank).sort_values(['qualifies_goal','hist_mdd','score'],ascending=[False,False,False]); R.to_csv('tqqq_stage42_final_rank.csv',index=False)
print('\n=== HIST ===');print(HIST[HIST.candidate.isin(sel)][['candidate','pre_cagr','pre_mdd','tax_cagr','avg_exp','turnover']].sort_values(['pre_mdd','tax_cagr'],ascending=[False,False]).to_string(index=False));print('\n=== TAX MC ===');print(TAXMC.sort_values('tax_median',ascending=False).to_string(index=False));print('\n=== FINAL ===');print(R.to_string(index=False))
Path('tqqq_stage42_summary.json').write_text(json.dumps({'selected':sel,'historical':HIST[HIST.candidate.isin(sel)].to_dict('records'),'costs':COSTS.to_dict('records'),'subperiods':WF.to_dict('records'),'mc':SUM.to_dict('records'),'tax_mc':TAXMC.to_dict('records'),'final':R.to_dict('records'),'rule':'Fine search around VIX 23-25, normal-sleeve cap 50-70%, optional extra 0/5/10 point cap reduction when VIX exceeds threshold+5. Existing explicit sleeves/risk locks unchanged.','caveats':['Synthetic Bear stress omitted because coherent VIX path is unavailable for injected episodes.','MC57 PIT/survivorship audit unresolved.','NQSAR history proxy.','USDJPY/dividend tax not modeled.']},ensure_ascii=False,indent=2,default=str))
