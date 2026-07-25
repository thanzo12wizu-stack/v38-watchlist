from __future__ import annotations

import pandas as pd

from intelligence_engine.research_execution import ExecutionPolicy, decide, select_portfolio, simulate_trade, summarize


def _price() -> pd.DataFrame:
    index = pd.bdate_range("2024-01-01", periods=90)
    close = pd.Series([100 + i * 0.7 for i in range(len(index))], index=index)
    return pd.DataFrame({
        "Open": close - 0.2,
        "High": close + 1.0,
        "Low": close - 1.0,
        "Close": close,
        "Volume": 1_000_000,
    }, index=index)


def test_next_open_two_stage_and_partial() -> None:
    signal = pd.Series({"ticker": "ABC", "date": "2024-01-10", "pivot_20d": 108.0, "research_rank": 1})
    trade = simulate_trade(signal, _price(), ExecutionPolicy(), "EMA21_LOW")
    assert trade is not None
    assert trade["entry_date"] > "2024-01-10"
    assert trade["added"] is True
    assert trade["return"] > -0.20


def test_portfolio_cap_is_enforced() -> None:
    rows = []
    for i in range(8):
        rows.append({"ticker": f"T{i}", "entry_date": "2024-01-02", "exit_date": "2024-01-20", "return": 0.01, "research_rank": i})
    selected = select_portfolio(pd.DataFrame(rows), ExecutionPolicy(max_positions=4))
    assert len(selected) == 4


def test_decision_requires_positive_block_ci() -> None:
    policy = ExecutionPolicy(min_trades=2, min_positive_year_rate=0.5, min_oos_positive_rate=0.5)
    frame = pd.DataFrame({
        "entry_date": pd.to_datetime(["2023-01-03", "2023-02-03", "2024-01-03", "2024-02-03"]),
        "return": [0.02, 0.01, 0.03, 0.02],
        "added": [True] * 4,
        "partial_taken": [False] * 4,
        "holding_sessions": [5] * 4,
    })
    summary = summarize(frame, policy)
    decision, _ = decide(summary, policy)
    assert decision in {"ADOPT", "DISPLAY_ONLY"}
