from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import numpy as np
import pandas as pd
import build_dashboard as d

ROOT=Path('.')

# Load exact validation definitions from v3 and base.
p3=Path('.github/scripts/oneoff_mc_layer_validation_v3.py')
spec=importlib.util.spec_from_file_location('v3',p3); v3=importlib.util.module_from_spec(spec); spec.loader.exec_module(v3)
base=v3.v2.base
metric_frames=v3.exact_metric_frames


def temp_from_concepts(metrics, concepts):
    raw=base.raw_from_concepts(metrics,concepts)
    return d._mc_temperature_from_raw(raw)[0]


def nearest_value(s,dt):
    x=pd.to_numeric(s,errors='coerce').dropna()
    if x.empty:return None
    ts=pd.Timestamp(dt)
    pos=x.index.searchsorted(ts)
    cand=[]
    if pos<len(x):cand.append(x.index[pos])
    if pos>0:cand.append(x.index[pos-1])
    if not cand:return None
    q=min(cand,key=lambda z:abs((pd.Timestamp(z)-ts).days))
    return str(pd.Timestamp(q).date()),float(x.loc[q])


def episode(mc,px,a,b):
    p=pd.to_numeric(px,errors='coerce').loc[a:b].dropna()
    if p.empty:return None
    trough=p.idxmin(); before=p.loc[:trough]
    peak=before.idxmax(); peak_px=float(p.loc[peak]); trough_px=float(p.loc[trough])
    m=pd.to_numeric(mc,errors='coerce').reindex(p.index)
    seg=m.loc[peak:trough]
    below=seg[seg<45].dropna()
    first_below=below.index[0] if len(below) else None
    after=m.loc[trough:]
    above=after[after>=55].dropna(); first_above=above.index[0] if len(above) else None
    return {
        'peak':str(pd.Timestamp(peak).date()),'trough':str(pd.Timestamp(trough).date()),
        'dd_pct':round((trough_px/peak_px-1)*100,2),
        'mc_peak':None if pd.isna(m.loc[peak]) else round(float(m.loc[peak]),2),
        'below45':None if first_below is None else str(pd.Timestamp(first_below).date()),
        'days_peak_to_below45':None if first_below is None else int((p.index.get_loc(first_below)-p.index.get_loc(peak))),
        'mc_trough':None if pd.isna(m.loc[trough]) else round(float(m.loc[trough]),2),
        'above55':None if first_above is None else str(pd.Timestamp(first_above).date()),
        'days_trough_to_above55':None if first_above is None else int((p.index.get_loc(first_above)-p.index.get_loc(trough))),
    }


def future_mae_by_band(mc,px,h=20):
    m=pd.to_numeric(mc,errors='coerce')
    p=pd.to_numeric(px,errors='coerce').reindex(m.index).ffill()
    arr=p.to_numpy(dtype=float)
    mae=np.full(len(p),np.nan)
    for i in range(len(p)-h):
        if not np.isfinite(arr[i]) or arr[i]==0:continue
        path=arr[i+1:i+h+1]/arr[i]-1
        if np.isfinite(path).any():mae[i]=np.nanmin(path)*100
    mae=pd.Series(mae,index=p.index)
    bands=[('<20',-np.inf,20),('20-35',20,35),('35-45',35,45),('45-55',45,55),('55-65',55,65),('65-80',65,80),('80+',80,np.inf)]
    out=[]
    for name,lo,hi in bands:
        z=mae[(m>=lo)&(m<hi)].dropna()
        out.append({'band':name,'n':len(z),'mean_mae':round(float(z.mean()),2) if len(z) else None,
                    'median_mae':round(float(z.median()),2) if len(z) else None,
                    'p10_mae':round(float(z.quantile(.10)),2) if len(z) else None,
                    'p_dd5':round(float((z<=-5).mean()*100),1) if len(z) else None,
                    'p_dd10':round(float((z<=-10).mean()*100),1) if len(z) else None})
    return out


def similarity(a,b,start='2008-01-01'):
    q=pd.concat([pd.to_numeric(a,errors='coerce').rename('a'),pd.to_numeric(b,errors='coerce').rename('b')],axis=1).loc[start:].dropna()
    gap=q.b-q.a; ag=gap.abs()
    return {'n':len(q),'corr':round(float(q.corr().iloc[0,1]),5),'mae':round(float(ag.mean()),3),
            'p95_abs':round(float(ag.quantile(.95)),3),'max_abs':round(float(ag.max()),3),
            'days_abs3':int((ag>=3).sum()),'days_abs5':int((ag>=5).sum()),'days_abs10':int((ag>=10).sum())}


def availability(metrics,dates):
    metric=metrics['ret252']
    rows={}
    layer_tickers={'Broad':d.MC_BROAD_ETFS,'Sector':d.MC_SECTOR_ETFS,'Industry':d.MC_INDUSTRY_ETFS}
    for ds in dates:
        ts=metric.index[metric.index.searchsorted(pd.Timestamp(ds))] if metric.index.searchsorted(pd.Timestamp(ds))<len(metric.index) else metric.index[-1]
        row={'date':str(pd.Timestamp(ts).date())}
        v0counts={k:int(metric.loc[ts,[x for x in v if x in metric.columns]].notna().sum()) for k,v in layer_tickers.items()}
        total=sum(v0counts.values()); row['V0_counts']=v0counts; row['V0_shares']={k:round(v/total*100,1) if total else None for k,v in v0counts.items()}
        v1counts={}
        for layer,concepts in base.LAYERS.items():
            cm=base.concept_metric(metric,concepts); v1counts[layer]=int(cm.loc[ts].notna().sum())
        total=sum(v1counts.values()); row['V1_counts']=v1counts; row['V1_shares']={k:round(v/total*100,1) if total else None for k,v in v1counts.items()}
        rows[ds]=row
    return rows


def snapshot_structure():
    snap=json.loads((ROOT/'sector_snapshot.json').read_text(encoding='utf-8'))
    out={}
    for k in ('s2i','e2j','j2rs','s2t'):
        obj=snap.get(k)
        item={'type':type(obj).__name__}
        try:item['len']=len(obj)
        except Exception:item['len']=None
        if isinstance(obj,dict):
            sample=list(obj.items())[:8]
            item['sample']=sample
            if k in ('s2i','s2t'):
                vals=[str(v) for v in obj.values() if v is not None]
                item['unique_values']=len(set(vals))
            if k=='j2rs':
                numeric=0
                for v in obj.values():
                    try:
                        if np.isfinite(float(v)):numeric+=1
                    except Exception:pass
                item['numeric_values']=numeric
        elif isinstance(obj,list): item['sample']=obj[:8]
        out[k]=item
    return out


def top_divergences(a,b,n=25,start='2008-01-01'):
    q=pd.concat([pd.to_numeric(a,errors='coerce').rename('V0'),pd.to_numeric(b,errors='coerce').rename('V1')],axis=1).loc[start:].dropna()
    q['gap']=q.V1-q.V0;q['abs']=q.gap.abs()
    return [(str(pd.Timestamp(i).date()),round(float(r.V0),2),round(float(r.V1),2),round(float(r.gap),2)) for i,r in q.nlargest(n,'abs').iterrows()]


def main():
    state=json.loads((ROOT/'state.json').read_text(encoding='utf-8'))
    hist=d._fetch_mc_long_history(asof=state.get('date'))
    c=d._mc_frame_from_macro(hist); metrics=metric_frames(c)
    prod=d.mri_frame(hist); v0=prod[0] if isinstance(prod,tuple) else prod
    allc={}
    for layer,concepts in base.LAYERS.items():
        for name,members in concepts.items():allc[f'{layer}:{name}']=members
    v1=temp_from_concepts(metrics,allc)
    # Layer temperatures are diagnostic where all three histories exist.
    lt={layer:temp_from_concepts(metrics,concepts) for layer,concepts in base.LAYERS.items()}
    v2=pd.concat(lt,axis=1).mean(axis=1,skipna=False)

    print('SIMILARITY',json.dumps({'V0_V1':similarity(v0,v1),'V0_V2':similarity(v0,v2,start='2016-01-01')},sort_keys=True))
    print('LATEST',json.dumps({'V0':round(float(v0.dropna().iloc[-1]),2),'V1':round(float(v1.dropna().iloc[-1]),2),'V2':round(float(v2.dropna().iloc[-1]),2),**{k:round(float(v.dropna().iloc[-1]),2) for k,v in lt.items()}},sort_keys=True))
    print('AVAILABILITY',json.dumps(availability(metrics,['2008-01-02','2011-01-03','2015-01-02','2018-01-02','2020-01-02','2022-01-03','2024-01-02','2026-08-25']),sort_keys=True))
    windows={'2008':['2007-10-01','2009-06-30'],'2011':['2011-04-01','2012-01-31'],'2015-16':['2015-05-01','2016-06-30'],'2018Q4':['2018-08-01','2019-04-30'],'2020':['2020-01-15','2020-08-31'],'2022':['2021-11-01','2023-03-31'],'2024':['2024-07-01','2024-10-31'],'2025':['2025-02-01','2025-07-31']}
    episodes={name:{'V0':episode(v0,c['SPY'],a,b),'V1':episode(v1,c['SPY'],a,b),'V2':episode(v2,c['SPY'],a,b)} for name,(a,b) in windows.items()}
    print('EPISODES',json.dumps(episodes,sort_keys=True))
    for h in (20,63):
        print('MAE',h,'V0',json.dumps(future_mae_by_band(v0,c['SPY'],h),sort_keys=True))
        print('MAE',h,'V1',json.dumps(future_mae_by_band(v1,c['SPY'],h),sort_keys=True))
    print('DIVERGENCES_V1_V0',json.dumps(top_divergences(v0,v1),ensure_ascii=False))
    print('SNAPSHOT_STRUCTURE',json.dumps(snapshot_structure(),ensure_ascii=False,sort_keys=True))

if __name__=='__main__':main()
