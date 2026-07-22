from intelligence_engine.morning_brief import build_morning_brief


def _brief(entries):
    return build_morning_brief(
        {
            "regime": "YELLOW",
            "entry_gate": "NO_NEW",
            "recommended_exposure_pct": 35,
            "components": {},
        },
        [],
        [],
        entries,
        {"positions": []},
    )


def test_candidate_partitions_are_exclusive_even_when_ready_has_warnings():
    brief = _brief(
        [
            {"ticker": "AAA", "decision_status": "ACTIONABLE", "warnings": []},
            {"ticker": "BBB", "decision_status": "READY", "warnings": ["market_gate"]},
            {"ticker": "CCC", "decision_status": "AVOID", "warnings": ["hard_block"]},
        ]
    )
    assert [item["ticker"] for item in brief["actionable_candidates"]] == ["AAA"]
    assert [item["ticker"] for item in brief["ready_candidates"]] == ["BBB"]
    assert [item["ticker"] for item in brief["avoid_candidates"]] == ["CCC"]
    assert "発注可能 1 / 準備 1 / 回避 1" in brief["summary_20s"]


def test_x_posts_are_language_specific_and_do_not_claim_ai_analysis():
    brief = _brief([{"ticker": "BBB", "decision_status": "READY", "warnings": ["market_gate"]}])
    assert brief["x_post_ja"].startswith("【V38】今日の米株")
    assert "AI分析" not in brief["x_post_ja"]
    assert "市場内部" in brief["x_post_ja"]
    assert brief["x_post_en"].startswith("V38 US Market Brief")
    assert "Market internals lag the indexes" in brief["x_post_en"]
    assert "市場内部" not in brief["x_post_en"]
    assert "Ready: BBB" in brief["x_post_en"]
