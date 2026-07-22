from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

PORTFOLIO_POLICY_VERSION = "2.1.0"
DEFAULT_POSITION_WEIGHT = 0.08
MAX_POSITIONS = 6
MARKET_EXPOSURE_CAP = {"BLUE": 1.00, "GREEN": 0.75, "YELLOW": 0.35, "RED": 0.00}


def _bool_series(series: pd.Series) -> pd.Series:
    return series.astype(str).str.lower().isin({"1", "true", "yes", "y", "済", "済み"})


def load_positions(path: Path) -> pd.DataFrame:
    cols = [
        "ticker", "weight", "shares", "cost_basis", "entry_date", "stop_method",
        "entry_stage", "first_pivot_date", "second_pivot_date", "partial_taken",
        "entry_price_1", "entry_price_2", "shares_1", "shares_2", "strategy",
    ]
    if not path.exists():
        return pd.DataFrame(columns=cols)
    frame = pd.read_csv(path)
    mapping = {str(column).strip().lower(): column for column in frame.columns}
    aliases = {
        "ticker": ("ticker", "symbol", "ティッカー", "シンボル"),
        "weight": ("weight", "portfolio_weight", "比率", "ウェイト"),
        "shares": ("shares", "quantity", "数量", "株数"),
        "cost_basis": ("cost_basis", "entry_price", "取得単価", "建値"),
        "entry_date": ("entry_date", "start_date", "保有開始日"),
        "stop_method": ("stop_method", "trail_method", "trail", "撤退方法"),
        "entry_stage": ("entry_stage", "stage", "エントリー段階"),
        "first_pivot_date": ("first_pivot_date", "1st_pivot_date"),
        "second_pivot_date": ("second_pivot_date", "2nd_pivot_date"),
        "partial_taken": ("partial_taken", "partial_profit_done", "partial_profit_taken", "部分利確済み"),
        "entry_price_1": ("entry_price_1", "first_entry_price", "1st_entry_price"),
        "entry_price_2": ("entry_price_2", "second_entry_price", "2nd_entry_price"),
        "shares_1": ("shares_1", "first_shares", "1st_shares"),
        "shares_2": ("shares_2", "second_shares", "2nd_shares"),
        "strategy": ("strategy", "strat", "戦略"),
    }
    out = pd.DataFrame(index=frame.index)
    for target, names in aliases.items():
        source = next((mapping[name.lower()] for name in names if name.lower() in mapping), None)
        out[target] = frame[source] if source is not None else None
    out["ticker"] = out["ticker"].astype(str).str.upper().str.strip()
    out = out[out.ticker.ne("") & out.ticker.ne("NAN")].drop_duplicates("ticker")
    for column in ("weight", "shares", "cost_basis", "entry_price_1", "entry_price_2", "shares_1", "shares_2"):
        out[column] = pd.to_numeric(out[column], errors="coerce")
    out["entry_stage"] = pd.to_numeric(out["entry_stage"], errors="coerce").fillna(2).clip(1, 2)
    out["partial_taken"] = _bool_series(out["partial_taken"])
    out["strategy"] = out["strategy"].fillna("swing").astype(str).str.lower()

    first_value = out["entry_price_1"] * out["shares_1"]
    second_value = out["entry_price_2"] * out["shares_2"]
    total_shares = out["shares_1"].fillna(0) + out["shares_2"].fillna(0)
    calculated_cost = (first_value.fillna(0) + second_value.fillna(0)) / total_shares.replace(0, np.nan)
    out["cost_basis"] = out["cost_basis"].fillna(calculated_cost)
    out["shares"] = out["shares"].fillna(total_shares.replace(0, np.nan))

    if out.weight.notna().sum() == 0:
        out["weight"] = DEFAULT_POSITION_WEIGHT
    else:
        total = float(out.weight.fillna(0).sum())
        if total > 1.000001:
            out["weight"] = out.weight.fillna(0) / total
        else:
            out["weight"] = out.weight.fillna(0)
    return out.reset_index(drop=True)


def _correlation_cluster(positions: pd.DataFrame, price_map: dict[str, pd.DataFrame]) -> dict[str, Any]:
    series: dict[str, pd.Series] = {}
    for ticker in positions.ticker:
        frame = price_map.get(ticker)
        if frame is None:
            continue
        column = next((item for item in frame.columns if str(item).lower().replace(" ", "_") in {"close", "adj_close", "adjclose"}), None)
        if column is not None:
            values = pd.to_numeric(frame[column], errors="coerce").dropna().tail(64)
            if len(values) >= 30:
                series[ticker] = values.pct_change(fill_method=None)
    if len(series) < 2:
        return {"average_pairwise_correlation": None, "high_correlation_pairs": [], "coverage": len(series)}
    corr = pd.DataFrame(series).corr(min_periods=20)
    pairs = []
    values = []
    names = list(corr.columns)
    for index, left in enumerate(names):
        for right in names[index + 1:]:
            value = corr.loc[left, right]
            if pd.notna(value):
                values.append(float(value))
                if value >= .75:
                    pairs.append({"left": left, "right": right, "correlation": round(float(value), 3)})
    return {
        "average_pairwise_correlation": round(float(np.mean(values)), 3) if values else None,
        "high_correlation_pairs": sorted(pairs, key=lambda item: -item["correlation"])[:10],
        "coverage": len(series),
    }


def _row_for_ticker(lookup: pd.DataFrame, ticker: str) -> pd.Series:
    if lookup.empty or ticker not in lookup.index:
        return pd.Series(dtype=object)
    row = lookup.loc[ticker]
    return row.iloc[0] if isinstance(row, pd.DataFrame) else row


def build_portfolio_doctor(
    positions: pd.DataFrame,
    scored: pd.DataFrame,
    prices: dict[str, pd.DataFrame],
    market_state: dict[str, Any],
) -> dict[str, Any]:
    if positions.empty:
        return {
            "status": "NO_POSITIONS",
            "policy_version": PORTFOLIO_POLICY_VERSION,
            "position_count": 0,
            "positions": [],
            "warnings": ["portfolio_input_missing"],
            "positions_copy": "",
        }
    lookup = scored.set_index("ticker", drop=False) if not scored.empty and "ticker" in scored else pd.DataFrame()
    records = []
    now = pd.Timestamp.utcnow().tz_localize(None).normalize()
    regime = str(market_state.get("regime") or "GREEN")
    exposure_cap = MARKET_EXPOSURE_CAP.get(regime, .5)
    gate = str(market_state.get("entry_gate") or "NO_NEW")

    for _, position in positions.iterrows():
        ticker = str(position.ticker)
        row = _row_for_ticker(lookup, ticker)
        price = pd.to_numeric(row.get("price"), errors="coerce")
        cost = pd.to_numeric(position.get("cost_basis"), errors="coerce")
        method = str(position.get("stop_method") or "21EMA_LOW").upper()
        raw_stop = row.get("stop_sma10") if "10" in method else row.get("stop_ema21_low")
        stop = pd.to_numeric(raw_stop, errors="coerce")
        gain = float(price / cost - 1) if pd.notna(price) and pd.notna(cost) and cost else None
        partial_due = bool(gain is not None and gain >= .25 and not bool(position.get("partial_taken")))
        if bool(position.get("partial_taken")) and pd.notna(cost):
            stop = max(float(stop) if pd.notna(stop) else 0.0, float(cost))
        stop_distance = float(price / stop - 1) * 100 if pd.notna(price) and pd.notna(stop) and stop else None
        entry_date = pd.to_datetime(position.get("entry_date"), errors="coerce")
        held = int((now - entry_date.normalize()).days) if pd.notna(entry_date) else None
        first_pivot = pd.to_datetime(position.get("first_pivot_date"), errors="coerce")
        second_pivot = pd.to_datetime(position.get("second_pivot_date"), errors="coerce")
        first_age = int((now - first_pivot.normalize()).days) if pd.notna(first_pivot) else held
        stage = int(position.get("entry_stage") or 2)
        action = "HOLD"
        reasons: list[str] = []

        if bool(row.get("hard_block", False)) or (stop_distance is not None and stop_distance <= 0):
            action = "EXIT"
            reasons.append("stop_or_hard_block")
        elif stage == 1 and first_age is not None and first_age >= 10 and pd.isna(second_pivot):
            action = "EXIT"
            reasons.append("second_pivot_missing_10d")
        elif stage == 1 and first_age is not None and first_age >= 5 and pd.isna(second_pivot):
            action = "REDUCE"
            reasons.append("second_pivot_late_5d")
        elif stage == 1 and first_age is not None and first_age >= 3 and pd.isna(second_pivot):
            reasons.append("second_pivot_watch_3d")
        if action == "HOLD" and stop_distance is not None and stop_distance <= 2:
            action = "REDUCE"
            reasons.append("stop_near")
        if action == "HOLD" and (
            row.get("story_phase") in {"DETERIORATING", "MARGIN_PRESSURE", "DILUTING"}
            or row.get("theme_phase") in {"WEAKENING", "BROKEN"}
        ):
            action = "REDUCE"
            reasons.append("fundamental_or_theme_weakness")
        if action == "HOLD" and stage == 1 and row.get("setup") in {"PULLBACK", "PRE_BREAKOUT"} and gate in {"ALLOW", "SELECTIVE"}:
            action = "ADD"
            reasons.append("second_half_candidate")
        if partial_due:
            reasons.append("take_25pct_partial")

        weight = float(position.get("weight") or DEFAULT_POSITION_WEIGHT)
        adr = pd.to_numeric(row.get("adr_pct"), errors="coerce")
        risk_contribution = weight * max(0.0, float(stop_distance or 0.0))
        records.append(
            {
                "ticker": ticker,
                "strategy": str(position.get("strategy") or "swing"),
                "weight": round(weight, 6),
                "target_full_weight": DEFAULT_POSITION_WEIGHT,
                "entry_stage": stage,
                "price": None if pd.isna(price) else float(price),
                "cost_basis": None if pd.isna(cost) else float(cost),
                "gain_pct": None if gain is None else round(gain * 100, 2),
                "held_days": held,
                "first_pivot_age_days": first_age,
                "sector": row.get("sector"),
                "theme": row.get("theme"),
                "adr_pct": None if pd.isna(adr) else float(adr),
                "stop_method": method,
                "stop": None if pd.isna(stop) else float(stop),
                "stop_distance_pct": None if stop_distance is None else round(stop_distance, 2),
                "risk_contribution_pct": round(risk_contribution, 3),
                "partial_take_due": partial_due,
                "partial_taken": bool(position.get("partial_taken")),
                "action": action,
                "reasons": reasons or ["trail_maintained"],
            }
        )

    weights = pd.Series({record["ticker"]: record["weight"] for record in records})
    sector_weights: dict[str, float] = {}
    theme_weights: dict[str, float] = {}
    for record in records:
        sector = str(record.get("sector") or "Unknown")
        theme = str(record.get("theme") or "Unknown")
        sector_weights[sector] = sector_weights.get(sector, 0.0) + record["weight"]
        theme_weights[theme] = theme_weights.get(theme, 0.0) + record["weight"]
    correlation = _correlation_cluster(positions, prices)
    total = float(weights.sum())
    warnings: list[str] = []
    if len(records) > MAX_POSITIONS:
        warnings.append("max_position_count_exceeded")
    if total > exposure_cap:
        warnings.append("market_exposure_cap_exceeded")
    if not weights.empty and weights.max() > DEFAULT_POSITION_WEIGHT * 1.25:
        warnings.extend(["single_position_above_rule", "single_position_concentration"])
    if sector_weights and max(sector_weights.values()) > .40:
        warnings.append("sector_concentration")
    if theme_weights and max(theme_weights.values()) > .24:
        warnings.append("theme_concentration")
    if correlation.get("average_pairwise_correlation") is not None and correlation["average_pairwise_correlation"] >= .65:
        warnings.append("correlation_concentration")
    hhi = float((weights ** 2).sum()) if len(weights) else 0.0
    sorted_records = sorted(records, key=lambda record: ({"EXIT": 0, "REDUCE": 1, "ADD": 2, "HOLD": 3}[record["action"]], -record["weight"]))
    action_counts = {action: sum(record["action"] == action for record in records) for action in ("EXIT", "REDUCE", "ADD", "HOLD")}
    return {
        "status": "OK",
        "policy_version": PORTFOLIO_POLICY_VERSION,
        "position_count": len(records),
        "max_positions": MAX_POSITIONS,
        "gross_exposure": round(total, 4),
        "market_exposure_cap": exposure_cap,
        "exposure_headroom": round(exposure_cap - total, 4),
        "concentration_hhi": round(hhi, 4),
        "effective_position_count": round(1 / hhi, 2) if hhi else None,
        "portfolio_adr_pct": round(sum(record["weight"] * (record["adr_pct"] or 0) for record in records), 2),
        "portfolio_stop_risk_pct": round(sum(record["risk_contribution_pct"] for record in records), 2),
        "sector_weights": sector_weights,
        "theme_weights": theme_weights,
        "correlation": correlation,
        "action_counts": action_counts,
        "positions_copy": " ".join(record["ticker"] for record in sorted_records),
        "positions": sorted_records,
        "warnings": sorted(set(warnings)),
    }
