from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def cagr(r: np.ndarray) -> float:
    r = np.asarray(r, float)
    eq = float(np.prod(1.0 + r))
    years = max((len(r) - 1) / TRADING_DAYS, 1.0 / TRADING_DAYS)
    return float(eq ** (1.0 / years) - 1.0)


def mdd(r: np.ndarray) -> float:
    eq = np.cumprod(1.0 + np.asarray(r, float))
    peak = np.maximum.accumulate(eq)
    return float(np.min(eq / peak - 1.0))


def sharpe(r: np.ndarray) -> float:
    r = np.asarray(r, float)
    sd = float(np.std(r, ddof=1))
    return float(np.sqrt(TRADING_DAYS) * np.mean(r) / sd) if sd > 0 else float('nan')


def drawdown_episodes(r: np.ndarray, dates: pd.Series, fill: np.ndarray) -> pd.DataFrame:
    eq = np.cumprod(1.0 + r)
    peak = np.maximum.accumulate(eq)
    episodes = []
    peak_i = 0
    in_dd = False
    for i in range(1, len(eq)):
        if eq[i] >= peak[i - 1] - 1e-12:
            if in_dd:
                seg = np.arange(peak_i, i + 1)
                trough_i = int(seg[np.argmin(eq[seg] / eq[peak_i] - 1.0)])
                episodes.append((peak_i, trough_i, i, float(eq[trough_i] / eq[peak_i] - 1.0)))
                in_dd = False
            peak_i = i
        else:
            in_dd = True
    if in_dd:
        seg = np.arange(peak_i, len(eq))
        trough_i = int(seg[np.argmin(eq[seg] / eq[peak_i] - 1.0)])
        episodes.append((peak_i, trough_i, len(eq) - 1, float(eq[trough_i] / eq[peak_i] - 1.0)))
    rows = []
    for p, t, rec, dd in sorted(episodes, key=lambda x: x[3])[:8]:
        rows.append({
            'peak_date': str(dates.iloc[p].date()),
            'trough_date': str(dates.iloc[t].date()),
            'recovery_or_end_date': str(dates.iloc[rec].date()),
            'base_drawdown': dd,
            'fill_days_peak_to_trough': int(fill[p:t+1].sum()),
            'peak_idx': p,
            'trough_idx': t,
        })
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--input-dir', required=True)
    ap.add_argument('--output', required=True)
    ap.add_argument('--bootstrap-samples', type=int, default=5000)
    ap.add_argument('--block', type=int, default=20)
    ap.add_argument('--seed', type=int, default=20260901)
    args = ap.parse_args()

    inp = Path(args.input_dir)
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    base = pd.read_csv(inp / 'daily_base.csv.gz', compression='gzip')
    cand = pd.read_csv(inp / 'daily_selective_fill_no_zero_override.csv.gz', compression='gzip')
    base['date'] = pd.to_datetime(base['date']).dt.normalize()
    cand['date'] = pd.to_datetime(cand['date']).dt.normalize()
    if not base['date'].equals(cand['date']):
        raise RuntimeError('date mismatch')
    dates = base['date']
    rb = base['return_10bp'].to_numpy(float)
    rc = cand['return_10bp'].to_numpy(float)
    fill = cand['extra_tqqq_vs_base'].to_numpy(float) > 1e-12
    n = len(rb)

    rng = np.random.default_rng(args.seed)
    starts = np.arange(n - args.block + 1)
    boot = np.empty((args.bootstrap_samples, 3), float)
    for k in range(args.bootstrap_samples):
        idx = []
        while len(idx) < n:
            s = int(rng.choice(starts))
            idx.extend(range(s, s + args.block))
        idx = np.asarray(idx[:n], int)
        boot[k, 0] = cagr(rc[idx]) - cagr(rb[idx])
        boot[k, 1] = mdd(rc[idx]) - mdd(rb[idx])
        boot[k, 2] = sharpe(rc[idx]) - sharpe(rb[idx])
    boot_df = pd.DataFrame(boot, columns=['cagr_delta', 'mdd_delta', 'sharpe_delta'])
    boot_df.to_csv(out / 'bootstrap_samples.csv.gz', index=False, compression='gzip')

    yearly = []
    for year in sorted(dates.dt.year.unique()):
        m = dates.dt.year.eq(year).to_numpy()
        br = float(np.prod(1.0 + rb[m]) - 1.0)
        cr = float(np.prod(1.0 + rc[m]) - 1.0)
        yearly.append({
            'year': int(year), 'sessions': int(m.sum()), 'fill_days': int(fill[m].sum()),
            'base_return': br, 'candidate_return': cr, 'delta_pp': cr - br,
            'relative_log_alpha': float(np.log1p(rc[m]).sum() - np.log1p(rb[m]).sum()),
        })
    yearly_df = pd.DataFrame(yearly)
    yearly_df.to_csv(out / 'yearly.csv', index=False)

    loyo = []
    for year in sorted(dates.dt.year.unique()):
        m = dates.dt.year.ne(year).to_numpy()
        loyo.append({'excluded_year': int(year), 'cagr_delta': cagr(rc[m]) - cagr(rb[m])})
    loyo_df = pd.DataFrame(loyo)
    loyo_df.to_csv(out / 'leave_one_year_out.csv', index=False)

    rel = np.log1p(rc) - np.log1p(rb)
    pos = np.sort(rel[rel > 0])[::-1]
    pos_total = float(pos.sum())
    concentration = []
    for topn in (1, 3, 5, 10, 20):
        concentration.append({
            'top_n': topn,
            'share_of_positive_relative_log_alpha': float(pos[:topn].sum() / pos_total) if pos_total else 0.0,
            'share_of_net_relative_log_alpha': float(pos[:topn].sum() / rel.sum()) if rel.sum() else 0.0,
        })
    conc_df = pd.DataFrame(concentration)
    conc_df.to_csv(out / 'alpha_concentration.csv', index=False)

    ordered = np.where(rel > 0)[0]
    ordered = ordered[np.argsort(rel[ordered])[::-1]]
    best_day_stress = []
    for topn in (1, 3, 5, 10):
        rs = rc.copy()
        rs[ordered[:topn]] = rb[ordered[:topn]]
        best_day_stress.append({
            'removed_best_positive_days': topn,
            'candidate_cagr_after_removal': cagr(rs),
            'cagr_delta_vs_base': cagr(rs) - cagr(rb),
            'terminal_relative_vs_base': float(np.prod(1.0 + rs) / np.prod(1.0 + rb) - 1.0),
        })
    stress_df = pd.DataFrame(best_day_stress)
    stress_df.to_csv(out / 'best_day_removal_stress.csv', index=False)

    dd = drawdown_episodes(rb, dates, fill)
    eqb = np.cumprod(1.0 + rb)
    eqc = np.cumprod(1.0 + rc)
    for i, row in dd.iterrows():
        p, t = int(row['peak_idx']), int(row['trough_idx'])
        dd.loc[i, 'candidate_same_span_return'] = float(eqc[t] / eqc[p] - 1.0)
        dd.loc[i, 'candidate_min_drawdown_same_span'] = float(np.min(eqc[p:t+1] / eqc[p] - 1.0))
    dd.drop(columns=['peak_idx', 'trough_idx']).to_csv(out / 'major_drawdowns.csv', index=False)

    active_delta = rc[fill] - rb[fill]
    q = lambda a, x: float(np.quantile(a, x))
    summary = {
        'status': 'SELECTIVE_FILL_NO_ZERO_OVERRIDE_ROBUSTNESS',
        'coverage': {'start': str(dates.min().date()), 'end': str(dates.max().date()), 'sessions': n},
        'fixed_candidate': 'SELECTIVE_FILL_NO_ZERO_OVERRIDE',
        'method': {'paired_moving_block_bootstrap': True, 'block_sessions': args.block, 'samples': args.bootstrap_samples, 'seed': args.seed, 'threshold_tuning': False},
        'actual': {
            'base_cagr': cagr(rb), 'candidate_cagr': cagr(rc), 'cagr_delta': cagr(rc) - cagr(rb),
            'base_mdd': mdd(rb), 'candidate_mdd': mdd(rc), 'mdd_delta': mdd(rc) - mdd(rb),
            'base_sharpe': sharpe(rb), 'candidate_sharpe': sharpe(rc), 'sharpe_delta': sharpe(rc) - sharpe(rb),
            'fill_days': int(fill.sum()),
            'fill_day_mean_return_delta': float(active_delta.mean()),
            'fill_day_median_return_delta': float(np.median(active_delta)),
            'fill_day_outperform_rate': float(np.mean(active_delta > 0)),
            'terminal_relative_wealth_vs_base': float(np.exp(rel.sum()) - 1.0),
        },
        'bootstrap': {
            'cagr_delta_q025': q(boot[:,0], .025), 'cagr_delta_q05': q(boot[:,0], .05), 'cagr_delta_median': q(boot[:,0], .5), 'cagr_delta_q95': q(boot[:,0], .95), 'cagr_delta_q975': q(boot[:,0], .975),
            'prob_cagr_delta_gt_0': float(np.mean(boot[:,0] > 0)),
            'mdd_delta_q025': q(boot[:,1], .025), 'mdd_delta_median': q(boot[:,1], .5), 'mdd_delta_q975': q(boot[:,1], .975),
            'prob_candidate_mdd_better': float(np.mean(boot[:,1] > 0)), 'prob_candidate_mdd_worse': float(np.mean(boot[:,1] < 0)),
            'sharpe_delta_q025': q(boot[:,2], .025), 'sharpe_delta_median': q(boot[:,2], .5), 'sharpe_delta_q975': q(boot[:,2], .975),
            'prob_sharpe_delta_gt_0': float(np.mean(boot[:,2] > 0)),
        },
        'yearly': {
            'years_better': int((yearly_df.delta_pp > 1e-12).sum()),
            'years_worse': int((yearly_df.delta_pp < -1e-12).sum()),
            'years_equal': int((yearly_df.delta_pp.abs() <= 1e-12).sum()),
            'largest_positive_year': int(yearly_df.loc[yearly_df.delta_pp.idxmax(), 'year']),
            'largest_positive_year_delta': float(yearly_df.delta_pp.max()),
            'largest_negative_year': int(yearly_df.loc[yearly_df.delta_pp.idxmin(), 'year']),
            'largest_negative_year_delta': float(yearly_df.delta_pp.min()),
        },
        'leave_one_year_out': {'min_cagr_delta': float(loyo_df.cagr_delta.min()), 'max_cagr_delta': float(loyo_df.cagr_delta.max()), 'all_positive': bool((loyo_df.cagr_delta > 0).all())},
        'concentration': {f'top_{int(r.top_n)}_share_positive_alpha': float(r.share_of_positive_relative_log_alpha) for _, r in conc_df.iterrows()},
        'best_day_removal_stress': {str(int(r.removed_best_positive_days)): {'cagr_delta_vs_base': float(r.cagr_delta_vs_base), 'terminal_relative_vs_base': float(r.terminal_relative_vs_base)} for _, r in stress_df.iterrows()},
    }
    (out / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary, indent=2), flush=True)
    print('\nYEARLY\n', yearly_df.to_string(index=False), flush=True)
    print('\nLEAVE_ONE_YEAR_OUT\n', loyo_df.to_string(index=False), flush=True)
    print('\nMAJOR_DRAWDOWNS\n', dd.drop(columns=['peak_idx', 'trough_idx']).to_string(index=False), flush=True)


if __name__ == '__main__':
    main()
