from __future__ import annotations

from pathlib import Path

import pandas as pd

from intelligence_engine.research_decision_dashboard import build_html
from intelligence_engine.research_operations import (
    build_model_health,
    build_portfolio_overlay,
    build_research_changes,
    run,
)
from intelligence_engine.research_storage import upsert_year_partitions, write_json


def _rankings() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "date": "2026-07-20",
                "research_rank": 20,
                "decision_status": "READY",
                "candidate_archetype": "EMERGING_LEADER",
                "financial_phase": "INFLECTING",
                "rs_archetype": "NEW_LEADER",
                "entry_state": "EARLY",
                "setup": "WATCH",
                "hard_blocks": [],
            },
            {
                "ticker": "OLD",
                "date": "2026-07-20",
                "research_rank": 5,
                "decision_status": "ACTIONABLE",
                "candidate_archetype": "QUALITY_COMPOUNDER",
                "financial_phase": "COMPOUNDING",
                "rs_archetype": "ESTABLISHED_LEADER",
                "entry_state": "READY",
                "setup": "PULLBACK",
                "hard_blocks": [],
            },
            {
                "ticker": "AAA",
                "date": "2026-07-21",
                "research_rank": 4,
                "decision_status": "ACTIONABLE",
                "candidate_archetype": "EMERGING_LEADER",
                "financial_phase": "ACCELERATING",
                "rs_archetype": "ACCELERATING_LEADER",
                "entry_state": "READY",
                "setup": "PRE_BREAKOUT",
                "expectancy_consistency": "CONFIRMED",
                "expectancy_status": "QUALIFIED",
                "expected_edge_10d_8y": .02,
                "price": 120.0,
                "stop_risk_pct": 5.0,
                "hard_blocks": [],
            },
            {
                "ticker": "BAD",
                "date": "2026-07-21",
                "research_rank": 30,
                "decision_status": "AVOID",
                "candidate_archetype": "DETERIORATION_ALERT",
                "financial_phase": "DILUTING",
                "rs_archetype": "FADING_LEADER",
                "entry_state": "BROKEN",
                "setup": "AVOID",
                "expectancy_consistency": "CONFLICT",
                "price": 80.0,
                "hard_blocks": ["FUNDAMENTAL_DETERIORATION"],
            },
        ]
    )


def _expectancy() -> dict:
    def group(edge: float, qualification: str, samples: int = 120) -> dict:
        return {
            "group_type": "archetype_setup",
            "candidate_archetype": "EMERGING_LEADER",
            "setup": "PRE_BREAKOUT",
            "horizon": 10,
            "samples": samples,
            "mean_excess_return": edge,
            "qualification": qualification,
            "max_ticker_share": .10,
            "max_year_share": .25,
            "loyo_positive_rate": .75,
        }

    return {
        "status": "OK",
        "primary_window_years": 8,
        "retained_years": list(range(2017, 2027)),
        "retained_sample_count": 5000,
        "windows": [
            {"window_years": 8, "groups": [group(.02, "QUALIFIED")]},
            {"window_years": 5, "groups": [group(-.01, "PROMISING")]},
        ],
        "walk_forward": [
            {"horizon": 10, "test_year": 2024, "test_mean_excess": .01},
            {"horizon": 10, "test_year": 2025, "test_mean_excess": -.005},
        ],
    }


def test_change_detection_catches_upgrade_rank_gain_new_and_drop() -> None:
    result = build_research_changes(_rankings())
    types = {event["type"] for event in result["events"]}
    assert result["status"] == "OK"
    assert {"STATUS_CHANGE", "RANK_GAIN", "NEW_CANDIDATE", "DROPPED"}.issubset(types)
    assert any(event["ticker"] == "AAA" and event["title"] == "買えるへ格上げ" for event in result["events"])


def test_model_health_warns_on_8y_5y_conflict() -> None:
    health = build_model_health(_expectancy())
    assert health["status"] == "WARN"
    assert health["qualified_groups"] == 1
    assert health["conflict_groups"] == 1
    assert health["conflict_rate"] == 1.0
    assert "recent_window_conflict_high" in health["warnings"]


def test_portfolio_overlay_supports_add_exit_and_unranked() -> None:
    positions = pd.DataFrame(
        [
            {"ticker": "AAA", "entry_stage": 1, "weight": .04, "cost_basis": 100.0, "partial_taken": False},
            {"ticker": "BAD", "entry_stage": 2, "weight": .08, "cost_basis": 90.0, "partial_taken": False},
            {"ticker": "MISS", "entry_stage": 2, "weight": .08, "cost_basis": 50.0, "partial_taken": False},
        ]
    )
    result = build_portfolio_overlay(positions, _rankings())
    actions = {row["ticker"]: row["action"] for row in result["positions"]}
    assert actions["AAA"] == "ADD"
    assert actions["BAD"] == "EXIT"
    assert actions["MISS"] == "HOLD"


def test_operations_run_and_dashboard_tabs(tmp_path: Path) -> None:
    root = tmp_path / "research"
    rankings = _rankings()
    upsert_year_partitions(
        root,
        "rankings",
        rankings,
        date_column="date",
        keys=("ticker", "date"),
        retention_years=10,
        reference_date=pd.Timestamp("2026-07-21"),
    )
    write_json(root / "expectancy.json", _expectancy())
    write_json(root / "manifest.json", {"generated_at": "2026-07-21T22:00:00Z", "warnings": []})
    portfolio = tmp_path / "portfolio.csv"
    pd.DataFrame(
        [{"ticker": "AAA", "entry_stage": 1, "weight": .04, "cost_basis": 100.0}]
    ).to_csv(portfolio, index=False)
    result = run(root, portfolio)
    assert result["changes"] == "OK"
    assert result["model_health"] == "WARN"
    assert (root / "changes.json").exists()
    assert (root / "portfolio_overlay.json").exists()
    assert (root / "model_health.json").exists()
    page = build_html(root)
    assert "前回からの変化" in page
    assert "Portfolio Research Overlay" in page
    assert "Model Health" in page
    assert "AAA" in page


def test_missing_primary_expectancy_is_not_pass() -> None:
    health = build_model_health({"windows": [], "walk_forward": []})
    assert health["status"] == "FAIL"
    assert "primary_8y_expectancy_missing" in health["warnings"]
