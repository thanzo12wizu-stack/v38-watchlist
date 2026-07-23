from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .portfolio import load_positions
from .research_storage import load_dataset, write_json

RESEARCH_OPERATIONS_POLICY_VERSION = "1.0.0"


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def _list(value: Any) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def _latest_pair(rankings: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, str | None, str | None]:
    if rankings is None or rankings.empty or "date" not in rankings:
        return pd.DataFrame(), pd.DataFrame(), None, None
    work = rankings.copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce")
    dates = sorted(value for value in work["date"].dropna().unique())
    if not dates:
        return pd.DataFrame(), pd.DataFrame(), None, None
    current_date = pd.Timestamp(dates[-1])
    prior_date = pd.Timestamp(dates[-2]) if len(dates) >= 2 else None
    current = work[work["date"] == current_date].copy()
    prior = work[work["date"] == prior_date].copy() if prior_date is not None else work.head(0).copy()
    return (
        current,
        prior,
        current_date.date().isoformat(),
        prior_date.date().isoformat() if prior_date is not None else None,
    )


def _lookup(frame: pd.DataFrame) -> dict[str, pd.Series]:
    if frame.empty or "ticker" not in frame:
        return {}
    result: dict[str, pd.Series] = {}
    ordered = frame.sort_values("research_rank") if "research_rank" in frame else frame
    for _, row in ordered.iterrows():
        ticker = str(row.get("ticker") or "").upper()
        if ticker and ticker not in result:
            result[ticker] = row
    return result


def _event(
    severity: str,
    event_type: str,
    ticker: str,
    title: str,
    detail: str,
    current: pd.Series | None = None,
) -> dict[str, Any]:
    row = current if current is not None else pd.Series(dtype=object)
    return {
        "severity": severity,
        "type": event_type,
        "ticker": ticker,
        "title": title,
        "detail": detail,
        "decision_status": row.get("decision_status"),
        "research_rank": _number(row.get("research_rank")),
        "candidate_archetype": row.get("candidate_archetype"),
        "financial_phase": row.get("financial_phase"),
        "rs_archetype": row.get("rs_archetype"),
        "entry_state": row.get("entry_state"),
    }


def build_research_changes(rankings: pd.DataFrame) -> dict[str, Any]:
    current, prior, current_date, prior_date = _latest_pair(rankings)
    if current.empty:
        return {
            "status": "NO_RANKINGS",
            "policy_version": RESEARCH_OPERATIONS_POLICY_VERSION,
            "current_date": current_date,
            "prior_date": prior_date,
            "events": [],
            "counts": {},
        }
    current_map = _lookup(current)
    prior_map = _lookup(prior)
    events: list[dict[str, Any]] = []
    for ticker, row in current_map.items():
        old = prior_map.get(ticker)
        status = str(row.get("decision_status") or "READY")
        if old is None:
            severity = "HIGH" if status == "ACTIONABLE" else "MEDIUM"
            events.append(
                _event(
                    severity,
                    "NEW_CANDIDATE",
                    ticker,
                    "新規候補",
                    f"{status}として候補プールへ追加",
                    row,
                )
            )
            continue
        old_status = str(old.get("decision_status") or "READY")
        if old_status != status:
            if status == "ACTIONABLE":
                severity, title = "HIGH", "買えるへ格上げ"
            elif status == "AVOID":
                severity, title = "CRITICAL", "避けるへ格下げ"
            else:
                severity, title = "MEDIUM", "判断変更"
            events.append(
                _event(severity, "STATUS_CHANGE", ticker, title, f"{old_status} → {status}", row)
            )
        old_rank = _number(old.get("research_rank"))
        new_rank = _number(row.get("research_rank"))
        if old_rank is not None and new_rank is not None:
            change = old_rank - new_rank
            if change >= 10:
                events.append(
                    _event(
                        "MEDIUM",
                        "RANK_GAIN",
                        ticker,
                        "順位急上昇",
                        f"#{int(old_rank)} → #{int(new_rank)}",
                        row,
                    )
                )
            elif change <= -15:
                events.append(
                    _event(
                        "HIGH",
                        "RANK_DROP",
                        ticker,
                        "順位急低下",
                        f"#{int(old_rank)} → #{int(new_rank)}",
                        row,
                    )
                )
        for column, event_type, label in (
            ("candidate_archetype", "ARCHETYPE_CHANGE", "候補タイプ"),
            ("financial_phase", "FINANCIAL_CHANGE", "財務フェーズ"),
            ("rs_archetype", "RS_CHANGE", "RS状態"),
            ("entry_state", "ENTRY_CHANGE", "Entry状態"),
            ("expectancy_consistency", "EXPECTANCY_CHANGE", "期待値一貫性"),
        ):
            before, after = str(old.get(column) or "—"), str(row.get(column) or "—")
            if before != after:
                severity = (
                    "HIGH"
                    if after
                    in {
                        "DECELERATING",
                        "DILUTING",
                        "FADING_LEADER",
                        "BROKEN",
                        "CONFLICT",
                    }
                    else "LOW"
                )
                events.append(
                    _event(
                        severity,
                        event_type,
                        ticker,
                        f"{label}変化",
                        f"{before} → {after}",
                        row,
                    )
                )
    for ticker, old in prior_map.items():
        if ticker not in current_map:
            events.append(
                _event(
                    "MEDIUM",
                    "DROPPED",
                    ticker,
                    "候補プールから離脱",
                    "最新ランキング上限または候補条件から外れた",
                    old,
                )
            )
    order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    events.sort(
        key=lambda item: (
            order.get(str(item.get("severity")), 9),
            item.get("research_rank") or 9999,
            item.get("ticker") or "",
        )
    )
    counts = (
        pd.Series([event["type"] for event in events], dtype="object")
        .value_counts()
        .to_dict()
        if events
        else {}
    )
    return {
        "status": "OK",
        "policy_version": RESEARCH_OPERATIONS_POLICY_VERSION,
        "current_date": current_date,
        "prior_date": prior_date,
        "event_count": len(events),
        "counts": {str(key): int(value) for key, value in counts.items()},
        "events": events[:100],
    }


def _group_key(row: dict[str, Any]) -> tuple[str, str, int]:
    return (
        str(row.get("candidate_archetype")),
        str(row.get("setup")),
        int(row.get("horizon") or 0),
    )


def _window_groups(
    expectancy: dict[str, Any], years: int
) -> dict[tuple[str, str, int], dict[str, Any]]:
    window = next(
        (
            item
            for item in expectancy.get("windows") or []
            if int(item.get("window_years") or 0) == years
        ),
        None,
    )
    rows = (window or {}).get("groups") or []
    return {
        _group_key(row): row
        for row in rows
        if row.get("group_type") == "archetype_setup"
        and int(row.get("horizon") or 0) == 10
    }


def build_model_health(
    expectancy: dict[str, Any], manifest: dict[str, Any] | None = None
) -> dict[str, Any]:
    manifest = manifest or {}
    primary = _window_groups(expectancy, 8)
    recent = _window_groups(expectancy, 5)
    warnings: list[str] = []
    rows: list[dict[str, Any]] = []
    conflicts = 0
    for key, base in primary.items():
        other = recent.get(key)
        base_edge = _number(base.get("mean_excess_return"))
        recent_edge = _number((other or {}).get("mean_excess_return"))
        conflict = bool(
            base_edge is not None
            and recent_edge is not None
            and np.sign(base_edge) != np.sign(recent_edge)
        )
        conflicts += int(conflict)
        rows.append(
            {
                "candidate_archetype": key[0],
                "setup": key[1],
                "samples_8y": int(base.get("samples") or 0),
                "edge_8y": base_edge,
                "qualification_8y": base.get("qualification"),
                "edge_5y": recent_edge,
                "qualification_5y": (other or {}).get("qualification"),
                "conflict": conflict,
                "max_ticker_share": _number(base.get("max_ticker_share")),
                "max_year_share": _number(base.get("max_year_share")),
                "loyo_positive_rate": _number(base.get("loyo_positive_rate")),
            }
        )
    qualified = sum(row["qualification_8y"] == "QUALIFIED" for row in rows)
    promising = sum(row["qualification_8y"] == "PROMISING" for row in rows)
    conflict_rate = conflicts / len(rows) if rows else None
    walk = [
        row
        for row in expectancy.get("walk_forward") or []
        if int(row.get("horizon") or 0) == 10
        and _number(row.get("test_mean_excess")) is not None
    ]
    walk_positive_rate = (
        float(np.mean([float(row["test_mean_excess"]) > 0 for row in walk]))
        if walk
        else None
    )
    retained_years = expectancy.get("retained_years") or []
    if not primary:
        warnings.append("primary_8y_expectancy_missing")
    if retained_years and len(set(retained_years)) < 5:
        warnings.append("history_under_5_calendar_years")
    if qualified == 0 and promising == 0:
        warnings.append("no_qualified_or_promising_groups")
    if conflict_rate is not None and conflict_rate > .35:
        warnings.append("recent_window_conflict_high")
    if walk_positive_rate is not None and walk_positive_rate < .50:
        warnings.append("walk_forward_positive_rate_low")
    if any((row.get("max_ticker_share") or 0) > .25 for row in rows):
        warnings.append("ticker_concentration_high")
    if any((row.get("max_year_share") or 0) > .50 for row in rows):
        warnings.append("year_concentration_high")
    status = (
        "FAIL"
        if "primary_8y_expectancy_missing" in warnings
        else ("WARN" if warnings else "PASS")
    )
    rows.sort(
        key=lambda item: (
            item["conflict"],
            -(item.get("edge_8y") or -999),
            -item.get("samples_8y", 0),
        )
    )
    return {
        "status": status,
        "policy_version": RESEARCH_OPERATIONS_POLICY_VERSION,
        "primary_window_years": expectancy.get("primary_window_years") or 8,
        "retained_years": retained_years,
        "retained_sample_count": expectancy.get("retained_sample_count")
        or expectancy.get("sample_count")
        or 0,
        "qualified_groups": qualified,
        "promising_groups": promising,
        "conflict_groups": conflicts,
        "conflict_rate": conflict_rate,
        "walk_forward_tests": len(walk),
        "walk_forward_positive_rate": walk_positive_rate,
        "warnings": sorted(set(warnings)),
        "groups": rows[:100],
        "manifest_warnings": manifest.get("warnings") or [],
    }


def build_portfolio_overlay(
    positions: pd.DataFrame, rankings: pd.DataFrame
) -> dict[str, Any]:
    if positions is None or positions.empty:
        return {
            "status": "NO_POSITIONS",
            "policy_version": RESEARCH_OPERATIONS_POLICY_VERSION,
            "position_count": 0,
            "positions": [],
            "counts": {},
        }
    current, _, current_date, _ = _latest_pair(rankings)
    lookup = _lookup(current)
    records: list[dict[str, Any]] = []
    for _, position in positions.iterrows():
        ticker = str(position.get("ticker") or "").upper()
        row = lookup.get(ticker)
        if row is None:
            records.append(
                {
                    "ticker": ticker,
                    "action": "HOLD",
                    "research_status": "UNRANKED",
                    "reasons": ["research_candidate_not_available"],
                    "weight": _number(position.get("weight")),
                    "entry_stage": _number(position.get("entry_stage")),
                }
            )
            continue
        blocks = _list(row.get("hard_blocks"))
        decision = str(row.get("decision_status") or "READY")
        consistency = str(row.get("expectancy_consistency") or "UNAVAILABLE")
        phase = str(row.get("financial_phase") or "DATA_INSUFFICIENT")
        rs_state = str(row.get("rs_archetype") or "UNCLASSIFIED")
        price = _number(row.get("price"))
        cost = _number(position.get("cost_basis"))
        gain_pct = (
            (price / cost - 1) * 100
            if price is not None and cost not in (None, 0)
            else None
        )
        stage = int(_number(position.get("entry_stage")) or 2)
        reasons: list[str] = []
        if (
            "LONG_TREND_BROKEN" in blocks
            or "FUNDAMENTAL_DETERIORATION" in blocks
        ):
            action = "EXIT"
            reasons.append("research_hard_exit")
        elif (
            decision == "AVOID"
            or phase in {"DECELERATING", "MARGIN_PRESSURE", "DILUTING"}
            or rs_state in {"FADING_LEADER", "FALSE_LEADERSHIP"}
        ):
            action = "REDUCE"
            reasons.append("research_deterioration")
        elif (
            stage == 1
            and decision == "ACTIONABLE"
            and consistency in {"CONFIRMED", "PRIMARY_ONLY"}
            and str(row.get("expectancy_status")) in {"QUALIFIED", "PROMISING"}
        ):
            action = "ADD"
            reasons.append("second_entry_supported")
        else:
            action = "HOLD"
            reasons.append("research_thesis_intact")
        if consistency == "CONFLICT":
            if action == "ADD":
                action = "HOLD"
            reasons.append("expectancy_window_conflict")
        if (
            gain_pct is not None
            and gain_pct >= 25
            and not bool(position.get("partial_taken"))
        ):
            reasons.append("partial_profit_due")
        records.append(
            {
                "ticker": ticker,
                "action": action,
                "research_status": decision,
                "research_rank": _number(row.get("research_rank")),
                "candidate_archetype": row.get("candidate_archetype"),
                "financial_phase": phase,
                "rs_archetype": rs_state,
                "entry_state": row.get("entry_state"),
                "expectancy_status": row.get("expectancy_status"),
                "expectancy_consistency": consistency,
                "expected_edge_10d_8y": _number(row.get("expected_edge_10d_8y")),
                "price": price,
                "cost_basis": cost,
                "gain_pct": gain_pct,
                "stop_risk_pct": _number(row.get("stop_risk_pct")),
                "weight": _number(position.get("weight")),
                "entry_stage": stage,
                "partial_taken": bool(position.get("partial_taken")),
                "reasons": reasons,
                "hard_blocks": blocks,
            }
        )
    action_order = {"EXIT": 0, "REDUCE": 1, "ADD": 2, "HOLD": 3}
    records.sort(
        key=lambda item: (
            action_order.get(str(item.get("action")), 9),
            item.get("research_rank") or 9999,
            item.get("ticker") or "",
        )
    )
    counts = (
        pd.Series([row["action"] for row in records], dtype="object")
        .value_counts()
        .to_dict()
    )
    return {
        "status": "OK",
        "policy_version": RESEARCH_OPERATIONS_POLICY_VERSION,
        "asof": current_date,
        "position_count": len(records),
        "counts": {str(key): int(value) for key, value in counts.items()},
        "positions": records,
    }


def run(root: Path, portfolio_path: Path) -> dict[str, Any]:
    rankings = load_dataset(root, "rankings")
    expectancy = _read_json(root / "expectancy.json", {})
    manifest = _read_json(root / "manifest.json", {})
    changes = build_research_changes(rankings)
    health = build_model_health(expectancy, manifest)
    positions = load_positions(portfolio_path)
    overlay = build_portfolio_overlay(positions, rankings)
    write_json(root / "changes.json", changes)
    write_json(root / "model_health.json", health)
    write_json(root / "portfolio_overlay.json", overlay)
    return {
        "changes": changes.get("status"),
        "events": changes.get("event_count", 0),
        "model_health": health.get("status"),
        "portfolio": overlay.get("status"),
        "positions": overlay.get("position_count", 0),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="data/intelligence/research")
    parser.add_argument("--portfolio", default="portfolio.csv")
    args = parser.parse_args()
    print(
        json.dumps(
            run(Path(args.root), Path(args.portfolio)),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
