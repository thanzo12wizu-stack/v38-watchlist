from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from intelligence_engine.pipeline import load_universe
from intelligence_engine.prices import load_price_map
from intelligence_engine.research_prices import build_price_panel
from intelligence_engine.research_storage import write_json


def _frame(periods: int, drift: float) -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-02", periods=periods)
    returns = np.full(periods, drift)
    close = 50.0 * np.exp(np.cumsum(returns))
    return pd.DataFrame(
        {
            "Open": close,
            "High": close * 1.01,
            "Low": close * .99,
            "Close": close,
            "Volume": 1_500_000,
        },
        index=dates,
    )


def test_partial_history_keeps_available_rs_and_leaves_long_horizons_missing():
    prices = {"QQQ": _frame(180, .0002), "FAST": _frame(180, .0010)}
    universe = pd.DataFrame(
        {
            "ticker": ["FAST"],
            "sector": ["Technology"],
            "industry": ["Software"],
            "market_cap": [10_000_000_000],
        }
    )
    panel = build_price_panel(
        prices,
        universe,
        start=pd.Timestamp("2025-01-02"),
        end=pd.Timestamp("2026-01-31"),
    )
    assert not panel.empty
    latest = panel.iloc[-1]
    assert pd.notna(latest["rs_raw_63"])
    assert pd.notna(latest["rs_raw_126"])
    assert pd.isna(latest["rs_raw_189"])
    assert latest["history_sessions"] == 180


def test_research_json_normalizes_nested_non_finite_values(tmp_path: Path):
    path = tmp_path / "strict.json"
    write_json(
        path,
        {
            "score": np.nan,
            "edge": np.inf,
            "nested": [1.0, -np.inf, {"value": np.float64(2.5)}],
        },
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload == {
        "score": None,
        "edge": None,
        "nested": [1.0, None, {"value": 2.5}],
    }


def test_repository_price_shapes_can_bootstrap_research():
    root = Path(__file__).resolve().parents[1]
    price_path = root / "prices.pkl"
    universe_path = root / "universe.csv"
    if not price_path.exists() or not universe_path.exists():
        pytest.skip("repository price inputs are not available")

    prices = load_price_map(price_path)
    qqq = prices.get("QQQ")
    if qqq is None or qqq.empty:
        pytest.skip("QQQ is not present in the repository cache")

    universe = load_universe(universe_path).reset_index(drop=True)
    valid = []
    available = set(universe["ticker"].astype(str).str.upper())
    for ticker, frame in prices.items():
        symbol = str(ticker).upper()
        if symbol != "QQQ" and symbol in available and frame is not None and len(frame) >= 80:
            valid.append(symbol)
        if len(valid) >= 25:
            break
    if not valid:
        pytest.skip("no sampled ticker has 80 sessions")

    subset = {"QQQ": qqq, **{ticker: prices[ticker] for ticker in valid}}
    dates = pd.to_datetime(qqq.index, errors="coerce")
    end = pd.Timestamp(dates.max()).tz_localize(None) if getattr(dates, "tz", None) is not None else pd.Timestamp(dates.max())
    panel = build_price_panel(
        subset,
        universe,
        start=end - pd.Timedelta(days=160),
        end=end,
        stride=5,
    )
    assert not panel.empty
    assert panel["ticker"].nunique() >= 1
