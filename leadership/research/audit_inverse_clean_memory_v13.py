from __future__ import annotations
import argparse,json
from pathlib import Path
import numpy as np,pandas as pd
import audit_inverse_full_v38_v4 as v4

COSTS=[5,40,80]
FREEZE=pd.Timestamp('2026-03-20')
RECENT=pd.Timestamp('2026-03-23')

def norm(x):
    z=pd.DatetimeIndex(pd.to_datetime(x))
    if z.tz is not None:z=z.tz_convert('America/New_York').tz_localize(None)
    return z.normalize()

def load_base(a):
    feat=pd.read_csv(a.v2_features,compression='gzip',parse_dates=['date']).sort_values('date')
    ordinary=pd.read_csv(Path(a.gross100)/'gross100_final_reset_components/ordinary_PEAK30_PART25_R3_daily.csv.gz',compression='gzip',parse_dates=['date']).rename(columns={'gross_exposure':'gross_exposure_ord','return':'return_ord'})
    reset=pd.read_csv(Path(a.gross100)/'gross100_final_reset_components/rsi_RESET_RISE30_S029_P4_H20_daily.csv.gz',compression='gzip',parse_dates=['date']).rename(columns={'gross_exposure':'gross_exposure_rsi','return':'return_rsi'})
    tq=pd.read_csv(a.tqqq,compression='gzip',parse_dates=['date'])
    d=v4.baseline_components(ordinary,reset,tq,feat);d['date']=norm(d.date);bm=v4.metrics(d.baseline_ret)
    if abs(bm['cagr']-.470025795426962)>5e-6 or abs(bm['mdd']-(-.2323359830178694))>5e-6:raise RuntimeError('baseline mismatch')
    guard=v4.guards(d)['PANIC_OR_STAGE56'];baseev=v4.cooldown_events(v4.signal_defs(d)['CORE_MC'],10)&~guard
    inv=v4.price_returns(norm(d.date),str(d.date.min().date()),str(d.date.max().date()));inv.index=d.index
    return d,bm,guard,baseev,inv

def prior_flags(ev,n):
    vals=pd.to_numeric(ev.qid2,errors='coerce').to_numpy(float);flag=np.zeros(len(ev),bool);mean=np.full(len(ev),np.nan)
    for i in range(len(ev)):
        z=vals[max(0,i-n):i];z=z[np.isfinite(z)]
        if len(z)==n:mean[i]=z.mean();flag[i]=mean[i]>0
    return pd.Series(flag,index=ev.index),pd.Series(mean,index=ev.index)

def sizes(ev,short=3,long=5,mid=.15):
    s,sm=prior_flags(ev,short);l,lm=prior_flags(ev,long);w=np.zeros(len(ev),float);w[s&l]=.30;w[s^l]=mid
    return pd.Series(w,index=ev.index),s,l,sm,lm

def overlay(d,baseev,guard,inv,size_map,cost=5,hold=2,delay=0):
    dates=pd.to_datetime(d.date).dt.normalize();eligible=set(dates[baseev].tolist());m={pd.Timestamp(k):float(v) for k,v in size_map.items() if float(v)>0 and pd.Timestamp(k) in eligible}
    desired=np.zeros(len(d),float)
    for i in np.flatnonzero(baseev.to_numpy(bool)):
        sz=float(m.get(pd.Timestamp(dates.iloc[i]),0.))
        if sz<=0:continue
        start=i+1+delay
        for t in range(start,min(len(d),start+hold)):
            if bool(guard.iloc[t-1]):break
            desired[t]=max(desired[t],sz)
    spare=np.maximum(0,1-pd.to_numeric(d.base_gross,errors='coerce').fillna(0).to_numpy(float));w=np.minimum(desired,spare)
    r=d.baseline_ret.to_numpy(float)+w*pd.to_numeric(inv.QID,errors='coerce').fillna(0).to_numpy(float);tr=np.zeros(len(d));tr[1:]=np.abs(np.diff(w));r-=tr*cost/10000
    return pd.Series(r,index=d.index),w

def pmetrics(d,r,b):
    periods={'TRAIN_2016_2021':('2016-01-04','2021-12-31'),'HOLDOUT_2022_2026':('2022-01-03','2026-03-20'),'2016_2019':('2016-01-04','2019-12-31'),'2020_2021':('2020-01-01','2021-12-31'),'2022_2023':('2022-01-03','2023-12-29'),'2024_2026':('2024-01-02','2026-03-20')}
    m=v4.metrics(r);row={'cagr':m['cagr'],'mdd':m['mdd'],'delta_cagr':m['cagr']-b['cagr'],'delta_mdd':m['mdd']-b['mdd']}
    for p,(aa,bb) in periods.items():
        ix=(d.date>=aa)&(d.date<=bb);mm=v4.metrics(r.loc[ix]);mb=v4.metrics(d.baseline_ret.loc[ix]);row[p+'_delta_cagr']=mm['cagr']-mb['cagr'];row[p+'_delta_mdd']=mm['mdd']-mb['mdd']
    return row

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--events',required=True);ap.add_argument('--v9-summary',required=True);ap.add_argument('--v2-features',required=True);ap.add_argument('--gross100',required=True);ap.add_argument('--tqqq',required=True);ap.add_argument('--output',required=True);a=ap.parse_args();out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
    raw=pd.read_csv(a.events,parse_dates=['signal_date']).sort_values('signal_date').reset_index(drop=True);s9=json.load(open(a.v9_summary));d,bm,guard,baseev,inv=load_base(a)
    official=set(pd.to_datetime(d.loc[baseev,'date']).dt.normalize());post_mask=(raw.signal_date>=pd.Timestamp('2016-01-01'))&(raw.signal_date<=FREEZE);raw_post=set(raw.loc[post_mask,'signal_date'].dt.normalize());extra=sorted(raw_post-official);missing=sorted(official-raw_post)
    clean=raw[(raw.signal_date<pd.Timestamp('2016-01-01'))|raw.signal_date.dt.normalize().isin(official)|(raw.signal_date>=RECENT)].copy().sort_values('signal_date').reset_index(drop=True)
    clean_post=set(clean.loc[(clean.signal_date>=pd.Timestamp('2016-01-01'))&(clean.signal_date<=FREEZE),'signal_date'].dt.normalize())
    if clean_post!=official:raise RuntimeError(f'clean memory universe mismatch missing={sorted(official-clean_post)} extra={sorted(clean_post-official)}')
    w,s3,s5,m3,m5=sizes(clean,3,5,.15);clean['prior3_mean']=m3;clean['prior5_mean']=m5;clean['adaptive_size']=w;clean.to_csv(out/'clean_event_memory.csv',index=False)
    # The old regime must be genuinely suppressed by the adaptive memory itself, not by a calendar/rate gate.
    old_nonzero=clean[(clean.signal_date<pd.Timestamp('2016-01-01'))&(clean.adaptive_size>0)]
    if len(old_nonzero):raise RuntimeError('primary adaptive memory trades old failed era: '+','.join(old_nonzero.signal_date.dt.strftime('%Y-%m-%d')))
    configs=[]
    for sh,lo in [(2,4),(3,5),(4,6)]:
        for mid in [.10,.15,.20]:
            z,*_=sizes(clean,sh,lo,mid);configs.append((f'S{sh}_L{lo}_M{int(mid*100)}',z))
    rows=[]
    for nm,z in configs:
        mp=pd.Series(z.to_numpy(float),index=clean.signal_date.dt.normalize())
        for cost in COSTS:
            r,aw=overlay(d,baseev,guard,inv,mp,cost,2,0);rows.append({'config':nm,'cost_bp':cost,'active_days':int((aw>0).sum()),'avg_weight':float(aw[aw>0].mean()) if (aw>0).any() else 0.,**pmetrics(d,r,bm)})
    grid=pd.DataFrame(rows);grid.to_csv(out/'clean_gross100_grid.csv',index=False)
    # Primary timing stress.
    mp=pd.Series(w.to_numpy(float),index=clean.signal_date.dt.normalize());tim=[]
    for hold in [1,2,3]:
        for delay in [0,1]:
            r,aw=overlay(d,baseev,guard,inv,mp,5,hold,delay);tim.append({'hold':hold,'delay':delay,'active_days':int((aw>0).sum()),**pmetrics(d,r,bm)})
    pd.DataFrame(tim).to_csv(out/'clean_timing_stress.csv',index=False)
    # Crisis and winner concentration.
    stress=[]
    for nm,yrs in {'NONE':[],'NO_2020':[2020],'NO_2022':[2022],'NO_2020_2022':[2020,2022],'NO_2018_2020_2022':[2018,2020,2022]}.items():
        z=w.copy();z[clean.signal_date.dt.year.isin(yrs)]=0;r,_=overlay(d,baseev,guard,inv,pd.Series(z.to_numpy(float),index=clean.signal_date.dt.normalize()),5,2,0);stress.append({'stress':nm,**pmetrics(d,r,bm)})
    ee=clean[(clean.signal_date.dt.normalize().isin(official))&(clean.signal_date<=FREEZE)].copy();ee['inc']=pd.to_numeric(ee.qid2,errors='coerce')*ee.adaptive_size;order=ee[ee.inc>0].sort_values('inc',ascending=False)
    for k in [1,2,3,5]:
        z=w.copy();z.loc[order.head(k).index]=0;r,_=overlay(d,baseev,guard,inv,pd.Series(z.to_numpy(float),index=clean.signal_date.dt.normalize()),5,2,0);stress.append({'stress':f'TOP{k}_POS_REMOVED',**pmetrics(d,r,bm)})
    pd.DataFrame(stress).to_csv(out/'clean_stress.csv',index=False)
    # Paired daily and event-level bootstrap.
    r0,_=overlay(d,baseev,guard,inv,mp,5,2,0);boots=[]
    for block in [20,63,120,252]:boots.append(v4.paired_block_boot(r0,d.baseline_ret,block,5000,13000+block))
    pd.DataFrame(boots).to_csv(out/'clean_block_bootstrap.csv',index=False)
    vals=ee.inc.to_numpy(float);rng=np.random.default_rng(131313);means=[]
    for _ in range(20000):means.append(rng.choice(vals,size=len(vals),replace=True).mean())
    eventboot={'n':len(vals),'weighted_mean':float(vals.mean()),'weighted_median':float(np.median(vals)),'p_mean_positive':float((np.asarray(means)>0).mean()),'mean_p05':float(np.quantile(means,.05))}
    primary=grid[(grid.config=='S3_L5_M15')&(grid.cost_bp==5)].iloc[0].to_dict();plateau=grid[grid.cost_bp==5]
    complete=clean[pd.to_numeric(clean.qid2,errors='coerce').notna()];q=complete.qid2.to_numpy(float);p3=float(q[-3:].mean());p5=float(q[-5:].mean());next_size=.30 if p3>0 and p5>0 else (.15 if (p3>0)^(p5>0) else 0.)
    mar=clean[clean.signal_date>=RECENT][['signal_date','qid2','adaptive_size','prior3_mean','prior5_mean']].to_dict('records')
    summary={'status':'RESEARCH_ONLY_NO_PRODUCTION_CHANGE','memory_universe':{'old_events':int((clean.signal_date<pd.Timestamp('2016-01-01')).sum()),'official_2016_freeze_events':len(official),'recent_dynamic_events':int((clean.signal_date>=RECENT).sum()),'removed_nonofficial_2016_freeze':[str(x.date()) for x in extra],'missing_official': [str(x.date()) for x in missing]},'primary_rule':'Official eligible CORE_MC event only; adaptive memory also updates only on eligible event outcomes. Prior3 mean>0 and prior5 mean>0 =>30%; exactly one=>15%; neither=>0%; spare gross only; hold2; Panic/Stage56 kill. No macro/date gate.','primary_cost5':primary,'plateau':{'configs':len(plateau),'all_full_positive':bool((plateau.delta_cagr>0).all()),'all_train_hold_positive':bool(((plateau.TRAIN_2016_2021_delta_cagr>0)&(plateau.HOLDOUT_2022_2026_delta_cagr>0)).all()),'min_delta_cagr':float(plateau.delta_cagr.min()),'max_delta_cagr':float(plateau.delta_cagr.max())},'event_bootstrap':eventboot,'current':{'latest_market_date':s9.get('dynamic_latest'),'prior3_after_true_oos':p3,'prior5_after_true_oos':p5,'next_eligible_target':next_size},'true_oos':mar,'notes':['This run fixes the last contamination risk: nonofficial 2016-01-11 and 2016-02-09 outcomes do not enter the adaptive memory.','2011-2015 reconstructed eligible events remain in the memory history so the rule must suppress that failed era without a calendar cutoff.','No production change.']}
    (out/'summary_v13.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,default=str),encoding='utf-8');print(json.dumps(summary,ensure_ascii=False,indent=2,default=str),flush=True)
if __name__=='__main__':main()
