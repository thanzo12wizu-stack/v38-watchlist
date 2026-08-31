import json

import pandas as pd

import sitecustomize as cachemod
from build_v38_sleeve_live import _merge_desired_into_tqqq, _monitor_band, advance_normal


def test_monitor_bands_are_display_only_thresholds():
    assert _monitor_band(29.9) == "RSI30_OR_BELOW"
    assert _monitor_band(34.9) == "WITHIN_5PT"
    assert _monitor_band(39.9) == "WITHIN_10PT"
    assert _monitor_band(45.0) == "WATCHING"
    assert _monitor_band(None) == "DATA_REQUIRED"


def test_merge_desired_into_tqqq_requires_same_asof_and_ready(tmp_path):
    path = tmp_path / "tqqq.json"
    path.write_text(json.dumps({"asof": "2026-08-28", "live_generation_status": "READY",
                                "underlying_target_pct": 30, "requested_target_pct": 30}), encoding="utf-8")
    _merge_desired_into_tqqq(path, "2026-08-28", 86.0, 5.8, "READY")
    ready = json.loads(path.read_text(encoding="utf-8"))
    assert ready["sleeve_live_status"] == "READY"
    assert ready["normal_stock_desired_pct"] == 86.0
    assert ready["reset_desired_pct"] == 5.8
    _merge_desired_into_tqqq(path, "2026-08-27", 86.0, 5.8, "READY")
    stale = json.loads(path.read_text(encoding="utf-8"))
    assert stale["sleeve_live_status"] == "DATA REQUIRED"
    assert stale["normal_stock_desired_pct"] is None
    assert stale["reset_desired_pct"] is None


def test_same_session_normal_seed_marks_exposure_and_keeps_stop_mode_no_entries():
    previous = {"status": "READY", "asof": "2026-08-28", "cash": 20.0,
                "positions": [{"symbol": "AAA", "shares": 1.0, "entry_price": 100.0,
                               "entry_date": "2026-08-01", "peak_close": 110.0,
                               "partial_done": False, "close": 105.0}],
                "pending": {"full_exits": [], "partial25": [], "entries": []}}
    companion = {"market": {"mode": "STOP", "new_entry_limit": 0},
                 "ranking": {"strict_loo_live_status": "READY"}, "candidates": []}
    state = advance_normal(previous, companion, "2026-08-28")
    assert state["status"] == "READY"
    assert state["position_count"] == 1
    assert round(state["desired_pct"], 6) == round(105.0 / 125.0 * 100.0, 6)
    assert state["pending"]["entries"] == []
    assert state["pending"]["entry_cap"] == 0


def _raw(symbol, opens, closes, adjusted):
    idx = pd.to_datetime(["2026-08-27", "2026-08-28"])
    part = pd.DataFrame({"Open": opens, "Close": closes, "Adj Close": adjusted}, index=idx)
    return pd.concat({symbol: part}, axis=1)


def test_shared_cache_preserves_adjusted_open_close_and_merges_batches(tmp_path):
    old = cachemod.CACHE_PATH
    cachemod.CACHE_PATH = tmp_path / "prices.pkl"
    try:
        cachemod._merge_cache(_raw("AAA", [100, 102], [110, 112], [55, 56]),
                              ["AAA"], "2026-08-27", "2026-08-29")
        cachemod._merge_cache(_raw("BBB", [20, 21], [20, 21], [20, 21]),
                              ["BBB"], "2026-08-27", "2026-08-29")
        out = cachemod._serve_cache(["AAA", "BBB"], start="2026-08-27", end="2026-08-29")
        assert isinstance(out.columns, pd.MultiIndex)
        assert set(out.columns.get_level_values(0)) == {"AAA", "BBB"}
        assert out["AAA"].loc[pd.Timestamp("2026-08-28"), "Close"] == 56.0
        assert out["AAA"].loc[pd.Timestamp("2026-08-28"), "Open"] == 51.0
        assert out["BBB"].loc[pd.Timestamp("2026-08-28"), "Open"] == 21.0
    finally:
        cachemod.CACHE_PATH = old


def test_shared_cache_patch_is_targeted_to_live_strict_and_sleeve_scripts_only():
    assert cachemod.TARGET_STRICT == "build_v38_strict_loo_live.py"
    assert cachemod.TARGET_SLEEVE == "build_v38_sleeve_live.py"
