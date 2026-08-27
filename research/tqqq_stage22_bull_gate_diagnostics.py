from __future__ import annotations
from pathlib import Path
import json, numpy as np, pandas as pd

src=Path('research/tqqq_stage21_bull_capture.py').read_text()
prefix=src.split('# Diagnostics frame for audit.')[0]
exec(compile(prefix,'stage21-prefix','exec'),globals())

print('\n=== STAGE22 BULL GATE DIAGNOSTICS ===',flush=True)
dates=pd.to_datetime(F.date).reset_index(drop=True)
rows=[]
for y in YEARS:
    m=(dates.dt.year.to_numpy()==y)
    nolock=~T['risklock'][m]
    mc=A['mc'][m]; nq=A['nq'][m]; a50=A['a50'][m]; a63=A['a63'][m]; s50a=A['s50a'][m]; target=T['target'][m]
    structure=nolock & a50 & a63 & (s50a<=2.5)
    blue_struct=structure & (nq==3)
    mc_struct=structure & (mc>=65)
    allgate=blue_struct & (mc>=65)
    rows.append({
        'year':y,'days':int(m.sum()),
        'pct_no_risklock':float(nolock.mean()),
        'pct_mc65':float((mc>=65).mean()),
        'pct_blue':float((nq==3).mean()),
        'pct_a50':float(a50.mean()),'pct_a63':float(a63.mean()),'pct_not_overheat':float((s50a<=2.5).mean()),
        'pct_structure_ready':float(structure.mean()),
        'pct_blue_and_structure':float(blue_struct.mean()),
        'pct_mc65_and_structure':float(mc_struct.mean()),
        'pct_all_strong_gate':float(allgate.mean()),
        'pct_blue_structure_but_mc_below65':float((blue_struct & (mc<65)).mean()),
        'pct_mc65_structure_but_not_blue':float((mc_struct & (nq!=3)).mean()),
        'pct_target30':float(np.isclose(target,.30).mean()),
        'pct_target90':float(np.isclose(target,.90).mean()),
        'pct_target100':float((target>=.999).mean()),
        'mc_median':float(np.median(mc)),'mc_p75':float(np.quantile(mc,.75)),'mc_p90':float(np.quantile(mc,.90)),
    })
R=pd.DataFrame(rows); R.to_csv('tqqq_stage22_bull_gate_diagnostics.csv',index=False)
print(R.to_string(index=False))

# Threshold sensitivity as diagnosis only: fraction of days that WOULD pass the existing strong-bull gate
# if only the MC threshold were changed. This does not change or backtest the strategy.
sens=[]
for y in YEARS:
    m=(dates.dt.year.to_numpy()==y); nolock=~T['risklock'][m]; mc=A['mc'][m]; nq=A['nq'][m]; a50=A['a50'][m]; a63=A['a63'][m]; s50a=A['s50a'][m]
    core=nolock & (nq==3) & a50 & a63 & (s50a<=2.5)
    for th in [45,50,55,60,65]:
        sens.append({'year':y,'mc_threshold':th,'pct_days_gate_would_pass':float((core&(mc>=th)).mean())})
S=pd.DataFrame(sens); S.to_csv('tqqq_stage22_mc_threshold_diagnostic.csv',index=False)
print('\n=== MC THRESHOLD DIAGNOSTIC (NOT A STRATEGY BACKTEST) ===')
print(S.pivot(index='year',columns='mc_threshold',values='pct_days_gate_would_pass').to_string())
Path('tqqq_stage22_summary.json').write_text(json.dumps({'gate':R.to_dict('records'),'mc_threshold_diagnostic':S.to_dict('records'),'note':'Diagnostic only. No strategy rule or target is changed. Threshold table only shows how often the existing Strong Bull core would pass at alternate MC cutoffs; it is not a performance backtest.'},ensure_ascii=False,indent=2))
