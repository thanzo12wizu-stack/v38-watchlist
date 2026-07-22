import pandas as pd

from intelligence_engine.story import add_story_intelligence


def test_dilution_only_input_classifies_without_failure():
    frame = pd.DataFrame({"ticker": ["AAA"], "shares_yoy": [0.10]})
    out = add_story_intelligence(frame)
    assert out.loc[0, "story_phase"] == "DILUTING"
