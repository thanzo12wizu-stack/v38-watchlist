from __future__ import annotations

import argparse, json, math
from pathlib import Path
import numpy as np
import pandas as pd

from research import nqsar_centric_broad_scan as scan
from research import audit_stock_nqsar_theme30_pit as audit

VARIANTS = [
    'WEEK_RS63_NOMIN',
    'WEEK_RS63_GE80',
    'WEEK_RS63_GE85',
    'WEEK_RS63_BOTH85',
    'WEEK_RS63_RS189GE85',
    'BLUEFIRST_RS63_NOMIN',
    'BLUEFIRST_RS63_BOTH85',
]


def safe(x):
    if isinstance(x, dict): return {str(k): safe(v) for k,v in x.items()}
    if isinstance(x, (list,tuple)): return [safe(v) for v in x]
    if isinstance(x, np.integer): return int(x)
    if isinstance(x, (np.floating,float)):
        z=float(x); return z if math.isfinite(z) else None
    return x


def rank_top12_then_ddv20(d, m, variant):
    pool=m['pool'].loc[d].fillna(False)
    mask=pool & m['struct'].loc[d].fillna(False) & m['wb'].loc[d].fillna(False)
    q63=pd.to_numeric(m['q'][63].loc[d],errors='coerce')
    q189=pd.to_numeric(m['q'][189].loc[d],errors='coerce')
    if variant=='WEEK_RS63_GE80': mask &= q63>=80
    elif variant=='WEEK_RS63_GE85': mask &= q63>=85
    elif variant=='WEEK_RS63_BOTH85': mask &= (q63>=85)&(q189>=85)
    elif variant=='WEEK_RS63_RS189GE85': mask &= q189>=85
    elif variant=='BLUEFIRST_RS63_BOTH85': mask &= (q63>=85)&(q189>=85)
    elif variant not in {'WEEK_RS63_NOMIN','BLUEFIRST_RS63_NOMIN'}: raise KeyError(variant)
    score=q63.copy()
    if variant.startswith('BLUEFIRST'):
        score=score+(m['ws'].loc[d]==3).astype(float)*1000
    selected=score.where(mask).dropna().nlargest(scan.NPORT).index.tolist()
    out=[]
    for s in selected:
        try: ddv=float(m['ddv'].at[d,s])
        except Exception: continue
        if np.isfinite(ddv) and ddv>=scan.DDV_ENTRY: out.append(s)
    return out


def blockprob(a,b,start=None,block=20,reps=5000,seed=20260907):
    if start is not None: a=a.loc[a.index>=start]; b=b.loc[b.index>=start]
    x=(a.pct_change(fill_method=None)-b.pct_change(fill_method=None)).dropna().to_numpy(float)
    if len(x)<20:return None
    rng=np.random.default_rng(seed+block+(100 if start is not None else 0)); starts=np.arange(max(1,len(x)-block+1)); win=0
    for _ in range(reps):
        z=[]
        while len(z)<len(x):
            st=int(rng.choice(starts)); z.extend(x[st:st+block])
        win += np.mean(z[:len(x)])>0
    return win/reps


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--root',default='.'); ap.add_argument('--output',required=True); ap.add_argument('--batch-size',type=int,default=100); a=ap.parse_args()
    root=Path(a.root); out=root/a.output; out.mkdir(parents=True,exist_ok=True)
    symbols,bio=audit.load_universe(root/'universe.csv'); warm=str((scan.START-pd.Timedelta(days=1600)).date()); end='2026-09-05'
    ohlcv,diag=audit.download_ohlcv(symbols,warm,end,a.batch_size)
    if diag['coverage']<.85: raise RuntimeError(diag)
    m=scan.build_inputs(ohlcv,bio)
    nq=audit.market_nqsar(str((scan.START-pd.Timedelta(days=120)).date()),end).reindex(m['close'].index).ffill(limit=2)
    idx=m['close'].index[(m['close'].index>=scan.START)&(m['close'].index<=scan.END)]
    orig=scan.score_mask
    results={}; rows=[]; costrows=[]
    for v in VARIANTS:
        scan.score_mask=lambda d, mm, _ignored, vv=v: rank_top12_then_ddv20(d,mm,vv)
        r=scan.simulate(idx,m,nq,v); results[v]=r; sl=scan.slices(r['equity'],r['exposure'])
        row={'variant':v}
        for p,met in sl.items():
            for k,val in met.items(): row[f'{p}_{k}']=val
        rows.append(row)
        rr=scan.simulate(idx,m,nq,v,cost_bps=25); cm=scan.slices(rr['equity'],rr['exposure'])
        costrows.append({'variant':v,'full_cagr_25bp':cm['full']['cagr'],'full_mdd_25bp':cm['full']['mdd'],'confirm_cagr_25bp':cm['confirmation_2022_plus']['cagr'],'confirm_mdd_25bp':cm['confirmation_2022_plus']['mdd']})
    scan.score_mask=orig
    base=results['WEEK_RS63_NOMIN']['equity']; boots=[]
    for v in VARIANTS:
        boots.append({'variant':v,'vs_nomin_full_block20':blockprob(results[v]['equity'],base),'vs_nomin_confirm_block20':blockprob(results[v]['equity'],base,scan.CONF_START)})
    pd.DataFrame(rows).to_csv(out/'threshold_metrics.csv',index=False)
    pd.DataFrame(costrows).to_csv(out/'threshold_cost25.csv',index=False)
    pd.DataFrame(boots).to_csv(out/'threshold_bootstrap.csv',index=False)
    summary={'method':'Weekly Bull + structural trend; RS63 rank; current Market Mode/current exits; Top12 on DDV10 then DDV20 no-refill; RS threshold sensitivity only','coverage':diag,'variants':VARIANTS}
    (out/'summary.json').write_text(json.dumps(safe(summary),indent=2),encoding='utf-8')

if __name__=='__main__': main()
