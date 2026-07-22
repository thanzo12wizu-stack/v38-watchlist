import numpy as np
import pandas as pd

from intelligence_engine.story import add_story_intelligence


def _base_frame():
    return pd.DataFrame({
        "ticker": ["AAA", "BBB", "CCC"],
        "score_candidate": [90.0, 80.0, 70.0],
    })


def test_story_accepts_completely_missing_fundamental_columns():
    out = add_story_intelligence(_base_frame())
    assert len(out) == 3
    assert {"score_story", "score_story_confidence", "story_phase"}.issubset(out.columns)
    assert out["story_phase"].eq("MIXED").all()


def test_story_accepts_duplicate_fundamental_columns():
    frame = _base_frame()
    frame["eps_yoy"] = [0.2, 0.1, -0.1]
    duplicate = pd.concat([frame, frame[["eps_yoy"]].rename(columns={"eps_yoy": "eps_yoy"})], axis=1)
    out = add_story_intelligence(duplicate)
    assert len(out) == 3
    assert isinstance(out["story_growth_raw"], pd.Series)
    assert out["score_story"].notna().any()


def test_story_accepts_partial_scalar_like_missing_values():
    frame = _base_frame()
    frame["revenue_yoy"] = [0.30, np.nan, -0.05]
    frame["shares_yoy"] = [0.01, 0.10, np.nan]
    out = add_story_intelligence(frame)
    assert len(out) == 3
    assert out.loc[1, "story_phase"] == "DILUTING"
