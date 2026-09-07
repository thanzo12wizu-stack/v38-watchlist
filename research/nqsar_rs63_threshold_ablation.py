from __future__ import annotations

import argparse, json, math
from pathlib import Path
import numpy as np
import pandas as pd

from research import nqsar_centric_broad_scan as scan

START=scan.START; END=scan.END; CONF=scan.CONF_START
VARIANTS=['RS63_NO_THRESH','RS63_R63_85','RS63_R189_85','RS63_BOTH_85','RS189_BOTH_85']


def safe(x):
    if isinstance(x,dict): return {str(k):safe(v) for k,v in x.items()}
    if isinstance(x,(list,tuple)): return [safe(v) for v in x]
    if isinstance(x,np.integer): return int(x)
    if isinstance(x,(np.floating,float)):
        z=float(x); return z if math.isfinite(z) else None
    return x


def selector(d,m,variant):
    pool=m['pool'].loc[d].fillna(False); struct=m['struct'].loc[d].fillna(False); wb=m['wb'].loc[d].fillna(False)
    q63=pd.to_numeric(m['q'][63].loc[d],errors='coerce'); q189=pd.to_numeric(m['q'][189].loc[d],errors='coerce'); ddv=pd.to_numeric(m['ddv'].loc[d],errors='coerce')
    mask=pool&struct&wb&q63.notna()&q189.notna()
    if variant=='RS63_R63_85': mask &= q63>=85
    elif variant=='RS63_R189_85': mask &= q189>=85
    elif variant in {'RS63_BOTH_85','RS189_BOTH_85'}: mask &= (q63>=85)&(q189>=85)
    elif variant!='RS63_NO_THRESH': raise KeyError(variant)
    score=q189 if variant=='RS189_BOTH_85' else q63
    # Rank the DDV10 pool first; only then drop <DDV20 with no refill.
    top=list(score.where(mask).dropna().nlargest(scan.NPORT).index)
    return [s for s in top if float(ddv.get(s,np.nan))>=20_000_000.0]


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--root',default='.'); ap.add_argument('--output',required=True); ap.add_argument('--batch-size',type=int,default=100)
    a=ap.parse_args(); root=Path(a.root); out=root/a.output; out.mkdir(parents=True,exist_ok=True)
    symbols,bio=scan.audit.load_universe(root/'universe.csv'); warm=str((START-pd.Timedelta(days=1600)).date()); end='2026-09-05'
    print('DOWNLOAD',flush=True); ohlcv,diag=scan.audit.download_ohlcv(symbols,warm,end,a.batch_size)
    if diag['coverage']<.85: raise RuntimeError(diag)
    print('INPUTS',flush=True); m=scan.build_inputs(ohlcv,bio); nq=scan.audit.market_nqsar(str((START-pd.Timedelta(days=120)).date()),end).reindex(m['close'].index).ffill(limit=2)
    idx=m['close'].index[(m['close'].index>=START)&(m['close'].index<=END)]
    orig=scan.score_mask; results={}; rows=[]
    try:
        scan.score_mask=selector
        for v in VARIANTS:
            print('SIM',v,flush=True); r=scan.simulate(idx,m,nq,v); results[v]=r; sl=scan.slices(r['equity'],r['exposure']); rec={'variant':v,'cost_bps':0}
            for p,mm in sl.items():
                for k,val in mm.items(): rec[f'{p}_{k}']=val
            rows.append(rec)
            r25=scan.simulate(idx,m,nq,v,cost_bps=25); sl25=scan.slices(r25['equity'],r25['exposure']); rec25={'variant':v,'cost_bps':25}
            for p,mm in sl25.items():
                for k,val in mm.items(): rec25[f'{p}_{k}']=val
            rows.append(rec25)
    finally: scan.score_mask=orig
    pd.DataFrame(rows).to_csv(out/'metrics.csv',index=False)
    base=results['RS63_NO_THRESH']['equity']; boots=[]
    for v in VARIANTS[1:]:
        boots.append({'variant':v,'vs_no_thresh_full_block20':scan.blockprob(results[v]['equity'],base),
                      'vs_no_thresh_conf_block20':scan.blockprob(results[v]['equity'],base,CONF)})
    # Directly isolate ranking axis under identical BOTH85 Weekly-Bull universe.
    boots.append({'variant':'RS63_BOTH85_vs_RS189_BOTH85','vs_no_thresh_full_block20':scan.blockprob(results['RS63_BOTH_85']['equity'],results['RS189_BOTH_85']['equity']),
                  'vs_no_thresh_conf_block20':scan.blockprob(results['RS63_BOTH_85']['equity'],results['RS189_BOTH_85']['equity'],CONF)})
    pd.DataFrame(boots).to_csv(out/'bootstrap.csv',index=False)
    summary={'method':'Weekly NQSAR Bull + structural trend; isolate RS63/RS189 ranking and RS63/RS189 >=85 eligibility thresholds; current market mode/exits; Top12 then DDV20 no-refill','coverage':diag,'variants':VARIANTS,'production_changed':False}
    (out/'summary.json').write_text(json.dumps(safe(summary),ensure_ascii=False,indent=2)); print('DONE_ABLATION',flush=True)

if __name__=='__main__': main()
