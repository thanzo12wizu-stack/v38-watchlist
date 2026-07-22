from __future__ import annotations

import math
import os
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

import pandas as pd

THEME_POLICY_VERSION = "1.2.1"


def _num(value, default: float = 0.0) -> float:
    value = pd.to_numeric(value, errors="coerce")
    return default if pd.isna(value) else float(value)


def _score_unit(value) -> float:
    """Normalize the engine's 0..100 score scale for 0..1 aggregations."""
    return min(max(_num(value) / 100.0, 0.0), 1.0)


@lru_cache(maxsize=4)
def _load_taxonomy(path_text: str) -> dict[str, list[dict[str, str]]]:
    path = Path(path_text)
    if not path.exists():
        return {}
    try:
        frame = pd.read_csv(path)
    except Exception:
        return {}
    required = {"ticker", "theme"}
    if not required.issubset(frame.columns):
        return {}
    frame = frame.copy()
    frame["ticker"] = frame["ticker"].astype(str).str.upper().str.strip()
    result: dict[str, list[dict[str, str]]] = defaultdict(list)
    seen: set[tuple[str, str]] = set()
    for _, row in frame.iterrows():
        ticker = str(row.get("ticker") or "").upper().strip()
        theme = str(row.get("theme") or "").strip()
        if not ticker or not theme or (ticker, theme) in seen:
            continue
        seen.add((ticker, theme))
        result[ticker].append(
            {
                "theme": theme,
                "theme_ja": str(row.get("theme_ja") or theme).strip(),
                "sector_hint": str(row.get("sector_hint") or "").strip(),
            }
        )
    return dict(result)


def taxonomy_path() -> Path:
    return Path(os.getenv("V38_THEME_TAXONOMY", "data/theme_taxonomy.csv"))


def _labels(row: pd.Series) -> list[tuple[str, str, str | None]]:
    ticker = str(row.get("ticker") or "").upper().strip()
    mapped = _load_taxonomy(str(taxonomy_path())).get(ticker) or []
    if mapped:
        return [
            (item["theme"], "curated_ticker", item.get("theme_ja"))
            for item in mapped
        ]
    industry = row.get("industry")
    sector = row.get("sector")
    if pd.notna(industry) and str(industry).strip():
        label = str(industry).strip()
        return [(label, "industry", label)]
    if pd.notna(sector) and str(sector).strip():
        label = str(sector).strip()
        return [(label, "sector_fallback", label)]
    return [("Unknown", "unknown", "不明")]


def _label(row: pd.Series) -> tuple[str, str, str | None]:
    """Backward-compatible primary label helper."""
    return _labels(row)[0]


def _phase(score: float, breadth: float, acceleration_component: float, concentration: float) -> str:
    if score >= .76 and breadth >= .65 and acceleration_component >= .52:
        return "LEADING"
    if score >= .66 and acceleration_component >= .62 and breadth >= .48:
        return "ACCELERATING"
    if acceleration_component >= .58 and breadth >= .42:
        return "EMERGING"
    if score >= .58 and acceleration_component < .52:
        return "MATURE"
    if score < .34 and breadth < .30:
        return "BROKEN"
    if acceleration_component < .43 and breadth < .42:
        return "WEAKENING"
    if concentration >= .70 and breadth < .45:
        return "WEAKENING"
    return "IMPROVING"


def build_theme_intelligence(frame: pd.DataFrame, *, min_members: int = 2, limit: int = 50) -> list[dict]:
    if frame.empty:
        return []
    groups: dict[str, list[pd.Series]] = defaultdict(list)
    sources: dict[str, str] = {}
    labels_ja: dict[str, str] = {}
    group_tickers: dict[str, set[str]] = defaultdict(set)
    for _, row in frame.iterrows():
        ticker = str(row.get("ticker") or "").upper().strip()
        for label, source, label_ja in _labels(row):
            if ticker and ticker in group_tickers[label]:
                continue
            groups[label].append(row)
            if ticker:
                group_tickers[label].add(ticker)
            sources[label] = source
            labels_ja[label] = label_ja or label

    records: list[dict] = []
    for theme, rows in groups.items():
        required_members = 1 if sources[theme] == "curated_ticker" else min_members
        if len(rows) < required_members:
            continue
        member_count = len(rows)
        rs_strength = sum((_num(r.get("rs_raw_63")) + _num(r.get("rs_raw_126")) + _num(r.get("rs_raw_189"))) / 3 for r in rows) / member_count
        acceleration = sum((_num(r.get("rs_change_raw_63")) + _num(r.get("rs_change_raw_126"))) / 2 for r in rows) / member_count
        breadth = sum(1 for r in rows if _num(r.get("rs_raw_63")) > 0 and _num(r.get("rs_raw_126")) > 0) / member_count
        leader_share = sum(1 for r in rows if _num(r.get("leader_rank_pct")) >= 80.0) / member_count
        entry_ready = sum(1 for r in rows if str(r.get("setup")) in {"PULLBACK", "PRE_BREAKOUT", "BREAKOUT"}) / member_count
        avg_leader = sum(_score_unit(r.get("score_leader")) for r in rows) / member_count
        leader_total = sum(max(_num(r.get("score_leader")), 0.0) for r in rows)
        concentration = max((max(_num(r.get("score_leader")), 0.0) for r in rows), default=0.0) / max(leader_total, 1e-9)
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
        phase = _phase(score, breadth, acceleration_component, concentration)
        ordered = sorted(
            rows,
            key=lambda r: (_num(r.get("score_leader")), _num(r.get("score_entry")), str(r.get("ticker"))),
            reverse=True,
        )
        records.append(
            {
                "theme": theme,
                "theme_ja": labels_ja[theme],
                "source": sources[theme],
                "sector": next((r.get("sector") for r in rows if pd.notna(r.get("sector"))), None),
                "member_count": member_count,
                "score_theme": round(score, 6),
                "phase": phase,
                "rs_strength_raw": round(rs_strength, 6),
                "rs_acceleration_raw": round(acceleration, 6),
                "acceleration_component": round(acceleration_component, 6),
                "breadth_positive": round(breadth, 6),
                "leader_share_top20pct": round(leader_share, 6),
                "entry_ready_share": round(entry_ready, 6),
                "leader_concentration": round(concentration, 6),
                "leaders": [str(r.get("ticker")) for r in ordered[:5]],
            }
        )
    return sorted(records, key=lambda x: (-x["score_theme"], x["theme"]))[:limit]


def attach_theme_context(frame: pd.DataFrame, themes: list[dict]) -> pd.DataFrame:
    out = frame.copy()
    mapping = {item["theme"]: item for item in themes}
    theme_names = []
    theme_names_ja = []
    theme_scores = []
    theme_phases = []
    all_themes = []
    all_themes_ja = []
    all_phases = []
    for _, row in out.iterrows():
        labels = _labels(row)
        options = []
        for label, _, label_ja in labels:
            item = mapping.get(label, {})
            options.append(
                {
                    "theme": label,
                    "theme_ja": item.get("theme_ja") or label_ja or label,
                    "score_theme": item.get("score_theme"),
                    "phase": item.get("phase"),
                }
            )
        options.sort(
            key=lambda item: (
                item.get("score_theme") is None,
                -float(item.get("score_theme") or 0.0),
                str(item["theme"]),
            )
        )
        primary = options[0]
        theme_names.append(primary["theme"])
        theme_names_ja.append(primary["theme_ja"])
        theme_scores.append(primary.get("score_theme"))
        theme_phases.append(primary.get("phase"))
        all_themes.append([item["theme"] for item in options])
        all_themes_ja.append([item["theme_ja"] for item in options])
        all_phases.append([item["phase"] for item in options if item.get("phase")])
    out["theme"] = theme_names
    out["theme_ja"] = theme_names_ja
    out["score_theme"] = theme_scores
    out["theme_phase"] = theme_phases
    out["themes"] = all_themes
    out["themes_ja"] = all_themes_ja
    out["theme_phases"] = all_phases
    return out


def apply_theme_context(candidates: list[dict], frame: pd.DataFrame) -> list[dict]:
    lookup = frame.set_index("ticker") if not frame.empty else pd.DataFrame()
    enriched = []
    for candidate in candidates:
        item = dict(candidate)
        ticker = item.get("ticker")
        if not lookup.empty and ticker in lookup.index:
            row = lookup.loc[ticker]
            if isinstance(row, pd.DataFrame):
                row = row.iloc[0]
            phases = row.get("theme_phases")
            if not isinstance(phases, list):
                phases = [row.get("theme_phase")] if row.get("theme_phase") else []
            item["theme"] = row.get("theme")
            item["theme_ja"] = row.get("theme_ja") or row.get("theme")
            item["themes"] = row.get("themes") if isinstance(row.get("themes"), list) else [row.get("theme")]
            item["themes_ja"] = row.get("themes_ja") if isinstance(row.get("themes_ja"), list) else [item["theme_ja"]]
            item["theme_score"] = row.get("score_theme")
            item["theme_phase"] = row.get("theme_phase")
            item["theme_phases"] = phases
            if phases and all(phase in {"WEAKENING", "BROKEN"} for phase in phases):
                item.setdefault("warnings", []).append("theme_weakening")
            item["theme_confirmed"] = any(phase in {"LEADING", "ACCELERATING", "EMERGING"} for phase in phases)
        enriched.append(item)
    return enriched
