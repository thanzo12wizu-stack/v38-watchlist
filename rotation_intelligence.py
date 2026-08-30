"""Truthful Sector / Theme Rotation Intelligence for the audited V38 companion.

The research view deliberately keeps five layers separate:
Price -> Internal participation -> Exact ETF fund flow -> Rotation/Divergence -> V38 action.
Missing data stays DATA_REQUIRED. Trading volume is never relabelled as ETF fund flow.
None of the display composites in this module are trading gates until separately validated.
"""

from __future__ import annotations

from statistics import median
from typing import Any, Mapping, Optional

MIN_GROUP_MEMBERS = 3
INTERNAL_FIELDS = ("ad_score", "obv_score", "breadth21_pct", "breadth50_pct")


def _num(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if x == x and x not in (float("inf"), float("-inf")) else None


def _clip(value: float) -> float:
    return max(0.0, min(100.0, float(value)))


def _med(values: list[float]) -> Optional[float]:
    return float(median(values)) if values else None


def _mean(values: list[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


def _median_field(rows: list[Mapping[str, Any]], *keys: str) -> Optional[float]:
    values: list[float] = []
    for row in rows:
        for key in keys:
            value = _num(row.get(key))
            if value is not None:
                values.append(value)
                break
    return _med(values)


def _percent_above(rows: list[Mapping[str, Any]], keys: tuple[str, ...]) -> Optional[float]:
    values: list[float] = []
    for row in rows:
        for key in keys:
            value = _num(row.get(key))
            if value is not None:
                values.append(value)
                break
    return None if not values else 100.0 * sum(v > 0 for v in values) / len(values)


def _flow_snapshot(flow: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    flow = flow or {}
    one, five, twenty, aum = (_num(flow.get(k)) for k in ("flow_1d", "flow_5d", "flow_20d", "aum"))
    exact = bool(flow.get("exact")) and twenty is not None
    return {
        "status": "EXACT" if exact else "DATA_REQUIRED",
        "ticker": flow.get("ticker") if exact else None,
        "source": flow.get("source") if exact else None,
        "asof": flow.get("asof") if exact else None,
        "flow_1d": one if exact else None,
        "flow_5d": five if exact else None,
        "flow_20d": twenty if exact else None,
        "aum": aum if exact else None,
        "flow_20d_pct_aum": ((twenty / aum) * 100.0 if exact and aum and aum > 0 else None),
        "volume_is_not_flow": True,
    }


def _exact_internal_variant(payload: Mapping[str, Any], *, parent_exact: bool = False) -> Optional[dict[str, Any]]:
    values = {key: _num(payload.get(key)) for key in INTERNAL_FIELDS}
    exact = bool(payload.get("exact", parent_exact))
    if not exact or not all(v is not None and 0 <= v <= 100 for v in values.values()):
        return None
    ad, obv, b21, b50 = (values[k] for k in INTERNAL_FIELDS)
    score = _clip(0.30 * ad + 0.30 * obv + 0.25 * b21 + 0.15 * b50)
    delta = _num(payload.get("internal_delta_20d"))
    return {
        "score": round(score, 1),
        "ad_trend_score": round(ad, 1),
        "obv_trend_score": round(obv, 1),
        "above21_pct": round(b21, 1),
        "above50_pct": round(b50, 1),
        "internal_delta_20d": round(delta, 1) if delta is not None else None,
        "source": payload.get("source"),
        "asof": payload.get("asof"),
        "status": "EXACT_INPUTS_UNVALIDATED_COMPOSITE",
    }


def _internal_snapshot(rows: list[Mapping[str, Any]], exact_internal: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    """Primary matrix internal is equal-weight participation.

    A cap-weight version can be supplied in parallel to diagnose mega-cap concentration.
    Both use the proposed 30/30/25/15 display weights, which remain unvalidated.
    Legacy flat exact input is treated as the equal-weight variant for compatibility.
    """
    raw = exact_internal or {}
    parent_exact = bool(raw.get("exact"))
    ew_payload = raw.get("equal_weight") if isinstance(raw.get("equal_weight"), Mapping) else raw
    cw_payload = raw.get("cap_weight") if isinstance(raw.get("cap_weight"), Mapping) else {}
    ew = _exact_internal_variant(ew_payload, parent_exact=parent_exact)
    cw = _exact_internal_variant(cw_payload, parent_exact=parent_exact) if cw_payload else None
    uv_ratio = _median_field(rows, "uvdv20", "uvdv")

    if ew is not None:
        gap = (cw["score"] - ew["score"]) if cw is not None else None
        return {
            "score": ew["score"],
            "above21_pct": ew["above21_pct"],
            "above50_pct": ew["above50_pct"],
            "median_up_down_volume_ratio20": round(uv_ratio, 2) if uv_ratio is not None else None,
            "ad_trend_score": ew["ad_trend_score"],
            "obv_trend_score": ew["obv_trend_score"],
            "internal_delta_20d": ew["internal_delta_20d"],
            "source": ew.get("source") or raw.get("source"),
            "asof": ew.get("asof") or raw.get("asof"),
            "status": "EXACT_INPUTS_UNVALIDATED_COMPOSITE",
            "complete": True,
            "weights": {"ad": 0.30, "obv": 0.30, "breadth21": 0.25, "breadth50": 0.15},
            "primary_weighting": "EQUAL_WEIGHT",
            "equal_weight": ew,
            "cap_weight": cw or {"status": "DATA_REQUIRED", "score": None},
            "cap_minus_equal_gap": round(gap, 1) if gap is not None else None,
            "concentration_diagnostic": "DISPLAY_ONLY_UNVALIDATED",
        }

    above21 = _percent_above(rows, ("dma21", "v21", "vs21"))
    above50 = _percent_above(rows, ("v50", "dma50", "vs50"))
    components = [x for x in (above21, above50) if x is not None]
    score = _clip(_mean(components)) if components else None
    partial = {
        "score": round(score, 1) if score is not None else None,
        "above21_pct": round(above21, 1) if above21 is not None else None,
        "above50_pct": round(above50, 1) if above50 is not None else None,
        "ad_trend_score": None,
        "obv_trend_score": None,
        "internal_delta_20d": None,
        "status": "PARTIAL_BREADTH_ONLY" if score is not None else "DATA_REQUIRED",
    }
    return {
        **partial,
        "median_up_down_volume_ratio20": round(uv_ratio, 2) if uv_ratio is not None else None,
        "source": None,
        "asof": None,
        "complete": False,
        "weights": None,
        "primary_weighting": "EQUAL_WEIGHT_PROXY",
        "equal_weight": partial,
        "cap_weight": {"status": "DATA_REQUIRED", "score": None},
        "cap_minus_equal_gap": None,
        "concentration_diagnostic": "DATA_REQUIRED",
    }


def classify_divergence(
    price_score: Optional[float],
    internal_score: Optional[float],
    *,
    flow_20d: Optional[float] = None,
    internal_delta_20d: Optional[float] = None,
    internal_complete: bool = False,
) -> dict[str, str]:
    """Observation labels only; not a validated entry/exit signal."""
    if price_score is None or internal_score is None:
        return {"state": "DATA_REQUIRED", "label": "データ不足", "confidence": "NONE"}
    price, internal = float(price_score), float(internal_score)
    delta = _num(internal_delta_20d)
    confidence = "FULL_DATA_UNVALIDATED_SIGNAL" if internal_complete else "PARTIAL"
    if flow_20d is None:
        if price >= 70 and internal < 50:
            return {"state": "PRICE_INTERNAL_DIVERGENCE", "label": "価格強・内部弱（分配候補、Flow未確認）", "confidence": "PARTIAL"}
        if price >= 65 and internal >= 60:
            return {"state": "BREADTH_CONFIRMED_STRENGTH", "label": "価格強・参加率強（Flow未確認）", "confidence": "PARTIAL"}
        if price < 55 and internal >= 60:
            return {"state": "HIDDEN_INTERNAL_STRENGTH", "label": "価格未発火・内部強（先回り監視）", "confidence": "PARTIAL"}
        return {"state": "NEUTRAL", "label": "中立 / Flow確認待ち", "confidence": "PARTIAL"}
    flow = float(flow_20d)
    if price >= 65 and internal >= 60 and flow > 0:
        return {"state": "CONFIRMED_ACCUMULATION" if internal_complete else "ACCUMULATION_CANDIDATE", "label": "蓄積×強（研究観測）" if internal_complete else "蓄積候補（A/D・OBV確認待ち）", "confidence": confidence}
    if price < 60 and internal >= 60 and flow > 0:
        return {"state": "HIDDEN_ACCUMULATION" if internal_complete else "HIDDEN_ACCUMULATION_CANDIDATE", "label": "Hidden Accumulation / 先回り研究候補" if internal_complete else "Hidden Accumulation候補 / 内部詳細確認待ち", "confidence": confidence}
    if price >= 70 and internal < 50 and flow < 0:
        return {"state": "DISTRIBUTION_TRAP" if internal_complete else "DISTRIBUTION_CANDIDATE", "label": "価格先行×内部/Flow逆行（研究観測）" if internal_complete else "Distribution候補 / A/D・OBV確認待ち", "confidence": confidence}
    if price >= 60 and internal >= 60 and flow < 0:
        return {"state": "REDEMPTION_DIVERGENCE" if internal_complete else "REDEMPTION_DIVERGENCE_CANDIDATE", "label": "ETF流出≠構成株売り" if internal_complete else "Redemption Divergence候補 / 内部詳細確認待ち", "confidence": confidence}
    if price < 60 and flow > 0 and delta is not None and delta >= 10:
        return {"state": "EARLY_ROTATION" if internal_complete else "EARLY_ROTATION_CANDIDATE", "label": "Flow先行・内部改善 / Watch", "confidence": confidence}
    return {"state": "NEUTRAL", "label": "方向感なし", "confidence": confidence}


def _group_rows(details: Mapping[str, Mapping[str, Any]], key: str, *, fallback: Optional[str] = None) -> dict[str, list[Mapping[str, Any]]]:
    groups: dict[str, list[Mapping[str, Any]]] = {}
    for row in details.values():
        name = str(row.get(key) or (row.get(fallback) if fallback else "") or "").strip()
        if name:
            groups.setdefault(name, []).append(row)
    return groups


def _group_snapshot(name: str, rows: list[Mapping[str, Any]], flow: Optional[Mapping[str, Any]], exact_internal: Optional[Mapping[str, Any]], *, level: str) -> dict[str, Any]:
    rs189 = _median_field(rows, "rs189")
    rs63 = _median_field(rows, "rs", "rs63")
    price_components = [x for x in (rs189, rs63) if x is not None]
    price_score = _clip(_mean(price_components)) if price_components else None
    internal = _internal_snapshot(rows, exact_internal)
    fund_flow = _flow_snapshot(flow)
    classification = classify_divergence(
        price_score,
        internal["score"],
        flow_20d=fund_flow["flow_20d"],
        internal_delta_20d=internal["internal_delta_20d"],
        internal_complete=bool(internal["complete"]),
    )
    missing = []
    if internal["above21_pct"] is None:
        missing.append("Breadth21")
    if internal["ad_trend_score"] is None:
        missing.append("A/D")
    if internal["obv_trend_score"] is None:
        missing.append("OBV")
    if internal["cap_weight"]["status"] == "DATA_REQUIRED":
        missing.append("Cap-weight Internal")
    if fund_flow["status"] != "EXACT":
        missing.append("Exact ETF Flow")
    return {
        "name": name,
        "level": level,
        "members": len(rows),
        "price": {
            "score": round(price_score, 1) if price_score is not None else None,
            "median_rs189": round(rs189, 1) if rs189 is not None else None,
            "median_rs63": round(rs63, 1) if rs63 is not None else None,
            "status": "DISPLAY_PROXY_UNVALIDATED",
        },
        "internal": internal,
        "fund_flow": fund_flow,
        "classification": classification,
        "missing": missing,
    }


def _snapshots(grouped: Mapping[str, list[Mapping[str, Any]]], exact_flows: Mapping[str, Mapping[str, Any]], exact_internals: Mapping[str, Mapping[str, Any]], *, level: str) -> list[dict[str, Any]]:
    rows = [
        _group_snapshot(name, members, exact_flows.get(name), exact_internals.get(name), level=level)
        for name, members in grouped.items() if len(members) >= MIN_GROUP_MEMBERS
    ]
    rows.sort(key=lambda row: (row["price"]["score"] is not None, row["price"]["score"] or -1, row["internal"]["score"] or -1), reverse=True)
    return rows


def build_rotation_intelligence(
    details: Mapping[str, Mapping[str, Any]],
    *,
    secrot: Optional[Mapping[str, Mapping[str, Any]]] = None,
    exact_flows: Optional[Mapping[str, Mapping[str, Any]]] = None,
    exact_internals: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> dict[str, Any]:
    exact_flows, exact_internals = exact_flows or {}, exact_internals or {}
    sector_groups = _snapshots(_group_rows(details, "sec", fallback="sth"), exact_flows, exact_internals, level="SECTOR_OR_PARENT")
    theme_groups = _snapshots(_group_rows(details, "sth"), exact_flows, exact_internals, level="THEME_DISPLAY_TAXONOMY")
    divergence_states = {
        "PRICE_INTERNAL_DIVERGENCE", "DISTRIBUTION_TRAP", "DISTRIBUTION_CANDIDATE",
        "REDEMPTION_DIVERGENCE", "REDEMPTION_DIVERGENCE_CANDIDATE", "HIDDEN_INTERNAL_STRENGTH",
        "HIDDEN_ACCUMULATION", "HIDDEN_ACCUMULATION_CANDIDATE", "EARLY_ROTATION", "EARLY_ROTATION_CANDIDATE",
    }
    divergences = [row for row in sector_groups if row["classification"]["state"] in divergence_states]
    leaders = [row for row in sector_groups if row["classification"]["state"] in {"BREADTH_CONFIRMED_STRENGTH", "CONFIRMED_ACCUMULATION", "ACCUMULATION_CANDIDATE"}]

    themes = []
    for name, raw in (secrot or {}).items():
        if isinstance(raw, Mapping):
            themes.append({"name": str(name), "rotation": raw.get("rot"), "rank": raw.get("rk"), "universe_n": raw.get("n"), "median_rs": raw.get("med"), "weekly_change": raw.get("d1w"), "source": "LEGACY_SECROT_DISPLAY_ONLY"})
    themes.sort(key=lambda row: (_num(row.get("rank")) is not None, -(_num(row.get("rank")) or 999999)), reverse=True)

    all_groups = sector_groups + theme_groups
    exact_flow_count = sum(row["fund_flow"]["status"] == "EXACT" for row in all_groups)
    exact_internal_count = sum(bool(row["internal"]["complete"]) for row in all_groups)
    cap_internal_count = sum(row["internal"]["cap_weight"]["status"] != "DATA_REQUIRED" for row in all_groups)
    return {
        "schema": "v38-rotation-intelligence-2",
        "status": "RESEARCH_VIEW",
        "matrix": {
            "x": "Price proxy = median Stock RS189 / RS63",
            "y": "Equal-weight Internal participation; Cap-weight is a separate concentration diagnostic",
            "bubble": "Exact 20D ETF Flow / AUM only; unavailable values are not approximated",
            "quality": "RESEARCH / not an entry-exit gate; score weights and thresholds remain unvalidated",
        },
        "fund_flow": {
            "status": "EXACT" if exact_flow_count else "DATA_REQUIRED",
            "exact_groups": exact_flow_count,
            "required_horizons": ["1D", "5D", "20D"],
            "required_fields": ["ticker", "flow_1d", "flow_5d", "flow_20d", "aum", "source", "asof", "exact=true"],
            "optional_input": "rotation-flow.json",
            "prohibited_proxy": "Trading volume must not be labelled Fund Flow",
        },
        "internals": {
            "status": "EXACT" if exact_internal_count else "DATA_REQUIRED",
            "exact_equal_weight_groups": exact_internal_count,
            "exact_cap_weight_groups": cap_internal_count,
            "primary": "EQUAL_WEIGHT",
            "required_variants": ["equal_weight", "cap_weight"],
            "required_fields_per_variant": [*INTERNAL_FIELDS, "internal_delta_20d", "source", "asof", "exact=true"],
            "optional_input": "rotation-internals.json",
            "composite": "30% A/D + 30% OBV + 25% Breadth21 + 15% Breadth50 (DISPLAY / UNVALIDATED)",
            "cap_weight_role": "diagnose concentration / mega-cap masking; never substitute for equal-weight participation",
        },
        "history": {
            "status": "DATA_REQUIRED",
            "optional_input": "rotation-history.json",
            "role": "1D/5D/20D state transitions and dated events; never infer dates from one current snapshot",
        },
        "groups": sector_groups,
        "sector_groups": sector_groups,
        "theme_groups": theme_groups,
        "leaders": leaders[:10],
        "divergences": divergences[:10],
        "themes": themes[:30],
        "narrative_contract": {
            "rule": "Facts first; prose may summarize only fields present in this state",
            "do_not_infer": ["ETF Fund Flow", "A/D", "OBV", "Macro causality", "PIT Theme taxonomy", "LOO Theme", "historical transition dates"],
        },
        "validation": {
            "predictive_status": "NOT VALIDATED",
            "required_before_trading_gate": "2022-2026 transition / forward-return study with frozen thresholds",
            "absolute_backtest_cagr_use": "PROHIBITED AS EXPECTED RETURN",
        },
        "v38_role_separation": {
            "rotation": "WHERE capital/internal participation appears to be moving",
            "market_mode": "WHEN / how many normal-stock positions may be added",
            "peer_theme": "WHAT Theme context is valid for Attack ranking",
            "stock_rs": "WHAT stock is eligible/strong",
            "exit": "HOW LONG to hold; rotation does not force exits",
        },
    }
