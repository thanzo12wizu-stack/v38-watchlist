#!/usr/bin/env python3
"""Build the isolated V38 audited companion state.

The legacy ``command-center.html`` is read-only input and is never rewritten.
The generated companion deliberately reports unavailable research inputs as
DATA REQUIRED rather than substituting an approximate production rule.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

from v38_rules import (
    attack_rank_score, clinical_biotech_exclusion, market_mode,
    peer_theme_score, select_peer_theme,
)


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


def _load_json(path: Path | None, default):
    if path is None or not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _map_value(blob: dict, ticker: str):
    value = blob.get(ticker)
    if isinstance(value, dict):
        return value.get("value")
    return value


def _revenue_value(blob: dict, ticker: str):
    record = (blob.get("records") or blob).get(ticker, {}) if isinstance(blob, dict) else {}
    if not isinstance(record, dict):
        return record
    # The audited condition is Revenue TTM. An annual value is not silently
    # substituted; absence therefore remains the documented fail-open case.
    for key in ("revenue_ttm", "tv_revenue_ttm"):
        if _finite(record.get(key)):
            return float(record[key])
    return None


def _strict_loo_record(ticker: str, memberships: list[str], live: dict):
    """Validate and score a precomputed strict-LOO record, or fail closed.

    The upstream daily route must calculate components from the full eligible
    universe. This consumer never computes LOO after a Top50 prefilter.
    """
    records = live.get("candidates") if isinstance(live, dict) else None
    record = records.get(ticker) if isinstance(records, dict) else None
    if not isinstance(record, dict) or int(record.get("history_sessions", 0)) < 21:
        return None
    theme_rows = record.get("themes")
    if not isinstance(theme_rows, dict):
        return None
    scores = {}
    components = {}
    for theme in memberships:
        row = theme_rows.get(theme)
        if not isinstance(row, dict):
            continue
        if not all(row.get(key) is True for key in (
            "candidate_excluded_from_return",
            "candidate_excluded_from_acceleration",
            "candidate_excluded_from_breadth21",
        )):
            continue
        try:
            score = peer_theme_score(row["theme_rs63_pct"], row["acceleration20_pct"],
                                     row["breadth21_pct"])
        except (KeyError, TypeError, ValueError):
            continue
        scores[theme] = score
        components[theme] = row
    selected, score = select_peer_theme(scores)
    if selected is None:
        return {"selected": None, "score": None, "components": None}
    return {"selected": selected, "score": score, "components": components[selected]}


def build_state(legacy_html: Path, *, sector_snapshot_path: Path | None = None,
                market_cap_path: Path | None = None, industry_path: Path | None = None,
                revenue_path: Path | None = None, strict_loo_path: Path | None = None) -> dict:
    source = legacy_html.read_text(encoding="utf-8")
    calc = _embedded_json(source, "CALC")
    details = _embedded_json(source, "DET")

    valid50 = [row for row in details.values() if _finite(row.get("v50"))]
    coverage = len(valid50) / len(details) if details else 0.0
    coverage_ok = len(valid50) >= 30 and coverage >= 0.45
    breadth50 = (100 * sum(float(row["v50"]) > 0 for row in valid50) / len(valid50)
                 if valid50 else None)
    mode = market_mode(calc.get("color"), breadth50, coverage_ok)

    snapshot = _load_json(sector_snapshot_path, {})
    s2t = snapshot.get("s2t", {}) if isinstance(snapshot, dict) else {}
    market_caps = _load_json(market_cap_path, {})
    industry_blob = _load_json(industry_path, {})
    industries = industry_blob.get("map", industry_blob) if isinstance(industry_blob, dict) else {}
    revenues = _load_json(revenue_path, {})
    loo_live = _load_json(strict_loo_path, {})

    candidates = []
    for ticker, row in details.items():
        industry_value = row.get("industry")
        if not industry_value and isinstance(industries.get(ticker), list):
            industry_value = industries[ticker][1] if len(industries[ticker]) > 1 else None
        market_cap_value = row.get("market_cap")
        if not _finite(market_cap_value):
            market_cap_value = _map_value(market_caps, ticker)
        revenue_value = row.get("revenue_ttm")
        if not _finite(revenue_value):
            revenue_value = _revenue_value(revenues, ticker)
        bio = clinical_biotech_exclusion(industry_value, market_cap_value, revenue_value)
        eligible = (
            _finite(row.get("px")) and float(row["px"]) >= 5
            and _finite(row.get("dvol")) and float(row["dvol"]) >= 10
            and bool(row.get("ma5020"))
            and _finite(row.get("v200")) and float(row["v200"]) > 0
            and _finite(row.get("rs189")) and float(row["rs189"]) >= 85
            and _finite(row.get("rs")) and float(row["rs"]) >= 85
            and not bio.excluded
        )
        if not eligible:
            continue
        memberships = [str(x) for x in s2t.get(ticker, []) if str(x).strip()]
        loo = _strict_loo_record(ticker, memberships, loo_live)
        loo_ready = loo is not None
        selected = loo.get("selected") if loo_ready else None
        selected_score = loo.get("score") if loo_ready else None
        comp = loo.get("components") if loo_ready else None
        candidates.append({
            "ticker": ticker,
            "price": row.get("px"),
            "rs189": row.get("rs189"),
            "rs63": row.get("rs"),
            # Legacy DET has no complete multi-membership/PIT peer history.
            # Do not mislabel its single display taxonomy as the selected LOO Theme.
            "peer_theme": selected,
            "theme_memberships": memberships,
            "membership_source": "sector_snapshot.json:s2t",
            "legacy_theme_label": row.get("sth"),
            "peer_theme_score": selected_score,
            "theme_rs63": comp.get("theme_rs63_pct") if comp else None,
            "theme_acceleration": comp.get("acceleration20_pct") if comp else None,
            "theme_breadth21": comp.get("breadth21_pct") if comp else None,
            "peer_only_status": "STRICT_LOO" if loo_ready else "DATA_REQUIRED",
            "candidate_exclusion_required": True,
            "candidate_excluded_from_return": True if loo_ready else None,
            "candidate_excluded_from_acceleration": True if loo_ready else None,
            "candidate_excluded_from_breadth21": True if loo_ready else None,
            "theme_selection": "MAX_VALID_MEMBERSHIP_SCORE",
            "missing_theme_neutral_score": 50,
            "attack_score": (attack_rank_score(row.get("rs189"), selected_score)
                             if mode.name == "ATTACK" and loo_ready else None),
            "final_rank": None,
            "eligibility": "ELIGIBLE",
            "clinical_biotech": {
                "industry": industry_value,
                "market_cap": market_cap_value,
                "revenue_ttm": revenue_value,
                "excluded": bio.excluded,
                "revenue_missing_fail_open": bio.revenue_missing_fail_open,
                "reason": bio.reason,
            },
            "entry_status": "NEXT_OPEN_WHEN_CAPACITY",
        })
    # IMPORTANT: all eligible symbols reach strict LOO before any display cap.
    # Top50 is presentation-only and is applied after the full-universe sort.
    all_attack_ready = bool(candidates) and all(row["attack_score"] is not None for row in candidates)
    if mode.name == "ATTACK" and all_attack_ready:
        candidates.sort(key=lambda row: (float(row["attack_score"]), float(row["rs189"])), reverse=True)
    else:
        candidates.sort(key=lambda row: float(row["rs189"]), reverse=True)
    if mode.name == "SELECTIVE":
        for rank, row in enumerate(candidates, 1):
            row["final_rank"] = rank
    elif mode.name == "ATTACK" and all_attack_ready:
        for rank, row in enumerate(candidates, 1):
            row["final_rank"] = rank

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
            "allocation_priority": "GROSS100 RESEARCH CANDIDATE / RESET_TQQQ80_NORMAL_TQQQ_EXTRA",
            "required_route": "tqqq-panic-state.json",
            "fields": ["vix_close", "qqq_sma50_atr_deviation", "qqq_drawdown10",
                       "seed_age_sessions", "rsi4h", "prior_rsi4h", "mc57",
                       "active", "held_sessions", "underlying_target_pct",
                       "reset_desired_pct", "normal_stock_desired_pct"],
        },
        "ranking": {
            "mode": ("RS189_ONLY" if mode.name == "SELECTIVE" else
                     "ATTACK_FINAL_RANK" if mode.name == "ATTACK" and all_attack_ready else
                     "RS189 PREVIEW ONLY / ATTACK FINAL RANK DATA REQUIRED"),
            "note": ("Selective: Stock RS189 only" if mode.name == "SELECTIVE"
                     else "RS189 PREVIEW ONLY. Formal Attack rank requires 21 sessions of strict LOO history for every eligible symbol; LOO is computed before the display Top50 cap."),
            "attack_formula": "0.70 * Stock RS189 + 0.30 * selected LOO Peer Theme Score",
            "peer_theme_formula": "(Theme RS63 pct + 20d Rank Acceleration pct + peer Breadth21) / 3",
            "candidate_exclusion_required_for_all_components": True,
            "multiple_theme_policy": "MAX_VALID_MEMBERSHIP_SCORE",
            "missing_theme_policy": "NEUTRAL_50",
            "membership_source": "sector_snapshot.json:s2t (multiple memberships)",
            "history_min_sessions": 21,
            "full_eligible_count": len(candidates),
            "display_limit_applied_after_full_sort": 50,
            "strict_loo_live_status": "READY" if all_attack_ready else "DATA REQUIRED",
        },
        "candidates": candidates[:50],
        "panic_reset": {"status": "MONITOR / NOT LIVE", "separate_sleeve": True},
        "gross100_allocation": {
            "status": "RESEARCH CANDIDATE / ENGINE IMPLEMENTED / LIVE INPUT DATA REQUIRED",
            "priority": ["RSI_RESET", "TQQQ_PROTECTED_TO_80", "NORMAL_STOCK", "TQQQ_EXTRA"],
            "run_id": 33339918881,
            "artifact_id": 9740224569,
            "workflow_commit": "02c6746e65fe688bcad68d3d76f27fef344b7cab",
            "comparison_period": ["2016-01-04", "2026-03-20"],
            "note": "80% is the protected amount under competition, not a TQQQ cap",
        },
        "rotation_intelligence": {
            "role": "WHERE_ONLY_NOT_A_TRADE_RULE",
            "exact_etf_fund_flow": "DATA REQUIRED",
            "internal_advance_decline": "DATA REQUIRED",
            "internal_obv": "DATA REQUIRED",
            "volume_is_not_fund_flow": True,
        },
        "gross_limit_pct": 100,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--legacy", default="command-center.html")
    parser.add_argument("--out", default="v38-live-state.json")
    parser.add_argument("--sector-snapshot", default="sector_snapshot.json")
    parser.add_argument("--market-cap", default="mktcap.json")
    parser.add_argument("--industry", default="industry_map.json")
    parser.add_argument("--revenue", default="bio_revenue_audit.json")
    parser.add_argument("--strict-loo", default="strict-loo-live.json")
    args = parser.parse_args()
    state = build_state(
        Path(args.legacy), sector_snapshot_path=Path(args.sector_snapshot),
        market_cap_path=Path(args.market_cap), industry_path=Path(args.industry),
        revenue_path=Path(args.revenue), strict_loo_path=Path(args.strict_loo),
    )
    Path(args.out).write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.out}: {state['market']['mode']} / {len(state['candidates'])} candidates")


if __name__ == "__main__":
    main()
