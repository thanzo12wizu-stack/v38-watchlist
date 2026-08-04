from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from intelligence_engine.trade_journal import (
    JournalInput,
    JournalRules,
    analyse_journal,
    detect_rule_violations,
    normalise_holdings,
    normalise_trades,
)
from intelligence_engine.trade_journal_run import _enrich_candidates_from_outcomes, run


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


def test_holding_operations_normalize_two_entries_trail_partial_and_capitulation() -> None:
    holdings = pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "quantity": 0,
                "entry_price_1": 100,
                "entry_price_2": 110,
                "shares_1": 5,
                "shares_2": 5,
                "current_price": 132,
                "fx_to_jpy": 1,
                "stop_method": "10MA",
                "stop_price": 90,
                "stop_ema21_low": 118,
                "stop_sma10": 121,
                "adr_pct": 4.5,
                "partial_taken": False,
                "capitulation_status": "セリクラ待ち",
            }
        ]
    )

    result = normalise_holdings(holdings, 10_000).iloc[0]

    assert result["quantity"] == 10
    assert result["entry_price"] == 105
    assert result["entry_stage"] == 2
    assert result["stop_method"] == "10MA"
    assert result["stop_price"] == 121
    assert result["partial_target_price"] == 131.25
    assert bool(result["partial_take_due"])
    assert result["capitulation_status"] == "WAITING"


def test_kpis_drawdown_setup_and_regime() -> None:
    dates = pd.date_range("2026-01-01", periods=15)
    equity = pd.DataFrame({"date": dates, "equity_jpy": [1000, 1050, 1100, 1000, 980, 1020, 1080, 1120, 1150, 1170, 1160, 1200, 1230, 1220, 1250]})
    report = analyse_journal(JournalInput(trades=sample_trades(), holdings=sample_holdings(), equity=equity, account_equity_jpy=1250, cash_jpy=250, nq_color="GREEN"), starting_equity_jpy=1000)
    assert report.kpis["trades"] == 2
    assert report.kpis["wins"] == 1
    assert report.kpis["losses"] == 1
    assert report.kpis["profit_factor"] > 1
    assert report.kpis["max_drawdown"] < 0
    assert not report.drawdown_episodes.empty
    assert set(report.setup_analysis["setup"]) == {"Breakout", "21EMA Pullback"}
    assert set(report.regime_analysis["nq_color"]) == {"BLUE", "YELLOW"}
    assert report.portfolio_risk["nominal_heat"] > 0


def test_ytd_is_unknown_when_equity_history_starts_midyear() -> None:
    equity = pd.DataFrame(
        {
            "date": pd.date_range("2026-04-14", periods=4),
            "equity_jpy": [1_000, 1_010, 1_020, 1_030],
        }
    )

    report = analyse_journal(
        JournalInput(equity=equity, account_equity_jpy=1_030),
        starting_equity_jpy=0,
    )

    assert pd.isna(report.kpis["ytd_return"])


def test_current_period_metrics_are_hidden_when_equity_is_stale() -> None:
    equity = pd.DataFrame(
        {
            "date": ["2026-07-01", "2026-07-02"],
            "equity_jpy": [1_000, 1_010],
        }
    )
    candidates = pd.DataFrame(
        [{"date": "2026-07-20", "ticker": "AAA", "rank": 1}]
    )

    report = analyse_journal(
        JournalInput(equity=equity, candidates=candidates, account_equity_jpy=1_010),
        starting_equity_jpy=0,
    )

    assert report.kpis["equity_age_days"] == 18
    assert pd.isna(report.kpis["daily_return"])
    assert pd.isna(report.kpis["mtd_return"])
    assert pd.isna(report.kpis["ytd_return"])


def test_correlation_adjusted_heat_respects_correlation() -> None:
    returns = pd.DataFrame({"AAA": [0.01, 0.02, -0.01, 0.015] * 10, "BBB": [0.01, 0.02, -0.01, 0.015] * 10})
    report = analyse_journal(JournalInput(holdings=sample_holdings(), account_equity_jpy=10_000, price_returns=returns), starting_equity_jpy=10_000)
    assert report.portfolio_risk["correlation_adjusted_heat"] > 0
    assert abs(report.portfolio_risk["correlation_adjusted_heat"] - report.portfolio_risk["nominal_heat"]) < 1e-8


def test_portfolio_adr_is_market_value_weighted_and_reports_coverage() -> None:
    holdings = sample_holdings().copy()
    holdings["adr_pct"] = [4.0, 2.0]
    report = analyse_journal(
        JournalInput(holdings=holdings, account_equity_jpy=10_000),
        starting_equity_jpy=10_000,
    )

    # AAA market value 1,100 and BBB 960.
    expected = (1_100 * 4.0 + 960 * 2.0) / (1_100 + 960)
    assert abs(report.portfolio_risk["portfolio_adr_pct"] - expected) < 1e-10
    assert report.portfolio_risk["adr_coverage"] == 1.0


def test_missing_correlation_data_does_not_reduce_reported_heat() -> None:
    report = analyse_journal(
        JournalInput(holdings=sample_holdings(), account_equity_jpy=10_000),
        starting_equity_jpy=10_000,
    )

    assert report.portfolio_risk["correlation_adjusted_heat"] == report.portfolio_risk["nominal_heat"]
    assert "完全相関" in report.portfolio_risk["method"]


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


def test_candidate_is_linked_to_next_session_entry() -> None:
    candidates = pd.DataFrame(
        [
            {
                "date": "2026-01-04",
                "ticker": "AAA",
                "rank": 1,
                "forward_10d_return": 0.20,
                "qqq_excess_10d": 0.15,
            }
        ]
    )

    report = analyse_journal(
        JournalInput(trades=sample_trades(), candidates=candidates, account_equity_jpy=1000),
        starting_equity_jpy=1000,
    )

    comparison = report.candidate_comparison.iloc[0]
    assert bool(comparison["traded"])
    assert round(float(comparison["realized_return"]), 4) == 0.19


def test_candidate_history_is_enriched_when_research_outcome_matures(tmp_path: Path) -> None:
    candidates = pd.DataFrame(
        [{"date": "2026-01-05", "ticker": "aaa", "rank": 1, "forward_10d_return": None}]
    )
    outcome_root = tmp_path / "outcomes"
    outcome_root.mkdir()
    pd.DataFrame(
        [
            {
                "date": "2026-01-05", "ticker": "AAA", "return_5": 0.05,
                "return_10": 0.12, "excess_10": 0.08, "mfe_10": 0.16, "mae_10": -0.03,
            }
        ]
    ).to_json(outcome_root / "year=2026.jsonl", orient="records", lines=True)

    enriched, notes = _enrich_candidates_from_outcomes(candidates, tmp_path)

    assert enriched.loc[0, "ticker"] == "AAA"
    assert enriched.loc[0, "forward_10d_return"] == 0.12
    assert enriched.loc[0, "qqq_excess_10d"] == 0.08
    assert "10d_ready=1" in notes[0]


def test_end_to_end_generates_dashboard_cards_and_exports(tmp_path: Path) -> None:
    output = tmp_path / "out"
    summary = run(input_dir=tmp_path / "input", output_dir=output, starting_equity_jpy=7_300_000, demo=True)
    assert summary["kpis"]["trades"] > 0
    expected = [
        "index.html", "daily_card.png", "portfolio_card.png", "social_post_ja.txt", "weekly_review.md",
        "summary.json", "equity_curve.csv", "monthly_returns.csv", "setup_analysis.csv", "regime_analysis.csv",
        "missed_trade_analysis.csv", "candidate_vs_actual.csv", "rule_violations.csv", "sector_allocation.csv",
        "holding_correlations.csv",
        "holding_correlation_pairs.csv", "drawdown_episodes.csv",
    ]
    for name in expected:
        assert (output / name).exists(), name
        assert (output / name).stat().st_size > 0, name
    payload = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert payload["nq_color"] == "GREEN"
    assert (output / "daily_card.png").read_bytes().startswith(b"\x89PNG")
