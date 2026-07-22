import pandas as pd

from intelligence_engine.story import add_story_intelligence


def test_partial_quality_factor_is_used_without_concat_error():
    frame = pd.DataFrame({"ticker": ["AAA"], "gross_margin_delta": [0.02]})
    out = add_story_intelligence(frame)
    assert out.loc[0, "story_quality_raw"] == 0.02
