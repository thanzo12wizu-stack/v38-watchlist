#!/usr/bin/env python3
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
src=json.loads((ROOT/'market_conditions_level_bias_15y.json').read_text())
rows=[]
for name,v in src['variants'].items():
    o=v['overall']; c=v['conditional']; cal=v['calibration']
    rows.append({
      'name':name,
      'aug21':round(v['aug21'],2),
      'overall_mean':round(o['mean'],2),'overall_median':round(o['median'],2),
      'overall_ge80_pct':round(o['pct_ge80'],1),'overall_ge65_pct':round(o['pct_ge65'],1),'overall_lt55_pct':round(o['pct_lt55'],1),
      'healthy_median':round(c['healthy_bull_combo']['median'],2),'healthy_ge65_pct':round(cal['healthy_bull_pct_ge65'],1),'healthy_lt55_pct':round(cal['healthy_bull_pct_lt55'],1),
      'mixed_median':round(cal['mixed_median'],2),'mixed_ge65_pct':round(cal['mixed_pct_ge65'],1),
      'stress10_median':round(c['stress_10pct']['median'],2),'stress10_ge65_pct':round(c['stress_10pct']['pct_ge65'],1),'stress10_lt55_pct':round(c['stress_10pct']['pct_lt55'],1),
      'weak_median':round(c['weak_combo']['median'],2),'weak_ge65_pct':round(cal['weak_pct_ge65'],1),'weak_lt55_pct':round(cal['weak_pct_lt55'],1),
      'healthy_weak_median_gap':round(cal['separation_healthy_minus_weak_median'],2),
    })
out={'context_days':src['context_days'],'rows':rows}
(ROOT/'market_conditions_level_bias_summary.json').write_text(json.dumps(out,ensure_ascii=False,indent=2))
print(json.dumps(out,ensure_ascii=False,indent=2))
