from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
from research import tqqq_backtest_once as bt

GRID=Path('prev/tqqq_stage1_grid.csv')
d1=pd.read_csv(GRID)

# IS-only, metric-diverse candidate selection. OOS is never used to choose parameters.
sel=[]
for metric in ['ema21_atr','sma50_atr','vwap63_atr','vwap252_atr']:
    dm=d1[d1['metric']==metric]
    sel += list(dm.sort_values(['is_calmar','is_cagr'],ascending=False).head(15).index)
    sel += list(dm.sort_values(['is_cagr','is_calmar'],ascending=False).head(15).index)
    for lim in (.40,.50,.60,.70):
        sel += list(dm[dm['is_mdd']>=-lim].sort_values(['is_cagr','is_calmar'],ascending=False).head(10).index)
sel=sorted(set(sel))
print('[stage3] IS-only metric-diverse bases',len(sel),flush=True)

qqq=bt.dl_one('QQQ','2009-01-01'); tqqq=bt.dl_one('TQQQ','2010-01-01'); vix=bt.dl_one('^VIX','1990-01-01')
mc,mc_cov=bt.compute_mc(); vstate,vsignals=bt.vix_state_series(vix); ind=bt.indicators(qqq)
common=ind.index.intersection(tqqq.index)
ind=ind.reindex(common); tqqq=tqqq.reindex(common); mc=mc.reindex(common).ffill(); mc_cov=mc_cov.reindex(common).ffill(); vstate=vstate.reindex(common).ffill()
mask=common>=bt.START
ind=ind.loc[mask]; tqqq=tqqq.loc[mask]; mc=mc.loc[mask]; mc_cov=mc_cov.loc[mask]; vstate=vstate.loc[mask]

OVERRIDE_STATES={
    'none':set(),
    'release_all':{'EXTREME','ROLLOVER','BOTTOM','RE-EXTREME'},
    'release_roll':{'ROLLOVER','BOTTOM','RE-EXTREME'},
    'release_bottom':{'BOTTOM','RE-EXTREME'},
}

def smart_target(metric,entries,exit_level,tactical,mc_gate,mode):
    idx=metric.index; mc2=mc.reindex(idx).ffill(); vs=vstate.reindex(idx).ffill()
    held=0; out=[]; release_states=OVERRIDE_STATES[mode]
    for d,x in metric.items():
        if pd.isna(x):
            out.append(bt.CORE+(tactical[held-1] if held else 0.0)); continue
        x=float(x)
        if held>0 and x>=exit_level: held=0
        desired=bt.tier_from_value(x,entries)
        if desired>held:
            allow=True
            if mc_gate is not None:
                mv=mc2.loc[d]
                allow=pd.notna(mv) and float(mv)>=float(mc_gate)
                state=str(vs.loc[d]) if pd.notna(vs.loc[d]) else 'NORMAL'
                if state in release_states: allow=True
            if allow: held=desired
        out.append(bt.CORE+(tactical[held-1] if held else 0.0))
    return pd.Series(out,index=idx,dtype=float).clip(bt.CORE,1.0)

rows=[]
for ix in sel:
    b=d1.loc[ix]; metric=ind[str(b['metric'])]; entries=tuple(float(x) for x in str(b['entries']).split('/')); ex=float(b['exit']); tactical=bt.ALLOC_SHAPES[str(b['shape'])]
    for gate in [None,35.0,45.0,55.0]:
        for mode in OVERRIDE_STATES:
            target=smart_target(metric,entries,ex,tactical,gate,mode)
            ret=bt.strategy_returns(target,tqqq['Open'])
            row={'base_ix':int(ix),'metric':str(b['metric']),'entries':str(b['entries']),'exit':ex,'shape':str(b['shape']),
                 'mc_gate':gate,'panic_mode':mode,'avg_exposure':float(target.mean()),'turnover':float(target.diff().abs().sum())}
            rows.append(bt.add_stats(row,ret))
d=pd.DataFrame(rows)
d.to_csv('tqqq_stage3_smart_vix.csv',index=False)

# Matched modifier diagnostics against same technical base with same MC gate and no panic release.
keys=['base_ix','mc_gate']
base=d[d['panic_mode']=='none'].set_index(keys)
for p in ['full','is','oos']:
    d[f'{p}_panic_cagr_delta']=d.apply(lambda r:r[f'{p}_cagr']-base.loc[(int(r['base_ix']),r['mc_gate'])][f'{p}_cagr'] if pd.notna(r['mc_gate']) else r[f'{p}_cagr']-d[(d.base_ix==r.base_ix)&d.mc_gate.isna()&(d.panic_mode=='none')].iloc[0][f'{p}_cagr'],axis=1)
    d[f'{p}_panic_mdd_delta']=d.apply(lambda r:r[f'{p}_mdd']-base.loc[(int(r['base_ix']),r['mc_gate'])][f'{p}_mdd'] if pd.notna(r['mc_gate']) else r[f'{p}_mdd']-d[(d.base_ix==r.base_ix)&d.mc_gate.isna()&(d.panic_mode=='none')].iloc[0][f'{p}_mdd'],axis=1)
    d[f'{p}_panic_calmar_delta']=d.apply(lambda r:r[f'{p}_calmar']-base.loc[(int(r['base_ix']),r['mc_gate'])][f'{p}_calmar'] if pd.notna(r['mc_gate']) else r[f'{p}_calmar']-d[(d.base_ix==r.base_ix)&d.mc_gate.isna()&(d.panic_mode=='none')].iloc[0][f'{p}_calmar'],axis=1)
d.to_csv('tqqq_stage3_smart_vix.csv',index=False)

print('\n=== MAX CAGR BY FULL MDD LIMIT ===')
for lim in (.35,.40,.45,.50,.55,.60):
    q=d[d.full_mdd>=-lim].sort_values(['full_cagr','full_calmar'],ascending=False).head(1)
    if len(q):
        r=q.iloc[0]; gate='none' if pd.isna(r.mc_gate) else str(int(r.mc_gate))
        print(f"MDD<={lim*100:.0f}% {r.metric} {r.entries} exit=+{r['exit']} {r['shape']} MC={gate} panic={r.panic_mode} CAGR={r.full_cagr*100:.2f}% MDD={r.full_mdd*100:.2f}% C={r.full_calmar:.3f} IS_C={r.is_calmar:.3f} OOS_C={r.oos_calmar:.3f} avgExp={r.avg_exposure*100:.1f}%")

print('\n=== BEST FULL CALMAR ===')
for _,r in d.sort_values(['full_calmar','full_cagr'],ascending=False).head(20).iterrows():
    gate='none' if pd.isna(r.mc_gate) else str(int(r.mc_gate))
    print(f"{r.metric:12s} {r.entries:20s} exit=+{r['exit']:<3} {r['shape']:6s} MC={gate:4s} panic={r.panic_mode:14s} FULL {r.full_cagr*100:6.2f}%/{r.full_mdd*100:7.2f}% C={r.full_calmar:.3f} IS_C={r.is_calmar:.3f} OOS_C={r.oos_calmar:.3f}")

print('\n=== PANIC RELEASE DIAGNOSTICS, MATCHED SAME BASE+MC ===')
for gate in [35.0,45.0,55.0]:
    for mode in ['release_all','release_roll','release_bottom']:
        x=d[(d.mc_gate==gate)&(d.panic_mode==mode)]
        print(f"MC={int(gate)} {mode:14s} FULL dCAGR={x.full_panic_cagr_delta.median()*100:+.2f}pt dMDD={x.full_panic_mdd_delta.median()*100:+.2f}pt dCalmar={x.full_panic_calmar_delta.median():+.3f} winC={(x.full_panic_calmar_delta>0).mean()*100:.0f}% | OOS dCAGR={x.oos_panic_cagr_delta.median()*100:+.2f}pt dMDD={x.oos_panic_mdd_delta.median()*100:+.2f}pt dCalmar={x.oos_panic_calmar_delta.median():+.3f} winC={(x.oos_panic_calmar_delta>0).mean()*100:.0f}%")

# Robustness diagnostic only, not clean OOS selection.
d['min_io_calmar']=d[['is_calmar','oos_calmar']].min(axis=1)
print('\n=== ROBUSTNESS min(IS,OOS Calmar), DIAGNOSTIC ===')
for _,r in d.sort_values(['min_io_calmar','full_calmar'],ascending=False).head(20).iterrows():
    gate='none' if pd.isna(r.mc_gate) else str(int(r.mc_gate))
    print(f"{r.metric:12s} {r.entries:20s} exit=+{r['exit']:<3} {r['shape']:6s} MC={gate:4s} panic={r.panic_mode:14s} minIO={r.min_io_calmar:.3f} FULL={r.full_calmar:.3f} IS={r.is_calmar:.3f} OOS={r.oos_calmar:.3f} CAGR={r.full_cagr*100:.2f}% MDD={r.full_mdd*100:.2f}%")

summary={'bases':len(sel),'configs':len(d),'mc_coverage_start':float(mc_cov.iloc[0]),'mc_coverage_median':float(mc_cov.median()),'mc_coverage_latest':float(mc_cov.iloc[-1]),
         'vix_counts':pd.Series([x['type'] for x in vsignals if x['date']>=bt.START.strftime('%Y-%m-%d')]).value_counts().to_dict(),
         'nqsar_note':'No exact long-history NQ-SAR series was found; not fabricated.'}
Path('tqqq_stage3_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
