import numpy as np
import pandas as pd

from intelligence_engine.story import add_story_intelligence


def test_all_nan_story_factors_do_not_raise():
    frame = pd.DataFrame({"ticker": ["AAA"], "eps_yoy": [np.nan], "revenue_yoy": [np.nan]})
    out = add_story_intelligence(frame)
    assert out.loc[0, "story_phase"] == "MIXED"
