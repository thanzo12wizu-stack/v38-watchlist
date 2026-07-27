from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .trade_journal_types import JournalInput, JournalReport, JournalRules, _normalise_color
from .trade_journal_data import build_equity_curve, monthly_return_table, normalise_holdings, normalise_trades
from .trade_journal_analysis import (
    _group_analysis, _period_return, allocation_table, analyse_candidates,
    build_weekly_review, compute_kpis, correlation_adjusted_heat, detect_rule_violations,
)

__all__ = [
    "JournalInput", "JournalReport", "JournalRules", "analyse_journal",
    "normalise_trades", "normalise_holdings", "detect_rule_violations",
    "write_report_data",
]


def analyse_journal(data: JournalInput, *, starting_equity_jpy: float = 0.0) -> JournalReport:
    account_equity = float(data.account_equity_jpy or starting_equity_jpy or 0)
    trades = normalise_trades(data.trades)
    equity = build_equity_curve(data.equity, trades, account_equity)
    if account_equity <= 0 and not equity.empty:
        account_equity = float(equity["equity_jpy"].iloc[-1])
    holdings = normalise_holdings(data.holdings, account_equity)
    cash = float(data.cash_jpy) if data.cash_jpy is not None else (
        float(equity["cash_jpy"].dropna().iloc[-1]) if not equity.empty and equity["cash_jpy"].notna().any() else max(0.0, account_equity - float(holdings["market_value_jpy"].sum() if not holdings.empty else 0))
    )
    as_of_candidates: list[pd.Timestamp] = []
    for frame, col in ((equity, "date"), (trades, "exit_date"), (trades, "entry_date")):
        if not frame.empty and col in frame and frame[col].notna().any():
            as_of_candidates.append(pd.to_datetime(frame[col], errors="coerce").max().normalize())
    as_of = max(as_of_candidates) if as_of_candidates else pd.Timestamp.now().normalize()
    nq_color = _normalise_color(data.nq_color)
    if nq_color == "UNKNOWN" and not data.market_context.empty:
        context = data.market_context.copy()
        color_column = next((c for c in ("nq_color", "market_state", "nq_gate", "gate_color", "regime_color") if c in context), None)
        if color_column:
            nq_color = _normalise_color(context[color_column].dropna().iloc[-1])
    if nq_color == "UNKNOWN" and not trades.empty and trades["nq_color"].ne("UNKNOWN").any():
        nq_color = _normalise_color(trades.loc[trades["nq_color"].ne("UNKNOWN"), "nq_color"].iloc[-1])
    violations = detect_rule_violations(trades, data.rules)
    setup = _group_analysis(trades, "setup")
    regime = _group_analysis(trades, "nq_color")
    missed, candidate_comparison = analyse_candidates(data.candidates, trades)
    sector = allocation_table(holdings, "sector")
    theme = allocation_table(holdings, "theme")
    corr, portfolio_risk = correlation_adjusted_heat(holdings, data.price_returns)
    kpis = compute_kpis(trades, equity, violations)
    kpis.update({
        "daily_return": float(equity["daily_return"].iloc[-1]) if not equity.empty else np.nan,
        "mtd_return": _period_return(equity, as_of.replace(day=1)),
        "ytd_return": _period_return(equity, pd.Timestamp(year=as_of.year, month=1, day=1)),
        "unrealized_pnl_jpy": float(holdings["unrealized_pnl_jpy"].sum()) if not holdings.empty else 0.0,
        "cash_fraction": cash / account_equity if account_equity else np.nan,
    })
    report = JournalReport(
        as_of=as_of,
        account_equity_jpy=account_equity,
        cash_jpy=cash,
        nq_color=nq_color,
        trades=trades,
        holdings=holdings,
        equity=equity,
        monthly_returns=monthly_return_table(equity),
        setup_analysis=setup,
        regime_analysis=regime,
        missed_analysis=missed,
        candidate_comparison=candidate_comparison,
        rule_violations=violations,
        sector_allocation=sector,
        theme_allocation=theme,
        correlation=corr,
        kpis=kpis,
        portfolio_risk=portfolio_risk,
        weekly_review="",
        source_notes=list(data.source_notes),
    )
    report.weekly_review = build_weekly_review(report)
    return report


def write_report_data(report: JournalReport, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    report.trades.to_csv(output_dir / "trades_normalized.csv", index=False)
    report.holdings.to_csv(output_dir / "holdings_normalized.csv", index=False)
    report.equity.to_csv(output_dir / "equity_curve.csv", index=False)
    report.monthly_returns.to_csv(output_dir / "monthly_returns.csv", index=False)
    report.setup_analysis.to_csv(output_dir / "setup_analysis.csv", index=False)
    report.regime_analysis.to_csv(output_dir / "regime_analysis.csv", index=False)
    report.missed_analysis.to_csv(output_dir / "missed_trade_analysis.csv", index=False)
    report.candidate_comparison.to_csv(output_dir / "candidate_vs_actual.csv", index=False)
    report.rule_violations.to_csv(output_dir / "rule_violations.csv", index=False)
    report.sector_allocation.to_csv(output_dir / "sector_allocation.csv", index=False)
    report.theme_allocation.to_csv(output_dir / "theme_allocation.csv", index=False)
    report.correlation.to_csv(output_dir / "holding_correlations.csv")
    (output_dir / "weekly_review.md").write_text(report.weekly_review, encoding="utf-8")
    (output_dir / "summary.json").write_text(json.dumps(report.to_summary_dict(), ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
