from __future__ import annotations
import argparse,json
from pathlib import Path
import numpy as np,pandas as pd
import audit_inverse_full_v38_v4 as v4

COSTS=[5,40,80]

def norm(x):
 z=pd.DatetimeIndex(pd.to_datetime(x));
 if z.tz is not None:z=z.tz_convert('America/New_York').tz_localize(None)
 return z.normalize()
def prior_mean_flags(ev,n):
 v=pd.to_numeric(ev.qid2,errors='coerce').to_numpy(float);f=np.zeros(len(ev),bool);m=np.full(len(ev),np.nan)
 for i in range(len(ev)):
  z=v[max(0,i-n):i];z=z[np.isfinite(z)]
  if len(z)==n:m[i]=z.mean();f[i]=m[i]>0
 return pd.Series(f,index=ev.index),pd.Series(m,index=ev.index)
def event_sizes(ev,short=3,long=5,mid=.15,use_macro=False):
 s,_=prior_mean_flags(ev,short);l,_=prior_mean_flags(ev,long);w=np.zeros(len(ev),float);w[s&l]=.30;w[s^l]=mid
 if use_macro:
  macro=~((pd.to_numeric(ev.DGS2,errors='coerce')<1.)&(pd.to_numeric(ev.curve_2s10s,errors='coerce')>1.));w[~macro]=0
 return pd.Series(w,index=ev.index),s,l
def load_base(a):
 feat=pd.read_csv(a.v2_features,compression='gzip',parse_dates=['date']).sort_values('date');ordinary=pd.read_csv(Path(a.gross100)/'gross100_final_reset_components/ordinary_PEAK30_PART25_R3_daily.csv.gz',compression='gzip',parse_dates=['date']).rename(columns={'gross_exposure':'gross_exposure_ord','return':'return_ord'});reset=pd.read_csv(Path(a.gross100)/'gross100_final_reset_components/rsi_RESET_RISE30_S029_P4_H20_daily.csv.gz',compression='gzip',parse_dates=['date']).rename(columns={'gross_exposure':'gross_exposure_rsi','return':'return_rsi'});tq=pd.read_csv(a.tqqq,compression='gzip',parse_dates=['date']);d=v4.baseline_components(ordinary,reset,tq,feat);d['date']=norm(d.date);bm=v4.metrics(d.baseline_ret)
 if abs(bm['cagr']-.470025795426962)>5e-6 or abs(bm['mdd']-(-.2323359830178694))>5e-6:raise RuntimeError('baseline mismatch')
 guard=v4.guards(d)['PANIC_OR_STAGE56'];baseev=v4.cooldown_events(v4.signal_defs(d)['CORE_MC'],10)&~guard;inv=v4.price_returns(norm(d.date),str(d.date.min().date()),str(d.date.max().date()));inv.index=d.index
 return d,bm,guard,baseev,inv
def overlay(d,baseev,guard,inv,size_map,cost=5,hold=2,delay=0):
 dates=pd.to_datetime(d.date).dt.normalize();eligible=set(dates[baseev].tolist());nonzero={pd.Timestamp(k):float(v) for k,v in size_map.items() if float(v)>0 and pd.Timestamp(k)<=pd.Timestamp('2026-03-20')};bad=set(nonzero)-eligible
 if bad:raise RuntimeError('nonzero adaptive size on non-V4 event dates: '+','.join(str(x.date()) for x in sorted(bad)))
 desired=np.zeros(len(d),float)
 for i in np.flatnonzero(baseev.to_numpy(bool)):
  sz=float(nonzero.get(pd.Timestamp(dates.iloc[i]),0.));
  if sz<=0:continue
  start=i+1+delay
  for t in range(start,min(len(d),start+hold)):
   if bool(guard.iloc[t-1]):break
   desired[t]=max(desired[t],sz)
 spare=np.maximum(0,1-pd.to_numeric(d.base_gross,errors='coerce').fillna(0).to_numpy(float));w=np.minimum(desired,spare);r=d.baseline_ret.to_numpy(float)+w*pd.to_numeric(inv.QID,errors='coerce').fillna(0).to_numpy(float);tr=np.zeros(len(d));tr[1:]=np.abs(np.diff(w));r-=tr*cost/10000
 return pd.Series(r,index=d.index),w
def pmetrics(d,r,b):
 periods={'TRAIN_2016_2021':('2016-01-04','2021-12-31'),'HOLDOUT_2022_2026':('2022-01-03','2026-03-20'),'2016_2019':('2016-01-04','2019-12-31'),'2020_2021':('2020-01-01','2021-12-31'),'2022_2023':('2022-01-03','2023-12-29'),'2024_2026':('2024-01-02','2026-03-20')};m=v4.metrics(r);row={'cagr':m['cagr'],'mdd':m['mdd'],'delta_cagr':m['cagr']-b['cagr'],'delta_mdd':m['mdd']-b['mdd']}
 for p,(aa,bb) in periods.items():
  x=(d.date>=aa)&(d.date<=bb);mm=v4.metrics(r.loc[x]);bbm=v4.metrics(d.baseline_ret.loc[x]);row[p+'_delta_cagr']=mm['cagr']-bbm['cagr'];row[p+'_delta_mdd']=mm['mdd']-bbm['mdd']
 return row
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--events',required=True);ap.add_argument('--v9-summary',required=True);ap.add_argument('--v2-features',required=True);ap.add_argument('--gross100',required=True);ap.add_argument('--tqqq',required=True);ap.add_argument('--output',required=True);a=ap.parse_args();out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
 ev=pd.read_csv(a.events,parse_dates=['signal_date']).sort_values('signal_date').reset_index(drop=True);s9=json.load(open(a.v9_summary));d,bm,guard,baseev,inv=load_base(a);v4dates=set(pd.to_datetime(d.loc[baseev,'date']).dt.normalize());histdates=set(ev[(ev.signal_date>='2016-01-01')&(ev.signal_date<='2026-03-20')].signal_date.dt.normalize());extra=sorted(histdates-v4dates);missing=sorted(v4dates-histdates)
 # Primary simplification: adaptive memory only; macro is diagnostic/safety comparison, not required for activation.
 w,s3,s5=event_sizes(ev,3,5,.15,False);wm,_,_=event_sizes(ev,3,5,.15,True);ev['adaptive_only_size']=w;ev['macro_adaptive_size']=wm;ev.to_csv(out/'final_event_ledger.csv',index=False)
 configs=[]
 for sh,lo in [(2,4),(3,5),(4,6)]:
  for mid in [.10,.15,.20]:
   z,_,_=event_sizes(ev,sh,lo,mid,False);configs.append((f'ADAPT_S{sh}_L{lo}_M{int(mid*100)}',z))
 configs.append(('MACRO_ADAPT_S3_L5_M15',wm))
 rows=[]
 for nm,z in configs:
  sm=pd.Series(z.to_numpy(float),index=ev.signal_date.dt.normalize())
  for cost in COSTS:
   r,aw=overlay(d,baseev,guard,inv,sm,cost,2,0);rows.append({'config':nm,'cost_bp':cost,'hold':2,'delay':0,'active_days':int((aw>0).sum()),'avg_weight':float(aw[aw>0].mean()) if (aw>0).any() else 0.,**pmetrics(d,r,bm)})
 # Hold and execution-delay stress for primary, standard cost.
 sm=pd.Series(w.to_numpy(float),index=ev.signal_date.dt.normalize())
 timing=[]
 for h in [1,2,3]:
  for delay in [0,1]:
   r,aw=overlay(d,baseev,guard,inv,sm,5,h,delay);timing.append({'hold':h,'delay_sessions_after_next_open':delay,'active_days':int((aw>0).sum()),**pmetrics(d,r,bm)})
 pd.DataFrame(rows).to_csv(out/'final_gross100_grid.csv',index=False);pd.DataFrame(timing).to_csv(out/'timing_stress.csv',index=False)
 # Crisis-year and event-concentration stress on primary by zeroing selected event sizes.
 stress=[]
 exclusions={'NONE':[],'NO_2020':[2020],'NO_2022':[2022],'NO_2020_2022':[2020,2022],'NO_2018_2020_2022':[2018,2020,2022]}
 for nm,yrs in exclusions.items():
  z=w.copy();z[ev.signal_date.dt.year.isin(yrs)]=0;mp=pd.Series(z.to_numpy(float),index=ev.signal_date.dt.normalize());r,_=overlay(d,baseev,guard,inv,mp,5,2,0);stress.append({'stress':nm,**pmetrics(d,r,bm)})
 # Event incremental ranking uses pre-freeze eligible V4 dates and actual assigned size.
 ee=ev[(ev.signal_date.dt.normalize().isin(v4dates))&(ev.signal_date<='2026-03-20')].copy();ee['inc']=ee.qid2*w.loc[ee.index].to_numpy(float);order=ee[ee.inc>0].sort_values('inc',ascending=False)
 for k in [1,2,3,5]:
  z=w.copy();z.loc[order.head(k).index]=0;mp=pd.Series(z.to_numpy(float),index=ev.signal_date.dt.normalize());r,_=overlay(d,baseev,guard,inv,mp,5,2,0);stress.append({'stress':f'TOP{k}_POS_EVENTS_REMOVED',**pmetrics(d,r,bm)})
 pd.DataFrame(stress).to_csv(out/'crisis_concentration_stress.csv',index=False)
 # Paired calendar block bootstrap of primary daily strategy vs audited baseline.
 r0,_=overlay(d,baseev,guard,inv,sm,5,2,0);boots=[]
 for block in [20,63,120,252]:boots.append(v4.paired_block_boot(r0,d.baseline_ret,block,5000,12000+block))
 pd.DataFrame(boots).to_csv(out/'paired_block_bootstrap.csv',index=False)
 # Event bootstrap across actual weighted incremental returns; one event is one cluster.
 vals=(ee.qid2*w.loc[ee.index].to_numpy(float)).to_numpy(float);rng=np.random.default_rng(121212);means=[];sums=[]
 for _ in range(20000):
  z=rng.choice(vals,size=len(vals),replace=True);means.append(z.mean());sums.append(np.prod(1+z)-1)
 eventboot={'n':len(vals),'mean':float(vals.mean()),'median':float(np.median(vals)),'p_mean_positive':float((np.array(means)>0).mean()),'mean_p05':float(np.quantile(means,.05)),'cum_p05':float(np.quantile(sums,.05)),'cum_median':float(np.median(sums))}
 # Current state after true OOS event.
 q=pd.to_numeric(ev.qid2,errors='coerce').dropna().to_numpy(float);p3=float(q[-3:].mean());p5=float(q[-5:].mean());next_size=.30 if p3>0 and p5>0 else (.15 if (p3>0)^(p5>0) else 0.)
 primary=pd.DataFrame(rows);pr=primary[(primary.config=='ADAPT_S3_L5_M15')&(primary.cost_bp==5)].iloc[0].to_dict();grid5=primary[(primary.cost_bp==5)&primary.config.str.startswith('ADAPT_')]
 summary={'status':'RESEARCH_ONLY_NO_PRODUCTION_CHANGE','event_alignment':{'v4_events':len(v4dates),'long_history_events_2016_freeze':len(histdates),'extra_long_history_dates':[str(x.date()) for x in extra],'missing_long_history_dates':[str(x.date()) for x in missing],'note':'Any nonzero adaptive size outside official V4 events aborts the run.'},'primary_rule':'QID from spare gross only; eligible V4 CORE_MC event; prior 3-event mean and prior 5-event mean both positive ->30%, exactly one positive ->15%, neither ->0%; hold2; Panic/Stage56 kill. Macro rate regime is not required.','primary_cost5':pr,'adaptive_plateau':{'configs':len(grid5),'all_positive_full':bool((grid5.delta_cagr>0).all()),'all_positive_train_holdout':bool(((grid5.TRAIN_2016_2021_delta_cagr>0)&(grid5.HOLDOUT_2022_2026_delta_cagr>0)).all()),'delta_cagr_min':float(grid5.delta_cagr.min()),'delta_cagr_max':float(grid5.delta_cagr.max())},'event_bootstrap':eventboot,'current':{'latest_market_date':s9.get('dynamic_latest'),'prior3_mean_after_latest_event':p3,'prior5_mean_after_latest_event':p5,'next_eligible_signal_target':next_size},'true_oos':ev[ev.signal_date>=pd.Timestamp('2026-03-23')][['signal_date','qid2','adaptive_only_size']].to_dict('records'),'notes':['Macro filter is dropped from the primary rule if adaptive-only survives these stresses; this avoids relying on a post-hoc era separator.','Execution delay stress means entering one additional session later than the normal next-open convention.','The Mar-30 true-OOS loss remains included in the monitor state.','No production change.']}
 (out/'summary_v12.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,default=str),encoding='utf-8');print(json.dumps(summary,ensure_ascii=False,indent=2,default=str),flush=True)
if __name__=='__main__':main()
