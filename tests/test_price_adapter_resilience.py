import numpy as np
import pandas as pd

from intelligence_engine.prices import _normalize_frame, _split_yfinance_download, compute_price_features


def _values(n=260):
    idx = pd.date_range("2025-01-01", periods=n, freq="B")
    close = pd.Series(np.linspace(100, 150, n), index=idx)
    return idx, close


def test_normalize_single_ticker_multiindex_and_duplicate_close():
    idx, close = _values()
    frame = pd.DataFrame({
        ("Close", "AAA"): close,
        ("Adj Close", "AAA"): close * .99,
        ("High", "AAA"): close + 1,
        ("Low", "AAA"): close - 1,
        ("Volume", "AAA"): 1_000_000,
    }, index=idx)
    normalized = _normalize_frame(frame)
    assert normalized.columns.tolist().count("close") == 1
    assert isinstance(normalized["close"], pd.Series)
    assert compute_price_features(frame)["price"] is not None


def test_split_field_first_yfinance_frame():
    idx, close = _values()
    raw = pd.DataFrame({
        ("Close", "AAA"): close,
        ("High", "AAA"): close + 1,
        ("Low", "AAA"): close - 1,
        ("Volume", "AAA"): 1_000_000,
        ("Close", "QQQ"): close * 2,
        ("High", "QQQ"): close * 2 + 1,
        ("Low", "QQQ"): close * 2 - 1,
        ("Volume", "QQQ"): 2_000_000,
    }, index=idx)
    result = _split_yfinance_download(raw, ["AAA", "QQQ"])
    assert set(result) == {"AAA", "QQQ"}
    assert all(isinstance(frame["close"], pd.Series) for frame in result.values())
