import math

import numpy as np
import pandas as pd

from build_v38_tqqq_live import (
    build_4h_bars,
    current30_trace,
    stage56_trace,
    wilder_rsi,
)


def base_data(n=40):
    return {
        "ret": np.zeros(n),
        "mc": np.full(n, 50.0),
        "nq": np.full(n, 2, dtype=np.int8),  # Green
        "panic": np.zeros(n, bool),
        "a50": np.ones(n, bool),
        "a63": np.ones(n, bool),
        "a200": np.ones(n, bool),
        "a252": np.ones(n, bool),
        "gte10": np.ones(n, bool),
        "lte21": np.zeros(n, bool),
        "s50a": np.zeros(n),
        "dd10": np.zeros(n),
    }


def test_current30_is_hierarchy_not_constant_30_percent():
    data = base_data(40)
    data["mc"][10] = 20.0  # MC lock -> target zero on this completed close.
    data["mc"][20] = 65.0
    data["nq"][20] = 3  # healthy Blue strong-bull condition -> target 100%.
    trace = current30_trace(data)
    assert math.isclose(trace["target"][5], 0.30)
    assert math.isclose(trace["target"][10], 0.0)
    assert math.isclose(trace["target"][20], 1.0)


def test_current30_panic_buy_can_override_risk_lock_exactly_as_stage34():
    data = base_data(30)
    data["mc"][10] = 20.0
    data["panic"][10] = True
    data["s50a"][10] = -2.1
    trace = current30_trace(data)
    assert trace["risklock"][10]
    assert math.isclose(trace["target"][10], 1.0)


def test_stage56_f80_is_floor_and_preserves_higher_current30_target():
    data = base_data(20)
    data["s50a"][:] = -0.6
    data["dd10"][:] = -0.03
    current = current30_trace(data)
    current["target"][:] = 0.90
    touch = np.zeros(20, bool)
    touch[2] = True
    out = stage56_trace(data, np.full(20, 25.0), touch, current)
    assert out["active"][2]
    assert math.isclose(out["target"][2], 0.90)


def test_stage56_d10_and_mc57_exit():
    data = base_data(20)
    data["s50a"][:] = -0.6
    data["dd10"][:] = -0.03
    current = current30_trace(data)
    touch = np.zeros(20, bool)
    touch[0] = True
    out = stage56_trace(data, np.full(20, 25.0), touch, current)
    assert out["active"][0]
    assert out["active"][9]
    assert not out["active"][10]

    data2 = base_data(10)
    data2["s50a"][:] = -0.6
    data2["dd10"][:] = -0.03
    data2["mc"][3] = 19.9
    touch2 = np.zeros(10, bool)
    touch2[0] = True
    out2 = stage56_trace(data2, np.full(10, 25.0), touch2, current30_trace(data2))
    assert out2["active"][2]
    assert not out2["active"][3]


def test_stage56_seed_day_is_age_zero_and_30_is_inclusive():
    data = base_data(35)
    data["s50a"][:] = 0
    data["dd10"][:] = 0
    data["s50a"][0] = -0.6
    data["dd10"][0] = -0.03
    touch = np.zeros(35, bool)
    touch[30] = True
    out = stage56_trace(data, np.full(35, 25.0), touch, current30_trace(data))
    assert out["seed_age"][0] == 0
    assert out["seed_age"][30] == 30
    assert out["active"][30]


def test_wilder_rsi_uses_stage51_seed_and_has_prior_bar_touch_semantics():
    close = np.array([100, 101, 102, 101, 100, 99, 98, 97, 96, 95, 94, 93, 92, 91, 90, 89, 88], float)
    rsi = wilder_rsi(close, 14)
    assert np.isnan(rsi[13])
    assert np.isfinite(rsi[14])


def test_4h_bar_split_matches_stage51_rth_slots():
    idx = pd.date_range("2026-08-28 09:30", "2026-08-28 15:55", freq="5min", tz="America/New_York")
    values = np.linspace(100, 99, len(idx))
    raw = pd.DataFrame({"Open": values, "High": values + .1, "Low": values - .1, "Close": values}, index=idx)
    bars = build_4h_bars(raw)
    assert len(bars) == 2
    assert list(bars["slot"]) == [0, 1]
    assert bars.iloc[0]["n"] == 48
    assert bars.iloc[1]["n"] == 30
