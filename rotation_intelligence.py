"""Truthful Sector / Theme Rotation Intelligence for the audited V38 companion.

This module deliberately separates:
- price / relative-strength observations,
- internal participation,
- exact ETF fund flow,
- divergence classification,
- V38 trading actions.

It must never treat trading volume as ETF creation/redemption fund flow. When
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


def _internal_snapshot(
    rows: list[Mapping[str, Any]],
    exact_internal: Optional[Mapping[str, Any]],
) -> dict[str, Any]:
    """Return exact Full4 internals when supplied, otherwise a truthful proxy.

    The exact-input composite uses the originally proposed 30/30/25/15 display
    weights for A/D, OBV, %Above21EMA and %Above50MA. Those weights are NOT a
    validated trading rule and are explicitly labelled as such.
    """
    exact_internal = exact_internal or {}
    ad = _num(exact_internal.get("ad_score"))
    obv = _num(exact_internal.get("obv_score"))
    b21_exact = _num(exact_internal.get("breadth21_pct"))
    b50_exact = _num(exact_internal.get("breadth50_pct"))
    delta20 = _num(exact_internal.get("internal_delta_20d"))
    exact = bool(exact_internal.get("exact")) and all(
        value is not None and 0 <= value <= 100
        for value in (ad, obv, b21_exact, b50_exact)
    )
    uv_ratio = _median_field(rows, "uvdv20", "uvdv")

    if exact:
        score = _clip(0.30 * ad + 0.30 * obv + 0.25 * b21_exact + 0.15 * b50_exact)
        return {
            "score": round(score, 1),
            "above21_pct": round(b21_exact, 1),
            "above50_pct": round(b50_exact, 1),
            "median_up_down_volume_ratio20": round(uv_ratio, 2) if uv_ratio is not None else None,
            "ad_trend_score": round(ad, 1),
            "obv_trend_score": round(obv, 1),
            "internal_delta_20d": round(delta20, 1) if delta20 is not None else None,
            "source": exact_internal.get("source"),
            "asof": exact_internal.get("asof"),
            "status": "EXACT_INPUTS_UNVALIDATED_COMPOSITE",
            "complete": True,
            "weights": {"ad": 0.30, "obv": 0.30, "breadth21": 0.25, "breadth50": 0.15},
        }

    above21 = _percent_above(rows, ("dma21", "v21", "vs21"))
    above50 = _percent_above(rows, ("v50", "dma50", "vs50"))
    components = [x for x in (above21, above50) if x is not None]
    score = _clip(_mean(components)) if components else None
    return {
        "score": round(score, 1) if score is not None else None,
        "above21_pct": round(above21, 1) if above21 is not None else None,
        "above50_pct": round(above50, 1) if above50 is not None else None,
        "median_up_down_volume_ratio20": round(uv_ratio, 2) if uv_ratio is not None else None,
        "ad_trend_score": None,
        "obv_trend_score": None,
        "internal_delta_20d": None,
        "source": None,
        "asof": None,
        "status": "PARTIAL_BREADTH_ONLY" if score is not None else "DATA_REQUIRED",
        "complete": False,
        "weights": None,
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

    Strong Flow-dependent labels require both exact 20-day flow and complete
    A/D+OBV+Breadth internals. With exact flow but incomplete internals, only a
    CANDIDATE label is allowed. All labels remain research observations until a
    separate forward-predictive validation is passed.
    """
    if price_score is None or internal_score is None:
        return {"state": "DATA_REQUIRED", "label": "データ不足", "confidence": "NONE"}

    price = float(price_score)
    internal = float(internal_score)
    delta = _num(internal_delta_20d)
    complete_label = "FULL_DATA_UNVALIDATED_SIGNAL" if internal_complete else "PARTIAL"

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
            "label": "蓄積×強（研究観測）" if internal_complete else "蓄積候補（A/D・OBV確認待ち）",
            "confidence": complete_label,
        }
    if price < 60 and internal >= 60 and flow > 0:
        state = "HIDDEN_ACCUMULATION" if internal_complete else "HIDDEN_ACCUMULATION_CANDIDATE"
        return {
            "state": state,
            "label": "Hidden Accumulation / 先回り研究候補" if internal_complete else "Hidden Accumulation候補 / 内部詳細確認待ち",
            "confidence": complete_label,
        }
    if price >= 70 and internal < 50 and flow < 0:
        state = "DISTRIBUTION_TRAP" if internal_complete else "DISTRIBUTION_CANDIDATE"
        return {
            "state": state,
            "label": "価格先行×内部/Flow逆行（研究観測）" if internal_complete else "Distribution候補 / A/D・OBV確認待ち",
            "confidence": complete_label,
        }
    if price >= 60 and internal >= 60 and flow < 0:
        state = "REDEMPTION_DIVERGENCE" if internal_complete else "REDEMPTION_DIVERGENCE_CANDIDATE"
        return {
            "state": state,
            "label": "ETF流出≠構成株売り" if internal_complete else "Redemption Divergence候補 / 内部詳細確認待ち",
            "confidence": complete_label,
        }
    if price < 60 and flow > 0 and delta is not None and delta >= 10:
        state = "EARLY_ROTATION" if internal_complete else "EARLY_ROTATION_CANDIDATE"
        return {"state": state, "label": "Flow先行・内部改善 / Watch", "confidence": complete_label}
    return {"state": "NEUTRAL", "label": "方向感なし", "confidence": complete_label}


def _group_rows(
    details: Mapping[str, Mapping[str, Any]],
    key: str,
    *,
    fallback: Optional[str] = None,
) -> dict[str, list[Mapping[str, Any]]]:
    groups: dict[str, list[Mapping[str, Any]]] = {}
    for row in details.values():
        name = str(row.get(key) or (row.get(fallback) if fallback else "") or "").strip()
        if not name:
            continue
        groups.setdefault(name, []).append(row)
    return groups


def _group_snapshot(
    name: str,
    rows: list[Mapping[str, Any]],
    flow: Optional[Mapping[str, Any]],
    exact_internal: Optional[Mapping[str, Any]],
    *,
    level: str,
) -> dict[str, Any]:
    rs189 = _median_field(rows, "rs189")
    rs63 = _median_field(rows, "rs", "rs63")
    price_components = [x for x in (rs189, rs63) if x is not None]
    price_score = _clip(_mean(price_components)) if price_components else None

    internal_state = _internal_snapshot(rows, exact_internal)
    flow_state = _flow_snapshot(flow)
    classification = classify_divergence(
        price_score,
        internal_state["score"],
        flow_20d=flow_state["flow_20d"],
        internal_delta_20d=internal_state["internal_delta_20d"],
        internal_complete=bool(internal_state["complete"]),
    )
    missing = []
    if internal_state["above21_pct"] is None:
        missing.append("Breadth21")
    if internal_state["ad_trend_score"] is None:
        missing.append("A/D")
    if internal_state["obv_trend_score"] is None:
        missing.append("OBV")
    if flow_state["status"] != "EXACT":
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
        "internal": internal_state,
        "fund_flow": flow_state,
        "classification": classification,
        "missing": missing,
    }


def _snapshots(
    grouped: Mapping[str, list[Mapping[str, Any]]],
    exact_flows: Mapping[str, Mapping[str, Any]],
    exact_internals: Mapping[str, Mapping[str, Any]],
    *,
    level: str,
) -> list[dict[str, Any]]:
    rows = []
    for name, members in grouped.items():
        if len(members) < MIN_GROUP_MEMBERS:
            continue
        rows.append(_group_snapshot(
            name, members, exact_flows.get(name), exact_internals.get(name), level=level
        ))
    rows.sort(
        key=lambda row: (
            row["price"]["score"] is not None,
            row["price"]["score"] or -1,
            row["internal"]["score"] or -1,
        ),
        reverse=True,
    )
    return rows


def build_rotation_intelligence(
    details: Mapping[str, Mapping[str, Any]],
    *,
    secrot: Optional[Mapping[str, Mapping[str, Any]]] = None,
    exact_flows: Optional[Mapping[str, Mapping[str, Any]]] = None,
    exact_internals: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> dict[str, Any]:
    """Build a research-facing rotation snapshot without inventing missing data."""
    exact_flows = exact_flows or {}
    exact_internals = exact_internals or {}
    sector_groups = _snapshots(
        _group_rows(details, "sec", fallback="sth"), exact_flows, exact_internals, level="SECTOR_OR_PARENT"
    )
    theme_groups = _snapshots(
        _group_rows(details, "sth"), exact_flows, exact_internals, level="THEME_DISPLAY_TAXONOMY"
    )

    divergence_states = {
        "PRICE_INTERNAL_DIVERGENCE", "DISTRIBUTION_TRAP", "DISTRIBUTION_CANDIDATE",
        "REDEMPTION_DIVERGENCE", "REDEMPTION_DIVERGENCE_CANDIDATE",
        "HIDDEN_INTERNAL_STRENGTH", "HIDDEN_ACCUMULATION", "HIDDEN_ACCUMULATION_CANDIDATE",
        "EARLY_ROTATION", "EARLY_ROTATION_CANDIDATE",
    }
    divergences = [row for row in sector_groups if row["classification"]["state"] in divergence_states]
    leaders = [row for row in sector_groups if row["classification"]["state"] in {
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
    themes.sort(
        key=lambda row: (_num(row.get("rank")) is not None, -(_num(row.get("rank")) or 999999)),
        reverse=True,
    )

    all_snapshots = sector_groups + theme_groups
    exact_flow_count = sum(1 for row in all_snapshots if row["fund_flow"]["status"] == "EXACT")
    exact_internal_count = sum(1 for row in all_snapshots if row["internal"]["complete"])
    return {
        "schema": "v38-rotation-intelligence-1",
        "status": "RESEARCH_VIEW",
        "matrix": {
            "x": "Price proxy = median Stock RS189 / RS63",
            "y": "Internal participation; exact Full4 when supplied, otherwise available breadth proxy",
            "bubble": "Exact 20D ETF Flow / AUM only; unavailable values are not approximated",
            "quality": "RESEARCH / not an entry-exit gate; exact-data composite weights remain unvalidated",
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
            "exact_groups": exact_internal_count,
            "required_fields": ["ad_score", "obv_score", "breadth21_pct", "breadth50_pct", "source", "asof", "exact=true"],
            "optional_input": "rotation-internals.json",
            "composite": "30% A/D + 30% OBV + 25% Breadth21 + 15% Breadth50 (DISPLAY / UNVALIDATED)",
        },
        "groups": sector_groups,
        "sector_groups": sector_groups,
        "theme_groups": theme_groups,
        "leaders": leaders[:10],
        "divergences": divergences[:10],
        "themes": themes[:30],
        "narrative_contract": {
            "rule": "Facts first; prose may summarize only fields present in this state",
            "do_not_infer": ["ETF Fund Flow", "A/D", "OBV", "PIT Theme taxonomy", "LOO Theme"],
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
