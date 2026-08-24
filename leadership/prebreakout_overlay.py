from __future__ import annotations

from copy import deepcopy
from typing import Any


PREBREAKOUT_LABEL_JA = {
    "READY": "発火前READY",
    "COILED": "発火前COILED",
    "WATCH": "発火前監視",
    "NOT_READY": "未形成",
    "ALREADY_BROKE": "発火済み",
    "NO_DATA": "判定データ不足",
}

STATUS_RANK = {"READY": 3, "COILED": 2, "WATCH": 1, "NOT_READY": 0, "ALREADY_BROKE": 0, "NO_DATA": 0}
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


def _pivot_gap(stock: dict[str, Any]) -> float | None:
    """Return nearest unbroken pivot distance as positive pct above current price."""
    gaps: list[float] = []
    for key in ("breakout20_pct", "breakout50_pct"):
        value = _num(stock.get(key))
        if value is not None and value < 0:
            gaps.append(abs(value))
    if not gaps:
        structure = stock.get("structure") if isinstance(stock.get("structure"), dict) else {}
        value = _num(structure.get("supply_distance_pct"))
        if value is not None and value >= 0:
            gaps.append(value)
    return min(gaps) if gaps else None


def _proximity_score(gap: float | None) -> float:
    if gap is None:
        return 15.0
    if gap <= 0.15:
        return 84.0
    if gap <= 1.5:
        return 100.0
    if gap <= 3.0:
        return 92.0
    if gap <= 4.5:
        return 78.0
    if gap <= 6.0:
        return 62.0
    if gap <= 8.0:
        return 42.0
    return 18.0


def _accel_score(accel: float | None) -> float:
    if accel is None:
        return 50.0
    return _clip(50.0 + accel * 4.0)


def stock_prebreakout(stock: dict[str, Any], group: dict[str, Any]) -> dict[str, Any]:
    breakout = stock.get("breakout") if isinstance(stock.get("breakout"), dict) else {}
    bo_status = str(breakout.get("status") or "")
    if bo_status in {"BREAKOUT_NOW", "BREAKOUT_RECENT", "EXTENDED"}:
        return {
            "status": "ALREADY_BROKE",
            "label": PREBREAKOUT_LABEL_JA["ALREADY_BROKE"],
            "score": 0.0,
            "pivot_gap_pct": _pivot_gap(stock),
            "reason": "すでに発火済み。発火前候補からは除外",
        }

    strength = _num(stock.get("strength"))
    rs63 = _num(stock.get("rs63"))
    rs21 = _num(stock.get("rs21"))
    accel = _num(stock.get("acceleration"))
    price = _num(stock.get("price"))
    sma50 = _num(stock.get("sma50"))
    rvol = _num(stock.get("volume_ratio"))
    group_priority = _num(group.get("priority_score"))
    structure = stock.get("structure") if isinstance(stock.get("structure"), dict) else {}
    absorption = _num(structure.get("absorption_score"))
    demand = _num(structure.get("demand_score"))
    dryup = _num(structure.get("volume_dryup_score"))
    structure_score = _num(structure.get("score"))
    gap = _pivot_gap(stock)

    if strength is None or rs63 is None or rs21 is None or price is None:
        return {
            "status": "NO_DATA",
            "label": PREBREAKOUT_LABEL_JA["NO_DATA"],
            "score": None,
            "pivot_gap_pct": gap,
            "reason": "RS・価格・Pivot周辺データ不足",
        }

    if sma50 is not None and price < sma50 * 0.99:
        return {
            "status": "NOT_READY",
            "label": PREBREAKOUT_LABEL_JA["NOT_READY"],
            "score": 20.0,
            "pivot_gap_pct": gap,
            "reason": "50SMA下。発火前候補としては弱い",
        }

    proximity = _proximity_score(gap)
    score = (
        0.25 * proximity
        + 0.20 * strength
        + 0.12 * rs63
        + 0.10 * rs21
        + 0.10 * _accel_score(accel)
        + 0.10 * (absorption if absorption is not None else 50.0)
        + 0.08 * (demand if demand is not None else 50.0)
        + 0.05 * (dryup if dryup is not None else 50.0)
    )
    if group_priority is not None and group_priority >= 75:
        score += 2.5
    if structure_score is not None and structure_score >= 70:
        score += 1.5
    if rvol is not None and rvol > 1.35:
        score -= 5.0
    score = _clip(score)

    role = str(stock.get("role") or "")
    phase = str(group.get("phase") or "")
    active_group = phase in {"EMERGING", "LEADING"}
    leader = role in {"PIONEER", "LEADER"}
    gap_ready = gap is not None and 0.05 <= gap <= 4.0
    gap_coiled = gap is not None and gap <= 6.0
    absorption_ok = (absorption is None or absorption >= 58.0) or (structure_score is not None and structure_score >= 66.0)
    quiet_ok = rvol is None or rvol <= 1.20

    if active_group and leader and gap_ready and strength >= 78 and rs63 >= 78 and score >= 80 and absorption_ok and quiet_ok:
        status = "READY"
    elif active_group and leader and gap_coiled and strength >= 75 and rs63 >= 72 and score >= 70:
        status = "COILED"
    elif active_group and leader and gap is not None and gap <= 8.0 and score >= 62:
        status = "WATCH"
    else:
        status = "NOT_READY"

    reasons: list[str] = []
    if gap is not None:
        reasons.append(f"Pivotまで{gap:.1f}%")
    reasons.append(f"RS63 {rs63:.0f}")
    if accel is not None:
        reasons.append(f"RS加速 {accel:+.1f}")
    if absorption is not None:
        reasons.append(f"Supply吸収 {absorption:.0f}")
    if dryup is not None:
        reasons.append(f"出来高乾き {dryup:.0f}")
    if rvol is not None:
        reasons.append(f"RVOL {rvol:.2f}x")

    return {
        "status": status,
        "label": PREBREAKOUT_LABEL_JA[status],
        "score": round(score, 1),
        "pivot_gap_pct": round(gap, 2) if gap is not None else None,
        "proximity_score": round(proximity, 1),
        "reason": " / ".join(reasons),
    }


def _item(group: dict[str, Any], stock: dict[str, Any]) -> dict[str, Any]:
    pre = stock.get("prebreakout") if isinstance(stock.get("prebreakout"), dict) else {}
    pre_status = str(pre.get("status") or "")
    display_status = "ENTRY" if pre_status == "READY" else "WATCH"
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
        "prebreakout_status": pre_status,
        "prebreakout_label": pre.get("label"),
        "prebreakout_score": pre.get("score"),
        "pivot_gap_pct": pre.get("pivot_gap_pct"),
        "status": display_status,
        "quality": pre.get("score"),
        "reason": f"{pre.get('label')} {pre.get('score')} / {pre.get('reason')}",
    }


def _item_key(item: dict[str, Any]) -> tuple[Any, ...]:
    return (
        STATUS_RANK.get(str(item.get("prebreakout_status")), 0),
        _num(item.get("prebreakout_score")) or 0.0,
        PHASE_RANK.get(str(item.get("group_phase")), 0),
        _num(item.get("priority_score")) or 0.0,
        _num(item.get("strength")) or 0.0,
    )


def apply_prebreakout_overlay(model: dict[str, Any]) -> dict[str, Any]:
    """Make pre-breakout setups the primary Leadership output.

    Confirmed breakouts remain in each stock's breakout field for context, but are
    intentionally removed from the primary candidate lists. The goal is to surface
    leaders before the trigger, not after it.
    """
    out = deepcopy(model)
    groups = list(out.get("groups") or [])
    ready: list[dict[str, Any]] = []
    coiled: list[dict[str, Any]] = []
    confirmed: list[dict[str, Any]] = []

    for group in groups:
        for stock in list(group.get("stocks") or []):
            pre = stock_prebreakout(stock, group)
            stock["prebreakout"] = pre
            status = str(pre.get("status") or "")
            if status == "READY":
                ready.append(_item(group, stock))
            elif status in {"COILED", "WATCH"}:
                coiled.append(_item(group, stock))
            elif status == "ALREADY_BROKE" and str(stock.get("role") or "") in {"PIONEER", "LEADER"}:
                confirmed.append({
                    "symbol": stock.get("symbol"),
                    "group": group.get("name"),
                    "role": stock.get("role"),
                    "breakout_status": (stock.get("breakout") or {}).get("status"),
                    "strength": stock.get("strength"),
                })

    ready.sort(key=_item_key, reverse=True)
    coiled.sort(key=_item_key, reverse=True)
    out["actionable"] = ready[:15]
    out["waiting"] = coiled[:15]
    out["confirmed_breakouts"] = confirmed[:20]

    coverage = out.get("coverage") if isinstance(out.get("coverage"), dict) else {}
    coverage["prebreakout_ready"] = len(ready)
    coverage["prebreakout_watch"] = len(coiled)
    coverage["prebreakout_method"] = "unbroken 20/50D pivot proximity + leader RS + acceleration + supply absorption + nearby demand + dry volume"
    out["coverage"] = coverage
    out["candidate_mode"] = "PRE_BREAKOUT_FIRST"
    out["schema"] = max(int(out.get("schema") or 0), 6)
    return out
