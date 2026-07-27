from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from .trade_journal_types import (
    CANDIDATE_COLUMNS, JournalReport, JournalRules, _bool, _ensure_columns, _fraction, _text,
)


def _profit_factor(values: pd.Series) -> float:
    values = pd.to_numeric(values, errors="coerce").dropna()
    gains = values[values > 0].sum()
    losses = -values[values < 0].sum()
    if losses <= 0:
        return float("inf") if gains > 0 else float("nan")
    return float(gains / losses)


def _group_analysis(trades: pd.DataFrame, column: str) -> pd.DataFrame:
    if trades.empty or column not in trades:
        return pd.DataFrame(columns=[column, "trades", "win_rate", "avg_r", "profit_factor", "net_pnl_jpy", "avg_return", "avg_hold_days"])
    rows: list[dict[str, Any]] = []
    for key, group in trades.groupby(column, dropna=False):
        rows.append({
            column: _text(key),
            "trades": len(group),
            "win_rate": float((group["net_pnl_jpy"] > 0).mean()),
            "avg_r": float(group["r_multiple"].mean()) if group["r_multiple"].notna().any() else np.nan,
            "profit_factor": _profit_factor(group["net_pnl_jpy"]),
            "net_pnl_jpy": float(group["net_pnl_jpy"].sum()),
            "avg_return": float(group["return_pct"].mean()) if group["return_pct"].notna().any() else np.nan,
            "avg_hold_days": float(group["hold_days"].mean()) if group["hold_days"].notna().any() else np.nan,
        })
    return pd.DataFrame(rows).sort_values(["net_pnl_jpy", "trades"], ascending=[False, False]).reset_index(drop=True)


def analyse_candidates(candidates: pd.DataFrame, trades: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if candidates.empty:
        empty = pd.DataFrame(columns=["bucket", "candidates", "avg_forward_10d", "avg_qqq_excess_10d", "positive_rate"])
        return empty, pd.DataFrame(columns=["ticker", "date", "selected", "traded", "forward_10d_return", "realized_return", "capture_gap"])
    out = _ensure_columns(candidates, CANDIDATE_COLUMNS)
    out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.normalize()
    out["ticker"] = out["ticker"].map(lambda x: _text(x, "").upper())
    out["selected"] = out["selected"].map(_bool)
    for col in ("forward_5d_return", "forward_10d_return", "qqq_excess_10d", "mfe_10d", "mae_10d"):
        out[col] = pd.to_numeric(out[col], errors="coerce")
    trade_keys = trades[["ticker", "entry_date", "return_pct"]].dropna(subset=["entry_date"]).rename(columns={"entry_date": "date", "return_pct": "realized_return"}) if not trades.empty else pd.DataFrame(columns=["ticker", "date", "realized_return"])
    merged = out.merge(trade_keys, on=["ticker", "date"], how="left")
    merged["traded"] = merged["realized_return"].notna()
    merged["capture_gap"] = merged["realized_return"] - merged["forward_10d_return"]
    rows = []
    masks = {
        "買った候補": merged["traded"],
        "見送った候補": ~merged["traded"],
        "上位10": pd.to_numeric(merged["rank"], errors="coerce").le(10),
        "全候補": pd.Series(True, index=merged.index),
    }
    for bucket, mask in masks.items():
        group = merged[mask]
        rows.append({
            "bucket": bucket,
            "candidates": len(group),
            "avg_forward_10d": float(group["forward_10d_return"].mean()) if group["forward_10d_return"].notna().any() else np.nan,
            "avg_qqq_excess_10d": float(group["qqq_excess_10d"].mean()) if group["qqq_excess_10d"].notna().any() else np.nan,
            "positive_rate": float((group["forward_10d_return"] > 0).mean()) if len(group) else np.nan,
        })
    return pd.DataFrame(rows), merged[["ticker", "date", "selected", "traded", "forward_10d_return", "qqq_excess_10d", "realized_return", "capture_gap", "setup", "nq_color", "sector", "theme"]]


def detect_rule_violations(trades: pd.DataFrame, rules: JournalRules) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame(columns=["trade_id", "ticker", "entry_date", "violation", "severity", "detail"])
    rows: list[dict[str, Any]] = []
    for _, row in trades.iterrows():
        entry = float(row.get("entry_price") or 0)
        stop = row.get("stop_price")
        stop_fraction = abs(entry - float(stop)) / abs(entry) if entry and pd.notna(stop) else np.nan
        target = row.get("target_price")
        rr = abs(float(target) - entry) / abs(entry - float(stop)) if entry and pd.notna(stop) and pd.notna(target) and abs(entry - float(stop)) > 0 else np.nan
        checks: list[tuple[bool, str, str, str]] = [
            (row.get("nq_color") == "RED" and not rules.red_new_entries, "RED_ENTRY", "critical", "赤地合いで新規エントリー"),
            (row.get("nq_color") == "YELLOW" and not rules.yellow_new_entries, "YELLOW_ENTRY", "high", "黄地合いで新規エントリー"),
            (pd.notna(stop_fraction) and stop_fraction > rules.max_stop_fraction, "STOP_TOO_WIDE", "high", f"初期ストップ {stop_fraction:.1%} > {rules.max_stop_fraction:.1%}"),
            (pd.notna(rr) and rr < rules.min_reward_risk, "LOW_REWARD_RISK", "high", f"予定RR {rr:.2f}R < {rules.min_reward_risk:.1f}R"),
            (not _bool(row.get("rule_followed")), "SELF_REPORTED_BREAK", "medium", _text(row.get("mistake_type"), "ルール逸脱")),
        ]
        extra = row.to_dict()
        earnings_days = pd.to_numeric(pd.Series([extra.get("earnings_days")]), errors="coerce").iloc[0]
        extension_atr = pd.to_numeric(pd.Series([extra.get("extension_atr")]), errors="coerce").iloc[0]
        gap_fraction = _fraction(extra.get("gap_pct"), np.nan)
        added_to_loser = _bool(extra.get("added_to_loser"))
        risk_fraction = _fraction(extra.get("initial_risk_pct"), np.nan)
        checks.extend([
            (pd.notna(earnings_days) and abs(earnings_days) <= rules.earnings_exclusion_sessions, "EARNINGS_WINDOW", "critical", f"決算まで {int(earnings_days) if pd.notna(earnings_days) else '—'} 営業日"),
            (pd.notna(extension_atr) and extension_atr > rules.max_extension_atr, "OVEREXTENDED", "high", f"{extension_atr:.2f} ATRの過熱" if pd.notna(extension_atr) else "ATR不明"),
            (pd.notna(gap_fraction) and gap_fraction > rules.max_gap_chase_fraction, "GAP_CHASE", "high", f"ギャップ追い {gap_fraction:.1%}" if pd.notna(gap_fraction) else "ギャップ不明"),
            (added_to_loser, "ADDED_TO_LOSER", "critical", "含み損への追加"),
            (pd.notna(risk_fraction) and risk_fraction > rules.risk_per_trade * 1.05, "RISK_TOO_LARGE", "critical", f"初期リスク {risk_fraction:.2%}" if pd.notna(risk_fraction) else "初期リスク不明"),
        ])
        for triggered, violation, severity, detail in checks:
            if triggered:
                rows.append({"trade_id": row.get("trade_id"), "ticker": row.get("ticker"), "entry_date": row.get("entry_date"), "violation": violation, "severity": severity, "detail": detail})
    return pd.DataFrame(rows)


def allocation_table(holdings: pd.DataFrame, column: str) -> pd.DataFrame:
    if holdings.empty:
        return pd.DataFrame(columns=[column, "market_value_jpy", "allocation", "unrealized_pnl_jpy", "heat_fraction"])
    out = holdings.groupby(column, dropna=False, as_index=False).agg(
        market_value_jpy=("market_value_jpy", "sum"),
        allocation=("allocation", "sum"),
        unrealized_pnl_jpy=("unrealized_pnl_jpy", "sum"),
        heat_fraction=("heat_fraction", "sum"),
    )
    return out.sort_values("market_value_jpy", ascending=False).reset_index(drop=True)


def correlation_adjusted_heat(holdings: pd.DataFrame, price_returns: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    if holdings.empty:
        empty = pd.DataFrame()
        return empty, {"nominal_heat": 0.0, "correlation_adjusted_heat": 0.0, "gross_exposure": 0.0, "largest_cluster": None}
    heat = holdings.set_index("ticker")["heat_fraction"].fillna(0).clip(lower=0)
    tickers = list(heat.index)
    if price_returns.empty:
        corr = pd.DataFrame(np.eye(len(tickers)), index=tickers, columns=tickers)
        note = "価格リターン未提供のため独立仮定"
    else:
        work = price_returns.copy()
        if "date" in work:
            work = work.set_index(pd.to_datetime(work.pop("date"), errors="coerce"))
        work.columns = [str(c).upper() for c in work.columns]
        available = [ticker for ticker in tickers if ticker in work.columns]
        corr = work[available].tail(60).corr(min_periods=15) if available else pd.DataFrame()
        corr = corr.reindex(index=tickers, columns=tickers)
        corr = corr.fillna(0.0).copy()
        for ticker in tickers:
            corr.loc[ticker, ticker] = 1.0
        note = "直近60観測の相関"
    vector = heat.reindex(tickers).to_numpy(dtype=float)
    matrix = corr.to_numpy(dtype=float)
    adjusted = float(math.sqrt(max(0.0, vector @ matrix @ vector.T)))
    nominal = float(vector.sum())
    gross = float(holdings["allocation"].sum())
    cluster = None
    if len(tickers) > 1:
        average_corr = corr.where(~np.eye(len(corr), dtype=bool)).mean(axis=1)
        if average_corr.notna().any():
            cluster = str(average_corr.idxmax())
    return corr, {"nominal_heat": nominal, "correlation_adjusted_heat": adjusted, "gross_exposure": gross, "largest_cluster": cluster, "method": note}


def compute_kpis(trades: pd.DataFrame, equity: pd.DataFrame, violations: pd.DataFrame) -> dict[str, Any]:
    closed = trades[trades["exit_date"].notna()].copy() if not trades.empty else trades
    pnl = closed["net_pnl_jpy"] if not closed.empty else pd.Series(dtype=float)
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    days = max((equity["date"].max() - equity["date"].min()).days, 1) if len(equity) > 1 else 1
    start_equity = float(equity["adjusted_equity_jpy"].iloc[0]) if len(equity) else np.nan
    end_equity = float(equity["adjusted_equity_jpy"].iloc[-1]) if len(equity) else np.nan
    years = days / 365.25
    cagr = (end_equity / start_equity) ** (1 / years) - 1 if start_equity > 0 and end_equity > 0 and years > 0.25 else np.nan
    daily = equity["daily_return"].dropna() if not equity.empty else pd.Series(dtype=float)
    sharpe = float(daily.mean() / daily.std(ddof=1) * math.sqrt(252)) if len(daily) > 2 and daily.std(ddof=1) > 0 else np.nan
    max_dd = float(equity["drawdown"].min()) if not equity.empty else np.nan
    total_return = end_equity / start_equity - 1 if start_equity else np.nan
    recovery_factor = total_return / abs(max_dd) if pd.notna(total_return) and pd.notna(max_dd) and max_dd < 0 else np.nan
    rule_break_trades = violations["trade_id"].nunique() if not violations.empty else 0
    return {
        "trades": int(len(closed)),
        "wins": int((pnl > 0).sum()),
        "losses": int((pnl < 0).sum()),
        "win_rate": float((pnl > 0).mean()) if len(pnl) else np.nan,
        "net_pnl_jpy": float(pnl.sum()) if len(pnl) else 0.0,
        "average_win_jpy": float(wins.mean()) if len(wins) else np.nan,
        "average_loss_jpy": float(losses.mean()) if len(losses) else np.nan,
        "payoff_ratio": float(wins.mean() / abs(losses.mean())) if len(wins) and len(losses) and losses.mean() != 0 else np.nan,
        "profit_factor": _profit_factor(pnl),
        "expectancy_jpy": float(pnl.mean()) if len(pnl) else np.nan,
        "average_r": float(closed["r_multiple"].mean()) if not closed.empty and closed["r_multiple"].notna().any() else np.nan,
        "average_hold_days": float(closed["hold_days"].mean()) if not closed.empty and closed["hold_days"].notna().any() else np.nan,
        "total_return": total_return,
        "cagr": cagr,
        "sharpe": sharpe,
        "max_drawdown": max_dd,
        "recovery_factor": recovery_factor,
        "rule_adherence": 1.0 - rule_break_trades / len(closed) if len(closed) else np.nan,
        "rule_break_trades": int(rule_break_trades),
    }


def _period_return(equity: pd.DataFrame, start: pd.Timestamp) -> float:
    if equity.empty:
        return np.nan
    group = equity[equity["date"] >= start]
    if group.empty:
        return np.nan
    first = float(group["adjusted_equity_jpy"].iloc[0])
    last = float(group["adjusted_equity_jpy"].iloc[-1])
    return last / first - 1 if first else np.nan


def build_weekly_review(report: JournalReport) -> str:
    k = report.kpis
    recent_start = report.as_of - pd.Timedelta(days=7)
    recent = report.trades[report.trades["exit_date"] >= recent_start] if not report.trades.empty else report.trades
    lines = ["# AI Weekly Review", "", f"基準日: {report.as_of.date().isoformat()}", ""]
    weekly_pnl = float(recent["net_pnl_jpy"].sum()) if not recent.empty else 0.0
    lines.append(f"今週は{len(recent)}トレード、実現損益は¥{weekly_pnl:,.0f}。全期間PFは{_fmt(k.get('profit_factor'), 2)}、勝率は{_pct(k.get('win_rate'))}、最大DDは{_pct(k.get('max_drawdown'))}。")
    if not report.setup_analysis.empty:
        eligible = report.setup_analysis[report.setup_analysis["trades"] >= 2]
        if not eligible.empty:
            best = eligible.sort_values(["profit_factor", "avg_r"], ascending=False).iloc[0]
            worst = eligible.sort_values(["profit_factor", "avg_r"], ascending=True).iloc[0]
            lines.append(f"最も機能したセットアップは「{best['setup']}」でPF {_fmt(best['profit_factor'], 2)}・平均R {_fmt(best['avg_r'], 2)}。最も弱いのは「{worst['setup']}」でPF {_fmt(worst['profit_factor'], 2)}。")
    if not report.regime_analysis.empty:
        eligible = report.regime_analysis[report.regime_analysis["trades"] >= 2]
        if not eligible.empty:
            best = eligible.sort_values("profit_factor", ascending=False).iloc[0]
            worst = eligible.sort_values("profit_factor", ascending=True).iloc[0]
            lines.append(f"地合い別では{best['nq_color']}が最良（PF {_fmt(best['profit_factor'], 2)}）、{worst['nq_color']}が最弱（PF {_fmt(worst['profit_factor'], 2)}）。")
    risk = report.portfolio_risk
    lines.append(f"現在の名目Heatは{_pct(risk.get('nominal_heat'))}、相関調整後Heatは{_pct(risk.get('correlation_adjusted_heat'))}、Gross Exposureは{_pct(risk.get('gross_exposure'))}。")
    if not report.rule_violations.empty:
        top = report.rule_violations["violation"].value_counts().head(3)
        issues = "、".join(f"{name} {count}件" for name, count in top.items())
        lines.append(f"改善優先度が高いルール逸脱は{issues}。まず新規エントリー前の機械的チェックで遮断する。")
    else:
        lines.append("記録上の重大なルール逸脱は検出されていない。今週はサイズを増やすより、同じ条件の再現性を確認する。")
    if not report.missed_analysis.empty:
        bought = report.missed_analysis[report.missed_analysis["bucket"] == "買った候補"]
        missed = report.missed_analysis[report.missed_analysis["bucket"] == "見送った候補"]
        if not bought.empty and not missed.empty and pd.notna(bought.iloc[0]["avg_forward_10d"]) and pd.notna(missed.iloc[0]["avg_forward_10d"]):
            gap = float(bought.iloc[0]["avg_forward_10d"] - missed.iloc[0]["avg_forward_10d"])
            lines.append(f"候補選択の10日後リターン差は{gap:+.2%}。プラスなら選択精度、マイナスなら見送り判断とエントリー位置を再点検する。")
    lines.extend(["", "## 来週の行動", "", "1. PFと平均Rが高い上位セットアップに発注を集中する。", "2. NQ色とセクター集中を発注前に確認し、相関調整後Heatで上限を決める。", "3. ルール逸脱が1件でも出た類型は、次回エントリー前にチェック項目を必須化する。", ""])
    return "\n".join(lines)


def _fmt(value: Any, digits: int = 1) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(number):
        return "∞" if number > 0 else "—"
    return f"{number:.{digits}f}"


def _pct(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    return f"{number:.1%}" if math.isfinite(number) else "—"
