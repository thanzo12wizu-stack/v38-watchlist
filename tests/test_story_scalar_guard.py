import pandas as pd

from intelligence_engine.story import _numeric_series


def test_numeric_series_missing_column_returns_aligned_nan_series():
    frame = pd.DataFrame({"ticker": ["AAA", "BBB"]}, index=[4, 9])
    result = _numeric_series(frame, "eps_yoy")
    assert list(result.index) == [4, 9]
    assert result.isna().all()
