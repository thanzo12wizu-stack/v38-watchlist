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
PARENT_BANDS = [
    ("PARENT_0_40", 0.0, 40.0),
    ("PARENT_40_60", 40.0, 60.0),
    ("PARENT_60_80", 60.0, 80.0),
    ("PARENT_80_100", 80.0, 100.000001),
]


def momentum_mask(theme_pct: pd.DataFrame, parent_pct: pd.DataFrame, breadth: pd.DataFrame) -> pd.DataFrame:
    common = theme_pct.columns.intersection(parent_pct.columns).intersection(breadth.columns)
    t = theme_pct[common]
    b = breadth[common]
    delta20 = t - t.shift(20)
    return (
        (t >= MOMENTUM_CONFIG["theme_min"])
        & (delta20 >= MOMENTUM_CONFIG["delta20_min"])
        & (b >= MOMENTUM_CONFIG["breadth_min"])
    )


def assign_parent_band(value: float) -> str:
    for label, lo, hi in PARENT_BANDS:
        if lo <= value < hi:
            return label
    return "UNASSIGNED"


def slope_formula(n: float, sx: float, sy: float, sxx: float, sxy: float) -> float | None:
    den = sxx - (sx * sx / n) if n > 0 else 0.0
    if n <= 1 or abs(den) < 1e-12:
        return None
    return (sxy - (sx * sy / n)) / den


def clustered_slope(values: pd.DataFrame, metric: str, cluster: str, seed: int, reps: int = 4000) -> dict[str, Any]:
    use = values[[cluster, "parent_rs_pct", metric]].dropna().copy()
    if len(use) < 3:
        return {"slope_per_20_parent_rs": None, "ci95": [None, None], "clusters": 0}
    use["x"] = use["parent_rs_pct"] / 20.0
    use["y"] = use[metric]
    use["x2"] = use["x"] * use["x"]
    use["xy"] = use["x"] * use["y"]
    grouped = use.groupby(cluster, observed=True).agg(
        n=("y", "size"), sx=("x", "sum"), sy=("y", "sum"), sxx=("x2", "sum"), sxy=("xy", "sum")
    )
    arrays = {c: grouped[c].to_numpy(float) for c in ("n", "sx", "sy", "sxx", "sxy")}
    point = slope_formula(
        float(arrays["n"].sum()),
        float(arrays["sx"].sum()),
        float(arrays["sy"].sum()),
        float(arrays["sxx"].sum()),
        float(arrays["sxy"].sum()),
    )
    rng = np.random.default_rng(seed)
    k = len(grouped)
    samples: list[float] = []
    for _ in range(reps):
        idx = rng.integers(0, k, size=k)
        slope = slope_formula(
            float(arrays["n"][idx].sum()),
            float(arrays["sx"][idx].sum()),
            float(arrays["sy"][idx].sum()),
            float(arrays["sxx"][idx].sum()),
            float(arrays["sxy"][idx].sum()),
        )
        if slope is not None and math.isfinite(slope):
            samples.append(float(slope))
    if not samples:
        return {"slope_per_20_parent_rs": point, "ci95": [None, None], "clusters": k}
    lo, hi = np.quantile(np.asarray(samples), [0.025, 0.975])
    return {"slope_per_20_parent_rs": point, "ci95": [float(lo), float(hi)], "clusters": k}


def high_minus_low(values: pd.DataFrame, metric: str, cluster: str, seed: int, reps: int = 4000) -> dict[str, Any]:
    use = values[[cluster, "parent_rs_pct", metric]].dropna().copy()
    use["group"] = np.where(use["parent_rs_pct"] >= 80.0, "HIGH", np.where(use["parent_rs_pct"] < 60.0, "LOW", "MID"))
    use = use[use["group"] != "MID"]
    high = use.loc[use["group"] == "HIGH", metric]
    low = use.loc[use["group"] == "LOW", metric]
    if high.empty or low.empty:
        return {"high_minus_low": None, "ci95": [None, None], "clusters": 0}
    point = float(high.mean() - low.mean())
    agg = use.groupby([cluster, "group"], observed=True)[metric].agg(["sum", "count"]).reset_index()
    clusters = list(pd.unique(use[cluster]))
    pos = {k: i for i, k in enumerate(clusters)}
    hs = np.zeros(len(clusters), dtype=float)
    hc = np.zeros(len(clusters), dtype=float)
    ls = np.zeros(len(clusters), dtype=float)
    lc = np.zeros(len(clusters), dtype=float)
    for row in agg.itertuples(index=False):
        i = pos[getattr(row, cluster)]
        if row.group == "HIGH":
            hs[i], hc[i] = float(row.sum), float(row.count)
        else:
            ls[i], lc[i] = float(row.sum), float(row.count)
    rng = np.random.default_rng(seed)
    k = len(clusters)
    samples: list[float] = []
    for _ in range(reps):
        idx = rng.integers(0, k, size=k)
        hcount = hc[idx].sum()
        lcount = lc[idx].sum()
        if hcount <= 0 or lcount <= 0:
            continue
        samples.append(float(hs[idx].sum() / hcount - ls[idx].sum() / lcount))
    if not samples:
        return {"high_minus_low": point, "ci95": [None, None], "clusters": k}
    lo, hi = np.quantile(np.asarray(samples), [0.025, 0.975])
    return {"high_minus_low": point, "ci95": [float(lo), float(hi)], "clusters": k}


def band_table(outcomes: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for label, lo, hi in PARENT_BANDS:
        part = outcomes[outcomes["parent_band"] == label]
        row: dict[str, Any] = {
            "parent_band": label,
            "range": [lo, 100.0 if hi > 100 else hi],
            "events": int(len(part)),
            "dates": int(part["date"].nunique()) if not part.empty else 0,
            "themes": int(part["theme"].nunique()) if not part.empty else 0,
        }
        for h in HORIZONS:
            for metric in (f"spy_excess_{h}", f"parent_excess_{h}", f"median_theme_excess_{h}", f"rs_delta_{h}"):
                s = part[metric].dropna()
                row[f"{metric}_mean"] = float(s.mean()) if len(s) else None
                row[f"{metric}_median"] = float(s.median()) if len(s) else None
                row[f"{metric}_positive_rate"] = float((s > 0).mean()) if len(s) else None
            top = part[f"top20_retained_{h}"].dropna()
            row[f"top20_retained_{h}"] = float(top.mean()) if len(top) else None
        rows.append(row)
    return rows


def monotonic_flags(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for h in HORIZONS:
        vals = [r.get(f"spy_excess_{h}_mean") for r in rows]
        ok = all(v is not None for v in vals)
        result[str(h)] = {
            "spy_excess_means_by_parent_band": vals,
            "non_decreasing": bool(ok and all(vals[i] <= vals[i + 1] for i in range(len(vals) - 1))),
        }
    return result


def trend_tests(outcomes: pd.DataFrame) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for h in HORIZONS:
        metrics: dict[str, Any] = {}
        for metric in (f"spy_excess_{h}", f"parent_excess_{h}", f"median_theme_excess_{h}", f"rs_delta_{h}"):
            date_slope = clustered_slope(outcomes, metric, "date", seed=1000 + h)
            theme_slope = clustered_slope(outcomes, metric, "theme", seed=2000 + h)
            date_diff = high_minus_low(outcomes, metric, "date", seed=3000 + h)
            theme_diff = high_minus_low(outcomes, metric, "theme", seed=4000 + h)
            metrics[metric] = {
                "slope_per_20_parent_rs": date_slope["slope_per_20_parent_rs"],
                "slope_date_cluster_ci95": date_slope["ci95"],
                "slope_theme_cluster_ci95": theme_slope["ci95"],
                "parent_ge80_minus_lt60": date_diff["high_minus_low"],
                "difference_date_cluster_ci95": date_diff["ci95"],
                "difference_theme_cluster_ci95": theme_diff["ci95"],
            }
        spy = metrics[f"spy_excess_{h}"]
        metrics["confirmed_leadership_supported_for_spy_alpha"] = bool(
            spy["slope_date_cluster_ci95"][0] is not None
            and spy["slope_theme_cluster_ci95"][0] is not None
            and spy["difference_date_cluster_ci95"][0] is not None
            and spy["difference_theme_cluster_ci95"][0] is not None
            and spy["slope_date_cluster_ci95"][0] > 0
            and spy["slope_theme_cluster_ci95"][0] > 0
            and spy["difference_date_cluster_ci95"][0] > 0
            and spy["difference_theme_cluster_ci95"][0] > 0
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
    parser.add_argument("--output", default="leadership/research/confirmed_output")
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
    outcomes["parent_band"] = outcomes["parent_rs_pct"].map(assign_parent_band)

    bands = band_table(outcomes)
    trends = trend_tests(outcomes)
    result = {
        "status": "PRELIMINARY_FIXED_CURRENT_TAXONOMY",
        "question": "Within the same Subtheme Momentum trigger, does stronger parent Industry RS improve forward outcomes?",
        "bias_warning": "Current ticker→theme and ticker→industry memberships are applied retrospectively. This is hypothesis filtering, not final survivorship/look-ahead-free proof.",
        "momentum_definition_frozen_before_outcomes": MOMENTUM_CONFIG,
        "parent_bands_frozen_before_outcomes": [{"label": a, "min": b, "max_exclusive": 100.0 if c > 100 else c} for a, b, c in PARENT_BANDS],
        "event_policy": "Momentum-only first qualifying day after inactive state, 20-trading-day per-theme cooldown. Parent strength is observed on that same signal day and does not alter trigger timing.",
        "primary_tests": "Continuous parent-RS slope per +20 percentile points and parent RS >=80 minus parent RS <60, each with 95% cluster bootstrap by signal date and separately by theme.",
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
            "event_dates": int(outcomes["date"].nunique()) if not outcomes.empty else 0,
            "themes": int(outcomes["theme"].nunique()) if not outcomes.empty else 0,
        },
        "parent_band_results": bands,
        "monotonicity": monotonic_flags(bands),
        "trend_tests": trends,
    }

    outcomes.to_csv(output / "confirmed_leadership_events.csv", index=False)
    pd.DataFrame(bands).to_csv(output / "parent_band_results.csv", index=False)
    (output / "summary.json").write_text(json.dumps(safe(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== CONFIRMED_LEADERSHIP_RESULT_JSON ===")
    print(json.dumps(safe(result), ensure_ascii=False, indent=2))
    print("=== END_CONFIRMED_LEADERSHIP_RESULT_JSON ===", flush=True)


if __name__ == "__main__":
    main()
