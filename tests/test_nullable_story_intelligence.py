import numpy as np
import pandas as pd

from intelligence_engine.story import add_story_intelligence


def test_missing_partial_duplicate_and_empty_story_inputs():
    missing = add_story_intelligence(pd.DataFrame({"ticker": ["A", "B"]}))
    assert missing["story_phase"].eq("DATA_INSUFFICIENT").all()
    partial = add_story_intelligence(pd.DataFrame({"ticker": ["A"], "gross_margin_delta": [0.02]}))
    assert partial.loc[0, "story_quality_raw"] == 0.02
    assert partial.loc[0, "story_phase"] == "DATA_INSUFFICIENT"
    all_nan = add_story_intelligence(pd.DataFrame({"ticker": ["A"], "eps_yoy": [np.nan]}))
    assert all_nan.loc[0, "story_phase"] == "DATA_INSUFFICIENT"
    duplicate = pd.DataFrame([["A", 0.2, None], ["B", None, 0.1]], columns=["ticker", "eps_yoy", "eps_yoy"])
    out = add_story_intelligence(duplicate)
    assert out["story_growth_raw"].tolist() == [0.2, 0.1]
    empty = add_story_intelligence(pd.DataFrame(columns=["ticker"]))
    assert empty.empty
    assert {"score_story", "story_phase"}.issubset(empty.columns)
