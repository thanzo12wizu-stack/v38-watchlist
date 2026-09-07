from __future__ import annotations
import argparse, json, math
from pathlib import Path
import numpy as np
import pandas as pd
from research import nqsar_centric_broad_scan as scan
from research import audit_stock_nqsar_theme30_pit as audit

VARIANTS=['WEEK_BULL_STRUCT_RS63','WEEK_BLUE_FIRST_RS63','WEEK_BULL_DAILY_NOT_RED_RS63']
EXITS=['CURRENT','DAILY_RED','WEEK_RED','WEEK_NONBULL']

def safe(x):
    if isinstance(x,dict):return {str(k):safe(v) for k,v in x.items()}
    if isinstance(x,(list,tuple)):return [safe(v) for v in x]
    if isinstance(x,np.integer):return int(x)
    if isinstance(x,(np.floating,float)):
        z=float(x);return z if math.isfinite(z) else None
    return x

def top12ddv(d,m,v):
    old=scan.DDV_ENTRY
    try:scan.DDV_ENTRY=0.;raw=_ORIG(d,m,v)
    finally:scan.DDV_ENTRY=old
    out=[]
    for s in raw:
        try:x=float(m['ddv'].at[d,s])
        except Exception:continue
        if np.isfinite(x) and x>=20_000_000:out.append(s)
    return out

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',default='.');ap.add_argument('--output',required=True);ap.add_argument('--batch-size',type=int,default=100);a=ap.parse_args()
    root=Path(a.root);out=root/a.output;out.mkdir(parents=True,exist_ok=True)
    symbols,bio=audit.load_universe(root/'universe.csv');warm=str((scan.START-pd.Timedelta(days=1600)).date());end='2026-09-05'
    ohlcv,diag=audit.download_ohlcv(symbols,warm,end,a.batch_size);m=scan.build_inputs(ohlcv,bio)
    nq=audit.market_nqsar(str((scan.START-pd.Timedelta(days=120)).date()),end).reindex(m['close'].index).ffill(limit=2);idx=m['close'].index[(m['close'].index>=scan.START)&(m['close'].index<=scan.END)]
    global _ORIG;_ORIG=scan.score_mask;scan.score_mask=top12ddv
    rows=[]
    for v in VARIANTS:
        for ep in EXITS:
            r=scan.simulate(idx,m,nq,v,exit_policy=ep);sl=scan.slices(r['equity'],r['exposure']);row={'variant':v,'exit_policy':ep}
            for p,met in sl.items():
                for k,val in met.items():row[f'{p}_{k}']=val
            t=r['trades'];row['trades']=len(t);row['mean_trade']=float(t['return'].mean()) if len(t) else None;row['win_rate']=float((t['return']>0).mean()) if len(t) else None;rows.append(row)
    scan.score_mask=_ORIG;pd.DataFrame(rows).to_csv(out/'exit_sensitivity.csv',index=False)
    (out/'summary.json').write_text(json.dumps(safe({'method':'Exact finalist entry architecture with current Market Mode and Top12->DDV20 no-refill; only stock-level exit overlay changes','coverage':diag,'variants':VARIANTS,'exits':EXITS}),indent=2),encoding='utf-8')
if __name__=='__main__':main()
