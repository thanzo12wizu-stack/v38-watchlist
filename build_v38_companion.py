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

from v38_rules import (
    NORMAL_STOCK_BUDGET, attack_rank_score, clinical_biotech_exclusion,
    gross100_allocation, market_mode, peer_theme_score, select_peer_theme,
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
    for key in ("revenue_ttm", "tv_revenue_ttm"):
        if _finite(record.get(key)):
            return float(record[key])
    return None


def _load_universe_metadata(path: Path | None) -> dict[str, dict]:
    if path is None or not path.is_file():
        return {}
    out: dict[str, dict] = {}
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                ticker = str(row.get("シンボル") or row.get("symbol") or row.get("Symbol") or "").strip().upper()
                if not ticker:
                    continue
                out[ticker] = {
                    "industry": row.get("業種") or row.get("industry") or row.get("Industry"),
                    "market_cap": row.get("時価総額") or row.get("market_cap") or row.get("Market Cap"),
                    "revenue_ttm": row.get("売上高TTM") or row.get("revenue_ttm") or row.get("Revenue TTM"),
                }
    except OSError:
        return {}
    return out


def _strict_loo_record(ticker: str, memberships: list[str], live: dict):
    if not isinstance(live, dict) or live.get("status") != "READY":
        return None
    if not memberships:
        if (
            int(live.get("history_sessions", 0)) >= 21
            and live.get("history_has_exact_20_session_base") is True
        ):
            return {
                "selected": None,
                "score": None,
                "components": None,
                "readiness": "LOO_READY_NO_VALID_THEME",
            }
        return None
    records = live.get("candidates")
    record = records.get(ticker) if isinstance(records, dict) else None
    if not isinstance(record, dict) or record.get("status") != "READY":
        return None
    if int(record.get("history_sessions", 0)) < 21:
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
        return {
            "selected": None,
            "score": None,
            "components": None,
            "readiness": "LOO_READY_NO_VALID_THEME",
        }
    return {
        "selected": selected,
        "score": score,
        "components": components[selected],
        "readiness": "STRICT_LOO",
    }


def _ready_live(blob: dict, asof: str | None, status_key: str, ready_value: str = "READY") -> bool:
    return (
        isinstance(blob, dict)
        and blob.get(status_key) == ready_value
        and str(blob.get("asof") or "") == str(asof or "")
    )


def _pct(value):
    return float(value) if _finite(value) else None


def build_state(legacy_html: Path, *, sector_snapshot_path: Path | None = None,
                market_cap_path: Path | None = None, industry_path: Path | None = None,
                revenue_path: Path | None = None, universe_path: Path | None = None,
                strict_loo_path: Path | None = None, tqqq_panic_path: Path | None = None,
                sleeve_state_path: Path | None = None) -> dict:
    source = legacy_html.read_text(encoding="utf-8")
    calc = _embedded_json(source, "CALC")
    details = _embedded_json(source, "DET")
    asof = calc.get("asof")

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
    universe_meta = _load_universe_metadata(universe_path)
    loo_live = _load_json(strict_loo_path, {})
    if not _ready_live(loo_live, asof, "status"):
        loo_live = {}
    tqqq_live = _load_json(tqqq_panic_path, {})
    tqqq_ready = _ready_live(tqqq_live, asof, "live_generation_status")
    sleeve_live = _load_json(sleeve_state_path, {})
    sleeve_ready = _ready_live(sleeve_live, asof, "status")
    normal_sleeve = sleeve_live.get("normal_stock", {}) if sleeve_ready else {}
    reset_sleeve = sleeve_live.get("rsi_reset", {}) if sleeve_ready else {}
    sleeve_refresh = sleeve_live.get("refresh", {}) if isinstance(sleeve_live, dict) else {}
    if not isinstance(sleeve_refresh, dict):
        sleeve_refresh = {}
    sleeve_refresh_status = str(sleeve_refresh.get("status") or "")
    sleeve_refresh_stale = "LAST_READY_PRESERVED" in sleeve_refresh_status
    source_label = str(legacy_html.name)
    if sleeve_refresh_stale:
        last_ready = sleeve_refresh.get("last_successful_asof") or sleeve_live.get("asof") or "unknown"
        source_label += f" / ⚠ Sleeve更新失敗・前回READY継続({last_ready})"

    candidates = []
    for ticker, row in details.items():
        meta = universe_meta.get(ticker, {})
        industry_value = meta.get("industry") or row.get("industry")
        if not industry_value and isinstance(industries.get(ticker), list):
            industry_value = industries[ticker][1] if len(industries[ticker]) > 1 else None
        market_cap_value = meta.get("market_cap")
        if not _finite(market_cap_value):
            market_cap_value = row.get("market_cap")
        if not _finite(market_cap_value):
            market_cap_value = _map_value(market_caps, ticker)
        revenue_value = meta.get("revenue_ttm")
        if not _finite(revenue_value):
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
        watch_score = attack_rank_score(row.get("rs189"), selected_score) if loo_ready else None
        candidates.append({
            "ticker": ticker,
            "price": row.get("px"),
            "daily_dollar_volume_m": row.get("dvol"),
            "sma50_gt_sma200": bool(row.get("ma5020")),
            "close_vs_sma200_pct": row.get("v200"),
            "eligibility_checks": {
                "price_gte_5": _finite(row.get("px")) and float(row["px"]) >= 5,
                "dollar_volume_gte_10m": _finite(row.get("dvol")) and float(row["dvol"]) >= 10,
                "sma50_gt_sma200": bool(row.get("ma5020")),
                "close_gt_sma200": _finite(row.get("v200")) and float(row["v200"]) > 0,
                "rs189_gte_85": _finite(row.get("rs189")) and float(row["rs189"]) >= 85,
                "rs63_gte_85": _finite(row.get("rs")) and float(row["rs"]) >= 85,
                "biotech_industry_excluded": bio.excluded,
            },
            "normal_biotech_policy": {
                "industry": industry_value,
                "excluded": bio.excluded,
                "policy": "STRUCTURAL_CLINICAL_BIOTECH_ONLY: targeted industry AND market_cap<10B AND revenue_ttm<50M; missing revenue fail-open",
            },
            "rs189": row.get("rs189"),
            "rs63": row.get("rs"),
            "peer_theme": selected,
            "theme_memberships": memberships,
            "membership_source": "sector_snapshot.json:s2t",
            "legacy_theme_label": row.get("sth"),
            "peer_theme_score": selected_score,
            "theme_rs63": comp.get("theme_rs63_pct") if comp else None,
            "theme_acceleration": comp.get("acceleration20_pct") if comp else None,
            "theme_breadth21": comp.get("breadth21_pct") if comp else None,
            "peer_only_status": (loo.get("readiness") if loo_ready else "DATA_REQUIRED"),
            "candidate_exclusion_required": True,
            "candidate_excluded_from_return": True if loo_ready else None,
            "candidate_excluded_from_acceleration": True if loo_ready else None,
            "candidate_excluded_from_breadth21": True if loo_ready else None,
            "theme_selection": "MAX_VALID_MEMBERSHIP_SCORE",
            "missing_theme_neutral_score": 50,
            "attack_watch_score": watch_score,
            "attack_watch_rank": None,
            "attack_score": watch_score if mode.name == "ATTACK" else None,
            "final_rank": None,
            "eligibility": "ELIGIBLE",
            "clinical_biotech": {
                "industry": industry_value,
                "market_cap": float(market_cap_value) if _finite(market_cap_value) else None,
                "revenue_ttm": float(revenue_value) if _finite(revenue_value) else None,
                "excluded": bio.excluded,
                "revenue_missing_fail_open": bio.revenue_missing_fail_open,
                "reason": bio.reason,
                "metadata_source": "universe.csv" if ticker in universe_meta else "fallback",
            },
            "entry_status": "NEXT_OPEN_WHEN_CAPACITY",
        })
    selective_order = sorted(candidates, key=lambda row: float(row["rs189"]), reverse=True)
    for rank, row in enumerate(selective_order, 1):
        row["selective_watch_rank"] = rank

    all_attack_watch_ready = bool(candidates) and all(
        row["attack_watch_score"] is not None for row in candidates
    )
    attack_order = []
    if all_attack_watch_ready:
        attack_order = sorted(
            candidates,
            key=lambda row: (float(row["attack_watch_score"]), float(row["rs189"])),
            reverse=True,
        )
        for rank, row in enumerate(attack_order, 1):
            row["attack_watch_rank"] = rank

    all_attack_ready = mode.name == "ATTACK" and all_attack_watch_ready
    if mode.name == "SELECTIVE":
        candidates = selective_order
        for row in candidates:
            row["final_rank"] = row["selective_watch_rank"]
    elif mode.name == "ATTACK" and all_attack_ready:
        candidates = attack_order
        for row in candidates:
            row["attack_score"] = row["attack_watch_score"]
            row["final_rank"] = row["attack_watch_rank"]
    elif mode.name in {"STOP", "DEFENSE"} and all_attack_watch_ready:
        candidates = attack_order
    else:
        candidates = selective_order

    current30 = tqqq_live.get("current30", {}) if tqqq_ready else {}
    underlying_pct = _pct(tqqq_live.get("underlying_target_pct")) if tqqq_ready else None
    requested_pct = _pct(tqqq_live.get("requested_target_pct")) if tqqq_ready else None
    reset_desired_pct = _pct(tqqq_live.get("reset_desired_pct")) if tqqq_ready else None
    normal_desired_pct = _pct(tqqq_live.get("normal_stock_desired_pct")) if tqqq_ready else None
    normal_portfolio_desired_pct = (
        min(normal_desired_pct, NORMAL_STOCK_BUDGET * 100.0)
        if normal_desired_pct is not None else None
    )

    gross_live_ready = (
        tqqq_ready and tqqq_live.get("sleeve_live_status") == "READY" and sleeve_ready
        and all(value is not None for value in (requested_pct, reset_desired_pct, normal_desired_pct))
    )
    gross_live = None
    if gross_live_ready:
        gross_live = gross100_allocation(
            reset_desired_pct / 100.0,
            requested_pct / 100.0,
            normal_desired_pct / 100.0,
            market_mode_name=mode.name,
            native_tqqq_target=(underlying_pct / 100.0 if underlying_pct is not None else None),
            apply_selective_fill=True,
        )

    normal_tqqq = {
        "status": "READY" if tqqq_ready and current30.get("status") == "READY" else "CURRENT30 HIERARCHY DATA REQUIRED",
        "strategy": "CURRENT30",
        "normal_exposure_pct": 30,
        "underlying_target_pct": underlying_pct,
        "risk_lock": current30.get("risk_lock") if tqqq_ready else None,
        "slow_lock": current30.get("slow_lock") if tqqq_ready else None,
        "fast_lock": current30.get("fast_lock") if tqqq_ready else None,
        "mc_lock": current30.get("mc_lock") if tqqq_ready else None,
        "sleeve": current30.get("sleeve") if tqqq_ready else None,
        "note": "30% is the normal exposure inside the Stage34 hierarchy; risk locks and hierarchy can change the target",
    }

    panic_tqqq = {
        "status": ("READY / ACTIVE" if tqqq_ready and bool(tqqq_live.get("active"))
                   else "READY / INACTIVE" if tqqq_ready else "DATA REQUIRED"),
        "candidate": "M30_TOUCH30_F80_D10",
        "floor_pct_when_active": 80,
        "floor_semantics": "max(underlying CURRENT30 hierarchy target, 80%)",
        "seed_age_rule": "age <= 30; seed day = 0",
        "entry_requires_mc57_gte": 20,
        "active_exit_mc57_lt": 20,
        "nqsar_scope": "not a Panic F80 overlay entry gate; underlying CURRENT30 hierarchy may use NQSAR",
        "allocation_priority": "GROSS100 LIVE / RESET_TQQQ80_NORMAL_TQQQ_EXTRA_SELECTIVE_FILL",
        "required_route": "tqqq-panic-state.json",
        "asof_match_required": True,
        "vix_close": tqqq_live.get("vix_close") if tqqq_ready else None,
        "qqq_sma50_atr_deviation": tqqq_live.get("qqq_sma50_atr_deviation") if tqqq_ready else None,
        "qqq_drawdown10": tqqq_live.get("qqq_drawdown10") if tqqq_ready else None,
        "seed_age_sessions": tqqq_live.get("seed_age_sessions") if tqqq_ready else None,
        "rsi4h": tqqq_live.get("rsi4h") if tqqq_ready else None,
        "prior_rsi4h": tqqq_live.get("prior_rsi4h") if tqqq_ready else None,
        "touch30_today": tqqq_live.get("touch30_today") if tqqq_ready else None,
        "mc57": tqqq_live.get("mc57") if tqqq_ready else None,
        "active": bool(tqqq_live.get("active")) if tqqq_ready else False,
        "held_sessions": tqqq_live.get("held_sessions") if tqqq_ready else None,
        "underlying_target_pct": underlying_pct,
        "requested_target_pct": requested_pct,
        "fields": ["vix_close", "qqq_sma50_atr_deviation", "qqq_drawdown10",
                   "seed_age_sessions", "rsi4h", "prior_rsi4h", "mc57",
                   "active", "held_sessions", "underlying_target_pct",
                   "reset_desired_pct", "normal_stock_desired_pct"],
    }

    gross_state = {
        "status": (
            "LIVE ALLOCATION READY / LAST READY PRESERVED"
            if gross_live is not None and sleeve_refresh_stale
            else "LIVE ALLOCATION READY" if gross_live is not None
            else "LIVE INPUT DATA REQUIRED"
        ),
        "adoption_status": "ADOPTED_FINAL_SPEC_20260901",
        "priority": [
            "RSI_RESET", "TQQQ_PROTECTED_TO_80", "NORMAL_STOCK_CAPPED_70",
            "TQQQ_NATIVE_EXTRA", "SELECTIVE_TQQQ_FILL_FROM_IDLE_CAPACITY",
        ],
        "selective_fill_rule": "SELECTIVE_FILL_NO_ZERO_OVERRIDE",
        "run_id": 33405477190,
        "artifact_id": 9763251012,
        "workflow_commit": "692fe4d68407138372514fe78bd316587250974a",
        "comparison_period": ["2016-01-04", "2026-03-20"],
        "reset_rule": "RS63_TOP3_RISE30_SIGTOP3",
        "sleeve_live_status": tqqq_live.get("sleeve_live_status") if tqqq_ready else "DATA REQUIRED",
        "sleeve_live_reason": tqqq_live.get("sleeve_live_reason") if tqqq_ready else "TQQQ_LIVE_REQUIRED",
        "sleeve_refresh_status": sleeve_refresh_status or ("FRESH" if sleeve_ready else "UNKNOWN"),
        "sleeve_refresh_attempted_asof": sleeve_refresh.get("attempted_asof"),
        "sleeve_last_successful_asof": sleeve_refresh.get("last_successful_asof"),
        "sleeve_refresh_attempted_at_utc": sleeve_refresh.get("attempted_at_utc"),
        "sleeve_refresh_error": sleeve_refresh.get("error"),
        "sleeve_preserved_previous_ready": bool(sleeve_refresh.get("preserved_previous_ready")),
        "normal_position_count": normal_sleeve.get("position_count") if sleeve_ready else None,
        "reset_position_count": reset_sleeve.get("position_count") if sleeve_ready else None,
        "note": "Reset -> protect native/Panic TQQQ to 80% under competition -> Normal Stock capped at 70% -> native TQQQ extra -> adopted Selective Fill from remaining cash only; native CURRENT30 zero is never overridden",
        "reset_desired_pct": reset_desired_pct,
        "native_tqqq_target_pct": underlying_pct,
        "tqqq_desired_pct": requested_pct,
        "normal_stock_desired_pct": normal_desired_pct,
        "normal_stock_standalone_desired_pct": normal_desired_pct,
        "normal_stock_portfolio_desired_pct": normal_portfolio_desired_pct,
        "normal_stock_max_pct": NORMAL_STOCK_BUDGET * 100.0,
        "reset_allocated_pct": (gross_live.reset_allocated * 100 if gross_live else None),
        "tqqq_protected_pct": (gross_live.tqqq_protected * 100 if gross_live else None),
        "normal_stock_allocated_pct": (gross_live.normal_stock_allocated * 100 if gross_live else None),
        "tqqq_extra_pct": (gross_live.tqqq_extra * 100 if gross_live else None),
        "base_gross_allocated_pct": (gross_live.base_gross_allocated * 100 if gross_live else None),
        "selective_fill_eligible": (gross_live.selective_fill_eligible if gross_live else None),
        "tqqq_selective_fill_pct": (gross_live.selective_fill * 100 if gross_live else None),
        "tqqq_allocated_pct": (gross_live.tqqq_allocated * 100 if gross_live else None),
        "gross_allocated_pct": (gross_live.gross_allocated * 100 if gross_live else None),
        "remaining_capacity_pct": (gross_live.remaining_capacity * 100 if gross_live else None),
    }

    return {
        "schema": "v38-live-state-1",
        "source": source_label,
        "asof": asof,
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
        "normal_tqqq": normal_tqqq,
        "panic_tqqq": panic_tqqq,
        "ranking": {
            "mode": ("RS189_ONLY" if mode.name == "SELECTIVE" else
                     "ATTACK_FINAL_RANK" if mode.name == "ATTACK" and all_attack_ready else
                     "WATCH_RANK_READY / ENTRY_BLOCKED_BY_MODE" if mode.name in {"STOP", "DEFENSE"} and all_attack_watch_ready else
                     "RS189 PREVIEW ONLY / ATTACK FINAL RANK DATA REQUIRED"),
            "note": ("Selective: Stock RS189 only" if mode.name == "SELECTIVE"
                     else "Formal ATTACK rank uses the adopted 70/30 strict-LOO formula." if mode.name == "ATTACK" and all_attack_ready
                     else "Reopening watch rank only. It uses the adopted ATTACK 70/30 formula across the full eligible universe, but current Market Mode still blocks entry." if mode.name in {"STOP", "DEFENSE"} and all_attack_watch_ready
                     else "RS189 PREVIEW ONLY. Formal Attack/watch rank requires READY strict LOO history for every eligible symbol; LOO is computed before the display Top50 cap."),
            "attack_formula": "0.70 * Stock RS189 + 0.30 * selected LOO Peer Theme Score",
            "peer_theme_formula": "(Theme RS63 pct + 20d Rank Acceleration pct + peer Breadth21) / 3",
            "candidate_exclusion_required_for_all_components": True,
            "multiple_theme_policy": "MAX_VALID_MEMBERSHIP_SCORE",
            "missing_theme_policy": "NEUTRAL_50_AT_FINAL_SCORE_ONLY",
            "membership_source": "sector_snapshot.json:s2t (multiple memberships)",
            "history_min_sessions": 21,
            "normal_biotech_policy": "STRUCTURAL_CLINICAL_BIOTECH_ONLY (<10B cap AND <50M revenue; missing revenue fail-open)",
            "full_eligible_count": len(candidates),
            "display_limit_applied_after_full_sort": 50,
            "selective_watch_status": "READY" if bool(candidates) else "DATA REQUIRED",
            "selective_watch_semantics": "STOP/DEFENSE REOPEN TO SELECTIVE: RS189 ONLY; TOP4",
            "selective_reopen_top4": [row["ticker"] for row in selective_order[:4]],
            "attack_watch_status": "READY" if all_attack_watch_ready else "DATA REQUIRED",
            "attack_watch_semantics": "STOP/DEFENSE REOPEN TO ATTACK: 70/30 STRICT LOO; TOP12",
            "attack_reopen_top12": [row["ticker"] for row in attack_order[:12]] if all_attack_watch_ready else [],
            "strict_loo_live_status": "READY" if all_attack_watch_ready else "DATA REQUIRED",
            "strict_loo_source_status": "READY" if loo_live else "DATA REQUIRED",
        },
        "candidates": candidates,
        "panic_reset": {
            "status": ("READY / LIVE" if sleeve_ready and reset_sleeve.get("status") == "READY" else "DATA REQUIRED"),
            "separate_sleeve": True, "strategy": "RS63_TOP3_RISE30_SIGTOP3",
            "slot_pct": 2.9, "max_positions": 4, "max_theme_positions": 2, "hold_sessions": 20,
            "headline_620_723_pf471": "NOT REPRODUCED / NOT USED", "desired_pct": reset_desired_pct,
            "position_count": reset_sleeve.get("position_count") if sleeve_ready else None,
            "positions": [dict(p) for p in reset_sleeve.get("positions", []) if isinstance(p, dict)] if sleeve_ready else [],
            "positions": reset_sleeve.get("positions", []) if sleeve_ready else [],
            "monitor": reset_sleeve.get("monitor", []) if sleeve_ready else [],
            "monitor_summary": reset_sleeve.get("monitor_summary", {}) if sleeve_ready else {},
            "monitor_note": reset_sleeve.get("monitor_note") if sleeve_ready else None,
            "rebuild_policy": reset_sleeve.get("rebuild_policy") if sleeve_ready else None,
            "download_quality": reset_sleeve.get("download_quality") if sleeve_ready else None,
            "note": "Strict reproducible Reset is live. RSI30 proximity bands are monitor-only and do not change the entry rule; old headline metrics remain excluded.",
        },
        "normal_stock_sleeve": {
            "status": normal_sleeve.get("status") if sleeve_ready else "DATA REQUIRED",
            "strategy": normal_sleeve.get("strategy") if sleeve_ready else "PEAK30_PART25_R3",
            "desired_pct": normal_desired_pct,
            "standalone_desired_pct": normal_desired_pct,
            "portfolio_desired_pct": normal_portfolio_desired_pct,
            "portfolio_max_pct": NORMAL_STOCK_BUDGET * 100.0,
            "position_count": normal_sleeve.get("position_count") if sleeve_ready else None,
            "positions": normal_sleeve.get("positions", []) if sleeve_ready else [],
            "pending": normal_sleeve.get("pending", {}) if sleeve_ready else {},
        },
        "gross100_allocation": gross_state,
        "rotation_intelligence": {
            "role": "WHERE_ONLY_NOT_A_TRADE_RULE",
            "exact_etf_fund_flow": "DATA REQUIRED",
            "internal_advance_decline": "DATA REQUIRED",
            "internal_obv": "DATA REQUIRED",
            "macro_live": "DATA REQUIRED",
            "transition_history": "DATA REQUIRED",
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
    parser.add_argument("--revenue", default=None)
    parser.add_argument("--universe", default="universe.csv")
    parser.add_argument("--strict-loo", default="v38-strict-loo-live.json")
    parser.add_argument("--tqqq-panic", default="tqqq-panic-state.json")
    parser.add_argument("--sleeve-state", default="v38-sleeve-state.json")
    args = parser.parse_args()
    state = build_state(
        Path(args.legacy), sector_snapshot_path=Path(args.sector_snapshot),
        market_cap_path=Path(args.market_cap), industry_path=Path(args.industry),
        revenue_path=Path(args.revenue) if args.revenue else None,
        universe_path=Path(args.universe), strict_loo_path=Path(args.strict_loo),
        tqqq_panic_path=Path(args.tqqq_panic), sleeve_state_path=Path(args.sleeve_state),
    )
    Path(args.out).write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.out}: {state['market']['mode']} / {len(state['candidates'])} candidates")


if __name__ == "__main__":
    main()
