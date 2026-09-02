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

def hist_flags(ev,n):
 vals=pd.to_numeric(ev.qid2,errors='coerce').to_numpy(float);out=np.zeros(len(ev),bool);means=np.full(len(ev),np.nan)
 for i in range(len(ev)):
  prior=vals[max(0,i-n):i];prior=prior[np.isfinite(prior)]
  if len(prior)==n:means[i]=prior.mean();out[i]=means[i]>0
 return pd.Series(out,index=ev.index),pd.Series(means,index=ev.index)
def sizes(ev,short=3,long=5,mid=.15):
 s,_=hist_flags(ev,short);l,_=hist_flags(ev,long);macro=~((pd.to_numeric(ev.DGS2,errors='coerce')<1.0)&(pd.to_numeric(ev.curve_2s10s,errors='coerce')>1.0))
 w=np.zeros(len(ev),float);w[macro&(s&l)]=.30;w[macro&(s^l)]=mid
 return pd.Series(w,index=ev.index),s,l,macro
def event_metrics(ev,w,aa,bb):
 m=(ev.signal_date>=aa)&(ev.signal_date<=bb)&pd.to_numeric(ev.qid2,errors='coerce').notna();r=pd.to_numeric(ev.loc[m,'qid2'],errors='coerce').to_numpy(float);ww=w.loc[m].to_numpy(float);take=ww>0
 return {'signals':int(m.sum()),'trades':int(take.sum()),'avg_size_on_trade':float(ww[take].mean()) if take.any() else 0.,'mean_qid_when_traded':float(r[take].mean()) if take.any() else np.nan,'win_when_traded':float((r[take]>0).mean()) if take.any() else np.nan,'cum_incremental':float(np.prod(1+ww*r)-1) if len(r) else 0.}
def add_qid_overlay(d,inv,event_size,guard,cost):
 desired=np.zeros(len(d),float);dates=pd.to_datetime(d.date).dt.normalize();mp=event_size.copy();mp.index=pd.to_datetime(mp.index).normalize()
 for i in np.flatnonzero(dates.isin(mp.index).to_numpy()):
  size=float(mp.get(pd.Timestamp(dates.iloc[i]),0.))
  if size<=0:continue
  for t in range(i+1,min(len(d),i+3)):
   if bool(guard.iloc[t-1]):break
   desired[t]=max(desired[t],size)
 spare=np.maximum(0,1-pd.to_numeric(d.base_gross,errors='coerce').fillna(0).to_numpy(float));w=np.minimum(desired,spare)
 rp=pd.to_numeric(inv.QID,errors='coerce').fillna(0).to_numpy(float);r=d.baseline_ret.to_numpy(float)+w*rp
 tr=np.zeros(len(d));tr[1:]=np.abs(np.diff(w));r-=tr*cost/10000
 return pd.Series(r,index=d.index),w

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--events',required=True);ap.add_argument('--v9-summary',required=True);ap.add_argument('--v2-features',required=True);ap.add_argument('--gross100',required=True);ap.add_argument('--tqqq',required=True);ap.add_argument('--output',required=True)
 a=ap.parse_args();out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
 ev=pd.read_csv(a.events,parse_dates=['signal_date']).sort_values('signal_date').reset_index(drop=True);s9=json.load(open(a.v9_summary))
 periods={'ALL':('2011-01-03','2099-12-31'),'OLD_2011_2015':('2011-01-03','2015-12-31'),'POST_2016':('2016-01-01','2099-12-31'),'DISCOVERY_2011_2021':('2011-01-03','2021-12-31'),'HOLDOUT_2022_FREEZE':('2022-01-01','2026-03-20'),'POST_2024_FREEZE':('2024-01-01','2026-03-20'),'TRUE_OOS':('2026-03-23','2099-12-31')}
 rows=[];configs=[]
 for sh,lo in [(2,4),(3,5),(4,6)]:
  for mid in [.10,.15,.20]:
   w,gs,gl,gm=sizes(ev,sh,lo,mid);name=f'S{sh}_L{lo}_M{int(mid*100)}';configs.append((name,w))
   for p,(aa,bb) in periods.items():rows.append({'config':name,'short_n':sh,'long_n':lo,'mid_size':mid,'period':p,**event_metrics(ev,w,aa,bb)})
 pd.DataFrame(rows).to_csv(out/'adaptive_sizing_event_grid.csv',index=False)
 w,gs,gl,gm=sizes(ev,3,5,.15);ev['macro_on']=gm;ev['prior3_on']=gs;ev['prior5_on']=gl;ev['target_size_3_5_15']=w;ev.to_csv(out/'adaptive_sizing_event_ledger.csv',index=False)
 # Frozen Gross100 integration.
 feat=pd.read_csv(a.v2_features,compression='gzip',parse_dates=['date']).sort_values('date');ordinary=pd.read_csv(Path(a.gross100)/'gross100_final_reset_components/ordinary_PEAK30_PART25_R3_daily.csv.gz',compression='gzip',parse_dates=['date']).rename(columns={'gross_exposure':'gross_exposure_ord','return':'return_ord'});reset=pd.read_csv(Path(a.gross100)/'gross100_final_reset_components/rsi_RESET_RISE30_S029_P4_H20_daily.csv.gz',compression='gzip',parse_dates=['date']).rename(columns={'gross_exposure':'gross_exposure_rsi','return':'return_rsi'});tq=pd.read_csv(a.tqqq,compression='gzip',parse_dates=['date']);d=v4.baseline_components(ordinary,reset,tq,feat);d['date']=norm(d.date);bm=v4.metrics(d.baseline_ret)
 if abs(bm['cagr']-.470025795426962)>5e-6:raise RuntimeError('baseline mismatch')
 guard=v4.guards(d)['PANIC_OR_STAGE56'];inv=v4.price_returns(norm(d.date),str(d.date.min().date()),str(d.date.max().date()));inv.index=d.index
 periods2={'TRAIN_2016_2021':('2016-01-04','2021-12-31'),'HOLDOUT_2022_2026':('2022-01-03','2026-03-20'),'2016_2019':('2016-01-04','2019-12-31'),'2020_2021':('2020-01-01','2021-12-31'),'2022_2023':('2022-01-03','2023-12-29'),'2024_2026':('2024-01-02','2026-03-20')}
 prows=[]
 for name,w0 in configs:
  es=pd.Series(w0.to_numpy(float),index=ev.signal_date.dt.normalize());es=es[es.index<=pd.Timestamp('2026-03-20')]
  for cost in COSTS:
   r,actual=add_qid_overlay(d,inv,es,guard,cost);mm=v4.metrics(r);row={'config':name,'cost_bp':cost,'cagr':mm['cagr'],'mdd':mm['mdd'],'delta_cagr':mm['cagr']-bm['cagr'],'delta_mdd':mm['mdd']-bm['mdd'],'active_weight_days':int((actual>0).sum()),'avg_qid_weight_when_active':float(actual[actual>0].mean()) if (actual>0).any() else 0.}
   for p,(aa,bb) in periods2.items():
    m=(d.date>=aa)&(d.date<=bb);x=v4.metrics(r.loc[m]);b=v4.metrics(d.baseline_ret.loc[m]);row[p+'_delta_cagr']=x['cagr']-b['cagr'];row[p+'_delta_mdd']=x['mdd']-b['mdd']
   prows.append(row)
 pd.DataFrame(prows).to_csv(out/'adaptive_sizing_gross100.csv',index=False)
 # Current state is computed AFTER incorporating the Mar-30 OOS outcome, unlike pre-event gate columns.
 vals=pd.to_numeric(ev.qid2,errors='coerce').dropna().to_numpy(float);last3=float(vals[-3:].mean()) if len(vals)>=3 else np.nan;last5=float(vals[-5:].mean()) if len(vals)>=5 else np.nan
 latest=s9.get('latest_market_features',{});d2=float(latest.get('DGS2',np.nan));curve=float(latest.get('curve_2s10s',np.nan));macro_now=bool(np.isfinite(d2) and np.isfinite(curve) and not(d2<1.0 and curve>1.0));s_on=bool(np.isfinite(last3) and last3>0);l_on=bool(np.isfinite(last5) and last5>0);target=.30 if macro_now and s_on and l_on else (.15 if macro_now and (s_on^l_on) else 0.)
 true_oos=ev[ev.signal_date>=pd.Timestamp('2026-03-23')][['signal_date','qid2','target_size_3_5_15','DGS2','curve_2s10s']].to_dict('records')
 pg=pd.DataFrame(prows);base=pg[(pg.config=='S3_L5_M15')&(pg.cost_bp==5)].iloc[0].to_dict();grid5=pg[pg.cost_bp==5];plateau={'configs':len(grid5),'positive_full':int((grid5.delta_cagr>0).sum()),'positive_train_holdout':int(((grid5.TRAIN_2016_2021_delta_cagr>0)&(grid5.HOLDOUT_2022_2026_delta_cagr>0)).sum()),'delta_cagr_min':float(grid5.delta_cagr.min()),'delta_cagr_max':float(grid5.delta_cagr.max())}
 summary={'status':'RESEARCH_ONLY_NO_PRODUCTION_CHANGE','primary':'Macro ON unless lagged DGS2<1% and 2s10s>1%; QID 30% when prior3 and prior5 eligible-event means are both >0, 15% when exactly one is >0, otherwise 0%; hold 2 sessions; spare gross only; Panic/Stage56 kills.','primary_gross100_cost5':base,'sizing_plateau_cost5':plateau,'current':{'latest_market_date':s9.get('dynamic_latest'),'DGS2':d2,'curve_2s10s':curve,'macro_on':macro_now,'prior3_mean_after_latest_event':last3,'prior5_mean_after_latest_event':last5,'prior3_on':s_on,'prior5_on':l_on,'next_signal_target_size':target},'true_oos':true_oos,'notes':['The 0/15/30 sizing rule was specified before this V11 run; 10/15/20 mid-sizes and 2/4,3/5,4/6 event-memory pairs are sensitivity checks, not an optimizer.','The 2026-03-30 true-OOS loss remains included. Its pre-event size under the primary rule was 30%; after observing that loss the next-signal size falls to 15%.','No production change.']}
 (out/'summary_v11.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,default=str),encoding='utf-8');print(json.dumps(summary,ensure_ascii=False,indent=2,default=str),flush=True)
if __name__=='__main__':main()
