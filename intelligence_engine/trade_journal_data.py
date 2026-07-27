from __future__ import annotations

import math
import numpy as np
import pandas as pd

from .trade_journal_types import (
    EQUITY_COLUMNS, HOLDING_COLUMNS, TRADE_COLUMNS, _bool, _ensure_columns,
    _normalise_color, _num, _text,
)


def normalise_trades(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=(*TRADE_COLUMNS, "gross_pnl_jpy", "net_pnl_jpy", "return_pct", "planned_risk_jpy", "r_multiple", "hold_days"))
    out = _ensure_columns(frame, TRADE_COLUMNS)
    aliases = {
        "symbol": "ticker", "code": "ticker", "date_in": "entry_date", "date_out": "exit_date",
        "buy_price": "entry_price", "sell_price": "exit_price", "shares": "quantity",
        "size": "quantity", "commission_jpy": "fees_jpy", "fee_jpy": "fees_jpy",
        "market_color": "nq_color", "regime": "nq_color", "strategy": "setup",
    }
    for src, dst in aliases.items():
        if src in out and out[dst].isna().all():
            out[dst] = out[src]
    out["ticker"] = out["ticker"].map(lambda x: _text(x, "").upper())
    out = out[out["ticker"] != ""].copy()
    out["side"] = out["side"].map(lambda x: "SHORT" if _text(x, "LONG").upper() in {"SHORT", "SELL", "S"} else "LONG")
    out["entry_date"] = pd.to_datetime(out["entry_date"], errors="coerce").dt.normalize()
    out["exit_date"] = pd.to_datetime(out["exit_date"], errors="coerce").dt.normalize()
    for col, default in (("entry_price", 0), ("exit_price", 0), ("quantity", 0), ("point_value", 1), ("fx_to_jpy", 1), ("fees_jpy", 0), ("taxes_jpy", 0), ("stop_price", np.nan), ("target_price", np.nan), ("mfe_pct", np.nan), ("mae_pct", np.nan)):
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(default) if not (isinstance(default, float) and math.isnan(default)) else pd.to_numeric(out[col], errors="coerce")
    direction = np.where(out["side"].eq("SHORT"), -1.0, 1.0)
    move = (out["exit_price"] - out["entry_price"]) * direction
    out["gross_pnl_jpy"] = move * out["quantity"] * out["point_value"] * out["fx_to_jpy"]
    supplied_net = pd.to_numeric(frame.get("net_pnl_jpy", pd.Series(index=frame.index, dtype=float)), errors="coerce")
    out["net_pnl_jpy"] = supplied_net.reindex(out.index).where(supplied_net.reindex(out.index).notna(), out["gross_pnl_jpy"] - out["fees_jpy"] - out["taxes_jpy"])
    invested = (out["entry_price"].abs() * out["quantity"] * out["point_value"] * out["fx_to_jpy"]).replace(0, np.nan)
    supplied_return = pd.to_numeric(frame.get("return_pct", pd.Series(index=frame.index, dtype=float)), errors="coerce")
    computed_return = out["net_pnl_jpy"] / invested
    out["return_pct"] = supplied_return.reindex(out.index).where(supplied_return.reindex(out.index).notna(), computed_return)
    stop_distance = (out["entry_price"] - out["stop_price"]).abs()
    out["planned_risk_jpy"] = stop_distance * out["quantity"] * out["point_value"] * out["fx_to_jpy"]
    supplied_risk = pd.to_numeric(frame.get("planned_risk_jpy", pd.Series(index=frame.index, dtype=float)), errors="coerce")
    out["planned_risk_jpy"] = supplied_risk.reindex(out.index).where(supplied_risk.reindex(out.index).notna(), out["planned_risk_jpy"])
    out["r_multiple"] = out["net_pnl_jpy"] / out["planned_risk_jpy"].replace(0, np.nan)
    supplied_r = pd.to_numeric(frame.get("r_multiple", pd.Series(index=frame.index, dtype=float)), errors="coerce")
    out["r_multiple"] = supplied_r.reindex(out.index).where(supplied_r.reindex(out.index).notna(), out["r_multiple"])
    out["hold_days"] = (out["exit_date"] - out["entry_date"]).dt.days.clip(lower=0)
    for column in ("setup", "sector", "industry", "theme", "entry_reason", "exit_reason", "mistake_type", "notes"):
        out[column] = out[column].map(lambda x: _text(x, "UNKNOWN"))
    out["nq_color"] = out["nq_color"].map(_normalise_color)
    out["rule_followed"] = out["rule_followed"].map(lambda x: True if pd.isna(x) or str(x).strip() == "" else _bool(x))
    if out["trade_id"].isna().all():
        out["trade_id"] = [f"T{i+1:05d}" for i in range(len(out))]
    else:
        out["trade_id"] = out["trade_id"].fillna(pd.Series([f"T{i+1:05d}" for i in range(len(out))], index=out.index)).astype(str)
    return out.sort_values(["exit_date", "entry_date", "ticker"], na_position="last").reset_index(drop=True)


def normalise_holdings(frame: pd.DataFrame, account_equity_jpy: float) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=(*HOLDING_COLUMNS, "market_value_jpy", "cost_basis_jpy", "unrealized_pnl_jpy", "unrealized_pct", "allocation", "planned_loss_jpy", "heat_fraction", "hold_days"))
    out = _ensure_columns(frame, HOLDING_COLUMNS)
    aliases = {"symbol": "ticker", "shares": "quantity", "price": "current_price", "avg_price": "entry_price", "market_color": "nq_color"}
    for src, dst in aliases.items():
        if src in out and out[dst].isna().all():
            out[dst] = out[src]
    out["ticker"] = out["ticker"].map(lambda x: _text(x, "").upper())
    out = out[out["ticker"] != ""].copy()
    for col, default in (("quantity", 0), ("entry_price", 0), ("current_price", 0), ("fx_to_jpy", 1), ("stop_price", np.nan)):
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(default) if not (isinstance(default, float) and math.isnan(default)) else pd.to_numeric(out[col], errors="coerce")
    supplied_mv = pd.to_numeric(frame.get("market_value_jpy", pd.Series(index=frame.index, dtype=float)), errors="coerce")
    computed_mv = out["quantity"] * out["current_price"] * out["fx_to_jpy"]
    out["market_value_jpy"] = supplied_mv.reindex(out.index).where(supplied_mv.reindex(out.index).notna(), computed_mv)
    out["cost_basis_jpy"] = out["quantity"] * out["entry_price"] * out["fx_to_jpy"]
    out["unrealized_pnl_jpy"] = out["market_value_jpy"] - out["cost_basis_jpy"]
    out["unrealized_pct"] = out["unrealized_pnl_jpy"] / out["cost_basis_jpy"].replace(0, np.nan)
    equity = max(float(account_equity_jpy or 0), 1.0)
    out["allocation"] = out["market_value_jpy"] / equity
    out["planned_loss_jpy"] = (out["current_price"] - out["stop_price"]).abs() * out["quantity"] * out["fx_to_jpy"]
    supplied_loss = pd.to_numeric(frame.get("planned_loss_jpy", pd.Series(index=frame.index, dtype=float)), errors="coerce")
    out["planned_loss_jpy"] = supplied_loss.reindex(out.index).where(supplied_loss.reindex(out.index).notna(), out["planned_loss_jpy"])
    out["heat_fraction"] = out["planned_loss_jpy"] / equity
    out["entry_date"] = pd.to_datetime(out["entry_date"], errors="coerce").dt.normalize()
    today = pd.Timestamp.now(tz="Asia/Tokyo").tz_localize(None).normalize()
    out["hold_days"] = (today - out["entry_date"]).dt.days.clip(lower=0)
    for column in ("sector", "industry", "theme", "setup"):
        out[column] = out[column].map(lambda x: _text(x, "UNKNOWN"))
    out["nq_color"] = out["nq_color"].map(_normalise_color)
    out["event_risk"] = out["event_risk"].map(_bool)
    return out.sort_values("market_value_jpy", ascending=False).reset_index(drop=True)


def build_equity_curve(equity_frame: pd.DataFrame, trades: pd.DataFrame, starting_equity_jpy: float) -> pd.DataFrame:
    if not equity_frame.empty:
        out = _ensure_columns(equity_frame, EQUITY_COLUMNS)
        out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.normalize()
        out["equity_jpy"] = pd.to_numeric(out["equity_jpy"], errors="coerce")
        out["cash_jpy"] = pd.to_numeric(out["cash_jpy"], errors="coerce")
        out["deposits_jpy"] = _num(out["deposits_jpy"])
        out["withdrawals_jpy"] = _num(out["withdrawals_jpy"])
        out = out.dropna(subset=["date", "equity_jpy"]).sort_values("date").drop_duplicates("date", keep="last")
    elif not trades.empty and trades["exit_date"].notna().any():
        daily = trades.dropna(subset=["exit_date"]).groupby("exit_date", as_index=False)["net_pnl_jpy"].sum().sort_values("exit_date")
        start = daily["exit_date"].min()
        end = max(daily["exit_date"].max(), pd.Timestamp.now().normalize())
        dates = pd.bdate_range(start, end)
        out = pd.DataFrame({"date": dates}).merge(daily.rename(columns={"exit_date": "date"}), on="date", how="left")
        out["net_pnl_jpy"] = out["net_pnl_jpy"].fillna(0)
        out["equity_jpy"] = float(starting_equity_jpy) + out["net_pnl_jpy"].cumsum()
        out["cash_jpy"] = np.nan
        out["deposits_jpy"] = 0.0
        out["withdrawals_jpy"] = 0.0
    else:
        today = pd.Timestamp.now().normalize()
        out = pd.DataFrame({"date": [today], "equity_jpy": [float(starting_equity_jpy)], "cash_jpy": [np.nan], "deposits_jpy": [0.0], "withdrawals_jpy": [0.0]})
    out["net_flow_jpy"] = out["deposits_jpy"].fillna(0) - out["withdrawals_jpy"].fillna(0)
    out["adjusted_equity_jpy"] = out["equity_jpy"] - out["net_flow_jpy"].cumsum()
    out["daily_return"] = out["adjusted_equity_jpy"].pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan).fillna(0)
    out["peak_jpy"] = out["adjusted_equity_jpy"].cummax()
    out["drawdown"] = out["adjusted_equity_jpy"] / out["peak_jpy"].replace(0, np.nan) - 1.0
    return out.reset_index(drop=True)


def monthly_return_table(equity: pd.DataFrame) -> pd.DataFrame:
    if equity.empty:
        return pd.DataFrame(columns=["year", *range(1, 13), "YTD"])
    monthly = equity.set_index("date")["adjusted_equity_jpy"].resample("ME").last().pct_change(fill_method=None)
    first_month = equity.set_index("date")["adjusted_equity_jpy"].resample("ME").last().iloc[0]
    first_equity = equity["adjusted_equity_jpy"].iloc[0]
    if first_equity:
        monthly.iloc[0] = first_month / first_equity - 1
    data = monthly.to_frame("return").reset_index()
    data["year"] = data["date"].dt.year
    data["month"] = data["date"].dt.month
    pivot = data.pivot(index="year", columns="month", values="return").reindex(columns=range(1, 13))
    yearly = equity.set_index("date")["adjusted_equity_jpy"].resample("YE").last().pct_change(fill_method=None)
    if len(yearly):
        yearly.iloc[0] = yearly.iloc[0] / first_equity - 1 if first_equity else np.nan
    pivot["YTD"] = yearly.to_numpy()[: len(pivot)] if len(yearly) >= len(pivot) else np.nan
    return pivot.reset_index()
