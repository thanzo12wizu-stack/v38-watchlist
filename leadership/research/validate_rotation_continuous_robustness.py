from __future__ import annotations

import argparse, json, math
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd
from scipy import stats
import statsmodels.api as sm
from statsmodels.stats.multitest import multipletests

HORIZONS=(5,10,20,40)


def safe(v:Any)->Any:
    if isinstance(v,dict): return {str(k):safe(x) for k,x in v.items()}
    if isinstance(v,(list,tuple)): return [safe(x) for x in v]
    if isinstance(v,(np.integer,)): return int(v)
    if isinstance(v,(np.floating,float)):
        x=float(v); return x if math.isfinite(x) else None
    return v


def features(df:pd.DataFrame)->pd.DataFrame:
    df=df.sort_values(['sector','date']).copy()
    for h in (5,10,20):
        for c in ('internal_score','price_score','breadth21','breadth50','ad20_score','obv_positive20','updown_volume20','flow20_pct_aum'):
            if c in df: df[f'{c}_delta{h}']=df.groupby('sector',sort=False)[c].diff(h)
    df['price_internal_gap']=df.price_score-df.internal_score
    return df


def daily_ic(df:pd.DataFrame,feat:str,h:int)->pd.DataFrame:
    rows=[]
    for dt,g in df.groupby('date'):
        z=g[[feat,f'fwd_excess_{h}d']].dropna()
        if len(z)>=6 and z[feat].nunique()>=3:
            r=stats.spearmanr(z[feat],z[f'fwd_excess_{h}d']).statistic
            if np.isfinite(r): rows.append({'date':dt,'ic':float(r)})
    return pd.DataFrame(rows)


def circular_block_ci(a:np.ndarray,block:int,reps:int=3000,seed:int=123)->list[float|None]:
    a=np.asarray(a,float); a=a[np.isfinite(a)]; n=len(a)
    if n<40:return [None,None]
    rng=np.random.default_rng(seed); nb=math.ceil(n/block); starts=rng.integers(0,n,size=(reps,nb)); offsets=np.arange(block)
    idx=(starts[:,:,None]+offsets[None,None,:])%n; samples=a[idx.reshape(reps,-1)[:,:n]]
    q=np.quantile(samples.mean(axis=1),[.025,.975]); return [float(q[0]),float(q[1])]


def phase_sensitivity(df:pd.DataFrame,feat:str,h:int)->dict[str,Any]:
    dates=np.array(sorted(df.date.unique())); step=max(20,h); vals=[]; spreads=[]
    for off in range(min(step,len(dates))):
        sample_dates=dates[off::step]; ics=[]; spr=[]
        for dt in sample_dates:
            z=df.loc[df.date==dt,[feat,f'fwd_excess_{h}d']].dropna().sort_values(feat)
            if len(z)>=8 and z[feat].nunique()>=4:
                r=stats.spearmanr(z[feat],z[f'fwd_excess_{h}d']).statistic
                if np.isfinite(r): ics.append(float(r))
                k=max(2,min(3,len(z)//3)); spr.append(float(z.tail(k)[f'fwd_excess_{h}d'].mean()-z.head(k)[f'fwd_excess_{h}d'].mean()))
        if len(ics)>=8: vals.append(float(np.mean(ics)))
        if len(spr)>=8: spreads.append(float(np.mean(spr)))
    return {'step':step,'phase_count':len(vals),'median_phase_ic':None if not vals else float(np.median(vals)),'fraction_phase_ic_positive':None if not vals else float(np.mean(np.array(vals)>0)),'phase_ic_range':None if not vals else [float(np.min(vals)),float(np.max(vals))],'median_top_bottom_spread':None if not spreads else float(np.median(spreads)),'fraction_top_bottom_positive':None if not spreads else float(np.mean(np.array(spreads)>0)),'spread_range':None if not spreads else [float(np.min(spreads)),float(np.max(spreads))]}


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--panel',type=Path,required=True); ap.add_argument('--output',type=Path,required=True); args=ap.parse_args(); args.output.mkdir(parents=True,exist_ok=True)
    df=features(pd.read_csv(args.panel,parse_dates=['date'])); df=df[df.date>=pd.Timestamp('2024-01-01')]
    feats=['price_score','internal_score','flow20_pct_aum','price_internal_gap']+[f'internal_score_delta{x}' for x in (5,10,20)]+[f'breadth21_delta{x}' for x in (5,10,20)]+[f'breadth50_delta{x}' for x in (5,10,20)]+[f'flow20_pct_aum_delta{x}' for x in (5,10,20)]
    rows=[]; detail={}
    for feat in feats:
        if feat not in df:continue
        for h in HORIZONS:
            ic=daily_ic(df,feat,h)
            if len(ic)<40:continue
            a=ic.ic.to_numpy(float); lag=max(20,h); fit=sm.OLS(a,np.ones((len(a),1))).fit(cov_type='HAC',cov_kwds={'maxlags':lag})
            ci=circular_block_ci(a,lag,3000,seed=1000+h)
            phase=phase_sensitivity(df,feat,h)
            rows.append({'feature':feat,'horizon':h,'n_dates':len(a),'mean_daily_ic':a.mean(),'hac_lag':lag,'hac_t':fit.tvalues[0],'hac_p':fit.pvalues[0],'block_ci_lo':ci[0],'block_ci_hi':ci[1],'phase_median_ic':phase['median_phase_ic'],'phase_positive_fraction':phase['fraction_phase_ic_positive'],'phase_median_spread':phase['median_top_bottom_spread'],'phase_spread_positive_fraction':phase['fraction_top_bottom_positive']})
            detail[f'{feat}__{h}']=phase
    out=pd.DataFrame(rows); out['hac_fdr_q']=multipletests(out.hac_p.to_numpy(),method='fdr_bh')[1] if len(out) else []
    out.to_csv(args.output/'continuous_overlap_safe_results.csv',index=False)
    robust=[]
    for _,r in out.iterrows():
        sign=1 if r.mean_daily_ic>0 else -1; block=bool((r.block_ci_lo>0) if sign>0 else (r.block_ci_hi<0)); phase=bool((r.phase_positive_fraction>=.75) if sign>0 else (r.phase_positive_fraction<=.25)); fdr=bool(r.hac_fdr_q<=.10)
        robust.append({'feature':r.feature,'horizon':int(r.horizon),'sign':'POSITIVE' if sign>0 else 'NEGATIVE','hac_fdr_q':r.hac_fdr_q,'block_ci_excludes_zero':block,'phase_sign_stable':phase,'classification':'ROBUST' if fdr and block and phase else ('TENTATIVE' if block and phase else 'NOT_ROBUST')})
    report={'schema':1,'research_only':True,'method':{'start':'2024-01-01','daily_ic':'cross-sectional Spearman','serial_correlation':'HAC maxlags=max(20,horizon)','uncertainty':'circular moving-block bootstrap','multiple_testing':'Benjamini-Hochberg across all feature/horizon tests','overlap_sensitivity':'all phase offsets using non-overlapping max(20,horizon)-session snapshots','robust_rule':'HAC FDR q<=0.10 AND block CI excludes zero AND >=75% phase offsets same sign'},'results':safe(robust),'phase_detail':safe(detail)}
    (args.output/'continuous_overlap_safe_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# Overlap-safe Rotation continuous validation','', 'Daily IC alone is not accepted. HAC, block bootstrap, global FDR and non-overlapping phase sensitivity are required.','', '| Feature | H | IC | HAC q | block CI | phase sign | Class |','|---|---:|---:|---:|---|---:|---|']
    for r,rr in zip(out.to_dict('records'),robust): lines.append(f"| {r['feature']} | {int(r['horizon'])} | {r['mean_daily_ic']:+.3f} | {r['hac_fdr_q']:.3f} | [{r['block_ci_lo']:+.3f}, {r['block_ci_hi']:+.3f}] | {r['phase_positive_fraction']:.2f} | {rr['classification']} |")
    (args.output/'README.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('DONE overlap-safe continuous validation', 'robust=',sum(x['classification']=='ROBUST' for x in robust),'tests=',len(robust))

if __name__=='__main__':main()
