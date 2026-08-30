import numpy as np
import pandas as pd

from tqqq_live_engine import build_4h_bars, current30_trace, stage56_overlay


def _base(n=80):
    return {
        "mc": np.full(n, 50.0), "nq": np.full(n, 2, np.int8),
        "panic": np.zeros(n, bool), "a50": np.ones(n, bool), "a63": np.ones(n, bool),
        "a200": np.ones(n, bool), "a252": np.ones(n, bool), "gte10": np.ones(n, bool),
        "lte21": np.zeros(n, bool), "s50a": np.zeros(n, float), "dd10": np.zeros(n, float),
    }


def test_current30_normal_is_30_and_mc_lock_is_zero_until_recovery():
    b = _base(80)
    out = current30_trace(b)
    assert np.allclose(out["target"], 0.30)

    b2 = _base(80)
    b2["mc"][20:30] = 20
    b2["mc"][30:] = 36
    out2 = current30_trace(b2)
    assert out2["mc_lock"][20]
    assert out2["target"][20] == 0.0
    assert not out2["mc_lock"][30]
    assert out2["target"][30] == 0.30


def test_stage56_f80_is_floor_not_fixed_target_and_executes_next_open():
    n = 50
    b = _base(n)
    b["s50a"][10] = -0.6
    b["dd10"][10] = -0.03
    touch = np.zeros(n, bool)
    touch[12] = True
    vx = np.full(n, 14.0)
    vx[10] = 25.0
    underlying = np.full(n, 0.30)
    underlying[13] = 0.90
    out = stage56_overlay(b, vx, touch, underlying=underlying)
    assert out["entered_close"][12]
    assert out["active_at_open"][12] is np.False_ or not bool(out["active_at_open"][12])
    assert bool(out["active_at_open"][13])
    assert out["target"][12] == 0.80
    assert out["target"][13] == 0.90


def test_stage56_mc_below20_blocks_entry_and_active_mc_drop_sets_exit_pending():
    n = 50
    b = _base(n)
    b["s50a"][5] = -0.6
    b["dd10"][5] = -0.03
    vx = np.full(n, 14.0); vx[5] = 25.0
    touch = np.zeros(n, bool); touch[7] = True
    b["mc"][7] = 19
    blocked = stage56_overlay(b, vx, touch)
    assert not blocked["entered_close"][7]

    b["mc"][7] = 25
    b["mc"][9] = 19
    live = stage56_overlay(b, vx, touch)
    assert live["entered_close"][7]
    assert live["exited_close"][9]
    assert bool(live["active_at_open"][9])
    assert not bool(live["active_after_close"][9])


def test_4h_builder_uses_stage51_rth_slots():
    idx = pd.date_range("2026-08-28 09:30", "2026-08-28 15:55", freq="5min", tz="America/New_York")
    close = np.linspace(100, 102, len(idx))
    raw = pd.DataFrame({"Open": close, "High": close + .1, "Low": close - .1, "Close": close}, index=idx)
    bars = build_4h_bars(raw)
    assert len(bars) == 2
    assert bars.iloc[0]["slot"] == 0
    assert bars.iloc[1]["slot"] == 1
    assert bars.iloc[0]["n"] == 48
    assert bars.iloc[1]["n"] == 30
