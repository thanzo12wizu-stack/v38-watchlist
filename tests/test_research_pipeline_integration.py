from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from intelligence_engine.research_contracts import ResearchConfig
from intelligence_engine.research_pipeline import _point_in_time_rankings, build


def _prices(seed: int, drift: float, periods: int = 700) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2022-01-03", periods=periods)
    returns = rng.normal(drift, .012, periods)
    close = 50 * np.exp(np.cumsum(returns))
    return pd.DataFrame(
        {
            "open": close,
            "high": close * (1 + rng.uniform(.002, .02, periods)),
            "low": close * (1 - rng.uniform(.002, .02, periods)),
            "close": close,
            "volume": rng.integers(1_000_000, 3_000_000, periods),
        },
        index=dates,
    )


def _companyfacts() -> dict:
    def point(start: str, end: str, value: float, filed: str) -> dict:
        return {"start": start, "end": end, "val": value, "filed": filed, "form": "10-Q", "accn": f"{end}-{filed}"}

    quarters = [
        ("2022-01-01", "2022-03-31", "2022-05-01"),
        ("2022-04-01", "2022-06-30", "2022-08-01"),
        ("2022-07-01", "2022-09-30", "2022-11-01"),
        ("2022-10-01", "2022-12-31", "2023-02-01"),
        ("2023-01-01", "2023-03-31", "2023-05-01"),
        ("2023-04-01", "2023-06-30", "2023-08-01"),
        ("2023-07-01", "2023-09-30", "2023-11-01"),
        ("2023-10-01", "2023-12-31", "2024-02-01"),
        ("2024-01-01", "2024-03-31", "2024-05-01"),
        ("2024-04-01", "2024-06-30", "2024-08-01"),
    ]
    revenue = [100, 110, 125, 140, 145, 165, 190, 220, 255, 300]
    eps = [.5, .55, .62, .7, .8, .95, 1.15, 1.4, 1.75, 2.1]
    gross = [value * ratio for value, ratio in zip(revenue, np.linspace(.48, .58, len(revenue)))]
    operating = [value * ratio for value, ratio in zip(revenue, np.linspace(.16, .25, len(revenue)))]
    shares = np.linspace(100, 102, len(revenue))

    def rows(values: list[float]) -> list[dict]:
        return [point(start, end, float(value), filed) for (start, end, filed), value in zip(quarters, values)]

    return {
        "facts": {
            "us-gaap": {
                "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": rows(revenue)}},
                "EarningsPerShareDiluted": {"units": {"USD/shares": rows(eps)}},
                "GrossProfit": {"units": {"USD": rows(gross)}},
                "OperatingIncomeLoss": {"units": {"USD": rows(operating)}},
                "WeightedAverageNumberOfDilutedSharesOutstanding": {"units": {"shares": rows(list(shares))}},
            }
        }
    }


def test_research_pipeline_builds_phase_1_to_8_contract(tmp_path: Path):
    pd.DataFrame(
        {"ticker": ["FAST"], "sector": ["Technology"], "industry": ["Software"], "market_cap": [10_000_000_000]}
    ).to_csv(tmp_path / "universe.csv", index=False)
    pd.to_pickle({"QQQ": _prices(1, .0002), "FAST": _prices(2, .0012)}, tmp_path / "prices.pkl")
    sec_dir = tmp_path / "sec"
    sec_dir.mkdir()
    (sec_dir / "FAST.json").write_text(json.dumps(_companyfacts()), encoding="utf-8")
    intelligence_root = tmp_path / "data" / "intelligence"
    research_root = intelligence_root / "research"
    intelligence_root.mkdir(parents=True)
    (intelligence_root / "index.json").write_text("{}", encoding="utf-8")

    result = build(
        universe_path=tmp_path / "universe.csv",
        price_path=tmp_path / "prices.pkl",
        sec_dir=sec_dir,
        root=research_root,
        mode="backfill",
        years=2,
        start="2024-01-01",
        end="2024-12-31",
        stride=5,
        max_daily_signals=20,
        min_samples=10,
    )

    assert result["signal_rows"] > 0
    assert result["ranking_rows"] > 0
    assert (research_root / "manifest.json").exists()
    assert (research_root / "current_rankings.json").exists()
    assert list((research_root / "signals").glob("year=*.jsonl.gz"))
    payload = json.loads((intelligence_root / "index.json").read_text(encoding="utf-8"))
    assert payload["research"]["schema_version"] == "2.0"
    assert payload["research"]["rankings"]


def test_historical_ranking_does_not_use_future_expectancy():
    signals = pd.DataFrame(
        {
            "ticker": ["A", "B", "A", "B"],
            "date": pd.to_datetime(["2023-06-01", "2023-06-01", "2024-06-03", "2024-06-03"]),
            "candidate_archetype": ["EMERGING_LEADER"] * 4,
            "setup": ["PRE_BREAKOUT"] * 4,
            "base_composite": [80.0, 79.0, 80.0, 79.0],
            "risk_fit": [80.0] * 4,
            "research_confidence": [1.0] * 4,
            "hard_blocks": [[] for _ in range(4)],
            "entry_state": ["READY"] * 4,
        }
    )
    outcomes = pd.DataFrame(
        {
            "ticker": ["A"] * 60,
            "date": pd.to_datetime(["2024-01-02"] * 60),
            "candidate_archetype": ["EMERGING_LEADER"] * 60,
            "setup": ["PRE_BREAKOUT"] * 60,
            "outcome_date_10": pd.to_datetime(["2024-02-01"] * 60),
            "excess_10": [.10] * 60,
            "excess_5": [.05] * 60,
            "excess_21": [.12] * 60,
            "excess_63": [.20] * 60,
        }
    )
    ranked = _point_in_time_rankings(
        signals,
        outcomes,
        ResearchConfig(min_samples=10, bootstrap_samples=20),
    )
    old = ranked[pd.to_datetime(ranked.date).dt.year == 2023]
    assert set(old.expectancy_status) == {"UNAVAILABLE"}
