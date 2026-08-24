from __future__ import annotations

from copy import deepcopy
from statistics import median
from typing import Any


STRUCTURE_LABEL_JA = {
    "CLEAR": "上値余地あり",
    "ABSORBING": "Supply吸収中",
    "DEMAND_SUPPORTED": "Demand上",
    "SUPPLY_NEAR": "Supply直下",
    "MIXED": "中立",
    "NO_DATA": "構造データ不足",
}

BREAKOUT_RANK = {
    "BREAKOUT_NOW": 4,
    "BREAKOUT_RECENT": 3,
    "BREAKOUT_WATCH": 2,
    "NONE": 1,
    "EXTENDED": 0,
    "NO_DATA": 0,
}

PHASE_RANK = {"EMERGING": 4, "LEADING": 3, "MATURE": 2, "LOSING": 1}


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    if x != x or x in (float("inf"), float("-inf")):
        return None
    return x


def _clip(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _med(values: list[float], default: float) -> float:
    return float(median(values)) if values else default


def _support_distance(price: float, level: float | None) -> float | None:
    if level is None or level <= 0 or level > price * 1.005:
        return None
    return 100.0 * (price / level - 1.0)


def _supply_distance(price: float, level: float | None) -> float | None:
    if level is None or level <= 0 or level < price * 0.995:
        return None
    return 100.0 * (level / price - 1.0)


def stock_structure(stock: dict[str, Any]) -> dict[str, Any]:
    """Estimate immediate supply/demand structure from levels already built by Leadership.

    This is intentionally independent from RS/earnings strength. Supply uses unbroken
    20/50-day pivots above price; demand uses the nearest held 21EMA/50SMA/63VWAP or
    already-cleared pivot below price. The result answers a different question from
    Leadership Score: whether the current location has room above and support below.
    """
    price = _num(stock.get("price"))
    if price is None or price <= 0:
        return {
            "score": None,
            "state": "NO_DATA",
            "label": STRUCTURE_LABEL_JA["NO_DATA"],
            "supply_distance_pct": None,
            "demand_distance_pct": None,
            "supply_score": None,
            "demand_score": None,
            "absorption_score": None,
            "volume_dryup_score": None,
        }

    pivot20 = _num(stock.get("pivot"))
    pivot50 = _num(stock.get("pivot50"))
    breakout = stock.get("breakout") if isinstance(stock.get("breakout"), dict) else {}
    bo_status = str(breakout.get("status") or "")

    supply_distances = [
        d for d in (
            _supply_distance(price, pivot20),
            _supply_distance(price, pivot50),
        ) if d is not None
    ]
    supply_distance = min(supply_distances) if supply_distances else None

    if bo_status in {"BREAKOUT_NOW", "BREAKOUT_RECENT"} and supply_distance is None:
        supply_score = 94.0
    elif supply_distance is None:
        supply_score = 78.0
    elif supply_distance <= 1.5:
        supply_score = 24.0
    elif supply_distance <= 3.0:
        supply_score = 38.0
    elif supply_distance <= 5.0:
        supply_score = 55.0
    elif supply_distance <= 8.0:
        supply_score = 72.0
    else:
        supply_score = 90.0

    demand_candidates: list[tuple[str, float]] = []
    for key in ("ema21", "vwap63", "sma50"):
        level = _num(stock.get(key))
        d = _support_distance(price, level)
        if d is not None:
            demand_candidates.append((key, d))
    for key, level in (("pivot20", pivot20), ("pivot50", pivot50)):
        d = _support_distance(price, level)
        if d is not None and level is not None and level <= price:
            demand_candidates.append((key, d))

    demand_source = None
    demand_distance = None
    if demand_candidates:
        demand_source, demand_distance = min(demand_candidates, key=lambda pair: pair[1])

    if demand_distance is None:
        demand_score = 30.0
    elif demand_distance <= 2.0:
        demand_score = 96.0
    elif demand_distance <= 4.0:
        demand_score = 88.0
    elif demand_distance <= 7.0:
        demand_score = 75.0
    elif demand_distance <= 10.0:
        demand_score = 60.0
    else:
        demand_score = 38.0

    rs63 = _num(stock.get("rs63"))
    rs21 = _num(stock.get("rs21"))
    accel = _num(stock.get("acceleration"))
    rvol = _num(stock.get("volume_ratio"))

    absorption_score = 20.0
    if bo_status == "BREAKOUT_NOW":
        absorption_score = 96.0
    elif bo_status == "BREAKOUT_RECENT":
        absorption_score = 88.0
    else:
        if supply_distance is not None and supply_distance <= 5.0:
            absorption_score += 25.0
        if bo_status == "BREAKOUT_WATCH":
            absorption_score += 20.0
        if rs63 is not None and rs63 >= 85:
            absorption_score += 10.0
        if rs21 is not None and rs21 >= 90:
            absorption_score += 8.0
        if accel is not None and accel >= 5:
            absorption_score += 9.0
        # Low-volume tests/base drying are constructive before a breakout.
        if rvol is not None and 0.45 <= rvol <= 0.95:
            absorption_score += 8.0
    absorption_score = _clip(absorption_score)

    if rvol is None:
        volume_dryup_score = 50.0
    elif rvol <= 0.65:
        volume_dryup_score = 92.0
    elif rvol <= 0.85:
        volume_dryup_score = 82.0
    elif rvol <= 1.0:
        volume_dryup_score = 70.0
    elif rvol <= 1.25:
        volume_dryup_score = 55.0
    else:
        # High RVOL is not a dry base, but is healthy if the breakout is happening now.
        volume_dryup_score = 75.0 if bo_status == "BREAKOUT_NOW" else 38.0

    score = _clip(
        0.40 * supply_score
        + 0.30 * demand_score
        + 0.20 * absorption_score
        + 0.10 * volume_dryup_score
    )

    if supply_distance is not None and supply_distance <= 4.0 and absorption_score < 65.0:
        state = "SUPPLY_NEAR"
    elif supply_distance is not None and supply_distance <= 5.0 and absorption_score >= 65.0:
        state = "ABSORBING"
    elif supply_score >= 78.0 and demand_score >= 58.0:
        state = "CLEAR"
    elif demand_score >= 78.0:
        state = "DEMAND_SUPPORTED"
    else:
        state = "MIXED"

    return {
        "score": round(score, 1),
        "state": state,
        "label": STRUCTURE_LABEL_JA[state],
        "supply_distance_pct": round(supply_distance, 2) if supply_distance is not None else None,
        "demand_distance_pct": round(demand_distance, 2) if demand_distance is not None else None,
        "demand_source": demand_source,
        "supply_score": round(supply_score, 1),
        "demand_score": round(demand_score, 1),
        "absorption_score": round(absorption_score, 1),
        "volume_dryup_score": round(volume_dryup_score, 1),
    }


def enrich_group(group: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(group)
    stocks = list(out.get("stocks") or [])
    for stock in stocks:
        stock["structure"] = stock_structure(stock)

    leaders = [s for s in stocks if str(s.get("role")) in {"PIONEER", "LEADER"}]
    sample = leaders[:8] or stocks[:8]
    structures = [s.get("structure") for s in sample if isinstance(s.get("structure"), dict) and _num(s["structure"].get("score")) is not None]

    if not structures:
        out.update({
            "leadership_score": _num(out.get("score")),
            "structure_score": None,
            "priority_score": _num(out.get("score")),
            "structure_state": "NO_DATA",
            "structure_label": STRUCTURE_LABEL_JA["NO_DATA"],
            "supply_distance_pct": None,
            "demand_distance_pct": None,
            "supply_clearance_score": None,
            "demand_support_score": None,
            "absorption_score": None,
        })
        out["stocks"] = stocks
        return out

    supply_scores = [_num(x.get("supply_score")) for x in structures]
    demand_scores = [_num(x.get("demand_score")) for x in structures]
    absorption_scores = [_num(x.get("absorption_score")) for x in structures]
    volume_scores = [_num(x.get("volume_dryup_score")) for x in structures]
    supply_distances = [_num(x.get("supply_distance_pct")) for x in structures]
    demand_distances = [_num(x.get("demand_distance_pct")) for x in structures]

    supply_score = _med([x for x in supply_scores if x is not None], 70.0)
    demand_score = _med([x for x in demand_scores if x is not None], 50.0)
    absorption_score = _med([x for x in absorption_scores if x is not None], 40.0)
    volume_score = _med([x for x in volume_scores if x is not None], 50.0)
    structure_score = _clip(0.40 * supply_score + 0.30 * demand_score + 0.20 * absorption_score + 0.10 * volume_score)

    supply_near_share = 100.0 * sum(
        1 for x in supply_distances if x is not None and x <= 4.0
    ) / len(structures)
    demand_near_share = 100.0 * sum(
        1 for x in demand_distances if x is not None and x <= 5.0
    ) / len(structures)

    median_supply = _med([x for x in supply_distances if x is not None], -1.0)
    median_demand = _med([x for x in demand_distances if x is not None], -1.0)
    leader_breakouts = int(out.get("leader_breakouts") or 0)

    if supply_near_share >= 40.0 and absorption_score < 65.0:
        state = "SUPPLY_NEAR"
    elif supply_near_share >= 25.0 and absorption_score >= 65.0:
        state = "ABSORBING"
    elif supply_score >= 78.0 and demand_score >= 58.0:
        state = "CLEAR"
    elif demand_near_share >= 50.0 and demand_score >= 75.0:
        state = "DEMAND_SUPPORTED"
    else:
        state = "MIXED"

    # A confirmed leader breakout is evidence that at least part of the nearby supply
    # has been absorbed, so do not leave the group in a hard SUPPLY_NEAR state.
    if state == "SUPPLY_NEAR" and leader_breakouts > 0 and absorption_score >= 55.0:
        state = "ABSORBING"

    leadership_score = _num(out.get("score")) or 0.0
    priority_score = _clip(0.60 * leadership_score + 0.40 * structure_score)

    out.update({
        "stocks": stocks,
        "leadership_score": round(leadership_score, 1),
        "structure_score": round(structure_score, 1),
        "priority_score": round(priority_score, 1),
        "structure_state": state,
        "structure_label": STRUCTURE_LABEL_JA[state],
        "supply_distance_pct": round(median_supply, 2) if median_supply >= 0 else None,
        "demand_distance_pct": round(median_demand, 2) if median_demand >= 0 else None,
        "supply_clearance_score": round(supply_score, 1),
        "demand_support_score": round(demand_score, 1),
        "absorption_score": round(absorption_score, 1),
        "supply_near_share": round(supply_near_share, 1),
        "demand_near_share": round(demand_near_share, 1),
    })
    return out


def _group_sort_key(group: dict[str, Any]) -> tuple[Any, ...]:
    return (
        PHASE_RANK.get(str(group.get("phase")), 0),
        1 if int(group.get("leader_breakouts") or 0) > 0 else 0,
        _num(group.get("priority_score")) or 0.0,
        _num(group.get("pioneer_score")) or 0.0,
        _num(group.get("breadth_score")) or 0.0,
    )


def _sector_overlay(sector: dict[str, Any], child_groups: list[dict[str, Any]]) -> dict[str, Any]:
    out = deepcopy(sector)
    values = [_num(g.get("structure_score")) for g in child_groups]
    values = [x for x in values if x is not None]
    structure_score = _med(values, 50.0) if values else None
    leadership_score = _num(out.get("score"))
    if structure_score is not None and leadership_score is not None:
        out["priority_score"] = round(_clip(0.60 * leadership_score + 0.40 * structure_score), 1)
    else:
        out["priority_score"] = leadership_score
    out["leadership_score"] = leadership_score
    out["structure_score"] = round(structure_score, 1) if structure_score is not None else None

    states = [str(g.get("structure_state")) for g in child_groups]
    if "ABSORBING" in states:
        state = "ABSORBING"
    elif states.count("CLEAR") >= max(1, len(states) // 2):
        state = "CLEAR"
    elif "DEMAND_SUPPORTED" in states:
        state = "DEMAND_SUPPORTED"
    elif "SUPPLY_NEAR" in states:
        state = "SUPPLY_NEAR"
    else:
        state = "MIXED" if states else "NO_DATA"
    out["structure_state"] = state
    out["structure_label"] = STRUCTURE_LABEL_JA[state]
    return out


def _action_item(group: dict[str, Any], stock: dict[str, Any], *, override_status: str | None = None, reason_prefix: str | None = None) -> dict[str, Any]:
    entry = stock.get("entry") if isinstance(stock.get("entry"), dict) else {}
    structure = stock.get("structure") if isinstance(stock.get("structure"), dict) else {}
    reason = str(entry.get("reason") or "")
    if reason_prefix:
        reason = f"{reason_prefix} / {reason}" if reason else reason_prefix
    return {
        "symbol": stock.get("symbol"),
        "group": group.get("name"),
        "sector": group.get("sector"),
        "group_phase": group.get("phase"),
        "pioneer_score": group.get("pioneer_score"),
        "breadth_score": group.get("breadth_score"),
        "structure_score": group.get("structure_score"),
        "priority_score": group.get("priority_score"),
        "structure_state": group.get("structure_state"),
        "structure_label": group.get("structure_label"),
        "strength": stock.get("strength"),
        "role": stock.get("role"),
        "breakout_status": (stock.get("breakout") or {}).get("status"),
        "stock_structure_score": structure.get("score"),
        "status": override_status or entry.get("status"),
        "quality": entry.get("quality"),
        "reason": reason,
    }


def _action_key(item: dict[str, Any]) -> tuple[Any, ...]:
    return (
        BREAKOUT_RANK.get(str(item.get("breakout_status")), 0),
        _num(item.get("priority_score")) or 0.0,
        _num(item.get("quality")) or 0.0,
        _num(item.get("strength")) or 0.0,
    )


def apply_structure_overlay(model: dict[str, Any]) -> dict[str, Any]:
    """Add structure/location context without changing the underlying Leadership engine."""
    out = deepcopy(model)
    groups = [enrich_group(g) for g in list(out.get("groups") or [])]
    groups.sort(key=_group_sort_key, reverse=True)
    out["groups"] = groups

    sectors = []
    for sector in list(out.get("sectors") or []):
        name = str(sector.get("name") or "")
        children = [g for g in groups if str(g.get("sector") or "") == name]
        sectors.append(_sector_overlay(sector, children))
    sectors.sort(
        key=lambda s: (
            PHASE_RANK.get(str(s.get("phase")), 0),
            _num(s.get("priority_score")) or 0.0,
        ),
        reverse=True,
    )
    out["sectors"] = sectors

    market = out.get("market") if isinstance(out.get("market"), dict) else {}
    market_status = str(market.get("status") or "")
    actionable: list[dict[str, Any]] = []
    waiting: list[dict[str, Any]] = []

    for group in groups:
        if str(group.get("phase")) not in {"EMERGING", "LEADING"}:
            continue
        group_structure = _num(group.get("structure_score")) or 0.0
        state = str(group.get("structure_state") or "")
        for stock in list(group.get("stocks") or []):
            if str(stock.get("role")) not in {"PIONEER", "LEADER"}:
                continue
            entry = stock.get("entry") if isinstance(stock.get("entry"), dict) else {}
            status = str(entry.get("status") or "")
            bo_status = str((stock.get("breakout") or {}).get("status") or "")

            structure_blocked = state == "SUPPLY_NEAR" and group_structure < 55.0 and bo_status != "BREAKOUT_NOW"
            if status == "ENTRY" and market_status != "STOP" and not structure_blocked:
                actionable.append(_action_item(group, stock))
            elif status in {"ENTRY", "WAIT", "WATCH"}:
                if structure_blocked and status == "ENTRY":
                    waiting.append(_action_item(
                        group,
                        stock,
                        override_status="WAIT",
                        reason_prefix="グループがSupply直下。突破確認待ち",
                    ))
                else:
                    waiting.append(_action_item(group, stock))

    actionable.sort(key=_action_key, reverse=True)
    waiting.sort(key=_action_key, reverse=True)
    out["actionable"] = actionable[:15]
    out["waiting"] = waiting[:15]

    coverage = out.get("coverage") if isinstance(out.get("coverage"), dict) else {}
    coverage["structure_groups"] = sum(1 for g in groups if _num(g.get("structure_score")) is not None)
    coverage["structure_method"] = "20/50D overhead pivots + 21EMA/50SMA/63VWAP/cleared-pivot demand + breakout absorption"
    out["coverage"] = coverage
    out["schema"] = max(int(out.get("schema") or 0), 5)
    return out
