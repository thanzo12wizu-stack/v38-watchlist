from __future__ import annotations
import argparse, json, math
from pathlib import Path
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

COOLDOWN=20

def safe(v):
    if isinstance(v,dict): return {str(k):safe(x) for k,x in v.items()}
    if isinstance(v,(list,tuple)): return [safe(x) for x in v]
    if isinstance(v,np.integer): return int(v)
    if isinstance(v,(np.floating,float)):
        x=float(v); return x if math.isfinite(x) else None
    return v

def strict_events(df,mask):
    z=df.assign(_s=mask.fillna(False).to_numpy(bool)); rows=[]
    for _,g in z.groupby('sector',sort=False):
        g=g.sort_values('date').reset_index(drop=True); prev=False; last=-99999
        for i,r in g.iterrows():
            active=bool(r._s)
            if active and not prev and i-last>=COOLDOWN:
                rows.append(r.drop(labels='_s').to_dict()); last=i
            prev=active
    return pd.DataFrame(rows)

def cluster_diff(ev,group,a,b,outcome,reps=5000,seed=1):
    z=ev[['sector',group,outcome]].dropna(); sectors=z.sector.unique()
    def calc(q):
        A=q[q[group]==a][outcome]; B=q[q[group]==b][outcome]
        return float(A.mean()-B.mean()) if len(A)>=2 and len(B)>=2 else np.nan
    obs=calc(z); vals=[]; rng=np.random.default_rng(seed)
    if len(sectors)>=3:
        for _ in range(reps):
            sampled=rng.choice(sectors,len(sectors),replace=True)
            v=calc(pd.concat([z[z.sector==s] for s in sampled],ignore_index=True))
            if np.isfinite(v): vals.append(v)
    ci=[None,None] if not vals else [float(x) for x in np.quantile(vals,[.025,.975])]
    return {'a':a,'b':b,'a_n':int((z[group]==a).sum()),'b_n':int((z[group]==b).sum()),'difference':obs,'sector_cluster_ci95':ci}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--panel',type=Path,required=True); ap.add_argument('--output',type=Path,required=True); args=ap.parse_args(); args.output.mkdir(parents=True,exist_ok=True)
    df=pd.read_csv(args.panel,parse_dates=['date']).sort_values(['sector','date']); df['internal_delta20']=df.groupby('sector').internal_score.diff(20)
    hp=strict_events(df,df.price_score>=70); hp=hp[hp.date>=pd.Timestamp('2024-01-01')].copy()
    hp['internal_group']=np.where(hp.internal_score<50,'weak',np.where(hp.internal_score>=60,'strong','mid'))
    hp['flow_group']=np.where(hp.flow20_pct_aum<=0,'out',np.where(hp.flow20_pct_aum>0,'in','missing'))
    hp['delta_group']=np.where(hp.internal_delta20<=-20,'sharp_down',np.where(hp.internal_delta20>=0,'non_down','mid'))
    iw=strict_events(df,(df.price_score>=70)&(df.internal_score<50)); iw=iw[iw.date>=pd.Timestamp('2024-01-01')].copy(); iw['flow_group']=np.where(iw.flow20_pct_aum<=0,'out',np.where(iw.flow20_pct_aum>0,'in','missing'))
    report={'schema':2,'research_only':True,'method':'Transition-only high-price entry events; 20-session cooldown; 2024+; sector-cluster bootstrap.','comparisons':{}}
    for h in (20,40):
        report['comparisons'][f'internal_weak_vs_strong_{h}d']=cluster_diff(hp[hp.internal_group.isin(['weak','strong'])],'internal_group','weak','strong',f'fwd_excess_{h}d',seed=100+h)
        report['comparisons'][f'flow_out_vs_in_high_price_{h}d']=cluster_diff(hp[hp.flow_group.isin(['out','in'])],'flow_group','out','in',f'fwd_excess_{h}d',seed=200+h)
        report['comparisons'][f'internal_sharp_down_vs_non_down_{h}d']=cluster_diff(hp[hp.delta_group.isin(['sharp_down','non_down'])],'delta_group','sharp_down','non_down',f'fwd_excess_{h}d',seed=300+h)
        report['comparisons'][f'flow_out_vs_in_with_internal_weak_{h}d']=cluster_diff(iw[iw.flow_group.isin(['out','in'])],'flow_group','out','in',f'fwd_excess_{h}d',seed=400+h)
    regs={}
    for h in (20,40):
        cols=['price_score','internal_score','internal_delta20','flow20_pct_aum',f'fwd_excess_{h}d','sector']; z=hp[cols].dropna().copy()
        for c in ('price_score','internal_score','internal_delta20','flow20_pct_aum'):
            sd=z[c].std(); z[c+'_z']=(z[c]-z[c].mean())/sd if sd else 0
        fit=smf.ols(f'fwd_excess_{h}d ~ price_score_z + internal_score_z + internal_delta20_z + flow20_pct_aum_z',data=z).fit(cov_type='cluster',cov_kwds={'groups':z.sector})
        regs[str(h)]={'n':len(z),'r2':fit.rsquared,'coefficients':{k:{'coef':fit.params[k],'p':fit.pvalues[k]} for k in fit.params.index}}
    report['multivariate_high_price_entry']=regs
    (args.output/'incremental_component_report.json').write_text(json.dumps(safe(report),ensure_ascii=False,indent=2),encoding='utf-8')
    rows=[]
    for k,v in report['comparisons'].items(): rows.append({'comparison':k,**v})
    pd.json_normalize(rows).to_csv(args.output/'incremental_component_comparisons.csv',index=False)
    print(json.dumps({'comparisons':report['comparisons'],'regression':regs},default=str))
if __name__=='__main__': main()
