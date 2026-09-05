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
    if isinstance(v,dict): return {str(k):safe(x) for k,x in v.items()}
    if isinstance(v,(list,tuple)): return [safe(x) for x in v]
    if isinstance(v,np.integer): return int(v)
    if isinstance(v,(np.floating,float)):
        x=float(v); return x if math.isfinite(x) else None
    return v


def cluster_ci(df,col,cluster,reps=5000,seed=1):
    z=df[[cluster,col]].dropna(); keys=z[cluster].drop_duplicates().tolist()
    if len(keys)<6:return [None,None]
    groups={k:z.loc[z[cluster]==k,col].to_numpy(float) for k in keys}; rng=np.random.default_rng(seed); vals=[]
    for _ in range(reps):
        draw=rng.choice(keys,len(keys),replace=True); vals.append(float(np.concatenate([groups[k] for k in draw]).mean()))
    q=np.quantile(vals,[.025,.975]);return [float(q[0]),float(q[1])]


def transition_events(df,mask):
    z=df.assign(_s=mask.fillna(False).to_numpy(bool));out=[]
    for _,g in z.groupby('sector',sort=False):
        g=g.sort_values('date').reset_index(drop=True);prev=False;last=-10**9
        for i,r in g.iterrows():
            active=bool(r['_s'])
            if active and not prev and i-last>=COOLDOWN:
                out.append(r.drop(labels='_s').to_dict());last=i
            prev=active
    return pd.DataFrame(out)


def attach_same_weak_controls(df,ev):
    if ev.empty:return ev
    rows=[]
    for _,r in ev.iterrows():
        peers=df[(df.date==r.date)&(df.internal_score<45)&(df.sector!=r.sector)].copy()
        near=peers[(peers.internal_score-r.internal_score).abs()<=10]
        same_price=near[near.price_band==r.price_band]
        z=r.to_dict()
        for h in H:
            c=f'fwd_excess_{h}d'
            for name,q,minn in [('weak',peers,3),('nearweak',near,2),('nearweak_price',same_price,2)]:
                a=pd.to_numeric(q[c],errors='coerce').dropna()
                z[f'matched_{name}_{h}d']=r[c]-a.mean() if pd.notna(r[c]) and len(a)>=minn else np.nan
        rows.append(z)
    return pd.DataFrame(rows)


def row_stats(ev,label,period,lookback,h):
    c=f'fwd_excess_{h}d'; z=ev.dropna(subset=[c]).copy()
    out={'path':label,'period':period,'lookback':lookback,'horizon':h,'n':len(z),'mean_excess':float(z[c].mean()) if len(z) else None,'median_excess':float(z[c].median()) if len(z) else None,'sector_ci95':cluster_ci(z,c,'sector',seed=100+lookback+h),'date_ci95':cluster_ci(z,c,'date',seed=200+lookback+h)}
    for name in ('weak','nearweak','nearweak_price'):
        mc=f'matched_{name}_{h}d'; q=z.dropna(subset=[mc]);out[f'{name}_n']=len(q);out[f'{name}_mean']=float(q[mc].mean()) if len(q) else None;out[f'{name}_sector_ci95']=cluster_ci(q,mc,'sector',seed=300+lookback+h)
    return out


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--panel',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);args=ap.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    df=pd.read_csv(args.panel,parse_dates=['date']).sort_values(['sector','date']).copy()
    df['price_band']=np.select([df.price_score<45,df.price_score>=70],['WEAK','STRONG'],default='MID')
    for lb in (5,10,20):
        df[f'prior_internal_{lb}']=df.groupby('sector',sort=False).internal_score.shift(lb)
        df[f'delta_internal_{lb}']=df.internal_score-df[f'prior_internal_{lb}']
    periods=[('CONFIRMATION_2024_PLUS',pd.Timestamp('2024-01-01')),('RECENT_2025_PLUS',pd.Timestamp('2025-01-01'))]
    rows=[];events=[]
    for lb in (5,10,20):
        prior=df[f'prior_internal_{lb}'];delta=df[f'delta_internal_{lb}'];curweak=df.internal_score<45
        defs={
            'BOTTOM_RECOVERY_10':curweak&(prior<45)&(delta>=10),
            'DEEP_BOTTOM_RECOVERY_10':curweak&(prior<=30)&(delta>=10),
            'FALLEN_FROM_STRONG':curweak&(prior>=60),
            'PERSISTENT_WEAK_FLAT':curweak&(prior<45)&(delta.abs()<10),
            'WEAK_GETTING_WEAKER_10':curweak&(prior<45)&(delta<=-10),
        }
        for label,mask in defs.items():
            ev=attach_same_weak_controls(df,transition_events(df,mask))
            if not ev.empty:
                ev['path']=label;ev['lookback']=lb;events.append(ev)
            for period,lo in periods:
                ep=ev[ev.date>=lo].copy() if not ev.empty else ev
                for h in H:rows.append(row_stats(ep,label,period,lb,h))
    summary=pd.DataFrame(rows);all_ev=pd.concat(events,ignore_index=True) if events else pd.DataFrame()
    summary.to_csv(args.output/'weak_origin_path_summary.csv',index=False);all_ev.to_csv(args.output/'weak_origin_path_events.csv',index=False)
    stability={}
    for label,g in summary.groupby('path'):
        e=g[g.n>=8];vals=pd.to_numeric(e.mean_excess,errors='coerce').dropna();m=pd.to_numeric(e.weak_mean,errors='coerce').dropna()
        stability[label]={'eligible_cells':len(vals),'raw_positive_fraction':None if vals.empty else float((vals>0).mean()),'raw_negative_fraction':None if vals.empty else float((vals<0).mean()),'matched_weak_positive_fraction':None if m.empty else float((m>0).mean()),'matched_weak_negative_fraction':None if m.empty else float((m<0).mean())}
    report={'schema':1,'research_only':True,'design':'Audited 11-sector PIT panel. Directly distinguishes current WEAK (<45) by prior internal state: prior weak recovering vs prior STRONG (>=60) fallen into weak. Transition-only plus 20-session cooldown; same-day weak/near-current-score/price-band controls; sector/date cluster bootstrap.','stability':stability}
    (args.output/'weak_origin_path_report.json').write_text(json.dumps(safe(report),ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(stability,indent=2))

if __name__=='__main__':main()
