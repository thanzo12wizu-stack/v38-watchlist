import math
import json
from pathlib import Path

import pandas as pd

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


def test_sleeve_refresh_runs_after_v38_on_staging_and_fails_closed_before_commit():
    workflow = Path(".github/workflows/v38-sleeve-refresh.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "PIPELINE_BRANCH: pipeline-live" in workflow
    assert "ref: pipeline-live" in workflow
    assert "Sync staged V38 snapshot" in workflow
    assert "Rebuild Normal Stock and RSI Reset sleeves with retries" in workflow
    assert "build_v38_sleeve_live.py" in workflow
    assert "Rebuild audited companion with live Gross100 inputs" in workflow
    assert "LIVE ALLOCATION READY" in workflow
    assert "sleeve.get('status') != 'READY'" in workflow
    assert "Reset OHLC coverage not proven" in workflow
    assert "git add v38-sleeve-state.json tqqq-panic-state.json v38-live-state.json" in workflow
    assert "Pipeline staging advanced during sleeve refresh; reject stale output" in workflow
    assert 'git push origin "HEAD:refs/heads/$PIPELINE_BRANCH"' in workflow
    assert "HEAD:main" not in workflow


def test_sleeve_price_download_falls_back_after_empty_yfinance(monkeypatch):
    import build_v38_sleeve_live as sleeve
    import build_v38_tqqq_live as tqqq

    monkeypatch.setattr(sleeve.yf, "download", lambda *args, **kwargs: pd.DataFrame())
    idx = pd.to_datetime(["2026-08-28", "2026-08-31"])
    fallback = pd.DataFrame({
        "Open": [100.0, 101.0],
        "High": [102.0, 103.0],
        "Low": [99.0, 100.0],
        "Close": [101.0, 102.0],
        "Volume": [1_000_000, 1_100_000],
    }, index=idx)
    monkeypatch.setattr(tqqq, "download_yahoo_chart", lambda *args, **kwargs: fallback.copy())

    def no_fmp(*args, **kwargs):
        raise AssertionError("FMP should not be needed when Yahoo Chart succeeds")

    monkeypatch.setattr(tqqq, "download_fmp_frame", no_fmp)
    op, cl, quality = sleeve.download_adjusted_ohlc(
        ["SPY"], "2026-08-28", "2026-09-01", batch_size=10
    )
    assert list(cl.columns) == ["SPY"]
    assert float(cl.loc[pd.Timestamp("2026-08-31"), "SPY"]) == 102.0
    assert float(op.loc[pd.Timestamp("2026-08-31"), "SPY"]) == 101.0
    assert quality["fallback_requested"] == 1
    assert quality["fallback_recovered"] == 1


def test_reset_wilder_rsi_matches_known_pine_reference():
    from build_v38_sleeve_live import wilder_rsi
    close = pd.DataFrame({"AAA": [44.34,44.09,44.15,43.61,44.33,44.83,45.1,45.42,45.84,46.08,45.89,46.03,45.61,46.28,46.28,46.0,46.03,46.41,46.22,45.64,46.21]})
    rsi = wilder_rsi(close, 14)["AAA"]
    assert math.isclose(float(rsi.iloc[14]), 70.46413502109705, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(float(rsi.iloc[-1]), 62.880718309962404, rel_tol=0, abs_tol=1e-12)
