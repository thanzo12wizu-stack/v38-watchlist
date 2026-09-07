from __future__ import annotations

import pandas as pd
from research import nqsar_centric_broad_scan as scan

_REAL_DDV_ENTRY = 20_000_000.0
_ORIG_SCORE_MASK = scan.score_mask


def _score_mask_top12_then_ddv20(d, m, variant):
    # The broad-scan module normally applies its DDV_ENTRY inside the candidate mask.
    # For V38-comparable execution, rank the DDV10 pool first, select Top12, then
    # remove winners below DDV20 without refill.
    old = scan.DDV_ENTRY
    try:
        scan.DDV_ENTRY = 0.0
        selected = _ORIG_SCORE_MASK(d, m, variant)
    finally:
        scan.DDV_ENTRY = old
    out = []
    for s in selected:
        try:
            v = float(m['ddv'].at[d, s])
        except Exception:
            continue
        if v >= _REAL_DDV_ENTRY:
            out.append(s)
    return out


def _transition_expectancy_fixed(m, idx):
    c = m['close'].loc[idx]
    periods = {'DISCOVERY': idx[idx <= scan.DISC_END], 'CONFIRMATION': idx[idx >= scan.CONF_START]}
    shallow = m['dist_ema'].ge(-.03) & m['dist_ema'].le(.03)
    defs = {
        'WEEK_BULL_ALL': m['wb'],
        'WEEK_FRESH_BULL': m['wfresh'],
        'WEEK_YOUNG_BULL': m['wb'] & (m['wage'] <= 4) & (m['wage'] >= 1),
        'WEEK_BLUE': m['ws'] == 3,
        'WEEK_GREEN': m['ws'] == 2,
        'WEEK_BULL_DAILY_BULL': m['wb'] & m['db'],
        'WEEK_BULL_DAILY_FRESH': m['wb'] & m['dfresh'],
        'WEEK_YELLOW_DAILY_BULL': (m['ws'] == 1) & m['db'],
        'PREWEEK_DAILY_BULL': (~m['wb']) & m['wnred'] & m['db'],
        'WEEK_BULL_RSI30_RESET': m['wb'] & m['rsi_reset'],
        'WEEK_BULL_BREAKOUT20': m['wb'] & m['breakout20'],
        'WEEK_BULL_SHALLOW_EMA21': m['wb'] & ~m['dr'] & shallow,
    }
    rows = []
    for name, mask in defs.items():
        mask = mask & m['pool']
        for period, pidx in periods.items():
            for h in (5, 10, 20, 63):
                fwd = c.shift(-h) / c - 1
                z = fwd.loc[pidx].where(mask.loc[pidx]).stack(future_stack=True).replace([float('inf'), -float('inf')], pd.NA).dropna()
                z = pd.to_numeric(z, errors='coerce').dropna()
                rows.append({'signal': name, 'period': period, 'horizon': h, 'n': len(z),
                             'mean': float(z.mean()) if len(z) else None,
                             'median': float(z.median()) if len(z) else None,
                             'win': float((z > 0).mean()) if len(z) else None})
    return pd.DataFrame(rows)


scan.score_mask = _score_mask_top12_then_ddv20
scan.transition_expectancy = _transition_expectancy_fixed

if __name__ == '__main__':
    scan.main()
