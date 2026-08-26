from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
from research import tqqq_backtest_once as bt

GRID = Path('prev/tqqq_stage1_grid.csv')
if not GRID.exists():
    raise SystemExit('missing previous stage1 grid')
d1 = pd.read_csv(GRID)

# Candidate union is selected only from 2011-2018 IS statistics.
# Preserve signal-family diversity so an IS-specific winner does not crowd out
# a different family before untouched 2019+ OOS evaluation.
is_candidates=[]
for metric_name in ('ema21_atr','sma50_atr','vwap63_atr','vwap252_atr'):
    dm=d1[d1['metric']==metric_name]
    is_candidates += list(dm.sort_values(['is_calmar','is_cagr'],ascending=False).head(12).index)
    is_candidates += list(dm.sort_values(['is_cagr','is_calmar'],ascending=False).head(12).index)
    for lim in (0.40,0.50,0.60,0.70):
        is_candidates += list(dm[dm['is_mdd'] >= -lim].sort_values(['is_cagr','is_calmar'],ascending=False).head(8).index)
is_candidates=sorted(set(is_candidates))
print('[stage2] metric-diverse IS-selected base configs',len(is_candidates),flush=True)
print('[stage2] family counts',d1.loc[is_candidates,'metric'].value_counts().to_dict(),flush=True)

qqq=bt.dl_one('QQQ','2009-01-01')
tqqq=bt.dl_one('TQQQ','2010-01-01')
vix=bt.dl_one('^VIX','1990-01-01')
mc,mc_cov=bt.compute_mc()
vstate,vsignals=bt.vix_state_series(vix)
ind=bt.indicators(qqq)
common=ind.index.intersection(tqqq.index)
ind=ind.reindex(common); tqqq=tqqq.reindex(common)
mc=mc.reindex(common).ffill(); mc_cov=mc_cov.reindex(common).ffill(); vstate=vstate.reindex(common).ffill()
mask=common>=bt.START
ind=ind.loc[mask]; tqqq=tqqq.loc[mask]; mc=mc.loc[mask]; mc_cov=mc_cov.loc[mask]; vstate=vstate.loc[mask]

mc_gates=[None,35.0,45.0,55.0]
vix_modes=['none','phase1','phase2','bottom_only']
rows=[]
for ix in is_candidates:
    base=d1.loc[ix]
    metric=ind[str(base['metric'])]
    entries=tuple(float(x) for x in str(base['entries']).split('/'))
    ex=float(base['exit']); tactical=bt.ALLOC_SHAPES[str(base['shape'])]
    for mg in mc_gates:
        for vm in vix_modes:
            target=bt.build_target(metric,entries,ex,tactical,mc=mc,mc_gate=mg,vix_state=vstate,vix_mode=vm)
            ret=bt.strategy_returns(target,tqqq['Open'])
            row={'base_ix':int(ix),'metric':str(base['metric']),'entries':str(base['entries']),
                 'exit':ex,'shape':str(base['shape']),'mc_gate':mg,'vix_mode':vm,
                 'avg_exposure':float(target.mean()),'turnover':float(target.diff().abs().sum())}
            rows.append(bt.add_stats(row,ret))
d2=pd.DataFrame(rows)
d2.to_csv('tqqq_stage2_regime.csv',index=False)

# Exact matched baseline per technical config.
base_map={}
for _,r in d2[(d2['mc_gate'].isna()) & (d2['vix_mode']=='none')].iterrows():
    base_map[int(r['base_ix'])]=r
for p in ('full','is','oos'):
    d2[f'{p}_calmar_delta']=d2.apply(lambda r: r[f'{p}_calmar']-base_map[int(r['base_ix'])][f'{p}_calmar'],axis=1)
    d2[f'{p}_cagr_delta']=d2.apply(lambda r: r[f'{p}_cagr']-base_map[int(r['base_ix'])][f'{p}_cagr'],axis=1)
    d2[f'{p}_mdd_delta']=d2.apply(lambda r: r[f'{p}_mdd']-base_map[int(r['base_ix'])][f'{p}_mdd'],axis=1)
d2.to_csv('tqqq_stage2_regime.csv',index=False)

print('\n=== STAGE2 IS TOP (OOS untouched) ===')
top_is=d2.sort_values(['is_calmar','is_cagr'],ascending=False).head(20)
for _,r in top_is.iterrows():
    mg='none' if pd.isna(r['mc_gate']) else f">={int(r['mc_gate'])}"
    print(f"{r['metric']:12s} {r['entries']:20s} exit=+{r['exit']:<3} {r['shape']:6s} MC={mg:5s} VIX={r['vix_mode']:11s} | IS CAGR={r['is_cagr']*100:6.2f}% MDD={r['is_mdd']*100:7.2f}% C={r['is_calmar']:.3f} | OOS CAGR={r['oos_cagr']*100:6.2f}% MDD={r['oos_mdd']*100:7.2f}% C={r['oos_calmar']:.3f} | FULL CAGR={r['full_cagr']*100:6.2f}% MDD={r['full_mdd']*100:7.2f}% C={r['full_calmar']:.3f}")

print('\n=== FULL MAX CAGR BY MDD LIMIT ===')
for lim in (.40,.45,.50,.55,.60,.65,.70):
    q=d2[d2['full_mdd']>=-lim].sort_values(['full_cagr','full_calmar'],ascending=False).head(1)
    if len(q):
        r=q.iloc[0]; mg='none' if pd.isna(r['mc_gate']) else f">={int(r['mc_gate'])}"
        print(f"MDD<={lim*100:.0f}% {r['metric']} {r['entries']} exit=+{r['exit']} {r['shape']} MC={mg} VIX={r['vix_mode']} CAGR={r['full_cagr']*100:.2f}% MDD={r['full_mdd']*100:.2f}% Calmar={r['full_calmar']:.3f} avgExp={r['avg_exposure']*100:.1f}%")

print('\n=== BEST FULL CALMAR ===')
for _,r in d2.sort_values(['full_calmar','full_cagr'],ascending=False).head(15).iterrows():
    mg='none' if pd.isna(r['mc_gate']) else f">={int(r['mc_gate'])}"
    print(f"{r['metric']:12s} {r['entries']:20s} exit=+{r['exit']:<3} {r['shape']:6s} MC={mg:5s} VIX={r['vix_mode']:11s} CAGR={r['full_cagr']*100:6.2f}% MDD={r['full_mdd']*100:7.2f}% C={r['full_calmar']:.3f} OOS_C={r['oos_calmar']:.3f}")

print('\n=== MODIFIER DIAGNOSTICS VS SAME TECH BASE ===')
for mg in mc_gates:
    for vm in vix_modes:
        x=d2[((d2['mc_gate'].isna()) if mg is None else (d2['mc_gate']==mg)) & (d2['vix_mode']==vm)]
        if not len(x): continue
        tag=f"MC={'none' if mg is None else int(mg)} VIX={vm}"
        print(tag,
              f"FULL dC={x['full_calmar_delta'].median():+.3f} winC={(x['full_calmar_delta']>0).mean()*100:.0f}% dCAGR={x['full_cagr_delta'].median()*100:+.2f}pt dMDD={x['full_mdd_delta'].median()*100:+.2f}pt |",
              f"OOS dC={x['oos_calmar_delta'].median():+.3f} winC={(x['oos_calmar_delta']>0).mean()*100:.0f}% dCAGR={x['oos_cagr_delta'].median()*100:+.2f}pt dMDD={x['oos_mdd_delta'].median()*100:+.2f}pt")

d2['min_io_calmar']=d2[['is_calmar','oos_calmar']].min(axis=1)
rob=d2.sort_values(['min_io_calmar','full_calmar'],ascending=False).head(20)
print('\n=== ROBUSTNESS DIAGNOSTIC min(IS,OOS Calmar) ===')
for _,r in rob.iterrows():
    mg='none' if pd.isna(r['mc_gate']) else f">={int(r['mc_gate'])}"
    print(f"{r['metric']:12s} {r['entries']:20s} exit=+{r['exit']:<3} {r['shape']:6s} MC={mg:5s} VIX={r['vix_mode']:11s} minIO={r['min_io_calmar']:.3f} IS={r['is_calmar']:.3f} OOS={r['oos_calmar']:.3f} FULL={r['full_calmar']:.3f}")

best=rob.iloc[0]
mg=None if pd.isna(best['mc_gate']) else float(best['mc_gate'])
target=bt.build_target(ind[str(best['metric'])],tuple(float(x) for x in str(best['entries']).split('/')),float(best['exit']),bt.ALLOC_SHAPES[str(best['shape'])],mc=mc,mc_gate=mg,vix_state=vstate,vix_mode=str(best['vix_mode']))
audit=pd.DataFrame({'QQQ':ind['qqq_close'],'metric':ind[str(best['metric'])],'MC':mc,'MC_coverage':mc_cov,'VIX_state':vstate,'TQQQ_target':target})
audit.to_csv('tqqq_best_position_audit.csv')
sig=[s for s in vsignals if s['date']>=bt.START.strftime('%Y-%m-%d')]
pd.DataFrame(sig).to_csv('tqqq_vix_signals.csv',index=False)

summary={'start':str(ind.index[0].date()),'end':str(ind.index[-1].date()),'sessions':len(ind),'n_stage2':len(d2),
         'family_counts':d1.loc[is_candidates,'metric'].value_counts().to_dict(),
         'vix_counts':pd.Series([s['type'] for s in sig]).value_counts().to_dict() if sig else {},
         'mc_coverage_start':float(mc_cov.iloc[0]),'mc_coverage_median':float(mc_cov.median()),'mc_coverage_latest':float(mc_cov.iloc[-1]),
         'best_robust':{k:(None if pd.isna(v) else v) for k,v in best.to_dict().items()},
         'nqsar_note':'Exact long-history NQ-SAR series is not available in the repo; current trend_history begins 2026-06-25. It is not fabricated in this backtest.'}
Path('tqqq_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
print('\n=== SUMMARY ===')
print(json.dumps(summary,ensure_ascii=False,indent=2,default=str))
