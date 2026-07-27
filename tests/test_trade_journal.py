from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from intelligence_engine.trade_journal import JournalInput, JournalRules, analyse_journal, detect_rule_violations, normalise_trades
from intelligence_engine.trade_journal_run import run


def sample_trades() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "trade_id": "A", "ticker": "AAA", "side": "LONG", "entry_date": "2026-01-05", "exit_date": "2026-01-08",
            "entry_price": 100, "exit_price": 120, "quantity": 10, "fx_to_jpy": 1, "point_value": 1,
            "fees_jpy": 10, "stop_price": 95, "target_price": 120, "setup": "Breakout", "nq_color": "BLUE",
            "sector": "Technology", "theme": "AI", "rule_followed": True,
        },
        {
            "trade_id": "B", "ticker": "BBB", "side": "LONG", "entry_date": "2026-01-10", "exit_date": "2026-01-12",
            "entry_price": 50, "exit_price": 47.5, "quantity": 20, "fx_to_jpy": 1, "point_value": 1,
            "fees_jpy": 0, "stop_price": 47.5, "target_price": 58, "setup": "21EMA Pullback", "nq_color": "YELLOW",
            "sector": "Materials", "theme": "Copper", "rule_followed": False, "mistake_type": "CHASE",
        },
    ])


def sample_holdings() -> pd.DataFrame:
    return pd.DataFrame([
        {"ticker": "AAA", "quantity": 10, "entry_price": 100, "current_price": 110, "fx_to_jpy": 1, "stop_price": 104, "sector": "Technology", "theme": "AI", "entry_date": "2026-01-01", "setup": "Breakout"},
        {"ticker": "BBB", "quantity": 20, "entry_price": 50, "current_price": 48, "fx_to_jpy": 1, "stop_price": 46, "sector": "Materials", "theme": "Copper", "entry_date": "2026-01-02", "setup": "Pullback"},
    ])


def test_trade_normalization_uses_point_value_and_costs() -> None:
    trades = normalise_trades(sample_trades())
    first = trades.loc[trades["trade_id"] == "A"].iloc[0]
    assert first["gross_pnl_jpy"] == 200
    assert first["net_pnl_jpy"] == 190
    assert first["planned_risk_jpy"] == 50
    assert first["r_multiple"] == 3.8
    assert first["hold_days"] == 3


def test_kpis_drawdown_setup_and_regime() -> None:
    dates = pd.date_range("2026-01-01", periods=15)
    equity = pd.DataFrame({"date": dates, "equity_jpy": [1000, 1050, 1100, 1000, 980, 1020, 1080, 1120, 1150, 1170, 1160, 1200, 1230, 1220, 1250]})
    report = analyse_journal(JournalInput(trades=sample_trades(), holdings=sample_holdings(), equity=equity, account_equity_jpy=1250, cash_jpy=250, nq_color="GREEN"), starting_equity_jpy=1000)
    assert report.kpis["trades"] == 2
    assert report.kpis["wins"] == 1
    assert report.kpis["losses"] == 1
    assert report.kpis["profit_factor"] > 1
    assert report.kpis["max_drawdown"] < 0
    assert set(report.setup_analysis["setup"]) == {"Breakout", "21EMA Pullback"}
    assert set(report.regime_analysis["nq_color"]) == {"BLUE", "YELLOW"}
    assert report.portfolio_risk["nominal_heat"] > 0


def test_correlation_adjusted_heat_respects_correlation() -> None:
    returns = pd.DataFrame({"AAA": [0.01, 0.02, -0.01, 0.015] * 10, "BBB": [0.01, 0.02, -0.01, 0.015] * 10})
    report = analyse_journal(JournalInput(holdings=sample_holdings(), account_equity_jpy=10_000, price_returns=returns), starting_equity_jpy=10_000)
    assert report.portfolio_risk["correlation_adjusted_heat"] > 0
    assert abs(report.portfolio_risk["correlation_adjusted_heat"] - report.portfolio_risk["nominal_heat"]) < 1e-8


def test_rule_violations_are_fail_closed() -> None:
    trades = sample_trades().copy()
    trades.loc[0, "nq_color"] = "RED"
    trades.loc[0, "stop_price"] = 90
    trades.loc[0, "target_price"] = 110
    trades.loc[0, "rule_followed"] = False
    normalized = normalise_trades(trades)
    violations = detect_rule_violations(normalized, JournalRules())
    kinds = set(violations[violations["trade_id"] == "A"]["violation"])
    assert "RED_ENTRY" in kinds
    assert "STOP_TOO_WIDE" in kinds
    assert "LOW_REWARD_RISK" in kinds
    assert "SELF_REPORTED_BREAK" in kinds


def test_candidates_compare_bought_and_missed() -> None:
    candidates = pd.DataFrame([
        {"date": "2026-01-05", "ticker": "AAA", "rank": 1, "forward_10d_return": 0.20, "qqq_excess_10d": 0.15},
        {"date": "2026-01-05", "ticker": "CCC", "rank": 2, "forward_10d_return": -0.10, "qqq_excess_10d": -0.15},
    ])
    report = analyse_journal(JournalInput(trades=sample_trades(), candidates=candidates, account_equity_jpy=1000), starting_equity_jpy=1000)
    bought = report.missed_analysis.set_index("bucket").loc["買った候補"]
    missed = report.missed_analysis.set_index("bucket").loc["見送った候補"]
    assert bought["candidates"] == 1
    assert missed["candidates"] == 1
    assert bought["avg_forward_10d"] > missed["avg_forward_10d"]


def test_end_to_end_generates_dashboard_cards_and_exports(tmp_path: Path) -> None:
    output = tmp_path / "out"
    summary = run(input_dir=tmp_path / "input", output_dir=output, starting_equity_jpy=7_300_000, demo=True)
    assert summary["kpis"]["trades"] > 0
    expected = [
        "index.html", "daily_card.png", "portfolio_card.png", "social_post_ja.txt", "weekly_review.md",
        "summary.json", "equity_curve.csv", "monthly_returns.csv", "setup_analysis.csv", "regime_analysis.csv",
        "missed_trade_analysis.csv", "candidate_vs_actual.csv", "rule_violations.csv", "sector_allocation.csv",
        "holding_correlations.csv",
    ]
    for name in expected:
        assert (output / name).exists(), name
        assert (output / name).stat().st_size > 0, name
    payload = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert payload["nq_color"] == "GREEN"
    assert (output / "daily_card.png").read_bytes().startswith(b"\x89PNG")
