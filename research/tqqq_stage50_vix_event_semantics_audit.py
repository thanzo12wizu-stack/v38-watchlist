from __future__ import annotations
from pathlib import Path
import json, numpy as np, pandas as pd

src=Path('research/tqqq_stage46_crash_seed_refinement.py').read_text()
prefix=src.split('SPECS=[]')[0]
exec(compile(prefix,'stage46-prefix','exec'),globals())

print('\n=== STAGE50 VIX EVENT SEMANTICS AUDIT ===',flush=True)
COST=.0005; TAX=.20315; H=2520; BLOCK=120; NSIM=1000; SEED50=500827
SPEC={'vth':23.0,'s50':-0.50,'ddcut':-0.02,'lookback':30,'maxd':80}
VIXC=vix['Close'].astype(float).reindex(pd.DatetimeIndex(DTS)).ffill().to_numpy(float)
VIXH=vix['High'].astype(float).reindex(pd.DatetimeIndex(DTS)).ffill().to_numpy(float)
_, sigs=bt.vix_state_series(vix)
ev_dates={pd.Timestamp(x['date']) for x in sigs if x.get('type') in ('BOTTOM','RE-EXTREME')}
VIX_EVENT=np.array([pd.Timestamp(d) in ev_dates for d in DTS],bool)


def runner50(B,vx,event,mode,cur=None,boundaries=None,trace=False):
    if cur is None: cur=current_trace(B)
    t=target_aggr(B,cur); base=t.copy()
    extra = B['panic'] if mode=='STATE' else event if mode=='EVENT' else np.zeros(len(t),bool)
    seed=(B['s50a']<=SPEC['s50'])&(vx>=SPEC['vth'])&((B['dd10']<=SPEC['ddcut'])|extra)
    rec=consec_true(B['gte10'],2)&(B['nq']!=0)&(B['mc']>=35)
    bset=set([] if boundaries is None else boundaries)
    active=False; entry=-1; consumed=-1; age=10**9; origin=-1; entries=0; active_days=0; incremental=0
    for i in range(len(t)):
        if i in bset:
            active=False; entry=-1; origin=-1; consumed=-1; age=10**9
        age=0 if seed[i] else age+1
        recent=age<=SPEC['lookback']
        if (not active) and recent and rec[i] and (not cur['risklock'][i]):
            last=np.flatnonzero(seed[:i+1]); sid=int(last[-1]) if len(last) else -1
            if sid>consumed:
                active=True; entry=i; origin=sid; consumed=sid; entries+=1
        if active:
            if seed[i]: consumed=max(consumed,i)  # prevent stale seed re-arm
            hold=i-entry
            bad=cur['risklock'][i] or (B['nq'][i]==0) or ((not B['a200'][i]) and (not B['a252'][i])) or hold>=SPEC['maxd']
            if bad:
                active=False; entry=-1; origin=-1
            else:
                active_days+=1; incremental+=int(t[i]<.999); t[i]=max(t[i],1.0)
    out={'target':np.clip(t,0,1),'seed':seed,'entries':entries,'active_days':active_days,'incremental_days':incremental}
    return out if trace else out['target']

CASES=[('STATE_CLOSE','STATE','CLOSE'),('EVENT_CLOSE','EVENT','CLOSE'),('PRICE_CLOSE','NONE','CLOSE'),('EVENT_HIGH','EVENT','HIGH'),('PRICE_HIGH','NONE','HIGH')]
curA=current_trace(A); hist=[]; traces={}
for nm,mode,vsrc in CASES:
    vx=VIXC if vsrc=='CLOSE' else VIXH
    tr=runner50(A,vx,VIX_EVENT,mode,curA,None,True); traces[nm]=tr; t=tr['target']
    m,_,_=from_target(A,t,COST); pre=account_end(A['ret'],t,COST,0.,DTS); aft=account_end(A['ret'],t,COST,TAX,DTS)
    hist.append({'candidate':nm,'mode':mode,'vix_source':vsrc,'seed_days':int(tr['seed'].sum()),'entries':tr['entries'],'active_days':tr['active_days'],'incremental_days':tr['incremental_days'],
                 'pre_cagr':pre['cagr'],'pre_mdd':pre['mdd'],'tax_cagr':aft['cagr'],'tax_end':aft['end'],'avg_exp':m['avg_exp'],'turnover':m['turnover']})
t=target_aggr(A,curA); m,_,_=from_target(A,t,COST); pre=account_end(A['ret'],t,COST,0.,DTS); aft=account_end(A['ret'],t,COST,TAX,DTS)
hist.append({'candidate':'AGGR','mode':'','vix_source':'','seed_days':0,'entries':0,'active_days':0,'incremental_days':0,'pre_cagr':pre['cagr'],'pre_mdd':pre['mdd'],'tax_cagr':aft['cagr'],'tax_end':aft['end'],'avg_exp':m['avg_exp'],'turnover':m['turnover']})
HIST=pd.DataFrame(hist); HIST.to_csv('tqqq_stage50_historical.csv',index=False)

# Matched 10y bootstrap. Event flags are sampled with the same source indices as returns/states.
L=len(A['ret']); nb=int(np.ceil(H/BLOCK)); offs=np.arange(BLOCK); rng=np.random.default_rng(SEED50)
starts=rng.integers(0,L-BLOCK+1,size=(NSIM,nb)); paths=(starts[:,:,None]+offs).reshape(NSIM,-1)[:,:H]
bounds=list(range(BLOCK,H,BLOCK)); mc=[]
for z in range(NSIM):
    ix=paths[z]; B={k:A[k][ix].copy() for k in KEYS}; vc=VIXC[ix].copy(); vh=VIXH[ix].copy(); ev=VIX_EVENT[ix].copy(); cur=current_trace(B)
    tg={'AGGR':target_aggr(B,cur)}
    for nm,mode,vsrc in CASES:
        vx=vc if vsrc=='CLOSE' else vh
        tg[nm]=runner50(B,vx,ev,mode,cur,None,False)
    # Conservative boundary-reset version of strict event/close candidate.
    tg['EVENT_CLOSE_BLOCK_RESET']=runner50(B,vc,ev,'EVENT',cur,bounds,False)
    for nm,t in tg.items():
        pre=account_end(B['ret'],t,COST,0.,None); aft=account_end(B['ret'],t,COST,TAX,None)
        mc.append({'sim':z,'candidate':nm,'tax_end':aft['end'],'tax_cagr':aft['cagr'],'pre_mdd':pre['mdd']})
    if (z+1)%50==0: print('[mc50]',z+1,'/',NSIM,flush=True)
MC=pd.DataFrame(mc); MC.to_csv('tqqq_stage50_mc.csv',index=False)
def q(x,p): return float(np.quantile(np.asarray(x,float),p))
sm=[]
for nm,g in MC.groupby('candidate'):
    sm.append({'candidate':nm,'tax_end_mean':float(g.tax_end.mean()),'tax_end_median':q(g.tax_end,.5),'tax_end_p05':q(g.tax_end,.05),'tax_cagr_median':q(g.tax_cagr,.5),'tax_cagr_p05':q(g.tax_cagr,.05),'mdd_median':q(g.pre_mdd,.5),'mdd_p05':q(g.pre_mdd,.05)})
SUM=pd.DataFrame(sm); SUM.to_csv('tqqq_stage50_mc_summary.csv',index=False)
p=MC.pivot(index='sim',columns='candidate',values=['tax_end','pre_mdd']); pair=[]
for nm in [x[0] for x in CASES]+['EVENT_CLOSE_BLOCK_RESET']:
    ratio=p[('tax_end',nm)]/p[('tax_end','AGGR')]; rs=p[('tax_end',nm)]/p[('tax_end','STATE_CLOSE')]; dm=p[('pre_mdd',nm)]-p[('pre_mdd','AGGR')]
    pair.append({'candidate':nm,'p_end_better_aggr':float(np.mean(ratio>1)),'median_ratio_vs_aggr':float(np.median(ratio)),'p05_ratio_vs_aggr':q(ratio,.05),
                 'median_ratio_vs_state':float(np.median(rs)),'p05_ratio_vs_state':q(rs,.05),'p_mdd_no_worse_aggr':float(np.mean(dm>=0))})
PAIR=pd.DataFrame(pair); PAIR.to_csv('tqqq_stage50_pairwise.csv',index=False)

out={'vix_event_dates_count':int(VIX_EVENT.sum()),'historical':HIST.to_dict('records'),'mc':SUM.to_dict('records'),'pairwise':PAIR.to_dict('records'),
     'notes':['STATE means the persisted VIX BOTTOM/RE-EXTREME state currently stored in B[panic].','EVENT means only actual BOTTOM or RE-EXTREME signal dates returned by vix_state_series.','PRICE ignores the VIX Sequence state/event override and requires dd10 threshold.','HIGH uses same-day VIX High; monthly high is not tradable intramonth without lookahead.'],
     'caveats':['MC57 PIT/survivorship audit unresolved.','NQSAR history is proxy.','USDJPY/dividend tax not modeled.','Moving-block bootstrap is not a forecast distribution.']}
Path('tqqq_stage50_summary.json').write_text(json.dumps(out,ensure_ascii=False,indent=2,default=str))
print('\n=== HIST ===');print(HIST.to_string(index=False));print('\n=== MC ===');print(SUM.to_string(index=False));print('\n=== PAIR ===');print(PAIR.to_string(index=False))
