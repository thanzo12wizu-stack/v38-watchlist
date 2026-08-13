from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


EXECUTION_COLUMNS = (
    "execution_id",
    "position_id",
    "ticker",
    "side",
    "action",
    "executed_at",
    "price",
    "quantity",
    "point_value",
    "fx_to_jpy",
    "fees_jpy",
    "taxes_jpy",
    "stop_price",
    "target_price",
    "setup",
    "nq_color",
    "sector",
    "industry",
    "theme",
    "entry_reason",
    "exit_reason",
    "rule_followed",
    "mistake_type",
    "notes",
)

CASH_FLOW_COLUMNS = ("flow_id", "date", "type", "amount_jpy", "notes")

_TABLE_KEYS: dict[str, tuple[str, ...]] = {
    "trades.csv": ("trade_id",),
    "executions.csv": ("execution_id",),
    "equity.csv": ("date",),
    "holdings.csv": ("ticker",),
    "cash_flows.csv": ("flow_id",),
}

_ENTRY_ACTIONS = {
    "LONG": {"BUY", "BTO", "BUY_TO_OPEN"},
    "SHORT": {"SELL", "SHORT", "SELL_SHORT", "STO", "SELL_TO_OPEN"},
}
_EXIT_ACTIONS = {
    "LONG": {"SELL", "STC", "SELL_TO_CLOSE"},
    "SHORT": {"BUY", "COVER", "BTC", "BUY_TO_COVER"},
}


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def _normalise_account_history(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    out = frame.copy()
    aliases = {
        "日時": "date",
        "日付": "date",
        "equity": "equity_jpy",
        "balance": "equity_jpy",
        "net_liquidation": "equity_jpy",
        "総資産": "equity_jpy",
        "資産": "equity_jpy",
        "cash": "cash_jpy",
        "現金": "cash_jpy",
        "deposits": "deposits_jpy",
        "入金": "deposits_jpy",
        "withdrawals": "withdrawals_jpy",
        "出金": "withdrawals_jpy",
    }
    for source, target in aliases.items():
        if source in out and target not in out:
            out[target] = out[source]
    if "date" not in out or "equity_jpy" not in out:
        return pd.DataFrame()
    out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.normalize()
    out["equity_jpy"] = pd.to_numeric(out["equity_jpy"], errors="coerce")
    out = out.dropna(subset=["date", "equity_jpy"])
    out = out[out["equity_jpy"] > 0]
    if out.empty:
        return pd.DataFrame()
    columns = ["date", "equity_jpy"]
    for column in ("cash_jpy", "deposits_jpy", "withdrawals_jpy"):
        if column in out:
            out[column] = pd.to_numeric(out[column], errors="coerce")
            columns.append(column)
    out = out[columns].copy()
    out["date"] = out["date"].dt.date.astype(str)
    out["equity_source"] = "COMMAND_CENTER_HISTORY"
    return out.sort_values("date", kind="stable").drop_duplicates("date", keep="last").reset_index(drop=True)


def _read_account_history(path: Path | None) -> pd.DataFrame:
    """Read conventional CSV and the repository's legacy mixed whitespace."""
    if path is None or not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    candidates: list[pd.DataFrame] = []
    for kwargs in ({}, {"sep": r"\s+", "engine": "python"}):
        try:
            candidates.append(_normalise_account_history(pd.read_csv(path, **kwargs)))
        except (OSError, pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeDecodeError):
            continue
    if not candidates:
        return pd.DataFrame()
    return max(candidates, key=len)


def _stable_id(prefix: str, values: Iterable[Any]) -> str:
    body = "\x1f".join("" if pd.isna(value) else str(value).strip() for value in values)
    return f"{prefix}-{hashlib.sha256(body.encode('utf-8')).hexdigest()[:20]}"


def _merge_table(
    existing: pd.DataFrame,
    incoming: pd.DataFrame,
    *,
    keys: tuple[str, ...],
    id_prefix: str,
) -> pd.DataFrame:
    if existing.empty and incoming.empty:
        return pd.DataFrame()
    frames = [frame.copy() for frame in (existing, incoming) if not frame.empty]
    merged = pd.concat(frames, ignore_index=True, sort=False)
    for key in keys:
        if key not in merged:
            merged[key] = np.nan
        if key == "date":
            parsed = pd.to_datetime(merged[key], errors="coerce")
            merged[key] = parsed.dt.date.astype("string")
        elif key == "ticker":
            merged[key] = merged[key].fillna("").astype(str).str.strip().str.upper()

    if len(keys) == 1:
        key = keys[0]
        missing = merged[key].isna() | merged[key].astype(str).str.strip().eq("")
        if missing.any() and key in {"date", "ticker"}:
            raise ValueError(f"{id_prefix} input contains {int(missing.sum())} row(s) without required {key}")
        if missing.any() and key.endswith("_id"):
            identity_columns = [
                column
                for column in (
                    "position_id",
                    "ticker",
                    "executed_at",
                    "date",
                    "action",
                    "price",
                    "quantity",
                    "entry_date",
                    "exit_date",
                    "amount_jpy",
                    "type",
                )
                if column in merged
            ]
            for index in merged.index[missing]:
                merged.at[index, key] = _stable_id(
                    id_prefix,
                    (merged.at[index, column] for column in identity_columns),
                )

    merged["_merge_key"] = merged[list(keys)].astype(str).agg("\x1f".join, axis=1)
    merged = merged.drop_duplicates("_merge_key", keep="last").drop(columns="_merge_key")
    sort_columns = [
        column
        for column in ("date", "executed_at", "entry_date", "exit_date", *keys)
        if column in merged
    ]
    if sort_columns:
        merged = merged.sort_values(sort_columns, kind="stable", na_position="last")
    return merged.reset_index(drop=True)


def _text(row: pd.Series, column: str, default: str = "") -> str:
    value = row.get(column)
    if value is None or pd.isna(value):
        return default
    text = str(value).strip()
    return text if text else default


def _number(row: pd.Series, column: str, default: float = 0.0) -> float:
    value = pd.to_numeric(pd.Series([row.get(column)]), errors="coerce").iloc[0]
    return float(value) if pd.notna(value) and math.isfinite(float(value)) else default


def _first_text(frame: pd.DataFrame, column: str, default: str = "UNKNOWN") -> str:
    if column not in frame:
        return default
    for value in frame[column]:
        if value is not None and not pd.isna(value):
            text = str(value).strip()
            if text:
                return text
    return default


def _last_text(frame: pd.DataFrame, column: str, default: str = "UNKNOWN") -> str:
    if column not in frame:
        return default
    for value in reversed(frame[column].tolist()):
        if value is not None and not pd.isna(value):
            text = str(value).strip()
            if text:
                return text
    return default


def _normalise_executions(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=EXECUTION_COLUMNS)
    out = frame.copy()
    aliases = {
        "id": "execution_id",
        "fill_id": "execution_id",
        "order_id": "execution_id",
        "trade_id": "position_id",
        "campaign_id": "position_id",
        "symbol": "ticker",
        "datetime": "executed_at",
        "timestamp": "executed_at",
        "date": "executed_at",
        "qty": "quantity",
        "shares": "quantity",
        "fill_price": "price",
        "commission_jpy": "fees_jpy",
        "fee_jpy": "fees_jpy",
    }
    for source, target in aliases.items():
        if source in out and (target not in out or out[target].isna().all()):
            out[target] = out[source]
    for column in EXECUTION_COLUMNS:
        if column not in out:
            out[column] = np.nan

    out["ticker"] = out["ticker"].fillna("").astype(str).str.strip().str.upper()
    out["position_id"] = out["position_id"].fillna("").astype(str).str.strip()
    out["action"] = (
        out["action"]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.upper()
        .str.replace(" ", "_", regex=False)
        .str.replace("-", "_", regex=False)
    )
    out["side"] = out["side"].fillna("").astype(str).str.strip().str.upper()
    out["side"] = out["side"].replace({"BUY": "LONG", "SELL": "SHORT", "S": "SHORT", "L": "LONG"})
    out["executed_at"] = pd.to_datetime(out["executed_at"], errors="coerce")
    for column, default in (
        ("price", np.nan),
        ("quantity", np.nan),
        ("point_value", np.nan),
        ("fx_to_jpy", np.nan),
        ("fees_jpy", 0.0),
        ("taxes_jpy", 0.0),
        ("stop_price", np.nan),
        ("target_price", np.nan),
    ):
        values = pd.to_numeric(out[column], errors="coerce")
        out[column] = values.fillna(default) if math.isfinite(default) else values

    for position_id, indexes in out.groupby("position_id", sort=False).groups.items():
        if not position_id:
            continue
        group = out.loc[indexes]
        explicit = set(group.loc[group["side"].ne(""), "side"])
        if len(explicit) == 1:
            inferred = next(iter(explicit))
        elif len(explicit) > 1:
            continue
        else:
            actions = group.sort_values(["executed_at", "execution_id"], kind="stable")["action"].tolist()
            long_signals = {"BTO", "BUY_TO_OPEN", "STC", "SELL_TO_CLOSE"}
            short_signals = {"SHORT", "SELL_SHORT", "STO", "SELL_TO_OPEN", "COVER", "BTC", "BUY_TO_COVER"}
            if any(action in long_signals for action in actions):
                inferred = "LONG"
            elif any(action in short_signals for action in actions):
                inferred = "SHORT"
            elif actions and actions[0] == "BUY":
                inferred = "LONG"
            elif actions and actions[0] == "SELL":
                inferred = "SHORT"
            else:
                continue
        out.loc[indexes, "side"] = out.loc[indexes, "side"].where(
            out.loc[indexes, "side"].ne(""),
            inferred,
        )
    return out


def executions_to_trades(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Aggregate multi-fill campaigns into one completed trade per position_id.

    Entry and exit tranches, including partial exits, are matched FIFO. Open
    campaigns remain in the execution ledger and are deliberately excluded from
    closed-trade KPIs until the remaining quantity is closed.
    """
    executions = _normalise_executions(frame)
    if executions.empty:
        return pd.DataFrame(), {
            "execution_rows": 0,
            "closed_positions": 0,
            "open_positions": 0,
            "partial_exit_positions": 0,
            "open_partial_exit_positions": 0,
            "invalid_rows": 0,
        }

    invalid = (
        executions["position_id"].eq("")
        | executions["ticker"].eq("")
        | executions["executed_at"].isna()
        | executions["price"].le(0)
        | executions["quantity"].le(0)
        | (executions["point_value"].notna() & executions["point_value"].le(0))
        | (executions["fx_to_jpy"].notna() & executions["fx_to_jpy"].le(0))
        | ~executions["side"].isin({"LONG", "SHORT"})
    )
    if invalid.any():
        sample = executions.loc[
            invalid,
            ["execution_id", "position_id", "ticker", "side", "action", "executed_at", "price", "quantity"],
        ].head(5)
        raise ValueError(
            "invalid execution rows; position_id, ticker, side, executed_at, positive price/quantity "
            "and positive point_value/fx_to_jpy when supplied are required: "
            + sample.to_json(orient="records", force_ascii=False, date_format="iso")
        )

    rows: list[dict[str, Any]] = []
    open_positions = 0
    partial_positions = 0
    open_partial_positions = 0
    for position_id, group in executions.groupby("position_id", sort=True):
        group = group.sort_values(["executed_at", "execution_id"], kind="stable")
        sides = set(group["side"])
        tickers = set(group["ticker"])
        if len(sides) != 1 or len(tickers) != 1:
            raise ValueError(f"position_id {position_id!r} mixes tickers or sides")
        side = next(iter(sides))
        direction = 1.0 if side == "LONG" else -1.0
        entry_actions = _ENTRY_ACTIONS[side]
        exit_actions = _EXIT_ACTIONS[side]
        lots: list[dict[str, float]] = []
        entry_rows: list[pd.Series] = []
        exit_rows: list[pd.Series] = []
        gross_pnl_jpy = 0.0
        matched_quantity = 0.0

        for _, execution in group.iterrows():
            action = _text(execution, "action").upper()
            quantity = _number(execution, "quantity")
            if action in entry_actions:
                lots.append(
                    {
                        "quantity": quantity,
                        "price": _number(execution, "price"),
                        "fx_to_jpy": _number(execution, "fx_to_jpy", 1.0),
                        "point_value": _number(execution, "point_value", 1.0),
                    }
                )
                entry_rows.append(execution)
                continue
            if action not in exit_actions:
                raise ValueError(
                    f"unsupported action {action!r} for {side} position {position_id!r}"
                )
            exit_rows.append(execution)
            remaining = quantity
            while remaining > 1e-9:
                if not lots:
                    raise ValueError(f"exit quantity exceeds entries for position {position_id!r}")
                lot = lots[0]
                matched = min(remaining, lot["quantity"])
                exit_fx = _number(execution, "fx_to_jpy", lot["fx_to_jpy"])
                point_value = _number(execution, "point_value", lot["point_value"])
                gross_pnl_jpy += (
                    direction
                    * (_number(execution, "price") - lot["price"])
                    * matched
                    * point_value
                    * exit_fx
                )
                matched_quantity += matched
                remaining -= matched
                lot["quantity"] -= matched
                if lot["quantity"] <= 1e-9:
                    lots.pop(0)

        if not entry_rows:
            raise ValueError(f"position {position_id!r} has no entry execution")
        if lots:
            open_positions += 1
            if exit_rows:
                partial_positions += 1
                open_partial_positions += 1
            continue
        if not exit_rows or matched_quantity <= 0:
            open_positions += 1
            continue

        entries = pd.DataFrame(entry_rows)
        exits = pd.DataFrame(exit_rows)
        if len(exits) > 1:
            partial_positions += 1
        exit_quantity = pd.to_numeric(exits["quantity"], errors="coerce").sum()
        entry_quantities = pd.to_numeric(entries["quantity"], errors="coerce")
        entry_prices = pd.to_numeric(entries["price"], errors="coerce")
        entry_fx_values = pd.to_numeric(entries["fx_to_jpy"], errors="coerce").fillna(1.0)
        entry_point_values = pd.to_numeric(entries["point_value"], errors="coerce").fillna(1.0)
        entry_price = float(
            np.average(
                entry_prices,
                weights=entry_quantities,
            )
        )
        exit_price = float(
            np.average(
                pd.to_numeric(exits["price"], errors="coerce"),
                weights=pd.to_numeric(exits["quantity"], errors="coerce"),
            )
        )
        entry_fx = float(
            np.average(
                entry_fx_values,
                weights=entry_quantities,
            )
        )
        point_value = float(
            np.average(
                entry_point_values,
                weights=entry_quantities,
            )
        )
        fees = float(pd.to_numeric(group["fees_jpy"], errors="coerce").fillna(0).sum())
        taxes = float(pd.to_numeric(group["taxes_jpy"], errors="coerce").fillna(0).sum())
        net_pnl = gross_pnl_jpy - fees - taxes
        invested = float(
            (entry_prices.abs() * entry_quantities * entry_point_values * entry_fx_values).sum()
        )
        stop_values = pd.to_numeric(entries["stop_price"], errors="coerce").dropna()
        stop_price = float(stop_values.iloc[0]) if len(stop_values) else np.nan
        if math.isfinite(stop_price):
            row_stops = pd.to_numeric(entries["stop_price"], errors="coerce").fillna(stop_price)
            planned_risk = float(
                (
                    (entry_prices - row_stops).abs()
                    * entry_quantities
                    * entry_point_values
                    * entry_fx_values
                ).sum()
            )
        else:
            planned_risk = np.nan
        target_values = pd.to_numeric(entries["target_price"], errors="coerce").dropna()
        target_price = float(target_values.iloc[0]) if len(target_values) else np.nan
        rows.append(
            {
                "trade_id": f"EXEC-{position_id}",
                "position_id": position_id,
                "source": "EXECUTIONS",
                "ticker": next(iter(tickers)),
                "side": side,
                "entry_date": pd.Timestamp(entries["executed_at"].min()).normalize(),
                "exit_date": pd.Timestamp(exits["executed_at"].max()).normalize(),
                "entry_price": entry_price,
                "exit_price": exit_price,
                "quantity": matched_quantity,
                "closed_quantity": exit_quantity,
                "point_value": point_value,
                "fx_to_jpy": entry_fx,
                "fees_jpy": fees,
                "taxes_jpy": taxes,
                "gross_pnl_jpy": gross_pnl_jpy,
                "net_pnl_jpy": net_pnl,
                "return_pct": net_pnl / invested if invested else np.nan,
                "stop_price": stop_price,
                "target_price": target_price,
                "planned_risk_jpy": planned_risk,
                "r_multiple": net_pnl / planned_risk if planned_risk and planned_risk > 0 else np.nan,
                "entry_tranches": len(entries),
                "exit_tranches": len(exits),
                "partial_exit": len(exits) > 1,
                "setup": _first_text(entries, "setup"),
                "nq_color": _first_text(entries, "nq_color"),
                "sector": _first_text(entries, "sector"),
                "industry": _first_text(entries, "industry"),
                "theme": _first_text(entries, "theme"),
                "entry_reason": _first_text(entries, "entry_reason"),
                "exit_reason": _last_text(exits, "exit_reason"),
                "rule_followed": _first_text(entries, "rule_followed", "true"),
                "mistake_type": _first_text(entries, "mistake_type", ""),
                "notes": _last_text(group, "notes", ""),
            }
        )

    trades = pd.DataFrame(rows)
    report = {
        "execution_rows": int(len(executions)),
        "closed_positions": int(len(trades)),
        "open_positions": int(open_positions),
        "partial_exit_positions": int(partial_positions),
        "open_partial_exit_positions": int(open_partial_positions),
        "invalid_rows": 0,
    }
    return trades, report


def _apply_cash_flows(
    equity: pd.DataFrame,
    cash_flows: pd.DataFrame,
) -> tuple[pd.DataFrame, list[str]]:
    if cash_flows.empty:
        return equity, []
    flows = cash_flows.copy()
    for column in CASH_FLOW_COLUMNS:
        if column not in flows:
            flows[column] = np.nan
    flows["date"] = pd.to_datetime(flows["date"], errors="coerce").dt.normalize()
    flows["type"] = flows["type"].fillna("").astype(str).str.strip().str.upper()
    flows["amount_jpy"] = pd.to_numeric(flows["amount_jpy"], errors="coerce")
    invalid = flows["date"].isna() | flows["amount_jpy"].isna() | flows["amount_jpy"].lt(0)
    if invalid.any():
        raise ValueError("cash_flows.csv contains invalid date or negative/non-numeric amount_jpy")
    unknown = ~flows["type"].isin({"DEPOSIT", "WITHDRAWAL", "入金", "出金"})
    if unknown.any():
        raise ValueError(f"cash_flows.csv contains unsupported types: {sorted(set(flows.loc[unknown, 'type']))}")

    if equity.empty:
        return equity, ["Cash flows were retained but no equity snapshots exist; returns cannot be flow-adjusted yet."]
    out = equity.copy()
    if "date" not in out:
        return out, ["Cash flows were retained but equity.csv has no date column."]
    out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.normalize()
    for column in ("deposits_jpy", "withdrawals_jpy"):
        if column not in out:
            out[column] = 0.0
        out[column] = pd.to_numeric(out[column], errors="coerce").fillna(0.0)

    grouped = flows.assign(
        deposits_jpy=np.where(flows["type"].isin({"DEPOSIT", "入金"}), flows["amount_jpy"], 0.0),
        withdrawals_jpy=np.where(flows["type"].isin({"WITHDRAWAL", "出金"}), flows["amount_jpy"], 0.0),
    ).groupby("date", as_index=False)[["deposits_jpy", "withdrawals_jpy"]].sum()
    equity_dates = pd.DatetimeIndex(sorted(out["date"].dropna().unique()))
    assigned_rows: list[dict[str, Any]] = []
    shifted_dates: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    pending_dates: list[pd.Timestamp] = []
    for _, flow in grouped.iterrows():
        position = int(equity_dates.searchsorted(flow["date"], side="left"))
        if position >= len(equity_dates):
            pending_dates.append(pd.Timestamp(flow["date"]))
            continue
        applied_date = pd.Timestamp(equity_dates[position])
        if applied_date != flow["date"]:
            shifted_dates.append((pd.Timestamp(flow["date"]), applied_date))
        assigned_rows.append(
            {
                "date": applied_date,
                "deposits_jpy": flow["deposits_jpy"],
                "withdrawals_jpy": flow["withdrawals_jpy"],
            }
        )
    overlay = (
        pd.DataFrame(assigned_rows)
        .groupby("date", as_index=False)[["deposits_jpy", "withdrawals_jpy"]]
        .sum()
        if assigned_rows
        else pd.DataFrame(columns=["date", "deposits_jpy", "withdrawals_jpy"])
    )
    warnings: list[str] = []
    if shifted_dates:
        warnings.append(
            "Cash flows applied to the next equity snapshot: "
            + ", ".join(
                f"{source.date().isoformat()}->{target.date().isoformat()}"
                for source, target in shifted_dates[:10]
            )
        )
    if pending_dates:
        warnings.append(
            "Cash flows pending a later equity snapshot: "
            + ", ".join(value.date().isoformat() for value in pending_dates[:10])
        )
    if not overlay.empty:
        out = out.merge(overlay, on="date", how="left", suffixes=("", "_flow"))
        out["deposits_jpy"] = out["deposits_jpy_flow"].where(
            out["deposits_jpy_flow"].notna(),
            out["deposits_jpy"],
        )
        out["withdrawals_jpy"] = out["withdrawals_jpy_flow"].where(
            out["withdrawals_jpy_flow"].notna(),
            out["withdrawals_jpy"],
        )
        out = out.drop(columns=["deposits_jpy_flow", "withdrawals_jpy_flow"])
    out["date"] = out["date"].dt.date.astype(str)
    return out, warnings


def ingest_bundle(
    import_dir: Path,
    state_dir: Path,
    account_history_path: Path | None = None,
) -> dict[str, Any]:
    state_dir.mkdir(parents=True, exist_ok=True)
    imported: dict[str, int] = {}
    totals: dict[str, int] = {}
    warnings: list[str] = []

    account_history = _read_account_history(account_history_path)
    if not account_history.empty:
        equity_path = state_dir / "equity.csv"
        existing = _read_csv(equity_path)
        if "equity_source" in existing:
            existing = existing[
                existing["equity_source"].fillna("").astype(str).ne("COMMAND_CENTER_HISTORY")
            ]
        merged = _merge_table(
            account_history,
            existing,
            keys=("date",),
            id_prefix="EQUITY",
        )
        merged.to_csv(equity_path, index=False)
        imported["account_history"] = int(len(account_history))
        totals["equity.csv"] = int(len(merged))

    for filename, keys in _TABLE_KEYS.items():
        source = import_dir / filename
        current = state_dir / filename
        incoming = _read_csv(source)
        existing = _read_csv(current)
        if incoming.empty and existing.empty:
            continue
        if filename == "equity.csv" and not incoming.empty and "equity_source" not in incoming:
            incoming["equity_source"] = "PRIVATE_IMPORT"
        merged = _merge_table(
            existing,
            incoming,
            keys=keys,
            id_prefix=filename.removesuffix(".csv").upper(),
        )
        merged.to_csv(current, index=False)
        imported[filename] = int(len(incoming))
        totals[filename] = int(len(merged))

    executions = _read_csv(state_dir / "executions.csv")
    generated, execution_report = executions_to_trades(executions)
    trades_path = state_dir / "trades.csv"
    manual = _read_csv(trades_path)
    if not generated.empty:
        if "source" in manual:
            manual = manual[manual["source"].fillna("").astype(str).str.upper() != "EXECUTIONS"]
        combined = _merge_table(
            manual,
            generated,
            keys=("trade_id",),
            id_prefix="TRADE",
        )
        combined.to_csv(trades_path, index=False)
        totals["trades.csv"] = int(len(combined))

    flows = _read_csv(state_dir / "cash_flows.csv")
    equity_path = state_dir / "equity.csv"
    equity, flow_warnings = _apply_cash_flows(_read_csv(equity_path), flows)
    warnings.extend(flow_warnings)
    if not equity.empty:
        equity.to_csv(equity_path, index=False)
        totals["equity.csv"] = int(len(equity))

    status = "IMPORTED" if any(imported.values()) else "NO_NEW_INPUT"
    report = {
        "schema_version": "1.0",
        "status": status,
        "import_dir": str(import_dir),
        "state_dir": str(state_dir),
        "imported_rows": imported,
        "state_rows": totals,
        "executions": execution_report,
        "warnings": warnings,
    }
    (state_dir / "ingestion_status.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge idempotent broker/CSV inputs into Trade Journal state")
    parser.add_argument("--import-dir", type=Path, default=Path("/tmp/trade-journal-import"))
    parser.add_argument("--state-dir", type=Path, default=Path("kaview/data"))
    parser.add_argument(
        "--account-history",
        type=Path,
        help="Optional repository equity history; private equity imports take precedence",
    )
    args = parser.parse_args()
    result = ingest_bundle(args.import_dir, args.state_dir, args.account_history)
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
