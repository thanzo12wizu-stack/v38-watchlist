from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .utils import atomic_write_json

OPERATIONAL_POLICY_VERSION = "1.1.0"
HORIZONS = (5, 10, 21)
MIN_SAMPLES = {5: 40, 10: 35, 21: 30}


def _read(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except (OSError, json.JSONDecodeError):
        return default


def _asof_timestamp(payload: dict[str, Any] | None) -> pd.Timestamp | None:
    if not payload:
        return None
    raw = payload.get("asof") or (payload.get("manifest") or {}).get("asof")
    try:
        value = pd.Timestamp(raw)
    except Exception:
        return None
    if pd.isna(value):
        return None
    if value.tzinfo is not None:
        value = value.tz_convert(None)
    return value.normalize()


def load_prior_history(history_dir: Path, current: dict[str, Any]) -> dict[str, Any] | None:
    """Return the latest history strictly before current.asof.

    The pipeline writes today's history before command_layer runs. Selecting the
    newest file blindly therefore compares the current snapshot with itself.
    """
    current_asof = _asof_timestamp(current)
    candidates: list[tuple[pd.Timestamp, dict[str, Any]]] = []
    for path in sorted(history_dir.glob("*.json")):
        payload = _read(path, {})
        prior_asof = _asof_timestamp(payload)
        if prior_asof is None:
            continue
        if current_asof is not None and prior_asof >= current_asof:
            continue
        candidates.append((prior_asof, payload))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def freeze_snapshot(index: dict[str, Any], ledger_dir: Path) -> dict[str, Any]:
    asof = str(index.get("manifest", {}).get("asof") or date.today().isoformat())
    target = ledger_dir / f"{asof}.json"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    if target.exists():
        return {"status": "EXISTS", "path": str(target)}
    payload = {
        "schema_version": "1.0",
        "asof": asof,
        "frozen_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "market_state": index.get("market_state") or {},
        "sector_rotation": index.get("sector_rotation") or [],
        "theme_intelligence": index.get("theme_intelligence") or [],
        "entry_candidates": index.get("entry_candidates") or [],
        "story_intelligence": index.get("story_intelligence") or [],
        "external_data": index.get("external_data") or [],
    }
    atomic_write_json(target, payload)
    return {"status": "CREATED", "path": str(target)}


def settle_outcomes(ledger_dir: Path, prices: dict[str, pd.DataFrame]) -> dict[str, Any]:
    qqq = prices.get("QQQ")
    if qqq is None:
        return {"settled": 0, "pending": 0, "warnings": ["qqq_missing"]}
    qclose = pd.to_numeric(qqq.get("close"), errors="coerce").dropna()
    if not isinstance(qclose.index, pd.DatetimeIndex):
        return {"settled": 0, "pending": 0, "warnings": ["qqq_index_invalid"]}

    settled = pending = invalid_ledgers = 0
    for path in sorted(ledger_dir.glob("*.json")):
        payload = _read(path, {})
        asof = _asof_timestamp(payload)
        if asof is None:
            invalid_ledgers += 1
            continue
        outcomes = payload.setdefault("outcomes", {})
        changed = False
        for candidate in payload.get("entry_candidates") or []:
            ticker = str(candidate.get("ticker") or "")
            frame = prices.get(ticker)
            if frame is None or not isinstance(frame.index, pd.DatetimeIndex):
                continue
            close = pd.to_numeric(frame.get("close"), errors="coerce").dropna()
            common_dates = close.index.intersection(qclose.index)
            common_dates = common_dates[common_dates >= asof]
            if not len(common_dates):
                continue
            rec = outcomes.setdefault(
                ticker,
                {"entry_date": str(common_dates[0].date()), "horizons": {}},
            )
            for horizon in HORIZONS:
                if str(horizon) in rec["horizons"]:
                    continue
                if len(common_dates) <= horizon:
                    pending += 1
                    continue
                entry_date = common_dates[0]
                exit_date = common_dates[horizon]
                sr = float(close.loc[exit_date] / close.loc[entry_date] - 1)
                qr = float(qclose.loc[exit_date] / qclose.loc[entry_date] - 1)
                rec["horizons"][str(horizon)] = {
                    "stock_return": sr,
                    "qqq_return": qr,
                    "excess_return": sr - qr,
                    "win": sr > qr,
                    "exit_date": str(exit_date.date()),
                }
                settled += 1
                changed = True
        if changed:
            atomic_write_json(path, payload)
    warnings = ["invalid_ledger_asof"] if invalid_ledgers else []
    return {
        "settled": settled,
        "pending": pending,
        "invalid_ledgers": invalid_ledgers,
        "warnings": warnings,
    }


def _bootstrap(values: list[float], seed: int = 38, n: int = 1000):
    if len(values) < 10:
        return None
    rng = np.random.default_rng(seed)
    arr = np.asarray(values, dtype=float)
    means = [float(rng.choice(arr, len(arr), replace=True).mean()) for _ in range(n)]
    return [float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))]


def build_robust_expectancy(ledger_dir: Path) -> dict[str, Any]:
    rows = []
    for path in sorted(ledger_dir.glob("*.json")):
        payload = _read(path, {})
        candidates = {str(x.get("ticker")): x for x in payload.get("entry_candidates") or []}
        asof = str(payload.get("asof") or "")
        year = int(asof[:4]) if asof[:4].isdigit() else None
        regime = (payload.get("market_state") or {}).get("regime")
        for ticker, result in (payload.get("outcomes") or {}).items():
            candidate = candidates.get(ticker, {})
            for horizon, outcome in (result.get("horizons") or {}).items():
                rows.append(
                    {
                        "ticker": ticker,
                        "year": year,
                        "regime": regime,
                        "horizon": int(horizon),
                        "setup": candidate.get("setup"),
                        "sector": candidate.get("sector"),
                        "theme": candidate.get("theme"),
                        "market_cap_bucket": candidate.get("market_cap_bucket"),
                        "adr_bucket": candidate.get("adr_bucket"),
                        "earnings_window": bool(candidate.get("earnings_window")),
                        "excess_return": outcome.get("excess_return"),
                    }
                )
    frame = pd.DataFrame(rows)
    if frame.empty:
        return {"status": "NO_SETTLED_OBSERVATIONS", "rankings": [], "coverage": {}}

    def summary(group: pd.DataFrame) -> dict[str, Any]:
        values = pd.to_numeric(group["excess_return"], errors="coerce").dropna().tolist()
        horizon = int(group["horizon"].iloc[0])
        if not values:
            return {
                "samples": 0,
                "sample_count": 0,
                "minimum_samples": MIN_SAMPLES[horizon],
                "qualified": False,
                "mean_excess": None,
                "median_excess": None,
                "median_excess_return": None,
                "win_rate": None,
                "downside_tail_p10": None,
                "downside_tail": None,
                "bootstrap_mean_ci95": None,
            }
        median = float(np.median(values))
        downside = float(np.quantile(values, 0.10))
        return {
            "samples": len(values),
            "sample_count": len(values),
            "minimum_samples": MIN_SAMPLES[horizon],
            "qualified": len(values) >= MIN_SAMPLES[horizon],
            "mean_excess": float(np.mean(values)),
            "median_excess": median,
            "median_excess_return": median,
            "win_rate": float(np.mean(np.asarray(values) > 0)),
            "downside_tail_p10": downside,
            "downside_tail": downside,
            "bootstrap_mean_ci95": _bootstrap(values),
        }

    dimensions = [
        "setup",
        "year",
        "regime",
        "sector",
        "theme",
        "market_cap_bucket",
        "adr_bucket",
        "earnings_window",
    ]
    cuts: dict[str, list[dict[str, Any]]] = {}
    for dim in dimensions:
        cuts[dim] = [
            {
                "label": None if pd.isna(keys[0]) else keys[0],
                "setup": None if dim != "setup" or pd.isna(keys[0]) else keys[0],
                "horizon": int(keys[1]),
                **summary(group),
            }
            for keys, group in frame.groupby([dim, "horizon"], dropna=False)
        ]

    walk_forward = []
    for horizon in HORIZONS:
        horizon_frame = frame[frame["horizon"] == horizon]
        years = sorted(int(y) for y in horizon_frame["year"].dropna().unique())
        for test_year in years:
            train = horizon_frame[horizon_frame["year"] < test_year]
            test = horizon_frame[horizon_frame["year"] == test_year]
            if train.empty or test.empty:
                continue
            means = (
                train.dropna(subset=["setup"])
                .groupby("setup")["excess_return"]
                .mean()
                .sort_values(ascending=False)
            )
            if means.empty:
                continue
            selected = means.index[0]
            observed = test[test["setup"] == selected]
            walk_forward.append(
                {
                    "horizon": horizon,
                    "test_year": test_year,
                    "selected_setup": selected,
                    "samples": len(observed),
                    "mean_excess": None
                    if observed.empty
                    else float(observed["excess_return"].mean()),
                }
            )

    years_all = sorted(int(y) for y in frame["year"].dropna().unique())
    excluding_2020 = [
        {"horizon": int(horizon), **summary(group)}
        for horizon, group in frame[frame["year"] != 2020].groupby("horizon")
    ]
    rankings = [x for x in cuts["setup"] if x["qualified"]]
    rankings.sort(
        key=lambda x: (
            x["horizon"],
            -(x["mean_excess"] if x["mean_excess"] is not None else -np.inf),
            -x["samples"],
        )
    )
    return {
        "status": "OK",
        "observation_count": len(frame),
        "minimum_samples": MIN_SAMPLES,
        "rankings": rankings,
        "cuts": cuts,
        "walk_forward": walk_forward,
        "excluding_2020": excluding_2020,
        "coverage": {
            "years": years_all,
            "settled_tickers": int(frame["ticker"].nunique()),
        },
    }


def _theme_score(item: dict[str, Any]) -> float:
    raw = item.get("score_theme")
    if raw is None:
        raw = item.get("score")
    value = pd.to_numeric(raw, errors="coerce")
    return 0.0 if pd.isna(value) else float(value)


def detect_leader_transitions(
    current: dict[str, Any], history_dir: Path
) -> dict[str, Any]:
    prior = load_prior_history(history_dir, current)
    if prior is None:
        return {"status": "NO_PRIOR_HISTORY", "changes": {}, "rank_changes": []}

    def ranks(stocks, window):
        def score(stock):
            value = pd.to_numeric(
                (stock.get("features") or {}).get(f"pct_rs_raw_{window}"),
                errors="coerce",
            )
            return -1.0 if pd.isna(value) else float(value)

        ordered = sorted(stocks, key=lambda stock: (-score(stock), str(stock.get("ticker"))))
        return {str(stock.get("ticker")): i + 1 for i, stock in enumerate(ordered)}

    changes: dict[str, Any] = {}
    flat_rank_changes: list[dict[str, Any]] = []
    for window in (63, 126, 189):
        now = ranks(current.get("stocks") or [], window)
        before = ranks(prior.get("stocks") or [], window)
        rank_changes = []
        for ticker, current_rank in now.items():
            previous_rank = before.get(ticker)
            change = (
                (previous_rank if previous_rank is not None else len(before) + 1)
                - current_rank
            )
            row = {
                "ticker": ticker,
                "window": window,
                "previous_rank": previous_rank,
                "current_rank": current_rank,
                "rank_change": change,
                "change": change,
            }
            rank_changes.append(row)
            flat_rank_changes.append(row)
        rank_changes.sort(key=lambda x: (-x["rank_change"], x["ticker"]))
        changes[f"rs{window}"] = {
            "new_top10": sorted(
                ticker
                for ticker, rank in now.items()
                if rank <= 10 and before.get(ticker, 999) > 10
            ),
            "dropped_top10": sorted(
                ticker
                for ticker, rank in before.items()
                if rank <= 10 and now.get(ticker, 999) > 10
            ),
            "rank_changes": rank_changes[:20],
        }

    prior_themes = {
        str(item.get("theme")): item for item in prior.get("theme_intelligence") or []
    }
    themes = []
    for item in current.get("theme_intelligence") or []:
        name = str(item.get("theme"))
        old = prior_themes.get(name, {})
        themes.append(
            {
                "theme": name,
                "score_change": _theme_score(item) - _theme_score(old),
                "from": old.get("phase"),
                "to": item.get("phase"),
            }
        )
    changes["themes"] = sorted(
        themes, key=lambda x: (-x["score_change"], x["theme"])
    )
    flat_rank_changes.sort(
        key=lambda x: (-x["rank_change"], x["window"], x["ticker"])
    )
    return {
        "status": "OK",
        "compared_to": prior.get("asof")
        or (prior.get("manifest") or {}).get("asof"),
        "changes": changes,
        "rank_changes": flat_rank_changes[:60],
    }


def _external_age_days(path: Path, now: datetime) -> float | None:
    try:
        frame = pd.read_csv(path)
    except Exception:
        frame = pd.DataFrame()
    if not frame.empty and "fetched_at" in frame.columns:
        fetched = pd.to_datetime(frame["fetched_at"], utc=True, errors="coerce").dropna()
        if not fetched.empty:
            return (now - fetched.max().to_pydatetime()).total_seconds() / 86400
    try:
        return (now.timestamp() - path.stat().st_mtime) / 86400
    except OSError:
        return None


def build_quality_report(
    index: dict[str, Any],
    prices: dict[str, pd.DataFrame],
    external_root: Path,
    previous_index: dict[str, Any] | None = None,
) -> dict[str, Any]:
    warnings: list[str] = []
    metrics: dict[str, Any] = {}
    today = pd.Timestamp.utcnow().tz_localize(None).normalize()
    qqq = prices.get("QQQ")
    if qqq is None or qqq.empty:
        warnings.append("qqq_missing")
    else:
        last = (
            pd.Timestamp(qqq.index.max()).tz_localize(None).normalize()
            if isinstance(qqq.index, pd.DatetimeIndex)
            else None
        )
        metrics["qqq_last_date"] = None if last is None else str(last.date())
        if last is None or (today - last).days > 4:
            warnings.append("qqq_stale")

    universe = int(index.get("manifest", {}).get("universe_count") or 0)
    covered = int(index.get("manifest", {}).get("price_covered_count") or 0)
    metrics["price_coverage_ratio"] = covered / universe if universe else 0
    if universe and covered / universe < 0.80:
        warnings.append("price_coverage_low")

    count = len(index.get("entry_candidates") or [])
    metrics["candidate_count"] = count
    if count == 0:
        warnings.append("candidate_count_zero")
    if previous_index is not None:
        previous_count = len(previous_index.get("entry_candidates") or [])
        metrics["previous_candidate_count"] = previous_count
        if previous_count and abs(count - previous_count) / previous_count > 0.60:
            warnings.append("candidate_count_anomaly")

    freshness = {}
    now = datetime.now(timezone.utc)
    if external_root.exists():
        for path in external_root.glob("*.csv"):
            age = _external_age_days(path, now)
            freshness[path.name] = None if age is None else round(age, 2)
            if age is not None and age > 8:
                warnings.append(f"external_stale:{path.name}")
    metrics["external_freshness_days"] = freshness
    return {
        "status": "PASS" if not warnings else "WARN",
        "warnings": sorted(set(warnings)),
        "metrics": metrics,
    }
