from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

PORTFOLIO_POLICY_VERSION = "1.0.0"


def load_positions(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["ticker", "weight", "shares", "cost_basis", "entry_date", "stop_method"])
    frame = pd.read_csv(path)
    cols = {str(c).strip().lower(): c for c in frame.columns}
    aliases = {"ticker": ("ticker", "symbol", "ティッカー", "シンボル"), "weight": ("weight", "portfolio_weight", "比率", "ウェイト"), "shares": ("shares", "quantity", "数量", "株数"), "cost_basis": ("cost_basis", "entry_price", "取得単価", "建値"), "entry_date": ("entry_date", "start_date", "保有開始日"), "stop_method": ("stop_method", "trail", "撤退方法")}
    out = pd.DataFrame(index=frame.index)
    for target, names in aliases.items():
        source = next((cols[n.lower()] for n in names if n.lower() in cols), None)
        out[target] = frame[source] if source is not None else None
    out["ticker"] = out["ticker"].astype(str).str.upper().str.strip()
    out = out[out["ticker"].ne("") & out["ticker"].ne("NAN")].drop_duplicates("ticker")
    for col in ("weight", "shares", "cost_basis"):
        out[col] = pd.to_numeric(out[col], errors="coerce")
    if out["weight"].notna().sum() == 0:
        out["weight"] = 1.0 / len(out) if len(out) else np.nan
    else:
        total = out["weight"].fillna(0).sum()
        out["weight"] = out["weight"].fillna(0) / total if total > 0 else 0
    return out.reset_index(drop=True)


def _correlation_cluster(positions: pd.DataFrame, prices: dict[str, pd.DataFrame]) -> dict[str, Any]:
    series = {}
    for ticker in positions["ticker"]:
        frame = prices.get(ticker)
        if frame is None:
            continue
        close_col = next((c for c in frame.columns if str(c).lower().replace(" ", "_") in {"close", "adj_close", "adjclose"}), None)
        if close_col is None:
            continue
        close = pd.to_numeric(frame[close_col], errors="coerce").dropna().tail(64)
        if len(close) >= 30:
            series[ticker] = close.pct_change(fill_method=None)
    if len(series) < 2:
        return {"average_pairwise_correlation": None, "high_correlation_pairs": [], "coverage": len(series)}
    corr = pd.DataFrame(series).corr(min_periods=20)
    pairs, values = [], []
    names = list(corr.columns)
    for i, left in enumerate(names):
        for right in names[i + 1:]:
            value = corr.loc[left, right]
            if pd.notna(value):
                values.append(float(value))
                if value >= 0.75:
                    pairs.append({"left": left, "right": right, "correlation": round(float(value), 3)})
    pairs.sort(key=lambda x: (-x["correlation"], x["left"], x["right"]))
    return {"average_pairwise_correlation": round(float(np.mean(values)), 3) if values else None, "high_correlation_pairs": pairs[:10], "coverage": len(series)}


def build_portfolio_doctor(positions: pd.DataFrame, scored: pd.DataFrame, prices: dict[str, pd.DataFrame], market_state: dict[str, Any]) -> dict[str, Any]:
    if positions.empty:
        return {"status": "NO_POSITIONS", "position_count": 0, "positions": [], "warnings": ["portfolio_input_missing"], "input_contract": "portfolio.csv: ticker, weight|shares, cost_basis, entry_date, stop_method"}
    lookup = scored.set_index("ticker", drop=False)
    records = []
    for _, pos in positions.iterrows():
        ticker = str(pos["ticker"])
        row = lookup.loc[ticker] if ticker in lookup.index else pd.Series(dtype=object)
        price = pd.to_numeric(row.get("price"), errors="coerce")
        stop_method = str(pos.get("stop_method") or "21EMA_LOW").upper()
        stop = pd.to_numeric(row.get("stop_sma10") if "10" in stop_method else row.get("stop_ema21_low"), errors="coerce")
        stop_distance = float(price / stop - 1) * 100 if pd.notna(price) and pd.notna(stop) and stop else None
        weight = float(pos.get("weight") or 0)
        adr = pd.to_numeric(row.get("adr_pct"), errors="coerce")
        phase, setup, theme_phase = row.get("story_phase"), row.get("setup"), row.get("theme_phase")
        hard_block = bool(row.get("hard_block", False))
        if hard_block or (stop_distance is not None and stop_distance <= 0): action = "EXIT"
        elif stop_distance is not None and stop_distance <= 2.0: action = "REDUCE"
        elif phase in {"DETERIORATING", "MARGIN_PRESSURE", "DILUTING"} or theme_phase == "WEAKENING": action = "REDUCE"
        elif setup in {"PULLBACK", "PRE_BREAKOUT"} and market_state.get("entry_gate") in {"ALLOW", "SELECTIVE"} and row.get("story_confirmed"): action = "ADD"
        else: action = "HOLD"
        entry_date = pd.to_datetime(pos.get("entry_date"), errors="coerce")
        held_days = int((pd.Timestamp.utcnow().tz_localize(None).normalize() - entry_date.normalize()).days) if pd.notna(entry_date) else None
        records.append({"ticker": ticker, "weight": round(weight, 6), "price": None if pd.isna(price) else float(price), "cost_basis": None if pd.isna(pos.get("cost_basis")) else float(pos.get("cost_basis")), "held_days": held_days, "sector": row.get("sector"), "theme": row.get("theme"), "adr_pct": None if pd.isna(adr) else float(adr), "stop_method": stop_method, "stop": None if pd.isna(stop) else float(stop), "stop_distance_pct": None if stop_distance is None else round(stop_distance, 2), "risk_contribution_pct": round(weight * max(0.0, float(stop_distance or 0)), 3), "action": action, "setup": setup, "story_phase": phase, "theme_phase": theme_phase})
    weights = pd.Series({r["ticker"]: r["weight"] for r in records})
    sector_weights, theme_weights = {}, {}
    for r in records:
        sector_weights[str(r.get("sector") or "Unknown")] = sector_weights.get(str(r.get("sector") or "Unknown"), 0) + r["weight"]
        theme_weights[str(r.get("theme") or "Unknown")] = theme_weights.get(str(r.get("theme") or "Unknown"), 0) + r["weight"]
    avg_adr = sum(r["weight"] * (r["adr_pct"] or 0) for r in records)
    total_stop_risk = sum(r["risk_contribution_pct"] for r in records)
    hhi = float((weights ** 2).sum()) if len(weights) else 0
    correlation = _correlation_cluster(positions, prices)
    warnings = []
    if weights.max() > 0.20: warnings.append("single_position_concentration")
    if sector_weights and max(sector_weights.values()) > 0.40: warnings.append("sector_concentration")
    if theme_weights and max(theme_weights.values()) > 0.35: warnings.append("theme_concentration")
    if correlation.get("average_pairwise_correlation") is not None and correlation["average_pairwise_correlation"] >= 0.65: warnings.append("correlation_concentration")
    if total_stop_risk > 4.0: warnings.append("portfolio_stop_risk_high")
    return {"status": "OK", "position_count": len(records), "concentration_hhi": round(hhi, 4), "effective_position_count": round(1 / hhi, 2) if hhi > 0 else None, "largest_position_weight": round(float(weights.max()), 4), "sector_weights": dict(sorted(((k, round(v, 4)) for k, v in sector_weights.items()), key=lambda x: (-x[1], x[0]))), "theme_weights": dict(sorted(((k, round(v, 4)) for k, v in theme_weights.items()), key=lambda x: (-x[1], x[0]))), "portfolio_adr_pct": round(avg_adr, 2), "portfolio_stop_risk_pct": round(total_stop_risk, 2), "correlation": correlation, "action_counts": pd.Series([r["action"] for r in records]).value_counts().to_dict(), "positions": sorted(records, key=lambda r: ({"EXIT": 0, "REDUCE": 1, "ADD": 2, "HOLD": 3}[r["action"]], -r["weight"], r["ticker"])), "warnings": warnings}
