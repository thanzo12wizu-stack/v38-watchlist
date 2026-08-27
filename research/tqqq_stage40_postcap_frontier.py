from __future__ import annotations
from pathlib import Path
import json, numpy as np, pandas as pd

src=Path('research/tqqq_stage36_goal_first_taxaware.py').read_text()
prefix=src.split('SPECS = [{"name":"CURRENT"}')[0]
exec(compile(prefix,'stage36-prefix','exec'),globals())

print('\n=== STAGE40 POST-CAP FRONTIER ===',flush=True)
NSIM=1000; TAXSIM=300; H=2520; BLOCK=120; SEEDN=400827; SEEDB=400828

def target40(B,s,cur=None):
    if s['name']=='CURRENT': return (cur if cur is not None else current_trace(B))['target'].copy()
    if s['name']=='BUYHOLD': return np.ones(len(B['ret']),float)
    if s['name']=='STAGE38':
        if cur is None: cur=current_trace(B)
        t=cur['target'].copy(); normal=(~cur['risklock'])&np.isclose(t,.30,atol=1e-9)
        x=np.full(len(t),.80); x[B['lte21']]=np.minimum(x[B['lte21']],.45); weak=(~B['a50'])&(~B['a63']); x[weak]=np.minimum(x[weak],.35); pre=(B['dd10']<=-.04)&B['lte21']; x[pre]=np.minimum(x[pre],.35)
        t[normal]=np.maximum(t[normal],x[normal]); hit=normal&(B['a200']&B['a252']&(B['mc']>=35)); t[hit]=np.maximum(t[hit],.90); return np.clip(t,0,1)
    if cur is None: cur=current_trace(B)
    t=cur['target'].copy(); normal=(~cur['risklock'])&np.isclose(t,.30,atol=1e-9)
    n=len(t)
    # high base outside explicit locks
    x=np.full(n,s['high'],float)
    bull=B['a200']&B['a252']&(B['mc']>=35)
    x[bull]=np.maximum(x[bull],s['full'])
    # require recovery confirmation before re-levering after EMA21 weakness
    good=(~B['lte21']); rec=np.zeros(n,bool); k=s['rec']
    for i in range(k-1,n): rec[i]=good[i-k+1:i+1].all()
    x[~rec]=np.minimum(x[~rec],s['midcap'])
    both=(~B['a50'])&(~B['a63']); x[both]=np.minimum(x[both],s['weak'])
    pre=(B['dd10']<=-.04)&B['lte21']; x[pre]=np.minimum(x[pre],s['weak'])
    if s['onecut']:
        one=(~B['a50'])|(~B['a63']); x[one&B['lte21']]=np.minimum(x[one&B['lte21']],s['midcap'])
    t[normal]=np.maximum(t[normal],x[normal]); return np.clip(t,0,1)

SPECS=[{'name':'CURRENT'},{'name':'BUYHOLD'},{'name':'STAGE38'}]
for high in (.75,.80):
  for full in (.80,.825,.85,.875,.90):
    for midcap in (.40,.45,.50,.55):
      for weak in (.30,.35,.40):
        for rec in (1,2,3):
          for onecut in (0,1):
            nm=f'H{int(high*100)}_F{int(round(full*1000))}_M{int(midcap*100)}_W{int(weak*100)}_R{rec}_O{onecut}'
            SPECS.append({'name':nm,'high':high,'full':full,'midcap':midcap,'weak':weak,'rec':rec,'onecut':onecut})
curA=current_trace(A); hist=[]; targets={}
for s in SPECS:
    t=target40(A,s,curA); targets[s['name']]=t; m,_,_=from_target(A,t,COST); pre=account_end(A['ret'],t,COST,0.,DTS); aft=account_end(A['ret'],t,COST,TAX,DTS)
    hist.append({'candidate':s['name'],**{k:s.get(k,np.nan) for k in ['high','full','midcap','weak','rec','onecut']},'pre_cagr':pre['cagr'],'pre_mdd':pre['mdd'],'tax_cagr':aft['cagr'],'tax_end':aft['end'],'avg_exp':m['avg_exp'],'turnover':m['turnover']})
HIST=pd.DataFrame(hist); HIST.to_csv('tqqq_stage40_scan.csv',index=False)
sel=['CURRENT','BUYHOLD','STAGE38']
for cap in (.325,.35,.36,.37,.38,.39,.40):
    g=HIST[(HIST.candidate.str.startswith('H'))&(HIST.pre_mdd>=-cap)].sort_values(['tax_cagr','pre_mdd'],ascending=[False,False]); sel+=g.head(3).candidate.tolist()
g=HIST[(HIST.candidate.str.startswith('H'))&(HIST.tax_cagr>=.30)&(HIST.pre_mdd>=-.40)].sort_values(['pre_mdd','tax_cagr'],ascending=[False,False]); sel+=g.head(8).candidate.tolist()
sel=list(dict.fromkeys(sel)); SMAP={s['name']:s for s in SPECS if s['name'] in sel}; print('SELECTED',sel,flush=True)

PER=[('2011-2015',2011,2015),('2016-2018',2016,2018),('2019-2021',2019,2021),('2022-2024',2022,2024),('2025-2026',2025,2026)]
wf=[]
for nm in sel:
    t=targets[nm]
    for lab,a,b in PER:
        ids=np.flatnonzero((YY>=a)&(YY<=b)); rr=A['ret'][ids]; tt=t[ids]; dd=DTS.iloc[ids].reset_index(drop=True); pre=account_end(rr,tt,COST,0.,dd); aft=account_end(rr,tt,COST,TAX,dd); wf.append({'candidate':nm,'period':lab,'pre_cagr':pre['cagr'],'pre_mdd':pre['mdd'],'tax_cagr':aft['cagr']})
WF=pd.DataFrame(wf); WF.to_csv('tqqq_stage40_subperiods.csv',index=False)
cc=[]
for nm in sel:
    t=targets[nm]
    for bps in (5,10,20):
        c=bps/10000.; pre=account_end(A['ret'],t,c,0.,DTS); aft=account_end(A['ret'],t,c,TAX,DTS); cc.append({'candidate':nm,'cost_bps':bps,'pre_cagr':pre['cagr'],'pre_mdd':pre['mdd'],'tax_cagr':aft['cagr']})
COSTS=pd.DataFrame(cc); COSTS.to_csv('tqqq_stage40_costs.csv',index=False)

L=len(A['ret']); nb=int(np.ceil(H/BLOCK)); offs=np.arange(BLOCK); rng=np.random.default_rng(SEEDN); starts=rng.integers(0,L-BLOCK+1,size=(NSIM,nb)); paths=(starts[:,:,None]+offs).reshape(NSIM,-1)[:,:H]
normal=[]; ntax=[]
for z in range(NSIM):
    ix=paths[z]; B={k:A[k][ix].copy() for k in KEYS}; cur=current_trace(B)
    for nm,s in SMAP.items():
        t=target40(B,s,cur); m,_,_=from_target(B,t,COST); normal.append({'sim':z,'candidate':nm,**m})
        if z<TAXSIM:
            pre=account_end(B['ret'],t,COST,0.,None); aft=account_end(B['ret'],t,COST,TAX,None); ntax.append({'sim':z,'candidate':nm,'tax_cagr':aft['cagr'],'pre_mdd':pre['mdd']})
    if (z+1)%100==0: print('[normal40]',z+1,'/',NSIM,flush=True)
NORMAL=pd.DataFrame(normal); NORMAL.to_csv('tqqq_stage40_normal_mc.csv',index=False); NTAX=pd.DataFrame(ntax); NTAX.to_csv('tqqq_stage40_normal_tax_mc.csv',index=False)

rng=np.random.default_rng(SEEDB); starts=rng.integers(0,L-BLOCK+1,size=(NSIM,nb)); paths=(starts[:,:,None]+offs).reshape(NSIM,-1)[:,:H]; fams=np.array((['dotcom_like']*250)+(['gfc_like']*250)+(['covid_like']*250)+(['2022_like']*250),object); rng.shuffle(fams); bear=[]
for z in range(NSIM):
    ix=paths[z]; B={k:A[k][ix].copy() for k in KEYS}; ep=make_episode(str(fams[z]),rng); le=len(ep['ret'])
    if le>=H-504:
        cut=(le-(H-504))//2; ep={k:v[cut:cut+(H-504)] for k,v in ep.items()}; le=len(ep['ret'])
    pos=int(rng.integers(252,max(253,H-le-252)))
    for k in KEYS:B[k][pos:pos+le]=ep[k]
    cur=current_trace(B)
    for nm,s in SMAP.items():
        t=target40(B,s,cur); m,_,_=from_target(B,t,COST); bear.append({'sim':z,'candidate':nm,**m})
    if (z+1)%100==0: print('[bear40]',z+1,'/',NSIM,flush=True)
BEAR=pd.DataFrame(bear); BEAR.to_csv('tqqq_stage40_bear_mc.csv',index=False)

def q(x,p):return float(np.quantile(np.asarray(x,float),p))
SUM=[]
for typ,df in [('normal',NORMAL),('bear',BEAR)]:
  for nm,g in df.groupby('candidate'):SUM.append({'test':typ,'candidate':nm,'cagr_p05':q(g.cagr,.05),'cagr_median':q(g.cagr,.5),'mdd_p05':q(g.mdd,.05),'mdd_median':q(g.mdd,.5),'p_mdd35':float(np.mean(g.mdd<-.35)),'p_mdd40':float(np.mean(g.mdd<-.40))})
SUM=pd.DataFrame(SUM); SUM.to_csv('tqqq_stage40_mc_summary.csv',index=False)
TS=[]
for nm,g in NTAX.groupby('candidate'):TS.append({'candidate':nm,'tax_p05':q(g.tax_cagr,.05),'tax_median':q(g.tax_cagr,.5),'prob_tax30':float(np.mean(g.tax_cagr>=.30)),'mdd_p05':q(g.pre_mdd,.05),'mdd_median':q(g.pre_mdd,.5)})
TAXMC=pd.DataFrame(TS); TAXMC.to_csv('tqqq_stage40_tax_mc_summary.csv',index=False)
mall=SUM.pivot(index='candidate',columns='test'); rank=[]
for nm in sel:
    h=HIST[HIST.candidate.eq(nm)].iloc[0]; tx=TAXMC[TAXMC.candidate.eq(nm)].iloc[0]; nmd=float(mall.loc[nm,('mdd_median','normal')]); bmd=float(mall.loc[nm,('mdd_median','bear')]); score=h.tax_cagr+.8*tx.tax_median+.15*tx.tax_p05-2.0*max(0.,-h.pre_mdd-.35)-.8*max(0.,-nmd-.40)
    rank.append({'candidate':nm,'hist_tax_cagr':h.tax_cagr,'hist_pre_cagr':h.pre_cagr,'hist_mdd':h.pre_mdd,'tax_mc_median':tx.tax_median,'tax_mc_p05':tx.tax_p05,'prob_tax30':tx.prob_tax30,'normal_mdd_median':nmd,'normal_mdd_p05':tx.mdd_p05,'bear_mdd_median':bmd,'score':score})
R=pd.DataFrame(rank).sort_values('score',ascending=False); R.to_csv('tqqq_stage40_final_rank.csv',index=False)
print('\n=== HIST ===');print(HIST[HIST.candidate.isin(sel)][['candidate','pre_cagr','pre_mdd','tax_cagr','avg_exp','turnover']].sort_values(['pre_mdd','tax_cagr'],ascending=[False,False]).to_string(index=False));print('\n=== TAX MC ===');print(TAXMC.sort_values('tax_median',ascending=False).to_string(index=False));print('\n=== FINAL ===');print(R.to_string(index=False))
Path('tqqq_stage40_summary.json').write_text(json.dumps({'selected':sel,'historical':HIST[HIST.candidate.isin(sel)].to_dict('records'),'subperiods':WF.to_dict('records'),'costs':COSTS.to_dict('records'),'mc':SUM.to_dict('records'),'tax_mc':TAXMC.to_dict('records'),'final':R.to_dict('records'),'rule':'High 75/80%, bull 80-90%; after setting bull exposure, cap down immediately on EMA21 weakness, medium-support loss or 10d DD<=-4%, and require 1-3 good days before re-levering. Existing risk hierarchy unchanged.','caveats':['MC57 PIT/survivorship audit unresolved.','NQSAR history proxy.','USDJPY/dividend tax not modeled.','Bear stress not forecast distribution.']},ensure_ascii=False,indent=2,default=str))
