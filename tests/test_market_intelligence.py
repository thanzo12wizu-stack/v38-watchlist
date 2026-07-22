import pandas as pd

from intelligence_engine.market import apply_market_gate, build_market_state


def _qqq(values):
    return pd.DataFrame({"close": values, "high": values, "low": values, "volume": [1_000_000] * len(values)})


def test_market_state_blue_when_index_and_breadth_are_strong():
    qqq = _qqq([100 + i * .5 for i in range(260)])
    frame = pd.DataFrame([
        {"ticker": f"A{i}", "price": 120, "sma10": 110, "sma50": 100, "sma200": 80, "rs_raw_63": .20, "rs_raw_126": .30, "leader_rank_pct": .9}
        for i in range(10)
    ])
    sectors = [{"sector": "Technology", "breadth_positive_63d": .9, "leader_share_top20pct": .3}]
    state = build_market_state(frame, qqq, sectors)
    assert state["regime"] == "BLUE"
    assert state["entry_gate"] == "ALLOW"
    assert state["score_market"] >= .72


def test_market_state_red_when_index_and_breadth_are_weak():
    qqq = _qqq([230 - i * .5 for i in range(260)])
    frame = pd.DataFrame([
        {"ticker": f"B{i}", "price": 60, "sma10": 70, "sma50": 80, "sma200": 100, "rs_raw_63": -.20, "rs_raw_126": -.30, "leader_rank_pct": .1}
        for i in range(10)
    ])
    sectors = [{"sector": "Utilities", "breadth_positive_63d": .1, "leader_share_top20pct": 0}]
    state = build_market_state(frame, qqq, sectors)
    assert state["regime"] == "RED"
    assert state["entry_gate"] == "DEFENSIVE"
    assert state["recommended_exposure"] == 0


def test_selective_gate_only_allows_high_quality_setup_types():
    candidates = [
        {"ticker": "A", "setup": "PULLBACK", "warnings": []},
        {"ticker": "B", "setup": "VOLUME_SURGE", "warnings": []},
    ]
    gated = apply_market_gate(candidates, {"regime": "GREEN", "entry_gate": "SELECTIVE"})
    assert gated[0]["actionable"] is True
    assert gated[1]["actionable"] is False
    assert "market_gate" in gated[1]["warnings"]


def test_market_state_flags_index_breadth_divergence():
    qqq = _qqq([100 + i * .4 for i in range(260)])
    frame = pd.DataFrame([
        {"ticker": f"C{i}", "price": 90 if i < 3 else 70, "sma10": 80, "sma50": 80, "sma200": 75, "rs_raw_63": -.1, "rs_raw_126": -.1, "leader_rank_pct": .2}
        for i in range(10)
    ])
    state = build_market_state(frame, qqq, [])
    assert "index_breadth_divergence" in state["warnings"]
