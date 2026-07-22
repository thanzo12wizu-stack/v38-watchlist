import pandas as pd

from intelligence_engine.scoring import score_universe
from intelligence_engine.story import add_story_intelligence


def test_scoring_chain_survives_no_sec_fundamentals():
    frame = pd.DataFrame({
        "ticker": ["AAA", "BBB", "CCC"],
        "sector": ["Tech", "Tech", "Industrial"],
        "industry": ["Software", "Hardware", "Machinery"],
        "rs_raw_21": [0.1, 0.2, -0.1],
        "rs_raw_63": [0.2, 0.1, -0.2],
        "rs_raw_126": [0.3, 0.2, -0.1],
        "rs_raw_189": [0.4, 0.3, -0.2],
        "rs_raw_252": [0.5, 0.4, -0.3],
        "rs_change_raw_63": [0.01, 0.02, -0.01],
        "rs_change_raw_126": [0.02, 0.01, -0.02],
        "rs_change_raw_189": [0.03, 0.02, -0.03],
        "volume_ratio_20d": [1.2, 1.1, 0.9],
        "distance_52w_high_pct": [-2.0, -4.0, -15.0],
    })
    scored = score_universe(frame)
    result = add_story_intelligence(scored)
    assert len(result) == 3
    assert result["story_phase"].eq("MIXED").all()
    assert "score_story_confidence" in result
