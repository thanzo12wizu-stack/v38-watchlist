from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _component(root: Path, index: dict[str, Any], key: str, filename: str) -> Any:
    value = index.get(key)
    if value is not None:
        return value
    payload = _read_json(root / filename)
    if key == "entry_candidates" and isinstance(payload, dict):
        return payload.get("candidates", [])
    return payload


def _positive_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _latest_equity(path: Path) -> float | None:
    if not path.exists():
        return None
    try:
        frame = pd.read_csv(path)
    except Exception:
        return None
    if "equity_jpy" not in frame:
        return None
    values = pd.to_numeric(frame["equity_jpy"], errors="coerce").dropna()
    return _positive_float(values.iloc[-1]) if len(values) else None


def _resolve_equity(index: dict[str, Any], output: Path, supplied: float | None) -> tuple[float | None, str]:
    explicit = _positive_float(supplied)
    if explicit is not None:
        return explicit, "EXPLICIT_ACCOUNT_EQUITY"
    for key in ("account_equity_jpy", "total_equity_jpy", "equity_jpy"):
        value = _positive_float(index.get(key))
        if value is not None:
            return value, f"COMMAND_CENTER_{key.upper()}"
    history = _latest_equity(output / "equity.csv")
    if history is not None:
        return history, "ENCRYPTED_EQUITY_HISTORY"
    return None, "ACCOUNT_EQUITY_MISSING"


def _as_of(index: dict[str, Any], market: dict[str, Any]) -> pd.Timestamp:
    for value in (
        index.get("generated_at"), market.get("as_of"), market.get("date"),
        market.get("generated_at"), pd.Timestamp.now(tz="Asia/Tokyo"),
    ):
        stamp = pd.to_datetime(value, errors="coerce")
        if pd.notna(stamp):
            if getattr(stamp, "tzinfo", None) is not None:
                stamp = stamp.tz_convert("Asia/Tokyo").tz_localize(None)
            return pd.Timestamp(stamp).normalize()
    return pd.Timestamp.now(tz="Asia/Tokyo").tz_localize(None).normalize()


def _normalise_color(value: Any) -> str:
    text = str(value or "UNKNOWN").strip().upper()
    aliases = {"青": "BLUE", "緑": "GREEN", "黄": "YELLOW", "赤": "RED"}
    return aliases.get(text, text if text in {"BLUE", "GREEN", "YELLOW", "RED"} else "UNKNOWN")


def _positions_to_holdings(positions: list[dict[str, Any]], account_equity: float, as_of: pd.Timestamp, nq_color: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for item in positions:
        if not isinstance(item, dict):
            continue
        ticker = str(item.get("ticker") or item.get("symbol") or "").strip().upper()
        weight = _positive_float(item.get("weight"))
        if not ticker or weight is None:
            continue
        market_value = account_equity * weight
        current_price = _positive_float(item.get("price") or item.get("current_price")) or market_value
        entry_price = _positive_float(item.get("cost_basis") or item.get("entry_price"))
        gain_pct = pd.to_numeric(pd.Series([item.get("gain_pct")]), errors="coerce").iloc[0]
        if entry_price is None and pd.notna(gain_pct) and 1 + float(gain_pct) / 100 > 0:
            entry_price = current_price / (1 + float(gain_pct) / 100)
        entry_price = entry_price or current_price
        shares = _positive_float(item.get("shares")) or 1.0
        synthetic_fx = market_value / (current_price * shares) if current_price and shares else 1.0
        held_days = pd.to_numeric(pd.Series([item.get("held_days") or item.get("held_sessions")]), errors="coerce").iloc[0]
        entry_date = as_of - pd.offsets.BDay(int(held_days)) if pd.notna(held_days) else pd.NaT
        risk_pct = pd.to_numeric(pd.Series([item.get("risk_contribution_pct")]), errors="coerce").iloc[0]
        planned_loss = account_equity * float(risk_pct) / 100 if pd.notna(risk_pct) else None
        rows.append({
            "ticker": ticker,
            "quantity": shares,
            "entry_price": entry_price,
            "current_price": current_price,
            "fx_to_jpy": synthetic_fx,
            "market_value_jpy": market_value,
            "planned_loss_jpy": planned_loss,
            "sector": item.get("sector") or "UNKNOWN",
            "industry": item.get("industry") or "UNKNOWN",
            "theme": item.get("theme") or "UNKNOWN",
            "stop_price": item.get("stop"),
            "stop_method": item.get("stop_method") or "21EMA_LOW",
            "stop_ema21_low": item.get("stop_ema21_low"),
            "stop_sma10": item.get("stop_sma10"),
            "entry_date": entry_date.date().isoformat() if pd.notna(entry_date) else "",
            "setup": item.get("setup") or item.get("entry_stage") or item.get("strategy") or "UNKNOWN",
            "adr_pct": item.get("adr_pct"),
            "entry_stage": item.get("entry_stage") or 2,
            "entry_price_1": item.get("entry_price_1"),
            "entry_price_2": item.get("entry_price_2"),
            "shares_1": item.get("shares_1"),
            "shares_2": item.get("shares_2"),
            "partial_taken": item.get("partial_taken", False),
            "partial_target_pct": item.get("partial_target_pct", .25),
            "partial_exit_fraction": item.get("partial_exit_fraction", .25),
            "capitulation_status": item.get("capitulation_status") or "NONE",
            "nq_color": nq_color,
            "event_risk": item.get("event_risk", ""),
        })
    return pd.DataFrame(rows)


def _candidates_frame(value: Any, as_of: pd.Timestamp, nq_color: str) -> pd.DataFrame:
    if isinstance(value, dict):
        value = value.get("candidates") or value.get("items") or []
    items = [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []
    rows: list[dict[str, Any]] = []
    for rank, item in enumerate(items, start=1):
        ticker = str(item.get("ticker") or item.get("symbol") or "").strip().upper()
        if not ticker:
            continue
        action = str(item.get("action") or "").upper()
        rows.append({
            "date": str(item.get("date") or item.get("as_of") or as_of.date().isoformat()),
            "ticker": ticker,
            "rank": item.get("rank") or item.get("entry_quality_rank") or rank,
            "setup": item.get("setup") or item.get("stage") or item.get("archetype") or "UNKNOWN",
            "nq_color": _normalise_color(item.get("nq_color") or item.get("market_state") or nq_color),
            "sector": item.get("sector") or "UNKNOWN",
            "theme": item.get("theme") or item.get("industry") or "UNKNOWN",
            "selected": bool(item.get("selected", False) or action == "BUYABLE"),
            "forward_5d_return": item.get("forward_5d_return"),
            "forward_10d_return": item.get("forward_10d_return"),
            "qqq_excess_10d": item.get("qqq_excess_10d"),
            "mfe_10d": item.get("mfe_10d"),
            "mae_10d": item.get("mae_10d"),
        })
    return pd.DataFrame(rows)


def _append_equity(path: Path, date: pd.Timestamp, account_equity: float, gross_exposure: float | None) -> None:
    cash = account_equity * max(0.0, 1.0 - gross_exposure) if gross_exposure is not None else None
    deposits = 0.0
    withdrawals = 0.0
    history = pd.DataFrame()
    if path.exists():
        try:
            history = pd.read_csv(path)
            history_dates = pd.to_datetime(history.get("date"), errors="coerce").dt.normalize()
            same_day = history[history_dates.eq(date.normalize())]
            if not same_day.empty:
                deposits_series = pd.to_numeric(
                    same_day["deposits_jpy"] if "deposits_jpy" in same_day else pd.Series([0.0]),
                    errors="coerce",
                ).fillna(0)
                withdrawals_series = pd.to_numeric(
                    same_day["withdrawals_jpy"] if "withdrawals_jpy" in same_day else pd.Series([0.0]),
                    errors="coerce",
                ).fillna(0)
                deposits = float(deposits_series.iloc[-1])
                withdrawals = float(withdrawals_series.iloc[-1])
        except Exception:
            history = pd.DataFrame()
    row = pd.DataFrame([{
        "date": date.date().isoformat(), "equity_jpy": account_equity,
        "cash_jpy": cash, "deposits_jpy": deposits, "withdrawals_jpy": withdrawals,
    }])
    if not history.empty:
        row = pd.concat([history, row], ignore_index=True)
    row["date"] = pd.to_datetime(row["date"], errors="coerce")
    row = row.dropna(subset=["date"]).sort_values("date").drop_duplicates("date", keep="last")
    row["date"] = row["date"].dt.date.astype(str)
    row.to_csv(path, index=False)


def _append_snapshot(path: Path, incoming: pd.DataFrame, keys: list[str]) -> None:
    if incoming.empty:
        return
    frames = []
    if path.exists():
        try:
            frames.append(pd.read_csv(path))
        except Exception:
            pass
    frames.append(incoming)
    combined = pd.concat(frames, ignore_index=True, sort=False)
    if "date" in combined:
        dates = pd.to_datetime(combined["date"], errors="coerce")
        combined["date"] = dates.dt.date.astype("string")
    combined = combined.drop_duplicates(keys, keep="last")
    sort_columns = [column for column in ("date", "rank", "ticker") if column in combined]
    if sort_columns:
        combined = combined.sort_values(sort_columns, kind="stable", na_position="last")
    combined.to_csv(path, index=False)


def sync_command_center(
    *, intelligence_root: Path, output_dir: Path, account_equity_jpy: float | None = None,
    preserve_existing_holdings: bool = False,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    index = _read_json(intelligence_root / "index.json")
    if not index:
        index = {"dashboard_input_status": "COMPONENT_FILES"}
    market = _component(intelligence_root, index, "market_state", "market_state.json")
    market = market if isinstance(market, dict) else {}
    portfolio = _component(intelligence_root, index, "portfolio_doctor", "portfolio_doctor.json")
    portfolio = portfolio if isinstance(portfolio, dict) else {}
    candidates = _component(intelligence_root, index, "entry_candidates", "entry_candidates.json")
    date = _as_of(index, market)
    nq_color = _normalise_color(market.get("regime") or market.get("nq_color") or market.get("market_gate"))
    account_equity, equity_source = _resolve_equity(index, output_dir, account_equity_jpy)

    candidate_frame = _candidates_frame(candidates, date, nq_color)
    if not candidate_frame.empty:
        _append_snapshot(
            output_dir / "candidates.csv",
            candidate_frame,
            ["date", "ticker"],
        )
    context_frame = pd.DataFrame([{
        "date": date.date().isoformat(), "nq_color": nq_color,
        "vix": market.get("vix"), "breadth": market.get("breadth"),
        "distribution_days": market.get("distribution_days"),
    }])
    _append_snapshot(output_dir / "market_context.csv", context_frame, ["date"])

    positions = portfolio.get("positions") or []
    holdings_written = False
    existing_holdings = output_dir / "holdings.csv"
    if (
        account_equity is not None
        and isinstance(positions, list)
        and not (preserve_existing_holdings and existing_holdings.exists() and existing_holdings.stat().st_size > 0)
    ):
        holdings = _positions_to_holdings(positions, account_equity, date, nq_color)
        holdings.to_csv(existing_holdings, index=False)
        holdings_written = not holdings.empty
    elif preserve_existing_holdings and existing_holdings.exists():
        try:
            holdings_written = not pd.read_csv(existing_holdings).empty
        except Exception:
            holdings_written = False
    if account_equity is not None and equity_source != "ENCRYPTED_EQUITY_HISTORY":
        gross = _positive_float(portfolio.get("gross_exposure"))
        _append_equity(output_dir / "equity.csv", date, account_equity, gross)

    status = {
        "status": "CONNECTED" if holdings_written else "PARTIAL",
        "as_of": date.date().isoformat(),
        "nq_color": nq_color,
        "account_equity_source": equity_source,
        "holdings_written": holdings_written,
        "candidate_count": int(len(candidate_frame)),
        "trade_history_source": (
            "EXECUTIONS"
            if (output_dir / "executions.csv").exists()
            else ("TRADES" if (output_dir / "trades.csv").exists() else "NOT_CONNECTED")
        ),
        "notes": [
            "Market, candidates and portfolio diagnostics are synchronized from Command Center.",
            "Executed trades and deposits/withdrawals require broker or CSV history; they are not inferred from candidates.",
        ],
    }
    (output_dir / "connection_status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return status


def main() -> None:
    parser = argparse.ArgumentParser(description="Synchronize Command Center state into Trade Journal inputs")
    parser.add_argument("--intelligence-root", default="data/intelligence")
    parser.add_argument("--output", default="kaview/data")
    parser.add_argument("--account-equity-jpy", type=float)
    parser.add_argument("--preserve-existing-holdings", action="store_true")
    args = parser.parse_args()
    result = sync_command_center(
        intelligence_root=Path(args.intelligence_root), output_dir=Path(args.output),
        account_equity_jpy=args.account_equity_jpy,
        preserve_existing_holdings=args.preserve_existing_holdings,
    )
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
