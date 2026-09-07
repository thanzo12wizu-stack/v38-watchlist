from tools.build_v38_chart_data import visible_symbols


def test_visible_symbols_collects_only_chartable_v38_symbols():
    state = {
        "asof": "2026-09-04",
        "candidates": [
            {"ticker": "MRNA"},
            {"ticker": "ARCT"},
        ],
        "early1": {
            "status": "READY",
            "top1": {"ticker": "DELL"},
        },
        "panic_reset": {
            "status": "READY / LIVE",
            "positions": [{"symbol": "SNDK"}],
            "monitor": [{"symbol": "MU"}],
        },
        "ranking": {
            "attack_reopen_top12": ["MRNA", "ECO"],
            "attack_core_top11": ["MRNA"],
            "canonical_rule": "DDV20_VACANCY_TOP12_EARLY1_RS21_HIGH_ACCEL",
        },
    }

    symbols = visible_symbols(state)

    assert symbols == sorted({"QQQ", "TQQQ", "MRNA", "ARCT", "DELL", "SNDK", "MU", "ECO"})
    assert "READY" not in symbols
    assert "LIVE" not in symbols
