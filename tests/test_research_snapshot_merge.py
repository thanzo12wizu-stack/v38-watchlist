from __future__ import annotations

import pandas as pd

from intelligence_engine.research_pipeline.worker import _merge_snapshots_indexed


def test_snapshot_merge_normalizes_aware_and_naive_timestamps():
    price_panel = pd.DataFrame(
        {
            "ticker": ["AAA", "AAA", "BBB"],
            "date": [
                pd.Timestamp("2026-01-05", tz="America/New_York"),
                pd.Timestamp("2026-01-10", tz="UTC"),
                pd.Timestamp("2026-01-10", tz="UTC"),
            ],
            "price": [10.0, 11.0, 20.0],
        }
    )
    snapshots = pd.DataFrame(
        {
            "ticker": ["AAA", "AAA"],
            "available_at": [pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-08", tz="UTC")],
            "revenue_yoy": [0.10, 0.20],
            "fundamental_confidence": [0.5, 0.8],
        }
    )

    merged = _merge_snapshots_indexed(price_panel, snapshots)
    aaa = merged[merged["ticker"] == "AAA"].sort_values("date")
    bbb = merged[merged["ticker"] == "BBB"]

    assert str(merged["date"].dtype) == "datetime64[ns]"
    assert aaa["revenue_yoy"].tolist() == [0.10, 0.20]
    assert aaa["fundamental_confidence"].tolist() == [0.5, 0.8]
    assert bbb["fundamental_confidence"].tolist() == [0.0]


def test_snapshot_merge_ignores_invalid_snapshot_dates_without_merge_error():
    price_panel = pd.DataFrame(
        {
            "ticker": ["AAA", "AAA"],
            "date": ["2026-01-05", "not-a-date"],
            "price": [10.0, 11.0],
        }
    )
    snapshots = pd.DataFrame(
        {
            "ticker": ["AAA", "AAA"],
            "available_at": ["bad", "2026-01-01T00:00:00Z"],
            "fundamental_confidence": [1.0, 0.7],
        }
    )

    merged = _merge_snapshots_indexed(price_panel, snapshots)

    assert len(merged) == 2
    valid = merged[merged["date"].notna()].iloc[0]
    invalid = merged[merged["date"].isna()].iloc[0]
    assert valid["fundamental_confidence"] == 0.7
    assert invalid["fundamental_confidence"] == 0.0
