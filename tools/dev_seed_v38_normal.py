from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import pandas as pd


def _px(frame, date, sym, fallback=None):
    try:
        x = float(frame.at[date, sym])
        if math.isfinite(x) and x > 0:
            return x
    except Exception:
        pass
    return fallback


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default='.')
    ap.add_argument('--research-path', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--start', default='2016-01-04')
    ap.add_argument('--end', default='2026-08-28')
    ap.add_argument('--max-tickers', type=int, default=6000)
    ap.add_argument('--batch-size', type=int, default=75)
    args = ap.parse_args()

    sys.path.insert(0, args.research_path)
    import audit_ordinary_stock_market_mode_robustness as base
    import audit_ordinary_stock_exit_trail as ex
    import audit_ordinary_stock_theme_leave_one_out as loo

    root = Path(args.root)
    meta, matrices = ex.build_inputs_ext(root, args.start, args.end, args.max_tickers, args.batch_size)
    print('BUILD strict LOO research context', flush=True)
    peer_ctx = loo.build_leave_one_out_scores(root, matrices)
    idx = meta['analysis_idx']
    opens, closes = matrices['open'], matrices['close']
    breadth, nq = meta['breadth'], meta['nq']
    cash = 1.0
    pos: dict[str, dict] = {}
    red_run = 0

    def close_position(sym, price):
        nonlocal cash
        p = pos.pop(sym)
        cash += p['shares'] * price

    for i, d0 in enumerate(idx):
        d = pd.Timestamp(d0)
        prev = None if i == 0 else pd.Timestamp(idx[i - 1])
        if prev is not None:
            color = str(nq.at[prev, 'nq_color']) if prev in nq.index and pd.notna(nq.at[prev, 'nq_color']) else ''
            red_run = red_run + 1 if color == 'Red' else 0
            red_force = color == 'Red' and red_run >= 1
            if red_force:
                for sym in list(pos):
                    opx = _px(opens, d, sym, _px(closes, prev, sym, pos[sym]['entry_price']))
                    if opx is not None:
                        close_position(sym, opx)
            else:
                for sym in list(pos):
                    p = pos[sym]
                    pc = _px(closes, prev, sym, p['entry_price'])
                    if pc is None:
                        continue
                    if (not p['partial_done']) and pc >= p['entry_price'] * 1.24:
                        opx = _px(opens, d, sym, pc)
                        if opx is not None:
                            sold = p['shares'] * 0.25
                            cash += sold * opx
                            p['shares'] -= sold
                            p['partial_done'] = True
                    stop = max(p['entry_price'] * 0.92, p['peak_close'] * 0.70)
                    if pc <= stop:
                        opx = _px(opens, d, sym, pc)
                        if opx is not None:
                            close_position(sym, opx)

            b = float(breadth.loc[prev]) if prev in breadth.index and pd.notna(breadth.loc[prev]) else float('nan')
            bucket = base.breadth_bucket(b)
            bull = color in ('Blue', 'Green')
            cap = base.N_PORT if bull and bucket == 2 else 4 if bull and bucket == 1 else 0
            if (not red_force) and cap > 0 and len(pos) < cap:
                candidates = ex.ranked_candidates(prev, matrices, peer_ctx, bucket, base.N_PORT)
                nav_open = cash
                for sym, p in pos.items():
                    opx = _px(opens, d, sym, _px(closes, prev, sym, p['entry_price']))
                    if opx is not None:
                        nav_open += p['shares'] * opx
                slot_cash = nav_open / base.N_PORT
                for sym, c in candidates:
                    if len(pos) >= cap or cash <= 0:
                        break
                    if sym in pos:
                        continue
                    opx = _px(opens, d, sym, _px(closes, prev, sym, None))
                    if opx is None:
                        continue
                    alloc = min(slot_cash, cash)
                    if alloc <= 1e-10:
                        break
                    cash -= alloc
                    pos[sym] = {
                        'shares': alloc / opx,
                        'entry_price': opx,
                        'entry_date': str(d.date()),
                        'peak_close': opx,
                        'partial_done': False,
                    }

        for sym, p in pos.items():
            cp = _px(closes, d, sym, _px(opens, d, sym, p['entry_price']))
            if cp is not None:
                p['peak_close'] = max(float(p['peak_close']), float(cp))

    asof = pd.Timestamp(idx[-1])
    gross = 0.0
    positions = []
    for sym, p in sorted(pos.items()):
        cp = _px(closes, asof, sym, p['entry_price'])
        if cp is None:
            raise RuntimeError(f'final close missing for {sym}')
        mark = p['shares'] * cp
        gross += mark
        positions.append({
            'symbol': sym,
            'shares': float(p['shares']),
            'entry_price': float(p['entry_price']),
            'entry_date': p['entry_date'],
            'peak_close': float(p['peak_close']),
            'partial_done': bool(p['partial_done']),
            'close': float(cp),
            'mark': float(mark),
        })
    nav = cash + gross
    payload = {
        'schema': 'v38-normal-sleeve-seed-1',
        'asof': str(asof.date()),
        'status': 'READY',
        'strategy': 'PEAK30_PART25_R3',
        'source_research_commit': '02c6746e65fe688bcad68d3d76f27fef344b7cab',
        'seed_policy': 'FULL_RESEARCH_SIM_THROUGH_ASOF; DAILY_INCREMENTAL_AFTER_SEED',
        'cash': float(cash),
        'nav': float(nav),
        'gross_value': float(gross),
        'desired_pct': float(gross / nav * 100.0 if nav > 0 else 0.0),
        'position_count': len(positions),
        'positions': positions,
    }
    Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(payload, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
