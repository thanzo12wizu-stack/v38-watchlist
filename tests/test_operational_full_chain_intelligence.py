from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from intelligence_engine.command_layer import run as run_command_layer
from intelligence_engine.config import EngineConfig
from intelligence_engine.intelligence_dashboard import build_html, generate, load_payload
from intelligence_engine.operational_pipeline import (
    build_robust_expectancy,
    detect_leader_transitions,
)
from intelligence_engine.pipeline import build
from intelligence_engine.validate_outputs import validate


def _price_frame(seed: int, periods: int = 320) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=periods)
    returns = rng.normal(0.0005 + seed * 0.00001, 0.012, periods)
    close = 30.0 * np.exp(np.cumsum(returns))
    high = close * (1 + rng.uniform(0.002, 0.018, periods))
    low = close * (1 - rng.uniform(0.002, 0.018, periods))
    volume = rng.integers(1_000_000, 5_000_000, periods)
    return pd.DataFrame(
        {
            "open": close * (1 + rng.normal(0, 0.002, periods)),
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        },
        index=dates,
    )


def _write_external_fixture(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    now = pd.Timestamp.utcnow().isoformat()
    future = (pd.Timestamp.today().normalize() + pd.Timedelta(days=30)).date().isoformat()
    pd.DataFrame(
        [{"ticker": "AAA", "event_date": future, "fetched_at": now}]
    ).to_csv(root / "earnings_calendar.csv", index=False)
    pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "metric": "eps",
                "revision_breadth_30d_pct": 20.0,
                "fetched_at": now,
            }
        ]
    ).to_csv(root / "estimate_revisions.csv", index=False)
    pd.DataFrame(
        [{"ticker": "AAA", "direction": "RAISED", "fetched_at": now}]
    ).to_csv(root / "guidance.csv", index=False)
    pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "published_at": now,
                "headline": "Company wins major contract",
                "event_type": "CONTRACT",
                "fetched_at": now,
            }
        ]
    ).to_csv(root / "news.csv", index=False)
    pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "filed_at": now,
                "transaction": "BUY",
                "value": 2_000_000,
                "fetched_at": now,
            }
        ]
    ).to_csv(root / "insider.csv", index=False)
    pd.DataFrame(
        [{"ticker": "AAA", "holder": "Fund A", "fetched_at": now}]
    ).to_csv(root / "holdings_13f.csv", index=False)
    pd.DataFrame(
        [{"ticker": "AAA", "status": "ok", "fetched_at": now}]
    ).to_csv(root / "provider_coverage.csv", index=False)


def test_pipeline_command_layer_contract_and_dashboard(tmp_path: Path) -> None:
    tickers = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG", "HHH"]
    universe = pd.DataFrame(
        {
            "ticker": tickers,
            "sector": [
                "Technology",
                "Technology",
                "Industrials",
                "Industrials",
                "Financials",
                "Financials",
                "Health Care",
                "Health Care",
            ],
            "industry": [
                "Software",
                "Software",
                "Machinery",
                "Machinery",
                "Banks",
                "Banks",
                "Medical Devices",
                "Medical Devices",
            ],
            "market_cap": [
                5_000_000_000 + index * 100_000_000
                for index in range(len(tickers))
            ],
        }
    )
    universe_path = tmp_path / "universe.csv"
    universe.to_csv(universe_path, index=False)
    prices = {ticker: _price_frame(index + 1) for index, ticker in enumerate(tickers)}
    prices["QQQ"] = _price_frame(99)
    prices_path = tmp_path / "prices.pkl"
    pd.to_pickle(prices, prices_path)

    output = tmp_path / "data" / "intelligence"
    config = EngineConfig(
        universe_path,
        prices_path,
        output,
        tmp_path / "data" / "sec_companyfacts",
        output / "history",
        300,
        100,
    )
    manifest = build(config)
    assert manifest["eligible_count"] > 0

    external_root = tmp_path / "data" / "external"
    _write_external_fixture(external_root)
    result = run_command_layer(
        output,
        prices_path,
        tmp_path / "portfolio.csv",
        external_root,
    )
    assert result["snapshot"] == "CREATED"
    assert validate(output) == []

    index = json.loads((output / "index.json").read_text(encoding="utf-8"))
    assert index["portfolio_doctor"]["status"] == "NO_POSITIONS"
    assert "morning_brief" in index
    assert "robust_expectancy" in index
    assert "data_quality" in index
    external = next(row for row in index["external_data"] if row["ticker"] == "AAA")
    assert external["eps_revision_30d_pct"] == 20.0
    assert external["guidance_direction"] == "RAISED"
    assert external["event_type"] == "CONTRACT"
    assert external["insider_signal"] == "BUY"

    target = tmp_path / "intelligence-dashboard.html"
    generate(output / "index.json", target)
    html = target.read_text(encoding="utf-8")
    assert "V38 Intelligence Dashboard" in html
    assert "CONTRACT" in html
    assert "AAA" in html


def test_bootstrap_dashboard_unwraps_individual_json_contracts(tmp_path: Path) -> None:
    root = tmp_path / "data" / "intelligence"
    root.mkdir(parents=True)
    (root / "sector_rotation.json").write_text(
        json.dumps({"sectors": [{"sector": "Technology", "score_rotation": 0.8}]}),
        encoding="utf-8",
    )
    (root / "theme_intelligence.json").write_text(
        json.dumps({"themes": [{"theme": "Software", "score_theme": 0.9}]}),
        encoding="utf-8",
    )
    (root / "entry_candidates.json").write_text(
        json.dumps({"candidates": [{"ticker": "AAA", "actionable": True}]}),
        encoding="utf-8",
    )
    payload = load_payload(root / "index.json")
    assert isinstance(payload["sector_rotation"], list)
    assert isinstance(payload["theme_intelligence"], list)
    assert isinstance(payload["entry_candidates"], list)
    assert "AAA" in build_html(payload)


def _stock(ticker: str, rs: float) -> dict:
    return {
        "ticker": ticker,
        "features": {
            "pct_rs_raw_63": rs,
            "pct_rs_raw_126": rs,
            "pct_rs_raw_189": rs,
        },
    }


def test_leader_transition_ignores_current_day_history(tmp_path: Path) -> None:
    history = tmp_path / "history"
    history.mkdir()
    prior = {
        "manifest": {"asof": "2026-07-21"},
        "stocks": [_stock("AAA", 0.9), _stock("BBB", 0.8)],
        "theme_intelligence": [
            {"theme": "Software", "score_theme": 0.5, "phase": "IMPROVING"}
        ],
    }
    current = {
        "manifest": {"asof": "2026-07-22"},
        "stocks": [_stock("AAA", 0.7), _stock("BBB", 0.95)],
        "theme_intelligence": [
            {"theme": "Software", "score_theme": 0.8, "phase": "LEADING"}
        ],
    }
    (history / "2026-07-21.json").write_text(json.dumps(prior), encoding="utf-8")
    (history / "2026-07-22.json").write_text(json.dumps(current), encoding="utf-8")

    result = detect_leader_transitions(current, history)
    assert result["compared_to"] == "2026-07-21"
    bbb = next(
        row
        for row in result["rank_changes"]
        if row["ticker"] == "BBB" and row["window"] == 63
    )
    assert bbb["previous_rank"] == 2
    assert bbb["current_rank"] == 1
    assert bbb["rank_change"] == 1
    assert result["changes"]["themes"][0]["score_change"] == pytest.approx(0.3)


def test_walk_forward_selects_setup_separately_by_horizon(tmp_path: Path) -> None:
    ledger = tmp_path / "observations"
    ledger.mkdir()
    train = {
        "asof": "2019-01-02",
        "market_state": {"regime": "GREEN"},
        "entry_candidates": [
            {"ticker": "AAA", "setup": "PULLBACK"},
            {"ticker": "BBB", "setup": "BREAKOUT"},
        ],
        "outcomes": {
            "AAA": {"horizons": {"5": {"excess_return": 0.10}, "10": {"excess_return": -0.10}}},
            "BBB": {"horizons": {"5": {"excess_return": -0.10}, "10": {"excess_return": 0.10}}},
        },
    }
    test = {
        "asof": "2020-01-02",
        "market_state": {"regime": "GREEN"},
        "entry_candidates": [
            {"ticker": "AAA", "setup": "PULLBACK"},
            {"ticker": "BBB", "setup": "BREAKOUT"},
        ],
        "outcomes": {
            "AAA": {"horizons": {"5": {"excess_return": 0.02}, "10": {"excess_return": -0.02}}},
            "BBB": {"horizons": {"5": {"excess_return": -0.02}, "10": {"excess_return": 0.02}}},
        },
    }
    (ledger / "2019-01-02.json").write_text(json.dumps(train), encoding="utf-8")
    (ledger / "2020-01-02.json").write_text(json.dumps(test), encoding="utf-8")

    robust = build_robust_expectancy(ledger)
    selected = {
        (row["horizon"], row["test_year"]): row["selected_setup"]
        for row in robust["walk_forward"]
    }
    assert selected[(5, 2020)] == "PULLBACK"
    assert selected[(10, 2020)] == "BREAKOUT"
