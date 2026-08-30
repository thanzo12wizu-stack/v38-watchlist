"""Truthful Sector / Theme Rotation Intelligence for the audited V38 companion.

This module deliberately separates:
- price / relative-strength observations,
- internal participation,
- exact ETF fund flow,
- divergence classification,
- V38 trading actions.

It must never treat trading volume as ETF creation/redemption fund flow.  When
exact flow, A/D, OBV, or 21EMA participation are not available, the output is
explicitly marked partial / DATA_REQUIRED rather than promoted to a complete
rotation signal.
"""

from __future__ import annotations

from statistics import median
from typing import Any, Mapping, Optional

MIN_GROUP_MEMBERS = 3


def _num(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    if x != x or x in (float("inf"), float("-inf")):
        return None
    return x


def _med(values: list[float]) -> Optional[float]:
    return float(median(values)) if values else None


def _mean(values: list[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


def _clip(value: float) -> float:
    return max(0.0, min(100.0, float(value)))


def _percent_above(rows: list[Mapping[str, Any]], keys: tuple[str, ...]) -> Optional[float]:
    values: list[float] = []
    for row in rows:
        value = None
        for key in keys:
            value = _num(row.get(key))
            if value is not None:
                break
        if value is not None:
            values.append(value)
    if not values:
        return None
    return 100.0 * sum(value > 0 for value in values) / len(values)


def _median_field(rows: list[Mapping[str, Any]], *keys: str) -> Optional[float]:
    values: list[float] = []
    for row in rows:
        for key in keys:
            value = _num(row.get(key))
            if value is not None:
                values.append(value)
                break
    return _med(values)


def _flow_snapshot(flow: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    flow = flow or {}
    one = _num(flow.get("flow_1d"))
    five = _num(flow.get("flow_5d"))
    twenty = _num(flow.get("flow_20d"))
    aum = _num(flow.get("aum"))
    exact = bool(flow.get("exact")) and twenty is not None
    return {
        "status": "EXACT" if exact else "DATA_REQUIRED",
        "source": flow.get("source") if exact else None,
        "flow_1d": one if exact else None,
        "flow_5d": five if exact else None,
        "flow_20d": twenty if exact else None,
        "aum": aum if exact else None,
        "flow_20d_pct_aum": ((twenty / aum) * 100.0 if exact and aum and aum > 0 else None),
        "volume_is_not_flow": True,
    }


def classify_divergence(
    price_score: Optional[float],
    internal_score: Optional[float],
    *,
    flow_20d: Optional[float] = None,
    internal_delta_20d: Optional[float] = None,
    internal_complete: bool = False,
) -> dict[str, str]:
    """Classify only what the available evidence supports.

    Flow-dependent labels are emitted only when exact 20-day flow exists.
    Complete-accumulation language is withheld when A/D + OBV + breadth are not
    all available.
    """
    if price_score is None or internal_score is None:
        return {"state": "DATA_REQUIRED", "label": "データ不足", "confidence": "NONE"}

    price = float(price_score)
    internal = float(internal_score)
    delta = _num(internal_delta_20d)

    if flow_20d is None:
        if price >= 70 and internal < 50:
            return {
                "state": "PRICE_INTERNAL_DIVERGENCE",
                "label": "価格強・内部弱（分配候補、Flow未確認）",
                "confidence": "PARTIAL",
            }
        if price >= 65 and internal >= 60:
            return {
                "state": "BREADTH_CONFIRMED_STRENGTH",
                "label": "価格強・参加率強（Flow未確認）",
                "confidence": "PARTIAL",
            }
        if price < 55 and internal >= 60:
            return {
                "state": "HIDDEN_INTERNAL_STRENGTH",
                "label": "価格未発火・内部強（先回り監視）",
                "confidence": "PARTIAL",
            }
        return {"state": "NEUTRAL", "label": "中立 / Flow確認待ち", "confidence": "PARTIAL"}

    flow = float(flow_20d)
    if price >= 65 and internal >= 60 and flow > 0:
        state = "CONFIRMED_ACCUMULATION" if internal_complete else "ACCUMULATION_CANDIDATE"
        return {
            "state": state,
            "label": "蓄積×強" if internal_complete else "蓄積候補（A/D・OBV確認待ち）",
            "confidence": "FULL" if internal_complete else "PARTIAL",
        }
    if price < 60 and internal >= 60 and flow > 0:
        return {"state": "HIDDEN_ACCUMULATION", "label": "Hidden Accumulation / 先回り", "confidence": "FULL" if internal_complete else "PARTIAL"}
    if price >= 70 and internal < 50 and flow < 0:
        return {"state": "DISTRIBUTION_TRAP", "label": "価格先行×内部/Flow逆行", "confidence": "FULL" if internal_complete else "PARTIAL"}
    if price >= 60 and internal >= 60 and flow < 0:
        return {"state": "REDEMPTION_DIVERGENCE", "label": "ETF流出≠構成株売り", "confidence": "FULL" if internal_complete else "PARTIAL"}
    if price < 60 and flow > 0 and delta is not None and delta >= 10:
        return {"state": "EARLY_ROTATION", "label": "Flow先行・内部改善 / Watch", "confidence": "FULL" if internal_complete else "PARTIAL"}
    return {"state": "NEUTRAL", "label": "方向感なし", "confidence": "FULL" if internal_complete else "PARTIAL"}


def _group_rows(details: Mapping[str, Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    groups: dict[str, list[Mapping[str, Any]]] = {}
    for row in details.values():
        name = str(row.get("sec") or row.get("sth") or "").strip()
        if not name:
            continue
        groups.setdefault(name, []).append(row)
    return groups


def _group_snapshot(name: str, rows: list[Mapping[str, Any]], flow: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    rs189 = _median_field(rows, "rs189")
    rs63 = _median_field(rows, "rs", "rs63")
    price_components = [x for x in (rs189, rs63) if x is not None]
    price_score = _clip(_mean(price_components)) if price_components else None

    above21 = _percent_above(rows, ("dma21", "v21", "vs21"))
    above50 = _percent_above(rows, ("v50", "dma50", "vs50"))
    internal_components = [x for x in (above21, above50) if x is not None]
    internal_score = _clip(_mean(internal_components)) if internal_components else None
    uv_ratio = _median_field(rows, "uvdv20", "uvdv")

    flow_state = _flow_snapshot(flow)
    classification = classify_divergence(
        price_score,
        internal_score,
        flow_20d=flow_state["flow_20d"],
        internal_complete=False,
    )
    missing = []
    if above21 is None:
        missing.append("Breadth21")
    missing.extend(["A/D", "OBV"])
    if flow_state["status"] != "EXACT":
        missing.append("Exact ETF Flow")

    return {
        "name": name,
        "members": len(rows),
        "price": {
            "score": round(price_score, 1) if price_score is not None else None,
            "median_rs189": round(rs189, 1) if rs189 is not None else None,
            "median_rs63": round(rs63, 1) if rs63 is not None else None,
            "status": "DISPLAY_PROXY_UNVALIDATED",
        },
        "internal": {
            "score": round(internal_score, 1) if internal_score is not None else None,
            "above21_pct": round(above21, 1) if above21 is not None else None,
            "above50_pct": round(above50, 1) if above50 is not None else None,
            "median_up_down_volume_ratio20": round(uv_ratio, 2) if uv_ratio is not None else None,
            "ad_trend": None,
            "obv_trend": None,
            "status": "PARTIAL_BREADTH_ONLY" if internal_score is not None else "DATA_REQUIRED",
        },
        "fund_flow": flow_state,
        "classification": classification,
        "missing": missing,
    }


def build_rotation_intelligence(
    details: Mapping[str, Mapping[str, Any]],
    *,
    secrot: Optional[Mapping[str, Mapping[str, Any]]] = None,
    exact_flows: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> dict[str, Any]:
    """Build a research-facing rotation snapshot without inventing missing data."""
    exact_flows = exact_flows or {}
    groups = []
    for name, rows in _group_rows(details).items():
        if len(rows) < MIN_GROUP_MEMBERS:
            continue
        groups.append(_group_snapshot(name, rows, exact_flows.get(name)))
    groups.sort(
        key=lambda row: (
            row["price"]["score"] is not None,
            row["price"]["score"] or -1,
            row["internal"]["score"] or -1,
        ),
        reverse=True,
    )

    divergences = [row for row in groups if row["classification"]["state"] in {
        "PRICE_INTERNAL_DIVERGENCE", "DISTRIBUTION_TRAP", "REDEMPTION_DIVERGENCE",
        "HIDDEN_INTERNAL_STRENGTH", "HIDDEN_ACCUMULATION", "EARLY_ROTATION",
    }]
    leaders = [row for row in groups if row["classification"]["state"] in {
        "BREADTH_CONFIRMED_STRENGTH", "CONFIRMED_ACCUMULATION", "ACCUMULATION_CANDIDATE",
    }]

    themes = []
    for name, raw in (secrot or {}).items():
        if not isinstance(raw, Mapping):
            continue
        themes.append({
            "name": str(name),
            "rotation": raw.get("rot"),
            "rank": raw.get("rk"),
            "universe_n": raw.get("n"),
            "median_rs": raw.get("med"),
            "weekly_change": raw.get("d1w"),
            "source": "LEGACY_SECROT_DISPLAY_ONLY",
        })
    themes.sort(key=lambda row: (_num(row.get("rank")) is not None, -(_num(row.get("rank")) or 999999)), reverse=True)

    exact_flow_count = sum(1 for row in groups if row["fund_flow"]["status"] == "EXACT")
    return {
        "schema": "v38-rotation-intelligence-1",
        "status": "RESEARCH_VIEW",
        "matrix": {
            "x": "Price proxy = median Stock RS189 / RS63",
            "y": "Internal participation proxy = available %Above21EMA / %Above50MA",
            "bubble": "Exact 20D ETF Flow / AUM only; unavailable values are not approximated",
            "quality": "PARTIAL until A/D + OBV + Breadth21 + exact ETF fund flow are live",
        },
        "fund_flow": {
            "status": "EXACT" if exact_flow_count else "DATA_REQUIRED",
            "exact_groups": exact_flow_count,
            "required_horizons": ["1D", "5D", "20D"],
            "required_fields": ["flow_1d", "flow_5d", "flow_20d", "aum", "source", "exact=true"],
            "prohibited_proxy": "Trading volume must not be labelled Fund Flow",
        },
        "groups": groups,
        "leaders": leaders[:10],
        "divergences": divergences[:10],
        "themes": themes[:30],
        "narrative_contract": {
            "rule": "Facts first; prose may summarize only fields present in this state",
            "do_not_infer": ["ETF Fund Flow", "A/D", "OBV", "PIT Theme taxonomy", "LOO Theme"],
        },
        "v38_role_separation": {
            "rotation": "WHERE capital/internal participation appears to be moving",
            "market_mode": "WHEN / how many normal-stock positions may be added",
            "peer_theme": "WHAT Theme context is valid for Attack ranking",
            "stock_rs": "WHAT stock is eligible/strong",
            "exit": "HOW LONG to hold; rotation does not force exits",
        },
    }
