from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from research.rulebook_v2 import audit_market_stop_reentry as ms
from research.rulebook_v3 import audit_custom_market_modes as v1
from research.rulebook_v3 import audit_custom_market_modes_v2 as v2


def safe(x):
    if isinstance(x, dict): return {str(k): safe(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)): return [safe(v) for v in x]
    if isinstance(x, np.integer): return int(x)
    if isinstance(x, (np.floating, float)):
        z=float(x); return z if math.isfinite(z) else None
    if isinstance(x, pd.Timestamp): return x.isoformat()
    return x


def candidate_stats(frame: pd.DataFrame, mask: pd.Series, period: str) -> dict:
    pm = frame.index <= v2.DISCOVERY_END if period == 'DISCOVERY' else frame.index >= v2.CONFIRM_START
    z = frame.loc[mask & pm & frame.basket_20.notna(), 'basket_20']
    if z.empty: return {'n':0}
    gp=float(z[z>0].sum()); gl=float(-z[z<0].sum())
    return {
        'n':int(len(z)), 'mean20':float(z.mean()), 'median20':float(z.median()),
        'win20':float((z>0).mean()), 'pf20':None if gl<=0 else gp/gl,
        'p10_20':float(z.quantile(.10)), 'p90_20':float(z.quantile(.90)),
    }


def gate_simulations(frame, market, signal):
    bg=frame.nq_color.isin(['Blue','Green'])
    gates={f'NQ_BG_PA{int(t*100)}': bg & (frame.stock_pa50>=t) for t in [.50,.55,.60,.65,.70]}
    gates.update({
        'NQ_BG_PA60_MC20':bg&(frame.stock_pa50>=.60)&(frame.mc>=20),
        'NQ_BG_PA60_MC30':bg&(frame.stock_pa50>=.60)&(frame.mc>=30),
        'NQ_BG_PA60_MC35':bg&(frame.stock_pa50>=.60)&(frame.mc>=35),
        'NQ_BG_PA60_MC50':bg&(frame.stock_pa50>=.60)&(frame.mc>=50),
    })
    rows=[]
    for name,mask in gates.items():
        _,daily=ms.simulate_core(market,signal,v1.permission_from_mask(frame,mask),force_exit_red=True)
        for period,vals in ms.period_metrics(daily).items():
            if period in ('ALL','DISCOVERY','CONFIRM','2018Q4','COVID2020','BEAR2022'):
                rows.append({'rule':name,'period':period,**vals})
    return pd.DataFrame(rows)


def restart_simulations(frame, market, signal):
    not_red=~frame.nq_color.eq('Red')
    triggers={f'RESTART_PA{int(t*100)}':not_red&(frame.stock_pa50>=t) for t in [.45,.50,.55]}
    rows=[]
    for name,trig in triggers.items():
        _,daily=ms.simulate_core(market,signal,v1.reentry_permission(frame,trig),force_exit_red=True)
        for period,vals in ms.period_metrics(daily).items():
            if period in ('ALL','DISCOVERY','CONFIRM','2018Q4','COVID2020','BEAR2022'):
                rows.append({'rule':name,'period':period,**vals})
    return pd.DataFrame(rows)


def local_bands(frame):
    bg=frame.nq_color.isin(['Blue','Green'])
    edges=[0,.30,.40,.50,.55,.60,.65,.70,1.01]
    labels=['LT30','30_40','40_50','50_55','55_60','60_65','65_70','GE70']
    band=pd.cut(frame.stock_pa50,edges,labels=labels,right=False,include_lowest=True)
    rows=[]
    for label in labels:
        mask=bg & band.eq(label)
        for period in ('DISCOVERY','CONFIRM'):
            rows.append({'band':label,'period':period,**candidate_stats(frame,mask,period)})
    return pd.DataFrame(rows)


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--root',default='.'); ap.add_argument('--output',required=True); ap.add_argument('--asof',default='2026-08-28'); args=ap.parse_args()
    out=Path(args.output); out.mkdir(parents=True,exist_ok=True)
    market,signal,frame=v2.build_frame(Path(args.root),args.asof)
    gates=gate_simulations(frame,market,signal); gates.to_csv(out/'gate_simulations.csv',index=False)
    restarts=restart_simulations(frame,market,signal); restarts.to_csv(out/'restart_simulations.csv',index=False)
    bands=local_bands(frame); bands.to_csv(out/'local_bands.csv',index=False)
    summary={
        'status':'CUSTOM_MARKET_MODE_AUDIT_V3_NORMAL_ONLY',
        'scope':'normal-stock mode only; no shallow/RSI30/TQQQ rule changes',
        'fixed_tests':{
            'attack_breadth':[.50,.55,.60,.65,.70],
            'attack_mc_check':[20,30,35,50],
            'post_red_restart_breadth':[.45,.50,.55],
        },
        'method':'NQSAR Blue/Green for ongoing new-entry/rebalance gates; NQSAR Red forces exit; post-Red restart waits for not-Red plus the tested broad >50MA threshold, then remains reopened until next Red.',
        'validation':'Local plateau check only. No broad parameter search.',
        'limitations':['Normal-stock sleeve is the comparison reconstruction, not the missing exact production ledger.','Current-universe survivorship bias remains.','2022+ is robustness confirmation, not untouched OOS.','No main/dashboard change.']
    }
    (out/'summary.json').write_text(json.dumps(safe(summary),ensure_ascii=False,indent=2),encoding='utf-8')
    print('CUSTOM_MARKET_MODE_V3_NORMAL_ONLY_DONE',flush=True)

if __name__=='__main__': main()
