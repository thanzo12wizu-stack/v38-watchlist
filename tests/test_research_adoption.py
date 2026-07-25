from __future__ import annotations

from pathlib import Path

import pandas as pd

from intelligence_engine.research_adoption import AdoptionPolicy, _candidate_masks, _decision, _summary, _walk_forward


def _frame() -> pd.DataFrame:
    rows = []
    for year in range(2017, 2027):
        for day in range(12):
            rows.append({
                "ticker": f"T{day % 6}",
                "date": f"{year}-01-{day + 1:02d}",
                "excess_10": 0.01 + (day % 3) * 0.001,
                "hard_blocks": [],
                "candidate_archetype": "EMERGING_LEADER",
                "decision_status": "QUALIFIED",
                "research_confidence": 0.8,
                "expected_edge_10d": 0.02,
                "expectancy_consistency": "CONFIRMED",
            })
    return pd.DataFrame(rows)


def test_candidate_masks_are_progressively_selective() -> None:
    frame = _frame()
    frame.loc[0, "hard_blocks"] = ["EARNINGS_WINDOW"]
    frame.loc[1, "candidate_archetype"] = "DETERIORATION_ALERT"
    frame.loc[2, "expected_edge_10d"] = -0.01
    masks = _candidate_masks(frame)
    assert int(masks["BASELINE"].sum()) == len(frame)
    assert int(masks["HARD_BLOCKS"].sum()) == len(frame) - 1
    assert not bool(masks["ARCHETYPE"].iloc[1])
    assert not bool(masks["EDGE_CONFIRMED"].iloc[2])


def test_date_block_summary_and_adoption() -> None:
    frame = _frame()
    policy = AdoptionPolicy(bootstrap_samples=100, min_samples=50)
    summary = _summary(frame, "excess_10", policy)
    walk = _walk_forward(frame, "EDGE_CONFIRMED", pd.Series(True, index=frame.index), "excess_10")
    decision, reasons = _decision(summary, walk, policy)
    assert summary["samples"] == len(frame)
    assert summary["date_block_ci95"][0] > 0
    assert walk["positive_rate"] == 1.0
    assert decision == "ADOPT"
    assert reasons == []


def test_negative_strategy_is_rejected() -> None:
    frame = _frame()
    frame["excess_10"] = -0.01
    policy = AdoptionPolicy(bootstrap_samples=100, min_samples=50)
    summary = _summary(frame, "excess_10", policy)
    walk = _walk_forward(frame, "BAD", pd.Series(True, index=frame.index), "excess_10")
    decision, reasons = _decision(summary, walk, policy)
    assert decision == "REJECT"
    assert "mean" in reasons
    assert "block_ci" in reasons


def test_report_publisher_is_serialized_and_retries_after_rebase() -> None:
    workflow = Path(".github/workflows/research-adoption-validation.yml").read_text(encoding="utf-8")
    assert "group: intelligence-engine-main" in workflow
    assert "for attempt in 1 2 3 4" in workflow
    assert workflow.index("git rebase origin/main") < workflow.index("git push origin HEAD:main")
    assert "Failed to publish adoption report after retries" in workflow
