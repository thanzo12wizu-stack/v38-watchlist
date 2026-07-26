import json

from intelligence_engine.stage_dashboard import build_html, generate, load_payload


def sample_matrix():
    item = {
        "ticker": "AAA",
        "sector": "Technology",
        "industry": "Software",
        "stage": "2B",
        "action": "BUYABLE",
        "leader_grade": "A",
        "rs_composite": 92,
        "entry_quality_rank": 88,
        "extension_atr": 2.4,
        "reward_risk": 3.1,
        "adr_pct": 4.0,
        "badges": ["GROUP50", "RS90"],
        "reasons": ["Stage・Group・RS・位置・R/Rを通過"],
    }
    return {
        "stage_order": ["2B"],
        "summary": {"pool_count": 1, "buyable_count": 1, "bullish_pct": 1.0, "risk_action_count": 0, "stage_counts": {"2B": 1}},
        "stages": [{"stage": "2B", "label_ja": "ブレイク確認", "tone": "green", "count": 1, "groups": [{"sector": "Technology", "industry": "Software", "group_score": 80, "group_rank": 1, "items": [item]}]}],
        "items": [item],
        "sectors": [{"sector": "Technology", "rank": 1, "group_score": 80, "rs_composite": 90, "stage2_share": 1, "bearish_share": 0, "top_half": True}],
        "industries": [{"industry": "Software", "rank": 1, "group_score": 82, "rs_composite": 92, "stage2_share": 1, "bearish_share": 0, "top_half": True}],
        "transitions": {"upgrades": 1, "downgrades": 0, "items": [{"ticker": "AAA", "from": "1A", "to": "2B", "direction": "UPGRADE", "industry": "Software", "rs_composite": 92}]},
    }


def test_build_html_replaces_old_candidate_dashboard_with_stage_matrix():
    payload = {
        "generated_at": "2026-07-26T00:00:00Z",
        "stage_matrix": sample_matrix(),
        "market_state": {"regime": "GREEN", "entry_gate": "SELECTIVE"},
        "morning_brief": {"summary_20s": "test"},
        "data_quality": {"status": "OK", "warnings": []},
    }
    text = build_html(payload)
    assert "V38 Stage × Group × RS" in text
    assert "STAGE MATRIX" in text
    assert "GROUPS" in text
    assert "BUYABLE" in text
    assert "AAA" in text
    assert "旧候補ロジック" in text


def test_generate_writes_standalone_file(tmp_path):
    source = tmp_path / "index.json"
    target = tmp_path / "intelligence-dashboard.html"
    source.write_text(json.dumps({"stage_matrix": sample_matrix(), "market_state": {}}), encoding="utf-8")
    generate(source, target)
    assert target.exists()
    assert "<!doctype html>" in target.read_text(encoding="utf-8")


def test_load_payload_bootstraps_stage_matrix_file(tmp_path):
    root = tmp_path / "data" / "intelligence"
    root.mkdir(parents=True)
    (root / "stage_matrix.json").write_text(json.dumps(sample_matrix()), encoding="utf-8")
    payload = load_payload(root / "index.json")
    assert payload["stage_matrix"]["summary"]["pool_count"] == 1
    assert payload["dashboard_input_status"] == "BOOTSTRAP_NO_INDEX"
