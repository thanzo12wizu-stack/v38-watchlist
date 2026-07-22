from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from intelligence_engine.config import EngineConfig
from intelligence_engine.pipeline import build
from intelligence_engine.story import add_story_intelligence


def _price_frame(seed: int, periods: int = 320) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2024-01-02", periods=periods)
    drift = 0.0004 + seed * 0.00002
    returns = rng.normal(drift, 0.012, periods)
    close = 30.0 * np.exp(np.cumsum(returns))
    high = close * (1 + rng.uniform(0.002, 0.018, periods))
    low = close * (1 - rng.uniform(0.002, 0.018, periods))
    volume = rng.integers(1_000_000, 5_000_000, periods)
    return pd.DataFrame({"open": close * (1 + rng.normal(0, 0.002, periods)), "high": high, "low": low, "close": close, "volume": volume}, index=dates)


def test_story_accepts_missing_scalar_and_duplicate_inputs() -> None:
    base = pd.DataFrame({"ticker": ["AAA", "BBB", "CCC"], "score_candidate": [80.0, 70.0, 60.0]})
    result = add_story_intelligence(base)
    assert len(result) == 3
    assert {"story_growth_raw", "score_story", "story_phase"}.issubset(result.columns)

    duplicate = pd.DataFrame(np.array([[0.10, 0.20], [0.30, np.nan], [np.nan, 0.40]]), columns=["eps_yoy", "eps_yoy"])
    duplicate.insert(0, "ticker", ["AAA", "BBB", "CCC"])
    duplicate["score_candidate"] = [80.0, 70.0, 60.0]
    result_duplicate = add_story_intelligence(duplicate)
    assert len(result_duplicate) == 3
    assert result_duplicate["story_growth_raw"].notna().any()


def test_pipeline_builds_without_sec_cache_and_writes_contract(tmp_path: Path) -> None:
    tickers = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG", "HHH"]
    universe = pd.DataFrame({"ticker": tickers, "sector": ["Technology", "Technology", "Industrials", "Industrials", "Financials", "Financials", "Health Care", "Health Care"], "industry": ["Software", "Semiconductors", "Machinery", "Aerospace", "Banks", "Capital Markets", "Medical Devices", "Biotechnology"], "market_cap": [5_000_000_000 + i * 100_000_000 for i in range(len(tickers))]})
    universe_path = tmp_path / "universe.csv"
    universe.to_csv(universe_path, index=False)
    prices = {ticker: _price_frame(i + 1) for i, ticker in enumerate(tickers)}
    prices["QQQ"] = _price_frame(99)
    prices_path = tmp_path / "prices.pkl"
    pd.to_pickle(prices, prices_path)
    output = tmp_path / "data" / "intelligence"
    config = EngineConfig(universe_path, prices_path, output, tmp_path / "data" / "sec_companyfacts", output / "history", 300, 100)
    manifest = build(config)
    assert manifest["price_covered_count"] == len(tickers)
    assert manifest["eligible_count"] > 0
    index = json.loads((output / "index.json").read_text(encoding="utf-8"))
    assert index["stocks"]
    assert "market_state" in index
    assert "entry_candidates" in index
    assert (output / "manifest.json").exists()
    assert (output / "story_intelligence.json").exists()
