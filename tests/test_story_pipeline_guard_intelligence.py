import pandas as pd

from intelligence_engine.story import add_story_intelligence


def test_story_pipeline_never_concats_scalars_when_fundamentals_are_missing():
    frame = pd.DataFrame({"ticker": ["AAA", "BBB"], "score_candidate": [80.0, 70.0]})
    out = add_story_intelligence(frame)
    assert len(out) == 2
    assert out["story_phase"].tolist() == ["MIXED", "MIXED"]
    assert "score_story" in out
