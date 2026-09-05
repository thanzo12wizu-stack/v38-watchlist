from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

H=(5,10,20,40)
COOLDOWN=20


def safe(v):
    if isinstance(v,dict):return {str(k):safe(x) for k,x in v.items()}
    if isinstance(v,(list,tuple)):return [safe(x) for x in v]
    if isinstance(v,np.integer):return int(v)
    if isinstance(v,(np.floating,float)):
        x=float(v); return x if math.isfinite(x) else None
    return v


def add_features(df):
    z=df.sort_values(['sector','date']).copy()
    for d in (5,10,20):
        z[f'internal_delta{d}']=z.groupby('sector',sort=False).internal_score.diff(d)
    z['internal_band']=np.select([z.internal_score<45,z.internal_score>=60],['WEAK','STRONG'],default='MID')
    z['price_band']=np.select([z.price_score<45,z.price_score>=70],['WEAK','STRONG'],default='MID')
    z['flow_band']=np.select([z.flow20_pct_aum<0,z.flow20_pct_aum>0],['OUT','IN'],default='FLAT_OR_NA')
    return z


def strict_events(df,mask):
    z=df.assign(_s=mask.fillna(False).to_numpy(bool)); rows=[]
    for _,g in z.groupby('sector',sort=False):
        g=g.sort_values('date').reset_index(drop=True); prev=False; last=-10**9
        for i,r in g.iterrows():
            active=bool(r['_s'])
            if active and not prev and i-last>=COOLDOWN:
                rows.append(r.drop(labels='_s').to_dict()); last=i
            prev=active
    return pd.DataFrame(rows)


def cluster_ci(df,col,cluster,reps=4000,seed=1):
    z=df[[cluster,col]].dropna(); keys=z[cluster].drop_duplicates().tolist()
    if len(keys)<6:return [None,None]
    groups={k:z.loc[z[cluster]==k,col].to_numpy(float) for k in keys}; rng=np.random.default_rng(seed); vals=[]
    for _ in range(reps):
        draw=rng.choice(keys,len(keys),replace=True); a=np.concatenate([groups[k] for k in draw]); vals.append(float(a.mean()))
    q=np.quantile(vals,[.025,.975]); return [float(q[0]),float(q[1])]


def attach_controls(df,ev,band,dcol,direction):
    if ev.empty:return ev
    out=[]
    for _,r in ev.iterrows():
        same=df[(df.date==r.date)&(df.internal_band==band)&(df.sector!=r.sector)].copy()
        # Primary control holds current internal band constant and excludes same direction.
        if direction=='UP': same=same[same[dcol]<10]
        else: same=same[same[dcol]>-10]
        same_price=same[same.price_band==r.price_band]
        z=r.to_dict()
        for h in H:
            target=f'fwd_excess_{h}d'
            a=pd.to_numeric(same[target],errors='coerce').dropna(); b=pd.to_numeric(same_price[target],errors='coerce').dropna()
            z[f'matched_band_{h}d']=r[target]-a.mean() if len(a)>=3 and pd.notna(r[target]) else np.nan
            z[f'matched_band_price_{h}d']=r[target]-b.mean() if len(b)>=2 and pd.notna(r[target]) else np.nan
        out.append(z)
    return pd.DataFrame(out)


def stats_row(ev,signal,period,delta_h,threshold,band,direction,h):
    col=f'fwd_excess_{h}d'; z=ev[['date','sector',col,f'matched_band_{h}d',f'matched_band_price_{h}d']].dropna(subset=[col]).copy()
    row={'signal':signal,'period':period,'delta_horizon':delta_h,'delta_threshold':threshold,'current_band':band,'direction':direction,'fwd_horizon':h,'n':len(z),'mean_excess':float(z[col].mean()) if len(z) else None,'median_excess':float(z[col].median()) if len(z) else None}
    row['ticker_cluster_ci95']=cluster_ci(z,col,'sector',seed=100+h+delta_h+threshold)
    row['date_cluster_ci95']=cluster_ci(z,col,'date',seed=200+h+delta_h+threshold)
    for kind in ('matched_band','matched_band_price'):
        c=f'{kind}_{h}d'; q=z.dropna(subset=[c]); row[f'{kind}_n']=len(q); row[f'{kind}_mean']=float(q[c].mean()) if len(q) else None; row[f'{kind}_sector_ci95']=cluster_ci(q,c,'sector',seed=300+h+delta_h+threshold)
    return row


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--panel',type=Path,required=True); ap.add_argument('--output',type=Path,required=True); args=ap.parse_args(); args.output.mkdir(parents=True,exist_ok=True)
    df=add_features(pd.read_csv(args.panel,parse_dates=['date']))
    periods=[('CONFIRMATION_2024_PLUS',pd.Timestamp('2024-01-01')),('RECENT_2025_PLUS',pd.Timestamp('2025-01-01'))]
    rows=[]; event_rows=[]
    for delta_h in (5,10,20):
        dcol=f'internal_delta{delta_h}'
        for threshold in (10,20):
            defs=[('WEAK_IMPROVING','WEAK','UP',(df.internal_band=='WEAK')&(df[dcol]>=threshold)),('WEAK_WORSENING','WEAK','DOWN',(df.internal_band=='WEAK')&(df[dcol]<=-threshold)),('STRONG_IMPROVING','STRONG','UP',(df.internal_band=='STRONG')&(df[dcol]>=threshold)),('STRONG_WORSENING','STRONG','DOWN',(df.internal_band=='STRONG')&(df[dcol]<=-threshold))]
            for signal,band,direction,mask in defs:
                ev=strict_events(df,mask)
                ev=attach_controls(df,ev,band,dcol,direction)
                if not ev.empty:
                    ev['signal']=signal; ev['delta_horizon']=delta_h; ev['delta_threshold']=threshold; event_rows.append(ev)
                for period,lo in periods:
                    ep=ev[ev.date>=lo].copy() if not ev.empty else ev
                    for h in H:rows.append(stats_row(ep,signal,period,delta_h,threshold,band,direction,h))
    summary=pd.DataFrame(rows)
    all_ev=pd.concat(event_rows,ignore_index=True) if event_rows else pd.DataFrame()
    summary.to_csv(args.output/'internal_path_quadrant_summary.csv',index=False); all_ev.to_csv(args.output/'internal_path_quadrant_events.csv',index=False)
    # Compact direction stability: fraction of eligible horizon/period/threshold variants with same sign.
    stability={}
    for signal,g in summary.groupby('signal'):
        eligible=g[g.n>=8].copy(); vals=pd.to_numeric(eligible.mean_excess,errors='coerce').dropna(); stability[signal]={'eligible_cells':len(vals),'positive_fraction':None if vals.empty else float((vals>0).mean()),'negative_fraction':None if vals.empty else float((vals<0).mean()),'mean_of_cell_means':None if vals.empty else float(vals.mean())}
    report={'schema':1,'research_only':True,'design':'Audited 11-sector PIT panel; current internal band x 5/10/20d internal change; transition-only events; 20-session cooldown; sector/date cluster bootstrap; same-day matched controls.','band_definition':{'WEAK':'internal_score <45','STRONG':'internal_score >=60'},'delta_thresholds':[10,20],'periods':[p[0] for p in periods],'stability':stability}
    (args.output/'internal_path_quadrant_report.json').write_text(json.dumps(safe(report),ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(stability,indent=2))

if __name__=='__main__':main()
