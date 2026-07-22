import numpy as np
import pandas as pd

from intelligence_engine.story import add_story_intelligence


def _base_frame():
    return pd.DataFrame({
        "ticker": ["AAA", "BBB"],
        "score_candidate": [80.0, 70.0],
        "score_confidence": [0.8, 0.7],
    })


def test_story_accepts_completely_missing_fundamentals():
    out = add_story_intelligence(_base_frame())
    assert len(out) == 2
    assert "score_story" in out
    assert out["story_phase"].eq("MIXED").all()


def test_story_accepts_scalar_and_partial_fundamentals():
    frame = _base_frame()
    frame["eps_yoy"] = [0.2, np.nan]
    frame["shares_yoy"] = 0.01
    out = add_story_intelligence(frame)
    assert len(out) == 2
    assert out["story_growth_raw"].notna().sum() == 1
    assert out["story_dilution_quality_raw"].notna().all()


def test_story_keeps_series_aligned_to_frame_index():
    frame = _base_frame()
    frame.index = [10, 20]
    frame["revenue_yoy"] = pd.Series([0.3, 0.1], index=[10, 20])
    out = add_story_intelligence(frame)
    assert list(out.index) == [10, 20]
    assert out.loc[10, "story_growth_raw"] == 0.3
