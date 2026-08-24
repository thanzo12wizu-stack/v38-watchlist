from __future__ import annotations

from copy import deepcopy
from typing import Any

ROTATION_JA = {"RISING": "急浮上", "LEADING": "主導中", "TOPPING": "ピークアウト警戒", "FADING": "失速"}
ROTATION_ORDER = {"RISING": 4, "LEADING": 3, "TOPPING": 2, "FADING": 1}


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


def _clip(value: float) -> float:
    return max(0.0, min(100.0, value))


def _momentum_score(top_accel: float | None, positive_share: float | None) -> float:
    accel = 50.0 if top_accel is None else _clip(50.0 + top_accel * 3.5)
    spread = 50.0 if positive_share is None else _clip(positive_share)
    return _clip(0.70 * accel + 0.30 * spread)


def _direction(top_accel: float | None, positive_share: float | None) -> tuple[str, str]:
    accel = top_accel if top_accel is not None else 0.0
    spread = positive_share if positive_share is not None else 50.0
    if accel >= 8 and spread >= 55:
        return "↑", "加速"
    if accel >= 3 and spread >= 45:
        return "↗", "上向き"
    if accel > -3 and spread >= 40:
        return "→", "維持"
    if accel > -8:
        return "↘", "鈍化"
    return "↓", "減速"


def _breadth_label(positive_share: float | None, breadth: float | None) -> str:
    if positive_share is None and breadth is None:
        return "広がり不明"
    p = positive_share if positive_share is not None else 50.0
    b = breadth if breadth is not None else 50.0
    if p >= 65 and b >= 62:
        return "広がり拡大"
    if p >= 45 and b >= 55:
        return "広がり維持"
    return "広がり弱い"


def _structure_label(group: dict[str, Any]) -> str:
    state = str(group.get("structure_state") or "")
    return {"CLEAR": "上値余地あり", "ABSORBING": "上値抵抗を吸収中", "DEMAND_SUPPORTED": "下値支持あり", "SUPPLY_NEAR": "上値抵抗直下", "MIXED": "構造は中立", "NO_DATA": "構造データ不足"}.get(state, str(group.get("structure_label") or "構造は中立"))


def _leader_status(stock: dict[str, Any]) -> tuple[str, str]:
    pre = stock.get("prebreakout") if isinstance(stock.get("prebreakout"), dict) else {}
    status = str(pre.get("status") or "")
    if status == "READY":
        return "発火目前", "READY"
    if status == "COILED":
        return "あと一歩", "COILED"
    if status == "WATCH":
        return "監視", "WATCH"
    if status == "ALREADY_BROKE":
        return "発火済み", "TRIGGERED"
    bo = str((stock.get("breakout") or {}).get("status") or "")
    if bo in {"BREAKOUT_NOW", "BREAKOUT_RECENT"}:
        return "発火済み", "TRIGGERED"
    return "形成中", "BUILDING"


def _leader_item(stock: dict[str, Any]) -> dict[str, Any]:
    pre = stock.get("prebreakout") if isinstance(stock.get("prebreakout"), dict) else {}
    jp, en = _leader_status(stock)
    return {"symbol": stock.get("symbol"), "name": stock.get("name"), "exchange": stock.get("exchange"), "role": stock.get("role"), "status": jp, "status_en": en, "strength": stock.get("strength"), "prebreakout_score": pre.get("score"), "pivot_gap_pct": pre.get("pivot_gap_pct"), "rs63": stock.get("rs63"), "rs21": stock.get("rs21"), "acceleration": stock.get("acceleration")}


def enrich_rotation_group(group: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(group)
    pioneer = _num(out.get("pioneer_score")) or 0.0
    breadth = _num(out.get("breadth_score")) or 0.0
    top_accel = _num(out.get("top_acceleration"))
    if top_accel is None:
        top_accel = _num(out.get("acceleration"))
    positive_share = _num(out.get("positive_accel_share"))
    structure = _num(out.get("structure_score"))
    priority = _num(out.get("priority_score"))
    momentum = _momentum_score(top_accel, positive_share)

    leaders = [s for s in list(out.get("stocks") or []) if str(s.get("role") or "") in {"PIONEER", "LEADER"}]
    ready_count = 0
    coiled_count = 0
    for stock in leaders:
        status = str((stock.get("prebreakout") or {}).get("status") or "")
        ready_count += int(status == "READY")
        coiled_count += int(status == "COILED")

    setup_score = _clip(50.0 + min(ready_count, 3) * 12.0 + min(coiled_count, 4) * 5.0)
    rotation_score = _clip(0.32 * pioneer + 0.25 * breadth + 0.23 * momentum + 0.10 * (structure if structure is not None else 50.0) + 0.10 * setup_score)
    if priority is not None:
        rotation_score = _clip(0.85 * rotation_score + 0.15 * priority)

    phase = str(out.get("phase") or "")
    med_accel = _num(out.get("acceleration")) or 0.0
    if phase == "EMERGING" and pioneer >= 68 and (top_accel or 0.0) >= 2:
        state = "RISING"
    elif phase == "LEADING" and breadth >= 58 and (top_accel or 0.0) >= -4:
        state = "LEADING"
    elif phase == "MATURE" or (breadth >= 55 and ((top_accel or 0.0) < -4 or med_accel < -3)):
        state = "TOPPING"
    else:
        state = "FADING"

    arrow, direction = _direction(top_accel, positive_share)
    breadth_text = _breadth_label(positive_share, breadth)
    structure_text = _structure_label(out)
    leader_items = [_leader_item(s) for s in leaders[:5]]
    reason = [f"{arrow} {direction}", breadth_text]
    if ready_count:
        reason.append(f"発火目前 {ready_count}")
    elif coiled_count:
        reason.append(f"あと一歩 {coiled_count}")
    reason.append(structure_text)

    out.update({"rotation_state": state, "rotation_label": ROTATION_JA[state], "rotation_score": round(rotation_score, 1), "rotation_arrow": arrow, "rotation_direction": direction, "rotation_momentum": round(momentum, 1), "rotation_breadth_label": breadth_text, "rotation_structure_label": structure_text, "prebreakout_ready": ready_count, "prebreakout_coiled": coiled_count, "rotation_leaders": leader_items, "rotation_leader_symbols": [str(x.get("symbol") or "") for x in leader_items if x.get("symbol")], "rotation_reason": " · ".join(reason)})
    return out


def apply_rotation_overlay(model: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(model)
    groups = [enrich_rotation_group(g) for g in list(out.get("groups") or [])]
    groups.sort(key=lambda g: (ROTATION_ORDER.get(str(g.get("rotation_state")), 0), _num(g.get("rotation_score")) or 0.0, _num(g.get("pioneer_score")) or 0.0), reverse=True)
    out["groups"] = groups
    buckets = {"RISING": [], "LEADING": [], "TOPPING": [], "FADING": []}
    for group in groups:
        buckets[str(group.get("rotation_state") or "FADING")].append(group)
    out["rotation"] = {"rising": buckets["RISING"], "leading": buckets["LEADING"], "topping": buckets["TOPPING"], "fading": buckets["FADING"], "focus": (buckets["RISING"] + buckets["LEADING"])[:8]}
    coverage = out.get("coverage") if isinstance(out.get("coverage"), dict) else {}
    coverage["rotation_groups"] = len(groups)
    coverage["rotation_method"] = "granular Industry Group pioneer + breadth + RS acceleration + structure + pre-breakout leader readiness"
    out["coverage"] = coverage
    out["view_mode"] = "SECTOR_ROTATION_FIRST"
    out["schema"] = max(int(out.get("schema") or 0), 7)
    return out
