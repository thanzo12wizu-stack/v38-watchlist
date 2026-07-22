import pandas as pd

from intelligence_engine.story import add_story_intelligence


def test_duplicate_fundamental_columns_are_collapsed_rowwise():
    frame = pd.DataFrame([["AAA", 0.2, None], ["BBB", None, 0.1]], columns=["ticker", "eps_yoy", "eps_yoy"])
    out = add_story_intelligence(frame)
    assert out["story_growth_raw"].tolist() == [0.2, 0.1]
