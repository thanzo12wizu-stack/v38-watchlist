import pandas as pd

from intelligence_engine.story import add_story_intelligence


def test_story_empty_frame_returns_empty_with_contract_columns():
    out = add_story_intelligence(pd.DataFrame(columns=["ticker"]))
    assert out.empty
    assert "story_phase" in out.columns
    assert "score_story" in out.columns
