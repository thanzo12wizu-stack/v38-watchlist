#!/usr/bin/env python3
"""Build the isolated V38 audited companion state.

The legacy ``command-center.html`` is read-only input and is never rewritten.
The generated companion deliberately reports unavailable research inputs as
DATA REQUIRED rather than substituting an approximate production rule.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from pathlib import Path

from rotation_intelligence import build_rotation_intelligence
from v38_rules import market_mode

BIO_EXCLUDE_INDUSTRIES = {"Biotechnology", "Pharmaceuticals: Other"}
BIO_KEEP_MCAP = 10_000_000_000.0
BIO_REVENUE_MAX = 50_000_000.0


def _embedded_json(source: str, name: str):
    match = re.search(rf"window\.{re.escape(name)}=(.*?);</script>", source, re.S)
    if not match:
        raise ValueError(f"window.{name} was not found")
    return json.loads(match.group(1))


def _finite(value) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _optional_group_payload(path: Path) -> dict:
    """Read an optional exact-data contract; malformed input fails closed."""
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    groups = raw.get("groups")
    if not isinstance(groups, dict):
        return {}
    return {str(name): value for name, value in groups.items() if isinstance(value, dict)}


def _structural_bio_exclusions(universe_csv: Path) -> tuple[set[str], bool]:
    """Reproduce the researched small-clinical-biotech eligibility exclusion.

    Exclude Biotechnology / Pharmaceuticals: Other only when market cap is
    below $10B AND reported TTM revenue is below $50M. Missing revenue is
    fail-open, matching the research/production selection rule. The bool says
    whether a usable universe file was available; callers may use the legacy
    display label only as a compatibility fallback when it was not.
    """
    if not universe_csv.is_file():
        return set(), False
    try:
        with universe_csv.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        if not rows:
            return set(), False
        required = {"シンボル", "業種", "時価総額", "売上高TTM"}
        if not required.issubset(rows[0].keys()):
            return set(), False
        excluded: set[str] = set()
        for row in rows:
            ticker = str(row.get("シンボル") or "").strip().upper()
            industry = str(row.get("業種") or "").strip()
            if not ticker or industry not in BIO_EXCLUDE_INDUSTRIES:
                continue
            mcap = row.get("時価総額")
            revenue = row.get("売上高TTM")
            if not _finite(mcap) or not _finite(revenue):
                continue
            if float(mcap) < BIO_KEEP_MCAP and float(revenue) < BIO_REVENUE_MAX:
                excluded.add(ticker)
        return excluded, True
    except Exception:
        return set(), False


def build_state(legacy_html: Path) -> dict:
    source = legacy_html.read_text(encoding="utf-8")
    calc = _embedded_json(source, "CALC")
    details = _embedded_json(source, "DET")
    try:
        secrot = _embedded_json(source, "SECROT")
    except ValueError:
        secrot = {}

    root = legacy_html.parent
    bio_excluded, structural_bio_metadata_ok = _structural_bio_exclusions(
        root / "universe.csv"
    )
    exact_flows = _optional_group_payload(root / "rotation-flow.json")
    exact_internals = _optional_group_payload(root / "rotation-internals.json")

    valid50 = [row for row in details.values() if _finite(row.get("v50"))]
    coverage = len(valid50) / len(details) if details else 0.0
    coverage_ok = len(valid50) >= 30 and coverage >= 0.45
    breadth50 = (100 * sum(float(row["v50"]) > 0 for row in valid50) / len(valid50)
                 if valid50 else None)
    mode = market_mode(calc.get("color"), breadth50, coverage_ok)

    candidates = []
    for ticker, row in details.items():
        ticker_key = str(ticker).strip().upper()
        if structural_bio_metadata_ok:
            biotech_ok = ticker_key not in bio_excluded
        else:
            # Compatibility fallback only. A single current display taxonomy
            # is not considered equivalent to the researched structural rule.
            biotech_ok = row.get("sth") != "臨床段階・中小型バイオ"
        eligible = (
            _finite(row.get("px")) and float(row["px"]) >= 5
            and _finite(row.get("dvol")) and float(row["dvol"]) >= 10
            and bool(row.get("ma5020"))
            and _finite(row.get("v200")) and float(row["v200"]) > 0
            and _finite(row.get("rs189")) and float(row["rs189"]) >= 85
            and _finite(row.get("rs")) and float(row["rs"]) >= 85
            and biotech_ok
        )
        if not eligible:
            continue
        candidates.append({
            "ticker": ticker,
            "price": row.get("px"),
            "rs189": row.get("rs189"),
            "rs63": row.get("rs"),
            # Legacy DET has no complete multi-membership/PIT peer history.
            # Do not mislabel its single display taxonomy as the selected LOO Theme.
            "peer_theme": None,
            "legacy_theme_label": row.get("sth"),
            "peer_theme_score": None,
            "theme_rs63": None,
            "theme_acceleration": None,
            "theme_breadth21": None,
            "peer_only_status": "DATA_REQUIRED",
            "candidate_exclusion_required": True,
            "candidate_excluded_from_return": None,
            "candidate_excluded_from_acceleration": None,
            "candidate_excluded_from_breadth21": None,
            "theme_selection": "MAX_VALID_MEMBERSHIP_SCORE",
            "missing_theme_neutral_score": 50,
            "final_rank": (row.get("rs189") if mode.name == "SELECTIVE" else None),
            "eligibility": "ELIGIBLE",
            "entry_status": "NEXT_OPEN_WHEN_CAPACITY",
        })
    # Selective can be ranked exactly from the static snapshot. Attack needs
    # historical peer returns and LOO acceleration, which legacy DET lacks.
    candidates.sort(key=lambda row: float(row["rs189"]), reverse=True)
    if mode.name == "SELECTIVE":
        for rank, row in enumerate(candidates, 1):
            row["final_rank"] = rank

    rotation = build_rotation_intelligence(
        details,
        secrot=secrot,
        exact_flows=exact_flows,
        exact_internals=exact_internals,
    )

    return {
        "schema": "v38-live-state-1",
        "source": str(legacy_html.name),
        "asof": calc.get("asof"),
        "market": {
            "nqsar": calc.get("color"),
            "breadth50": round(breadth50, 2) if breadth50 is not None else None,
            "breadth_valid": len(valid50),
            "breadth_universe": len(details),
            "coverage": round(coverage, 4),
            "coverage_ok": coverage_ok,
            "mode": mode.name,
            "reason": mode.reason,
            "new_entry_limit": mode.new_entry_limit,
            "force_exit_next_open": mode.force_exit_next_open,
        },
        "eligibility": {
            "structural_bio_rule": "Biotechnology/Pharmaceuticals: Other AND mcap<$10B AND known revenue<$50M",
            "revenue_missing_policy": "FAIL_OPEN",
            "structural_metadata_status": "LIVE" if structural_bio_metadata_ok else "FALLBACK_LEGACY_LABEL",
            "excluded_count": len(bio_excluded) if structural_bio_metadata_ok else None,
        },
        "normal_tqqq": {
            "status": "CURRENT30 HIERARCHY DATA REQUIRED",
            "strategy": "CURRENT30",
            "normal_exposure_pct": 30,
            "underlying_target_pct": None,
            "note": "30% is the normal exposure inside the existing hierarchy; risk locks and hierarchy can change the target",
        },
        "panic_tqqq": {
            "status": "DATA REQUIRED",
            "candidate": "M30_TOUCH30_F80_D10",
            "floor_pct_when_active": 80,
            "floor_semantics": "max(underlying CURRENT30 hierarchy target, 80%)",
            "seed_age_rule": "age <= 30; seed day = 0",
            "entry_requires_mc57_gte": 20,
            "active_exit_mc57_lt": 20,
            "nqsar_scope": "not a Panic F80 overlay entry gate; underlying CURRENT30 hierarchy may use NQSAR",
            "allocation_priority": "NOT REPRODUCED",
            "required_route": "tqqq-panic-state.json",
            "fields": ["vix_close", "qqq_sma50_atr_deviation", "qqq_drawdown10",
                       "seed_age_sessions", "rsi4h", "prior_rsi4h", "mc57",
                       "active", "held_sessions", "underlying_target_pct",
                       "other_sleeve_exposure_pct"],
        },
        "ranking": {
            "mode": "RS189_ONLY" if mode.name == "SELECTIVE" else "LOO_THEME30_DATA_REQUIRED",
            "note": ("Selective: Stock RS189 only" if mode.name == "SELECTIVE"
                     else "Attack: candidate-excluded peer-only Theme RS63, 20d rank acceleration, and Breadth21; max valid membership; missing Theme uses neutral 50"),
            "attack_formula": "0.70 * Stock RS189 + 0.30 * selected LOO Peer Theme Score",
            "peer_theme_formula": "(Theme RS63 pct + 20d Rank Acceleration pct + peer Breadth21) / 3",
            "candidate_exclusion_required_for_all_components": True,
            "multiple_theme_policy": "MAX_VALID_MEMBERSHIP_SCORE",
            "missing_theme_policy": "NEUTRAL_50",
        },
        "candidates": candidates[:50],
        "rotation_intelligence": rotation,
        "panic_reset": {"status": "MONITOR / NOT LIVE", "separate_sleeve": True},
        "gross_limit_pct": 100,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--legacy", default="command-center.html")
    parser.add_argument("--out", default="v38-live-state.json")
    args = parser.parse_args()
    state = build_state(Path(args.legacy))
    Path(args.out).write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.out}: {state['market']['mode']} / {len(state['candidates'])} candidates")


if __name__ == "__main__":
    main()
