from __future__ import annotations

import math
from collections import defaultdict

import pandas as pd

THEME_POLICY_VERSION = "1.0.0"


def _num(value, default: float = 0.0) -> float:
    value = pd.to_numeric(value, errors="coerce")
    return default if pd.isna(value) else float(value)


def _label(row: pd.Series) -> tuple[str, str]:
    industry = row.get("industry")
    sector = row.get("sector")
    if pd.notna(industry) and str(industry).strip():
        return str(industry).strip(), "industry"
    if pd.notna(sector) and str(sector).strip():
        return str(sector).strip(), "sector_fallback"
    return "Unknown", "unknown"


def build_theme_intelligence(frame: pd.DataFrame, *, min_members: int = 2, limit: int = 50) -> list[dict]:
    if frame.empty:
        return []
    groups: dict[str, list[pd.Series]] = defaultdict(list)
    sources: dict[str, str] = {}
    for _, row in frame.iterrows():
        label, source = _label(row)
        groups[label].append(row)
        sources[label] = source

    records: list[dict] = []
    for theme, rows in groups.items():
        if len(rows) < min_members:
            continue
        member_count = len(rows)
        rs_strength = sum((_num(r.get("rs_raw_63")) + _num(r.get("rs_raw_126")) + _num(r.get("rs_raw_189"))) / 3 for r in rows) / member_count
        acceleration = sum((_num(r.get("rs_change_raw_63")) + _num(r.get("rs_change_raw_126"))) / 2 for r in rows) / member_count
        breadth = sum(1 for r in rows if _num(r.get("rs_raw_63")) > 0 and _num(r.get("rs_raw_126")) > 0) / member_count
        leader_share = sum(1 for r in rows if _num(r.get("leader_rank_pct")) >= 0.80) / member_count
        entry_ready = sum(1 for r in rows if str(r.get("setup")) in {"PULLBACK", "PRE_BREAKOUT", "BREAKOUT"}) / member_count
        avg_leader = sum(_num(r.get("score_leader")) for r in rows) / member_count
        concentration = max((_num(r.get("score_leader")) for r in rows), default=0.0) / max(sum(_num(r.get("score_leader")) for r in rows), 1e-9)
        strength_component = 1 / (1 + math.exp(-4 * rs_strength))
        acceleration_component = 1 / (1 + math.exp(-6 * acceleration))
        score = (
            0.30 * strength_component
            + 0.20 * acceleration_component
            + 0.20 * breadth
            + 0.15 * leader_share
            + 0.10 * entry_ready
            + 0.05 * avg_leader
        )
        if score >= 0.75 and breadth >= 0.60:
            phase = "LEADING"
        elif acceleration_component >= 0.58 and breadth >= 0.45:
            phase = "EMERGING"
        elif score >= 0.50:
            phase = "IMPROVING"
        elif acceleration_component < 0.45 and breadth < 0.40:
            phase = "WEAKENING"
        else:
            phase = "MIXED"
        ordered = sorted(rows, key=lambda r: (_num(r.get("score_leader")), _num(r.get("score_entry")), str(r.get("ticker"))), reverse=True)
        records.append({
            "theme": theme,
            "source": sources[theme],
            "sector": next((r.get("sector") for r in rows if pd.notna(r.get("sector"))), None),
            "member_count": member_count,
            "score_theme": round(score, 6),
            "phase": phase,
            "rs_strength_raw": round(rs_strength, 6),
            "rs_acceleration_raw": round(acceleration, 6),
            "breadth_positive": round(breadth, 6),
            "leader_share_top20pct": round(leader_share, 6),
            "entry_ready_share": round(entry_ready, 6),
            "leader_concentration": round(concentration, 6),
            "leaders": [str(r.get("ticker")) for r in ordered[:5]],
        })
    return sorted(records, key=lambda x: (-x["score_theme"], x["theme"]))[:limit]


def attach_theme_context(frame: pd.DataFrame, themes: list[dict]) -> pd.DataFrame:
    out = frame.copy()
    mapping = {item["theme"]: item for item in themes}
    theme_names = []
    theme_scores = []
    theme_phases = []
    for _, row in out.iterrows():
        label, _ = _label(row)
        item = mapping.get(label, {})
        theme_names.append(label)
        theme_scores.append(item.get("score_theme"))
        theme_phases.append(item.get("phase"))
    out["theme"] = theme_names
    out["score_theme"] = theme_scores
    out["theme_phase"] = theme_phases
    return out


def apply_theme_context(candidates: list[dict], frame: pd.DataFrame) -> list[dict]:
    lookup = frame.set_index("ticker") if not frame.empty else pd.DataFrame()
    enriched = []
    for candidate in candidates:
        item = dict(candidate)
        ticker = item.get("ticker")
        if not lookup.empty and ticker in lookup.index:
            row = lookup.loc[ticker]
            item["theme"] = row.get("theme")
            item["theme_score"] = row.get("score_theme")
            item["theme_phase"] = row.get("theme_phase")
            if row.get("theme_phase") == "WEAKENING":
                item.setdefault("warnings", []).append("theme_weakening")
            if row.get("theme_phase") in {"LEADING", "EMERGING"}:
                item["theme_confirmed"] = True
            else:
                item["theme_confirmed"] = False
        enriched.append(item)
    return enriched
