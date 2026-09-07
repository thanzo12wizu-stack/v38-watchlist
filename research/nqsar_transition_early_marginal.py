from __future__ import annotations

import argparse, json, math
from pathlib import Path
import numpy as np
import pandas as pd

from research import audit_stock_nqsar_theme30_pit as audit
from research import preimpl_core11_early1_pit as pit
from research import preimpl_core11_early1_long as lng
from research import preimpl_early1_marginal as marginal
from research import nqsar_centric_broad_scan as broad
import build_v38_sleeve_live as sleeve
import build_v38_early1_live as earlylive

START = pd.Timestamp('2016-01-04')
END = pd.Timestamp('2026-09-04')
CONF = pd.Timestamp('2022-01-03')
DDV_POOL = 10_000_000.0
DDV_ENTRY = 20_000_000.0

EARLY_VARIANTS = [
    'NQ_YELLOW_DBULL_Q21_85_ACC80',
    'NQ_YELLOW_Q21_85_ACC80',
    'NQ_YELLOW_DBULL_Q21_85',
    'NQ_YELLOW_DBULL_Q21_80_ACC70',
    'NQ_YELLOW_DBULL_Q21_85_ACC80_NEARHIGH',
    'NQ_YELLOW_DBULL_Q21_85_ACC80_MONTH_NOT_RED',
    'NQ_YELLOW_FROM_RED_DBULL_Q21_85_ACC80',
    'NQ_YELLOW_FROM_BULL_DBULL_Q21_85_ACC80',
    'NQ_YELLOW_PERSIST_DBULL_Q21_85_ACC80',
]


def finite(x):
    try: return math.isfinite(float(x))
    except Exception: return False


def safe(x):
    if isinstance(x, dict): return {str(k): safe(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)): return [safe(v) for v in x]
    if isinstance(x, np.integer): return int(x)
    if isinstance(x, (np.floating, float)):
        z = float(x); return z if math.isfinite(z) else None
    if isinstance(x, pd.Timestamp): return str(x.date())
    return x


def pct(v: pd.DataFrame, mask: pd.DataFrame) -> pd.DataFrame:
    return v.where(mask & v.notna()).rank(axis=1, pct=True, method='average') * 100.0


def build_features(ohlcv, early_excluded, mx):
    c, v = ohlcv['close'], ohlcv['volume']
    ddv = c * v.rolling(20, min_periods=20).mean()
    pool = (c >= 5) & (ddv >= DDV_POOL)
    ex = [s for s in early_excluded if s in pool.columns]
    if ex: pool.loc[:, ex] = False
    q21 = pct(c / c.shift(21) - 1, pool)
    q63 = pct(c / c.shift(63) - 1, pool)
    q189 = pct(c / c.shift(189) - 1, pool)
    acc = pct(q21 - q21.shift(20), pool)
    high63 = pct(c / c.shift(1).rolling(63, min_periods=40).max(), pool)
    score = .50 * q21 + .25 * high63 + .25 * acc
    prior20 = ohlcv['high'].shift(1).rolling(20, min_periods=15).max()
    nearhigh = c / prior20 - 1 >= -.05

    wh, wl, wc = broad.period_ohlc(ohlcv['high'], ohlcv['low'], c, 'W-FRI')
    print('EXACT WEEKLY STATE FOR TRANSITIONS', flush=True)
    ws0 = broad.exact_states(wh, wl, wc, 30)
    ws = broad.to_daily(ws0, c.index).astype(np.int8)
    prev_ws = broad.to_daily(ws0.shift(1), c.index).astype(np.int8)
    return {
        'close': c, 'ddv': ddv, 'pool': pool, 'q21': q21, 'q63': q63, 'q189': q189,
        'acc': acc, 'high63': high63, 'score': score, 'nearhigh': nearhigh,
        'ws0': ws0, 'ws': ws, 'prev_ws': prev_ws,
        'day_bull': mx['day_bull'], 'month_red': mx['month_red'],
    }


def early_mask(d, f, variant):
    pool = f['pool'].loc[d].fillna(False)
    ws = f['ws'].loc[d]
    pws = f['prev_ws'].loc[d]
    db = f['day_bull'].loc[d].fillna(False)
    q21 = f['q21'].loc[d]
    acc = f['acc'].loc[d]
    base = pool & (f['ddv'].loc[d] >= DDV_ENTRY) & (ws == 1)
    if variant == 'NQ_YELLOW_DBULL_Q21_85_ACC80':
        return base & db & (q21 >= 85) & (acc >= 80)
    if variant == 'NQ_YELLOW_Q21_85_ACC80':
        return base & (q21 >= 85) & (acc >= 80)
    if variant == 'NQ_YELLOW_DBULL_Q21_85':
        return base & db & (q21 >= 85)
    if variant == 'NQ_YELLOW_DBULL_Q21_80_ACC70':
        return base & db & (q21 >= 80) & (acc >= 70)
    if variant == 'NQ_YELLOW_DBULL_Q21_85_ACC80_NEARHIGH':
        return base & db & (q21 >= 85) & (acc >= 80) & f['nearhigh'].loc[d].fillna(False)
    if variant == 'NQ_YELLOW_DBULL_Q21_85_ACC80_MONTH_NOT_RED':
        return base & db & (q21 >= 85) & (acc >= 80) & ~f['month_red'].loc[d].fillna(True)
    if variant == 'NQ_YELLOW_FROM_RED_DBULL_Q21_85_ACC80':
        return base & (pws == 0) & db & (q21 >= 85) & (acc >= 80)
    if variant == 'NQ_YELLOW_FROM_BULL_DBULL_Q21_85_ACC80':
        return base & (pws >= 2) & db & (q21 >= 85) & (acc >= 80)
    if variant == 'NQ_YELLOW_PERSIST_DBULL_Q21_85_ACC80':
        return base & (pws == 1) & db & (q21 >= 85) & (acc >= 80)
    raise KeyError(variant)


def early_rows(d, f, variant):
    mask = early_mask(d, f, variant)
    z = pd.to_numeric(f['score'].loc[d].where(mask), errors='coerce').dropna().sort_values(ascending=False)
    return [{'ticker': str(s), 'score': float(v), 'rank': i + 1} for i, (s, v) in enumerate(z.head(40).items())]


def simulate(idx, mx, nq, e_existing, f, policy):
    first = pd.Timestamp(idx[0])
    state = {'status': 'READY', 'asof': str(first.date()), 'cash': 1.0, 'positions': [],
             'pending': {'full_exits': [], 'partial25': [], 'entries': []}}
    eq, snaps = [], []
    for d0 in idx:
        d = pd.Timestamp(d0)
        c = pit.companion(d, mx, {}, nq, e_existing, True)
        if policy == 'CORE12_NO_EARLY':
            c = dict(c); c['early1'] = {'status': 'READY', 'entry_allowed_now': False, 'candidates': []}
        elif policy == 'CORE11_EARLY1':
            pass
        elif policy in EARLY_VARIANTS:
            c = dict(c)
            mode = str((c.get('market') or {}).get('mode') or 'STOP')
            c['early1'] = {'status': 'READY', 'entry_allowed_now': mode in {'ATTACK', 'SELECTIVE'},
                           'candidates': early_rows(d, f, policy)}
        else:
            raise KeyError(policy)
        state = sleeve.advance_normal(state, c, str(d.date()), mx['open'], mx['close'])
        if policy == 'CORE12_NO_EARLY':
            state = marginal.strip_early_and_optionally_fill_core(state, c, True)
        eq.append((d, float(state['nav'])))
        snaps.append((d, json.dumps(state.get('pending', {}), sort_keys=True, default=str)))
    return {'equity': pd.Series(dict(eq), dtype=float), 'pending_snapshots': snaps}


def event_counts(res):
    out = {'CORE': 0, 'EARLY': 0}
    for _, txt in res['pending_snapshots']:
        p = json.loads(txt)
        for x in p.get('entries', []):
            sl = str(x.get('sleeve') or 'CORE'); out[sl] = out.get(sl, 0) + 1
    return out


def transition_expectancy(f, idx):
    c = f['close'].loc[idx]
    ws0 = f['ws0']
    names = {0: 'RED', 1: 'YELLOW', 2: 'GREEN', 3: 'BLUE'}
    periods = {'DISCOVERY': idx[idx <= pd.Timestamp('2021-12-31')], 'CONFIRMATION': idx[idx >= CONF]}
    filters = {
        'ALL': lambda d: f['pool'].loc[d],
        'DAILY_BULL': lambda d: f['pool'].loc[d] & f['day_bull'].loc[d],
        'RS21_80': lambda d: f['pool'].loc[d] & (f['q21'].loc[d] >= 80),
        'RS21_85': lambda d: f['pool'].loc[d] & (f['q21'].loc[d] >= 85),
        'ACC80': lambda d: f['pool'].loc[d] & (f['acc'].loc[d] >= 80),
        'RS63_85': lambda d: f['pool'].loc[d] & (f['q63'].loc[d] >= 85),
        'RS189_85': lambda d: f['pool'].loc[d] & (f['q189'].loc[d] >= 85),
        'DBULL_RS21_85_ACC80': lambda d: f['pool'].loc[d] & f['day_bull'].loc[d] & (f['q21'].loc[d] >= 85) & (f['acc'].loc[d] >= 80),
    }
    fwd = {h: c.shift(-h) / c - 1 for h in (5, 10, 20, 63)}
    rows = []
    for a in range(4):
        for b in range(4):
            if a == b: continue
            ev0 = (ws0.shift(1) == a) & (ws0 == b)
            dates = [d for d in ws0.index if d in c.index]
            for period, pidx in periods.items():
                pset = set(pd.DatetimeIndex(pidx))
                for fil, fn in filters.items():
                    pieces = {h: [] for h in fwd}
                    n_events = 0
                    for d in dates:
                        if d not in pset: continue
                        ev = ev0.loc[d].fillna(False)
                        if not ev.any(): continue
                        mask = ev & fn(d).fillna(False)
                        if not mask.any(): continue
                        n_events += int(mask.sum())
                        for h in fwd:
                            z = pd.to_numeric(fwd[h].loc[d].where(mask), errors='coerce').dropna()
                            if len(z): pieces[h].extend(z.tolist())
                    for h, vals in pieces.items():
                        z = pd.Series(vals, dtype=float)
                        rows.append({'transition': f'{names[a]}->{names[b]}', 'period': period, 'filter': fil,
                                     'horizon': h, 'n': len(z), 'event_n': n_events,
                                     'mean': float(z.mean()) if len(z) else None,
                                     'median': float(z.median()) if len(z) else None,
                                     'win': float((z > 0).mean()) if len(z) else None})
    return pd.DataFrame(rows)


def preweek_conversion(f, idx):
    wb = f['ws'] >= 2
    rows = []
    for v in EARLY_VARIANTS:
        for period, pidx in [('DISCOVERY', idx[idx <= pd.Timestamp('2021-12-31')]), ('CONFIRMATION', idx[idx >= CONF])]:
            total = 0
            hit = {5: 0, 10: 0, 20: 0}
            for d in pidx:
                m = early_mask(pd.Timestamp(d), f, v)
                syms = list(m.index[m.fillna(False)])
                if not syms: continue
                i = idx.get_loc(pd.Timestamp(d))
                total += len(syms)
                for h in hit:
                    future = idx[i + 1:min(len(idx), i + h + 1)]
                    if len(future) == 0: continue
                    anybull = wb.loc[future, syms].any(axis=0)
                    hit[h] += int(anybull.sum())
            for h in hit:
                rows.append({'variant': v, 'period': period, 'horizon_sessions': h, 'signals': total,
                             'bull_conversions': hit[h], 'conversion_rate': hit[h] / total if total else None})
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--root', default='.'); ap.add_argument('--output', required=True); ap.add_argument('--batch-size', type=int, default=100)
    a = ap.parse_args(); root = Path(a.root); out = root / a.output; out.mkdir(parents=True, exist_ok=True)
    symbols, bio = audit.load_universe(root / 'universe.csv')
    allowed = earlylive._industry_symbols(root / 'industry_map.json')
    early_excluded = set(bio)
    if allowed: early_excluded.update(set(symbols) - set(allowed))
    warm = str((START - pd.Timedelta(days=1600)).date()); end = '2026-09-05'
    print('DOWNLOAD', flush=True)
    ohlcv, diag = audit.download_ohlcv(symbols, warm, end, a.batch_size)
    if diag['coverage'] < .85: raise RuntimeError(diag)
    print('BUILD CORE INPUTS', flush=True)
    mx = audit.build_stock_inputs(ohlcv, bio, END)
    e = pit.early_inputs(ohlcv['close'], ohlcv['volume'], early_excluded)
    print('BUILD NQSAR-EARLY FEATURES', flush=True)
    f = build_features(ohlcv, early_excluded, mx)
    nq = audit.market_nqsar(str((START - pd.Timedelta(days=120)).date()), end).reindex(mx['close'].index).ffill(limit=2)
    idx = mx['close'].index[(mx['close'].index >= START) & (mx['close'].index <= END)]
    policies = ['CORE12_NO_EARLY', 'CORE11_EARLY1'] + EARLY_VARIANTS
    results, rows = {}, []
    for i, p in enumerate(policies, 1):
        print(f'SIM {i}/{len(policies)} {p}', flush=True)
        r = simulate(idx, mx, nq, e, f, p); results[p] = r
        sl = lng.slices(r['equity']); counts = event_counts(r)
        rows.append({'variant': p,
                     **{f'full_{k}': v for k, v in sl['full'].items()},
                     **{f'conf_{k}': v for k, v in sl['confirmation_2022_plus'].items()},
                     **counts})
        r['equity'].rename('equity').to_csv(out / f'equity_{p}.csv')
    metrics = pd.DataFrame(rows); metrics.to_csv(out / 'metrics.csv', index=False)
    trans = transition_expectancy(f, idx); trans.to_csv(out / 'transition_expectancy.csv', index=False)
    conv = preweek_conversion(f, idx); conv.to_csv(out / 'preweek_conversion.csv', index=False)
    base12 = results['CORE12_NO_EARLY']['equity']; old = results['CORE11_EARLY1']['equity']
    boots = []
    for p in policies[1:]:
        boots.append({'variant': p,
                      'vs_core12_full_block20': lng.blockprob(results[p]['equity'], base12),
                      'vs_core12_conf_block20': lng.blockprob(results[p]['equity'], base12, CONF),
                      'vs_existing_early1_full_block20': lng.blockprob(results[p]['equity'], old),
                      'vs_existing_early1_conf_block20': lng.blockprob(results[p]['equity'], old, CONF)})
    pd.DataFrame(boots).to_csv(out / 'bootstrap.csv', index=False)
    summary = {
        'method': 'Exact production advance_normal; Weekly-priority Core11 plus one Early slot; direct Early1 vs NQSAR-Early marginal comparison; signals close -> next open; Early D10/direct promotion unchanged',
        'universe': diag, 'analysis_start': str(START.date()), 'analysis_end': str(END.date()),
        'policies': policies,
        'limitations': ['no historical Theme30 in long test; verified PIT taxonomy begins 2026-06-22', 'transaction-cost stress is handled by broad architecture scan, not injected into production-parity sleeve engine'],
        'metrics': rows,
    }
    (out / 'summary.json').write_text(json.dumps(safe(summary), ensure_ascii=False, indent=2))
    print('DONE', json.dumps(safe(summary), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
