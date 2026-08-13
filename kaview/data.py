from __future__ import annotations

import math
import numpy as np
import pandas as pd

from .types import (
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
    for col, default in (
        ("entry_price", 0), ("exit_price", 0), ("quantity", 0), ("point_value", 1),
        ("fx_to_jpy", 1), ("fees_jpy", 0), ("taxes_jpy", 0), ("stop_price", np.nan),
        ("target_price", np.nan), ("mfe_pct", np.nan), ("mae_pct", np.nan),
        ("closed_quantity", np.nan), ("entry_tranches", 1), ("exit_tranches", 1),
    ):
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(default) if not (isinstance(default, float) and math.isnan(default)) else pd.to_numeric(out[col], errors="coerce")
    direction = np.where(out["side"].eq("SHORT"), -1.0, 1.0)
    move = (out["exit_price"] - out["entry_price"]) * direction
    computed_gross = move * out["quantity"] * out["point_value"] * out["fx_to_jpy"]
    supplied_gross = pd.to_numeric(
        frame.get("gross_pnl_jpy", pd.Series(index=frame.index, dtype=float)),
        errors="coerce",
    )
    out["gross_pnl_jpy"] = supplied_gross.reindex(out.index).where(
        supplied_gross.reindex(out.index).notna(),
        computed_gross,
    )
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
    for column in ("source", "position_id"):
        out[column] = out[column].map(lambda x: _text(x, ""))
    out["nq_color"] = out["nq_color"].map(_normalise_color)
    out["rule_followed"] = out["rule_followed"].map(lambda x: True if pd.isna(x) or str(x).strip() == "" else _bool(x))
    out["partial_exit"] = out["partial_exit"].map(_bool)
    if out["trade_id"].isna().all():
        out["trade_id"] = [f"T{i+1:05d}" for i in range(len(out))]
    else:
        out["trade_id"] = out["trade_id"].fillna(pd.Series([f"T{i+1:05d}" for i in range(len(out))], index=out.index)).astype(str)
    return out.sort_values(["exit_date", "entry_date", "ticker"], na_position="last").reset_index(drop=True)


def normalise_holdings(frame: pd.DataFrame, account_equity_jpy: float) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=(
            *HOLDING_COLUMNS, "market_value_jpy", "cost_basis_jpy", "unrealized_pnl_jpy",
            "unrealized_pct", "allocation", "planned_loss_jpy", "heat_fraction", "hold_days",
            "partial_take_due", "partial_target_price",
        ))
    out = _ensure_columns(frame, HOLDING_COLUMNS)
    aliases = {
        "symbol": "ticker", "shares": "quantity", "price": "current_price",
        "avg_price": "entry_price", "cost_basis": "entry_price", "market_color": "nq_color",
        "adr": "adr_pct", "average_daily_range_pct": "adr_pct", "trail_method": "stop_method",
        "stop_21ema_low": "stop_ema21_low", "ema21_low": "stop_ema21_low",
        "stop_10ma": "stop_sma10", "sma10": "stop_sma10",
        "first_entry_price": "entry_price_1", "second_entry_price": "entry_price_2",
        "first_shares": "shares_1", "second_shares": "shares_2",
        "partial_profit_done": "partial_taken", "partial_profit_taken": "partial_taken",
        "climax_status": "capitulation_status", "selloff_status": "capitulation_status",
        "撤退方法": "stop_method", "セリクラ": "capitulation_status",
    }
    for src, dst in aliases.items():
        if src in out and out[dst].isna().all():
            out[dst] = out[src]
    out["ticker"] = out["ticker"].map(lambda x: _text(x, "").upper())
    out = out[out["ticker"] != ""].copy()
    for col, default in (
        ("quantity", 0), ("entry_price", 0), ("current_price", 0), ("fx_to_jpy", 1),
        ("stop_price", np.nan), ("stop_ema21_low", np.nan), ("stop_sma10", np.nan),
        ("adr_pct", np.nan), ("entry_price_1", np.nan), ("entry_price_2", np.nan),
        ("shares_1", np.nan), ("shares_2", np.nan), ("entry_stage", np.nan),
        ("partial_target_pct", .25), ("partial_exit_fraction", .25),
    ):
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(default) if not (isinstance(default, float) and math.isnan(default)) else pd.to_numeric(out[col], errors="coerce")

    tranche_shares = out["shares_1"].fillna(0).clip(lower=0) + out["shares_2"].fillna(0).clip(lower=0)
    tranche_value = (
        out["entry_price_1"].fillna(0) * out["shares_1"].fillna(0).clip(lower=0)
        + out["entry_price_2"].fillna(0) * out["shares_2"].fillna(0).clip(lower=0)
    )
    tranche_entry = tranche_value / tranche_shares.replace(0, np.nan)
    out["quantity"] = out["quantity"].where(out["quantity"] > 0, tranche_shares)
    out["entry_price"] = out["entry_price"].where(out["entry_price"] > 0, tranche_entry)

    method_text = out["stop_method"].map(lambda value: _text(value, "21EMA_LOW").upper())
    out["stop_method"] = np.where(method_text.str.contains("10"), "10MA", "21EMA_LOW")
    selected_stop = out["stop_ema21_low"].where(out["stop_method"].eq("21EMA_LOW"), out["stop_sma10"])
    out["stop_price"] = selected_stop.where(selected_stop.notna() & selected_stop.gt(0), out["stop_price"])

    out["entry_stage"] = out["entry_stage"].where(out["entry_stage"].isin([1, 2]))
    has_first_tranche = out["entry_price_1"].gt(0) | out["shares_1"].fillna(0).gt(0)
    has_second_tranche = out["entry_price_2"].gt(0) | out["shares_2"].fillna(0).gt(0)
    inferred_stage = np.where(has_second_tranche, 2, np.where(has_first_tranche, 1, 2))
    out["entry_stage"] = out["entry_stage"].fillna(pd.Series(inferred_stage, index=out.index)).astype(int)
    out["partial_taken"] = out["partial_taken"].map(_bool)
    for column in ("partial_target_pct", "partial_exit_fraction"):
        out[column] = out[column].where(out[column].abs() <= 1, out[column] / 100.0).clip(lower=0, upper=1)

    def normalise_capitulation(value: object) -> str:
        text = _text(value, "NONE").strip().upper().replace(" ", "_")
        if text in {"WAIT", "WAITING", "PENDING", "待ち", "セリクラ待ち"}:
            return "WAITING"
        if text in {"DONE", "COMPLETED", "YES", "TRUE", "1", "済", "済み", "セリクラ済", "セリクラ済み"}:
            return "DONE"
        return "NONE"

    out["capitulation_status"] = out["capitulation_status"].map(normalise_capitulation)
    supplied_mv = pd.to_numeric(frame.get("market_value_jpy", pd.Series(index=frame.index, dtype=float)), errors="coerce")
    computed_mv = out["quantity"] * out["current_price"] * out["fx_to_jpy"]
    out["market_value_jpy"] = supplied_mv.reindex(out.index).where(supplied_mv.reindex(out.index).notna(), computed_mv)
    out["cost_basis_jpy"] = out["quantity"] * out["entry_price"] * out["fx_to_jpy"]
    out["unrealized_pnl_jpy"] = out["market_value_jpy"] - out["cost_basis_jpy"]
    out["unrealized_pct"] = out["unrealized_pnl_jpy"] / out["cost_basis_jpy"].replace(0, np.nan)
    out["partial_target_price"] = out["entry_price"] * (1.0 + out["partial_target_pct"])
    out["partial_take_due"] = out["unrealized_pct"].ge(out["partial_target_pct"]) & ~out["partial_taken"]
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
    event_text = out["event_risk"].map(lambda x: _text(x, ""))
    false_values = {"", "0", "false", "none", "nan", "unknown", "なし"}
    out["event_risk_label"] = event_text.where(
        ~event_text.str.strip().str.lower().isin(false_values),
        "",
    )
    out["event_risk"] = out["event_risk_label"].ne("")
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
        if out.empty:
            today = pd.Timestamp.now().normalize()
            out = pd.DataFrame(
                {
                    "date": [today],
                    "equity_jpy": [float(starting_equity_jpy)],
                    "cash_jpy": [np.nan],
                    "deposits_jpy": [0.0],
                    "withdrawals_jpy": [0.0],
                }
            )
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
    previous_equity = out["equity_jpy"].shift(1)
    out["daily_return"] = (
        (out["equity_jpy"] - out["net_flow_jpy"]) / previous_equity.replace(0, np.nan) - 1.0
    ).replace([np.inf, -np.inf], np.nan)
    out.loc[out.index[0], "daily_return"] = 0.0
    out["daily_return"] = out["daily_return"].fillna(0.0)
    first_equity = float(out["equity_jpy"].iloc[0])
    out["adjusted_equity_jpy"] = first_equity * (1.0 + out["daily_return"]).cumprod()
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
