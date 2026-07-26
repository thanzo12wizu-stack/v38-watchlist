from intelligence_engine.stage_matrix import build_stage_matrix, classify_stage


def feature_set(**updates):
    base = {
        "price": 110,
        "sma10": 108,
        "sma20": 105,
        "sma50": 100,
        "sma200": 90,
        "sma10_slope_10d_pct": 2,
        "sma20_slope_10d_pct": 1,
        "sma50_slope_20d_pct": 1,
        "extension_atr": 2,
        "above_pivot": False,
        "reward_risk_raw": 3.2,
        "distance_pivot_pct": -1,
        "volume_ratio_20d": 1.6,
        "adr_pct": 4,
        "pct_rs_raw_63": 92,
        "pct_rs_raw_126": 91,
        "pct_rs_raw_189": 90,
    }
    base.update(updates)
    return base


def test_stage_classifier_uses_structure_breakout_and_extension():
    assert classify_stage(feature_set()) == "2A"
    assert classify_stage(feature_set(above_pivot=True)) == "2B"
    assert classify_stage(feature_set(extension_atr=7.5)) == "2C"
    assert classify_stage(feature_set(price=80, sma10=85, sma20=90, sma50=100, extension_atr=-2)) == "4B"


def test_matrix_groups_by_industry_and_separates_stage_from_action():
    stocks = [
        {"ticker": "AAA", "sector": "Technology", "industry": "Software", "features": feature_set()},
        {"ticker": "BBB", "sector": "Technology", "industry": "Software", "features": feature_set(price=108, pct_rs_raw_63=86, pct_rs_raw_126=85, pct_rs_raw_189=84)},
        {"ticker": "CCC", "sector": "Energy", "industry": "Oil", "features": feature_set(price=80, sma10=85, sma20=90, sma50=100, extension_atr=-2, pct_rs_raw_63=20, pct_rs_raw_126=25, pct_rs_raw_189=30)},
    ]
    matrix = build_stage_matrix(stocks, {"entry_gate": "SELECTIVE", "regime": "GREEN"}, generated_at="2026-07-26T00:00:00Z")
    assert matrix["summary"]["pool_count"] == 3
    assert matrix["summary"]["stage_counts"]["2A"] == 2
    assert matrix["industries"][0]["industry"] == "Software"
    aaa = next(item for item in matrix["items"] if item["ticker"] == "AAA")
    assert aaa["stage"] == "2A"
    assert aaa["action"] == "BUYABLE"
    assert aaa["leader_grade"] in {"A", "A+"}
    assert matrix["implementation"]["score_is_probability"] is False


def test_market_gate_blocks_buyable_without_changing_stage():
    stock = {"ticker": "AAA", "sector": "Technology", "industry": "Software", "features": feature_set()}
    matrix = build_stage_matrix([stock], {"entry_gate": "CLOSED", "regime": "RED"})
    item = matrix["items"][0]
    assert item["stage"] == "2A"
    assert item["action"] == "WAIT"
    assert any("市場ゲート" in reason for reason in item["reasons"])
