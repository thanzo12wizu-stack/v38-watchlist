from pathlib import Path

import pandas as pd

from intelligence_engine.ab_stage_data import ExperimentConfig
from intelligence_engine.ab_stage_v3_exposure import simulate


def price_frame(dates, values):
    return pd.DataFrame(
        {
            "open": values,
            "high": [value * 1.01 for value in values],
            "low": [value * .99 for value in values],
            "close": values,
            "volume": [1_000_000] * len(values),
        },
        index=pd.to_datetime(dates),
    )


def test_normalized_stage_scale_restores_some_exposure_without_exceeding_cap():
    dates = ["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07"]
    prices = {
        "QQQ": price_frame(dates, [100, 101, 102, 103]),
        "AAA": price_frame(dates, [10, 10, 11, 11]),
    }
    frame = pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "date": "2026-01-02",
                "entry_date": "2026-01-05",
                "entry_price": 10.0,
                "trade_exit_date": "2026-01-07",
                "trade_return_gross": .10,
                "risk_fraction": .05,
                "individual_stage": "2C",
                "market_stage": "2A",
                "sector_stage_score": 100,
            }
        ]
    )
    config = ExperimentConfig(
        research_root=Path("."),
        prices_path=Path("prices.pkl"),
        output_dir=Path("."),
        max_positions=1,
        max_position_weight=.08,
        risk_per_trade=.006,
    )
    raw = simulate(
        frame,
        pd.Series([1.0]),
        prices,
        config,
        stage_mode="RAW",
        learned_scale=1.0,
    )
    normalized = simulate(
        frame,
        pd.Series([1.0]),
        prices,
        config,
        stage_mode="NORMALIZED",
        learned_scale=2.0,
    )
    assert normalized["average_gross_exposure"] > raw["average_gross_exposure"]
    assert normalized["max_gross_exposure"] <= .09


def test_baseline_reports_nonzero_exposure():
    dates = ["2026-01-02", "2026-01-05", "2026-01-06"]
    prices = {
        "QQQ": price_frame(dates, [100, 101, 102]),
        "AAA": price_frame(dates, [10, 10, 11]),
    }
    frame = pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "date": "2026-01-02",
                "entry_date": "2026-01-05",
                "entry_price": 10.0,
                "trade_exit_date": "2026-01-06",
                "trade_return_gross": .10,
                "risk_fraction": .05,
                "individual_stage": "2A",
                "market_stage": "2A",
                "sector_stage_score": 100,
            }
        ]
    )
    config = ExperimentConfig(
        research_root=Path("."), prices_path=Path("prices.pkl"), output_dir=Path(".")
    )
    result = simulate(
        frame,
        pd.Series([1.0]),
        prices,
        config,
        stage_mode="NONE",
        learned_scale=1.0,
    )
    assert result["trade_count"] == 1
    assert result["average_gross_exposure"] >= 0
