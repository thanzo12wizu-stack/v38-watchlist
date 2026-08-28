from __future__ import annotations

import argparse
import json
from pathlib import Path
import pandas as pd

import audit_systematic_entry_exit as base


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default='.')
    ap.add_argument('--output', required=True)
    ap.add_argument('--start', default='2016-01-04')
    ap.add_argument('--end', default='2026-06-30')
    ap.add_argument('--asof', default='2026-08-28')
    args = ap.parse_args()

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    st = base.build_market_states(Path(args.root), args.start, args.end, args.asof)
    corr = base.correction_signals(st)
    corr['signal_date'] = pd.to_datetime(corr['signal_date'])
    corr['entry_date'] = pd.to_datetime(corr['entry_date'])
    lo, hi = pd.Timestamp(args.start), pd.Timestamp(args.end)
    corr = corr[corr.signal_date.between(lo, hi, inclusive='both')].copy()
    corr, vdiag = base.add_liquidity(corr, st)
    rows, summary = base.correction_exit_audit(corr, st)
    corr.to_csv(out/'correction_signals.csv.gz', index=False, compression='gzip')
    rows.to_csv(out/'correction_exit_rows.csv.gz', index=False, compression='gzip')
    summary.to_csv(out/'correction_exit_summary.csv', index=False)
    meta = {
        'status': 'STANDARD_CORRECTION_V2',
        'period_filter': f'{args.start}..{args.end} applied to signal_date before liquidity/exit analysis',
        'signals': int(len(corr)),
        'liquid_signals': int(corr.liquid.sum()) if len(corr) else 0,
        'volume_download': vdiag,
        'limitations': [
            'Current-universe/current-sector survivorship bias remains.',
            '2022+ is confirmation, not pristine OOS.',
            'This fixes only the date-boundary bug in the first systematic audit; entry/exit definitions are unchanged.'
        ]
    }
    (out/'summary.json').write_text(json.dumps(base.safe(meta), ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(base.safe(meta), ensure_ascii=False, indent=2))
    print(summary.to_string(index=False))


if __name__ == '__main__':
    main()
