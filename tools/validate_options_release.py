#!/usr/bin/env python3
"""Fail-closed validation for a complete Options page release.

This validator is deliberately read-only unless --write-manifest is supplied.
It never changes Dashboard/V38/Rotation/Leadership data. It only verifies that
the Options page can be published as one same-session snapshot.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATE = Path("state.json")
DASHBOARD = Path("command-center.html")
RS_LEADERS = Path("options-rs-leaders.json")
ROT_STATUS = Path("rotation/data/status.json")
ROT_CONTEXT = Path("rotation/data/rotation-theme56-stock-context.json")
POSITIONING = Path("options_positioning.json")
DAILY = Path("options_daily_liquid_status.json")
INTELLIGENCE = Path("options_intelligence.json")
CHART = Path("options_chart_data.json")
CHART_HISTORY = Path("options_chart_history")
POSITIONING_HTML = Path("options-positioning.html")


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"{path}: {type(exc).__name__}: {exc}") from exc


def _day(v: Any) -> str:
    return str(v or "")[:10]


def _embedded(path: Path, name: str) -> Any:
    text = path.read_text(encoding="utf-8")
    marker = f"window.{name}="
    start = text.find(marker)
    if start < 0:
        raise RuntimeError(f"{path}: {marker} not found")
    start += len(marker)
    end = text.find(";</script>", start)
    if end < 0:
        raise RuntimeError(f"{path}: terminator for {name} not found")
    return json.loads(text[start:end])


def _ratio(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return -1.0


def expected_session(explicit: str = "") -> str:
    target = _day(explicit)
    if target:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", target):
            raise RuntimeError(f"invalid expected session: {explicit!r}")
        return target
    state = _load(STATE)
    target = _day(state.get("date"))
    if not target:
        raise RuntimeError("state.json has no date")
    return target


def upstream_checks(target: str) -> tuple[list[str], dict[str, Any]]:
    errors: list[str] = []
    meta: dict[str, Any] = {}

    state = _load(STATE)
    state_day = _day(state.get("date"))
    meta["state_asof"] = state_day
    if state_day != target:
        errors.append(f"state={state_day or 'missing'} expected={target}")

    calc = _embedded(DASHBOARD, "CALC")
    dashboard_day = _day(calc.get("asof"))
    meta["dashboard_asof"] = dashboard_day
    if dashboard_day != target:
        errors.append(f"dashboard={dashboard_day or 'missing'} expected={target}")

    rs = _load(RS_LEADERS)
    rs_day = _day(rs.get("asof"))
    meta["rs_leaders_asof"] = rs_day
    if rs_day != target:
        errors.append(f"options-rs-leaders={rs_day or 'missing'} expected={target}")

    rot = _load(ROT_STATUS)
    rot_day = _day(rot.get("asof"))
    meta["rotation_asof"] = rot_day
    meta["rotation_status"] = rot.get("status")
    if str(rot.get("status") or "").upper() != "READY":
        errors.append(f"rotation status={rot.get('status')!r}")
    if rot_day != target:
        errors.append(f"rotation={rot_day or 'missing'} expected={target}")

    ctx = _load(ROT_CONTEXT)
    market = ctx.get("leadership_market") if isinstance(ctx.get("leadership_market"), dict) else {}
    coverage = ctx.get("leadership_coverage") if isinstance(ctx.get("leadership_coverage"), dict) else {}
    market_day = _day(market.get("asof"))
    coverage_day = _day(coverage.get("market_asof"))
    meta["leadership_market_asof"] = market_day
    meta["leadership_coverage_asof"] = coverage_day
    if market_day != target:
        errors.append(f"leadership_market={market_day or 'missing'} expected={target}")
    if coverage_day != target:
        errors.append(f"leadership_coverage={coverage_day or 'missing'} expected={target}")

    return errors, meta


def release_checks(target: str) -> tuple[list[str], dict[str, Any]]:
    errors, meta = upstream_checks(target)

    pos = _load(POSITIONING)
    pos_session = _day(pos.get("session_date"))
    quality = pos.get("quality") if isinstance(pos.get("quality"), dict) else {}
    meta["positioning_session"] = pos_session
    meta["positioning_asof"] = pos.get("asof")
    meta["positioning_quality"] = quality
    if pos_session != target:
        errors.append(f"positioning session={pos_session or 'missing'} expected={target}")
    if quality.get("gate_ok") is not True:
        errors.append(f"positioning quality gate not READY: {quality}")

    bad_fresh: list[str] = []
    fresh_count = 0
    fallback_count = 0
    for ticker, rec in (pos.get("tickers") or {}).items():
        if not isinstance(rec, dict):
            continue
        if rec.get("refresh_failed"):
            fallback_count += 1
            continue
        fresh_count += 1
        pday = _day(rec.get("price_session_date"))
        if pday != target or rec.get("session_consistent") is not True:
            bad_fresh.append(
                f"{ticker}:price={pday or 'missing'} consistent={rec.get('session_consistent')}"
            )
    meta["positioning_fresh_records"] = fresh_count
    meta["positioning_fallback_records"] = fallback_count
    if bad_fresh:
        errors.append("fresh positioning session mismatch: " + ", ".join(bad_fresh[:8]))

    daily = _load(DAILY)
    daily_days = {
        "session_date": _day(daily.get("session_date")),
        "state_asof": _day(daily.get("state_asof")),
        "dashboard_asof": _day(daily.get("dashboard_asof")),
    }
    meta["daily_liquid"] = {
        **daily_days,
        "daily_checked_ratio": daily.get("daily_checked_ratio"),
        "broad_terminal_ratio": daily.get("broad_terminal_ratio"),
        "eligible_total": daily.get("eligible_total"),
        "fresh_options_total": daily.get("fresh_options_total"),
        "unresolved": daily.get("unresolved"),
    }
    for key, value in daily_days.items():
        if value != target:
            errors.append(f"daily_liquid {key}={value or 'missing'} expected={target}")
    if int(daily.get("broad_attempted_unique") or 0) != int(daily.get("broad_requested") or 0):
        errors.append(
            "daily_liquid attempt coverage "
            f"{daily.get('broad_attempted_unique')}/{daily.get('broad_requested')}"
        )
    if _ratio(daily.get("broad_terminal_ratio")) < 0.98:
        errors.append(f"daily_liquid terminal ratio={daily.get('broad_terminal_ratio')}")
    if _ratio(daily.get("daily_checked_ratio")) < 0.98:
        errors.append(f"daily_liquid checked ratio={daily.get('daily_checked_ratio')}")

    intel = _load(INTELLIGENCE)
    intel_session = _day(intel.get("session_date"))
    intel_state = intel.get("state") if isinstance(intel.get("state"), dict) else {}
    meta["intelligence"] = {
        "session_date": intel_session,
        "state_session_date": _day(intel_state.get("session_date")),
        "positioning_asof": intel.get("positioning_asof"),
        "coverage": (intel.get("summary") or {}).get("coverage")
        if isinstance(intel.get("summary"), dict)
        else None,
    }
    if intel_session != target:
        errors.append(f"intelligence session={intel_session or 'missing'} expected={target}")
    if _day(intel_state.get("session_date")) != target:
        errors.append(
            f"intelligence state={_day(intel_state.get('session_date')) or 'missing'} expected={target}"
        )
    if str(intel.get("positioning_asof") or "") != str(pos.get("asof") or ""):
        errors.append("intelligence positioning_asof does not match positioning")

    chart = _load(CHART)
    chart_session = _day(chart.get("session_date"))
    chart_summary = chart.get("summary") if isinstance(chart.get("summary"), dict) else {}
    meta["chart"] = {
        "session_date": chart_session,
        "positioning_asof": chart.get("positioning_asof"),
        **chart_summary,
    }
    if chart_session != target:
        errors.append(f"chart session={chart_session or 'missing'} expected={target}")
    if str(chart.get("positioning_asof") or "") != str(pos.get("asof") or ""):
        errors.append("chart positioning_asof does not match positioning")
    if int(chart_summary.get("failed_without_cache") or 0) != 0:
        errors.append(f"chart failed_without_cache={chart_summary.get('failed_without_cache')}")
    requested = int(chart_summary.get("requested") or 0)
    available = int(chart_summary.get("available") or 0)
    if requested and available != requested:
        errors.append(f"chart availability={available}/{requested}")

    if not CHART_HISTORY.is_dir():
        errors.append("options_chart_history directory missing")
    if not POSITIONING_HTML.is_file() or POSITIONING_HTML.stat().st_size < 1000:
        errors.append("options-positioning.html missing/invalid")

    return errors, meta


def write_manifest(path: Path, target: str, meta: dict[str, Any]) -> None:
    payload = {
        "schema": "options-page-release-1",
        "status": "READY",
        "session_date": target,
        "validated_at": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        **meta,
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("upstream", "release"), required=True)
    parser.add_argument("--expected-session", default="")
    parser.add_argument("--write-manifest", default="")
    args = parser.parse_args()

    try:
        target = expected_session(args.expected_session)
        if args.mode == "upstream":
            errors, meta = upstream_checks(target)
        else:
            errors, meta = release_checks(target)
    except Exception as exc:
        print(f"OPTIONS_RELEASE_VALIDATE_ERROR {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    if errors:
        print(
            "OPTIONS_RELEASE_NOT_READY "
            + json.dumps({"expected": target, "errors": errors, "meta": meta}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 2

    if args.write_manifest:
        write_manifest(Path(args.write_manifest), target, meta)

    print(
        "OPTIONS_RELEASE_READY "
        + json.dumps({"session": target, "meta": meta}, ensure_ascii=False)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
