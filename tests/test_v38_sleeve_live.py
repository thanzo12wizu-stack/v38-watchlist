import json
from pathlib import Path

import numpy as np
import pandas as pd

from build_v38_sleeve_live import (
    _merge_desired_into_tqqq,
    _normal_from_seed,
    advance_normal,
    build_reset_trades_and_monitor,
    simulate_reset,
    wilder_rsi,
)


def test_wilder_rsi_reaches_oversold_and_recovers():
    idx = pd.date_range('2026-01-01', periods=40, freq='B')
    x = pd.Series(list(np.linspace(100, 70, 25)) + list(np.linspace(69, 80, 15)), index=idx)
    r = wilder_rsi(pd.DataFrame({'AAA': x}), 14)['AAA']
    assert r.min() <= 30
    assert r.iloc[-1] > r.min()


def test_normal_seed_and_one_session_advance_preserve_next_open_semantics():
    seed = {
        'schema': 'v38-normal-sleeve-seed-1', 'status': 'READY', 'asof': '2026-08-28',
        'cash': 0.5, 'source_research_commit': 'x', 'seed_policy': 'test',
        'positions': [{'symbol': 'AAA', 'shares': 0.005, 'entry_price': 100.0,
                       'entry_date': '2026-08-28', 'peak_close': 100.0, 'partial_done': False}],
    }
    normal = _normal_from_seed(seed)
    idx = pd.to_datetime(['2026-08-28', '2026-08-31'])
    op = pd.DataFrame({'AAA': [100.0, 99.0]}, index=idx)
    cl = pd.DataFrame({'AAA': [100.0, 91.0]}, index=idx)
    companion0 = {'market': {'mode': 'STOP', 'new_entry_limit': 0}, 'ranking': {}, 'candidates': []}
    normal = advance_normal(normal, companion0, '2026-08-28', op, cl)
    assert normal['pending']['full_exits'] == []
    # 91 is below the initial -8% close stop; it becomes a next-open pending exit.
    normal = advance_normal(normal, companion0, '2026-08-31', op, cl)
    assert normal['pending']['full_exits'][0]['symbol'] == 'AAA'
    assert normal['position_count'] == 1


def test_merge_desired_never_substitutes_missing_with_zero(tmp_path):
    p = tmp_path / 'tqqq.json'
    p.write_text(json.dumps({'asof': '2026-08-31', 'live_generation_status': 'READY'}))
    _merge_desired_into_tqqq(p, '2026-08-31', None, 0.0, 'DATA REQUIRED', 'missing normal')
    got = json.loads(p.read_text())
    assert got['normal_stock_desired_pct'] is None
    assert got['reset_desired_pct'] is None
    assert got['sleeve_live_status'] == 'DATA REQUIRED'


def test_reset_monitor_only_contains_active_theme_top3_windows(monkeypatch):
    idx = pd.date_range('2026-01-02', periods=115, freq='B')
    syms = ['AAA', 'BBB', 'CCC']
    # Price shape: long history, then AAA sells off into RSI30 and starts recovering.
    base = np.linspace(50, 100, len(idx))
    close = pd.DataFrame({
        'AAA': base.copy(),
        'BBB': base * 0.95,
        'CCC': base * 0.90,
    }, index=idx)
    close.loc[idx[-12:-2], 'AAA'] = np.linspace(100, 55, 10)
    close.loc[idx[-2:], 'AAA'] = [54, 56]
    open_ = close.copy()

    # Isolate reset state-machine semantics from cross-sectional math.
    def fake_snap(_close, d, _s2t):
        i = idx.get_loc(d)
        pct = {'Theme': 90.0 if i >= 83 else 60.0}
        breadth = {'Theme': 80.0}
        members = {'Theme': syms}
        # AAA is always top3 because Theme has exactly 3 members.
        stock63 = pd.Series({'AAA': 3.0, 'BBB': 2.0, 'CCC': 1.0})
        return pct, breadth, members, stock63

    monkeypatch.setattr('build_v38_sleeve_live._theme_snapshot', fake_snap)
    history = {'taxonomy_snapshots': [{'effective_asof': '2026-01-02', 's2t': {s: ['Theme'] for s in syms}}]}
    trades, monitor = build_reset_trades_and_monitor(close, open_, history, str(idx[-1].date()))
    assert monitor
    aaa = next(row for row in monitor if row['symbol'] == 'AAA')
    assert aaa['theme'] == 'Theme'
    assert aaa['day0_rank63'] <= 3
    assert 'rsi14' in aaa and 'distance_to_30' in aaa
    assert 0 <= aaa['days_remaining'] <= 20
    # Any emitted trade obeys the adopted next-open structure.
    if not trades.empty:
        assert (pd.to_datetime(trades['entry_date']) > pd.to_datetime(trades['signal_date'])).all()


def test_reset_simulator_caps_four_positions_and_two_per_theme():
    idx = pd.date_range('2026-01-02', periods=30, freq='B')
    syms = ['A','B','C','D','E']
    op = pd.DataFrame(10.0, index=idx, columns=syms)
    cl = op.copy()
    entry = idx[5]
    trades = pd.DataFrame([
        {'entry_date': entry, 'symbol': 'A', 'theme': 'T1', 'rank_priority': 1, 'rsi_signal': 31},
        {'entry_date': entry, 'symbol': 'B', 'theme': 'T1', 'rank_priority': 2, 'rsi_signal': 32},
        {'entry_date': entry, 'symbol': 'C', 'theme': 'T1', 'rank_priority': 3, 'rsi_signal': 33},
        {'entry_date': entry, 'symbol': 'D', 'theme': 'T2', 'rank_priority': 1, 'rsi_signal': 31},
        {'entry_date': entry, 'symbol': 'E', 'theme': 'T3', 'rank_priority': 1, 'rsi_signal': 31},
    ])
    out = simulate_reset(cl, op, trades, str(idx[10].date()))
    assert out['position_count'] == 4
    assert sum(p['theme'] == 'T1' for p in out['positions']) == 2
    assert out['desired_pct'] > 0
