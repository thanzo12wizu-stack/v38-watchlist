from __future__ import annotations
from pathlib import Path
import json, numpy as np, pandas as pd

# Reuse exact Stage36 data, hierarchy and tax-account machinery.
src=Path('research/tqqq_stage36_goal_first_taxaware.py').read_text()
prefix=src.split('SPECS = [{"name":"CURRENT"}')[0]
exec(compile(prefix,'stage36-prefix','exec'),globals())

print('\n=== STAGE45 CRASH -> BULL REGIME OPTIMIZER ===', flush=True)
COST=.0005; TAX=.20315; NSIM=1000; TAXSIM=1000; H=2520; BLOCK=120; SEED=450827
VIXLVL=vix['Close'].astype(float).reindex(pd.DatetimeIndex(DTS)).ffill().to_numpy(float)

# Aggressive Stage37: 80% normal, 100% when both long trends are positive and MC>=35.
def target_aggr(B,cur=None):
    if cur is None: cur=current_trace(B)
    t=cur['target'].copy(); normal=(~cur['risklock'])&np.isclose(t,.30,atol=1e-9)
    t[normal]=np.maximum(t[normal],.80)
    hit=normal&B['a200']&B['a252']&(B['mc']>=35)
    t[hit]=1.0
    return np.clip(t,0,1)

# Exact Stage38-style structural throttle used by Stage41.
def target_d38(B,cur=None):
    if cur is None: cur=current_trace(B)
    t=cur['target'].copy(); normal=(~cur['risklock'])&np.isclose(t,.30,atol=1e-9)
    x=np.full(len(t),.80)
    x[B['lte21']]=np.minimum(x[B['lte21']],.45)
    weak=(~B['a50'])&(~B['a63']); x[weak]=np.minimum(x[weak],.35)
    pre=(B['dd10']<=-.04)&B['lte21']; x[pre]=np.minimum(x[pre],.35)
    t[normal]=np.maximum(t[normal],x[normal])
    hit=normal&B['a200']&B['a252']&(B['mc']>=35)
    t[hit]=np.maximum(t[hit],.90)
    return np.clip(t,0,1)

# Stage41 current defensive leader: D38 plus VIX>=24 cap at 60%, only on the normal sleeve.
def target_v60(B,vx,cur=None):
    if cur is None: cur=current_trace(B)
    t=target_d38(B,cur)
    normal=(~cur['risklock'])&np.isclose(cur['target'],.30,atol=1e-9)
    t[normal&(vx>=24.)]=np.minimum(t[normal&(vx>=24.)],.60)
    return np.clip(t,0,1)

def base_target(B,vx,name,cur=None):
    if cur is None: cur=current_trace(B)
    if name=='CURRENT': return cur['target'].copy()
    if name=='BUYHOLD': return np.ones(len(B['ret']),float)
    if name=='AGGR': return target_aggr(B,cur)
    if name=='D38': return target_d38(B,cur)
    if name=='V60': return target_v60(B,vx,cur)
    raise ValueError(name)

def rolling_min(x,w):
    return pd.Series(np.asarray(x,float)).rolling(w,min_periods=1).min().to_numpy(float)

def consec_true(x,k):
    x=np.asarray(x,bool); out=np.zeros(len(x),bool)
    if k<=1: return x.copy()
    c=0
    for i,v in enumerate(x):
        c=c+1 if v else 0
        out[i]=c>=k
    return out

def seed_mask(B,vx,mode,vth):
    # Panic is the existing VIX Sequence BOTTOM / RE-EXTREME signal.
    if mode=='PANIC':
        return B['panic'] & (B['s50a']<=-2.)
    # DEEP expands the seed universe to major dislocations with elevated VIX.
    if mode=='DEEP':
        return (B['s50a']<=-2.) & (vx>=vth) & ((B['dd10']<=-.065)|B['panic'])
    raise ValueError(mode)

def runner_target(B,vx,s,cur=None):
    if cur is None: cur=current_trace(B)
    t=base_target(B,vx,s['base'],cur)
    seed=seed_mask(B,vx,s['seed'],s.get('vth',0.))
    recent=np.zeros(len(t),bool); age=10**9
    for i in range(len(t)):
        if seed[i]: age=0
        else: age+=1
        recent[i]=age<=s['lookback']

    r10=consec_true(B['gte10'],2)
    if s['rec']=='R10': rec=r10 & (B['nq']!=0) & (B['mc']>=35)
    elif s['rec']=='R21': rec=(~B['lte21']) & (B['nq']!=0) & (B['mc']>=35)
    elif s['rec']=='BLUE': rec=(B['nq']==3) & (B['mc']>=35)
    else: raise ValueError(s['rec'])

    active=False; entry=-1; consumed=-1
    for i in range(1,len(t)):
        # New crash episode can arm only after a seed not already consumed.
        if (not active) and recent[i] and rec[i] and (not cur['risklock'][i]):
            last=np.flatnonzero(seed[:i+1])
            sid=int(last[-1]) if len(last) else -1
            if sid>consumed:
                active=True; entry=i; consumed=sid
        if active:
            hold=i-entry
            if s['exit']=='SOFT':
                bad=cur['risklock'][i] or (B['nq'][i]==0) or ((not B['a50'][i]) and (not B['a63'][i]))
            elif s['exit']=='LONG':
                bad=cur['risklock'][i] or (B['nq'][i]==0) or ((not B['a200'][i]) and (not B['a252'][i]))
            else: raise ValueError(s['exit'])
            if bad or hold>=s['maxd']:
                active=False
            else:
                # Key hypothesis: after a confirmed crash bottom, do NOT obey the ordinary
                # VIX/EMA throttle; ride TQQQ at 90-100% until the recovery regime breaks.
                t[i]=max(t[i],s['run'])
    return np.clip(t,0,1)

BASELINES=[{'name':'CURRENT','base':'CURRENT'},{'name':'BUYHOLD','base':'BUYHOLD'},{'name':'AGGR','base':'AGGR'},{'name':'D38','base':'D38'},{'name':'V60','base':'V60'}]
SPECS=[]
for base in ('AGGR','V60'):
    for seed in ('PANIC','DEEP'):
        vths=(0.,) if seed=='PANIC' else (28.,32.,36.)
        for vth in vths:
            for look in (20,40,60):
                for rec in ('R10','R21','BLUE'):
                    for run in (.90,1.00):
                        for maxd in (40,80,120,180):
                            for ex in ('SOFT','LONG'):
                                nm=f'{base}_{seed}{int(vth) if vth else ""}_L{look}_{rec}_R{int(run*100)}_D{maxd}_{ex}'
                                SPECS.append({'name':nm,'base':base,'seed':seed,'vth':vth,'lookback':look,'rec':rec,'run':run,'maxd':maxd,'exit':ex})

curA=current_trace(A); rows=[]; targets={}
for s in BASELINES:
    t=base_target(A,VIXLVL,s['base'],curA); targets[s['name']]=t
    m,_,_=from_target(A,t,COST); pre=account_end(A['ret'],t,COST,0.,DTS); aft=account_end(A['ret'],t,COST,TAX,DTS)
    rows.append({'candidate':s['name'],'base':s['base'],'seed':'','vth':np.nan,'lookback':np.nan,'rec':'','run':np.nan,'maxd':np.nan,'exit':'','pre_cagr':pre['cagr'],'pre_mdd':pre['mdd'],'tax_cagr':aft['cagr'],'tax_end':aft['end'],'avg_exp':m['avg_exp'],'turnover':m['turnover']})
for z,s in enumerate(SPECS):
    t=runner_target(A,VIXLVL,s,curA); targets[s['name']]=t
    m,_,_=from_target(A,t,COST); pre=account_end(A['ret'],t,COST,0.,DTS); aft=account_end(A['ret'],t,COST,TAX,DTS)
    rows.append({'candidate':s['name'],**{k:s[k] for k in ['base','seed','vth','lookback','rec','run','maxd','exit']},'pre_cagr':pre['cagr'],'pre_mdd':pre['mdd'],'tax_cagr':aft['cagr'],'tax_end':aft['end'],'avg_exp':m['avg_exp'],'turnover':m['turnover']})
    if (z+1)%100==0: print('[scan45]',z+1,'/',len(SPECS),flush=True)
HIST=pd.DataFrame(rows); HIST.to_csv('tqqq_stage45_scan.csv',index=False)

# Keep multiple points on the return/DD frontier, plus the absolute after-tax leaders.
sel=['CURRENT','BUYHOLD','AGGR','D38','V60']
R=HIST[~HIST.candidate.isin(sel)].copy()
for cap in (.35,.375,.40,.425,.45,.475,.50):
    g=R[R.pre_mdd>=-cap].sort_values(['tax_cagr','pre_mdd'],ascending=[False,False]); sel+=g.head(3).candidate.tolist()
sel+=R.sort_values(['tax_cagr','pre_mdd'],ascending=[False,False]).head(8).candidate.tolist()
sel=list(dict.fromkeys(sel)); SPEC_MAP={s['name']:s for s in SPECS}; print('SELECTED',len(sel),sel,flush=True)

# Fixed subperiod stability + costs.
PER=[('2011-2015',2011,2015),('2016-2018',2016,2018),('2019-2021',2019,2021),('2022-2024',2022,2024),('2025-2026',2025,2026)]
wf=[]; costs=[]
for nm in sel:
    t=targets[nm]
    for lab,a,b in PER:
        ix=np.flatnonzero((YY>=a)&(YY<=b)); dd=DTS.iloc[ix].reset_index(drop=True)
        pre=account_end(A['ret'][ix],t[ix],COST,0.,dd); aft=account_end(A['ret'][ix],t[ix],COST,TAX,dd)
        wf.append({'candidate':nm,'period':lab,'pre_cagr':pre['cagr'],'pre_mdd':pre['mdd'],'tax_cagr':aft['cagr']})
    for bps in (5,10,20):
        c=bps/10000.; pre=account_end(A['ret'],t,c,0.,DTS); aft=account_end(A['ret'],t,c,TAX,DTS)
        costs.append({'candidate':nm,'cost_bps':bps,'pre_cagr':pre['cagr'],'pre_mdd':pre['mdd'],'tax_cagr':aft['cagr'],'tax_end':aft['end']})
WF=pd.DataFrame(wf); WF.to_csv('tqqq_stage45_subperiods.csv',index=False)
COSTS=pd.DataFrame(costs); COSTS.to_csv('tqqq_stage45_costs.csv',index=False)

# Matched-state 10-year moving-block Monte Carlo. Tax is calculated on every path because
# the user's objective is terminal after-tax wealth, not just pre-tax CAGR.
L=len(A['ret']); nb=int(np.ceil(H/BLOCK)); offs=np.arange(BLOCK); rng=np.random.default_rng(SEED)
starts=rng.integers(0,L-BLOCK+1,size=(NSIM,nb)); paths=(starts[:,:,None]+offs).reshape(NSIM,-1)[:,:H]
mc=[]
for z in range(NSIM):
    ix=paths[z]; B={k:A[k][ix].copy() for k in KEYS}; vx=VIXLVL[ix].copy(); cur=current_trace(B)
    for nm in sel:
        if nm in ('CURRENT','BUYHOLD','AGGR','D38','V60'):
            t=base_target(B,vx,nm if nm in ('CURRENT','BUYHOLD','AGGR','D38','V60') else nm,cur)
        else:
            t=runner_target(B,vx,SPEC_MAP[nm],cur)
        m,_,_=from_target(B,t,COST); pre=account_end(B['ret'],t,COST,0.,None); aft=account_end(B['ret'],t,COST,TAX,None)
        mc.append({'sim':z,'candidate':nm,'pre_cagr':pre['cagr'],'pre_mdd':pre['mdd'],'tax_cagr':aft['cagr'],'tax_end':aft['end'],'avg_exp':m['avg_exp'],'turnover':m['turnover']})
    if (z+1)%50==0: print('[mc45]',z+1,'/',NSIM,flush=True)
MC=pd.DataFrame(mc); MC.to_csv('tqqq_stage45_mc.csv',index=False)

def q(x,p): return float(np.quantile(np.asarray(x,float),p))
summary=[]
for nm,g in MC.groupby('candidate'):
    summary.append({'candidate':nm,'n':len(g),'tax_cagr_p05':q(g.tax_cagr,.05),'tax_cagr_median':q(g.tax_cagr,.5),'tax_cagr_mean':float(g.tax_cagr.mean()),'tax_end_p05':q(g.tax_end,.05),'tax_end_median':q(g.tax_end,.5),'tax_end_mean':float(g.tax_end.mean()),'pre_mdd_p05':q(g.pre_mdd,.05),'pre_mdd_median':q(g.pre_mdd,.5),'p_mdd40':float(np.mean(g.pre_mdd<-.40)),'p_mdd50':float(np.mean(g.pre_mdd<-.50)),'p_tax30':float(np.mean(g.tax_cagr>=.30))})
SUM=pd.DataFrame(summary); SUM.to_csv('tqqq_stage45_mc_summary.csv',index=False)

# Annual drawdown profile on actual history for selected candidates.
ann=[]
def annual_dd(ret,target,cost):
    n=len(target); eff=np.zeros(n); eff[2:]=target[:-2]; turn=np.zeros(n); turn[2:]=np.abs(np.diff(target))[:-1]; sr=eff*ret-turn*cost
    out=[]
    for y in sorted(np.unique(YY)):
        ids=np.flatnonzero(YY==y); rr=sr[ids]; eq=np.cumprod(1+np.nan_to_num(rr,nan=0.)); pk=np.maximum.accumulate(eq); dd=eq/pk-1
        out.append((int(y),float(dd.min()),float(dd.mean())))
    return out
for nm in sel:
    for y,mx,av in annual_dd(A['ret'],targets[nm],COST): ann.append({'candidate':nm,'year':y,'year_mdd':mx,'mean_daily_dd':av})
ANN=pd.DataFrame(ann); ANN.to_csv('tqqq_stage45_annual_dd.csv',index=False)

# Rank 1 = pure expected terminal wealth; rank 2 = growth-efficient with DD penalty.
joined=HIST[HIST.candidate.isin(sel)].merge(SUM,on='candidate',how='left')
joined['ev_rank']=joined['tax_end_mean'].rank(ascending=False,method='min')
joined['eff_score']=np.log(joined['tax_end_mean'].clip(lower=1e-12))-1.25*np.maximum(0.,-joined['pre_mdd_median']-.40)-.50*np.maximum(0.,-joined['pre_mdd_p05']-.55)
joined=joined.sort_values(['ev_rank','eff_score'],ascending=[True,False]); joined.to_csv('tqqq_stage45_final_rank.csv',index=False)
print('\n=== EXPECTED WEALTH LEADERS ==='); print(joined[['candidate','pre_cagr','pre_mdd','tax_cagr','tax_end_mean','tax_end_median','tax_cagr_median','pre_mdd_median','pre_mdd_p05','p_mdd40','p_mdd50','ev_rank','eff_score']].head(20).to_string(index=False))

out={'selected':sel,'historical':HIST[HIST.candidate.isin(sel)].to_dict('records'),'mc_summary':SUM.to_dict('records'),'final':joined.to_dict('records'),'rule':'Crash-to-Bull runner: seed from existing VIX panic + deep QQQ displacement (or deep displacement with VIX 28/32/36); after recovery confirmation and risk-lock clearance, hold 90/100% for 40-180 trading days unless regime exit. It intentionally bypasses ordinary VIX/EMA throttles during confirmed recovery, but never overrides a new risk lock.','caveats':['MC57 PIT/survivorship audit unresolved.','NQSAR historical state is reconstruction proxy.','USDJPY/dividend tax not modeled.','Monte Carlo is matched-state moving-block resampling, not a forecast probability distribution.']}
Path('tqqq_stage45_summary.json').write_text(json.dumps(out,ensure_ascii=False,indent=2,default=str))
