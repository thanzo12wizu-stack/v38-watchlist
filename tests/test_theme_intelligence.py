import pandas as pd

from intelligence_engine.theme import apply_theme_context, attach_theme_context, build_theme_intelligence


def _row(ticker, industry, rs63, rs126, rs189, accel, leader, rank, setup):
    return {
        "ticker": ticker,
        "sector": "Technology",
        "industry": industry,
        "rs_raw_63": rs63,
        "rs_raw_126": rs126,
        "rs_raw_189": rs189,
        "rs_change_raw_63": accel,
        "rs_change_raw_126": accel,
        "score_leader": leader,
        "leader_rank_pct": rank,
        "score_entry": leader,
        "setup": setup,
    }


def test_theme_intelligence_prefers_broad_accelerating_group():
    frame = pd.DataFrame([
        _row("A1", "Optical", .50, .45, .40, .20, .95, .95, "PRE_BREAKOUT"),
        _row("A2", "Optical", .40, .35, .30, .15, .85, .85, "PULLBACK"),
        _row("A3", "Optical", .30, .25, .20, .10, .75, .75, "BREAKOUT"),
        _row("B1", "Legacy", -.20, -.15, -.10, -.15, .30, .30, "WATCH"),
        _row("B2", "Legacy", -.10, -.05, 0, -.10, .20, .20, "WATCH"),
    ])
    themes = build_theme_intelligence(frame)
    assert themes[0]["theme"] == "Optical"
    assert themes[0]["score_theme"] > themes[1]["score_theme"]
    assert themes[0]["phase"] in {"LEADING", "EMERGING"}
    assert themes[0]["leaders"][0] == "A1"


def test_theme_uses_sector_fallback_and_enriches_candidates():
    frame = pd.DataFrame([
        _row("A1", None, .30, .25, .20, .10, .90, .90, "PULLBACK"),
        _row("A2", None, .25, .20, .15, .08, .80, .80, "PRE_BREAKOUT"),
    ])
    themes = build_theme_intelligence(frame)
    assert themes[0]["theme"] == "Technology"
    assert themes[0]["source"] == "sector_fallback"
    enriched_frame = attach_theme_context(frame, themes)
    candidates = apply_theme_context([{"ticker": "A1", "warnings": []}], enriched_frame)
    assert candidates[0]["theme"] == "Technology"
    assert candidates[0]["theme_score"] == themes[0]["score_theme"]
    assert isinstance(candidates[0]["theme_confirmed"], bool)


def test_single_member_groups_are_not_promoted_to_themes():
    frame = pd.DataFrame([_row("SOLO", "Niche", .50, .50, .50, .20, .90, .90, "BREAKOUT")])
    assert build_theme_intelligence(frame) == []
