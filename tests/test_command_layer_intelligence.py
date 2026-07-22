import json
from pathlib import Path

import pandas as pd

from intelligence_engine.dashboard_bridge import build_panel, inject_panel
from intelligence_engine.morning_brief import build_morning_brief
from intelligence_engine.portfolio import build_portfolio_doctor, load_positions


def test_load_positions_normalizes_weights(tmp_path):
    path = tmp_path / "portfolio.csv"
    pd.DataFrame({"ticker": ["AAA", "BBB"], "weight": [30, 70]}).to_csv(path, index=False)
    result = load_positions(path)
    assert round(result["weight"].sum(), 8) == 1
    assert result.loc[1, "weight"] == .7


def test_portfolio_doctor_flags_concentration_and_exit():
    positions = pd.DataFrame({"ticker": ["AAA", "BBB"], "weight": [.8, .2], "cost_basis": [10, 10], "entry_date": [None, None], "stop_method": ["21EMA_LOW", "10MA"]})
    scored = pd.DataFrame([
        {"ticker": "AAA", "price": 9, "stop_ema21_low": 10, "stop_sma10": 9.5, "adr_pct": 4, "sector": "Tech", "theme": "Semi", "hard_block": True},
        {"ticker": "BBB", "price": 12, "stop_ema21_low": 10, "stop_sma10": 11, "adr_pct": 3, "sector": "Tech", "theme": "Semi", "hard_block": False},
    ])
    result = build_portfolio_doctor(positions, scored, {}, {"entry_gate": "ALLOW"})
    assert result["positions"][0]["action"] == "EXIT"
    assert "single_position_concentration" in result["warnings"]
    assert "sector_concentration" in result["warnings"]


def test_morning_brief_outputs_copyable_post():
    result = build_morning_brief(
        {"regime": "GREEN", "entry_gate": "SELECTIVE", "recommended_exposure_pct": 50},
        [{"sector": "Technology", "score_rotation": .9}],
        [{"theme": "Semiconductors", "score_theme": .9, "phase": "LEADING", "leaders": ["AAA"]}],
        [{"ticker": "AAA", "actionable": True, "setup": "PULLBACK"}],
        {"positions": []},
    )
    assert "GREEN" in result["headline"]
    assert "AAA" in result["x_post_ja"]
    assert result["leader_changes"][0]["leader"] == "AAA"


def test_dashboard_bridge_is_idempotent(tmp_path):
    target = tmp_path / "dashboard.html"
    target.write_text("<html><body><main>existing</main></body></html>", encoding="utf-8")
    payload = {"market_state": {"regime": "BLUE", "entry_gate": "ALLOW"}, "morning_brief": {"market_comment": "ok", "actionable_candidates": [], "strong_themes": [], "x_post_ja": "post"}, "portfolio_doctor": {"positions": []}}
    assert inject_panel(target, payload)
    assert inject_panel(target, payload)
    text = target.read_text(encoding="utf-8")
    assert text.count("COMMAND_CENTER_INTELLIGENCE_START") == 1
    assert "existing" in text
    assert "AI Command Layer" in build_panel(payload)
