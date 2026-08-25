#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd

import market_conditions_simple_variants_15y as simple
import market_conditions_etf_equal_15y as direct
import market_conditions_deterioration_validate as prod

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'market_conditions_level_bias_15y.json'

simple.EVAL_END = pd.Timestamp('2026-08-21')
prod.START = '2009-01-01'
prod.END = '2026-08-22'
EVAL_START = pd.Timestamp('2011-01-01')
EVAL_END = pd.Timestamp('2026-08-21')


def prod_score(px: pd.DataFrame) -> pd.Series:
    m = prod.build_metrics(px)
    raw = .15*m['short'] + .55*m['medium_level'] + .20*m['long'] + .10*m['damage']
    return raw.ewm(span=2, adjust=False).mean().rename('prod_15552010')


def candidate_scores(px: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    m = simple.build(px)
    x = m[simple.METRICS]
    mom = m[['ret5','ret21','ret63','ret252']].mean(axis=1)
    breadth = m[['above10','above20','above50','above200']].mean(axis=1)
    trend = m[['ma20_gt50','ma50_gt200']].mean(axis=1)
    damage = m[['dd_score','within10']].mean(axis=1)
    raws = {
        'family_eq12': x.mean(axis=1),
        'family25': pd.concat([mom,breadth,trend,damage],axis=1).mean(axis=1),
        'robust_mean_median': .5*x.mean(axis=1) + .5*x.median(axis=1),
        'family_speed14': m[simple.METRICS+['delta20_soft','delta50_soft']].mean(axis=1),
    }
    md = direct.build_direct(px)
    raws['etf_equal12'] = md[simple.METRICS].mean(axis=1)
    raws['etf_equal_speed14'] = md[simple.METRICS+['delta20','delta50']].mean(axis=1)
    scores = pd.DataFrame({k:v.ewm(span=2,adjust=False).mean() for k,v in raws.items()})
    return scores, m


def market_context(px: pd.DataFrame, idx: pd.DatetimeIndex) -> pd.DataFrame:
    q = px['QQQ'].reindex(idx)
    s = px['SPY'].reindex(idx)
    q63 = q/q.shift(63)-1
    s63 = s/s.shift(63)-1
    qhi = q.rolling(252,min_periods=200).max()
    shi = s.rolling(252,min_periods=200).max()
    qdd = q/qhi-1
    sdd = s/shi-1
    c = pd.DataFrame({'qqq63':q63,'spy63':s63,'qqq_dd252':qdd,'spy_dd252':sdd}, index=idx)
    c['both_63_positive'] = (q63>0)&(s63>0)
    c['both_63_negative'] = (q63<0)&(s63<0)
    c['mixed_63'] = ~(c['both_63_positive']|c['both_63_negative'])
    c['both_near_5pct_high'] = (qdd>=-.05)&(sdd>=-.05)
    c['stress_10pct'] = (qdd<=-.10)|(sdd<=-.10)
    c['deep_stress_20pct'] = (qdd<=-.20)|(sdd<=-.20)
    return c


def stats(s: pd.Series) -> dict:
    z=s.dropna()
    if z.empty: return {}
    return {
        'n':int(len(z)), 'mean':float(z.mean()), 'median':float(z.median()),
        'p10':float(z.quantile(.10)), 'p25':float(z.quantile(.25)),
        'p75':float(z.quantile(.75)), 'p90':float(z.quantile(.90)),
        'pct_ge80':float((z>=80).mean()*100), 'pct_ge65':float((z>=65).mean()*100),
        'pct_lt55':float((z<55).mean()*100), 'pct_lt45':float((z<45).mean()*100),
    }


def cond_stats(s: pd.Series, ctx: pd.DataFrame) -> dict:
    out={}
    masks={
        'both_63_positive':ctx['both_63_positive'],
        'both_63_negative':ctx['both_63_negative'],
        'mixed_63':ctx['mixed_63'],
        'both_near_5pct_high':ctx['both_near_5pct_high'],
        'stress_10pct':ctx['stress_10pct'],
        'deep_stress_20pct':ctx['deep_stress_20pct'],
        'healthy_bull_combo':ctx['both_63_positive']&ctx['both_near_5pct_high'],
        'weak_combo':ctx['both_63_negative']&ctx['stress_10pct'],
    }
    for k,m in masks.items(): out[k]=stats(s.where(m))
    return out


def calibration_summary(s: pd.Series, ctx: pd.DataFrame) -> dict:
    healthy=ctx['both_63_positive']&ctx['both_near_5pct_high']
    weak=ctx['both_63_negative']&ctx['stress_10pct']
    mixed=ctx['mixed_63']
    return {
        'healthy_bull_days':int(healthy.sum()),
        'healthy_bull_pct_ge65':float((s[healthy]>=65).mean()*100),
        'healthy_bull_pct_lt55':float((s[healthy]<55).mean()*100),
        'weak_days':int(weak.sum()),
        'weak_pct_ge65':float((s[weak]>=65).mean()*100),
        'weak_pct_lt55':float((s[weak]<55).mean()*100),
        'mixed_days':int(mixed.sum()),
        'mixed_median':float(s[mixed].median()),
        'mixed_pct_ge65':float((s[mixed]>=65).mean()*100),
        'separation_healthy_minus_weak_median':float(s[healthy].median()-s[weak].median()),
    }


def yearly(s: pd.Series) -> dict:
    out={}
    for y in range(2011,2027):
        z=s[s.index.year==y].dropna()
        if len(z):
            out[str(y)]={'median':float(z.median()),'mean':float(z.mean()),'pct_ge65':float((z>=65).mean()*100),'pct_lt55':float((z<55).mean()*100)}
    return out


def main():
    px, failed = simple.download()
    px=px.loc[:EVAL_END]
    scores,_ = candidate_scores(px)
    scores.insert(0,'prod_15552010',prod_score(px))
    idx=px.loc[EVAL_START:EVAL_END].index
    scores=scores.reindex(idx)
    ctx=market_context(px,idx)
    report={}
    for name in scores.columns:
        s=scores[name]
        report[name]={
            'overall':stats(s),
            'conditional':cond_stats(s,ctx),
            'calibration':calibration_summary(s,ctx),
            'yearly':yearly(s),
            'aug21':float(s.loc[pd.Timestamp('2026-08-21')]),
        }
    out={
      'scope':{'evaluation':'2011-01-01..2026-08-21','universe57':len(simple.UNIVERSE),'failed':failed,
               'purpose':'test whether scores are structurally biased high; Aug-21 level is descriptive, not an optimization target'},
      'context_definitions':{
          'both_63_positive':'QQQ and SPY trailing 63-session returns > 0',
          'both_63_negative':'QQQ and SPY trailing 63-session returns < 0',
          'both_near_5pct_high':'QQQ and SPY each within 5% of rolling 252-session high',
          'stress_10pct':'QQQ or SPY at least 10% below rolling 252-session high',
          'healthy_bull_combo':'both_63_positive AND both_near_5pct_high',
          'weak_combo':'both_63_negative AND stress_10pct'},
      'context_days':{k:int(ctx[k].sum()) for k in ['both_63_positive','both_63_negative','mixed_63','both_near_5pct_high','stress_10pct','deep_stress_20pct']},
      'variants':report,
    }
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(out,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
