from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.api import OLS
from statsmodels.stats.multitest import multipletests

H = (5, 10, 20, 40)
EXPECTED = {
    'PRICE_LEAD_INTERNAL_WEAK': -1,
    'INTERNAL_DETERIORATION': -1,
    'INTERNAL_IGNITION_5D': 1,
    'INTERNAL_IGNITION_10D': 1,
    'INTERNAL_LEAD': 1,
    'TOP5_MOVE_CONCENTRATED': -1,
    'BROAD_CONFIRMED': 1,
    'PARENT_UNCONFIRMED_LEAD': 1,
    'DISTRIBUTION_WITH_FLOW': -1,
    'EARLY_ROTATION_WITH_FLOW': 1,
}
FEATURES = [
    'price_score','internal_score','internal_delta5','internal_delta10','internal_delta20',
    'breadth21_delta5','breadth21_delta10','breadth21_delta20','top5_move_share5',
    'parent_ret20_gap_pct','flow20_pct_aum'
]


def safe(v):
    if isinstance(v, dict): return {str(k): safe(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)): return [safe(x) for x in v]
    if isinstance(v, (np.integer,)): return int(v)
    if isinstance(v, (np.floating, float)):
        x = float(v); return x if math.isfinite(x) else None
    return v


def mbb_mean(x: np.ndarray, block: int, reps: int = 3000, seed: int = 7):
    x = np.asarray(x, float); x = x[np.isfinite(x)]
    n = len(x)
    if n < max(20, block * 2): return {'ci95':[None,None], 'p_two':None}
    block = max(2, min(block, n))
    rng = np.random.default_rng(seed)
    nblocks = int(math.ceil(n / block))
    starts = rng.integers(0, n, size=(reps, nblocks))
    offsets = np.arange(block, dtype=int)
    idx = (starts[:, :, None] + offsets[None, None, :]) % n
    idx = idx.reshape(reps, -1)[:, :n]
    vals = x[idx].mean(axis=1)
    ci=np.quantile(vals,[.025,.975]); p=2*min(np.mean(vals<=0),np.mean(vals>=0)); p=min(1.0,float(p))
    return {'ci95':[float(ci[0]),float(ci[1])], 'p_two':p}


def cluster_ci(df:pd.DataFrame,col:str,cluster:str,reps:int=3000,seed:int=11):
    z=df[[cluster,col]].dropna()
    agg=z.groupby(cluster,sort=False)[col].agg(['sum','count'])
    if len(agg)<8:return [None,None]
    sums=agg['sum'].to_numpy(float); counts=agg['count'].to_numpy(float); k=len(agg)
    rng=np.random.default_rng(seed)
    draw=rng.integers(0,k,size=(reps,k))
    numer=sums[draw].sum(axis=1); denom=counts[draw].sum(axis=1)
    vals=numer/denom
    q=np.quantile(vals,[.025,.975]); return [float(q[0]),float(q[1])]


def continuous(panel:pd.DataFrame):
    rows=[]; d=panel[panel.date>=pd.Timestamp('2024-01-01')]
    for feat in FEATURES:
        if feat not in d:continue
        for h in H:
            target=f'fwd_excess_{h}d'; vals=[]
            for _,g in d.groupby('date',sort=True):
                z=g[[feat,target]].dropna()
                if len(z)>=20 and z[feat].nunique()>=5:
                    r=stats.spearmanr(z[feat],z[target]).statistic
                    if np.isfinite(r): vals.append(float(r))
            a=np.asarray(vals,float)
            if len(a)<30:continue
            maxlags=min(max(1,h),len(a)-1)
            fit=OLS(a,np.ones((len(a),1))).fit(cov_type='HAC',cov_kwds={'maxlags':maxlags})
            mb=mbb_mean(a,block=max(5,h),seed=1000+h+len(rows))
            hac_p=float(fit.pvalues[0]); block_p=mb['p_two']; conservative=max(hac_p,block_p) if block_p is not None else hac_p
            rows.append({'feature':feat,'horizon':h,'n_dates':len(a),'mean_ic':float(a.mean()),'hac_p':hac_p,'mbb_p':block_p,'mbb_ci95':mb['ci95'],'conservative_p':conservative})
    if rows:
        q=multipletests([r['conservative_p'] for r in rows],method='fdr_bh')[1]
        for r,v in zip(rows,q):r['fdr_q']=float(v)
    return rows


def event_robust(events:pd.DataFrame):
    out=[]
    if events.empty:return out
    events=events.copy(); events['date']=pd.to_datetime(events.date).dt.normalize()
    for signal,g0 in events.groupby('signal'):
        sign=EXPECTED.get(signal)
        for period,lo in [('CONFIRMATION_2024_PLUS','2024-01-01'),('RECENT_2025_PLUS','2025-01-01')]:
            g=g0[g0.date>=pd.Timestamp(lo)].copy()
            for h in (20,40):
                row={'signal':signal,'expected_sign':sign,'period':period,'horizon':h}
                for kind,col in [('excess',f'fwd_excess_{h}d'),('matched',f'matched_{h}d')]:
                    if col not in g:
                        row.update({f'{kind}_n':0,f'{kind}_mean':None,f'{kind}_ticker_ci95':[None,None],f'{kind}_date_ci95':[None,None]}); continue
                    z=g[['date','ticker',col]].dropna()
                    row[f'{kind}_n']=len(z); row[f'{kind}_mean']=float(z[col].mean()) if len(z) else None
                    row[f'{kind}_ticker_ci95']=cluster_ci(z,col,'ticker',seed=2000+h)
                    row[f'{kind}_date_ci95']=cluster_ci(z,col,'date',seed=3000+h)
                ci1=row['excess_ticker_ci95']; ci2=row['excess_date_ci95']
                if sign is None or None in ci1 or None in ci2:
                    row['excess_both_clusters_expected']=None
                elif sign>0:
                    row['excess_both_clusters_expected']=bool(ci1[0]>0 and ci2[0]>0)
                else:
                    row['excess_both_clusters_expected']=bool(ci1[1]<0 and ci2[1]<0)
                out.append(row)
    return out


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--output',type=Path,required=True); args=ap.parse_args()
    panel=pd.read_parquet(args.output/'theme56_retrospective_panel.parquet'); panel['date']=pd.to_datetime(panel.date).dt.normalize()
    events=pd.read_csv(args.output/'theme56_retrospective_events.csv') if (args.output/'theme56_retrospective_events.csv').exists() else pd.DataFrame()
    ic=continuous(panel); ev=event_robust(events)
    pd.DataFrame([{k:v for k,v in r.items() if k!='mbb_ci95'}|{'mbb_ci_lo':r['mbb_ci95'][0],'mbb_ci_hi':r['mbb_ci95'][1]} for r in ic]).to_csv(args.output/'theme56_overlap_safe_ic.csv',index=False)
    pd.DataFrame([{k:v for k,v in r.items() if not k.endswith('_ci95')}|{f'{k}_lo':v[0] for k,v in r.items() if k.endswith('_ci95')}|{f'{k}_hi':v[1] for k,v in r.items() if k.endswith('_ci95')} for r in ev]).to_csv(args.output/'theme56_event_robustness.csv',index=False)
    summary={'schema':1,'research_only':True,'evidence_grade':'CURRENT_MEMBERSHIP_RETROSPECTIVE_NOT_PIT','guardrail':'Supportive evidence only. Historical Theme56 membership is unavailable.','continuous_ic':ic,'events':ev,'ic_q_lt_010':sum(1 for r in ic if r.get('fdr_q',1)<.10)}
    (args.output/'theme56_robustness_report.json').write_text(json.dumps(safe(summary),ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'ic_tests':len(ic),'ic_q_lt_010':summary['ic_q_lt_010'],'event_rows':len(ev)},indent=2))

if __name__=='__main__':main()
