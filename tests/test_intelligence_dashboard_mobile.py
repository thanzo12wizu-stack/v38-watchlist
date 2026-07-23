from intelligence_engine.intelligence_dashboard import build_html


def _candidate(ticker: str, status: str = "READY") -> dict:
    return {
        "ticker": ticker,
        "decision_status": status,
        "decision_status_ja": "準備候補" if status == "READY" else status,
        "decision_rank": 1,
        "setup": "PULLBACK",
        "setup_ja": "21EMA付近の押し目",
        "theme_ja": "クラウド監視",
        "final_rank_score": 78,
        "price": 100,
        "entry_low": 96,
        "entry_high": 100,
        "entry_1": 96,
        "entry_2": 100,
        "stop_effective": 92,
        "stop_distance_pct": 4.2,
        "reward_risk": 3.1,
        "reasons_ja": ["押し目形成を待つ", "地合いゲートにより新規発注停止"],
    }


def test_mobile_dashboard_uses_progressive_disclosure_and_compact_limits():
    payload = {
        "market_state": {
            "regime": "YELLOW",
            "entry_gate": "NO_NEW",
            "recommended_exposure_pct": 35,
        },
        "entry_candidates": [_candidate(f"R{i}") for i in range(1, 8)],
        "morning_brief": {"headline": "test", "summary_20s": "新規停止。準備を継続。"},
        "data_quality": {"status": "PASS"},
    }

    text = build_html(payload)

    assert '<details class="candidate' in text
    assert "タップで詳細" in text
    assert "残り2件を見る" in text
    assert "準備候補" in text
    assert "Entry" in text and "Stop" in text and "R/R" in text


def test_empty_external_records_are_hidden_but_coverage_is_visible():
    payload = {
        "market_state": {},
        "morning_brief": {},
        "data_quality": {"status": "PASS", "metrics": {"price_coverage_ratio": 0.95}},
        "external_data": [
            {"ticker": "EMPTYEXT"},
            {"ticker": "COVEREDEXT", "next_earnings_date": "2026-08-01"},
        ],
    }

    text = build_html(payload)

    assert "COVEREDEXT" in text
    assert "EMPTYEXT" not in text
    assert "1/2" in text
    assert "空欄銘柄は非表示" in text


def test_portfolio_without_positions_shows_one_clear_empty_state():
    text = build_html(
        {
            "market_state": {},
            "morning_brief": {},
            "portfolio_doctor": {"status": "NO_POSITIONS", "positions": []},
        }
    )

    assert "Portfolio未設定" in text
    assert "Gross Exposure" not in text
    assert "21EMA Low／10MA Stop" in text


def test_sector_and_theme_lists_show_top_items_then_collapse_remainder():
    sectors = [
        {
            "sector": f"Sector {index}",
            "phase": "IMPROVING",
            "score_rotation": 80 - index,
            "score_acceleration": 70 - index,
            "breadth_positive_63d": 0.6,
        }
        for index in range(9)
    ]
    themes = [
        {
            "theme_ja": f"Theme {index}",
            "phase": "LEADING",
            "score_theme": 90 - index,
            "breadth_positive": 0.7,
        }
        for index in range(11)
    ]

    text = build_html(
        {
            "market_state": {},
            "morning_brief": {},
            "sector_rotation": sectors,
            "theme_intelligence": themes,
        }
    )

    assert "残り1セクターを表示" in text
    assert "残り1テーマを表示" in text
    assert "上位8" in text
    assert "上位10" in text


def test_candidate_missing_plan_values_are_explained_not_rendered_as_dash_grid():
    candidate = {
        "ticker": "NOPLAN",
        "decision_status": "READY",
        "setup": "WATCH",
        "reasons_ja": ["形待ち"],
    }
    text = build_html(
        {
            "market_state": {},
            "morning_brief": {},
            "entry_candidates": [candidate],
        }
    )

    assert "算出不可" in text
    assert "未算出" in text
    assert "現在値</span><b>—" not in text
