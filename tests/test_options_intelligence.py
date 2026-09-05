from tools import build_options_intelligence as intel


def test_acceleration_requires_previous_call_wall_break_and_non_negative_regime():
    prev = {"spot": 100.0, "call_wall": 105.0}
    cur = {
        "spot": 108.0, "atr14": 4.0, "call_wall": 115.0, "put_wall": 102.0,
        "gamma_flip": 103.0, "net_gex": 1_000_000.0, "regime": "POSITIVE_GAMMA",
        "confidence": "HIGH", "stale": False,
    }
    signal, score, reasons = intel._classify(cur, prev, {"positive": 2, "negative": 0}, 0)
    assert signal == "ACCELERATION"
    assert score >= 70
    assert "前回Call Wallを突破" in reasons


def test_negative_gamma_is_headwind():
    cur = {
        "spot": 95.0, "atr14": 4.0, "call_wall": 105.0, "put_wall": 90.0,
        "gamma_flip": 102.0, "net_gex": -5_000_000.0, "regime": "NEGATIVE_GAMMA",
        "confidence": "HIGH", "stale": False,
    }
    assert intel._classify(cur, None, None, 0)[0] == "HEADWIND"


def test_low_confidence_is_data_low():
    cur = {"spot": 100.0, "confidence": "LOW", "regime": "POSITIVE_GAMMA", "stale": False}
    assert intel._classify(cur, None, None, 0)[0] == "DATA LOW"


def test_plan_uses_flip_then_put_as_invalidation():
    cur = {"spot": 110.0, "atr14": 5.0, "call_wall": 120.0, "put_wall": 100.0, "gamma_flip": 105.0}
    plan = intel._plan(cur, "SUPPORTIVE")
    assert "105.00" in plan["invalid"]
    assert "100.00" in plan["invalid"]
    assert "120.00" in plan["target"]
