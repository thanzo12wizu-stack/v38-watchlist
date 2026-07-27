from pathlib import Path

import pandas as pd

from intelligence_engine.ab_stage_data import ExperimentConfig
from intelligence_engine.ab_stage_v2_models import (
    competing_target,
    simulate_portfolio_mtm,
    stage_weight_multiplier,
)
from intelligence_engine.ab_stage_v2_policy import incremental_verdicts


def price_frame(dates, opens, closes):
    return pd.DataFrame({
        "open": opens,
        "high": [max(o, c) * 1.01 for o, c in zip(opens, closes)],
        "low": [min(o, c) * .99 for o, c in zip(opens, closes)],
        "close": closes,
        "volume": [1_000_000] * len(dates),
    }, index=pd.to_datetime(dates))


def test_competing_target_is_mutually_exclusive():
    frame = pd.DataFrame({
        "hit_3r_before_1r_15": [1, 0, 0],
        "stop_before_3r_15": [0, 1, 0],
    })
    assert competing_target(frame).tolist() == [2, 0, 1]


def test_stage_weight_blocks_broken_individual_stage():
    row = pd.Series({
        "individual_stage": "4B",
        "market_stage": "2A",
        "sector_stage_score": 90,
    })
    assert stage_weight_multiplier(row) == 0.0


def test_exit_today_does_not_free_opening_slot():
    dates = ["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07"]
    prices = {
        "QQQ": price_frame(dates, [100, 100, 101, 102], [100, 101, 102, 103]),
        "AAA": price_frame(dates, [10, 10, 11, 11], [10, 11, 11, 11]),
        "BBB": price_frame(dates, [20, 20, 20, 22], [20, 20, 22, 22]),
    }
    frame = pd.DataFrame([
        {
            "ticker": "AAA", "date": "2026-01-02", "entry_date": "2026-01-05",
            "entry_price": 10.0, "trade_exit_date": "2026-01-06",
            "trade_return_gross": .10, "outcome_date_10": "2026-01-06",
            "return_10": .10, "risk_fraction": .05,
            "individual_stage": "2A", "market_stage": "2A", "sector_stage_score": 80,
        },
        {
            "ticker": "BBB", "date": "2026-01-05", "entry_date": "2026-01-06",
            "entry_price": 20.0, "trade_exit_date": "2026-01-07",
            "trade_return_gross": .10, "outcome_date_10": "2026-01-07",
            "return_10": .10, "risk_fraction": .05,
            "individual_stage": "2A", "market_stage": "2A", "sector_stage_score": 80,
        },
    ])
    config = ExperimentConfig(
        research_root=Path("."), prices_path=Path("prices.pkl"), output_dir=Path("."),
        max_positions=1, risk_per_trade=.006, max_position_weight=.08,
    )
    result = simulate_portfolio_mtm(
        frame, pd.Series([1.0, 1.0]), prices, config,
        mode="PATH", stage_sizing=False,
    )
    assert result["trade_count"] == 1


def test_adoption_requires_improvement_and_no_guardrail_break():
    summary = pd.DataFrame([
        {
            "spec": 11, "mean_top10_excess_return": .01, "mean_hit_3r_rate": .20,
            "mean_early_failure_rate": .40, "mean_brier_skill": .01,
            "mean_profit_factor": 1.1, "worst_max_drawdown": -.20,
            "mean_portfolio_return": .10, "total_trades": 100,
        },
        {
            "spec": 12, "mean_top10_excess_return": .01, "mean_hit_3r_rate": .20,
            "mean_early_failure_rate": .40, "mean_brier_skill": .01,
            "mean_profit_factor": 1.25, "worst_max_drawdown": -.19,
            "mean_portfolio_return": .11, "total_trades": 80,
        },
    ])
    verdict = incremental_verdicts(summary)[0]
    assert verdict["verdict"] == "ADOPT"
    assert "PF" in verdict["material_improvements"]
