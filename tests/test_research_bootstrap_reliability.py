from __future__ import annotations

import numpy as np
import pandas as pd

from intelligence_engine.research_contracts import ResearchConfig
from intelligence_engine.research_pipeline import (
    MAX_INCREMENTAL_CATCHUP_CALENDAR_DAYS,
    _date_range,
)
from intelligence_engine.research_prices import build_price_panel


def _prices(seed: int, periods: int = 320) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2025-01-02", periods=periods)
    returns = rng.normal(.0005, .01, periods)
    close = 50 * np.exp(np.cumsum(returns))
    return pd.DataFrame(
        {
            "open": close,
            "high": close * (1 + rng.uniform(.002, .015, periods)),
            "low": close * (1 - rng.uniform(.002, .015, periods)),
            "close": close,
            "volume": rng.integers(800_000, 2_000_000, periods),
        },
        index=dates,
    )


def test_initial_incremental_run_uses_latest_session_only() -> None:
    prices = {"QQQ": _prices(1)}
    config = ResearchConfig(years=10)
    start, end = _date_range(
        prices,
        config,
        mode="incremental",
        year=None,
        start=None,
        end=None,
        existing_signals=pd.DataFrame(),
    )
    assert start == end
    assert end == pd.Timestamp(prices["QQQ"].index.max()).normalize()


def test_incremental_catchup_is_capped() -> None:
    prices = {"QQQ": _prices(1)}
    latest = pd.Timestamp(prices["QQQ"].index.max()).normalize()
    existing = pd.DataFrame({"date": [latest - pd.Timedelta(days=120)]})
    start, end = _date_range(
        prices,
        ResearchConfig(years=10),
        mode="incremental",
        year=None,
        start=None,
        end=None,
        existing_signals=existing,
    )
    assert end == latest
    assert start == latest - pd.Timedelta(days=MAX_INCREMENTAL_CATCHUP_CALENDAR_DAYS)


def test_backfill_without_year_is_bounded_to_current_price_year() -> None:
    prices = {"QQQ": _prices(1)}
    latest = pd.Timestamp(prices["QQQ"].index.max()).normalize()
    start, end = _date_range(
        prices,
        ResearchConfig(years=10),
        mode="backfill",
        year=None,
        start=None,
        end=None,
        existing_signals=pd.DataFrame(),
    )
    assert start == pd.Timestamp(latest.year, 1, 1)
    assert end == latest


def test_peer_rank_handles_text_blank_and_float_nan_dimensions() -> None:
    prices = {
        "QQQ": _prices(1),
        "AAA": _prices(2),
        "BBB": _prices(3),
        "CCC": _prices(4),
    }
    universe = pd.DataFrame(
        {
            "ticker": ["AAA", "BBB", "CCC"],
            "sector": ["Technology", "Technology", np.nan],
            "industry": ["Software", np.nan, ""],
            "market_cap": [10e9, 8e9, 6e9],
        }
    )
    latest = pd.Timestamp(prices["QQQ"].index.max()).normalize()
    panel = build_price_panel(
        prices,
        universe,
        start=latest - pd.Timedelta(days=45),
        end=latest,
        stride=1,
    )
    assert not panel.empty
    assert "sector_rank_pct" in panel
    assert "industry_rank_pct" in panel
    assert panel["sector_rank_pct"].notna().any()
    assert panel["industry_rank_pct"].notna().any()
    assert set(panel["ticker"].unique()) == {"AAA", "BBB", "CCC"}
