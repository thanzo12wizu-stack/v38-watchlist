import numpy as np
import pandas as pd

from intelligence_engine.story import add_story_intelligence


def _base_frame():
    return pd.DataFrame({"ticker": ["AAA", "BBB", "CCC"], "score_candidate": [90.0, 80.0, 70.0]})


def test_story_accepts_missing_fundamental_columns():
    out = add_story_intelligence(_base_frame())
    assert len(out) == 3
    assert out["story_phase"].eq("DATA_INSUFFICIENT").all()
    assert {"score_story", "score_story_confidence"}.issubset(out.columns)


def test_story_accepts_duplicate_fundamental_columns():
    frame = _base_frame()
    frame["eps_yoy"] = [0.2, 0.1, -0.1]
    duplicate = pd.concat([frame, frame[["eps_yoy"]]], axis=1)
    out = add_story_intelligence(duplicate)
    assert len(out) == 3
    assert isinstance(out["story_growth_raw"], pd.Series)


def test_story_accepts_partial_fundamentals_without_overstating_signal():
    frame = _base_frame()
    frame["revenue_yoy"] = [0.30, np.nan, -0.05]
    frame["shares_yoy"] = [0.01, 0.10, np.nan]
    out = add_story_intelligence(frame)
    assert out.loc[1, "story_evidence_count"] == 1
    assert out.loc[1, "story_phase"] == "DATA_INSUFFICIENT"
    assert out.loc[0, "story_phase"] == "COMPOUNDING"
