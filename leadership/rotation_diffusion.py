from __future__ import annotations

from copy import deepcopy
from typing import Any

try:
    from leadership.rotation_overlay import apply_rotation_overlay as apply_legacy_rotation
except ModuleNotFoundError:
    from rotation_overlay import apply_rotation_overlay as apply_legacy_rotation

ROTATION_ORDER = {"RISING": 4, "LEADING": 3, "TOPPING": 2, "FADING": 1}
ENTRY_ORDER = {"PULLBACK_RECLAIM": 6, "TIGHT_BREAKOUT": 5, "WATCH": 4, "EXTENDED": 2, "WINDOW_CLOSED": 1, "NO_DATA": 0}


def _num(value: Any) -> float | None:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if x == x and x not in (float("inf"), float("-inf")) else None


def _status(stock: dict[str, Any]) -> tuple[str, str]:
    status = str((((stock.get("diffusion") or {}).get("entry") or {}).get("status")) or "")
    return {
        "PULLBACK_RECLAIM": ("押し目発火", "ENTRY"),
        "TIGHT_BREAKOUT": ("圧縮ブレイク", "ENTRY"),
        "WATCH": ("初押し待ち", "WATCH"),
        "EXTENDED": ("追わない", "EXTENDED"),
        "WINDOW_CLOSED": ("窓終了", "CLOSED"),
        "NO_DATA": ("判定不能", "NO DATA"),
    }.get(status, ("先導株", "EARLY"))


def _leader_item(stock: dict[str, Any]) -> dict[str, Any]:
    jp, en = _status(stock)
    diff = stock.get("diffusion") if isinstance(stock.get("diffusion"), dict) else {}
    entry = diff.get("entry") if isinstance(diff.get("entry"), dict) else {}
    return {
        "symbol": stock.get("symbol"), "name": stock.get("name"), "exchange": stock.get("exchange"),
        "role": "PIONEER", "status": jp, "status_en": en, "strength": stock.get("strength"),
        "prebreakout_score": diff.get("lead_score"), "pivot_gap_pct": entry.get("pivot_gap_pct"),
        "rs63": diff.get("rs63_now") if diff.get("rs63_now") is not None else stock.get("rs63"),
        "rs21": stock.get("rs21"), "acceleration": stock.get("acceleration"), "lead_days": diff.get("lead_days"),
    }


def _reason(group: dict[str, Any], early_count: int, entry_count: int) -> str:
    sec = group.get("sector_diffusion") if isinstance(group.get("sector_diffusion"), dict) else {}
    parts: list[str] = []
    if str(sec.get("state") or "") in {"IGNITION", "ACTIVE", "MATURE", "DECAY"}:
        age = sec.get("event_age")
        parts.append(f"Sector発火 +{age}日" if age is not None else "Sector発火")
    if sec.get("relative_high_5d") is not None:
        delta = sec.get("relative_high_delta_5d")
        d = f"{float(delta):+.0f}pt" if delta is not None else "—"
        parts.append(f"相対高値 {float(sec['relative_high_5d']):.0f}% ({d})")
    if sec.get("leader_density") is not None:
        parts.append(f"Leader {float(sec['leader_density']):.0f}%")
    if early_count:
        parts.append(f"先導株 {early_count}")
    if entry_count:
        parts.append(f"発火 {entry_count}")
    return " · ".join(parts) if parts else str(group.get("rotation_reason") or "")


def apply_diffusion_rotation(model: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(apply_legacy_rotation(model))
    diffusion = out.get("diffusion") if isinstance(out.get("diffusion"), dict) else {}
    if not diffusion.get("enabled"):
        return out

    groups = list(out.get("groups") or [])
    for group in groups:
        sec = group.get("sector_diffusion") if isinstance(group.get("sector_diffusion"), dict) else {}
        sector_state = str(sec.get("state") or "NONE")
        early = [s for s in list(group.get("stocks") or []) if (s.get("diffusion") or {}).get("early_leader")]
        early.sort(key=lambda s: (ENTRY_ORDER.get(str((((s.get("diffusion") or {}).get("entry") or {}).get("status")) or ""), 0), _num((s.get("diffusion") or {}).get("lead_score")) or 0.0), reverse=True)
        entry_count = sum(1 for s in early if str((((s.get("diffusion") or {}).get("entry") or {}).get("status")) or "") in {"PULLBACK_RECLAIM", "TIGHT_BREAKOUT"})
        breadth = _num(group.get("breadth_score")) or 0.0
        legacy_state = str(group.get("rotation_state") or "")
        if sector_state == "IGNITION" and early:
            state = "RISING"
        elif sector_state == "ACTIVE" and early:
            state = "LEADING" if breadth >= 55 else "RISING"
        elif sector_state == "MATURE" and (early or legacy_state in {"LEADING", "TOPPING"}):
            state = "TOPPING"
        elif sector_state == "DECAY" and legacy_state in {"RISING", "LEADING", "TOPPING"}:
            state = "TOPPING"
        else:
            state = "FADING"
        if early:
            legacy_leaders = list(group.get("rotation_leaders") or [])
            early_items = [_leader_item(s) for s in early[:5]]
            seen = {str(x.get("symbol") or "") for x in early_items}
            group["rotation_leaders"] = early_items + [x for x in legacy_leaders if str(x.get("symbol") or "") not in seen][:max(0, 5-len(early_items))]
            group["rotation_leader_symbols"] = [str(x.get("symbol") or "") for x in group["rotation_leaders"] if x.get("symbol")]
        group["rotation_state"] = state
        group["rotation_label"] = {"RISING": "急浮上", "LEADING": "主導中", "TOPPING": "ピークアウト警戒", "FADING": "失速"}[state]
        group["rotation_reason"] = _reason(group, len(early), entry_count)
        group["diffusion_primary"] = True

    groups.sort(key=lambda g: (ROTATION_ORDER.get(str(g.get("rotation_state") or "FADING"), 0), int(g.get("diffusion_entry_count") or 0), int(g.get("early_leader_count") or 0), _num(g.get("max_lead_score")) or 0.0, _num((g.get("sector_diffusion") or {}).get("event_score")) or 0.0, _num(g.get("rotation_score")) or 0.0), reverse=True)
    out["groups"] = groups
    buckets = {"RISING": [], "LEADING": [], "TOPPING": [], "FADING": []}
    for group in groups:
        buckets[str(group.get("rotation_state") or "FADING")].append(group)
    out["rotation"] = {"rising": buckets["RISING"], "leading": buckets["LEADING"], "topping": buckets["TOPPING"], "fading": buckets["FADING"], "focus": (buckets["RISING"] + buckets["LEADING"])[:8]}
    coverage = out.get("coverage") if isinstance(out.get("coverage"), dict) else {}
    coverage["rotation_method"] = "PRIMARY: eventized Sector Diffusion -> pre-ignition Early Leader -> first pullback/tight breakout; legacy scores are tie-break/context only"
    coverage["rotation_groups"] = len(groups)
    out["coverage"] = coverage
    out["view_mode"] = "SECTOR_DIFFUSION_FIRST"
    out["schema"] = max(int(out.get("schema") or 0), 9)
    return out
