#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

import market_conditions_compare as base


def pct_participation(mask: pd.DataFrame) -> pd.Series:
    return base.participation(mask) * 100.0


def new_mc_direct(px: pd.DataFrame, weights: tuple[float,float,float,float]) -> pd.DataFrame:
    c = px.reindex(columns=base.available(base.MC_UNIVERSE, px))
    ma10=c.rolling(10).mean(); ma20=c.rolling(20).mean(); ma50=c.rolling(50).mean(); ma200=c.rolling(200).mean()
    p={}
    p['ret5']=pct_participation(c/c.shift(5)-1>0)
    p['above10']=pct_participation(c>ma10)
    p['above20']=pct_participation(c>ma20)
    short=pd.concat([p['ret5'],p['above10'],p['above20']],axis=1).mean(axis=1)
    p['ret21']=pct_participation(c/c.shift(21)-1>0)
    p['ret63']=pct_participation(c/c.shift(63)-1>0)
    p['above50']=pct_participation(c>ma50)
    p['ma20_gt_50']=pct_participation(ma20>ma50)
    p['ma50_rising']=pct_participation(ma50>ma50.shift(20))
    medium=pd.concat([p[k] for k in ['ret21','ret63','above50','ma20_gt_50','ma50_rising']],axis=1).mean(axis=1)
    p['above200']=pct_participation(c>ma200)
    p['ma50_gt_200']=pct_participation(ma50>ma200)
    long=pd.concat([p['above200'],p['ma50_gt_200']],axis=1).mean(axis=1)
    hi252=c.rolling(252,min_periods=200).max(); dd=c/hi252-1
    med_dd=base.stratified_median(dd)
    dd_score=base.linear_score(med_dd,-.30,-.05)*100
    within10=pct_participation(dd>=-.10)
    damage=pd.concat([dd_score,within10],axis=1).mean(axis=1)
    ws,wm,wl,wd=weights
    raw=short*ws+medium*wm+long*wl+damage*wd
    score=raw.ewm(span=2,adjust=False).mean()
    out=pd.DataFrame({'score':score,'raw':raw,'short':short,'medium':medium,'long':long,'damage':damage,'median_dd':med_dd*100})
    for k,v in p.items(): out[k]=v
    return out


def hysteresis_changes(score: pd.Series, margin: float=2.5) -> dict:
    bounds=[20,35,45,55,65,80]
    names=base.BAND_ORDER
    s=score.dropna()
    if s.empty: return {'changes_per_year':None,'changes':0,'occupancy':{}}
    def idx_for(x):
        return names.index(base.band(x))
    cur=idx_for(float(s.iloc[0])); labels=[]; changes=0
    for x in s:
        x=float(x)
        while cur < len(names)-1 and x >= bounds[cur] + margin:
            cur += 1; changes += 1
        while cur > 0 and x < bounds[cur-1] - margin:
            cur -= 1; changes += 1
        labels.append(names[cur])
    years=max((s.index[-1]-s.index[0]).days/365.25,1)
    vc=pd.Series(labels).value_counts(normalize=True)*100
    return {'changes_per_year':changes/years,'changes':changes,'occupancy':{k:float(vc.get(k,0)) for k in names}}


def contemporaneous(score: pd.Series, qqq: pd.Series) -> dict:
    d=pd.DataFrame({'s':score,'q':qqq}).dropna()
    ret63=d['q']/d['q'].shift(63)-1
    dd=d['q']/d['q'].rolling(252,min_periods=200).max()-1
    return {'corr_qqq_63d':float(d['s'].corr(ret63)), 'corr_qqq_52w_dd':float(d['s'].corr(dd))}


def main():
    px,failed=base.download_prices(); qqq=px['QQQ']
    eval_mask=(px.index>=pd.Timestamp(base.EVAL_START))&(px.index<=pd.Timestamp('2026-08-21'))
    candidates={
        'v1_scaled_20403010':base.new_mc(px),
        'v2_direct_20403010':new_mc_direct(px,(.20,.40,.30,.10)),
        'v2_direct_25452010':new_mc_direct(px,(.25,.45,.20,.10)),
        'v2_direct_25501510':new_mc_direct(px,(.25,.50,.15,.10)),
    }
    reference={'current_mri_standardized':base.current_mri_standardized(px),'oratnek_like':base.oratnek_like(px)}
    events=base.crash_events(qqq.loc[eval_mask])
    result={'scope':{'failed_tickers':failed,'evaluation':'2016-01-01..2026-08-21','note':'v2 uses raw participation percentage directly; no 30%-70% rescaling.'},'candidates':{},'references':{}}
    for group,items in [('candidates',candidates),('references',reference)]:
        for name,frame in items.items():
            s=frame['score'].where(eval_mask)
            bt,h=base.forward_stats(s,qqq)
            h.update(contemporaneous(s,qqq)); h['hysteresis_2p5']=hysteresis_changes(s,2.5)
            clean=s.dropna(); latest=clean.iloc[-1]
            result[group][name]={
                'summary':h,
                'latest':{'score':float(latest),'band':base.band(float(latest)),'delta5':float(latest-clean.iloc[-6])},
                'band_stats':bt.to_dict(orient='records'),
                'event_lags':base.event_lags(s,qqq,events),
                'nqsar':base.nq_overlap({name:s}).get(name,{}),
            }
            if name.startswith('v'):
                result[group][name]['latest_components']={k:float(frame[k].dropna().iloc[-1]) for k in ['short','medium','long','damage','median_dd']}
    Path('market_conditions_compare_v2_results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    compact={}
    for name,x in result['candidates'].items():
        ev=x['event_lags']; compact[name]={
            'latest':x['latest'], 'components':x.get('latest_components'),
            'mean_abs_daily_change':x['summary']['mean_abs_daily_change'],
            'raw_changes_per_year':x['summary']['regime_changes_per_year'],
            'hysteresis_changes_per_year':x['summary']['hysteresis_2p5']['changes_per_year'],
            'corr_qqq_63d':x['summary']['corr_qqq_63d'], 'corr_qqq_52w_dd':x['summary']['corr_qqq_52w_dd'],
            'bull_worst20':x['summary']['bull_fwd20_worst_pct'],'bear_worst20':x['summary']['bear_fwd20_worst_pct'],
            'avg_bear_lag':float(np.mean([e['bear_sessions_from_peak'] for e in ev if e['bear_sessions_from_peak'] is not None])),
            'avg_recovery_lag':float(np.mean([e['recovery_sessions_from_trough'] for e in ev if e['recovery_sessions_from_trough'] is not None])),
            'nqsar':x['nqsar']}
    result2={'compact':compact,'references':{n:{'latest':x['latest'],'mean_abs_daily_change':x['summary']['mean_abs_daily_change'],
               'raw_changes_per_year':x['summary']['regime_changes_per_year'],'hysteresis_changes_per_year':x['summary']['hysteresis_2p5']['changes_per_year'],
               'corr_qqq_63d':x['summary']['corr_qqq_63d'],'corr_qqq_52w_dd':x['summary']['corr_qqq_52w_dd'],
               'nqsar':x['nqsar']} for n,x in result['references'].items()}}
    Path('market_conditions_compare_v2_compact.json').write_text(json.dumps(result2,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result2,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
