"""Exact source trade event instrumentation on the frozen input artifact."""
from pathlib import Path
import pickle,gzip,inspect,sys,json
import pandas as pd
import numpy as np
sys.path[:0]=['research_source','research_source/leadership/research']
import audit_gross100_early_slot_overlay as early
BASE=Path('frozen/audit');OUT=Path('trade_output');OUT.mkdir(exist_ok=True)
with gzip.open(BASE/'frozen_research_inputs.pkl.gz','rb') as f:meta,m,peer,ctx,ca,cs,ec=pickle.load(f)
EVENTS=[];src=inspect.getsource(early.simulate_early_overlay)
patches={
 '        cash += p["shares"] * price':'        EVENTS.append(dict(kind="EXIT", date=d, symbol=sym, price=price, shares=p["shares"], entry_date=p["entry_date"], entry_sleeve=p["entry_sleeve"], reason=reason))\n        cash += p["shares"] * price',
 '                            cash += sold * opx':'                            EVENTS.append(dict(kind="PARTIAL",date=d,symbol=sym,price=opx,shares=sold,entry_date=p["entry_date"],entry_sleeve=p["entry_sleeve"]))\n                            cash += sold * opx',
 '                        core_entries += 1':'                        EVENTS.append(dict(kind="ENTRY",date=d,symbol=sym,price=opx,**pos[sym]))\n                        core_entries += 1',
 '                            early_entries += 1':'                            EVENTS.append(dict(kind="ENTRY",date=d,symbol=sym,price=opx,**pos[sym]))\n                            early_entries += 1',
 '                            promoted_core += 1':'                            EVENTS.append(dict(kind="PROMOTE",date=d,symbol=sym,price=_px(opens,d,sym,None),shares=pos[sym]["shares"],entry_date=pos[sym]["entry_date"],entry_sleeve=pos[sym]["entry_sleeve"]))\n                            promoted_core += 1'
}
for needle,replacement in patches.items():
 assert src.count(needle)==1,needle
 src=src.replace(needle,replacement)
ns=dict(early.__dict__);ns['EVENTS']=EVENTS;exec(src,ns)
ordinary,diag=ns['simulate_early_overlay'](1,meta,m,ca,cs,ec)
prior=pd.read_csv(BASE/'ordinary_EARLY1.csv.gz');error=float(np.max(np.abs(ordinary.nav.to_numpy()-prior.nav.to_numpy())));assert error<1e-10
ev=pd.DataFrame(EVENTS);ev.to_csv(OUT/'early1_trade_events.csv.gz',index=False,compression='gzip')
rows=[]
for (symbol,entry_date),g in ev.groupby(['symbol','entry_date']):
 en=g[g.kind=='ENTRY'];ex=g[g.kind=='EXIT']
 if len(en)!=1:continue
 e=en.iloc[0];initial=float(e.shares*e.price);sales=g[g.kind.isin(['PARTIAL','EXIT'])];proceeds=float((sales.shares*sales.price).sum());closed=len(ex)>0
 if not closed:continue
 assert abs(float(sales.shares.sum())-float(e.shares))<1e-8
 exit_date=pd.Timestamp(ex.iloc[-1].date);entry_date=pd.Timestamp(entry_date);enidx=m['close'].index.get_loc(entry_date);prior_close=m['close'].iloc[enidx-1][symbol];entry_gap=float(e.price/prior_close-1)
 exidx=m['close'].index.get_loc(exit_date);exit_gap=float(ex.iloc[-1].price/m['close'].iloc[exidx-1][symbol]-1)
 rows.append(dict(symbol=symbol,entry_date=entry_date,exit_date=exit_date,entry_sleeve=e.entry_sleeve,promoted=bool((g.kind=='PROMOTE').any()),entry_price=e.price,exit_price=ex.iloc[-1].price,entry_value=initial,pnl=proceeds-initial,return_gross=proceeds/initial-1,return_5bp=(proceeds-initial-(initial+proceeds)*.0005)/initial,exit_reason=ex.iloc[-1].reason,entry_gap=entry_gap,exit_gap=exit_gap))
tr=pd.DataFrame(rows);tr.to_csv(OUT/'early1_closed_trades.csv.gz',index=False,compression='gzip')
def stats(z):
 r=z.return_5bp.to_numpy();pos=r[r>0].sum();neg=-r[r<0].sum()
 return dict(n=len(z),symbols=z.symbol.nunique(),mean=float(r.mean()),win=float((r>0).mean()),pf=float(pos/neg) if neg else None,median=float(np.median(r)),worst=float(r.min()),best=float(r.max()))
summary=[];clusters=[];rng=np.random.default_rng(20260905)
for sleeve in ['ALL','CORE','EARLY','EARLY_NOT_PROMOTED','EARLY_PROMOTED']:
 z=tr if sleeve=='ALL' else tr[tr.entry_sleeve==sleeve]
 if sleeve=='EARLY_NOT_PROMOTED':z=tr[(tr.entry_sleeve=='EARLY')&~tr.promoted]
 if sleeve=='EARLY_PROMOTED':z=tr[(tr.entry_sleeve=='EARLY')&tr.promoted]
 for p,a,b in [('FULL','2016-01-01','2026-03-20'),('2016_2020','2016-01-01','2020-12-31'),('2021_2025','2021-01-01','2025-12-31'),('2022_2026','2022-01-01','2026-03-20')]:
  zz=z[(z.entry_date>=a)&(z.entry_date<=b)]
  if len(zz):summary.append(dict(cohort=sleeve,period=p,**stats(zz)))
 if sleeve in ['CORE','EARLY']:
  gs=[v.return_5bp.to_numpy() for _,v in z.groupby('symbol')];means=[];pfs=[]
  for _ in range(5000):
   r=np.concatenate([gs[j] for j in rng.integers(0,len(gs),len(gs))]);means.append(r.mean());neg=-r[r<0].sum();pfs.append(r[r>0].sum()/neg if neg else np.nan)
  clusters.append(dict(cohort=sleeve,symbols=len(gs),mean_p05=float(np.quantile(means,.05)),mean_p95=float(np.quantile(means,.95)),pf_p05=float(np.nanquantile(pfs,.05)),pf_p95=float(np.nanquantile(pfs,.95)),p_mean_gt0=float(np.mean(np.array(means)>0))))
pd.DataFrame(summary).to_csv(OUT/'trade_cohort_summary.csv',index=False)
(OUT/'symbol_cluster.json').write_text(json.dumps(clusters,indent=2))
(OUT/'method.json').write_text(json.dumps(dict(diag=diag,nav_reproduction_max_error=error,limits=['Virtual ordinary sleeve trade cohorts, not funded Gross100 ledger PF.','Early-origin cohort retains promoted winners through Core exit; not the same as Early-residency contribution.','Open trades excluded from closed-trade statistics.','Symbol cluster is trade expectancy/PF inference, not portfolio CAGR bootstrap.','5bp is applied to each buy/sell notional; no future information changes entries.']),indent=2))
print('TRADE_DONE',json.dumps(summary),flush=True)
