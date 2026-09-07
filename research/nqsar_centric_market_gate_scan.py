from __future__ import annotations

import argparse, json
from pathlib import Path

import pandas as pd

from research import nqsar_centric_broad_scan as scan
from research import nqsar_centric_broad_scan_runner as _runner  # patches Top12->DDV20 semantics

GATES = ('CURRENT','MARKET_NQSAR_ONLY','MARKET_RED_ONLY','BREADTH_WITH_RED')


def gate_fn(name):
    def current(color, breadth):
        return scan.audit.mode(color, breadth)
    def nqsar_only(color, breadth):
        c=str(color or '').title()
        if c=='Red': return 'DEFENSE'
        if c in {'Blue','Green'}: return 'ATTACK'
        return 'STOP'
    def red_only(color, breadth):
        return 'DEFENSE' if str(color or '').title()=='Red' else 'ATTACK'
    def breadth_red(color, breadth):
        if str(color or '').title()=='Red': return 'DEFENSE'
        if not scan.audit.finite(breadth): return 'STOP'
        b=float(breadth)
        if b>=60: return 'ATTACK'
        if b>=50: return 'SELECTIVE'
        return 'STOP'
    return {'CURRENT':current,'MARKET_NQSAR_ONLY':nqsar_only,'MARKET_RED_ONLY':red_only,'BREADTH_WITH_RED':breadth_red}[name]


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--root',default='.'); ap.add_argument('--output',required=True); ap.add_argument('--batch-size',type=int,default=100); a=ap.parse_args()
    root=Path(a.root); out=root/a.output; out.mkdir(parents=True,exist_ok=True)
    symbols,bio=scan.audit.load_universe(root/'universe.csv'); warm=str((scan.START-pd.Timedelta(days=1600)).date()); end='2026-09-05'
    print('DOWNLOAD',flush=True); ohlcv,diag=scan.audit.download_ohlcv(symbols,warm,end,a.batch_size)
    if diag['coverage']<.85: raise RuntimeError(diag)
    print('INPUTS',flush=True); m=scan.build_inputs(ohlcv,bio)
    nq=scan.audit.market_nqsar(str((scan.START-pd.Timedelta(days=120)).date()),end).reindex(m['close'].index).ffill(limit=2)
    idx=m['close'].index[(m['close'].index>=scan.START)&(m['close'].index<=scan.END)]
    orig=scan.audit.mode; rows=[]
    try:
        for gate in GATES:
            print('GATE',gate,flush=True); scan.audit.mode=gate_fn(gate)
            for i,v in enumerate(scan.VARIANTS,1):
                print(f'{gate} {i}/{len(scan.VARIANTS)} {v}',flush=True)
                r=scan.simulate(idx,m,nq,v); sl=scan.slices(r['equity'],r['exposure']); rec={'gate':gate,'variant':v}
                for p,mm in sl.items():
                    for k,val in mm.items(): rec[f'{p}_{k}']=val
                rows.append(rec)
    finally:
        scan.audit.mode=orig
    df=pd.DataFrame(rows); df.to_csv(out/'market_gate_matrix.csv',index=False)
    # Pick winners only on discovery within each gate, then expose untouched confirmation.
    winners=[]
    for gate,g in df.groupby('gate',observed=True):
        z=g[g.discovery_2016_2021_avg_exposure>=.20].sort_values('discovery_2016_2021_cagr',ascending=False).head(8)
        winners.extend(z.to_dict('records'))
    pd.DataFrame(winners).to_csv(out/'discovery_winners_by_gate.csv',index=False)
    summary={'method':'same stock architectures under four market timing gates; Top12 then DDV20 no-refill; current exits unchanged','coverage':diag,'gates':list(GATES),'variants':len(scan.VARIANTS),'note':'winner ranking uses discovery only; confirmation_2022_plus is untouched'}
    (out/'summary.json').write_text(json.dumps(scan.safe(summary),ensure_ascii=False,indent=2)); print('DONE_GATE',flush=True)

if __name__=='__main__': main()
