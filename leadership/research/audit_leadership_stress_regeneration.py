from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import audit_leadership_cycle as lc
import audit_leadership_combinations as combo
import audit_ordinary_stock_market_mode_robustness as base

DISC_END=pd.Timestamp('2021-12-31')
CONF_START=pd.Timestamp('2022-01-03')


def safe(v: Any) -> Any:
    if isinstance(v,dict): return {str(k):safe(x) for k,x in v.items()}
    if isinstance(v,(list,tuple)): return [safe(x) for x in v]
    if isinstance(v,np.integer): return int(v)
    if isinstance(v,(np.floating,float)):
        x=float(v); return x if math.isfinite(x) else None
    if isinstance(v,pd.Timestamp): return v.isoformat()
    return v


def eventize(mask: pd.Series,cooldown:int)->list[pd.Timestamp]:
    m=mask.fillna(False).astype(bool); cross=m&~m.shift(1,fill_value=False)
    out=[]; last=-10**9
    for i,v in enumerate(cross.to_numpy(bool)):
        if v and i-last>=cooldown: out.append(pd.Timestamp(cross.index[i])); last=i
    return out


def boot(a:np.ndarray,b:np.ndarray,seed:int,reps:int=20000)->dict[str,Any]:
    ok=np.isfinite(a)&np.isfinite(b); d=np.asarray(a[ok]-b[ok],float)
    if len(d)<3:return {'n':int(len(d))}
    rng=np.random.default_rng(seed); means=d[rng.integers(0,len(d),(reps,len(d)))].mean(axis=1)
    return {'n':int(len(d)),'mean_delta':float(d.mean()),'median_delta':float(np.median(d)),
            'ci025':float(np.quantile(means,.025)),'ci05':float(np.quantile(means,.05)),
            'ci95':float(np.quantile(means,.95)),'ci975':float(np.quantile(means,.975)),
            'prob_delta_gt0':float((means>0).mean())}


def nearest_pairs(frame:pd.DataFrame,dates:list[pd.Timestamp],mask:pd.Series,year_window:int|None)->list[tuple[pd.Timestamp,pd.Timestamp,float]]:
    feats=['breadth50','qqq_ret20_back','f1','f2','f3','leader_temp']; used=set(); out=[]
    for d in dates:
        r=frame.loc[d]
        pool=frame.loc[(frame['split']==r['split'])&(frame['mode']==r['mode'])&(frame['nqsar']==r['nqsar'])&(~mask.reindex(frame.index).fillna(False))&(frame['f2']<.40)].copy()
        if year_window is not None: pool=pool.loc[(pool.index.year>=d.year-year_window)&(pool.index.year<=d.year+year_window)]
        p=frame.index.get_loc(d); keep=[c for c in pool.index if abs(int(frame.index.get_loc(c))-int(p))>40 and c not in used]
        pool=pool.loc[keep]
        if pool.empty: continue
        sf=frame.loc[frame['split']==r['split'],feats]; scale=(sf.quantile(.75)-sf.quantile(.25)).replace(0,np.nan)
        dist=(((pool[feats]-r[feats]).divide(scale))**2).sum(axis=1,skipna=False).dropna()
        if dist.empty: continue
        c=pd.Timestamp(dist.idxmin()); used.add(c); out.append((d,c,float(dist.loc[c])))
    return out


def report(frame:pd.DataFrame,mask:pd.Series,qqq:pd.DataFrame,spy:pd.DataFrame,nq:pd.Series,cooldown:int,year_window:int|None,seed:int)->dict[str,Any]:
    dates=eventize(mask,cooldown); result={'cooldown':cooldown,'year_window':year_window,'splits':{}}
    for split in ('DISCOVERY','CONFIRMATION'):
        ds=[d for d in dates if frame.at[d,'split']==split]; pairs=nearest_pairs(frame,ds,mask,year_window)
        ed=[p[0] for p in pairs]; cd=[p[1] for p in pairs]
        eo=combo.outcome_table(ed,qqq,spy,nq).set_index('signal_date') if ed else pd.DataFrame(); co=combo.outcome_table(cd,qqq,spy,nq).set_index('signal_date') if cd else pd.DataFrame()
        z={'n_events':len(ds),'n_pairs':len(pairs),'event_dates':[str(d.date()) for d in ds],'mean_match_distance':float(np.mean([p[2] for p in pairs])) if pairs else None}
        if pairs:
            for h in (20,40,60):
                for col in (f'qqq_ret_{h}',f'spy_ret_{h}',f'excess_{h}',f'qqq_mdd_{h}'):
                    av=pd.to_numeric(eo.reindex(ed).get(col),errors='coerce').to_numpy(float); bv=pd.to_numeric(co.reindex(cd).get(col),errors='coerce').to_numpy(float)
                    z[col]=boot(av,bv,seed+h+len(col))
            er=pd.to_numeric(eo.reindex(ed).get('qqq_ret_60'),errors='coerce').dropna(); ex=pd.to_numeric(eo.reindex(ed).get('excess_60'),errors='coerce').dropna(); mdd=pd.to_numeric(eo.reindex(ed).get('qqq_mdd_60'),errors='coerce').dropna()
            z['event_ret60_mean']=float(er.mean()) if len(er) else None; z['event_ret60_median']=float(er.median()) if len(er) else None; z['event_ret60_win_rate']=float((er>0).mean()) if len(er) else None
            z['event_excess60_mean']=float(ex.mean()) if len(ex) else None; z['event_mdd60_mean']=float(mdd.mean()) if len(mdd) else None
        result['splits'][split]=z
    return result


def submat(matrices:dict[str,pd.DataFrame],fraction:float)->dict[str,pd.DataFrame]:
    cols=list(matrices['close'].columns); keep=[]
    for c in cols:
        u=int(hashlib.sha256(str(c).encode()).hexdigest()[:12],16)/float(16**12-1)
        if u<fraction: keep.append(c)
    return {k:v.loc[:,[c for c in keep if c in v.columns]].copy() for k,v in matrices.items() if isinstance(v,pd.DataFrame)}


def make_masks(frame:pd.DataFrame,lookback:int=40,temp_cut:float=15.0,f3_cut:float=.60)->dict[str,pd.Series]:
    rt=combo.recent_low(frame['leader_temp'],temp_cut,lookback); rf3=combo.recent_high(frame['f3'],f3_cut,lookback)
    rec=combo.cross_below(frame['f2'],.40); gate=frame['gate_on']
    return {'TEMP_ONLY':rt&rec&gate,'F3_ONLY':rf3&rec&gate,'STRESS_OR':(rt|rf3)&rec&gate,'STRESS_AND':(rt&rf3)&rec&gate}


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--root',default='.'); ap.add_argument('--output',required=True); ap.add_argument('--analysis-start',default='2016-01-04'); ap.add_argument('--analysis-end',default='2026-08-31'); ap.add_argument('--max-tickers',type=int,default=6000); ap.add_argument('--batch-size',type=int,default=75); a=ap.parse_args()
    root=Path(a.root); out=root/a.output; out.mkdir(parents=True,exist_ok=True)
    print('BUILD INPUTS',flush=True); meta,matrices=base.build_inputs(root,a.analysis_start,a.analysis_end,a.max_tickers,a.batch_size)
    idx=pd.DatetimeIndex(meta['analysis_idx']); breadth=meta['breadth'].reindex(idx); nq=meta['nq'].reindex(idx)['nq_color'].astype(object).ffill(limit=1)
    print('BUILD LEADERSHIP',flush=True); sig=lc.build_leadership_series(matrices).reindex(idx)
    market=lc.download_market(str((pd.Timestamp(a.analysis_start)-pd.Timedelta(days=10)).date()),str((pd.Timestamp(a.analysis_end)+pd.Timedelta(days=120)).date())); qqq=market['QQQ']; spy=market['SPY'].reindex(qqq.index).ffill(limit=1)
    frame=combo.add_market_features(sig,breadth,nq,qqq); masks=make_masks(frame)
    reports={}
    print('CORE COMPARISONS',flush=True)
    for i,(name,mask) in enumerate(masks.items()):
        for cd in (20,40):
            reports[f'{name}_CD{cd}_SPLITMATCH']=report(frame,mask,qqq,spy,nq,cd,None,20264000+i*100+cd)
            reports[f'{name}_CD{cd}_YEAR2MATCH']=report(frame,mask,qqq,spy,nq,cd,2,20265000+i*100+cd)
    print('OR SENSITIVITY',flush=True); sensitivity=[]
    for lb in (20,40,60):
        for tc in (10.0,15.0,20.0):
            for f3c in (.40,.60):
                mask=make_masks(frame,lb,tc,f3c)['STRESS_OR']
                rr=report(frame,mask,qqq,spy,nq,20,2,int(20266000+lb+tc*10+f3c*100))
                for split in ('DISCOVERY','CONFIRMATION'):
                    z=rr['splits'][split]; q=z.get('qqq_ret_60',{}); x=z.get('excess_60',{}); d=z.get('qqq_mdd_60',{})
                    sensitivity.append({'lookback':lb,'temp_cut':tc,'f3_cut':f3c,'split':split,'n_events':z.get('n_events'),'n_pairs':z.get('n_pairs'),'event_ret60_mean':z.get('event_ret60_mean'),'event_ret60_win_rate':z.get('event_ret60_win_rate'),'qqq60_delta':q.get('mean_delta'),'qqq60_ci025':q.get('ci025'),'qqq60_ci05':q.get('ci05'),'qqq60_ci95':q.get('ci95'),'qqq60_ci975':q.get('ci975'),'qqq60_prob_gt0':q.get('prob_delta_gt0'),'excess60_delta':x.get('mean_delta'),'excess60_ci05':x.get('ci05'),'excess60_ci95':x.get('ci95'),'mdd60_delta':d.get('mean_delta'),'mdd60_ci05':d.get('ci05'),'mdd60_ci95':d.get('ci95')})
    print('MEMBERSHIP',flush=True); membership=[]; full_dates=set(eventize(masks['STRESS_OR'],20))
    for frac in (.50,.75,1.0):
        if frac==1.0: fsig=sig; ncols=matrices['close'].shape[1]
        else:
            sm=submat(matrices,frac); ncols=sm['close'].shape[1]; fsig=lc.build_leadership_series(sm).reindex(idx)
        ff=combo.add_market_features(fsig,breadth,nq,qqq); fm=make_masks(ff)['STRESS_OR']; fdates=eventize(fm,20); fs=set(fdates); jac=len(fs&full_dates)/len(fs|full_dates) if fs|full_dates else None
        oo=combo.outcome_table(fdates,qqq,spy,nq)
        for split in ('DISCOVERY','CONFIRMATION'):
            ds=[d for d in fdates if ff.at[d,'split']==split]; oz=oo.loc[pd.to_datetime(oo['signal_date']).isin(ds)] if len(oo) else pd.DataFrame(); er=pd.to_numeric(oz.get('qqq_ret_60'),errors='coerce').dropna() if len(oz) else pd.Series(dtype=float); ex=pd.to_numeric(oz.get('excess_60'),errors='coerce').dropna() if len(oz) else pd.Series(dtype=float)
            membership.append({'fraction':frac,'symbols':ncols,'split':split,'n_events':len(ds),'ret60_n':len(er),'ret60_mean':float(er.mean()) if len(er) else None,'ret60_win_rate':float((er>0).mean()) if len(er) else None,'excess60_mean':float(ex.mean()) if len(ex) else None,'event_date_jaccard_vs_full':jac})
    pd.DataFrame(sensitivity).to_csv(out/'stress_or_sensitivity.csv',index=False); pd.DataFrame(membership).to_csv(out/'stress_or_membership.csv',index=False)
    result={'status':'STRESS_TO_REGENERATION_AUDIT','definition':{'stress':'prior 40 sessions contain Leader Temperature <=15 OR F3 >=60%','reacceleration':'F2 crosses from >=40% to <40%','market_confirmation':'NQSAR Blue/Green and stock 50MA Breadth >=50'},'coverage':{'selected':meta.get('selected'),'downloaded':meta.get('downloaded')},'reports':reports,'membership':membership,'warning':'Retrospectively discovered combination. Robustness evidence only; not pristine prospective OOS and not an authorization to change production.'}
    (out/'summary_stress_regeneration.json').write_text(json.dumps(safe(result),ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps(safe(result),ensure_ascii=False,indent=2),flush=True)

if __name__=='__main__': main()
