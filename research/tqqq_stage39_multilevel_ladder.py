from __future__ import annotations
from pathlib import Path
import json, numpy as np, pandas as pd

src=Path('research/tqqq_stage36_goal_first_taxaware.py').read_text()
prefix=src.split('SPECS = [{"name":"CURRENT"}')[0]
exec(compile(prefix,'stage36-prefix','exec'),globals())

print('\n=== STAGE39 MULTILEVEL LADDER ===',flush=True)
NSIM=1000; TAXSIM=300; H=2520; BLOCK=120; SEEDN=390827; SEEDB=390828

# More defensive ladder: low neutral floor, high exposure only when short/mid trend confirms,
# 90/100% only in long-trend bull state, immediate pre-lock cut on weakness.
def midmask(B,mode):
    if mode=='E21': return ~B['lte21']
    if mode=='ONE': return (~B['lte21']) & (B['a50']|B['a63'])
    if mode=='BOTH': return (~B['lte21']) & B['a50'] & B['a63']
    raise ValueError(mode)

def fullmask(B,mode):
    a2=B['a200']&B['a252']&(B['mc']>=35)
    if mode=='A2': return a2
    if mode=='E21': return a2 & (~B['lte21'])
    if mode=='MID': return a2 & (~B['lte21']) & (B['a50']|B['a63'])
    if mode=='A4': return a2 & B['a50'] & B['a63'] & (~B['lte21'])
    raise ValueError(mode)

def target39(B,s,cur=None):
    if s['name']=='CURRENT': return (cur if cur is not None else current_trace(B))['target'].copy()
    if s['name']=='BUYHOLD': return np.ones(len(B['ret']),float)
    if s['name']=='STAGE38':
        if cur is None: cur=current_trace(B)
        t=cur['target'].copy(); normal=(~cur['risklock'])&np.isclose(t,.30,atol=1e-9)
        x=np.full(len(t),.80); x[B['lte21']]=np.minimum(x[B['lte21']],.45); weak=(~B['a50'])&(~B['a63']); x[weak]=np.minimum(x[weak],.35); pre=(B['dd10']<=-.04)&B['lte21']; x[pre]=np.minimum(x[pre],.35)
        t[normal]=np.maximum(t[normal],x[normal]); hit=normal&(B['a200']&B['a252']&(B['mc']>=35)); t[hit]=np.maximum(t[hit],.90); return np.clip(t,0,1)
    if cur is None: cur=current_trace(B)
    t=cur['target'].copy(); normal=(~cur['risklock'])&np.isclose(t,.30,atol=1e-9)
    x=np.full(len(t),s['neutral'])
    mm=midmask(B,s['midmode']); x[mm]=np.maximum(x[mm],s['mid'])
    fm=fullmask(B,s['fullmode']); x[fm]=np.maximum(x[fm],s['full'])
    # Downward overrides after upward floors: these are pre-lock drawdown controls.
    both=(~B['a50'])&(~B['a63']); x[both]=np.minimum(x[both],s['def'])
    pre=(B['dd10']<=s['ddcut'])&B['lte21']; x[pre]=np.minimum(x[pre],s['def'])
    # EMA21 loss alone caps at neutral or a small cushion, regardless of a stale long-term bull signal.
    x[B['lte21']]=np.minimum(x[B['lte21']],s['ema_cap'])
    t[normal]=np.maximum(t[normal],x[normal])
    return np.clip(t,0,1)

SPECS=[{'name':'CURRENT'},{'name':'BUYHOLD'},{'name':'STAGE38'}]
for neutral in (.35,.40,.45,.50):
  for mid in (.70,.80,.90):
    for de in (.30,.35,.40):
      for full in (.90,1.0):
        for midmode in ('E21','ONE','BOTH'):
          for fullmode in ('E21','MID','A4'):
            for ema_cap in (.45,.50,.55,.60):
              if ema_cap<neutral: continue
              nm=f'N{int(neutral*100)}_M{int(mid*100)}_D{int(de*100)}_F{int(full*100)}_{midmode}_{fullmode}_E{int(ema_cap*100)}'
              SPECS.append({'name':nm,'neutral':neutral,'mid':mid,'def':de,'full':full,'midmode':midmode,'fullmode':fullmode,'ema_cap':ema_cap,'ddcut':-.04})

curA=current_trace(A); hist=[]; targets={}
for s in SPECS:
    t=target39(A,s,curA); targets[s['name']]=t; m,_,_=from_target(A,t,COST); pre=account_end(A['ret'],t,COST,0.0,DTS); aft=account_end(A['ret'],t,COST,TAX,DTS)
    hist.append({'candidate':s['name'],**{k:s.get(k,np.nan) for k in ['neutral','mid','def','full','midmode','fullmode','ema_cap']},'pre_cagr':pre['cagr'],'pre_mdd':pre['mdd'],'tax_cagr':aft['cagr'],'tax_end':aft['end'],'avg_exp':m['avg_exp'],'turnover':m['turnover']})
HIST=pd.DataFrame(hist); HIST.to_csv('tqqq_stage39_scan.csv',index=False)

sel=['CURRENT','BUYHOLD','STAGE38']
for cap in (.30,.325,.35,.375,.40):
    g=HIST[(HIST.candidate.str.startswith('N'))&(HIST.pre_mdd>=-cap)].sort_values(['tax_cagr','pre_mdd'],ascending=[False,False]); sel+=g.head(3).candidate.tolist()
g=HIST[(HIST.candidate.str.startswith('N'))&(HIST.tax_cagr>=.30)&(HIST.pre_mdd>=-.40)].sort_values(['tax_cagr','pre_mdd'],ascending=[False,False]); sel+=g.head(8).candidate.tolist()
sel=list(dict.fromkeys(sel)); SMAP={s['name']:s for s in SPECS if s['name'] in sel}; print('SELECTED',sel,flush=True)

PER=[('2011-2015',2011,2015),('2016-2018',2016,2018),('2019-2021',2019,2021),('2022-2024',2022,2024),('2025-2026',2025,2026)]
wf=[]
for nm in sel:
  t=targets[nm]
  for lab,a,b in PER:
    ids=np.flatnonzero((YY>=a)&(YY<=b)); rr=A['ret'][ids]; tt=t[ids]; dd=DTS.iloc[ids].reset_index(drop=True); pre=account_end(rr,tt,COST,0.,dd); aft=account_end(rr,tt,COST,TAX,dd); wf.append({'candidate':nm,'period':lab,'pre_cagr':pre['cagr'],'pre_mdd':pre['mdd'],'tax_cagr':aft['cagr']})
WF=pd.DataFrame(wf); WF.to_csv('tqqq_stage39_subperiods.csv',index=False)

cc=[]
for nm in sel:
  for bps in (5,10,20):
    c=bps/10000.; t=targets[nm]; pre=account_end(A['ret'],t,c,0.,DTS); aft=account_end(A['ret'],t,c,TAX,DTS); cc.append({'candidate':nm,'cost_bps':bps,'pre_cagr':pre['cagr'],'pre_mdd':pre['mdd'],'tax_cagr':aft['cagr']})
COSTS=pd.DataFrame(cc); COSTS.to_csv('tqqq_stage39_costs.csv',index=False)

L=len(A['ret']); nb=int(np.ceil(H/BLOCK)); offs=np.arange(BLOCK); rng=np.random.default_rng(SEEDN); starts=rng.integers(0,L-BLOCK+1,size=(NSIM,nb)); paths=(starts[:,:,None]+offs).reshape(NSIM,-1)[:,:H]
normal=[]; ntax=[]
for z in range(NSIM):
    ix=paths[z]; B={k:A[k][ix].copy() for k in KEYS}; cur=current_trace(B)
    for nm,s in SMAP.items():
        t=target39(B,s,cur); m,_,_=from_target(B,t,COST); normal.append({'sim':z,'candidate':nm,**m})
        if z<TAXSIM:
            pre=account_end(B['ret'],t,COST,0.,None); aft=account_end(B['ret'],t,COST,TAX,None); ntax.append({'sim':z,'candidate':nm,'tax_cagr':aft['cagr'],'pre_mdd':pre['mdd']})
    if (z+1)%100==0: print('[normal39]',z+1,'/',NSIM,flush=True)
NORMAL=pd.DataFrame(normal); NORMAL.to_csv('tqqq_stage39_normal_mc.csv',index=False); NTAX=pd.DataFrame(ntax); NTAX.to_csv('tqqq_stage39_normal_tax_mc.csv',index=False)

rng=np.random.default_rng(SEEDB); starts=rng.integers(0,L-BLOCK+1,size=(NSIM,nb)); paths=(starts[:,:,None]+offs).reshape(NSIM,-1)[:,:H]; fams=np.array((['dotcom_like']*250)+(['gfc_like']*250)+(['covid_like']*250)+(['2022_like']*250),object); rng.shuffle(fams); bear=[]
for z in range(NSIM):
    ix=paths[z]; B={k:A[k][ix].copy() for k in KEYS}; ep=make_episode(str(fams[z]),rng); le=len(ep['ret'])
    if le>=H-504:
        cut=(le-(H-504))//2; ep={k:v[cut:cut+(H-504)] for k,v in ep.items()}; le=len(ep['ret'])
    pos=int(rng.integers(252,max(253,H-le-252)))
    for k in KEYS:B[k][pos:pos+le]=ep[k]
    cur=current_trace(B)
    for nm,s in SMAP.items():
        t=target39(B,s,cur); m,_,_=from_target(B,t,COST); bear.append({'sim':z,'candidate':nm,**m})
    if (z+1)%100==0: print('[bear39]',z+1,'/',NSIM,flush=True)
BEAR=pd.DataFrame(bear); BEAR.to_csv('tqqq_stage39_bear_mc.csv',index=False)

def q(x,p): return float(np.quantile(np.asarray(x,float),p))
SUM=[]
for typ,df in [('normal',NORMAL),('bear',BEAR)]:
  for nm,g in df.groupby('candidate'): SUM.append({'test':typ,'candidate':nm,'cagr_p05':q(g.cagr,.05),'cagr_median':q(g.cagr,.5),'mdd_p05':q(g.mdd,.05),'mdd_median':q(g.mdd,.5),'p_mdd35':float(np.mean(g.mdd<-.35)),'p_mdd40':float(np.mean(g.mdd<-.40))})
SUM=pd.DataFrame(SUM); SUM.to_csv('tqqq_stage39_mc_summary.csv',index=False)
TS=[]
for nm,g in NTAX.groupby('candidate'): TS.append({'candidate':nm,'tax_p05':q(g.tax_cagr,.05),'tax_median':q(g.tax_cagr,.5),'prob_tax30':float(np.mean(g.tax_cagr>=.30)),'mdd_p05':q(g.pre_mdd,.05),'mdd_median':q(g.pre_mdd,.5)})
TAXMC=pd.DataFrame(TS); TAXMC.to_csv('tqqq_stage39_tax_mc_summary.csv',index=False)

mall=SUM.pivot(index='candidate',columns='test'); rank=[]
for nm in sel:
    h=HIST[HIST.candidate.eq(nm)].iloc[0]; tx=TAXMC[TAXMC.candidate.eq(nm)].iloc[0]; nmd=float(mall.loc[nm,('mdd_median','normal')]); bmd=float(mall.loc[nm,('mdd_median','bear')]); score=h.tax_cagr+.8*tx.tax_median+.15*tx.tax_p05-2.2*max(0.,-h.pre_mdd-.35)-.9*max(0.,-nmd-.40)
    rank.append({'candidate':nm,'hist_tax_cagr':h.tax_cagr,'hist_pre_cagr':h.pre_cagr,'hist_mdd':h.pre_mdd,'tax_mc_median':tx.tax_median,'tax_mc_p05':tx.tax_p05,'prob_tax30':tx.prob_tax30,'normal_mdd_median':nmd,'normal_mdd_p05':tx.mdd_p05,'bear_mdd_median':bmd,'score':score})
R=pd.DataFrame(rank).sort_values('score',ascending=False); R.to_csv('tqqq_stage39_final_rank.csv',index=False)
print('\n=== HIST <=40 DD ==='); print(HIST[(HIST.candidate.isin(sel))][['candidate','pre_cagr','pre_mdd','tax_cagr','avg_exp','turnover']].sort_values('tax_cagr',ascending=False).to_string(index=False)); print('\n=== TAX MC ==='); print(TAXMC.sort_values('tax_median',ascending=False).to_string(index=False)); print('\n=== FINAL ==='); print(R.to_string(index=False))
Path('tqqq_stage39_summary.json').write_text(json.dumps({'selected':sel,'historical':HIST[HIST.candidate.isin(sel)].to_dict('records'),'subperiods':WF.to_dict('records'),'costs':COSTS.to_dict('records'),'mc':SUM.to_dict('records'),'tax_mc':TAXMC.to_dict('records'),'final':R.to_dict('records'),'rule':'Neutral 35-50%; raise to 70-90% only with short/mid trend confirmation; 90-100% only with A2+MC35 plus confirmation; immediately cap on EMA21 loss, both SMA50/VWAP63 loss, or 10d DD<=-4%. Existing locks/RG/GB/StrongBull/VIX Panic unchanged.','caveats':['MC57 PIT/survivorship audit unresolved.','NQSAR history proxy.','USDJPY/dividend tax not modeled.','Bear stress not forecast distribution.']},ensure_ascii=False,indent=2,default=str))
