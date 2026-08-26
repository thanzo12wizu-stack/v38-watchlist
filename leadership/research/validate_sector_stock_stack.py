from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import validate_early_rotation as er
import validate_confirmed_leadership as cl
import validate_pioneer_leader as pl
import validate_rs_periods as rs

HORIZONS = (5, 10, 20)
DISCOVERY_END = pd.Timestamp("2021-12-31")
CONFIRM_START = pd.Timestamp("2022-01-01")

EVENT_CONTEXTS = {
    "ALL": lambda x: pd.Series(True, index=x.index),
    "SECTOR_GE60": lambda x: x["sector_rs_pct"] >= 60.0,
    "SECTOR_GE80": lambda x: x["sector_rs_pct"] >= 80.0,
    "INDUSTRY_GE60": lambda x: x["parent_rs_pct"] >= 60.0,
    "INDUSTRY_GE80": lambda x: x["parent_rs_pct"] >= 80.0,
    "ALIGNED_GE60": lambda x: (x["sector_rs_pct"] >= 60.0) & (x["parent_rs_pct"] >= 60.0),
    "ALIGNED_GE80": lambda x: (x["sector_rs_pct"] >= 80.0) & (x["parent_rs_pct"] >= 80.0),
    "SECTOR80_INDUSTRY_LT60": lambda x: (x["sector_rs_pct"] >= 80.0) & (x["parent_rs_pct"] < 60.0),
    "SECTOR_LT60_INDUSTRY80": lambda x: (x["sector_rs_pct"] < 60.0) & (x["parent_rs_pct"] >= 80.0),
}

STOCK_STRATEGIES = {
    "ALL_STOCKS": lambda x: pd.Series(True, index=x.index),
    "LEADER252_TOP20": lambda x: x["RS252"] >= 0.80,
    "MID126_TOP33": lambda x: x["RS126"] >= (2.0 / 3.0),
    "IGNITION21_TOP33": lambda x: x["RS21"] >= (2.0 / 3.0),
    "ACCEL21_DELTA15": lambda x: x["RS21_DELTA20"] >= 0.15,
    "LEADER252_IGNITION21": lambda x: (x["RS252"] >= 0.80) & (x["RS21"] >= (2.0 / 3.0)),
    "LEADER252_ACCEL21": lambda x: (x["RS252"] >= 0.80) & (x["RS21_DELTA20"] >= 0.15),
    "LEADER252_IGNITION_ACCEL": lambda x: (
        (x["RS252"] >= 0.80)
        & (x["RS21"] >= (2.0 / 3.0))
        & (x["RS21_DELTA20"] >= 0.15)
    ),
}


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


def build_sector_weights(theme_members: dict[str, list[str]], industry_map: dict[str, tuple[str, str]], max_sectors: int = 2) -> dict[str, list[tuple[str, float]]]:
    out: dict[str, list[tuple[str, float]]] = {}
    for theme, members in theme_members.items():
        counts = Counter(industry_map[s][0] for s in members if s in industry_map and industry_map[s][0])
        top = counts.most_common(max_sectors)
        total = sum(n for _, n in top)
        if total:
            out[theme] = [(sector, n / total) for sector, n in top]
    return out


def cluster_ci(table: pd.DataFrame, value_col: str, cluster_col: str, seed: int, reps: int = 3000) -> list[float | None]:
    use = table[[cluster_col, value_col]].dropna()
    if use.empty:
        return [None, None]
    grouped = use.groupby(cluster_col, observed=True)[value_col].mean().to_numpy(float)
    if len(grouped) < 2:
        return [None, None]
    rng = np.random.default_rng(seed)
    draws = rng.choice(grouped, size=(reps, len(grouped)), replace=True).mean(axis=1)
    lo, hi = np.quantile(draws, [0.025, 0.975])
    return [float(lo), float(hi)]


def summarize_event_metric(table: pd.DataFrame, value_col: str, seed: int) -> dict[str, Any]:
    use = table[["event_id", "date", "theme", value_col]].dropna()
    if use.empty:
        return {"n": 0, "mean": None, "median": None, "positive_rate": None, "date_ci95": [None, None], "theme_ci95": [None, None], "discovery_mean": None, "confirmation_mean": None}
    disc = use.loc[use["date"] <= DISCOVERY_END, value_col]
    conf = use.loc[use["date"] >= CONFIRM_START, value_col]
    return {
        "n": int(len(use)),
        "dates": int(use["date"].nunique()),
        "themes": int(use["theme"].nunique()),
        "mean": float(use[value_col].mean()),
        "median": float(use[value_col].median()),
        "positive_rate": float((use[value_col] > 0).mean()),
        "date_ci95": cluster_ci(use, value_col, "date", seed),
        "theme_ci95": cluster_ci(use, value_col, "theme", seed + 1000),
        "discovery_mean": float(disc.mean()) if len(disc) else None,
        "confirmation_mean": float(conf.mean()) if len(conf) else None,
    }


def add_rs21_delta20(rows: pd.DataFrame, events: pd.DataFrame, theme_members: dict[str, list[str]], stock_period21: pd.DataFrame, stock_close: pd.DataFrame) -> pd.DataFrame:
    date_pos = {pd.Timestamp(d): i for i, d in enumerate(stock_close.index)}
    records: list[dict[str, Any]] = []
    for event in events.itertuples(index=False):
        date = pd.Timestamp(event.date)
        theme = str(event.theme)
        pos = date_pos.get(date, -1)
        if pos < 20:
            continue
        prev_date = stock_close.index[pos - 20]
        members = [s for s in theme_members.get(theme, []) if s in stock_period21.columns]
        if len(members) < 3 or date not in stock_period21.index or prev_date not in stock_period21.index:
            continue
        cur = rs.rank_within(stock_period21.loc[date, members])
        prev = rs.rank_within(stock_period21.loc[prev_date, members])
        delta = cur - prev
        event_id = f"{date.date()}|{theme}"
        for sym, value in delta.items():
            if pd.notna(value):
                records.append({"event_id": event_id, "symbol": sym, "RS21_DELTA20": float(value)})
    if not records:
        rows = rows.copy()
        rows["RS21_DELTA20"] = np.nan
        return rows
    delta_df = pd.DataFrame(records).drop_duplicates(["event_id", "symbol"])
    return rows.merge(delta_df, on=["event_id", "symbol"], how="left")


def high_low_event_test(event_table: pd.DataFrame, signal_col: str, metric: str, seed: int) -> dict[str, Any]:
    use = event_table[["event_id", "date", "theme", signal_col, metric]].dropna().copy()
    high = use[use[signal_col] >= 80.0].copy()
    low = use[use[signal_col] < 60.0].copy()
    if high.empty or low.empty:
        return {"high_n": int(len(high)), "low_n": int(len(low)), "high_minus_low": None, "date_ci95": [None, None], "theme_ci95": [None, None]}
    point = float(high[metric].mean() - low[metric].mean())
    joined = pd.concat([high.assign(group="HIGH"), low.assign(group="LOW")], ignore_index=True)

    def diff_by_cluster(cluster: str, seed0: int) -> list[float | None]:
        agg = joined.groupby([cluster, "group"], observed=True)[metric].agg(["sum", "count"]).reset_index()
        clusters = list(pd.unique(joined[cluster]))
        pos = {c: i for i, c in enumerate(clusters)}
        hs = np.zeros(len(clusters)); hc = np.zeros(len(clusters)); ls = np.zeros(len(clusters)); lc = np.zeros(len(clusters))
        for row in agg.itertuples(index=False):
            i = pos[getattr(row, cluster)]
            if row.group == "HIGH":
                hs[i], hc[i] = float(row.sum), float(row.count)
            else:
                ls[i], lc[i] = float(row.sum), float(row.count)
        rng = np.random.default_rng(seed0)
        vals: list[float] = []
        k = len(clusters)
        for _ in range(3000):
            idx = rng.integers(0, k, size=k)
            if hc[idx].sum() <= 0 or lc[idx].sum() <= 0:
                continue
            vals.append(float(hs[idx].sum() / hc[idx].sum() - ls[idx].sum() / lc[idx].sum()))
        if not vals:
            return [None, None]
        lo, hi = np.quantile(vals, [0.025, 0.975])
        return [float(lo), float(hi)]

    return {"high_n": int(len(high)), "low_n": int(len(low)), "high_minus_low": point, "date_ci95": diff_by_cluster("date", seed), "theme_ci95": diff_by_cluster("theme", seed + 1000)}


def strategy_event_table(rows: pd.DataFrame, strategy_name: str, horizon: int) -> pd.DataFrame:
    metric_peer = f"stock_minus_peers_{horizon}"
    metric_spy = f"stock_minus_spy_{horizon}"
    metric_mfe = f"mfe_{horizon}"
    metric_mae = f"mae_{horizon}"
    base = rows.groupby(["event_id", "date", "theme"], observed=True).agg(
        baseline_peer=(metric_peer, "mean"), baseline_spy=(metric_spy, "mean"), baseline_mfe=(metric_mfe, "mean"), baseline_mae=(metric_mae, "mean"), eligible_stocks=("symbol", "nunique")
    ).reset_index()
    mask = STOCK_STRATEGIES[strategy_name](rows).fillna(False)
    chosen = rows[mask].copy()
    if chosen.empty:
        return pd.DataFrame()
    sel = chosen.groupby(["event_id", "date", "theme"], observed=True).agg(
        selected_peer=(metric_peer, "mean"), selected_spy=(metric_spy, "mean"), selected_mfe=(metric_mfe, "mean"), selected_mae=(metric_mae, "mean"), selected_stocks=("symbol", "nunique")
    ).reset_index()
    out = base.merge(sel, on=["event_id", "date", "theme"], how="inner")
    out["peer_lift"] = out["selected_peer"] - out["baseline_peer"]
    out["spy_lift"] = out["selected_spy"] - out["baseline_spy"]
    out["mfe_lift"] = out["selected_mfe"] - out["baseline_mfe"]
    out["mae_lift"] = out["selected_mae"] - out["baseline_mae"]
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", default="leadership/research/sector_stock_output")
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
    download_start = str((pd.Timestamp(args.analysis_start) - pd.Timedelta(days=520)).date())
    download_end = str((pd.Timestamp(args.analysis_end) + pd.Timedelta(days=120)).date())
    ohlcv, download_diag = pl.download_ohlcv(requested, download_start, download_end, args.batch_size)
    close = ohlcv["close"]
    if "SPY" not in close.columns:
        raise RuntimeError("SPY benchmark missing")
    stock_cols = [s for s in selected if s in close.columns]
    stock_close = close[stock_cols]
    stock_high = ohlcv["high"][stock_cols]
    stock_low = ohlcv["low"][stock_cols]
    stock_ret = er.arithmetic_returns(stock_close)
    spy_ret = er.arithmetic_returns(close[["SPY"]])["SPY"]
    theme_members = {t: [s for s in members if s in stock_cols] for t, members in theme_members_all.items()}
    member_counts = {t: len(members) for t, members in theme_members.items()}
    theme_ret = er.grouped_equal_weight(stock_ret, theme_members, args.min_members)

    industry_groups: dict[str, list[str]] = {}
    sector_groups: dict[str, list[str]] = {}
    for sym in stock_cols:
        pair = industry_map.get(sym)
        if not pair:
            continue
        sector, industry = pair
        if sector:
            sector_groups.setdefault(sector, []).append(sym)
        if industry:
            industry_groups.setdefault(industry, []).append(sym)
    industry_ret = er.grouped_equal_weight(stock_ret, industry_groups, args.min_members)
    sector_ret = er.grouped_equal_weight(stock_ret, sector_groups, args.min_members)
    industry_weights = er.build_parent_weights(theme_members_all, industry_map)
    sector_weights = build_sector_weights(theme_members_all, industry_map)
    common_themes = sorted(set(theme_ret.columns) & set(industry_weights) & set(sector_weights))
    theme_ret = theme_ret[common_themes]
    theme63 = er.period_return(theme_ret, 63)
    spy63 = er.period_return(spy_ret, 63)
    theme_pct = theme63.sub(spy63, axis=0).rank(axis=1, pct=True, method="average") * 100.0
    industry63 = er.period_return(industry_ret, 63)
    industry_pct = industry63.sub(spy63, axis=0).rank(axis=1, pct=True, method="average") * 100.0
    parent_industry_pct = er.weighted_matrix(industry_pct, industry_weights, common_themes)
    sector63 = er.period_return(sector_ret, 63)
    sector_pct = sector63.sub(spy63, axis=0).rank(axis=1, pct=True, method="average") * 100.0
    parent_sector_pct = er.weighted_matrix(sector_pct, sector_weights, common_themes)
    breadth = er.breadth_above_ema21(stock_close, theme_members, args.min_members).reindex(columns=common_themes)
    start, end = pd.Timestamp(args.analysis_start), pd.Timestamp(args.analysis_end)
    mask = cl.momentum_mask(theme_pct, parent_industry_pct, breadth)
    events = er.extract_events(mask, theme_pct, parent_industry_pct, breadth, member_counts, start, end)
    events["sector_rs_pct"] = [
        float(parent_sector_pct.at[pd.Timestamp(d), str(t)]) if str(t) in parent_sector_pct.columns and pd.Timestamp(d) in parent_sector_pct.index and pd.notna(parent_sector_pct.at[pd.Timestamp(d), str(t)]) else np.nan
        for d, t in zip(events["date"], events["theme"])
    ]

    stock_period = {p: er.period_return(stock_ret, p) for p in rs.RS_PERIODS}
    rows = rs.extract_rows(events, theme_members, stock_close, stock_high, stock_low, stock_ret, spy_ret, stock_period)
    event_meta = events.assign(event_id=events.apply(lambda r: f"{pd.Timestamp(r['date']).date()}|{r['theme']}", axis=1))[["event_id", "sector_rs_pct"]]
    rows = rows.merge(event_meta, on="event_id", how="left")
    rows = add_rs21_delta20(rows, events, theme_members, stock_period[21], stock_close)

    result: dict[str, Any] = {
        "status": "PRELIMINARY_FIXED_CURRENT_TAXONOMY",
        "question": "Does broad Sector + Industry alignment add statistically useful information to Subtheme Momentum and stock leader/ignition selection?",
        "frozen_definitions": {
            "subtheme_momentum": cl.MOMENTUM_CONFIG,
            "sector_rs": "63d equal-weight constituent TradingView Sector return vs SPY, cross-Sector percentile, then theme constituent-weighted parent Sector percentile",
            "industry_rs": "63d equal-weight constituent TradingView Industry return vs SPY, cross-Industry percentile, then theme constituent-weighted parent Industry percentile",
            "sector_industry_strength_thresholds": [60, 80],
            "stock_strategies": list(STOCK_STRATEGIES),
            "horizons": list(HORIZONS),
        },
        "coverage": {"selected_stocks": len(stock_cols), "events": int(len(events)), "event_stock_rows": int(len(rows)), "themes": int(events["theme"].nunique()), "dates": int(events["date"].nunique()), "sector_groups": int(len(sector_ret.columns)), "industry_groups": int(len(industry_ret.columns))},
        "download": download_diag,
        "taxonomy_candidates": taxonomy_candidates,
        "event_layer_tests": {},
        "stock_selection_tests": {},
    }

    event_base = rows.groupby(["event_id", "date", "theme"], observed=True).agg(
        sector_rs_pct=("sector_rs_pct", "first"), parent_rs_pct=("parent_rs_pct", "first"), theme_rs_pct=("theme_rs_pct", "first"),
        **{f"spy_excess_{h}": (f"stock_minus_spy_{h}", "mean") for h in HORIZONS},
        **{f"mfe_{h}": (f"mfe_{h}", "mean") for h in HORIZONS},
        **{f"mae_{h}": (f"mae_{h}", "mean") for h in HORIZONS},
    ).reset_index()

    for h in HORIZONS:
        hres: dict[str, Any] = {
            "sector_ge80_minus_lt60": high_low_event_test(event_base, "sector_rs_pct", f"spy_excess_{h}", 1000 + h),
            "industry_ge80_minus_lt60": high_low_event_test(event_base, "parent_rs_pct", f"spy_excess_{h}", 2000 + h),
            "contexts": {},
        }
        for name, fn in EVENT_CONTEXTS.items():
            part = event_base[fn(event_base).fillna(False)].copy()
            hres["contexts"][name] = {
                "events": int(len(part)),
                "spy_excess": summarize_event_metric(part.rename(columns={f"spy_excess_{h}": "value"}), "value", 3000 + h),
                "mfe": summarize_event_metric(part.rename(columns={f"mfe_{h}": "value"}), "value", 4000 + h),
                "mae": summarize_event_metric(part.rename(columns={f"mae_{h}": "value"}), "value", 5000 + h),
            }
        result["event_layer_tests"][str(h)] = hres

    for context_name, context_fn in EVENT_CONTEXTS.items():
        context_rows = rows[context_fn(rows).fillna(False)].copy()
        cres: dict[str, Any] = {"rows": int(len(context_rows)), "events": int(context_rows["event_id"].nunique()), "horizons": {}}
        for h in HORIZONS:
            sh: dict[str, Any] = {}
            for strategy in STOCK_STRATEGIES:
                tab = strategy_event_table(context_rows, strategy, h)
                sh[strategy] = {
                    "events": int(len(tab)),
                    "mean_selected_stocks": float(tab["selected_stocks"].mean()) if len(tab) else None,
                    "peer_lift": summarize_event_metric(tab, "peer_lift", 6000 + h + len(strategy)),
                    "spy_lift": summarize_event_metric(tab, "spy_lift", 7000 + h + len(strategy)),
                    "mfe_lift": summarize_event_metric(tab, "mfe_lift", 8000 + h + len(strategy)),
                    "mae_lift": summarize_event_metric(tab, "mae_lift", 9000 + h + len(strategy)),
                }
            cres["horizons"][str(h)] = sh
        result["stock_selection_tests"][context_name] = cres

    safe_result = safe(result)
    rows.to_csv(output / "sector_stock_event_rows.csv.gz", index=False, compression="gzip")
    (output / "summary.json").write_text(json.dumps(safe_result, ensure_ascii=False, indent=2), encoding="utf-8")
    compact = {
        "status": safe_result["status"],
        "coverage": safe_result["coverage"],
        "event_layer_tests": safe_result["event_layer_tests"],
        "stock_selection_tests": {
            c: {
                h: {
                    s: {
                        "events": safe_result["stock_selection_tests"][c]["horizons"][h][s]["events"],
                        "peer_lift_mean": safe_result["stock_selection_tests"][c]["horizons"][h][s]["peer_lift"]["mean"],
                        "peer_lift_date_ci95": safe_result["stock_selection_tests"][c]["horizons"][h][s]["peer_lift"]["date_ci95"],
                        "peer_lift_theme_ci95": safe_result["stock_selection_tests"][c]["horizons"][h][s]["peer_lift"]["theme_ci95"],
                        "spy_lift_mean": safe_result["stock_selection_tests"][c]["horizons"][h][s]["spy_lift"]["mean"],
                        "mfe_lift_mean": safe_result["stock_selection_tests"][c]["horizons"][h][s]["mfe_lift"]["mean"],
                        "mae_lift_mean": safe_result["stock_selection_tests"][c]["horizons"][h][s]["mae_lift"]["mean"],
                    }
                    for s in STOCK_STRATEGIES
                }
                for h in map(str, HORIZONS)
            }
            for c in ("ALL", "SECTOR_GE80", "INDUSTRY_GE80", "ALIGNED_GE80")
        },
    }
    print("=== SECTOR_STOCK_RESULT_JSON ===", flush=True)
    print(json.dumps(compact, ensure_ascii=False, indent=2), flush=True)
    print("=== END_SECTOR_STOCK_RESULT_JSON ===", flush=True)


if __name__ == "__main__":
    main()
