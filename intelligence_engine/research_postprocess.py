from __future__ import annotations

import argparse
import json
from bisect import bisect_left
from pathlib import Path
from typing import Any

import pandas as pd

from .prices import load_price_map
from .research_contracts import RESEARCH_RETENTION_YEARS, ResearchConfig
from .research_expectancy import build_research_expectancy
from .research_pipeline import legacy
from .research_storage import load_dataset, upsert_year_partitions, write_json

KEYS = ("ticker", "date", "candidate_archetype", "setup")


def _sessions(price_path: Path) -> list[pd.Timestamp]:
    prices = load_price_map(price_path)
    qqq = prices.get("QQQ")
    if qqq is None or qqq.empty:
        raise RuntimeError("QQQ sessions are unavailable for learning-event normalization")
    index = pd.DatetimeIndex(qqq.index)
    if index.tz is not None:
        index = index.tz_convert(None)
    return sorted(pd.Timestamp(value).normalize() for value in index.unique())


def _session_number(value: Any, sessions: list[pd.Timestamp]) -> int | None:
    date = pd.to_datetime(value, errors="coerce")
    if pd.isna(date):
        return None
    normalized = pd.Timestamp(date).normalize()
    position = bisect_left(sessions, normalized)
    if position >= len(sessions) or sessions[position] != normalized:
        return None
    return position


def select_learning_events(
    signals: pd.DataFrame,
    sessions: list[pd.Timestamp],
    *,
    cooldown_sessions: int = 5,
) -> pd.DataFrame:
    """Keep the first occurrence, then require a trading-session cooldown.

    Daily signals remain stored for display. Only the returned event set is used
    for forward labels and expectancy, preventing a multi-day setup from being
    counted repeatedly merely because it stayed visible.
    """
    if signals is None or signals.empty:
        return pd.DataFrame(columns=list(signals.columns) if signals is not None else [])
    missing = [column for column in KEYS if column not in signals]
    if missing:
        raise ValueError(f"learning-event keys are missing: {missing}")

    work = signals.copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce")
    work = work.dropna(subset=["date", "ticker"]).sort_values(list(KEYS))
    work["_session"] = work["date"].map(lambda value: _session_number(value, sessions))
    work = work.dropna(subset=["_session"])
    work["_session"] = work["_session"].astype(int)

    selected_indexes: list[int] = []
    group_columns = ["ticker", "candidate_archetype", "setup"]
    for _, group in work.groupby(group_columns, dropna=False, sort=False):
        last_selected: int | None = None
        for index, row in group.sort_values(["_session", "date"]).iterrows():
            current = int(row["_session"])
            if last_selected is None or current - last_selected >= max(1, int(cooldown_sessions)):
                selected_indexes.append(index)
                last_selected = current

    selected = work.loc[selected_indexes].drop(columns=["_session"], errors="ignore")
    return selected.sort_values(["date", "ticker", "candidate_archetype", "setup"]).reset_index(drop=True)


def _filter_outcomes(outcomes: pd.DataFrame, learning_events: pd.DataFrame) -> pd.DataFrame:
    if outcomes is None or outcomes.empty or learning_events.empty:
        return pd.DataFrame(columns=list(outcomes.columns) if outcomes is not None else [])
    left = outcomes.copy()
    right = learning_events[list(KEYS)].copy()
    left["date"] = pd.to_datetime(left["date"], errors="coerce")
    right["date"] = pd.to_datetime(right["date"], errors="coerce")
    right = right.drop_duplicates(list(KEYS))
    return left.merge(right.assign(_learning_sample=True), on=list(KEYS), how="inner").drop(
        columns=["_learning_sample"], errors="ignore"
    )


def _qualified_count(expectancy: dict[str, Any]) -> int:
    return sum(
        1
        for window in expectancy.get("windows", [])
        for row in window.get("groups", [])
        if row.get("qualification") == "QUALIFIED"
    )


def run(
    *,
    root: Path,
    price_path: Path,
    years: int = RESEARCH_RETENTION_YEARS,
    min_samples: int = 40,
    cooldown_sessions: int = 5,
) -> dict[str, Any]:
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    config = ResearchConfig(root=root, years=max(RESEARCH_RETENTION_YEARS, years), min_samples=min_samples)
    sessions = _sessions(price_path)
    signals = load_dataset(root, "signals")
    outcomes = load_dataset(root, "outcomes")
    learning_events = select_learning_events(signals, sessions, cooldown_sessions=cooldown_sessions)
    learning_outcomes = _filter_outcomes(outcomes, learning_events)

    expectancy = build_research_expectancy(
        learning_outcomes,
        horizons=config.horizons,
        min_samples=config.min_samples,
        bootstrap_samples=config.bootstrap_samples,
        seed=config.seed,
        analysis_windows=config.analysis_windows,
        primary_window_years=config.primary_window_years,
    )
    ranked = legacy._point_in_time_rankings(signals, learning_outcomes, config)
    reference = pd.to_datetime(manifest.get("end_date"), errors="coerce")
    if pd.isna(reference):
        reference = pd.Timestamp(sessions[-1])
    ranking_result = (
        upsert_year_partitions(
            root,
            "rankings",
            ranked,
            date_column="date",
            keys=KEYS,
            retention_years=config.years,
            reference_date=pd.Timestamp(reference),
        )
        if not ranked.empty
        else {"rows": 0, "partitions": 0}
    )

    source_rows = int(len(signals))
    event_rows = int(len(learning_events))
    outcome_rows = int(len(learning_outcomes))
    sampling = {
        "policy": "first_occurrence_then_trading_session_cooldown",
        "cooldown_sessions": int(cooldown_sessions),
        "display_signal_rows": source_rows,
        "learning_event_rows": event_rows,
        "duplicate_signal_rows_excluded": max(0, source_rows - event_rows),
        "learning_outcome_rows": outcome_rows,
        "density_ratio": (event_rows / source_rows) if source_rows else None,
    }
    audit = {
        "schema_version": "1.0",
        "status": "PASS" if expectancy.get("status") == "OK" else "BUILDING",
        "sampling": sampling,
        "expectancy_status": expectancy.get("status"),
        "qualified_group_count": _qualified_count(expectancy),
        "analysis_windows_years": list(config.analysis_windows),
        "primary_window_years": config.primary_window_years,
        "ranking_rows": int(len(ranked)),
        "ranking_partitions_touched": int(ranking_result.get("partitions", 0)),
        "point_in_time": True,
        "future_outcomes_excluded_from_historical_ranking": True,
    }

    manifest["years_retained"] = config.years
    manifest["sampling"] = sampling
    manifest["model_audit_status"] = audit["status"]
    warnings = list(manifest.get("warnings") or [])
    if expectancy.get("status") != "OK" and "expectancy_building" not in warnings:
        warnings.append("expectancy_building")
    manifest["warnings"] = warnings

    summary = legacy._research_summary(ranked, expectancy, manifest)
    summary["model_audit"] = audit
    write_json(root / "expectancy.json", expectancy)
    write_json(root / "model-audit.json", audit)
    write_json(root / "manifest.json", manifest)
    write_json(root / "current_rankings.json", summary)
    legacy._attach_to_index(root.parent / "index.json", summary)
    return audit


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="data/intelligence/research")
    parser.add_argument("--prices", default="prices.pkl")
    parser.add_argument("--years", type=int, default=RESEARCH_RETENTION_YEARS)
    parser.add_argument("--min-samples", type=int, default=40)
    parser.add_argument("--learning-cooldown", type=int, default=5)
    args, _unknown = parser.parse_known_args()
    result = run(
        root=Path(args.root),
        price_path=Path(args.prices),
        years=max(RESEARCH_RETENTION_YEARS, args.years),
        min_samples=max(10, args.min_samples),
        cooldown_sessions=max(1, args.learning_cooldown),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
