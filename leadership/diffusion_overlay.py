from __future__ import annotations

from copy import deepcopy
from typing import Any

ENTRY_ORDER = {
    "PULLBACK_RECLAIM": 6,
    "TIGHT_BREAKOUT": 5,
    "WATCH": 4,
    "EXTENDED": 2,
    "WINDOW_CLOSED": 1,
    "NO_DATA": 0,
}


def _num(value: Any) -> float | None:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if x == x and x not in (float("inf"), float("-inf")) else None


def apply_diffusion_overlay(model: dict[str, Any], market_snapshot: dict[str, Any] | None) -> dict[str, Any]:
    out = deepcopy(model)
    snapshot = market_snapshot if isinstance(market_snapshot, dict) else {}
    diffusion = snapshot.get("diffusion") if isinstance(snapshot.get("diffusion"), dict) else {}
    sectors = diffusion.get("sectors") if isinstance(diffusion.get("sectors"), dict) else {}
    stocks = diffusion.get("stocks") if isinstance(diffusion.get("stocks"), dict) else {}
    enabled = str(diffusion.get("status") or "") == "OK"

    for sector in list(out.get("sectors") or []):
        name = str(sector.get("name") or "")
        if name in sectors:
            sector["diffusion"] = deepcopy(sectors[name])

    groups = list(out.get("groups") or [])
    for group in groups:
        sector_name = str(group.get("sector") or "")
        sector_diff = deepcopy(sectors.get(sector_name) or {})
        group["sector_diffusion"] = sector_diff
        early_count = 0
        entry_count = 0
        lead_scores: list[float] = []
        for stock in list(group.get("stocks") or []):
            symbol = str(stock.get("symbol") or "").upper()
            row = stocks.get(symbol)
            if not isinstance(row, dict):
                continue
            stock["diffusion"] = deepcopy(row)
            stock["diffusion_role"] = "EARLY_LEADER" if row.get("early_leader") else None
            if row.get("early_leader"):
                early_count += 1
                score = _num(row.get("lead_score"))
                if score is not None:
                    lead_scores.append(score)
                status = str((row.get("entry") or {}).get("status") or "")
                if status in {"PULLBACK_RECLAIM", "TIGHT_BREAKOUT"}:
                    entry_count += 1
        group["early_leader_count"] = early_count
        group["diffusion_entry_count"] = entry_count
        group["max_lead_score"] = round(max(lead_scores), 1) if lead_scores else None
        group["stocks"] = sorted(
            list(group.get("stocks") or []),
            key=lambda stock: (
                1 if (stock.get("diffusion") or {}).get("early_leader") else 0,
                ENTRY_ORDER.get(str(((stock.get("diffusion") or {}).get("entry") or {}).get("status") or ""), 0),
                _num((stock.get("diffusion") or {}).get("lead_score")) or 0.0,
                _num(stock.get("strength")) or 0.0,
            ),
            reverse=True,
        )

    focus_sectors = [
        {"name": name, **deepcopy(row)}
        for name, row in sectors.items()
        if str(row.get("state") or "") in {"IGNITION", "ACTIVE", "MATURE"}
    ]
    state_order = {"IGNITION": 4, "ACTIVE": 3, "MATURE": 2, "DECAY": 1, "NONE": 0}
    focus_sectors.sort(
        key=lambda row: (
            state_order.get(str(row.get("state") or ""), 0),
            _num(row.get("event_score")) or 0.0,
        ),
        reverse=True,
    )
    candidate_stocks = [
        {"symbol": symbol, **deepcopy(row)}
        for symbol, row in stocks.items()
        if row.get("early_leader")
    ]
    candidate_stocks.sort(
        key=lambda row: (
            ENTRY_ORDER.get(str((row.get("entry") or {}).get("status") or ""), 0),
            _num(row.get("lead_score")) or 0.0,
        ),
        reverse=True,
    )

    out["diffusion"] = {
        "enabled": enabled,
        "method": diffusion.get("method"),
        "uses_stock_capture": diffusion.get("uses_stock_capture"),
        "eventization": diffusion.get("eventization"),
        "cooldown_sessions": diffusion.get("cooldown_sessions"),
        "entry_window_sessions": diffusion.get("entry_window_sessions"),
        "coverage": deepcopy(diffusion.get("coverage") or {}),
        "focus_sectors": focus_sectors,
        "candidate_stocks": candidate_stocks[:30],
    }
    coverage = out.get("coverage") if isinstance(out.get("coverage"), dict) else {}
    coverage["diffusion_enabled"] = enabled
    coverage["diffusion_sectors"] = len(sectors)
    coverage["diffusion_early_leaders"] = len(candidate_stocks)
    coverage["diffusion_method"] = "eventized sector breadth diffusion + pre-ignition stock/sector relative breakout; Stock Capture excluded"
    out["coverage"] = coverage
    out["schema"] = max(int(out.get("schema") or 0), 8)
    return out
