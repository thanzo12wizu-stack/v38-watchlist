import json

from intelligence_engine.intelligence_dashboard import build_html, generate


def test_build_html_contains_views_and_preserves_existing_dashboard_name():
    payload = {
        "generated_at": "2026-07-22T00:00:00Z",
        "market_state": {"regime": "GREEN", "entry_gate": "SELECTIVE", "recommended_exposure_pct": 50},
        "entry_candidates": [{"ticker": "AAA", "actionable": True, "setup": "PULLBACK", "entry_score_calibrated": 78}],
        "theme_intelligence": [{"theme": "Semiconductors", "phase": "LEADING", "score_theme": 90}],
        "portfolio_doctor": {"positions": [{"ticker": "AAA", "action": "HOLD"}]},
        "morning_brief": {"headline": "test", "x_post_ja": "post"},
        "data_quality": {"status": "OK", "warnings": []},
    }
    text = build_html(payload)
    assert "V38 Intelligence Dashboard" in text
    assert "発注可能候補" in text
    assert "AAA" in text
    assert "intelligence-dashboard.html" not in text


def test_generate_writes_standalone_file(tmp_path):
    source = tmp_path / "index.json"
    target = tmp_path / "intelligence-dashboard.html"
    source.write_text(json.dumps({"market_state": {}, "morning_brief": {}}), encoding="utf-8")
    generate(source, target)
    assert target.exists()
    assert "<!doctype html>" in target.read_text(encoding="utf-8")
