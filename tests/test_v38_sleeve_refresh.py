import json
import sys

import numpy as np
import pandas as pd
import pytest

import build_v38_sleeve_refresh as refresh


def _frame(symbols, date="2026-08-31"):
    idx = pd.DatetimeIndex([pd.Timestamp(date)])
    op = pd.DataFrame({s: [100.0] for s in symbols}, index=idx)
    cl = pd.DataFrame({s: [101.0] for s in symbols}, index=idx)
    return op, cl


def _reset_frame(symbols, periods=90, end="2026-08-31"):
    idx = pd.bdate_range(end=end, periods=periods)
    op = pd.DataFrame(
        {s: np.linspace(90.0, 100.0, len(idx)) for s in symbols},
        index=idx,
    )
    cl = pd.DataFrame(
        {s: np.linspace(91.0, 101.0, len(idx)) for s in symbols},
        index=idx,
    )
    return op, cl


def test_small_normal_request_recovers_missing_symbol(monkeypatch):
    def base(symbols, start, end, batch_size=150):
        op, cl = _frame(["AAA"])
        return op, cl, {"requested": 2, "downloaded": 1, "failed_batches": 0}

    def chart(symbol, start=None):
        assert symbol == "CAKE"
        idx = pd.DatetimeIndex([pd.Timestamp("2026-08-31")])
        return pd.DataFrame(
            {"Open": [65.0], "High": [67.0], "Low": [64.0], "Close": [66.0], "Volume": [1_000_000]},
            index=idx,
        )

    monkeypatch.setattr(refresh, "_BASE_DOWNLOAD", base)
    monkeypatch.setattr(refresh, "download_yahoo_chart", chart)
    op, cl, quality = refresh.download_adjusted_ohlc_resilient(
        ["AAA", "CAKE"], "2026-08-28", "2026-09-01", 100
    )

    assert cl.at[pd.Timestamp("2026-08-31"), "CAKE"] == 66.0
    assert op.at[pd.Timestamp("2026-08-31"), "CAKE"] == 65.0
    assert quality["fallback_used"] == ["CAKE"]
    assert quality["fallback_failed"] == {}


def test_reset_retries_missing_batch_then_reuses_validated_cache(monkeypatch, tmp_path):
    symbols = [f"T{i}" for i in range(60)]
    calls = []

    def base(requested, start, end, batch_size=150):
        calls.append(list(requested))
        if len(calls) == 1:
            op, cl = _reset_frame(requested[:-10])
        else:
            op, cl = _reset_frame(requested)
        # Deliberately lie the old way: column-count metadata alone says all downloaded.
        return op, cl, {"requested": len(requested), "downloaded": len(requested), "failed_batches": 0}

    monkeypatch.setenv(refresh.RESET_CACHE_ENV, str(tmp_path / "cache"))
    monkeypatch.setattr(refresh, "_BASE_DOWNLOAD", base)
    monkeypatch.setattr(refresh.time, "sleep", lambda _: None)

    op1, cl1, quality1 = refresh.download_adjusted_ohlc_resilient(
        symbols, "2026-04-01", "2026-09-01", 150
    )
    assert quality1["coverage_ok"] is True
    assert quality1["history_coverage_ratio"] == 1.0
    assert quality1["target_coverage_ratio"] == 1.0
    assert quality1["cache_hit"] is False
    assert [len(x) for x in calls] == [60, 10]

    def rate_limited(*args, **kwargs):
        raise RuntimeError("YFRateLimitError")

    monkeypatch.setattr(refresh, "_BASE_DOWNLOAD", rate_limited)
    op2, cl2, quality2 = refresh.download_adjusted_ohlc_resilient(
        symbols, "2026-04-01", "2026-09-01", 150
    )
    assert quality2["cache_hit"] is True
    assert quality2["coverage_ok"] is True
    pd.testing.assert_frame_equal(op1, op2)
    pd.testing.assert_frame_equal(cl1, cl2)


def test_reset_rate_limit_cannot_return_ready(monkeypatch, tmp_path):
    symbols = [f"T{i}" for i in range(60)]

    def rate_limited(*args, **kwargs):
        raise RuntimeError("YFRateLimitError")

    monkeypatch.setenv(refresh.RESET_CACHE_ENV, str(tmp_path / "cache"))
    monkeypatch.setattr(refresh, "_BASE_DOWNLOAD", rate_limited)
    monkeypatch.setattr(refresh.time, "sleep", lambda _: None)

    with pytest.raises(refresh.ResetPriceCoverageError, match="RESET_PRICE_COVERAGE_INSUFFICIENT"):
        refresh.download_adjusted_ohlc_resilient(
            symbols, "2026-04-01", "2026-09-01", 150
        )


def test_reset_nan_columns_do_not_count_as_real_downloads(monkeypatch, tmp_path):
    symbols = [f"T{i}" for i in range(60)]

    def fake_column_complete(requested, start, end, batch_size=150):
        good = requested[:20]
        op, cl = _reset_frame(good)
        # Add every requested column, but most contain no actual OHLC values.
        for symbol in requested[20:]:
            op[symbol] = np.nan
            cl[symbol] = np.nan
        return op, cl, {
            "requested": len(requested),
            "downloaded": len(requested),
            "failed_batches": 0,
        }

    monkeypatch.setenv(refresh.RESET_CACHE_ENV, str(tmp_path / "cache"))
    monkeypatch.setattr(refresh, "_BASE_DOWNLOAD", fake_column_complete)
    monkeypatch.setattr(refresh.time, "sleep", lambda _: None)

    with pytest.raises(refresh.ResetPriceCoverageError):
        refresh.download_adjusted_ohlc_resilient(
            symbols, "2026-04-01", "2026-09-01", 150
        )


def test_complete_reset_input_is_unchanged_and_marked_coverage_ready(monkeypatch, tmp_path):
    symbols = [f"T{i}" for i in range(60)]
    expected_op, expected_cl = _reset_frame(symbols)

    def base(requested, start, end, batch_size=150):
        return (
            expected_op[requested].copy(),
            expected_cl[requested].copy(),
            {"requested": len(requested), "downloaded": len(requested), "failed_batches": 0},
        )

    monkeypatch.setenv(refresh.RESET_CACHE_ENV, str(tmp_path / "cache"))
    monkeypatch.setattr(refresh, "_BASE_DOWNLOAD", base)
    monkeypatch.setattr(refresh.time, "sleep", lambda _: None)

    op, cl, quality = refresh.download_adjusted_ohlc_resilient(
        symbols, "2026-04-01", "2026-09-01", 150
    )

    pd.testing.assert_frame_equal(op, expected_op)
    pd.testing.assert_frame_equal(cl, expected_cl)
    assert quality["coverage_ok"] is True
    assert quality["source"] == "CACHE_PLUS_BATCH_RETRY"


def test_incomplete_rebuild_cannot_overwrite_previous_ready_state(monkeypatch, tmp_path):
    out = tmp_path / "v38-sleeve-state.json"
    tqqq = tmp_path / "tqqq-panic-state.json"
    previous = {
        "schema": "v38-sleeve-live-1",
        "asof": "2026-08-31",
        "status": "READY",
        "rsi_reset": {
            "status": "READY",
            "strategy": "RS63_TOP3_RISE30_SIGTOP3",
            "desired_pct": 2.9,
            "position_count": 1,
            "positions": [{"symbol": "HRL", "entry_date": "2026-08-31"}],
            "monitor": [],
            "download_quality": {"coverage_ok": True},
        },
    }
    tqqq_before = {"asof": "2026-08-31", "reset_desired_pct": 2.9}
    out.write_text(json.dumps(previous), encoding="utf-8")
    tqqq.write_text(json.dumps(tqqq_before), encoding="utf-8")
    before_out = out.read_bytes()
    before_tqqq = tqqq.read_bytes()

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "build_v38_sleeve_refresh.py",
            "--out",
            str(out),
            "--tqqq-state",
            str(tqqq),
        ],
    )

    def bad_runner():
        out.write_text(
            json.dumps(
                {
                    "status": "DATA REQUIRED",
                    "rsi_reset": {"status": "DATA REQUIRED", "monitor": []},
                }
            ),
            encoding="utf-8",
        )
        tqqq.write_text(json.dumps({"reset_desired_pct": 0.0}), encoding="utf-8")

    with pytest.raises(refresh.ResetPriceCoverageError, match="RESET_REBUILD_NOT_READY"):
        refresh.run_guarded_refresh(bad_runner)

    assert out.read_bytes() == before_out
    assert tqqq.read_bytes() == before_tqqq


def test_reset_reproducibility_payload_includes_hrl_signal_position_and_desired_pct():
    state = {
        "rsi_reset": {
            "asof": "2026-08-31",
            "strategy": "RS63_TOP3_RISE30_SIGTOP3",
            "desired_pct": 2.9405515934699182,
            "position_count": 1,
            "positions": [
                {
                    "symbol": "HRL",
                    "theme": "肉/食肉加工",
                    "entry_date": "2026-08-31",
                    "exit_i": 116,
                    "shares": 0.0013463323476042676,
                    "close": 21.850000381469727,
                    "mark": 0.02941736230873828,
                }
            ],
            "signal_count_in_rebuild_window": 1,
            "accepted_in_rebuild_window": 1,
            "monitor": [
                {
                    "symbol": "HRL",
                    "theme": "肉/食肉加工",
                    "signal_date": "2026-08-28",
                    "status": "SIGNAL_OCCURRED",
                }
            ],
        }
    }

    first = refresh.reset_reproducibility_payload(state)
    second = refresh.reset_reproducibility_payload(json.loads(json.dumps(state)))

    assert first == second
    assert first["desired_pct"] == round(2.9405515934699182, 12)
    assert first["positions"][0]["symbol"] == "HRL"
    assert first["visible_signals"][0]["signal_date"] == "2026-08-28"
