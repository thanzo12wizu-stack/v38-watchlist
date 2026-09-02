from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
import yfinance as yf

import audit_inverse_etf_regime_scan as base
import audit_inverse_event_engine_v2 as v2
from audit_inverse_event_engine_v2_runner import fixed_extra_market

PRODUCTS = ['PSQ','QID','SQQQ']
HORIZONS = [1,3,5,10,20]


def product_outcomes(idx: pd.DatetimeIndex, start: str, end: str):
    warm = str((pd.Timestamp(start)-pd.Timedelta(days=30)).date())
    dl_end = str((pd.Timestamp(end)+pd.Timedelta(days=45)).date())
    raw = yf.download(PRODUCTS, start=warm, end=dl_end, auto_adjust=True, actions=False,
                      progress=False, threads=False, group_by='column')
    if raw.empty:
        raise RuntimeError('inverse product download empty')
    if isinstance(raw.columns, pd.MultiIndex):
        opn = raw['Open'].copy()
    else:
        raise RuntimeError('unexpected inverse product frame')
    opn.index = base.norm_idx(opn.index)
    opn = opn.reindex(idx).ffill(limit=2)
    outcomes = {}
    for p in PRODUCTS:
        z = pd.DataFrame(index=idx)
        for h in HORIZONS:
            z[f'fwd{h}'] = opn[p].shift(-(h+1))/opn[p].shift(-1)-1.0
        z['oo_ret'] = opn[p].shift(-1)/opn[p]-1.0
        outcomes[p] = z
    return outcomes, {p:int(opn[p].notna().sum()) for p in PRODUCTS}


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--features',required=True)
    ap.add_argument('--output',required=True)
    ap.add_argument('--start',default='2016-01-04')
    ap.add_argument('--end',default='2026-03-20')
    a=ap.parse_args()
    out=Path(a.output); out.mkdir(parents=True,exist_ok=True)

    feat=pd.read_csv(a.features,parse_dates=['date']).set_index('date').sort_index()
    feat.index=base.norm_idx(feat.index)
    feat=feat.loc[(feat.index>=pd.Timestamp(a.start))&(feat.index<=pd.Timestamp(a.end))].copy()
    outcomes,product_nonnull=product_outcomes(feat.index,a.start,a.end)

    extra=fixed_extra_market(feat.index,a.start,a.end)
    for c in extra.columns:
        feat[c]=extra[c]
    feat,macro_status=v2.add_macro(feat)
    hyp,thresholds=v2.build_hypotheses(feat)
    ev=v2.event_screen(hyp,outcomes,feat.index)
    st=v2.strategy_screen(hyp,feat,outcomes,feat.index)

    ev.to_csv(out/'event_screen.csv',index=False)
    st.to_csv(out/'strategy_screen.csv',index=False)
    feat.reset_index(names='date').to_csv(out/'feature_state_v2.csv.gz',index=False,compression='gzip')

    robust_ev=ev[(ev.stable_sign)&(ev.positive_subperiods>=3)].sort_values(
        ['min_train_hold','HOLDOUT_2022_2026_mean'],ascending=False)
    robust_st=st[(st.stable_positive)&(st.positive_subperiods>=3)].sort_values(
        ['min_train_hold','HOLDOUT_2022_2026_cagr'],ascending=False)

    summary={
      'status':'RESEARCH_ONLY_NO_PRODUCTION_CHANGE',
      'source':'frozen inverse_feature_state from successful run 33638677456 / artifact 9850106810',
      'sessions':len(feat),'product_nonnull':product_nonnull,'macro_status':macro_status,
      'train_thresholds':thresholds,'hypotheses':list(hyp.keys()),
      'event_rows':len(ev),'stable_event_rows':int(ev.stable_sign.sum()),
      'robust_event_rows_3of4':int(((ev.stable_sign)&(ev.positive_subperiods>=3)).sum()),
      'strategy_rows':len(st),'stable_strategy_rows':int(st.stable_positive.sum()),
      'robust_strategy_rows_3of4':int(((st.stable_positive)&(st.positive_subperiods>=3)).sum()),
      'best_events':robust_ev.head(50).to_dict('records'),
      'best_strategies':robust_st.head(50).to_dict('records'),
      'mechanics':{
        'signal':'close-known signal, entry next session open',
        'products':'actual adjusted PSQ/QID/SQQQ opens',
        'holds':'3/5/10 sessions',
        'weights':'PSQ/QID 15% or 30%; SQQQ 15% only',
        'costs':'5 or 10 bp per side round-trip charge at entry',
        'validation':'2016-2021 train + 2022-2026 holdout + four subperiod sign check; event block bootstrap/FDR',
        'production_change':'none'
      }
    }
    (out/'summary_v2.json').write_text(json.dumps(base.safe(summary),ensure_ascii=False,indent=2),encoding='utf-8')
    print('===FROZEN_V2_SUMMARY===')
    print(json.dumps(base.safe({k:v for k,v in summary.items() if k not in ['best_events','best_strategies']}),ensure_ascii=False))
    print('===BEST_EVENTS===')
    print(robust_ev.head(20).to_string(index=False))
    print('===BEST_STRATEGIES===')
    print(robust_st.head(20).to_string(index=False))

if __name__=='__main__':
    main()
