from __future__ import annotations
import argparse, json
from pathlib import Path
import numpy as np
import pandas as pd
import yfinance as yf
import audit_inverse_etf_regime_scan as base
import audit_inverse_event_engine_v2 as v2

SYMS=['TQQQ','PSQ','QID','SQQQ']

def cooldown_events(cond,cooldown=10):
    raw=base.event_mask(cond).fillna(False).to_numpy(bool); out=np.zeros(len(raw),dtype=bool); last=-10**9
    for i,x in enumerate(raw):
        if x and i-last>cooldown: out[i]=True; last=i
    return pd.Series(out,index=cond.index)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--features',required=True); ap.add_argument('--output',required=True); a=ap.parse_args()
    out=Path(a.output); out.mkdir(parents=True,exist_ok=True)
    feat=pd.read_csv(a.features,parse_dates=['date']).set_index('date').sort_index(); feat.index=base.norm_idx(feat.index)
    hyp,_=v2.build_hypotheses(feat); ev=cooldown_events(hyp['TREND_NQSAR'],10)
    # actual V38 panic episodes: do not open inverse sleeve if panic engine is already active
    ev=ev & ~(feat.panic_episode.fillna(0)>0)
    raw=yf.download(SYMS,start='2015-11-01',end='2026-05-01',auto_adjust=True,actions=False,progress=False,threads=False,group_by='column')
    op=raw['Open'].copy(); op.index=base.norm_idx(op.index); op=op.reindex(feat.index).ffill(limit=2)
    rows=[]
    for i in np.flatnonzero(ev.to_numpy(bool)):
        if i+3>=len(feat): continue
        d=feat.index[i]; r={s:float(op[s].iloc[i+3]/op[s].iloc[i+1]-1) for s in SYMS}
        # Portfolio returns over event window. 5bp per side friction on event-induced trades.
        plans={
          'CURRENT_TQQQ30':0.30*r['TQQQ'],
          'CASH_TQQQ0':-0.30*0.001,
          'TRIM_TQQQ15':0.15*r['TQQQ']-0.15*0.001,
          'KEEP_TQQQ30_PLUS_QID15':0.30*r['TQQQ']+0.15*r['QID']-0.15*0.001,
          'REPLACE_QID15':0.15*r['QID']-(0.30+0.15)*0.001,
          'REPLACE_QID30':0.30*r['QID']-(0.30+0.30)*0.001,
          'REPLACE_PSQ30':0.30*r['PSQ']-(0.30+0.30)*0.001,
          'REPLACE_SQQQ15':0.15*r['SQQQ']-(0.30+0.15)*0.001,
        }
        row={'date':d,'year':d.year,'nqsar':feat.nq_color.iloc[i],'breadth50':feat.breadth50.iloc[i],**{f'{s}_2d':r[s] for s in SYMS},**plans}
        rows.append(row)
    led=pd.DataFrame(rows); led.to_csv(out/'integration_event_ledger.csv',index=False)
    periods={'TRAIN_2016_2021':('2016-01-04','2021-12-31'),'HOLDOUT_2022_2026':('2022-01-03','2026-03-20'),'2016_2019':('2016-01-04','2019-12-31'),'2020_2021':('2020-01-01','2021-12-31'),'2022_2023':('2022-01-03','2023-12-29'),'2024_2026':('2024-01-02','2026-03-20')}
    plan_names=list(plans.keys()); summ=[]
    for plan in plan_names:
      row={'plan':plan}
      for p,(aa,bb) in periods.items():
        x=led.loc[(led.date>=aa)&(led.date<=bb),plan].dropna()
        row[f'{p}_n']=len(x); row[f'{p}_mean']=float(x.mean()) if len(x) else None; row[f'{p}_median']=float(x.median()) if len(x) else None; row[f'{p}_win']=float((x>0).mean()) if len(x) else None
        if len(x):
          yrs=(pd.Timestamp(bb)-pd.Timestamp(aa)).days/365.25; row[f'{p}_event_cagr']=float(np.prod(1+x.to_numpy())**(1/yrs)-1)
      summ.append(row)
    sdf=pd.DataFrame(summ); sdf.to_csv(out/'integration_summary.csv',index=False)
    payload={'status':'RESEARCH_ONLY_NO_PRODUCTION_CHANGE','signal':'TREND_NQSAR onset, 10-session cooldown, skip active actual panic_episode','hold_sessions':2,'cost':'5bp/side; event-induced TQQQ roundtrip included in cash/replacement plans','events':len(led),'summary':summ}
    (out/'summary.json').write_text(json.dumps(base.safe(payload),ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(base.safe(payload),ensure_ascii=False))
if __name__=='__main__':main()
