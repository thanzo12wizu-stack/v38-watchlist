from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import validate_early_rotation as er

HORIZONS = er.HORIZONS
MOMENTUM_CONFIG = {"theme_min": 80.0, "delta20_min": 15.0, "breadth_min": 60.0}
PARENT_SPLIT = 60.0


def momentum_mask(theme_pct: pd.DataFrame, parent_pct: pd.DataFrame, breadth: pd.DataFrame) -> pd.DataFrame:
    common = theme_pct.columns.intersection(parent_pct.columns).intersection(breadth.columns)
    t = theme_pct[common]
    b = breadth[common]
    delta20 = t - t.shift(20)
    return (t >= MOMENTUM_CONFIG["theme_min"]) & (delta20 >= MOMENTUM_CONFIG["delta20_min"]) & (b >= MOMENTUM_CONFIG["breadth_min"])


def group_summary(outcomes: pd.DataFrame) -> dict[str, Any]:
    return er.summarize_outcomes(outcomes) if not outcomes.empty else {}


def clustered_difference(values: pd.DataFrame, metric: str, cluster: str, seed: int, reps: int = 4000) -> dict[str, Any]:
    use = values[[cluster, "parent_state", metric]].dropna()
    weak = use[use["parent_state"] == "PARENT_WEAK"][metric]
    confirmed = use[use["parent_state"] == "PARENT_NOT_WEAK"][metric]
    point = float(weak.mean() - confirmed.mean()) if len(weak) and len(confirmed) else None
    if point is None:
        return {"weak_minus_not_weak": None, "ci95": [None, None], "clusters": 0}

    table = use.assign(
        weak_value=np.where(use["parent_state"] == "PARENT_WEAK", use[metric], 0.0),
        weak_count=np.where(use["parent_state"] == "PARENT_WEAK", 1.0, 0.0),
        not_weak_value=np.where(use["parent_state"] == "PARENT_NOT_WEAK", use[metric], 0.0),
        not_weak_count=np.where(use["parent_state"] == "PARENT_NOT_WEAK", 1.0, 0.0),
    ).groupby(cluster, observed=True)[["weak_value", "weak_count", "not_weak_value", "not_weak_count"]].sum()

    n_clusters = len(table)
    if n_clusters == 0:
        return {"weak_minus_not_weak": point, "ci95": [None, None], "clusters": 0}
    arr = table.to_numpy(float)
    rng = np.random.default_rng(seed)
    # Multinomial cluster counts are exactly equivalent to resampling n clusters
    # with replacement, but avoid repeated Python concatenation.
    draws = rng.multinomial(n_clusters, np.full(n_clusters, 1.0 / n_clusters), size=reps)
    totals = draws @ arr
    valid = (totals[:, 1] > 0) & (totals[:, 3] > 0)
    diffs = totals[valid, 0] / totals[valid, 1] - totals[valid, 2] / totals[valid, 3]
    if not len(diffs):
        return {"weak_minus_not_weak": point, "ci95": [None, None], "clusters": n_clusters}
    lo, hi = np.quantile(diffs, [0.025, 0.975])
    return {"weak_minus_not_weak": point, "ci95": [float(lo), float(hi)], "clusters": n_clusters}


def compare_groups(outcomes: pd.DataFrame) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for h in HORIZONS:
        metrics: dict[str, Any] = {}
        for metric in (f"spy_excess_{h}", f"parent_excess_{h}", f"median_theme_excess_{h}", f"rs_delta_{h}"):
            date_diff = clustered_difference(outcomes, metric, "date", seed=100 + h)
            theme_diff = clustered_difference(outcomes, metric, "theme", seed=200 + h)
            metrics[metric] = {
                "weak_minus_not_weak": date_diff["weak_minus_not_weak"],
                "date_cluster_ci95": date_diff["ci95"],
                "theme_cluster_ci95": theme_diff["ci95"],
            }
        for metric in (f"top20_retained_{h}", f"parent_top20_{h}"):
            weak = outcomes.loc[outcomes["parent_state"] == "PARENT_WEAK", metric].dropna()
            confirmed = outcomes.loc[outcomes["parent_state"] == "PARENT_NOT_WEAK", metric].dropna()
            metrics[metric] = {
                "weak_rate": float(weak.mean()) if len(weak) else None,
                "not_weak_rate": float(confirmed.mean()) if len(confirmed) else None,
                "weak_minus_not_weak": float(weak.mean() - confirmed.mean()) if len(weak) and len(confirmed) else None,
            }
        spy = metrics[f"spy_excess_{h}"]
        metrics["parent_weakness_adds_significant_spy_alpha"] = bool(
            spy["date_cluster_ci95"][0] is not None
            and spy["theme_cluster_ci95"][0] is not None
            and spy["date_cluster_ci95"][0] > 0
            and spy["theme_cluster_ci95"][0] > 0
        )
        result[str(h)] = metrics
    return result


def safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe(v) for v in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (np.floating, float)):
        x = float(value)
        return x if math.isfinite(x) else None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", default="leadership/research/momentum_output")
    parser.add_argument("--analysis-start", default="2016-01-04")
    parser.add_argument("--analysis-end", default="2026-06-20")
    parser.add_argument("--max-tickers", type=int, default=1500)
    parser.add_argument("--batch-size", type=int, default=75)
    parser.add_argument("--min-members", type=int, default=3)
    args = parser.parse_args()

    root = Path(args.root)
    output = root / args.output
    output.mkdir(parents=True, exist_ok=True)

    snapshot = er.load_json(root / "sector_snapshot.json")
    theme_members_all, taxonomy_candidates = er.extract_theme_members(snapshot)
    industry_map = er.read_industry_map(root / "industry_map.json")
    universe = er.read_universe_symbols(root / "universe.csv")

    selected = er.stratified_symbols(theme_members_all, set(industry_map) & universe, args.max_tickers)
    requested = selected + (["SPY"] if "SPY" not in selected else [])
    download_start = str((pd.Timestamp(args.analysis_start) - pd.Timedelta(days=320)).date())
    download_end = str((pd.Timestamp(args.analysis_end) + pd.Timedelta(days=100)).date())
    close, download_diag = er.download_adjusted_close(requested, download_start, download_end, args.batch_size)
    if "SPY" not in close.columns:
        raise RuntimeError("SPY benchmark missing from Yahoo download")

    stock_cols = [s for s in selected if s in close.columns]
    stock_close = close[stock_cols]
    stock_ret = er.arithmetic_returns(stock_close)
    spy_ret = er.arithmetic_returns(close[["SPY"]])["SPY"]

    theme_members = {theme: [s for s in members if s in stock_cols] for theme, members in theme_members_all.items()}
    member_counts = {theme: len(members) for theme, members in theme_members.items()}
    theme_ret = er.grouped_equal_weight(stock_ret, theme_members, args.min_members)

    industry_groups: dict[str, list[str]] = defaultdict(list)
    for sym in stock_cols:
        pair = industry_map.get(sym)
        if pair and pair[1]:
            industry_groups[pair[1]].append(sym)
    industry_ret = er.grouped_equal_weight(stock_ret, dict(industry_groups), args.min_members)

    parent_weights = er.build_parent_weights(theme_members_all, industry_map)
    common_themes = sorted(set(theme_ret.columns) & set(parent_weights))
    theme_ret = theme_ret[common_themes]
    parent_ret = er.weighted_matrix(industry_ret, parent_weights, common_themes)

    theme_63 = er.period_return(theme_ret, 63)
    spy_63 = er.period_return(spy_ret, 63)
    theme_pct = theme_63.sub(spy_63, axis=0).rank(axis=1, pct=True, method="average") * 100.0
    industry_63 = er.period_return(industry_ret, 63)
    industry_pct = industry_63.sub(spy_63, axis=0).rank(axis=1, pct=True, method="average") * 100.0
    parent_pct = er.weighted_matrix(industry_pct, parent_weights, common_themes)

    breadth = er.breadth_above_ema21(stock_close, theme_members, args.min_members).reindex(columns=common_themes)
    theme_fwd = {h: er.forward_return(theme_ret, h) for h in HORIZONS}
    spy_fwd = {h: er.forward_return(spy_ret, h) for h in HORIZONS}
    parent_fwd = {h: er.forward_return(parent_ret, h) for h in HORIZONS}

    analysis_start, analysis_end = pd.Timestamp(args.analysis_start), pd.Timestamp(args.analysis_end)
    events = er.extract_events(momentum_mask(theme_pct, parent_pct, breadth), theme_pct, parent_pct, breadth, member_counts, analysis_start, analysis_end)
    outcomes = er.attach_outcomes(events, HORIZONS, theme_fwd, spy_fwd, parent_fwd, theme_pct, parent_pct)
    outcomes["parent_state"] = np.where(outcomes["parent_rs_pct"] < PARENT_SPLIT, "PARENT_WEAK", "PARENT_NOT_WEAK")

    weak = outcomes[outcomes["parent_state"] == "PARENT_WEAK"].copy()
    not_weak = outcomes[outcomes["parent_state"] == "PARENT_NOT_WEAK"].copy()

    result = {
        "status": "PRELIMINARY_FIXED_CURRENT_TAXONOMY",
        "question": "Does requiring a weak parent Industry add signal value beyond Subtheme Momentum itself?",
        "bias_warning": "Current ticker→theme and ticker→industry memberships are applied retrospectively. This is hypothesis filtering, not final survivorship/look-ahead-free proof.",
        "momentum_definition_frozen_before_outcomes": MOMENTUM_CONFIG,
        "parent_split_frozen_before_outcomes": {"weak": f"parent_rs_pct < {PARENT_SPLIT:g}", "not_weak": f"parent_rs_pct >= {PARENT_SPLIT:g}"},
        "event_policy": "Momentum-only first qualifying day after inactive state, 20-trading-day per-theme cooldown; parent groups are assigned on that exact same signal day.",
        "comparison_design": "Same Momentum event universe split by contemporaneous parent RS. This isolates the incremental value of parent weakness instead of allowing different trigger dates.",
        "theme_index": "daily rebalanced equal-weight arithmetic constituent returns, compounded through time",
        "significance": "95% cluster bootstrap by signal date and separately by theme; weak-parent incremental alpha requires weak-minus-not-weak SPY excess lower bound > 0 in both cluster schemes.",
        "analysis_window": [args.analysis_start, args.analysis_end],
        "download": download_diag,
        "taxonomy_candidates": taxonomy_candidates,
        "coverage": {
            "themes_current_taxonomy": len(theme_members_all),
            "themes_with_downloaded_min_members": int(len(theme_ret.columns)),
            "industries_with_downloaded_min_members": int(len(industry_ret.columns)),
            "selected_stock_symbols": len(selected),
            "downloaded_stock_symbols": len(stock_cols),
        },
        "events": {
            "momentum_all": int(len(outcomes)),
            "parent_weak": int(len(weak)),
            "parent_not_weak": int(len(not_weak)),
            "event_dates": int(outcomes["date"].nunique()) if not outcomes.empty else 0,
            "themes": int(outcomes["theme"].nunique()) if not outcomes.empty else 0,
        },
        "momentum_all": group_summary(outcomes),
        "parent_weak": group_summary(weak),
        "parent_not_weak": group_summary(not_weak),
        "incremental_parent_weakness": compare_groups(outcomes),
    }

    outcomes.to_csv(output / "momentum_events_with_outcomes.csv", index=False)
    (output / "summary.json").write_text(json.dumps(safe(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== MOMENTUM_PARENT_COMPARISON_JSON ===")
    print(json.dumps(safe(result), ensure_ascii=False, indent=2))
    print("=== END_MOMENTUM_PARENT_COMPARISON_JSON ===", flush=True)


if __name__ == "__main__":
    main()
