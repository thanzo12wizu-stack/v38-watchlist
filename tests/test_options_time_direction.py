import importlib
import json
import sys
from pathlib import Path

import pandas as pd

from tools import build_options_intelligence as intel


def _directional_module():
    tools_path = str(Path("tools").resolve())
    sys.path.insert(0, tools_path)
    try:
        return importlib.import_module("build_options_positioning_directional")
    finally:
        sys.path.remove(tools_path)


def test_time_mismatch_blocks_direction():
    cur = {
        "spot": 100.0,
        "confidence": "HIGH",
        "session_consistent": False,
        "price_session_date": "2026-09-03",
    }
    out = intel._direction_bias(
        cur,
        time_quality="MISMATCH",
    )
    assert out["direction"] == "UNKNOWN"
    assert out["confidence"] == 0


def test_direction_bias_uses_structure_not_net_gex_sign():
    up = {
        "spot": 110.0,
        "atr14": 5.0,
        "call_wall": 125.0,
        "put_wall": 103.0,
        "gamma_flip": 104.0,
        "net_gex": -10_000_000.0,
        "regime": "POSITIVE_GAMMA",
        "confidence": "HIGH",
        "tech": {"21EMA": 105.0, "63VWAP": 106.0},
        "expected_move": {"expected_move_pct": 0.06},
    }
    up_bias = intel._direction_bias(
        up,
        multi={"positive": 3, "negative": 0},
        meta={"change_pct": 4.0},
        leader={"leader_score": 85},
        time_quality="VERIFIED",
    )
    assert up_bias["direction"] == "UP"
    assert up_bias["score"] >= 68

    down = {
        "spot": 90.0,
        "atr14": 5.0,
        "call_wall": 96.0,
        "put_wall": 75.0,
        "gamma_flip": 98.0,
        "net_gex": 10_000_000.0,
        "regime": "NEGATIVE_GAMMA",
        "confidence": "HIGH",
        "tech": {"21EMA": 97.0, "63VWAP": 99.0},
        "expected_move": {"expected_move_pct": 0.07},
    }
    down_bias = intel._direction_bias(
        down,
        multi={"positive": 0, "negative": 3},
        meta={"change_pct": -4.0},
        leader=None,
        time_quality="VERIFIED",
    )
    assert down_bias["direction"] == "DOWN"
    assert down_bias["score"] <= 32


def test_expected_move_falls_back_to_atm_iv_when_quotes_are_zero():
    directional = _directional_module()
    calls = pd.DataFrame({
        "strike": [100.0],
        "bid": [0.0],
        "ask": [0.0],
        "impliedVolatility": [0.40],
    })
    puts = pd.DataFrame({
        "strike": [100.0],
        "bid": [0.0],
        "ask": [0.0],
        "impliedVolatility": [0.44],
    })
    out = directional._expected_move(calls, puts, 100.0, 14 / 365.0)
    assert out["expected_move_method"] == "atm_iv_1sigma"
    assert out["expected_move"] > 0
    assert out["expected_low"] < 100.0 < out["expected_high"]


def test_price_context_prefers_upstream_completed_session_over_stale_yahoo(tmp_path, monkeypatch):
    directional = _directional_module()
    state = tmp_path / "state.json"
    universe = tmp_path / "universe.csv"
    state.write_text(json.dumps({"date": "2026-09-04"}), encoding="utf-8")
    universe.write_text(
        'シンボル,名称,価格,"価格変動 %, 1日","出来高, 1日"\n'
        'MU,Micron,1016.59,6.1,35161248\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(directional.base, "STATE_JSON", str(state))
    monkeypatch.setattr(directional.base, "UNIVERSE_CSV", str(universe))
    monkeypatch.setattr(directional, "_UPSTREAM_CACHE", None)

    idx = pd.DatetimeIndex([pd.Timestamp("2026-09-03 00:00:00", tz="America/New_York")])
    px = pd.DataFrame({"Close": [933.44]}, index=idx)
    out = directional._price_context("MU", px, "2026-09-04T23:30:00+00:00")

    assert out["spot"] == 1016.59
    assert out["price_source"] == "upstream_universe_close"
    assert out["price_session_date"] == "2026-09-04"
    assert out["history_session_date"] == "2026-09-03"
    assert out["session_consistent"] is True


def test_same_session_scan_is_verified_and_preserves_expected_move():
    row = {
        "date": "2026-09-04", "price_session_date": "2026-09-04",
        "session_consistent": "True", "spot": "100", "atr14": "4",
        "call_wall": "110", "put_wall": "95", "gamma_flip": "98",
        "net_gex": "1000000", "regime": "POSITIVE_GAMMA", "confidence": "MEDIUM",
        "total_oi": "8000", "n_strikes": "30", "expected_move": "6.5",
        "expected_move_pct": "0.065", "expected_move_method": "atm_iv_1sigma",
        "expected_low": "93.5", "expected_high": "106.5",
        "observed_at": "2026-09-05T07:55:28+00:00",
    }
    cur = intel._hist_obs(row, "SCAN")
    assert cur["session_consistent"] is True
    assert cur["price_session_date"] == "2026-09-04"
    assert cur["expected_move"]["expected_move_pct"] == 0.065
    assert intel._time_quality(cur, "2026-09-04", "SCAN") == "VERIFIED"


def test_same_session_scan_low_quality_is_not_verified():
    cur = intel._hist_obs({
        "date": "2026-09-04", "price_session_date": "2026-09-04",
        "session_consistent": "true", "spot": "100", "confidence": "LOW",
    }, "SCAN")
    assert intel._time_quality(cur, "2026-09-04", "SCAN") == "LOW_QUALITY"


def test_scan_from_previous_session_is_blocked():
    cur = intel._hist_obs({
        "date": "2026-09-03", "price_session_date": "2026-09-03",
        "session_consistent": "true", "spot": "100", "confidence": "HIGH",
    }, "SCAN")
    assert intel._time_quality(cur, "2026-09-04", "SCAN") == "MISMATCH"
