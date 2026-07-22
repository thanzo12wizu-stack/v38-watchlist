from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .utils import atomic_write_json

OPERATIONAL_POLICY_VERSION = "1.0.0"
HORIZONS = (5, 10, 21)
MIN_SAMPLES = {5: 40, 10: 35, 21: 30}


def _read(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except (OSError, json.JSONDecodeError):
        return default


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
        "external_data": index.get("external_data") or {},
    }
    atomic_write_json(target, payload)
    return {"status": "CREATED", "path": str(target)}


def settle_outcomes(ledger_dir: Path, prices: dict[str, pd.DataFrame]) -> dict[str, Any]:
    qqq = prices.get("QQQ")
    if qqq is None:
        return {"settled": 0, "pending": 0, "warnings": ["qqq_missing"]}
    qclose = pd.to_numeric(qqq.get("close"), errors="coerce").dropna()
    settled = pending = 0
    for path in sorted(ledger_dir.glob("*.json")):
        payload = _read(path, {})
        asof = pd.Timestamp(payload.get("asof"))
        outcomes = payload.setdefault("outcomes", {})
        changed = False
        for candidate in payload.get("entry_candidates") or []:
            ticker = str(candidate.get("ticker") or "")
            frame = prices.get(ticker)
            if frame is None or not isinstance(frame.index, pd.DatetimeIndex):
                continue
            close = pd.to_numeric(frame.get("close"), errors="coerce").dropna()
            stock_dates = close.index[close.index >= asof]
            qqq_dates = qclose.index[qclose.index >= asof]
            if not len(stock_dates) or not len(qqq_dates):
                continue
            rec = outcomes.setdefault(ticker, {"entry_date": str(stock_dates[0].date()), "horizons": {}})
            for horizon in HORIZONS:
                if str(horizon) in rec["horizons"]:
                    continue
                if len(stock_dates) <= horizon or len(qqq_dates) <= horizon:
                    pending += 1
                    continue
                sr = float(close.loc[stock_dates[horizon]] / close.loc[stock_dates[0]] - 1)
                qr = float(qclose.loc[qqq_dates[horizon]] / qclose.loc[qqq_dates[0]] - 1)
                rec["horizons"][str(horizon)] = {"stock_return": sr, "qqq_return": qr, "excess_return": sr - qr, "win": sr > qr}
                settled += 1
                changed = True
        if changed:
            atomic_write_json(path, payload)
    return {"settled": settled, "pending": pending, "warnings": []}


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
                rows.append({
                    "ticker": ticker, "year": year, "regime": regime, "horizon": int(horizon),
                    "setup": candidate.get("setup"), "sector": candidate.get("sector"), "theme": candidate.get("theme"),
                    "market_cap_bucket": candidate.get("market_cap_bucket"), "adr_bucket": candidate.get("adr_bucket"),
                    "earnings_window": bool(candidate.get("earnings_window")), "excess_return": outcome.get("excess_return"),
                })
    frame = pd.DataFrame(rows)
    if frame.empty:
        return {"status": "NO_SETTLED_OBSERVATIONS", "rankings": [], "coverage": {}}

    def summary(group):
        values = pd.to_numeric(group["excess_return"], errors="coerce").dropna().tolist()
        horizon = int(group["horizon"].iloc[0])
        return {
            "samples": len(values), "minimum_samples": MIN_SAMPLES[horizon], "qualified": len(values) >= MIN_SAMPLES[horizon],
            "mean_excess": float(np.mean(values)), "median_excess": float(np.median(values)),
            "win_rate": float(np.mean(np.asarray(values) > 0)), "downside_tail_p10": float(np.quantile(values, 0.10)),
            "bootstrap_mean_ci95": _bootstrap(values),
        }

    dimensions = ["setup", "year", "regime", "sector", "theme", "market_cap_bucket", "adr_bucket", "earnings_window"]
    cuts = {}
    for dim in dimensions:
        cuts[dim] = [{"label": None if pd.isna(keys[0]) else keys[0], "horizon": int(keys[1]), **summary(group)} for keys, group in frame.groupby([dim, "horizon"], dropna=False)]
    walk_forward = []
    years = sorted(int(y) for y in frame["year"].dropna().unique())
    for test_year in years:
        train = frame[frame["year"] < test_year]
        test = frame[frame["year"] == test_year]
        if train.empty or test.empty:
            continue
        means = train.groupby("setup")["excess_return"].mean().sort_values(ascending=False)
        if means.empty:
            continue
        selected = means.index[0]
        observed = test[test["setup"] == selected]
        walk_forward.append({"test_year": test_year, "selected_setup": selected, "samples": len(observed), "mean_excess": None if observed.empty else float(observed["excess_return"].mean())})
    excluding_2020 = [{"horizon": int(horizon), **summary(group)} for horizon, group in frame[frame["year"] != 2020].groupby("horizon")]
    rankings = [x for x in cuts["setup"] if x["qualified"]]
    rankings.sort(key=lambda x: (x["horizon"], -x["mean_excess"], -x["samples"]))
    return {"status": "OK", "observation_count": len(frame), "minimum_samples": MIN_SAMPLES, "rankings": rankings, "cuts": cuts, "walk_forward": walk_forward, "excluding_2020": excluding_2020, "coverage": {"years": years, "settled_tickers": int(frame["ticker"].nunique())}}


def detect_leader_transitions(current: dict[str, Any], history_dir: Path) -> dict[str, Any]:
    histories = sorted(history_dir.glob("*.json"))
    if not histories:
        return {"status": "NO_HISTORY", "changes": {}}
    prior = _read(histories[-1], {})
    def ranks(stocks, window):
        ordered = sorted(stocks, key=lambda s: -float((s.get("features") or {}).get(f"pct_rs_raw_{window}") or -1))
        return {str(s.get("ticker")): i + 1 for i, s in enumerate(ordered)}
    changes = {}
    for window in (63, 126, 189):
        now, before = ranks(current.get("stocks") or [], window), ranks(prior.get("stocks") or [], window)
        changes[f"rs{window}"] = {
            "new_top10": sorted(t for t, r in now.items() if r <= 10 and before.get(t, 999) > 10),
            "dropped_top10": sorted(t for t, r in before.items() if r <= 10 and now.get(t, 999) > 10),
            "rank_changes": sorted(({"ticker": t, "change": before.get(t, len(before) + 1) - r} for t, r in now.items()), key=lambda x: (-x["change"], x["ticker"]))[:20],
        }
    prior_themes = {str(x.get("theme")): x for x in prior.get("theme_intelligence") or []}
    themes = []
    for item in current.get("theme_intelligence") or []:
        name = str(item.get("theme")); old = prior_themes.get(name, {})
        themes.append({"theme": name, "score_change": float(item.get("score") or 0) - float(old.get("score") or 0), "from": old.get("phase"), "to": item.get("phase")})
    changes["themes"] = sorted(themes, key=lambda x: (-x["score_change"], x["theme"]))
    return {"status": "OK", "compared_to": prior.get("asof") or prior.get("manifest", {}).get("asof"), "changes": changes}


def build_quality_report(index: dict[str, Any], prices: dict[str, pd.DataFrame], external_root: Path, previous_index: dict[str, Any] | None = None) -> dict[str, Any]:
    warnings, metrics = [], {}
    today = pd.Timestamp.utcnow().tz_localize(None).normalize()
    qqq = prices.get("QQQ")
    if qqq is None or qqq.empty:
        warnings.append("qqq_missing")
    else:
        last = pd.Timestamp(qqq.index.max()).tz_localize(None).normalize() if isinstance(qqq.index, pd.DatetimeIndex) else None
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
    if external_root.exists():
        for path in external_root.glob("*.csv"):
            age = (datetime.now(timezone.utc).timestamp() - path.stat().st_mtime) / 86400
            freshness[path.name] = round(age, 2)
            if age > 8:
                warnings.append(f"external_stale:{path.name}")
    metrics["external_freshness_days"] = freshness
    return {"status": "PASS" if not warnings else "WARN", "warnings": sorted(set(warnings)), "metrics": metrics}
