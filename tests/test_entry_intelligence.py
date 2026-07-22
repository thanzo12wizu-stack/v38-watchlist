import pandas as pd

from intelligence_engine.entry import add_entry_intelligence, build_entry_candidates, classify_setup
from intelligence_engine.prices import compute_price_features


def test_price_features_identify_breakout_structure():
    close = [100 + i * .2 for i in range(40)] + [108 + i * .05 for i in range(19)] + [112]
    frame = pd.DataFrame({
        "Close": close,
        "High": [x + .4 for x in close[:-1]] + [111.5],
        "Low": [x - .4 for x in close],
        "Volume": [1_000_000] * 55 + [2_000_000] * 5,
    })
    features = compute_price_features(frame)
    assert features["above_pivot"] is True
    assert features["pivot_20d"] < features["price"]
    assert features["stop_risk_pct"] > 0


def test_entry_score_prefers_actionable_leader():
    frame = pd.DataFrame([
        {"ticker":"A","sector":"Tech","industry":"Semi","score_leader":.9,"score_candidate":.8,"trend_alignment":1.0,"contraction_score_raw":.8,"pivot_quality_raw":.9,"participation_score_raw":.8,"reward_risk_raw":4.0,"extension_atr":1.0,"stop_risk_pct":4.0,"supply_risk_raw":.2,"distance_pivot_pct":-.5,"above_pivot":False,"near_ema21_low":False,"volume_ratio_20d":1.0,"hard_block":False,"distance_52w_high_pct":-2},
        {"ticker":"B","sector":"Tech","industry":"Semi","score_leader":.4,"score_candidate":.4,"trend_alignment":.25,"contraction_score_raw":.1,"pivot_quality_raw":.1,"participation_score_raw":.2,"reward_risk_raw":.5,"extension_atr":4.0,"stop_risk_pct":15.0,"supply_risk_raw":.8,"distance_pivot_pct":-15,"above_pivot":False,"near_ema21_low":False,"volume_ratio_20d":.7,"hard_block":False,"distance_52w_high_pct":-25},
    ])
    scored = add_entry_intelligence(frame).set_index("ticker")
    assert scored.loc["A", "score_entry"] > scored.loc["B", "score_entry"]
    assert scored.loc["A", "setup"] == "PRE_BREAKOUT"
    assert scored.loc["B", "setup"] == "EXTENDED"


def test_hard_block_is_never_actionable():
    row = pd.Series({"hard_block": True})
    assert classify_setup(row) == "AVOID"


def test_candidates_exclude_avoid_and_extended():
    frame = pd.DataFrame([
        {"ticker":"A","sector":"Tech","industry":"Semi","setup":"PRE_BREAKOUT","score_entry":.9,"score_leader":.8,"score_entry_confidence":1.0},
        {"ticker":"B","sector":"Tech","industry":"Semi","setup":"AVOID","score_entry":1.0,"score_leader":1.0,"score_entry_confidence":1.0},
    ])
    result = build_entry_candidates(frame)
    assert [item["ticker"] for item in result] == ["A"]
    assert "earnings_unknown" in result[0]["warnings"]
