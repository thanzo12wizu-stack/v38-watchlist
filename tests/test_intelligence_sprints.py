from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from intelligence_engine.expectancy import build_expectancy, calibrate_candidates
from intelligence_engine.intelligence_dashboard import build_html
from intelligence_engine.leader_history import build_price_leader_transitions
from intelligence_engine.portfolio import build_portfolio_doctor, load_positions
from intelligence_engine.presentation import enrich_candidates, partition_candidates
from intelligence_engine.story import add_story_intelligence
from intelligence_engine.theme import attach_theme_context, build_theme_intelligence


def _price_frame(drift: float = .001, periods: int = 420, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    index = pd.bdate_range("2024-01-02", periods=periods)
    noise = rng.normal(drift, .008, periods)
    close = 50 * np.exp(np.cumsum(noise))
    return pd.DataFrame(
        {
            "open": close * .998,
            "high": close * 1.012,
            "low": close * .988,
            "close": close,
            "volume": np.linspace(1_000_000, 2_000_000, periods),
        },
        index=index,
    )


def test_story_missing_is_not_mixed() -> None:
    frame = pd.DataFrame([{"ticker": "AAA"}])
    result = add_story_intelligence(frame)
    assert result.loc[0, "story_phase"] == "DATA_INSUFFICIENT"
    assert result.loc[0, "story_evidence_count"] == 0


def test_candidate_decision_layer_builds_three_states_and_japanese_reasons() -> None:
    candidates = [
        {
            "ticker": "BUY",
            "setup": "PULLBACK",
            "market_gate": "ALLOW",
            "score_entry": 90,
            "score_leader": 92,
            "score_candidate": 88,
            "theme_score": .82,
            "theme_confirmed": True,
            "story_score": 80,
            "story_phase": "COMPOUNDING",
            "price": 100,
            "adr_pct": 4,
            "pivot": 106,
            "stop_ema21_low": 96,
            "stop_sma10": 95,
            "distance_52w_high_pct": -12,
            "warnings": [],
        },
        {
            "ticker": "WAIT",
            "setup": "PRE_BREAKOUT",
            "market_gate": "NO_NEW",
            "score_entry": 85,
            "score_leader": 86,
            "score_candidate": 84,
            "theme_score": .72,
            "story_phase": "DATA_INSUFFICIENT",
            "price": 50,
            "pivot": 51,
            "stop_ema21_low": 48,
            "stop_sma10": 47,
            "distance_52w_high_pct": -10,
            "warnings": ["market_gate", "story_data_insufficient"],
        },
        {
            "ticker": "NO",
            "setup": "WATCH",
            "market_gate": "ALLOW",
            "score_entry": 60,
            "score_leader": 60,
            "score_candidate": 60,
            "price": 20,
            "stop_ema21_low": 15,
            "stop_sma10": 14,
            "distance_52w_high_pct": -2,
            "warnings": ["hard_block"],
            "hard_block": True,
        },
    ]
    enriched = enrich_candidates(candidates, generated_at="2026-07-22T00:00:00Z", price_asof="2026-07-21")
    parts = partition_candidates(enriched)
    assert [item["ticker"] for item in parts["ACTIONABLE"]] == ["BUY"]
    assert [item["ticker"] for item in parts["READY"]] == ["WAIT"]
    assert [item["ticker"] for item in parts["AVOID"]] == ["NO"]
    buy = parts["ACTIONABLE"][0]
    assert buy["entry_low"] is not None
    assert buy["entry_high"] is not None
    assert buy["stop_effective"] == 96
    assert buy["stop_distance_pct"] is not None
    assert buy["reward_risk"] is not None
    wait = parts["READY"][0]
    assert "地合いゲートにより新規発注停止" in wait["reasons_ja"]
    assert wait["story_phase"] == "DATA_INSUFFICIENT"
    assert all(reason != "—" for reason in wait["reasons_ja"])


def test_curated_taxonomy_overrides_sector_fallback(tmp_path: Path, monkeypatch) -> None:
    taxonomy = tmp_path / "themes.csv"
    pd.DataFrame(
        [{"ticker": "AAA", "theme": "AI Cloud", "theme_ja": "AIクラウド"}]
    ).to_csv(taxonomy, index=False)
    monkeypatch.setenv("V38_THEME_TAXONOMY", str(taxonomy))
    frame = pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "sector": "Technology",
                "industry": "Software",
                "rs_raw_63": .2,
                "rs_raw_126": .2,
                "rs_raw_189": .2,
                "rs_change_raw_63": .1,
                "rs_change_raw_126": .1,
                "leader_rank_pct": 95,
                "setup": "PULLBACK",
                "score_leader": 90,
                "score_entry": 88,
            }
        ]
    )
    themes = build_theme_intelligence(frame)
    assert themes[0]["theme"] == "AI Cloud"
    assert themes[0]["theme_ja"] == "AIクラウド"
    attached = attach_theme_context(frame, themes)
    assert attached.loc[0, "theme"] == "AI Cloud"
    assert attached.loc[0, "theme_ja"] == "AIクラウド"


def test_price_history_produces_rs_boards_without_prior_snapshot() -> None:
    prices = {
        "QQQ": _price_frame(.0004, seed=99),
        "AAA": _price_frame(.0016, seed=1),
        "BBB": _price_frame(.0008, seed=2),
        "CCC": _price_frame(-.0002, seed=3),
    }
    result = build_price_leader_transitions(prices, lookback_sessions=5)
    assert result["status"] == "PRICE_HISTORY"
    assert set(result["leader_board"]) == {"rs63", "rs126", "rs189"}
    assert result["leader_board"]["rs63"][0]["ticker"] in {"AAA", "BBB", "CCC"}
    assert result["rank_changes"]


def test_expectancy_has_walk_forward_and_candidate_adjustment() -> None:
    prices = {
        "QQQ": _price_frame(.0003, seed=99),
        "AAA": _price_frame(.0015, seed=1),
        "BBB": _price_frame(-.0001, seed=2),
        "CCC": _price_frame(.0008, seed=3),
    }
    result = build_expectancy(prices, min_samples=2, stride=4)
    assert result["status"] == "OK"
    assert result["rankings"]
    assert result["walk_forward"]
    calibrated = calibrate_candidates(
        [{"ticker": "AAA", "setup": "WATCH", "score_entry": 60}], result
    )[0]
    assert "expectancy_rank_adjustment" in calibrated
    assert 0 <= calibrated["entry_score_calibrated"] <= 100


def test_portfolio_two_stage_cost_exit_and_concentration(tmp_path: Path) -> None:
    path = tmp_path / "portfolio.csv"
    pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "weight": .30,
                "entry_date": "2026-01-01",
                "entry_price_1": 10,
                "entry_price_2": 12,
                "shares_1": 10,
                "shares_2": 10,
                "entry_stage": 1,
                "first_pivot_date": "2026-01-01",
                "trail_method": "21EMA_LOW",
                "strategy": "swing",
            },
            {
                "ticker": "BBB",
                "weight": .30,
                "entry_date": "2026-01-01",
                "entry_price_1": 10,
                "shares_1": 10,
                "entry_stage": 2,
                "trail_method": "10MA",
                "strategy": "swing",
            },
        ]
    ).to_csv(path, index=False)
    positions = load_positions(path)
    assert positions.loc[0, "cost_basis"] == 11
    scored = pd.DataFrame(
        [
            {"ticker": "AAA", "price": 12, "stop_ema21_low": 10, "stop_sma10": 11, "adr_pct": 4, "sector": "Tech", "theme": "AI", "hard_block": False},
            {"ticker": "BBB", "price": 13, "stop_ema21_low": 11, "stop_sma10": 12, "adr_pct": 3, "sector": "Tech", "theme": "AI", "hard_block": False},
        ]
    )
    result = build_portfolio_doctor(positions, scored, {}, {"regime": "YELLOW", "entry_gate": "NO_NEW"})
    aaa = next(item for item in result["positions"] if item["ticker"] == "AAA")
    assert aaa["action"] == "EXIT"
    assert "second_pivot_missing_10d" in aaa["reasons"]
    assert "market_exposure_cap_exceeded" in result["warnings"]
    assert "sector_concentration" in result["warnings"]
    assert "theme_concentration" in result["warnings"]
    assert result["positions_copy"]


def test_dashboard_translates_decision_contract_without_raw_json() -> None:
    candidate = enrich_candidates(
        [
            {
                "ticker": "AAA",
                "setup": "PULLBACK",
                "market_gate": "NO_NEW",
                "score_entry": 80,
                "score_leader": 85,
                "score_candidate": 82,
                "story_phase": "DATA_INSUFFICIENT",
                "price": 100,
                "pivot": 105,
                "stop_ema21_low": 96,
                "stop_sma10": 95,
                "distance_52w_high_pct": -10,
                "warnings": ["market_gate", "story_data_insufficient"],
            }
        ]
    )[0]
    payload = {
        "generated_at": "2026-07-22T00:00:00Z",
        "manifest": {"price_asof": "2026-07-21"},
        "market_state": {"regime": "YELLOW", "entry_gate": "NO_NEW", "recommended_exposure_pct": 35},
        "morning_brief": {"headline": "地合い YELLOW", "summary_20s": "新規停止、準備継続"},
        "entry_candidates": [candidate],
        "data_quality": {"status": "PASS", "warnings": [], "metrics": {"price_coverage_ratio": .99}},
        "expectancy_rankings": {"status": "OK", "sample_count": 100, "ticker_count": 5, "years": [2025, 2026], "rankings": [], "walk_forward": []},
        "robust_expectancy": {"status": "NO_SETTLED_OBSERVATIONS"},
        "leader_transitions": {"status": "PRICE_HISTORY", "changes": {}},
    }
    html = build_html(payload)
    assert "発注可能" in html
    assert "準備候補" in html
    assert "回避" in html
    assert "Entry帯" in html
    assert "DATA_INSUFFICIENT" in html
    assert "地合いゲートにより新規発注停止" in html
    assert "Leader Transition Raw" not in html
    assert '"status": "NO_SETTLED_OBSERVATIONS"' not in html
