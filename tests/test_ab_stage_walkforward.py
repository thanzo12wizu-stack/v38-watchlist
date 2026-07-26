from __future__ import annotations

import numpy as np
import pandas as pd

from intelligence_engine.ab_stage_data import classify_stage_series, first_hit, stage_history_features
from intelligence_engine.ab_stage_models import aggregate, incremental_verdicts


def price_frame(values: list[float]) -> pd.DataFrame:
    index = pd.bdate_range("2024-01-01", periods=len(values))
    close = pd.Series(values, index=index, dtype=float)
    return pd.DataFrame({
        "open": close, "high": close * 1.01, "low": close * .99,
        "close": close, "volume": 1_000_000,
    }, index=index)


def test_first_hit_is_conservative_when_both_boundaries_touch_same_day():
    result, day = first_hit(np.array([111.0]), np.array([94.0]), upper=110.0, lower=95.0)
    assert result == "LOWER"
    assert day == 1


def test_stage_history_counts_days_and_transition_direction():
    result = stage_history_features(pd.Series(["1A", "1A", "2A", "2A", "3A"]))
    assert result["stage_days"].tolist() == [1.0, 2.0, 1.0, 2.0, 1.0]
    assert result.loc[2, "stage_upgrade"] == 1.0
    assert result.loc[4, "stage_downgrade"] == 1.0


def test_stage_classifier_recognizes_rising_state():
    stage = classify_stage_series(price_frame(np.linspace(50, 120, 260).tolist()))
    assert stage.iloc[-1] in {"2A", "2B", "2C"}


def test_aggregate_counts_qqq_outperformance_years():
    rows = []
    for year, strategy, qqq in [(2020, .20, .10), (2021, .05, .08)]:
        rows.append({
            "spec": 1, "spec_name": "RS189のみ", "test_year": year,
            "daily_spearman_ic": .02, "top10_excess_return": .01,
            "top10_hit_3r_rate": .4, "top10_early_failure_rate": .2,
            "brier_score": .23, "profit_factor": 1.3, "max_drawdown": -.1,
            "portfolio_return": strategy, "qqq_return": qqq, "trade_count": 10,
        })
    summary = aggregate(pd.DataFrame(rows))
    assert int(summary.iloc[0]["qqq_excess_years"]) == 1
    assert int(summary.iloc[0]["positive_years"]) == 2


def test_stage_increment_rejected_when_only_trade_count_changes():
    summary = pd.DataFrame([
        {"spec": 3, "mean_top10_excess_return": .01, "mean_hit_3r_rate": .4,
         "mean_early_failure_rate": .2, "mean_brier_score": .2,
         "mean_profit_factor": 1.2, "worst_max_drawdown": -.15, "total_trades": 100},
        {"spec": 4, "mean_top10_excess_return": .01, "mean_hit_3r_rate": .4,
         "mean_early_failure_rate": .2, "mean_brier_score": .2,
         "mean_profit_factor": 1.2, "worst_max_drawdown": -.15, "total_trades": 70},
    ])
    verdict = incremental_verdicts(summary)[0]
    assert verdict["verdict"] == "REJECT"
    assert verdict["trade_count_change"] == -30
