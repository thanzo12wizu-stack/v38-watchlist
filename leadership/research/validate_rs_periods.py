from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import validate_early_rotation as er
import validate_confirmed_leadership as cl
import validate_pioneer_leader as pl

HORIZONS = (5, 10, 20, 63)
RS_PERIODS = (21, 42, 63, 126, 189, 252)
BLENDS: dict[str, dict[int, float]] = {
    "BLEND_21_42_63_EQ": {21: 1 / 3, 42: 1 / 3, 63: 1 / 3},
    "BLEND_42_63_126_EQ": {42: 1 / 3, 63: 1 / 3, 126: 1 / 3},
    "BLEND_63_126_EQ": {63: 0.5, 126: 0.5},
    "BLEND_63_126_189_EQ": {63: 1 / 3, 126: 1 / 3, 189: 1 / 3},
    "BLEND_126_189_252_EQ": {126: 1 / 3, 189: 1 / 3, 252: 1 / 3},
    "BLEND_RECENT_WEIGHTED": {63: 0.4, 126: 0.2, 189: 0.2, 252: 0.2},
}
SINGLE_NAMES = {p: f"RS{p}" for p in RS_PERIODS}
CANDIDATES = tuple(list(SINGLE_NAMES.values()) + list(BLENDS.keys()))
BASELINE = "RS63"
TOP_CUT = 2.0 / 3.0
BOTTOM_CUT = 1.0 / 3.0
DISCOVERY_END = pd.Timestamp("2021-12-31")
CONFIRM_START = pd.Timestamp("2022-01-01")


def rank_within(values: pd.Series) -> pd.Series:
    x = pd.to_numeric(values, errors="coerce")
    if x.notna().sum() < 3:
        return pd.Series(np.nan, index=values.index)
    return x.rank(pct=True, method="average")


def feature_values_for_event(
    date: pd.Timestamp,
    members: list[str],
    stock_period: dict[int, pd.DataFrame],
) -> dict[str, pd.Series]:
    single: dict[int, pd.Series] = {}
    for p in RS_PERIODS:
        if date not in stock_period[p].index:
            single[p] = pd.Series(np.nan, index=members)
        else:
            single[p] = rank_within(stock_period[p].loc[date, members])
    out: dict[str, pd.Series] = {SINGLE_NAMES[p]: single[p] for p in RS_PERIODS}
    for name, weights in BLENDS.items():
        frame = pd.DataFrame({p: single[p] for p in weights})
        required = frame.notna().all(axis=1)
        value = pd.Series(0.0, index=frame.index)
        for p, w in weights.items():
            value = value + frame[p] * w
        out[name] = value.where(required)
    return out


def compound_daily(ret: pd.Series, horizon: int) -> float:
    x = pd.to_numeric(ret, errors="coerce").dropna()
    min_obs = max(1, int(math.ceil(horizon * 0.8)))
    x = x[x > -0.999999]
    if len(x) < min_obs:
        return np.nan
    return float(np.expm1(np.log1p(x).sum()))


def event_peer_returns(stock_ret: pd.DataFrame, members: list[str], pos: int, horizon: int) -> dict[str, float]:
    if pos < 0 or pos + horizon >= len(stock_ret):
        return {}
    dates = stock_ret.index[pos + 1:pos + horizon + 1]
    part = stock_ret.loc[dates, members]
    sums = part.sum(axis=1, skipna=True)
    counts = part.notna().sum(axis=1)
    out: dict[str, float] = {}
    for sym in members:
        sr = part[sym]
        peer_count = counts - sr.notna().astype(int)
        peer_daily = (sums - sr.fillna(0.0)) / peer_count.replace(0, np.nan)
        peer_daily = peer_daily.where(peer_count >= 2)
        out[sym] = compound_daily(peer_daily, horizon)
    return out


def extract_rows(
    events: pd.DataFrame,
    theme_members: dict[str, list[str]],
    stock_close: pd.DataFrame,
    stock_high: pd.DataFrame,
    stock_low: pd.DataFrame,
    stock_ret: pd.DataFrame,
    spy_ret: pd.Series,
    stock_period: dict[int, pd.DataFrame],
) -> pd.DataFrame:
    stock_fwd = {h: er.forward_return(stock_ret, h) for h in HORIZONS}
    spy_fwd = {h: er.forward_return(spy_ret, h) for h in HORIZONS}
    date_pos = {pd.Timestamp(d): i for i, d in enumerate(stock_close.index)}
    rows: list[dict[str, Any]] = []

    for ei, event in enumerate(events.itertuples(index=False)):
        date = pd.Timestamp(event.date)
        theme = str(event.theme)
        pos = date_pos.get(date, -1)
        if pos < 0:
            continue
        members = [s for s in theme_members.get(theme, []) if s in stock_close.columns]
        if len(members) < 3:
            continue
        feats = feature_values_for_event(date, members, stock_period)
        peer_by_h = {h: event_peer_returns(stock_ret, members, pos, h) for h in HORIZONS}
        event_id = f"{date.date()}|{theme}"

        for sym in members:
            entry = stock_close.at[date, sym]
            if pd.isna(entry) or entry <= 0:
                continue
            row: dict[str, Any] = {
                "event_id": event_id,
                "event_index": ei,
                "date": date,
                "date_pos": pos,
                "theme": theme,
                "symbol": sym,
                "theme_rs_pct": float(event.theme_rs_pct),
                "parent_rs_pct": float(event.parent_rs_pct),
                "confirmed_parent80": bool(float(event.parent_rs_pct) >= 80.0),
            }
            for name, series in feats.items():
                val = series.get(sym, np.nan)
                row[name] = float(val) if pd.notna(val) else np.nan
            row["common_all_periods"] = bool(all(pd.notna(row[SINGLE_NAMES[p]]) for p in RS_PERIODS))

            for h in HORIZONS:
                sr = stock_fwd[h].at[date, sym] if date in stock_fwd[h].index else np.nan
                sp = spy_fwd[h].at[date] if date in spy_fwd[h].index else np.nan
                pr = peer_by_h[h].get(sym, np.nan)
                future_dates = stock_close.index[pos + 1:min(pos + h + 1, len(stock_close))]
                highs = stock_high.loc[future_dates, sym].dropna()
                lows = stock_low.loc[future_dates, sym].dropna()
                row[f"stock_ret_{h}"] = sr
                row[f"stock_minus_peers_{h}"] = sr - pr if pd.notna(sr) and pd.notna(pr) else np.nan
                row[f"stock_minus_spy_{h}"] = sr - sp if pd.notna(sr) and pd.notna(sp) else np.nan
                row[f"mfe_{h}"] = float(highs.max() / entry - 1.0) if len(highs) else np.nan
                row[f"mae_{h}"] = float(lows.min() / entry - 1.0) if len(lows) else np.nan
            rows.append(row)
        if (ei + 1) % 500 == 0:
            print(f"RS_EVENT_FEATURES {ei + 1}/{len(events)} rows={len(rows)}", flush=True)
    return pd.DataFrame(rows)


def bootstrap_cluster_mean(values: pd.DataFrame, value_col: str, cluster_col: str, seed: int, reps: int = 4000, alpha: float = 0.05) -> list[float | None]:
    use = values[[cluster_col, value_col]].dropna()
    if use.empty:
        return [None, None]
    grouped = use.groupby(cluster_col, observed=True)[value_col].mean().to_numpy(float)
    if len(grouped) < 2:
        return [None, None]
    rng = np.random.default_rng(seed)
    samples = rng.choice(grouped, size=(reps, len(grouped)), replace=True).mean(axis=1)
    lo, hi = np.quantile(samples, [alpha / 2, 1 - alpha / 2])
    return [float(lo), float(hi)]


def event_ic_table(rows: pd.DataFrame, feature: str, outcome: str, horizon: int) -> pd.DataFrame:
    use = rows[["event_id", "date", "date_pos", "theme", feature, outcome]].dropna().copy()
    records: list[dict[str, Any]] = []
    for keys, part in use.groupby(["event_id", "date", "date_pos", "theme"], observed=True):
        if len(part) < 4 or part[feature].nunique() < 3 or part[outcome].nunique() < 2:
            continue
        ic = part[feature].corr(part[outcome], method="spearman")
        if pd.isna(ic):
            continue
        event_id, date, date_pos, theme = keys
        records.append({
            "event_id": event_id,
            "date": pd.Timestamp(date),
            "date_pos": int(date_pos),
            "theme": theme,
            "time_block": int(date_pos) // int(horizon),
            "ic": float(ic),
        })
    return pd.DataFrame(records)


def top_bottom_table(rows: pd.DataFrame, feature: str, outcome: str, horizon: int) -> pd.DataFrame:
    use = rows[["event_id", "date", "date_pos", "theme", feature, outcome]].dropna().copy()
    use["bucket"] = np.where(use[feature] >= TOP_CUT, "TOP", np.where(use[feature] <= BOTTOM_CUT, "BOTTOM", "MID"))
    use = use[use["bucket"] != "MID"]
    if use.empty:
        return pd.DataFrame()
    grouped = use.groupby(["event_id", "date", "date_pos", "theme", "bucket"], observed=True)[outcome].mean().unstack("bucket")
    if "TOP" not in grouped.columns or "BOTTOM" not in grouped.columns:
        return pd.DataFrame()
    grouped = grouped.dropna(subset=["TOP", "BOTTOM"]).reset_index()
    grouped["diff"] = grouped["TOP"] - grouped["BOTTOM"]
    grouped["time_block"] = grouped["date_pos"].astype(int) // int(horizon)
    return grouped[["event_id", "date", "date_pos", "theme", "time_block", "diff"]]


def summarize_measure(table: pd.DataFrame, value_col: str, seed: int, m_tests: int) -> dict[str, Any]:
    if table.empty:
        return {
            "n": 0, "mean": None, "median": None, "positive_rate": None,
            "event_ci95": [None, None], "block_ci95": [None, None], "block_bonferroni_ci": [None, None],
            "discovery_mean": None, "confirmation_mean": None,
        }
    alpha_bonf = 0.05 / max(1, m_tests)
    disc = table.loc[table["date"] <= DISCOVERY_END, value_col].dropna()
    conf = table.loc[table["date"] >= CONFIRM_START, value_col].dropna()
    return {
        "n": int(len(table)),
        "dates": int(table["date"].nunique()),
        "themes": int(table["theme"].nunique()),
        "mean": float(table[value_col].mean()),
        "median": float(table[value_col].median()),
        "positive_rate": float((table[value_col] > 0).mean()),
        "event_ci95": bootstrap_cluster_mean(table, value_col, "event_id", seed, alpha=0.05),
        "block_ci95": bootstrap_cluster_mean(table, value_col, "time_block", seed + 10000, alpha=0.05),
        "block_bonferroni_ci": bootstrap_cluster_mean(table, value_col, "time_block", seed + 20000, alpha=alpha_bonf),
        "discovery_mean": float(disc.mean()) if len(disc) else None,
        "confirmation_mean": float(conf.mean()) if len(conf) else None,
        "discovery_n": int(len(disc)),
        "confirmation_n": int(len(conf)),
    }


def candidate_result(rows: pd.DataFrame, feature: str, horizon: int, seed: int) -> dict[str, Any]:
    primary_outcome = f"stock_minus_peers_{horizon}"
    ic_table = event_ic_table(rows, feature, primary_outcome, horizon)
    spread_table = top_bottom_table(rows, feature, primary_outcome, horizon)
    ic = summarize_measure(ic_table, "ic", seed, len(CANDIDATES))
    spread = summarize_measure(spread_table, "diff", seed + 30000, len(CANDIDATES))
    mfe = summarize_measure(top_bottom_table(rows, feature, f"mfe_{horizon}", horizon), "diff", seed + 40000, len(CANDIDATES))
    mae = summarize_measure(top_bottom_table(rows, feature, f"mae_{horizon}", horizon), "diff", seed + 50000, len(CANDIDATES))
    supported = bool(
        ic["event_ci95"][0] is not None
        and ic["block_bonferroni_ci"][0] is not None
        and ic["event_ci95"][0] > 0
        and ic["block_bonferroni_ci"][0] > 0
        and ic["discovery_mean"] is not None and ic["discovery_mean"] > 0
        and ic["confirmation_mean"] is not None and ic["confirmation_mean"] > 0
    )
    return {"ic": ic, "top_minus_bottom": spread, "mfe": mfe, "mae": mae, "supported": supported}


def head_to_head_vs_baseline(rows: pd.DataFrame, feature: str, horizon: int, seed: int) -> dict[str, Any]:
    if feature == BASELINE:
        return {"n": 0, "mean_ic_advantage_vs_rs63": 0.0, "block_ci95": [0.0, 0.0], "block_bonferroni_ci": [0.0, 0.0]}
    outcome = f"stock_minus_peers_{horizon}"
    a = event_ic_table(rows, feature, outcome, horizon).rename(columns={"ic": "candidate_ic"})
    b = event_ic_table(rows, BASELINE, outcome, horizon).rename(columns={"ic": "baseline_ic"})
    if a.empty or b.empty:
        return {"n": 0, "mean_ic_advantage_vs_rs63": None, "block_ci95": [None, None], "block_bonferroni_ci": [None, None]}
    merged = a[["event_id", "date", "date_pos", "theme", "time_block", "candidate_ic"]].merge(
        b[["event_id", "baseline_ic"]], on="event_id", how="inner"
    )
    merged["ic_diff"] = merged["candidate_ic"] - merged["baseline_ic"]
    alpha_bonf = 0.05 / max(1, len(CANDIDATES) - 1)
    disc = merged.loc[merged["date"] <= DISCOVERY_END, "ic_diff"].dropna()
    conf = merged.loc[merged["date"] >= CONFIRM_START, "ic_diff"].dropna()
    return {
        "n": int(len(merged)),
        "mean_ic_advantage_vs_rs63": float(merged["ic_diff"].mean()) if len(merged) else None,
        "block_ci95": bootstrap_cluster_mean(merged, "ic_diff", "time_block", seed, alpha=0.05),
        "block_bonferroni_ci": bootstrap_cluster_mean(merged, "ic_diff", "time_block", seed + 10000, alpha=alpha_bonf),
        "discovery_mean": float(disc.mean()) if len(disc) else None,
        "confirmation_mean": float(conf.mean()) if len(conf) else None,
    }


def summarize(rows: pd.DataFrame) -> dict[str, Any]:
    result: dict[str, Any] = {}
    contexts = {
        "ALL_MOMENTUM": rows,
        "CONFIRMED_PARENT80": rows[rows["confirmed_parent80"]],
    }
    samples = {
        "COMMON_ALL_PERIODS": lambda x: x[x["common_all_periods"]],
        "NATIVE_AVAILABLE": lambda x: x,
    }
    for context_name, context_rows in contexts.items():
        ctx: dict[str, Any] = {}
        for sample_name, sample_fn in samples.items():
            part = sample_fn(context_rows)
            sample_result: dict[str, Any] = {
                "rows": int(len(part)),
                "events": int(part["event_id"].nunique()),
                "dates": int(part["date"].nunique()),
                "themes": int(part["theme"].nunique()),
                "horizons": {},
            }
            for h in HORIZONS:
                h_result: dict[str, Any] = {"candidates": {}, "head_to_head_vs_rs63": {}}
                for i, feature in enumerate(CANDIDATES):
                    h_result["candidates"][feature] = candidate_result(part, feature, h, 1000 + h * 100 + i)
                    h_result["head_to_head_vs_rs63"][feature] = head_to_head_vs_baseline(part, feature, h, 70000 + h * 100 + i)
                supported = [f for f in CANDIDATES if h_result["candidates"][f]["supported"]]
                ranked = sorted(
                    CANDIDATES,
                    key=lambda f: (h_result["candidates"][f]["ic"]["mean"] if h_result["candidates"][f]["ic"]["mean"] is not None else -999),
                    reverse=True,
                )
                h_result["supported_candidates"] = supported
                h_result["ranked_by_mean_ic"] = ranked
                sample_result["horizons"][str(h)] = h_result
            ctx[sample_name] = sample_result
        result[context_name] = ctx
    return result


def safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [safe(v) for v in value]
    if isinstance(value, tuple):
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
    parser.add_argument("--output", default="leadership/research/rs_period_output")
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
        raise RuntimeError("SPY benchmark missing from Yahoo download")

    stock_cols = [s for s in selected if s in close.columns]
    stock_close = close[stock_cols]
    stock_high = ohlcv["high"][stock_cols]
    stock_low = ohlcv["low"][stock_cols]
    stock_ret = er.arithmetic_returns(stock_close)
    spy_ret = er.arithmetic_returns(close[["SPY"]])["SPY"]

    theme_members = {theme: [s for s in members if s in stock_cols] for theme, members in theme_members_all.items()}
    member_counts = {theme: len(members) for theme, members in theme_members.items()}
    theme_ret = er.grouped_equal_weight(stock_ret, theme_members, args.min_members)

    industry_groups: dict[str, list[str]] = {}
    for sym in stock_cols:
        pair = industry_map.get(sym)
        if pair and pair[1]:
            industry_groups.setdefault(pair[1], []).append(sym)
    industry_ret = er.grouped_equal_weight(stock_ret, industry_groups, args.min_members)
    parent_weights = er.build_parent_weights(theme_members_all, industry_map)
    common_themes = sorted(set(theme_ret.columns) & set(parent_weights))
    theme_ret = theme_ret[common_themes]

    theme63 = er.period_return(theme_ret, 63)
    spy63 = er.period_return(spy_ret, 63)
    theme_pct = theme63.sub(spy63, axis=0).rank(axis=1, pct=True, method="average") * 100.0
    industry63 = er.period_return(industry_ret, 63)
    industry_pct = industry63.sub(spy63, axis=0).rank(axis=1, pct=True, method="average") * 100.0
    parent_pct = er.weighted_matrix(industry_pct, parent_weights, common_themes)
    breadth = er.breadth_above_ema21(stock_close, theme_members, args.min_members).reindex(columns=common_themes)

    start, end = pd.Timestamp(args.analysis_start), pd.Timestamp(args.analysis_end)
    mask = cl.momentum_mask(theme_pct, parent_pct, breadth)
    events = er.extract_events(mask, theme_pct, parent_pct, breadth, member_counts, start, end)

    stock_period = {p: er.period_return(stock_ret, p) for p in RS_PERIODS}
    rows = extract_rows(events, theme_members, stock_close, stock_high, stock_low, stock_ret, spy_ret, stock_period)
    tests = summarize(rows)

    result = {
        "status": "PRELIMINARY_FIXED_CURRENT_TAXONOMY",
        "question": "Which RS lookback or predeclared rank blend best predicts future stock leadership inside Subtheme Momentum events?",
        "bias_warning": "Current ticker→subtheme membership is applied retrospectively and the stock universe is a current-taxonomy sample. Treat this as hypothesis filtering until point-in-time membership exists.",
        "momentum_definition_frozen": cl.MOMENTUM_CONFIG,
        "rs_single_periods": list(RS_PERIODS),
        "rs_blends_frozen_before_outcomes": BLENDS,
        "candidate_count": len(CANDIDATES),
        "primary_metric": "Per-event Spearman IC between within-theme RS candidate rank and forward stock return minus the equal-weight arithmetic return of the other theme members.",
        "secondary_metric": "Within each event, top-third minus bottom-third forward peer-relative return; MFE and MAE top-minus-bottom are diagnostics.",
        "significance_policy": "A candidate is primary-supported only if event bootstrap 95% CI and horizon-sized time-block Bonferroni familywise CI are both >0, and mean IC is positive in both 2016-2021 and 2022-2026H1. No post-outcome threshold optimization.",
        "common_sample_policy": "COMMON_ALL_PERIODS requires all 21/42/63/126/189/252d RS inputs for a stock at the event date so candidate comparisons use the same stock-history sample. NATIVE_AVAILABLE is secondary coverage analysis.",
        "horizons": list(HORIZONS),
        "analysis_window": [args.analysis_start, args.analysis_end],
        "download": download_diag,
        "taxonomy_candidates": taxonomy_candidates,
        "coverage": {
            "selected_stocks": len(stock_cols),
            "themes_current_taxonomy": len(theme_members_all),
            "themes_with_signal_model": len(common_themes),
            "momentum_events": int(len(events)),
            "momentum_themes": int(events["theme"].nunique()) if not events.empty else 0,
            "event_stock_rows": int(len(rows)),
            "common_all_period_rows": int(rows["common_all_periods"].sum()) if len(rows) else 0,
        },
        "tests": tests,
    }
    safe_result = safe(result)
    rows.to_csv(output / "rs_period_event_stock_rows.csv.gz", index=False, compression="gzip")
    (output / "summary.json").write_text(json.dumps(safe_result, ensure_ascii=False, indent=2), encoding="utf-8")

    compact: dict[str, Any] = {"status": safe_result["status"], "coverage": safe_result["coverage"], "contexts": {}}
    for context in ("ALL_MOMENTUM", "CONFIRMED_PARENT80"):
        compact["contexts"][context] = {}
        for sample in ("COMMON_ALL_PERIODS", "NATIVE_AVAILABLE"):
            compact["contexts"][context][sample] = {}
            for h in HORIZONS:
                hr = safe_result["tests"][context][sample]["horizons"][str(h)]
                compact["contexts"][context][sample][str(h)] = {
                    "supported": hr["supported_candidates"],
                    "ranked": hr["ranked_by_mean_ic"],
                    "mean_ic": {f: hr["candidates"][f]["ic"]["mean"] for f in CANDIDATES},
                    "block_bonf_ci": {f: hr["candidates"][f]["ic"]["block_bonferroni_ci"] for f in CANDIDATES},
                    "disc_mean": {f: hr["candidates"][f]["ic"]["discovery_mean"] for f in CANDIDATES},
                    "conf_mean": {f: hr["candidates"][f]["ic"]["confirmation_mean"] for f in CANDIDATES},
                    "spread_mean": {f: hr["candidates"][f]["top_minus_bottom"]["mean"] for f in CANDIDATES},
                    "h2h_vs_rs63": {f: hr["head_to_head_vs_rs63"][f]["mean_ic_advantage_vs_rs63"] for f in CANDIDATES},
                    "h2h_bonf_ci": {f: hr["head_to_head_vs_rs63"][f]["block_bonferroni_ci"] for f in CANDIDATES},
                }
    print("=== RS_PERIOD_RESULT_JSON ===", flush=True)
    print(json.dumps(compact, ensure_ascii=False, indent=2), flush=True)
    print("=== END_RS_PERIOD_RESULT_JSON ===", flush=True)


if __name__ == "__main__":
    main()
