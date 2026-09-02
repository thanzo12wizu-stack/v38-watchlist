from __future__ import annotations

import argparse, json, math
from pathlib import Path
import numpy as np
import pandas as pd

TRAIN_END=pd.Timestamp('2021-12-31')
HOLD_START=pd.Timestamp('2022-01-03')
FEATURES=['rate_shock_z5','duration_shock_z5','real10_chg5_z252','rate_accel_z5','duration_accel_z5']


def safe(x):
    if isinstance(x,dict): return {str(k):safe(v) for k,v in x.items()}
    if isinstance(x,list): return [safe(v) for v in x]
    if isinstance(x,(np.integer,)): return int(x)
    if isinstance(x,(np.floating,float)):
        z=float(x); return z if np.isfinite(z) else None
    return x


def perf(x: pd.Series):
    x=pd.to_numeric(x,errors='coerce').fillna(0.0).astype(float)
    nav=(1+x).cumprod(); years=len(x)/252.0
    cagr=float(nav.iloc[-1]**(1/years)-1) if years>0 and nav.iloc[-1]>0 else np.nan
    vol=float(x.std(ddof=1)*math.sqrt(252)) if len(x)>1 else np.nan
    ann=float(x.mean()*252); sharpe=ann/vol if vol>0 else np.nan
    dd=nav/nav.cummax()-1; mdd=float(dd.min())
    return {'n':int(len(x)),'cagr':cagr,'maxdd':mdd,'sharpe':float(sharpe) if np.isfinite(sharpe) else None,'calmar':float(cagr/abs(mdd)) if mdd<0 else None,'final_nav':float(nav.iloc[-1])}


def attach_prior(t: pd.DataFrame,r: pd.DataFrame):
    t=t.copy(); t['date']=pd.to_datetime(t['date']); t['cutoff']=t['date']-pd.Timedelta(days=1)
    r=r.copy(); r['date']=pd.to_datetime(r['date']); r=r.sort_values('date').rename(columns={'date':'rate_date'})
    return pd.merge_asof(t.sort_values('cutoff'),r.sort_values('rate_date'),left_on='cutoff',right_on='rate_date',direction='backward',tolerance=pd.Timedelta(days=7)).sort_values('date').reset_index(drop=True)


def block_boot_delta(delta: pd.Series,reps=5000,seed=38):
    z=pd.to_numeric(delta,errors='coerce').fillna(0.0).reset_index(drop=True)
    bid=np.arange(len(z))//20; b=pd.DataFrame({'x':z,'b':bid}).groupby('b').x.agg(['sum','count'])
    keys=b.index.to_numpy(); rng=np.random.default_rng(seed); draws=np.empty(reps)
    for i in range(reps):
        k=rng.choice(keys,size=len(keys),replace=True); draws[i]=b.loc[k,'sum'].sum()/b.loc[k,'count'].sum()
    lo,hi=np.quantile(draws,[.025,.975]); p=2*min((draws<=0).mean(),(draws>=0).mean())
    return {'mean_daily':float(z.mean()),'lo':float(lo),'hi':float(hi),'p_two':float(min(1,p))}


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--tqqq',required=True); ap.add_argument('--rates',required=True); ap.add_argument('--output',required=True)
    args=ap.parse_args(); out=Path(args.output); out.mkdir(parents=True,exist_ok=True)
    t=pd.read_csv(args.tqqq); r=pd.read_csv(args.rates); t['date']=pd.to_datetime(t['date'])
    req=['target_CURRENT30','target_M30_TOUCH30_F80_D10','target_M30_TOUCH30_F100_D10','tqqq_ret_usd']
    miss=[c for c in req if c not in t.columns]
    if miss: raise RuntimeError(f'missing adopted columns {miss}')
    t=t[(t.date>=pd.Timestamp('2016-01-04'))&(t.date<=pd.Timestamp('2026-03-20'))].copy().reset_index(drop=True)
    m=attach_prior(t,r)
    current=m['target_CURRENT30'].astype(float); f80=m['target_M30_TOUCH30_F80_D10'].astype(float); f100=m['target_M30_TOUCH30_F100_D10'].astype(float)
    active=f100>current+1e-9
    reconstructed=np.where(active,np.maximum(current,0.80),current)
    maxerr=float(np.max(np.abs(reconstructed-f80.to_numpy())))
    if maxerr>1e-9: raise RuntimeError(f'F80 floor identity failed maxerr={maxerr}')
    ret=m['tqqq_ret_usd'].astype(float); base_ret=ret*f80
    rows=[]; policies={'BASE_F80':f80.to_numpy()}
    for feat in FEATURES:
        z=m[feat].astype(float)
        for cut in (.5,.75,1.0):
            for floor in (.30,.50,.65):
                target=f80.to_numpy().copy(); mask=active.to_numpy() & (z.to_numpy()>=cut); target[mask]=np.maximum(current.to_numpy()[mask],floor)
                policies[f'{feat}|TIGHT_GE_{cut}|FLOOR_{floor}']=target
            for floor in (.90,1.00):
                target=f80.to_numpy().copy(); mask=active.to_numpy() & (z.to_numpy()<=-cut); target[mask]=np.maximum(current.to_numpy()[mask],floor)
                policies[f'{feat}|EASE_LE_{-cut}|FLOOR_{floor}']=target
    periods={'TRAIN_2016_2021':m.date<=TRAIN_END,'HOLDOUT_2022_2026':m.date>=HOLD_START,'ALL':pd.Series(True,index=m.index)}
    base_by={k:perf(base_ret[mask]) for k,mask in periods.items()}
    for name,target in policies.items():
        rr=ret*target
        for period,mask in periods.items():
            p=perf(rr[mask]); b=base_by[period]
            row={'policy':name,'period':period,'affected_days':int(np.sum(np.abs(target[mask.to_numpy()]-f80.to_numpy()[mask.to_numpy()])>1e-12)),**p,
                 'delta_cagr':p['cagr']-b['cagr'],'delta_maxdd':p['maxdd']-b['maxdd'],'delta_calmar':(p['calmar']-b['calmar']) if p['calmar'] is not None and b['calmar'] is not None else None}
            if period=='HOLDOUT_2022_2026':
                boot=block_boot_delta((rr-base_ret)[mask]); row.update({f'boot_{k}':v for k,v in boot.items()})
            rows.append(row)
    df=pd.DataFrame(rows); df.to_csv(out/'policy_performance.csv',index=False)
    hold=df[(df.period=='HOLDOUT_2022_2026')&(df.policy!='BASE_F80')].sort_values(['delta_calmar','delta_cagr'],ascending=False)
    train=df[(df.period=='TRAIN_2016_2021')&(df.policy!='BASE_F80')].sort_values(['delta_calmar','delta_cagr'],ascending=False)
    result={'status':'RESEARCH_ONLY_CORRECTION','adopted_rule':'M30_TOUCH30_F80_D10','f80_definition':'max(CURRENT30 hierarchy, 0.80) only while TOUCH30 panic overlay active','active_detection':'TOUCH30_F100 > CURRENT30','f80_identity_max_error':maxerr,'active_days':int(active.sum()),'base':base_by,'top_train':train.head(10).to_dict('records'),'top_holdout':hold.head(10).to_dict('records'),'warning':'This artifact supersedes any rate conclusion previously computed with M30_RISE30_F80_D10. No production rule is changed.'}
    (out/'summary.json').write_text(json.dumps(safe(result),ensure_ascii=False,indent=2),encoding='utf-8')
    print('===TQQQ_TOUCH_RATE_CORRECTION==='); print(json.dumps(safe(result),ensure_ascii=False,separators=(',',':'))); print('===END===')

if __name__=='__main__': main()
