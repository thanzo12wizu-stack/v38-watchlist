import pandas as pd

from intelligence_engine.story import add_story_intelligence, apply_story_context, build_story_records


def test_story_score_rewards_growth_acceleration_and_quality():
    frame = pd.DataFrame([
        {"ticker":"A","sector":"Tech","industry":"Semi","eps_yoy":.60,"eps_acceleration":.20,"revenue_yoy":.35,"revenue_acceleration":.10,"gross_margin_delta":.03,"operating_margin_delta":.04,"free_cash_flow_yoy":.50,"shares_yoy":-.01},
        {"ticker":"B","sector":"Tech","industry":"Semi","eps_yoy":-.20,"eps_acceleration":-.10,"revenue_yoy":-.05,"revenue_acceleration":-.05,"gross_margin_delta":-.03,"operating_margin_delta":-.04,"free_cash_flow_yoy":-.30,"shares_yoy":.10},
    ])
    scored = add_story_intelligence(frame).set_index("ticker")
    assert scored.loc["A", "score_story"] > scored.loc["B", "score_story"]
    assert scored.loc["A", "story_phase"] == "ACCELERATING"
    assert scored.loc["B", "story_phase"] == "DILUTING"


def test_story_phase_detects_inflection_and_margin_pressure():
    frame = pd.DataFrame([
        {"ticker":"I","eps_yoy":.02,"eps_acceleration":.20,"revenue_yoy":.01,"revenue_acceleration":.10,"gross_margin_delta":0,"operating_margin_delta":0,"free_cash_flow_yoy":0,"shares_yoy":0},
        {"ticker":"M","eps_yoy":.15,"eps_acceleration":0,"revenue_yoy":.12,"revenue_acceleration":0,"gross_margin_delta":-.05,"operating_margin_delta":-.04,"free_cash_flow_yoy":-.20,"shares_yoy":0},
    ])
    scored = add_story_intelligence(frame).set_index("ticker")
    assert scored.loc["I", "story_phase"] == "INFLECTING"
    assert scored.loc["M", "story_phase"] == "MARGIN_PRESSURE"


def test_story_records_and_candidate_context_include_risk():
    frame = add_story_intelligence(pd.DataFrame([
        {"ticker":"A","sector":"Tech","industry":"Semi","eps_yoy":.4,"eps_acceleration":.1,"revenue_yoy":.3,"revenue_acceleration":.1,"gross_margin_delta":.02,"operating_margin_delta":.02,"free_cash_flow_yoy":.3,"shares_yoy":0,"latest_filing_date":"2026-05-01"},
        {"ticker":"B","sector":"Tech","industry":"Software","eps_yoy":-.2,"eps_acceleration":-.1,"revenue_yoy":-.1,"revenue_acceleration":-.1,"gross_margin_delta":-.02,"operating_margin_delta":-.03,"free_cash_flow_yoy":-.2,"shares_yoy":0,"latest_filing_date":"2026-05-02"},
    ]))
    records = build_story_records(frame)
    assert records[0]["ticker"] == "A"
    candidates = apply_story_context([{"ticker":"B","warnings":[]}], frame)
    assert candidates[0]["story_phase"] == "DETERIORATING"
    assert "story_deteriorating" in candidates[0]["warnings"]
