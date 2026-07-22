from intelligence_engine.display_labels import candidates_with_freshness


def test_candidate_freshness_reserves_the_third_visible_reason_line():
    candidates = [
        {
            "ticker": "AAA",
            "reasons_ja": [
                "地合いゲートにより新規発注停止",
                "決算日を確認できていない",
                "財務データが不足",
            ],
        }
    ]
    output = candidates_with_freshness(
        candidates,
        generated_at="2026-07-23T01:23:45Z",
        price_asof="2026-07-22",
    )
    assert output[0]["reasons_ja"] == [
        "地合いゲートにより新規発注停止",
        "決算日を確認できていない",
        "データ鮮度：価格 2026-07-22 / 生成 2026-07-23",
    ]
    assert output[0]["data_freshness_ja"] == "データ鮮度：価格 2026-07-22 / 生成 2026-07-23"
    assert candidates[0]["reasons_ja"][-1] == "財務データが不足"
