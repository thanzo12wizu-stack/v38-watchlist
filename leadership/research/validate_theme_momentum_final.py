from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import validate_confirmed_leadership as cl
import validate_early_rotation as er

HORIZONS = (5, 10, 20, 63)
DISCOVERY_END = pd.Timestamp("2021-12-31")
VALIDATION_START = pd.Timestamp("2022-01-01")
VALIDATION_END = pd.Timestamp("2026-06-30")


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


def block20_ids(dates: pd.Series, trading_index: pd.DatetimeIndex) -> pd.Series:
    pos = pd.Series(np.arange(len(trading_index), dtype=int), index=trading_index)
    vals = []
    for d in pd.to_datetime(dates):
        p = pos.get(pd.Timestamp(d), np.nan)
        vals.append(int(p // 20) if pd.notna(p) else np.nan)
    return pd.Series(vals, index=dates.index)


def cluster_mean_ci(frame: pd.DataFrame, metric: str, cluster: str, seed: int, reps: int) -> list[float | None]:
    use = frame[[cluster, metric]].dropna()
    if use.empty:
        return [None, None]
    agg = use.groupby(cluster, observed=True)[metric].agg(["sum", "count"])
    if len(agg) < 2:
        return [None, None]
    sums = agg["sum"].to_numpy(float)
    counts = agg["count"].to_numpy(float)
    k = len(agg)
    rng = np.random.default_rng(seed)
    draws: list[np.ndarray] = []
    chunk = 250
    for start in range(0, reps, chunk):
        n = min(chunk, reps - start)
        idx = rng.integers(0, k, size=(n, k))
        draws.append(sums[idx].sum(axis=1) / counts[idx].sum(axis=1))
    values = np.concatenate(draws)
    lo, hi = np.quantile(values, [0.025, 0.975])
    return [float(lo), float(hi)]


def stats(frame: pd.DataFrame, metric: str, reps: int, seed: int) -> dict[str, Any]:
    use = frame[["date", "theme", "block20", metric]].dropna(subset=[metric]).copy()
    s = pd.to_numeric(use[metric], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    use = use.loc[s.index]
    if use.empty:
        return {"n": 0, "mean": None}
    return {
        "n": int(len(s)),
        "dates": int(use["date"].nunique()),
        "themes": int(use["theme"].nunique()),
        "blocks20": int(use["block20"].nunique()),
        "mean": float(s.mean()),
        "median": float(s.median()),
        "positive_rate": float((s > 0).mean()),
        "block20_ci95": cluster_mean_ci(use, metric, "block20", seed, reps),
        "date_ci95": cluster_mean_ci(use, metric, "date", seed + 100, reps),
        "theme_ci95": cluster_mean_ci(use, metric, "theme", seed + 200, reps),
    }


def subset_report(outcomes: pd.DataFrame, reps: int, seed: int) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for h in HORIZONS:
        result[f"{h}d_spy_excess"] = stats(outcomes, f"spy_excess_{h}", reps, seed + h)
    return result


def selected_symbols(theme_members: dict[str, list[str]], industry_map: dict[str, tuple[str, str]], universe: set[str]) -> list[str]:
    mapped = {s for members in theme_members.values() for s in members}
    return sorted(mapped & set(industry_map) & universe)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--root", default=".")
    p.add_argument("--output", default="leadership/research/theme_momentum_final")
    p.add_argument("--analysis-start", default="2016-01-04")
    p.add_argument("--analysis-end", default="2026-06-30")
    p.add_argument("--batch-size", type=int, default=75)
    p.add_argument("--min-members", type=int, default=3)
    p.add_argument("--bootstrap", type=int, default=3000)
    args = p.parse_args()

    root = Path(args.root)
    output = root / args.output
    output.mkdir(parents=True, exist_ok=True)

    snapshot = er.load_json(root / "sector_snapshot.json")
    theme_members_all, taxonomy_candidates = er.extract_theme_members(snapshot)
    industry_map = er.read_industry_map(root / "industry_map.json")
    universe = er.read_universe_symbols(root / "universe.csv")
    selected = selected_symbols(theme_members_all, industry_map, universe)
    requested = selected + (["SPY"] if "SPY" not in selected else [])

    download_start = str((pd.Timestamp(args.analysis_start) - pd.Timedelta(days=380)).date())
    download_end = str((pd.Timestamp(args.analysis_end) + pd.Timedelta(days=100)).date())
    close, download_diag = er.download_adjusted_close(requested, download_start, download_end, args.batch_size)
    if "SPY" not in close.columns:
        raise RuntimeError("SPY benchmark missing")

    stock_cols = [s for s in selected if s in close.columns]
    stock_close = close[stock_cols]
    stock_ret = er.arithmetic_returns(stock_close)
    spy_ret = er.arithmetic_returns(close[["SPY"]])["SPY"]

    theme_members = {t: [s for s in members if s in stock_cols] for t, members in theme_members_all.items()}
    member_counts = {t: len(members) for t, members in theme_members.items()}
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

    theme63 = er.period_return(theme_ret, 63)
    spy63 = er.period_return(spy_ret, 63)
    theme_pct = theme63.sub(spy63, axis=0).rank(axis=1, pct=True, method="average") * 100.0
    industry63 = er.period_return(industry_ret, 63)
    industry_pct = industry63.sub(spy63, axis=0).rank(axis=1, pct=True, method="average") * 100.0
    parent_pct = er.weighted_matrix(industry_pct, parent_weights, common_themes)
    breadth = er.breadth_above_ema21(stock_close, theme_members, args.min_members).reindex(columns=common_themes)

    mask = cl.momentum_mask(theme_pct, parent_pct, breadth)
    events = er.extract_events(
        mask,
        theme_pct,
        parent_pct,
        breadth,
        member_counts,
        pd.Timestamp(args.analysis_start),
        pd.Timestamp(args.analysis_end),
        cooldown=20,
    )

    theme_fwd = {h: er.forward_return(theme_ret, h) for h in HORIZONS}
    spy_fwd = {h: er.forward_return(spy_ret, h) for h in HORIZONS}
    parent_fwd = {h: er.forward_return(parent_ret, h) for h in HORIZONS}
    outcomes = er.attach_outcomes(events, HORIZONS, theme_fwd, spy_fwd, parent_fwd, theme_pct, parent_pct)
    outcomes["block20"] = block20_ids(outcomes["date"], theme_pct.index)

    discovery = outcomes[pd.to_datetime(outcomes["date"]) <= DISCOVERY_END].copy()
    validation = outcomes[(pd.to_datetime(outcomes["date"]) >= VALIDATION_START) & (pd.to_datetime(outcomes["date"]) <= VALIDATION_END)].copy()

    report = {
        "status": "FINAL_CURRENT_TAXONOMY_FULL_UNIVERSE_VALIDATION",
        "rule": {
            "theme_rs_min": 80.0,
            "theme_rs_20d_delta_min": 15.0,
            "breadth_above_ema21_min": 60.0,
            "event": "first qualifying day after inactive state",
            "theme_cooldown_sessions": 20,
        },
        "anti_overlap": {
            "one_theme_event_one_observation": True,
            "cooldown_sessions": 20,
            "block_bootstrap_sessions": 20,
            "clusters": ["date", "theme"],
        },
        "coverage": {
            "source_universe": len(universe),
            "mapped_selected": len(selected),
            "downloaded_stocks": len(stock_cols),
            "themes": int(outcomes["theme"].nunique()) if not outcomes.empty else 0,
            "events": int(len(outcomes)),
            "event_dates": int(outcomes["date"].nunique()) if not outcomes.empty else 0,
        },
        "download": download_diag,
        "taxonomy_candidates": taxonomy_candidates,
        "discovery_2016_2021": subset_report(discovery, args.bootstrap, 1000),
        "validation_2022_2026H1": subset_report(validation, args.bootstrap, 2000),
    }

    v10 = report["validation_2022_2026H1"]["10d_spy_excess"]
    cis = [v10.get("block20_ci95"), v10.get("date_ci95"), v10.get("theme_ci95")]
    report["decision"] = {
        "adopt_theme_activation": bool(
            (v10.get("n") or 0) >= 300
            and (v10.get("mean") or -999.0) >= 0.003
            and all(ci and ci[0] is not None and ci[0] > 0 for ci in cis)
        ),
        "primary_horizon": "10d",
        "threshold": "validation mean >= +0.30% vs SPY, n>=300, and lower 95% CI >0 for 20d block/date/theme clusters",
    }

    outcomes.to_csv(output / "events.csv", index=False)
    (output / "summary.json").write_text(json.dumps(safe(report), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("=== THEME_MOMENTUM_FINAL ===")
    print(json.dumps(safe(report), ensure_ascii=False, indent=2))
    print("=== END_THEME_MOMENTUM_FINAL ===", flush=True)


if __name__ == "__main__":
    main()
