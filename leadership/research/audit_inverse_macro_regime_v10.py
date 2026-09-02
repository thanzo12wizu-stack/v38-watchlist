from __future__ import annotations
import argparse, json
from pathlib import Path
import numpy as np, pandas as pd
import audit_inverse_full_v38_v4 as v4

LEVELS=[.50,.75,1.00,1.25,1.50]
SLOPES=[.50,.75,1.00,1.25,1.50]
COSTS=[5,40,80]
PERIODS={
 'OLD_2011_2015':('2011-01-03','2015-12-31'),
 'DISCOVERY_2011_2021':('2011-01-03','2021-12-31'),
 'POST_2016_2021':('2016-01-01','2021-12-31'),
 'HOLDOUT_2022_FREEZE':('2022-01-01','2026-03-20'),
 'POST_2024_FREEZE':('2024-01-01','2026-03-20'),
 'TRUE_OOS_20260323_PLUS':('2026-03-23','2099-12-31'),
}

def norm(x):
 z=pd.DatetimeIndex(pd.to_datetime(x));
 if z.tz is not None:z=z.tz_convert('America/New_York').tz_localize(None)
 return z.normalize()

def metrics_event(z):
 a=pd.to_numeric(z.qid2,errors='coerce').dropna()
 return {'n':len(a),'mean':float(a.mean()) if len(a) else np.nan,'median':float(a.median()) if len(a) else np.nan,'win':float((a>0).mean()) if len(a) else np.nan,'cum_qid30':float(np.prod(1+.30*a)-1) if len(a) else 0.}

def corrected_variant(d,inv,active,cost):
 t,iw=v4.overlay_positions(d,active,'QID_CASH30'); ret=d.o_contrib.to_numpy(float)+d.r_contrib.to_numpy(float)+t*d.tqqq_ret.to_numpy(float)
 tt=np.zeros(len(d));tt[1:]=np.abs(np.diff(t));ret-=tt*5/10000
 w=iw['QID']; rp=pd.to_numeric(inv.QID,errors='coerce').fillna(0).to_numpy(float);ret+=w*rp;tr=np.zeros(len(d));tr[1:]=np.abs(np.diff(w));ret-=tr*cost/10000
 return pd.Series(ret,index=d.index)
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--events',required=True);ap.add_argument('--v2-features',required=True);ap.add_argument('--gross100',required=True);ap.add_argument('--tqqq',required=True);ap.add_argument('--output',required=True)
 a=ap.parse_args();out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
 ev=pd.read_csv(a.events,parse_dates=['signal_date']).sort_values('signal_date').reset_index(drop=True)
 # Macro-ON means NOT in the low-short-rate + steep-curve environment. Rates were shifted one session in V9.
 grid=[]
 for lv in LEVELS:
  for sl in SLOPES:
   g=~((pd.to_numeric(ev.DGS2,errors='coerce')<lv)&(pd.to_numeric(ev.curve_2s10s,errors='coerce')>sl))
   name=f'L{lv:.2f}_S{sl:.2f}'
   for p,(aa,bb) in PERIODS.items():
    m=(ev.signal_date>=aa)&(ev.signal_date<=bb)&g;grid.append({'rule':name,'dgs2_floor':lv,'curve_ceiling':sl,'period':p,**metrics_event(ev[m])})
 pd.DataFrame(grid).to_csv(out/'macro_threshold_plateau.csv',index=False)
 primary=~((pd.to_numeric(ev.DGS2,errors='coerce')<1.0)&(pd.to_numeric(ev.curve_2s10s,errors='coerce')>1.0));ev['G_MACRO_L1_S1']=primary
 for c in ['G_LAST3_MEAN','G_LAST5_MEAN','G_EWMA_HL3','G_TRAIL3Y_MEAN']:
  ev['G_MACRO_AND_'+c]=primary&ev[c].fillna(False).astype(bool)
 ev.to_csv(out/'macro_event_ledger.csv',index=False)
 # Fixed primary and nearby rules by event sequence; no best threshold is selected.
 summary=[]
 gates=['G_MACRO_L1_S1','G_MACRO_AND_G_LAST3_MEAN','G_MACRO_AND_G_LAST5_MEAN','G_MACRO_AND_G_EWMA_HL3','G_MACRO_AND_G_TRAIL3Y_MEAN']
 for g in gates:
  for p,(aa,bb) in PERIODS.items():summary.append({'gate':g,'period':p,**metrics_event(ev[(ev.signal_date>=aa)&(ev.signal_date<=bb)&ev[g]])})
 pd.DataFrame(summary).to_csv(out/'macro_gate_summary.csv',index=False)
 # Audited Gross100 integration through the frozen endpoint.
 feat=pd.read_csv(a.v2_features,compression='gzip',parse_dates=['date']).sort_values('date')
 ordinary=pd.read_csv(Path(a.gross100)/'gross100_final_reset_components/ordinary_PEAK30_PART25_R3_daily.csv.gz',compression='gzip',parse_dates=['date']).rename(columns={'gross_exposure':'gross_exposure_ord','return':'return_ord'})
 reset=pd.read_csv(Path(a.gross100)/'gross100_final_reset_components/rsi_RESET_RISE30_S029_P4_H20_daily.csv.gz',compression='gzip',parse_dates=['date']).rename(columns={'gross_exposure':'gross_exposure_rsi','return':'return_rsi'})
 tq=pd.read_csv(a.tqqq,compression='gzip',parse_dates=['date']);d=v4.baseline_components(ordinary,reset,tq,feat);d['date']=norm(d.date);bm=v4.metrics(d.baseline_ret)
 if abs(bm['cagr']-.470025795426962)>5e-6:raise RuntimeError('baseline mismatch')
 sig=v4.signal_defs(d)['CORE_MC'];guard=v4.guards(d)['PANIC_OR_STAGE56'];baseev=v4.cooldown_events(sig,10)&~guard;inv=v4.price_returns(norm(d.date),str(d.date.min().date()),str(d.date.max().date()));inv.index=d.index
 periods2={'TRAIN_2016_2021':('2016-01-04','2021-12-31'),'HOLDOUT_2022_2026':('2022-01-03','2026-03-20'),'2016_2019':('2016-01-04','2019-12-31'),'2020_2021':('2020-01-01','2021-12-31'),'2022_2023':('2022-01-03','2023-12-29'),'2024_2026':('2024-01-02','2026-03-20')}
 prows=[]
 mp=ev.set_index(ev.signal_date.dt.normalize())
 specs={'UNGATED':pd.Series(True,index=ev.index),'MACRO_L1_S1':ev.G_MACRO_L1_S1,'MACRO_LAST3':ev.G_MACRO_AND_G_LAST3_MEAN,'MACRO_LAST5':ev.G_MACRO_AND_G_LAST5_MEAN,'MACRO_EWMA':ev.G_MACRO_AND_G_EWMA_HL3}
 # Also test all 25 nearby macro rules in Gross100 at standard 5bp to demonstrate a plateau rather than a magic point.
 for lv in LEVELS:
  for sl in SLOPES: specs[f'GRID_L{lv:.2f}_S{sl:.2f}']=~((ev.DGS2<lv)&(ev.curve_2s10s>sl))
 for nm,flag in specs.items():
  allowmap=pd.Series(flag.to_numpy(bool),index=ev.signal_date.dt.normalize());allow=d.date.map(allowmap).fillna(False).to_numpy(bool);sel=baseev&pd.Series(allow,index=baseev.index)
  for cost in (COSTS if not nm.startswith('GRID_') else [5]):
   act,_=v4.build_active(sel,2,guard);r=corrected_variant(d,inv,act,cost);mm=v4.metrics(r);row={'gate':nm,'cost_bp':cost,'events':int(sel.sum()),'cagr':mm['cagr'],'mdd':mm['mdd'],'delta_cagr':mm['cagr']-bm['cagr'],'delta_mdd':mm['mdd']-bm['mdd']}
   for p,(aa,bb) in periods2.items():
    m=(d.date>=aa)&(d.date<=bb);x=v4.metrics(r.loc[m]);b=v4.metrics(d.baseline_ret.loc[m]);row[p+'_delta_cagr']=x['cagr']-b['cagr'];row[p+'_delta_mdd']=x['mdd']-b['mdd']
   prows.append(row)
 pd.DataFrame(prows).to_csv(out/'macro_gross100.csv',index=False)
 # Current status is explicit and mechanical.
 latest=ev.iloc[-1];cur={'last_event':str(latest.signal_date.date()),'last_event_qid2':float(latest.qid2),'macro_L1_S1_at_last_event':bool(latest.G_MACRO_L1_S1),'adaptive_last3_after_last_event':bool(ev.G_LAST3_MEAN.iloc[-1])}
 # For today, use latest market/macro row from V9 summary's event-independent state is not available here; macro state at last event is reported, while V9 reports Sep-2 rates.
 gdf=pd.DataFrame(grid);plateau=gdf[gdf.period.isin(['DISCOVERY_2011_2021','HOLDOUT_2022_FREEZE'])].pivot(index='rule',columns='period',values='mean').dropna();plateau_pass=int(((plateau.DISCOVERY_2011_2021>0)&(plateau.HOLDOUT_2022_FREEZE>0)).sum())
 res={'status':'RESEARCH_ONLY_NO_PRODUCTION_CHANGE','primary_rule':'QID macro-compatible unless (lagged DGS2 < 1.00% AND lagged 2s10s > 1.00%)','plateau_cells':25,'plateau_positive_discovery_and_holdout':plateau_pass,'current_after_latest_event':cur,'notes':['Threshold grid is robustness only; no best cell is selected.','The primary 1%/1% boundary is an interpretable low-rate/steep-curve regime marker, but it was motivated after seeing the V9 era diagnostic and therefore is not pristine OOS.','The single post-2026-03-20 true-OOS event remains a required counterexample and is not removed by the macro gate.','No production change.']}
 (out/'summary_v10.json').write_text(json.dumps(res,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(res,ensure_ascii=False,indent=2),flush=True)
if __name__=='__main__':main()
