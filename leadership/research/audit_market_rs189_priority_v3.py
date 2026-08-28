from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

import audit_market_rs189_context as ctx
import audit_rsi_reset_portfolio as portfolio
import audit_rsi_reset_robust as market_base

SLOT = 0.029
HOLD = 20
DISC_END = pd.Timestamp('2021-12-31')
CONF_START = pd.Timestamp('2022-01-03')


def safe(x):
    return ctx.safe(x)


def masks(z: pd.DataFrame) -> dict[str, pd.Series]:
    return {
        'BASE': pd.Series(True, index=z.index),
        'MC20_UP1': (z.mc >= 20) & z.mc_up1.astype(bool),
        'MC20_UP1_SEC50': (z.mc >= 20) & z.mc_up1.astype(bool) & (z.sector_rs63_pct >= 50),
        'MC20_UP1_SEC60': (z.mc >= 20) & z.mc_up1.astype(bool) & (z.sector_rs63_pct >= 60),
        'MC20_UP1_SEC70': (z.mc >= 20) & z.mc_up1.astype(bool) & (z.sector_rs63_pct >= 70),
        'MC20_50_SEC60': (z.mc >= 20) & (z.mc < 50) & (z.sector_rs63_pct >= 60),
    }


def priority(z: pd.DataFrame, mode: str) -> pd.Series:
    if mode == 'RS189':
        return (100.0 - z.rs189_signal) * 100.0 + z.rsi_min_reset
    if mode == 'RSI':
        return z.rsi_min_reset * 100.0 + (100.0 - z.rs189_signal)
    if mode == 'SECTOR':
        return (100.0 - z.sector_rs63_pct) * 10000.0 + (100.0 - z.rs189_signal) * 100.0 + z.rsi_min_reset
    raise ValueError(mode)


def max1(z: pd.DataFrame, market: dict, mask: pd.Series, mode: str, start: pd.Timestamp, end: pd.Timestamp) -> dict:
    cl, op, active = market['close'], market['open'], market['active']
    ema21 = cl.ewm(span=21, adjust=False).mean()
    cal = cl.index[(cl.index >= start) & (cl.index <= end)]
    q = z.loc[mask & z.entry_date.isin(cal)].copy()
    q['theme'] = q.symbol
    q['rank_priority'] = priority(q, mode)
    m, _ = portfolio.simulate(cal, op, cl, active, ema21, q, SLOT, 1, HOLD, 'full', False)
    return {'input_signals': int(len(q)), **m}


def prep_theme(path: Path) -> pd.DataFrame:
    t = pd.read_csv(path, compression='gzip', parse_dates=['entry_date','signal_date'])
    t = t[(t.kind == 'RISE') & (t.threshold == 30) & t.RS63_TOP3.astype(bool) & t.signal_top3.astype(bool)].copy()
    t['source'] = 'theme'; t['rank_priority'] = t.rank63
    return t[['entry_date','signal_date','symbol','theme','source','rank_priority','rsi_signal']]


def prep_market(z: pd.DataFrame, mask: pd.Series, mode: str) -> pd.DataFrame:
    q = z.loc[mask].copy()
    q['source'] = 'market'; q['theme'] = q.symbol; q['rank_priority'] = priority(q, mode)
    return q[['entry_date','signal_date','symbol','theme','source','rank_priority','rsi_signal']]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default='.')
    ap.add_argument('--market-trades', required=True)
    ap.add_argument('--theme-trades', required=True)
    ap.add_argument('--output', required=True)
    ap.add_argument('--asof', default='2026-08-28')
    args = ap.parse_args()
    root, out = Path(args.root), Path(args.output); out.mkdir(parents=True, exist_ok=True)
    tr = pd.read_csv(args.market_trades, compression='gzip', parse_dates=['touch_date','signal_date','entry_date'])
    market = market_base.rebuild_market(root, '2016-01-04', '2026-06-30', 6000, 75, 3)
    z = ctx.attach_context(tr, market['close'], root, args.asof, '2010-01-01')
    mm = masks(z); theme = prep_theme(Path(args.theme_trades))
    periods = [('DISCOVERY', pd.Timestamp('2016-01-04'), DISC_END), ('CONFIRM', CONF_START, pd.Timestamp('2026-06-30'))]
    modes = ('RS189','RSI','SECTOR')
    rows=[]; comb=[]
    cl, op = market['close'], market['open']
    for period, start, end in periods:
        cal = cl.index[(cl.index>=start)&(cl.index<=end)]
        th = theme[theme.entry_date.isin(cal)].copy()
        base_comb = ctx.simulate_combined_preempt(cal, op, cl, th, th.iloc[0:0])
        comb.append({'condition':'THEME_ONLY','priority':'NONE','period':period,**base_comb})
        for cond, mask in mm.items():
            for mode in modes:
                m = max1(z, market, mask, mode, start, end)
                rows.append({'condition':cond,'priority':mode,'period':period,**m})
                mk = prep_market(z, mask, mode); mk = mk[mk.entry_date.isin(cal)]
                cm = ctx.simulate_combined_preempt(cal, op, cl, th, mk)
                comb.append({'condition':cond,'priority':mode,'period':period,**cm})
    p = pd.DataFrame(rows); c = pd.DataFrame(comb)
    p.to_csv(out/'priority_max1.csv',index=False); c.to_csv(out/'priority_combined.csv',index=False)
    cs = c.set_index(['condition','priority','period'])
    theme_d = cs.loc[('THEME_ONLY','NONE','DISCOVERY')]; theme_c = cs.loc[('THEME_ONLY','NONE','CONFIRM')]
    ranked=[]
    for cond in mm:
        for mode in modes:
            pd_ = p[(p.condition==cond)&(p.priority==mode)&(p.period=='DISCOVERY')].iloc[0]
            pc = p[(p.condition==cond)&(p.priority==mode)&(p.period=='CONFIRM')].iloc[0]
            cd = cs.loc[(cond,mode,'DISCOVERY')]; cc = cs.loc[(cond,mode,'CONFIRM')]
            theme_ok = int(cd.accepted_theme)==int(theme_d.accepted_theme) and int(cc.accepted_theme)==int(theme_c.accepted_theme)
            both_add = float(cd.cagr)>float(theme_d.cagr) and float(cc.cagr)>float(theme_c.cagr)
            max1_ok = float(pd_.cagr)>0 and float(pc.cagr)>0
            dd_ok = (float(cd.mdd)>=float(theme_d.mdd)-0.015) and (float(cc.mdd)>=float(theme_c.mdd)-0.015)
            ranked.append({'condition':cond,'priority':mode,'passes':bool(theme_ok and both_add and max1_ok and dd_ok),
                           'disc_max1_cagr':float(pd_.cagr),'conf_max1_cagr':float(pc.cagr),
                           'disc_max1_mdd':float(pd_.mdd),'conf_max1_mdd':float(pc.mdd),
                           'disc_combined_delta':float(cd.cagr-theme_d.cagr),'conf_combined_delta':float(cc.cagr-theme_c.cagr),
                           'disc_mdd_delta':float(cd.mdd-theme_d.mdd),'conf_mdd_delta':float(cc.mdd-theme_c.mdd),
                           'conf_market_accepted':int(cc.accepted_market),'conf_preemptions':int(cc.market_preemptions)})
    passing=[x for x in ranked if x['passes']]
    passing=sorted(passing,key=lambda x:(x['conf_combined_delta']+x['disc_combined_delta'],x['conf_max1_cagr']),reverse=True)
    result={'status':'MARKET_RS189_PRIORITY_AUDIT_V3','selected':passing[0] if passing else None,'passing':passing,'all':ranked,
            'contract':'No new RSI/RS189 grid. Fixed conditions from V1/V2; only same-day candidate priority RS189 vs RSI depth vs sector strength.',
            'limitations':['Current-universe/current-classification survivorship bias remains.','2022+ is confirmation, not pristine OOS.','No tax model.']}
    (out/'summary.json').write_text(json.dumps(safe(result),ensure_ascii=False,indent=2))
    print(json.dumps(safe(result),ensure_ascii=False,indent=2))

if __name__=='__main__': main()
