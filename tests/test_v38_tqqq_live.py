import math
from pathlib import Path

import numpy as np
import pandas as pd

from build_v38_tqqq_live import (
    CACHE_SCHEMA,
    _frame_payload,
    apply_legacy_mc57_overlay,
    load_source_cache,
    build_4h_bars,
    current30_trace,
    stage56_trace,
    write_source_cache,
    wilder_rsi,
)


def test_legacy_dashboard_mc57_overrides_reconstructed_current_and_log(tmp_path):
    log = tmp_path / "daily_log.csv"
    log.write_text("date,gate,mri\n2026-08-28,Yellow,62.6\n2026-08-31,Yellow,58.6\n", encoding="utf-8")
    sources = {
        "mc57": pd.Series([55.0, 56.6], index=pd.to_datetime(["2026-08-28", "2026-08-31"])),
        "providers": {"mc57": {"coverage_tickers": 57}},
    }
    state = {"date": "2026-08-31", "mri": 58.7}
    out = apply_legacy_mc57_overlay(sources, state, log)
    assert math.isclose(out["mc57"].loc[pd.Timestamp("2026-08-28")], 62.6)
    assert math.isclose(out["mc57"].loc[pd.Timestamp("2026-08-31")], 58.7)
    assert out["providers"]["mc57_canonical"]["policy"] == "LEGACY_DASHBOARD_CANONICAL_OVERLAY"


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


def test_private_source_cache_roundtrip_preserves_daily_and_intraday_timezone(tmp_path):
    daily_index = pd.date_range("2026-08-27", periods=2, freq="B")
    daily = pd.DataFrame(
        {
            "Open": [100.0, 101.0], "High": [102.0, 103.0],
            "Low": [99.0, 100.0], "Close": [101.0, 102.0],
            "Volume": [1_000.0, 1_100.0],
        },
        index=daily_index,
    )
    intraday_index = pd.date_range(
        "2026-08-28 09:30", periods=8, freq="5min", tz="America/New_York"
    )
    intraday = daily.iloc[[0] * 8].copy()
    intraday.index = intraday_index
    series = pd.Series([50.0, 51.0], index=daily_index)
    payload = {
        "schema": CACHE_SCHEMA,
        "fetched_at": "2026-08-31T00:00:00+00:00",
        "daily": {ticker: _frame_payload(daily) for ticker in ("QQQ", "TQQQ", "NQ=F", "^VIX")},
        "mc57": {"index": [value.isoformat() for value in daily_index], "data": [50.0, 51.0]},
        "mc57_coverage": {"index": [value.isoformat() for value in daily_index], "data": [100.0, 100.0]},
        "qqq_5m": _frame_payload(intraday),
        "coverage": {},
    }
    path = tmp_path / "cache.json"
    write_source_cache(path, payload)
    loaded = load_source_cache(path)
    assert loaded["qqq"].index.tz is None
    assert str(loaded["qqq_5m"].index.tz) == "UTC"
    assert loaded["qqq_5m"].iloc[-1]["Close"] == 101.0
    assert loaded["mc57"].iloc[-1] == series.iloc[-1]


def test_yahoo_utc_cache_roundtrip_builds_correct_new_york_rth_slots(tmp_path):
    utc_index = pd.date_range("2026-08-28 13:30", "2026-08-28 19:55", freq="5min", tz="UTC")
    values = np.linspace(100, 101, len(utc_index))
    intraday = pd.DataFrame({"Open": values, "High": values + .1, "Low": values - .1, "Close": values}, index=utc_index)
    daily_index = pd.date_range("2026-08-27", periods=2, freq="B")
    daily = pd.DataFrame({"Open": [100., 101.], "High": [102., 103.], "Low": [99., 100.], "Close": [101., 102.], "Volume": [1000., 1100.]}, index=daily_index)
    payload = {
        "schema": CACHE_SCHEMA, "fetched_at": "2026-08-28T21:00:00+00:00",
        "daily": {ticker: _frame_payload(daily) for ticker in ("QQQ", "TQQQ", "NQ=F", "^VIX")},
        "mc57": {"index": [x.isoformat() for x in daily_index], "data": [50., 51.]},
        "mc57_coverage": {"index": [x.isoformat() for x in daily_index], "data": [100., 100.]},
        "qqq_5m": _frame_payload(intraday), "coverage": {},
    }
    path = tmp_path / "cache.json"
    write_source_cache(path, payload)
    loaded = load_source_cache(path)
    assert str(loaded["qqq_5m"].index.tz) == "UTC"
    bars = build_4h_bars(loaded["qqq_5m"])
    assert list(bars["slot"]) == [0, 1]
    assert list(bars["n"]) == [48, 30]


def test_wilder_rsi_matches_known_sma_seed_reference():
    close = np.array([44.34,44.09,44.15,43.61,44.33,44.83,45.1,45.42,45.84,46.08,45.89,46.03,45.61,46.28,46.28,46.0,46.03,46.41,46.22,45.64,46.21])
    rsi = wilder_rsi(close, 14)
    assert math.isclose(rsi[14], 70.46413502109705, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(rsi[-1], 62.880718309962404, rel_tol=0, abs_tol=1e-12)


def test_isolated_v38_workflow_prefetches_tqqq_before_producer_and_companion():
    workflow = Path(".github/workflows/v38-live.yml").read_text(encoding="utf-8")
    prefetch = workflow.index("Prefetch dedicated TQQQ market inputs")
    producer = workflow.index("- name: Build CURRENT30 and Stage56 TQQQ live state")
    companion = workflow.index("- name: Build provisional audited V38 companion")
    assert prefetch < producer < companion
    assert "--prefetch-cache v38-tqqq-live-source-cache.json" in workflow
    assert "--cache v38-tqqq-live-source-cache.json" in workflow
    assert "TQQQ_LAST_KNOWN_GOOD_READY" in workflow
    assert "retained same-session READY last-known-good" in workflow
    assert "reacquiring all dedicated market inputs" not in workflow
    assert "build_dashboard.py" not in workflow
    assert "v38-tqqq-live-source-cache.json" not in Path(
        "scripts/export_public_site.py"
    ).read_text(encoding="utf-8")
