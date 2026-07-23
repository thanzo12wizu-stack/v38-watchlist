from __future__ import annotations

import pandas as pd
import pytest

from intelligence_engine.market import build_market_state


def _qqq_uptrend() -> pd.DataFrame:
    return pd.DataFrame({"close": [100.0 + index for index in range(260)]})


def test_empty_cross_section_cannot_authorize_full_exposure() -> None:
    state = build_market_state(pd.DataFrame(), _qqq_uptrend(), [])

    assert state["score_market"] == pytest.approx(1.0)
    assert state["score_confidence"] == pytest.approx(0.30)
    assert state["regime"] == "UNKNOWN"
    assert state["entry_gate"] == "NO_NEW"
    assert state["recommended_exposure"] == 0.0
    assert "low_confidence" in state["warnings"]


def test_missing_breadth_cannot_authorize_full_exposure() -> None:
    frame = pd.DataFrame(
        {
            "price": [100.0, 101.0],
            "sma10": [None, None],
            "sma50": [None, None],
            "sma200": [None, None],
            "rs_raw_63": [None, None],
            "rs_raw_126": [None, None],
            "leader_rank_pct": [None, None],
        }
    )
    state = build_market_state(frame, _qqq_uptrend(), [])

    assert state["score_confidence"] == pytest.approx(0.30)
    assert state["regime"] == "UNKNOWN"
    assert state["entry_gate"] == "NO_NEW"
    assert state["recommended_exposure_pct"] == 0.0
    assert "low_confidence" in state["warnings"]


def test_sufficient_evidence_can_still_classify_blue() -> None:
    frame = pd.DataFrame(
        {
            "price": [100.0] * 20,
            "sma10": [90.0] * 20,
            "sma50": [80.0] * 20,
            "sma200": [70.0] * 20,
            "rs_raw_63": [0.20] * 20,
            "rs_raw_126": [0.10] * 20,
            "leader_rank_pct": [90.0] * 20,
        }
    )
    sectors = [{"sector": "Technology", "breadth_positive_63d": 1.0}]
    state = build_market_state(frame, _qqq_uptrend(), sectors)

    assert state["score_confidence"] == pytest.approx(1.0)
    assert state["regime"] == "BLUE"
    assert state["entry_gate"] == "ALLOW"
    assert state["recommended_exposure"] == 1.0
    assert "low_confidence" not in state["warnings"]


def test_missing_qqq_is_always_no_new_even_with_full_breadth() -> None:
    frame = pd.DataFrame(
        {
            "price": [100.0] * 20,
            "sma10": [90.0] * 20,
            "sma50": [80.0] * 20,
            "sma200": [70.0] * 20,
            "rs_raw_63": [0.20] * 20,
            "rs_raw_126": [0.10] * 20,
            "leader_rank_pct": [90.0] * 20,
        }
    )
    sectors = [{"sector": "Technology", "breadth_positive_63d": 1.0}]
    state = build_market_state(frame, pd.DataFrame(), sectors)

    assert state["regime"] == "UNKNOWN"
    assert state["entry_gate"] == "NO_NEW"
    assert state["recommended_exposure"] == 0.0
    assert "qqq_unavailable" in state["warnings"]
