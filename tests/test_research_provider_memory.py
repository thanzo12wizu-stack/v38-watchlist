from __future__ import annotations

import pandas as pd

from intelligence_engine.research_providers import _bounded_filing_history


def _facts() -> pd.DataFrame:
    rows = []
    for index, filed in enumerate(pd.date_range("2018-01-01", periods=24, freq="QS")):
        for metric in ("revenue", "eps", "gross_profit"):
            rows.append(
                {
                    "ticker": "AAA",
                    "metric": metric,
                    "value": float(index + 1),
                    "period_end": filed - pd.Timedelta(days=30),
                    "available_at": filed,
                }
            )
    return pd.DataFrame(rows)


def test_bounded_history_keeps_latest_filing_dates_not_individual_rows() -> None:
    bounded = _bounded_filing_history(_facts(), asof=None, filing_limit=12)
    assert bounded["available_at"].nunique() == 12
    assert len(bounded) == 36
    assert bounded["available_at"].min() == _facts()["available_at"].drop_duplicates().sort_values().iloc[-12]


def test_bounded_history_is_point_in_time_for_requested_year() -> None:
    bounded = _bounded_filing_history(_facts(), asof=pd.Timestamp("2020-12-31"), filing_limit=12)
    assert (bounded["available_at"] <= pd.Timestamp("2020-12-31")).all()
    assert bounded["available_at"].nunique() <= 12
