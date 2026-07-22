from __future__ import annotations

import math
from typing import Any

import pandas as pd


MARKET_POLICY_VERSION = "1.0.1"


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _numeric_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(float("nan"), index=frame.index, dtype="float64", name=column)
    value: Any = frame.loc[:, column]
    if isinstance(value, pd.DataFrame):
        value = value.apply(pd.to_numeric, errors="coerce").bfill(axis=1).iloc[:, 0]
    elif not isinstance(value, pd.Series):
        value = pd.Series(value, index=frame.index, name=column)
    return pd.to_numeric(value, errors="coerce").reindex(frame.index)


def _comparison_ratio(left: pd.Series, right: pd.Series) -> float | None:
    valid = left.notna() & right.notna()
    return float((left[valid] > right[valid]).mean()) if valid.any() else None


def _threshold_ratio(series: pd.Series, threshold: float) -> float | None:
    valid = series.dropna()
    return float((valid >= threshold).mean()) if not valid.empty else None


def _index_state(frame: pd.DataFrame) -> dict[str, Any]:
    if frame is None or frame.empty:
        return {"available": False}
    f = frame.copy()
    f.columns = [str(c).lower().replace(" ", "_") for c in f.columns]
    close = _numeric_series(f, "close").dropna()
    if len(close) < 50:
        return {"available": False, "history_count": int(len(close))}
    latest = float(close.iloc[-1])
    sma10 = close.rolling(10).mean()
    sma20 = close.rolling(20).mean()
    sma50 = close.rolling(50).mean()
    sma200 = close.rolling(200).mean()
    return {
        "available": True,
        "price": latest,
        "above_sma10": bool(latest > sma10.iloc[-1]),
        "above_sma20": bool(latest > sma20.iloc[-1]),
        "above_sma50": bool(latest > sma50.iloc[-1]),
        "above_sma200": bool(len(close) >= 200 and latest > sma200.iloc[-1]),
        "sma20_rising": bool(len(sma20.dropna()) >= 6 and sma20.iloc[-1] > sma20.iloc[-6]),
        "sma50_rising": bool(len(sma50.dropna()) >= 21 and sma50.iloc[-1] > sma50.iloc[-21]),
        "return_5d": _finite(latest / close.iloc[-6] - 1) if len(close) > 5 else None,
        "return_21d": _finite(latest / close.iloc[-22] - 1) if len(close) > 21 else None,
        "distance_52w_high_pct": _finite((latest / close.tail(252).max() - 1) * 100),
    }


def build_market_state(frame: pd.DataFrame, qqq_frame: pd.DataFrame, sector_rotation: list[dict]) -> dict[str, Any]:
    """Build a transparent market regime from index trend and cross-sectional breadth."""
    qqq = _index_state(qqq_frame)
    work = frame.copy()
    price = _numeric_series(work, "price")
    sma10 = _numeric_series(work, "sma10")
    sma50 = _numeric_series(work, "sma50")
    sma200 = _numeric_series(work, "sma200")
    rs63 = _numeric_series(work, "rs_raw_63")
    rs126 = _numeric_series(work, "rs_raw_126")
    leaders = _numeric_series(work, "leader_rank_pct")

    breadth = {
        "above_sma10": _comparison_ratio(price, sma10),
        "above_sma50": _comparison_ratio(price, sma50),
        "above_sma200": _comparison_ratio(price, sma200),
        "positive_rs63": _threshold_ratio(rs63, 0.0),
        "positive_rs126": _threshold_ratio(rs126, 0.0),
        "leader_share_top20pct": _threshold_ratio(leaders, 80.0),
    }
    top_sector = sector_rotation[0] if sector_rotation else None
    top3 = sector_rotation[:3]
    sector_values: list[float] = []
    for item in top3:
        value = _finite(item.get("breadth_positive_63d"))
        if value is not None:
            sector_values.append(value)
    sector_breadth = sum(sector_values) / len(sector_values) if sector_values else None

    components = {
        "index_trend": sum(bool(qqq.get(k)) for k in ("above_sma20", "above_sma50", "above_sma200", "sma20_rising", "sma50_rising")) / 5 if qqq.get("available") else None,
        "short_breadth": breadth["above_sma10"],
        "medium_breadth": breadth["above_sma50"],
        "long_breadth": breadth["above_sma200"],
        "relative_strength_breadth": None if breadth["positive_rs63"] is None or breadth["positive_rs126"] is None else (breadth["positive_rs63"] * .6 + breadth["positive_rs126"] * .4),
        "sector_participation": sector_breadth,
    }
    weights = {"index_trend": .30, "short_breadth": .15, "medium_breadth": .20, "long_breadth": .10, "relative_strength_breadth": .15, "sector_participation": .10}
    available = [(name, value) for name, value in components.items() if value is not None]
    total_weight = sum(weights[name] for name, _ in available)
    score = sum(value * weights[name] for name, value in available) / total_weight if total_weight else None
    confidence = total_weight

    if score is None:
        regime, gate, exposure = "UNKNOWN", "NO_NEW", 0.0
    elif score >= .72:
        regime, gate, exposure = "BLUE", "ALLOW", 1.0
    elif score >= .55:
        regime, gate, exposure = "GREEN", "SELECTIVE", .75
    elif score >= .38:
        regime, gate, exposure = "YELLOW", "NO_NEW", .35
    else:
        regime, gate, exposure = "RED", "DEFENSIVE", 0.0

    warnings: list[str] = []
    if breadth["above_sma50"] is not None and breadth["above_sma50"] < .40:
        warnings.append("weak_medium_breadth")
    if breadth["above_sma10"] is not None and breadth["above_sma50"] is not None and breadth["above_sma10"] < breadth["above_sma50"] - .15:
        warnings.append("short_term_deterioration")
    if qqq.get("above_sma50") and breadth["above_sma50"] is not None and breadth["above_sma50"] < .45:
        warnings.append("index_breadth_divergence")
    if top_sector and float(top_sector.get("leader_share_top20pct") or 0) >= .50:
        warnings.append("leadership_concentration")

    return {
        "policy_version": MARKET_POLICY_VERSION,
        "regime": regime,
        "entry_gate": gate,
        "recommended_exposure": exposure,
        "recommended_exposure_pct": exposure * 100.0,
        "score_market": score,
        "score_confidence": confidence,
        "qqq": qqq,
        "breadth": breadth,
        "components": components,
        "top_sector": top_sector.get("sector") if top_sector else None,
        "warnings": warnings,
    }


def apply_market_gate(candidates: list[dict], market_state: dict[str, Any]) -> list[dict]:
    gate = str(market_state.get("entry_gate", "NO_NEW"))
    regime = str(market_state.get("regime", "UNKNOWN"))
    output: list[dict] = []
    for candidate in candidates:
        item = dict(candidate)
        item["market_regime"] = regime
        item["market_gate"] = gate
        item["actionable"] = gate in {"ALLOW", "SELECTIVE"}
        if gate == "SELECTIVE" and item.get("setup") not in {"PULLBACK", "PRE_BREAKOUT", "BREAKOUT"}:
            item["actionable"] = False
        warnings = list(item.get("warnings") or [])
        if not item["actionable"]:
            warnings.append("market_gate")
        item["warnings"] = sorted(set(warnings))
        output.append(item)
    return output
