from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from intelligence_engine.config import EngineConfig
from intelligence_engine.intelligence_dashboard import build_html
from intelligence_engine.market import build_market_state
from intelligence_engine.pipeline import build
from intelligence_engine.validate_outputs import validate


def _price_frame(seed: int, periods: int = 320) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=periods)
    returns = rng.normal(0.0004 + seed * 0.00003, 0.01, periods)
    close = 30.0 * np.exp(np.cumsum(returns))
    high = close * (1 + rng.uniform(0.003, 0.015, periods))
    low = close * (1 - rng.uniform(0.003, 0.015, periods))
    volume = rng.integers(1_000_000, 3_000_000, periods)
    return pd.DataFrame(
        {
            "open": close,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        },
        index=dates,
    )


def test_pipeline_without_sec_data_emits_finite_scores_and_strict_json(tmp_path: Path):
    tickers = ["AAA", "BBB", "CCC", "DDD"]
    universe = pd.DataFrame(
        {
            "ticker": tickers,
            "sector": ["Technology", "Technology", "Industrials", "Industrials"],
            "industry": ["Software", "Software", "Machinery", "Machinery"],
            "market_cap": [5_000_000_000] * len(tickers),
        }
    )
    universe_path = tmp_path / "universe.csv"
    universe.to_csv(universe_path, index=False)
    prices = {ticker: _price_frame(index + 1) for index, ticker in enumerate(tickers)}
    prices["QQQ"] = _price_frame(99)
    prices_path = tmp_path / "prices.pkl"
    pd.to_pickle(prices, prices_path)
    output = tmp_path / "data" / "intelligence"

    manifest = build(
        EngineConfig(
            universe_path,
            prices_path,
            output,
            tmp_path / "data" / "sec_companyfacts",
            output / "history",
            300,
            100,
        )
    )

    assert manifest["eligible_count"] == len(tickers)
    assert validate(output) == []
    index_text = (output / "index.json").read_text(encoding="utf-8")
    assert "NaN" not in index_text
    assert "Infinity" not in index_text
    index = json.loads(index_text)
    assert index["stocks"]
    for stock in index["stocks"]:
        for name in ("candidate", "leader", "entry"):
            value = stock["scores"].get(name)
            assert value is not None
            assert math.isfinite(float(value))
            assert 0 <= float(value) <= 100
        assert stock["scores"].get("story") is None
        assert stock["story_confidence"] == 0.0

    market = index["market_state"]
    assert market["recommended_exposure_pct"] == market["recommended_exposure"] * 100
    rendered = build_html({**index, "data_quality": {"status": "PASS", "warnings": []}})
    assert f"{market['recommended_exposure_pct']:.1f}%" in rendered


def test_market_state_accepts_missing_cross_section_columns():
    frame = pd.DataFrame({"ticker": ["AAA", "BBB"], "price": [10.0, 20.0]})
    market = build_market_state(frame, _price_frame(10), [])
    assert market["breadth"]["above_sma50"] is None
    assert market["breadth"]["positive_rs63"] is None
    assert market["score_confidence"] == pytest.approx(.30)
    assert market["recommended_exposure_pct"] == market["recommended_exposure"] * 100
