import json

from intelligence_engine.intelligence_dashboard import build_html, generate, load_payload


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


def test_generate_bootstraps_when_index_is_missing(tmp_path):
    root = tmp_path / "data" / "intelligence"
    root.mkdir(parents=True)
    (root / "morning_brief.json").write_text(json.dumps({"headline": "bootstrap"}), encoding="utf-8")
    target = tmp_path / "intelligence-dashboard.html"
    generate(root / "index.json", target)
    text = target.read_text(encoding="utf-8")
    assert "<!doctype html>" in text
    assert "bootstrap" in text
    assert "統合JSONがまだ未生成" in text


def test_load_payload_unwraps_individual_sidecar_files(tmp_path):
    root = tmp_path / "data" / "intelligence"
    root.mkdir(parents=True)
    (root / "entry_candidates.json").write_text(json.dumps({"candidates": [{"ticker": "AAA"}]}), encoding="utf-8")
    (root / "external_data.json").write_text(json.dumps({"records": [{"ticker": "BBB"}]}), encoding="utf-8")
    payload = load_payload(root / "index.json")
    assert payload["entry_candidates"][0]["ticker"] == "AAA"
    assert payload["external_data"][0]["ticker"] == "BBB"
    assert payload["dashboard_input_status"] == "BOOTSTRAP_NO_INDEX"
