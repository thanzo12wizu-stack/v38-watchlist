from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from intelligence_engine.ensure_prices import run as ensure_prices
from intelligence_engine.prices import save_price_map
from intelligence_engine.research_contracts import ResearchConfig
from intelligence_engine.research_decision_dashboard import build_html
from intelligence_engine.research_engine import rank_signals
from intelligence_engine.research_expectancy import build_research_expectancy
from intelligence_engine.research_storage import upsert_year_partitions, write_json


def _price_frame(start: str = "2016-01-04", periods: int = 2600) -> pd.DataFrame:
    dates = pd.bdate_range(start, periods=periods)
    close = 100 * np.exp(np.linspace(0, .8, periods))
    return pd.DataFrame(
        {
            "open": close,
            "high": close * 1.01,
            "low": close * .99,
            "close": close,
            "volume": 1_500_000,
        },
        index=dates,
    )


def test_research_config_enforces_ten_year_retention() -> None:
    config = ResearchConfig(years=5)
    assert config.years == 10
    assert config.primary_window_years == 8
    assert config.analysis_windows == (10, 8, 5, 3)


def test_ensure_prices_clamps_requested_history_to_ten_years(tmp_path: Path, monkeypatch) -> None:
    universe = tmp_path / "universe.csv"
    pd.DataFrame({"ticker": ["AAA"], "sector": ["Tech"], "industry": ["Software"]}).to_csv(universe, index=False)
    cache = tmp_path / "prices.pkl"
    save_price_map(cache, {"QQQ": _price_frame("2021-01-04", 900), "AAA": _price_frame("2021-01-04", 900)})

    class FakeProvider:
        name = "fake"

        def __init__(self) -> None:
            self.calls: list[tuple[tuple[str, ...], str]] = []

        def download(self, tickers, *, period="18mo"):
            normalized = tuple(str(ticker) for ticker in tickers)
            self.calls.append((normalized, period))
            start = "2016-01-04" if period == "10y" else "2025-01-02"
            periods = 2600 if period == "10y" else 80
            return ({ticker: _price_frame(start, periods) for ticker in normalized}, {"requested": len(normalized), "received": len(normalized)})

    provider = FakeProvider()
    monkeypatch.setattr("intelligence_engine.ensure_prices.get_price_provider", lambda _name=None: provider)
    result = ensure_prices(universe, cache, min_coverage=.5, history_years=5, max_history_tickers=2)
    assert result["history_years"] == 10
    assert any(period == "10y" for _, period in provider.calls)


def _outcomes() -> pd.DataFrame:
    dates = pd.date_range("2017-01-31", "2026-06-30", freq="14D")
    rows = []
    for index, date in enumerate(dates):
        if date >= pd.Timestamp("2022-01-01"):
            excess = -.01 if index % 3 else .002
        else:
            excess = .018 if index % 4 else .006
        rows.append(
            {
                "ticker": f"T{index % 12:02d}",
                "date": date,
                "candidate_archetype": "EMERGING_LEADER",
                "setup": "PRE_BREAKOUT",
                "market_regime": "GREEN",
                "rs_archetype": "ACCELERATING_LEADER",
                "financial_phase": "ACCELERATING",
                "pct_rs_raw_63": 90.0,
                "eps_yoy": .35,
                "stop_risk_pct": 5.0,
                "reward_risk_raw": 3.0,
                "excess_5": excess * .6,
                "excess_10": excess,
                "excess_21": excess * 1.2,
                "excess_63": excess * 1.5,
                "outcome_date_5": date + pd.Timedelta(days=7),
                "outcome_date_10": date + pd.Timedelta(days=14),
                "outcome_date_21": date + pd.Timedelta(days=30),
                "outcome_date_63": date + pd.Timedelta(days=90),
            }
        )
    return pd.DataFrame(rows)


def test_expectancy_builds_10_8_5_3_year_windows() -> None:
    result = build_research_expectancy(_outcomes(), min_samples=10, bootstrap_samples=30)
    assert result["primary_window_years"] == 8
    assert result["comparison_windows_years"] == [10, 8, 5, 3]
    assert {window["window_years"] for window in result["windows"]} == {10, 8, 5, 3}
    assert result["groups"]


def test_rank_signals_weakens_conflicting_recent_expectancy() -> None:
    def row(years: int, edge: float, qualification: str = "QUALIFIED") -> dict:
        return {
            "window_years": years,
            "groups": [
                {
                    "group_type": "archetype_setup",
                    "candidate_archetype": "EMERGING_LEADER",
                    "setup": "PRE_BREAKOUT",
                    "horizon": 10,
                    "mean_excess_return": edge,
                    "qualification": qualification,
                    "samples": 120,
                }
            ],
        }

    expectancy = {"windows": [row(10, .025), row(8, .02), row(5, -.01), row(3, -.015)]}
    signals = pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "date": pd.Timestamp("2026-06-30"),
                "candidate_archetype": "EMERGING_LEADER",
                "setup": "PRE_BREAKOUT",
                "entry_state": "READY",
                "base_composite": 80.0,
                "risk_fit": 80.0,
                "research_confidence": .9,
                "hard_blocks": [],
            }
        ]
    )
    ranked = rank_signals(signals, expectancy)
    assert ranked.iloc[0]["expectancy_consistency"] == "CONFLICT"
    assert ranked.iloc[0]["expectancy_consistency_factor"] == .25
    assert abs(ranked.iloc[0]["expectancy_adjustment"]) <= 2.5


def test_research_dashboard_builds_from_rank_partitions(tmp_path: Path) -> None:
    root = tmp_path / "research"
    ranking = pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "date": pd.Timestamp("2026-06-30"),
                "research_rank": 1,
                "decision_status": "ACTIONABLE",
                "candidate_archetype": "EMERGING_LEADER",
                "financial_phase": "ACCELERATING",
                "rs_archetype": "ACCELERATING_LEADER",
                "setup": "PRE_BREAKOUT",
                "entry_state": "READY",
                "composite_rank_score": 88.2,
                "fundamental_quality": 82.0,
                "fundamental_change": 91.0,
                "leadership_quality": 89.0,
                "entry_quality": 78.0,
                "risk_fit": 80.0,
                "expected_edge_10d_8y": .018,
                "expected_edge_10d_5y": .014,
                "expected_edge_10d_3y": .01,
                "expectancy_status": "QUALIFIED",
                "expectancy_consistency": "CONFIRMED",
                "expectancy_samples": 140,
                "hard_blocks": [],
            }
        ]
    )
    upsert_year_partitions(root, "rankings", ranking, date_column="date", keys=("ticker", "date"), retention_years=10, reference_date=pd.Timestamp("2026-06-30"))
    write_json(root / "manifest.json", {"generated_at": "2026-06-30T22:00:00Z", "years_retained": 10, "tickers": 1, "signal_rows": 10, "outcome_rows": 8, "ranking_rows": 1})
    write_json(root / "expectancy.json", {"primary_window_years": 8, "comparison_windows_years": [10, 8, 5, 3], "windows": [], "walk_forward": [], "leave_one_year_out": []})
    page = build_html(root)
    assert "Research Decision" in page
    assert "AAA" in page
    assert "8年を標準" in page
    assert "買える" in page
