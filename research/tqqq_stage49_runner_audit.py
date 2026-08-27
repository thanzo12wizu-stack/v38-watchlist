from __future__ import annotations
from pathlib import Path
import json, numpy as np, pandas as pd

# Reuse exact Stage46 data / hierarchy / tax machinery without running its scan.
src=Path('research/tqqq_stage46_crash_seed_refinement.py').read_text()
prefix=src.split('SPECS=[]')[0]
exec(compile(prefix,'stage46-prefix','exec'),globals())

print('\n=== STAGE49 RUNNER OVERLAP / VIX-BOTTOM AUDIT ===',flush=True)
COST=.0005; TAX=.20315; H=2520; BLOCK=120; NSIM=1000; SEED49=490827
SPEC={'name':'FINAL_V23_S50_D20_L30_M80','vth':23.0,'s50':-0.50,'ddcut':-0.02,'lookback':30,'rec':'R10','maxd':80}
QQQ_CLOSE=qqq.Close.astype(float).reindex(pd.DatetimeIndex(DTS)).to_numpy(float)


def audited_runner(B,vx,s,cur=None,consume_active_seeds=False,boundaries=None,trace=False):
    if cur is None: cur=current_trace(B)
    base=target_aggr(B,cur)
    t=base.copy(); seed=seed46(B,vx,s)
    rec=consec_true(B['gte10'],2)&(B['nq']!=0)&(B['mc']>=35)
    bset=set([] if boundaries is None else boundaries)
    active=False; entry=-1; consumed=-1; age=10**9; origin=-1
    active_mask=np.zeros(len(t),bool); origin_arr=np.full(len(t),-1,int); entries=[]; exits=[]
    stale_rearm=0; last_exit=-10**9; last_origin=-10**9
    for i in range(len(t)):
        if i in bset:
            if active:
                exits.append({'entry_i':entry,'exit_i':i,'origin_i':origin,'reason':'BLOCK_RESET'})
            active=False; entry=-1; origin=-1; consumed=-1; age=10**9
        if seed[i]: age=0
        else: age+=1
        recent=age<=s['lookback']
        if (not active) and recent and rec[i] and (not cur['risklock'][i]):
            last=np.flatnonzero(seed[:i+1]); sid=int(last[-1]) if len(last) else -1
            if sid>consumed:
                if sid<=last_exit and sid>last_origin: stale_rearm+=1
                active=True; entry=i; origin=sid; consumed=sid
                entries.append({'entry_i':i,'origin_i':sid})
        if active:
            if consume_active_seeds and seed[i]: consumed=max(consumed,i)
            hold=i-entry
            reason=None
            if cur['risklock'][i]: reason='RISKLOCK'
            elif B['nq'][i]==0: reason='NQ_RED'
            elif ((not B['a200'][i]) and (not B['a252'][i])): reason='LONG_BROKEN'
            elif hold>=s['maxd']: reason='MAXD'
            if reason is not None:
                exits.append({'entry_i':entry,'exit_i':i,'origin_i':origin,'reason':reason})
                last_exit=i; last_origin=origin; active=False; entry=-1; origin=-1
            else:
                active_mask[i]=True; origin_arr[i]=origin; t[i]=max(t[i],1.0)
    if active:
        exits.append({'entry_i':entry,'exit_i':len(t)-1,'origin_i':origin,'reason':'END'})
    out={'target':np.clip(t,0,1),'base':base,'seed':seed,'rec':rec,'active':active_mask,'origin':origin_arr,'entries':entries,'exits':exits,'stale_rearm_count':stale_rearm}
    return out if trace else out['target']

# ---------- actual-history event audit ----------
curA=current_trace(A)
ORIG=audited_runner(A,VIXLVL,SPEC,curA,False,None,True)
FIX=audited_runner(A,VIXLVL,SPEC,curA,True,None,True)

# Seed clusters: a new episode only when > lookback trading days have elapsed since prior seed.
seed_idx=np.flatnonzero(ORIG['seed']); clusters=[]
for i in seed_idx:
    if not clusters or i-clusters[-1][-1]>SPEC['lookback']: clusters.append([int(i)])
    else: clusters[-1].append(int(i))
cluster_of={i:k for k,c in enumerate(clusters) for i in c}

# Match entry to its exit record.
exit_map={}
for x in ORIG['exits']: exit_map.setdefault(x['entry_i'],x)
rows=[]
for j,e in enumerate(ORIG['entries']):
    ei=int(e['entry_i']); sid=int(e['origin_i']); ex=exit_map.get(ei,{'exit_i':len(A['ret'])-1,'reason':'END'}); xi=int(ex['exit_i'])
    cid=cluster_of.get(sid,-1); c=clusters[cid] if cid>=0 else [sid]
    # Event window from 10 sessions before first seed through 63 sessions after last seed.
    w0=max(0,c[0]-10); w1=min(len(A['ret'])-1,c[-1]+63)
    qslice=QQQ_CLOSE[w0:w1+1]; vslice=VIXLVL[w0:w1+1]
    qlow=w0+int(np.nanargmin(qslice)); vpk=w0+int(np.nanargmax(vslice))
    act=np.flatnonzero(ORIG['active'] & (ORIG['origin']==sid));
    inc=act[ORIG['base'][act]<.999] if len(act) else np.array([],int)
    newseed=act[(ORIG['seed'][act]) & (act>sid)] if len(act) else np.array([],int)
    sleeve=curA.get('sleeve',np.zeros(len(A['ret']),np.int8)); strong=curA.get('strong',np.zeros(len(A['ret']),bool))
    prev_same=False
    if j>0:
        psid=int(ORIG['entries'][j-1]['origin_i']); prev_same=(cluster_of.get(psid,-2)==cid)
    rows.append({
        'event':j+1,'cluster':cid+1,'seed_date':str(pd.Timestamp(DTS.iloc[sid]).date()),'seed_vix':float(VIXLVL[sid]),'seed_s50_atr':float(A['s50a'][sid]),'seed_dd10':float(A['dd10'][sid]),
        'entry_signal_date':str(pd.Timestamp(DTS.iloc[ei]).date()),'execution_open_date':str(pd.Timestamp(DTS.iloc[min(ei+1,len(DTS)-1)]).date()),
        'exit_signal_date':str(pd.Timestamp(DTS.iloc[xi]).date()),'exit_reason':ex['reason'],'active_signal_days':int(len(act)),'incremental_days_base_lt100':int(len(inc)),
        'new_seed_days_while_active':int(len(newseed)),'same_seed_cluster_as_prev_entry':bool(prev_same),
        'already_base100_days':int(np.sum(ORIG['base'][act]>=.999)) if len(act) else 0,'gb_overlap_days':int(np.sum(sleeve[act]==2)) if len(act) else 0,
        'strong_overlap_days':int(np.sum(strong[act])) if len(act) else 0,'panic_overlap_days':int(np.sum(A['panic'][act])) if len(act) else 0,'risklock_overlap_days':int(np.sum(curA['risklock'][act])) if len(act) else 0,
        'vix_peak_date':str(pd.Timestamp(DTS.iloc[vpk]).date()),'vix_peak':float(VIXLVL[vpk]),'qqq_low_date':str(pd.Timestamp(DTS.iloc[qlow]).date()),'qqq_low':float(QQQ_CLOSE[qlow]),
        'qqq_low_minus_vix_peak_td':int(qlow-vpk),'entry_minus_qqq_low_td':int(ei-qlow),'execution_minus_qqq_low_td':int(min(ei+1,len(DTS)-1)-qlow),
        'entry_before_final_low_in_window':bool(ei<qlow)
    })
EVENTS=pd.DataFrame(rows); EVENTS.to_csv('tqqq_stage49_events.csv',index=False)

# Cluster-level VIX peak / QQQ low timing.
cr=[]
for k,c in enumerate(clusters):
    w0=max(0,c[0]-10); w1=min(len(A['ret'])-1,c[-1]+63)
    qlow=w0+int(np.nanargmin(QQQ_CLOSE[w0:w1+1])); vpk=w0+int(np.nanargmax(VIXLVL[w0:w1+1]))
    cr.append({'cluster':k+1,'first_seed':str(pd.Timestamp(DTS.iloc[c[0]]).date()),'last_seed':str(pd.Timestamp(DTS.iloc[c[-1]]).date()),'seed_days':len(c),
               'vix_peak_date':str(pd.Timestamp(DTS.iloc[vpk]).date()),'vix_peak':float(VIXLVL[vpk]),'qqq_low_date':str(pd.Timestamp(DTS.iloc[qlow]).date()),'qqq_low_minus_vix_peak_td':int(qlow-vpk)})
CLUSTERS=pd.DataFrame(cr); CLUSTERS.to_csv('tqqq_stage49_seed_clusters.csv',index=False)

# Historical metrics: original vs stale-seed-safe variant.
hist=[]
for nm,t in [('AGGR',target_aggr(A,curA)),('ORIGINAL',ORIG['target']),('FIX_CONSUME_ACTIVE_SEEDS',FIX['target'])]:
    m,_,_=from_target(A,t,COST); pre=account_end(A['ret'],t,COST,0.,DTS); aft=account_end(A['ret'],t,COST,TAX,DTS)
    hist.append({'candidate':nm,'pre_cagr':pre['cagr'],'pre_mdd':pre['mdd'],'tax_cagr':aft['cagr'],'tax_end':aft['end'],'avg_exp':m['avg_exp'],'turnover':m['turnover']})
HIST=pd.DataFrame(hist); HIST.to_csv('tqqq_stage49_historical.csv',index=False)

# ---------- matched 10y bootstrap robustness ----------
# Compare original logic, stale-seed-safe logic, and conservative runner reset at each 120d block boundary.
L=len(A['ret']); nb=int(np.ceil(H/BLOCK)); offs=np.arange(BLOCK); rng=np.random.default_rng(SEED49)
starts=rng.integers(0,L-BLOCK+1,size=(NSIM,nb)); paths=(starts[:,:,None]+offs).reshape(NSIM,-1)[:,:H]
bounds=list(range(BLOCK,H,BLOCK)); mc=[]
for z in range(NSIM):
    ix=paths[z]; B={k:A[k][ix].copy() for k in KEYS}; vx=VIXLVL[ix].copy(); cur=current_trace(B)
    tg={
      'AGGR':target_aggr(B,cur),
      'ORIGINAL':audited_runner(B,vx,SPEC,cur,False,None,False),
      'FIX_CONSUME_ACTIVE_SEEDS':audited_runner(B,vx,SPEC,cur,True,None,False),
      'FIX_PLUS_BLOCK_RESET':audited_runner(B,vx,SPEC,cur,True,bounds,False),
    }
    for nm,t in tg.items():
        pre=account_end(B['ret'],t,COST,0.,None); aft=account_end(B['ret'],t,COST,TAX,None)
        mc.append({'sim':z,'candidate':nm,'tax_end':aft['end'],'tax_cagr':aft['cagr'],'pre_mdd':pre['mdd']})
    if (z+1)%50==0: print('[mc49]',z+1,'/',NSIM,flush=True)
MC=pd.DataFrame(mc); MC.to_csv('tqqq_stage49_mc.csv',index=False)

def q(x,p): return float(np.quantile(np.asarray(x,float),p))
sm=[]
for nm,g in MC.groupby('candidate'):
    sm.append({'candidate':nm,'tax_end_mean':float(g.tax_end.mean()),'tax_end_median':q(g.tax_end,.5),'tax_end_p05':q(g.tax_end,.05),'tax_cagr_median':q(g.tax_cagr,.5),'tax_cagr_p05':q(g.tax_cagr,.05),'mdd_median':q(g.pre_mdd,.5),'mdd_p05':q(g.pre_mdd,.05)})
SUM=pd.DataFrame(sm); SUM.to_csv('tqqq_stage49_mc_summary.csv',index=False)
p=MC.pivot(index='sim',columns='candidate',values=['tax_end','pre_mdd']); pair=[]
for nm in ['ORIGINAL','FIX_CONSUME_ACTIVE_SEEDS','FIX_PLUS_BLOCK_RESET']:
    ratio=p[('tax_end',nm)]/p[('tax_end','AGGR')]
    ro=p[('tax_end',nm)]/p[('tax_end','ORIGINAL')]
    dm=p[('pre_mdd',nm)]-p[('pre_mdd','AGGR')]
    pair.append({'candidate':nm,'p_end_better_aggr':float(np.mean(ratio>1)),'median_end_ratio_vs_aggr':float(np.median(ratio)),'p05_end_ratio_vs_aggr':q(ratio,.05),
                 'median_end_ratio_vs_original':float(np.median(ro)),'p05_end_ratio_vs_original':q(ro,.05),'p_mdd_no_worse_aggr':float(np.mean(dm>=0))})
PAIR=pd.DataFrame(pair); PAIR.to_csv('tqqq_stage49_pairwise.csv',index=False)

summary={
 'spec':SPEC,
 'seed_days':int(len(seed_idx)),'seed_clusters_30td':int(len(clusters)),'runner_entries':int(len(ORIG['entries'])),'runner_exits':int(len(ORIG['exits'])),
 'stale_rearm_count_internal':int(ORIG['stale_rearm_count']),
 'entries_same_cluster_as_previous':int(EVENTS.same_seed_cluster_as_prev_entry.sum()) if len(EVENTS) else 0,
 'events_with_seed_during_active':int((EVENTS.new_seed_days_while_active>0).sum()) if len(EVENTS) else 0,
 'events_entry_before_qqq_low':int(EVENTS.entry_before_final_low_in_window.sum()) if len(EVENTS) else 0,
 'risklock_overlap_days':int(EVENTS.risklock_overlap_days.sum()) if len(EVENTS) else 0,
 'incremental_runner_days':int(EVENTS.incremental_days_base_lt100.sum()) if len(EVENTS) else 0,
 'already_base100_runner_days':int(EVENTS.already_base100_days.sum()) if len(EVENTS) else 0,
 'historical':HIST.to_dict('records'),'mc':SUM.to_dict('records'),'pairwise':PAIR.to_dict('records'),
 'caveats':['MC57 PIT/survivorship audit unresolved.','NQSAR history is proxy.','USDJPY/dividend tax not modeled.','Moving-block bootstrap is not a forecast distribution; FIX_PLUS_BLOCK_RESET specifically audits runner state across block boundaries.']
}
Path('tqqq_stage49_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,default=str))
print('\n=== SUMMARY ==='); print(json.dumps(summary,ensure_ascii=False,indent=2,default=str))
print('\n=== EVENTS ==='); print(EVENTS.to_string(index=False))
print('\n=== MC SUMMARY ==='); print(SUM.to_string(index=False))
print('\n=== PAIRWISE ==='); print(PAIR.to_string(index=False))
