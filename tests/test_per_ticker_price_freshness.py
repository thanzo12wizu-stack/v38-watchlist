import numpy as np
import pandas as pd

from intelligence_engine.entry import build_entry_candidates
from intelligence_engine.prices import compute_price_features


def test_price_features_include_the_tickers_actual_last_session():
    index = pd.date_range(end="2026-07-21", periods=300, freq="B")
    close = np.linspace(50.0, 100.0, len(index))
    frame = pd.DataFrame(
        {
            "open": close * 0.999,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": np.full(len(index), 2_000_000),
        },
        index=index,
    )
    features = compute_price_features(frame)
    assert features["price_asof"] == "2026-07-21"


def test_entry_candidate_carries_price_asof():
    frame = pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "sector": "Technology",
                "industry": "Software",
                "setup": "PULLBACK",
                "score_entry": 90.0,
                "score_leader": 88.0,
                "score_candidate": 85.0,
                "price": 100.0,
                "price_asof": "2026-07-21",
                "hard_block": False,
            }
        ]
    )
    candidate = build_entry_candidates(frame, limit=1)[0]
    assert candidate["price_asof"] == "2026-07-21"
