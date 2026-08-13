from __future__ import annotations

import gzip
import json
import pickle
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd

from .journal import JournalInput, JournalRules


def _read_table(path: Path | None) -> pd.DataFrame:
    if path is None or not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    suffixes = "".join(path.suffixes).lower()
    if suffixes.endswith(".csv"):
        try:
            return pd.read_csv(path)
        except pd.errors.EmptyDataError:
            return pd.DataFrame()
    if suffixes.endswith(".jsonl") or suffixes.endswith(".jsonl.gz"):
        opener = gzip.open if suffixes.endswith(".gz") else open
        rows: list[dict[str, Any]] = []
        with opener(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
        return pd.DataFrame(rows)
    if suffixes.endswith(".json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            return pd.DataFrame(payload)
        if isinstance(payload, dict):
            for key in ("rows", "data", "trades", "holdings", "candidates", "equity"):
                if isinstance(payload.get(key), list):
                    return pd.DataFrame(payload[key])
            return pd.DataFrame([payload])
    raise ValueError(f"unsupported table format: {path}")


def _read_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def _status_notes(input_dir: Path) -> list[str]:
    notes: list[str] = []
    ingestion = _read_json(input_dir / "ingestion_status.json")
    executions = ingestion.get("executions")
    if isinstance(executions, dict):
        notes.append(
            "約定取込: "
            f"{int(executions.get('execution_rows') or 0)}行 / "
            f"完結{int(executions.get('closed_positions') or 0)} / "
            f"未決済{int(executions.get('open_positions') or 0)} / "
            f"部分Exit{int(executions.get('partial_exit_positions') or 0)}"
        )
    warnings = ingestion.get("warnings")
    if isinstance(warnings, list):
        notes.extend(f"取込警告: {warning}" for warning in warnings if warning)
    connection = _read_json(input_dir / "connection_status.json")
    if connection:
        notes.append(
            "同期元: "
            f"資産={connection.get('account_equity_source') or 'UNKNOWN'} / "
            f"取引={connection.get('trade_history_source') or 'NOT_CONNECTED'}"
        )
    return notes


def _discover(base: Path, names: Iterable[str]) -> Path | None:
    for name in names:
        path = base / name
        if path.exists():
            return path
    return None


def _portfolio_from_json(path: Path | None) -> tuple[pd.DataFrame, float | None, float | None, str | None, list[str]]:
    payload = _read_json(path)
    if not payload:
        return pd.DataFrame(), None, None, None, []
    holdings = pd.DataFrame(payload.get("holdings") or payload.get("positions") or [])
    if not holdings.empty and "planned_loss_jpy" not in holdings and "market_value_jpy" in holdings:
        stop = pd.to_numeric(holdings.get("stop_fraction", holdings.get("stop_pct")), errors="coerce")
        stop = stop.where(stop.abs() <= 1, stop / 100.0)
        holdings["planned_loss_jpy"] = pd.to_numeric(holdings["market_value_jpy"], errors="coerce") * stop.abs()
    account = payload.get("account_equity_jpy", payload.get("total_equity_jpy", payload.get("equity_jpy")))
    cash = payload.get("available_cash_jpy", payload.get("cash_jpy", payload.get("buying_power_jpy")))
    nq = payload.get("nq_color", payload.get("market_state", payload.get("nq_gate")))
    notes = [f"Portfolio: {path}"] if path else []
    return holdings, float(account) if account is not None else None, float(cash) if cash is not None else None, str(nq) if nq is not None else None, notes


def _load_signal_candidates(research_root: Path | None) -> tuple[pd.DataFrame, pd.DataFrame, str | None, list[str]]:
    if research_root is None or not research_root.exists():
        return pd.DataFrame(), pd.DataFrame(), None, []
    signal_root = research_root / "signals"
    files = sorted(signal_root.glob("*.jsonl.gz")) + sorted(signal_root.glob("*.jsonl"))
    if not files:
        return pd.DataFrame(), pd.DataFrame(), None, []
    frames = [_read_table(path) for path in files[-2:]]
    panel = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if panel.empty or "date" not in panel:
        return pd.DataFrame(), pd.DataFrame(), None, [f"Signals: {signal_root}（候補行なし）"]
    panel["date"] = pd.to_datetime(panel["date"], errors="coerce").dt.normalize()
    as_of = panel["date"].max()
    latest = panel[panel["date"] == as_of].copy()
    aliases = {
        "a_rank": "rank", "alpha_rank": "rank", "market_state": "nq_color", "nq_gate": "nq_color",
        "forward_return_10d": "forward_10d_return", "excess_10d": "qqq_excess_10d",
        "individual_stage": "setup", "archetype": "setup",
    }
    for src, dst in aliases.items():
        if src in latest and dst not in latest:
            latest[dst] = latest[src]
    if "rank" not in latest:
        sort_col = next((c for c in ("base_composite", "leadership_quality", "entry_quality", "rs189") if c in latest), None)
        latest = latest.sort_values(sort_col, ascending=False) if sort_col else latest.sort_values("ticker")
        latest["rank"] = np.arange(1, len(latest) + 1)
    latest["selected"] = False
    color_col = next((c for c in ("nq_color", "market_state", "nq_gate", "gate_color", "regime_color") if c in latest), None)
    nq = str(latest[color_col].dropna().iloc[0]) if color_col and latest[color_col].notna().any() else None
    context_cols = [c for c in ("date", "nq_color", "market_state", "nq_gate", "gate_color", "regime_color", "vix", "breadth", "distribution_days") if c in latest]
    context = latest[context_cols].head(1).copy() if context_cols else pd.DataFrame()
    return latest, context, nq, [f"Signals: {signal_root} / as_of={as_of.date().isoformat()}"]


def _enrich_candidates_from_outcomes(
    candidates: pd.DataFrame,
    research_root: Path | None,
) -> tuple[pd.DataFrame, list[str]]:
    if candidates.empty or research_root is None:
        return candidates, []
    if "date" not in candidates or "ticker" not in candidates:
        return candidates, []
    work = candidates.copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce").dt.normalize()
    work["ticker"] = work["ticker"].fillna("").astype(str).str.strip().str.upper()
    years = sorted(set(work["date"].dropna().dt.year.astype(int)))
    outcome_root = research_root / "outcomes"
    files = [
        path
        for year in years
        for path in (
            outcome_root / f"year={year}.jsonl.gz",
            outcome_root / f"year={year}.jsonl",
        )
        if path.exists()
    ]
    if not files:
        return work, []
    frames = [_read_table(path) for path in files]
    outcomes = pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()
    required = {"date", "ticker"}
    if outcomes.empty or not required.issubset(outcomes.columns):
        return work, [f"Research outcomes: {outcome_root}（候補照合列なし）"]
    outcomes["date"] = pd.to_datetime(outcomes["date"], errors="coerce").dt.normalize()
    outcomes["ticker"] = outcomes["ticker"].fillna("").astype(str).str.strip().str.upper()
    candidate_keys = work[["date", "ticker"]].copy()
    candidate_keys["ticker"] = candidate_keys["ticker"].fillna("").astype(str).str.strip().str.upper()
    outcomes = outcomes.merge(candidate_keys.drop_duplicates(), on=["date", "ticker"], how="inner")
    aliases = {
        "return_5": "forward_5d_return",
        "return_10": "forward_10d_return",
        "excess_10": "qqq_excess_10d",
        "mfe_10": "mfe_10d",
        "mae_10": "mae_10d",
    }
    available = {source: target for source, target in aliases.items() if source in outcomes}
    if not available:
        return work, [f"Research outcomes: {outcome_root}（10日結果未確定）"]
    outcome_columns = ["date", "ticker", *available]
    ready = outcomes[outcome_columns].rename(columns=available)
    ready = ready.sort_values(["date", "ticker"]).drop_duplicates(["date", "ticker"], keep="last")
    original_columns = list(work.columns)
    merged = work.merge(ready, on=["date", "ticker"], how="left", suffixes=("", "_research"))
    for target in available.values():
        research_column = f"{target}_research"
        if target not in merged:
            merged[target] = merged[research_column]
        elif research_column in merged:
            merged[target] = pd.to_numeric(merged[target], errors="coerce").where(
                pd.to_numeric(merged[target], errors="coerce").notna(),
                pd.to_numeric(merged[research_column], errors="coerce"),
            )
        if research_column in merged:
            merged = merged.drop(columns=research_column)
    ordered = [column for column in original_columns if column in merged]
    ordered.extend(column for column in merged.columns if column not in ordered)
    enriched = (
        int(pd.to_numeric(merged["forward_10d_return"], errors="coerce").notna().sum())
        if "forward_10d_return" in merged
        else 0
    )
    return merged[ordered], [f"Research outcomes: {outcome_root} / 10d_ready={enriched}"]


def _load_price_returns(path: Path | None) -> pd.DataFrame:
    if path is None or not path.exists():
        return pd.DataFrame()
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    with path.open("rb") as handle:
        payload = pickle.load(handle)
    if isinstance(payload, pd.DataFrame):
        frame = payload.copy()
        if isinstance(frame.columns, pd.MultiIndex):
            close_level = next((level for level in frame.columns.levels[0] if str(level).lower() in {"close", "adj close", "adj_close"}), None)
            if close_level is not None:
                frame = frame[close_level]
        return frame.pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan)
    if isinstance(payload, Mapping):
        series: dict[str, pd.Series] = {}
        for ticker, value in payload.items():
            if isinstance(value, pd.DataFrame):
                close_col = next((c for c in ("Adj Close", "adj_close", "Close", "close") if c in value), None)
                if close_col:
                    series[str(ticker).upper()] = pd.to_numeric(value[close_col], errors="coerce")
            elif isinstance(value, pd.Series):
                series[str(ticker).upper()] = pd.to_numeric(value, errors="coerce")
        if series:
            prices = pd.concat(series, axis=1).sort_index()
            return prices.pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan)
    return pd.DataFrame()


def _demo_input(starting_equity_jpy: float) -> JournalInput:
    dates = pd.bdate_range("2026-01-05", periods=145)
    rng = np.random.default_rng(38)
    daily = rng.normal(0.0010, 0.010, len(dates))
    equity_values = starting_equity_jpy * np.cumprod(1 + daily)
    equity = pd.DataFrame({"date": dates, "equity_jpy": equity_values, "cash_jpy": equity_values * 0.28, "deposits_jpy": 0, "withdrawals_jpy": 0})
    tickers = ["SNDK", "MU", "FCX", "STLD", "APP", "HOOD", "VRT", "PLTR", "NVDA", "CRDO", "WDC", "AVGO"]
    setups = ["21EMA Pullback", "Breakout", "2nd Pivot", "Pocket Pivot"]
    colors = ["BLUE", "GREEN", "GREEN", "YELLOW"]
    rows = []
    for i in range(42):
        entry_date = dates[min(i * 3, len(dates) - 7)]
        exit_date = dates[min(i * 3 + int(rng.integers(2, 9)), len(dates) - 1)]
        entry = float(rng.uniform(25, 220))
        ret = float(rng.choice([rng.normal(0.21, 0.11), rng.normal(-0.045, 0.02)], p=[0.42, 0.58]))
        exit_price = entry * (1 + ret)
        qty = float(max(1, int(320_000 / entry / 150)))
        stop = entry * (1 - float(rng.uniform(0.025, 0.055)))
        rows.append({
            "trade_id": f"D{i+1:03d}", "ticker": tickers[i % len(tickers)], "side": "LONG",
            "entry_date": entry_date, "exit_date": exit_date, "entry_price": entry, "exit_price": exit_price,
            "quantity": qty, "point_value": 1, "fx_to_jpy": 150, "fees_jpy": 500, "taxes_jpy": 0,
            "stop_price": stop, "target_price": entry + 3.5 * (entry - stop), "setup": setups[i % len(setups)],
            "nq_color": colors[i % len(colors)], "sector": "Technology" if i % 3 else "Materials",
            "theme": "AI / Semis" if i % 3 else "Metals", "rule_followed": i % 11 != 0,
            "mistake_type": "GAP_CHASE" if i % 11 == 0 else "", "exit_reason": "Trail" if ret > 0 else "Stop",
        })
    trades = pd.DataFrame(rows)
    holdings = pd.DataFrame([
        {"ticker": "SNDK", "quantity": 22, "entry_price": 186, "current_price": 203, "fx_to_jpy": 150, "sector": "Technology", "theme": "Memory", "stop_price": 194, "entry_date": dates[-24], "setup": "2nd Pivot", "nq_color": "GREEN"},
        {"ticker": "FCX", "quantity": 55, "entry_price": 54, "current_price": 57, "fx_to_jpy": 150, "sector": "Materials", "theme": "Copper", "stop_price": 53.5, "entry_date": dates[-15], "setup": "21EMA Pullback", "nq_color": "GREEN"},
        {"ticker": "VRT", "quantity": 18, "entry_price": 149, "current_price": 142, "fx_to_jpy": 150, "sector": "Industrials", "theme": "Data Center Power", "stop_price": 137, "entry_date": dates[-8], "setup": "Breakout", "nq_color": "GREEN"},
        {"ticker": "HOOD", "quantity": 28, "entry_price": 104, "current_price": 119, "fx_to_jpy": 150, "sector": "Financials", "theme": "Digital Brokerage", "stop_price": 111, "entry_date": dates[-34], "setup": "Pocket Pivot", "nq_color": "BLUE"},
    ])
    candidates = pd.DataFrame([
        {"date": dates[-20 + i // 5], "ticker": tickers[i % len(tickers)], "rank": i % 20 + 1, "setup": setups[i % 4], "nq_color": colors[i % 4], "sector": "Technology", "theme": "AI", "selected": i % 7 == 0, "forward_10d_return": rng.normal(0.05, 0.12), "qqq_excess_10d": rng.normal(0.02, 0.09)}
        for i in range(80)
    ])
    returns = pd.DataFrame({ticker: rng.normal(0.0008, 0.025, 80) for ticker in holdings["ticker"]})
    return JournalInput(trades=trades, holdings=holdings, equity=equity, candidates=candidates, account_equity_jpy=float(equity_values[-1]), cash_jpy=float(equity_values[-1] * 0.28), nq_color="GREEN", price_returns=returns, source_notes=["デモデータ（実データ投入後に置換）"])


def write_templates(input_dir: Path) -> None:
    input_dir.mkdir(parents=True, exist_ok=True)
    templates = {
        "trades.csv": "trade_id,ticker,side,entry_date,exit_date,entry_price,exit_price,quantity,point_value,fx_to_jpy,fees_jpy,taxes_jpy,stop_price,target_price,setup,nq_color,sector,industry,theme,entry_reason,exit_reason,rule_followed,mistake_type,notes,mfe_pct,mae_pct\n",
        "executions.csv": "execution_id,position_id,ticker,side,action,executed_at,price,quantity,point_value,fx_to_jpy,fees_jpy,taxes_jpy,stop_price,target_price,setup,nq_color,sector,industry,theme,entry_reason,exit_reason,rule_followed,mistake_type,notes\n",
        "holdings.csv": "ticker,quantity,entry_price,current_price,fx_to_jpy,sector,industry,theme,adr_pct,stop_method,stop_price,stop_ema21_low,stop_sma10,entry_date,setup,nq_color,event_risk,entry_stage,entry_price_1,entry_price_2,shares_1,shares_2,partial_taken,partial_target_pct,partial_exit_fraction,capitulation_status\n",
        "equity.csv": "date,equity_jpy,cash_jpy,deposits_jpy,withdrawals_jpy\n",
        "cash_flows.csv": "flow_id,date,type,amount_jpy,notes\n",
        "candidates.csv": "date,ticker,rank,setup,nq_color,sector,theme,selected,forward_5d_return,forward_10d_return,qqq_excess_10d,mfe_10d,mae_10d\n",
        "market_context.csv": "date,nq_color,vix,breadth,distribution_days\n",
    }
    for name, header in templates.items():
        path = input_dir / name
        if not path.exists():
            path.write_text(header, encoding="utf-8")


def load_input(
    *, input_dir: Path, portfolio_path: Path | None, rules_path: Path | None,
    research_root: Path | None, prices_path: Path | None, starting_equity_jpy: float,
    demo: bool = False,
) -> JournalInput:
    if demo:
        return _demo_input(starting_equity_jpy)
    input_dir.mkdir(parents=True, exist_ok=True)
    trades_path = _discover(input_dir, ["trades.csv", "trades.json", "trade_journal.csv"])
    holdings_path = _discover(input_dir, ["holdings.csv", "positions.csv", "portfolio.csv"])
    equity_path = _discover(input_dir, ["equity.csv", "asset_history.csv", "balance_history.csv"])
    candidates_path = _discover(input_dir, ["candidates.csv", "candidate_history.csv", "watchlist_history.csv"])
    context_path = _discover(input_dir, ["market_context.csv", "market_history.csv", "nq_history.csv"])
    trades = _read_table(trades_path)
    holdings = _read_table(holdings_path)
    equity = _read_table(equity_path)
    candidates = _read_table(candidates_path)
    context = _read_table(context_path)
    auto_portfolio = portfolio_path
    if auto_portfolio is None:
        portfolio_candidates = [
            input_dir / "portfolio.json", input_dir.parent / "portfolio.json", Path("portfolio.json"),
            Path("config/portfolio.json"), Path("config/defensive_risk_portfolio.json"),
        ]
        auto_portfolio = next((path for path in portfolio_candidates if path.exists()), None)
    portfolio_holdings, account, cash, nq, notes = _portfolio_from_json(auto_portfolio)
    if holdings.empty and not portfolio_holdings.empty:
        holdings = portfolio_holdings
    signal_candidates, signal_context, signal_nq, signal_notes = _load_signal_candidates(research_root)
    if candidates.empty and not signal_candidates.empty:
        candidates = signal_candidates
    if context.empty and not signal_context.empty:
        context = signal_context
    nq = nq or signal_nq
    rules_payload = _read_json(rules_path)
    if "rules" in rules_payload and isinstance(rules_payload["rules"], dict):
        rules_payload = rules_payload["rules"]
    rules = JournalRules.from_mapping(rules_payload)
    candidates, outcome_notes = _enrich_candidates_from_outcomes(candidates, research_root)
    source_notes = notes + signal_notes + outcome_notes + _status_notes(input_dir)
    for label, path in (("Trades", trades_path), ("Holdings", holdings_path), ("Equity", equity_path), ("Candidates", candidates_path), ("Market context", context_path), ("Rules", rules_path)):
        if path:
            source_notes.append(f"{label}: {path}")
    return JournalInput(
        trades=trades, holdings=holdings, equity=equity, candidates=candidates, market_context=context,
        account_equity_jpy=account, cash_jpy=cash, nq_color=nq, rules=rules,
        price_returns=_load_price_returns(prices_path), source_notes=source_notes,
    )
