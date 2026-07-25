from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .prices import load_price_map
from .research_storage import load_dataset


@dataclass(frozen=True)
class AdoptionPolicy:
    horizon: int = 10
    round_trip_cost: float = 0.002
    max_positions: int = 4
    position_weight: float = 0.08
    min_samples: int = 100
    min_positive_year_rate: float = 0.70
    min_oos_positive_rate: float = 0.60
    max_ticker_share: float = 0.25
    max_year_share: float = 0.50
    bootstrap_samples: int = 1000
    seed: int = 38


def _num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _date_block_ci(frame: pd.DataFrame, value_col: str, *, samples: int, seed: int) -> list[float] | None:
    if frame.empty or value_col not in frame or "date" not in frame:
        return None
    daily = frame.assign(date=pd.to_datetime(frame["date"], errors="coerce")).dropna(subset=["date"])
    daily = daily.groupby(daily["date"].dt.normalize())[value_col].mean()
    daily = _num(daily).dropna()
    if len(daily) < 10:
        return None
    rng = np.random.default_rng(seed)
    means = np.empty(samples, dtype=float)
    values = daily.to_numpy(dtype=float)
    for i in range(samples):
        means[i] = rng.choice(values, len(values), replace=True).mean()
    return [float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))]


def _summary(frame: pd.DataFrame, value_col: str, policy: AdoptionPolicy) -> dict[str, Any]:
    work = frame.copy()
    work[value_col] = _num(work.get(value_col, pd.Series(dtype=float)))
    work = work.dropna(subset=[value_col])
    if work.empty:
        return {"samples": 0, "mean": None, "win_rate": None, "positive_year_rate": None,
                "max_ticker_share": None, "max_year_share": None, "date_block_ci95": None}
    dates = pd.to_datetime(work["date"], errors="coerce")
    years = dates.dt.year
    yearly = work.assign(_year=years).dropna(subset=["_year"]).groupby("_year")[value_col].mean()
    tick_share = work["ticker"].astype(str).value_counts(normalize=True).max() if "ticker" in work else np.nan
    year_share = years.value_counts(normalize=True).max() if years.notna().any() else np.nan
    return {
        "samples": int(len(work)),
        "mean": float(work[value_col].mean()),
        "median": float(work[value_col].median()),
        "win_rate": float((work[value_col] > 0).mean()),
        "positive_year_rate": float((yearly > 0).mean()) if len(yearly) else None,
        "years": [int(x) for x in yearly.index],
        "max_ticker_share": None if pd.isna(tick_share) else float(tick_share),
        "max_year_share": None if pd.isna(year_share) else float(year_share),
        "date_block_ci95": _date_block_ci(work, value_col, samples=policy.bootstrap_samples, seed=policy.seed),
    }


def _hard_block_free(frame: pd.DataFrame) -> pd.Series:
    if "hard_blocks" not in frame:
        return pd.Series(True, index=frame.index)
    def clear(value: Any) -> bool:
        if isinstance(value, list):
            return len(value) == 0
        if value is None or (isinstance(value, float) and np.isnan(value)):
            return True
        text = str(value).strip()
        return text in {"", "[]", "null", "None"}
    return frame["hard_blocks"].map(clear)


def _candidate_masks(frame: pd.DataFrame) -> dict[str, pd.Series]:
    clear = _hard_block_free(frame)
    archetype = frame.get("candidate_archetype", pd.Series("NONE", index=frame.index)).astype(str)
    status = frame.get("decision_status", pd.Series("", index=frame.index)).astype(str)
    confidence = _num(frame.get("research_confidence", pd.Series(np.nan, index=frame.index)))
    edge = _num(frame.get("expected_edge_10d", pd.Series(np.nan, index=frame.index)))
    consistency = frame.get("expectancy_consistency", pd.Series("", index=frame.index)).astype(str)
    return {
        "BASELINE": pd.Series(True, index=frame.index),
        "HARD_BLOCKS": clear,
        "ARCHETYPE": clear & ~archetype.isin(["NONE", "DETERIORATION_ALERT"]),
        "RESEARCH_QUALIFIED": clear & status.isin(["QUALIFIED", "PROMISING"]),
        "EDGE_CONFIRMED": clear & (edge > 0) & consistency.isin(["CONFIRMED", "PRIMARY_ONLY"]) & (confidence >= 0.60),
    }


def _walk_forward(frame: pd.DataFrame, mask_name: str, mask: pd.Series, value_col: str) -> dict[str, Any]:
    work = frame.loc[mask].copy()
    dates = pd.to_datetime(work.get("date"), errors="coerce")
    rows = []
    for year in sorted(int(x) for x in dates.dt.year.dropna().unique()):
        test = work[dates.dt.year == year]
        values = _num(test.get(value_col, pd.Series(dtype=float))).dropna()
        if len(values):
            rows.append({"year": year, "samples": int(len(values)), "mean": float(values.mean())})
    return {
        "strategy": mask_name,
        "years": rows,
        "positive_rate": float(np.mean([row["mean"] > 0 for row in rows])) if rows else None,
    }


def _decision(summary: dict[str, Any], walk: dict[str, Any], policy: AdoptionPolicy) -> tuple[str, list[str]]:
    reasons: list[str] = []
    ci = summary.get("date_block_ci95")
    checks = {
        "samples": summary.get("samples", 0) >= policy.min_samples,
        "mean": (summary.get("mean") or 0) > 0,
        "block_ci": ci is not None and ci[0] > 0,
        "positive_year_rate": (summary.get("positive_year_rate") or 0) >= policy.min_positive_year_rate,
        "oos_positive_rate": (walk.get("positive_rate") or 0) >= policy.min_oos_positive_rate,
        "ticker_concentration": (summary.get("max_ticker_share") or 0) <= policy.max_ticker_share,
        "year_concentration": (summary.get("max_year_share") or 0) <= policy.max_year_share,
    }
    reasons.extend(name for name, passed in checks.items() if not passed)
    if all(checks.values()):
        return "ADOPT", reasons
    if checks["samples"] and checks["mean"] and checks["positive_year_rate"]:
        return "DISPLAY_ONLY", reasons
    return "REJECT", reasons


def build_report(root: Path, policy: AdoptionPolicy = AdoptionPolicy()) -> dict[str, Any]:
    outcomes = load_dataset(root, "outcomes")
    rankings = load_dataset(root, "rankings")
    if outcomes.empty:
        raise RuntimeError("research outcomes are missing")
    keys = ["ticker", "date", "candidate_archetype", "setup"]
    merge_cols = [c for c in [*keys, "decision_status", "research_confidence", "expected_edge_10d", "expectancy_consistency", "hard_blocks"] if c in rankings]
    merged = outcomes.merge(rankings[merge_cols].drop_duplicates(keys), on=[c for c in keys if c in outcomes and c in rankings], how="left", suffixes=("", "_rank")) if merge_cols else outcomes.copy()
    value_col = f"excess_{policy.horizon}"
    masks = _candidate_masks(merged)
    strategies = []
    for name, mask in masks.items():
        summary = _summary(merged.loc[mask], value_col, policy)
        walk = _walk_forward(merged, name, mask, value_col)
        decision, reasons = _decision(summary, walk, policy)
        strategies.append({"strategy": name, "decision": decision, "reasons": reasons, "summary": summary, "walk_forward": walk})
    priority = {"ADOPT": 0, "DISPLAY_ONLY": 1, "REJECT": 2}
    strategies.sort(key=lambda x: (priority[x["decision"]], -(x["summary"].get("mean") or -999)))
    adopted = [x["strategy"] for x in strategies if x["decision"] == "ADOPT"]
    display = [x["strategy"] for x in strategies if x["decision"] in {"ADOPT", "DISPLAY_ONLY"}]
    return {
        "schema_version": "1.0",
        "method": "point-in-time rankings; QQQ excess returns; date-block bootstrap; annual walk-forward",
        "limitations": [
            "Primary return labels use signal-date close and fixed holding horizons.",
            "Execution-grade next-open/two-stage/trailing-stop validation requires retained price cache.",
            "No Command Center files are modified by this report.",
        ],
        "policy": policy.__dict__,
        "strategies": strategies,
        "implementation": {
            "execution_filters": [x for x in adopted if x in {"HARD_BLOCKS", "ARCHETYPE", "RESEARCH_QUALIFIED", "EDGE_CONFIRMED"}],
            "dashboard_fields": display,
            "market_regime": "ANALYSIS_ONLY",
            "command_center_integration": "SIDECAR_ONLY",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="data/intelligence/research")
    parser.add_argument("--output", default="research-adoption-report.json")
    args = parser.parse_args()
    report = build_report(Path(args.root))
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": args.output, "strategies": len(report["strategies"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
