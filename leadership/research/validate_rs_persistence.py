from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

import validate_early_rotation as er
import validate_confirmed_leadership as cl
import validate_pioneer_leader as pl
import validate_rs_periods as rs


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


def t_summary(values: pd.Series, alpha: float = 0.05) -> dict[str, Any]:
    x = pd.to_numeric(values, errors="coerce").dropna().to_numpy(float)
    n = len(x)
    if n < 3:
        return {"n": n, "mean": None, "ci": [None, None], "p_gt0": None}
    mean = float(np.mean(x))
    se = float(np.std(x, ddof=1) / math.sqrt(n))
    if se == 0:
        ci = [mean, mean]
        p = 0.0 if mean > 0 else 1.0
    else:
        crit = float(stats.t.ppf(1 - alpha / 2, df=n - 1))
        ci = [mean - crit * se, mean + crit * se]
        p = float(stats.t.sf(mean / se, df=n - 1))
    return {"n": int(n), "mean": mean, "ci": [float(ci[0]), float(ci[1])], "p_gt0": p}


def summarize_level(table: pd.DataFrame, feature: str, horizon: int) -> dict[str, Any]:
    x = table[["event_id", "date", "date_pos", feature]].dropna().copy()
    if x.empty:
        return {"events": 0, "mean_retention": None, "median_retention": None, "discovery_mean": None, "confirmation_mean": None}
    disc = x.loc[x["date"] <= rs.DISCOVERY_END, feature]
    conf = x.loc[x["date"] >= rs.CONF_START, feature] if hasattr(rs, "CONF_START") else x.loc[x["date"] >= rs.CONFIRM_START, feature]
    return {
        "events": int(len(x)),
        "dates": int(x["date"].nunique()),
        "mean_retention": float(x[feature].mean()),
        "median_retention": float(x[feature].median()),
        "discovery_mean": float(disc.mean()) if len(disc) else None,
        "confirmation_mean": float(conf.mean()) if len(conf) else None,
    }


def h2h_vs_rs63(table: pd.DataFrame, feature: str, horizon: int) -> dict[str, Any]:
    base = rs.BASELINE
    x = table[["event_id", "date", "date_pos", base, feature]].dropna().copy()
    if feature == base:
        return {"events": int(len(x)), "mean_advantage": 0.0, "block_bonferroni_ci": [0.0, 0.0], "p_bonferroni": 1.0, "discovery_mean": 0.0, "confirmation_mean": 0.0}
    if x.empty:
        return {"events": 0, "mean_advantage": None, "block_bonferroni_ci": [None, None], "p_bonferroni": None, "discovery_mean": None, "confirmation_mean": None}
    x["diff"] = x[feature] - x[base]
    x["time_block"] = x["date_pos"].astype(int) // int(horizon)
    blocks = x.groupby("time_block", observed=True)["diff"].mean()
    normal = t_summary(blocks, alpha=0.05)
    bonf = t_summary(blocks, alpha=0.05 / max(1, len(rs.CANDIDATES) - 1))
    p_bonf = min(1.0, float(normal["p_gt0"]) * max(1, len(rs.CANDIDATES) - 1)) if normal["p_gt0"] is not None else None
    disc = x.loc[x["date"] <= rs.DISCOVERY_END, "diff"]
    conf = x.loc[x["date"] >= rs.CONFIRM_START, "diff"]
    return {
        "events": int(len(x)),
        "mean_advantage": float(x["diff"].mean()),
        "block_bonferroni_ci": bonf["ci"],
        "p_bonferroni": p_bonf,
        "discovery_mean": float(disc.mean()) if len(disc) else None,
        "confirmation_mean": float(conf.mean()) if len(conf) else None,
    }


def build_persistence_tables(
    events: pd.DataFrame,
    theme_members: dict[str, list[str]],
    stock_close: pd.DataFrame,
    stock_period: dict[int, pd.DataFrame],
) -> dict[int, pd.DataFrame]:
    date_pos = {pd.Timestamp(d): i for i, d in enumerate(stock_close.index)}
    rows_by_h: dict[int, list[dict[str, Any]]] = {h: [] for h in rs.HORIZONS}

    for ei, event in enumerate(events.itertuples(index=False)):
        date = pd.Timestamp(event.date)
        theme = str(event.theme)
        pos = date_pos.get(date, -1)
        if pos < 0:
            continue
        members = [s for s in theme_members.get(theme, []) if s in stock_close.columns]
        if len(members) < 4:
            continue
        current = rs.feature_values_for_event(date, members, stock_period)
        event_id = f"{date.date()}|{theme}"

        for h in rs.HORIZONS:
            fpos = pos + h
            if fpos >= len(stock_close):
                continue
            future_date = pd.Timestamp(stock_close.index[fpos])
            future = rs.feature_values_for_event(future_date, members, stock_period)
            frame = pd.DataFrame(index=members)
            for feature in rs.CANDIDATES:
                frame[f"c_{feature}"] = current[feature]
                frame[f"f_{feature}"] = future[feature]
            frame = frame.dropna()
            if len(frame) < 4:
                continue

            out: dict[str, Any] = {
                "event_id": event_id,
                "date": date,
                "date_pos": int(pos),
                "theme": theme,
                "parent_rs_pct": float(event.parent_rs_pct),
                "confirmed_parent80": bool(float(event.parent_rs_pct) >= 80.0),
                "n_common_members": int(len(frame)),
            }
            for feature in rs.CANDIDATES:
                c_rank = frame[f"c_{feature}"].rank(pct=True, method="average")
                f_rank = frame[f"f_{feature}"].rank(pct=True, method="average")
                current_top = c_rank >= 0.8
                if int(current_top.sum()) < 1:
                    out[feature] = np.nan
                else:
                    out[feature] = float((f_rank[current_top] >= 0.8).mean())
            rows_by_h[h].append(out)

        if (ei + 1) % 500 == 0:
            print(f"PERSISTENCE {ei + 1}/{len(events)}", flush=True)

    return {h: pd.DataFrame(rows) for h, rows in rows_by_h.items()}


def analyze_table(table: pd.DataFrame, horizon: int) -> dict[str, Any]:
    result: dict[str, Any] = {"events": int(len(table)), "candidates": {}, "head_to_head_vs_rs63": {}}
    for feature in rs.CANDIDATES:
        result["candidates"][feature] = summarize_level(table, feature, horizon)
        result["head_to_head_vs_rs63"][feature] = h2h_vs_rs63(table, feature, horizon)
    ranked = sorted(
        rs.CANDIDATES,
        key=lambda f: result["candidates"][f]["mean_retention"] if result["candidates"][f]["mean_retention"] is not None else -999,
        reverse=True,
    )
    result["ranked_by_retention"] = ranked
    result["significantly_better_than_rs63"] = [
        f for f in rs.CANDIDATES
        if f != rs.BASELINE
        and result["head_to_head_vs_rs63"][f]["p_bonferroni"] is not None
        and result["head_to_head_vs_rs63"][f]["p_bonferroni"] < 0.05
        and result["head_to_head_vs_rs63"][f]["block_bonferroni_ci"][0] is not None
        and result["head_to_head_vs_rs63"][f]["block_bonferroni_ci"][0] > 0
        and result["head_to_head_vs_rs63"][f]["discovery_mean"] is not None
        and result["head_to_head_vs_rs63"][f]["discovery_mean"] > 0
        and result["head_to_head_vs_rs63"][f]["confirmation_mean"] is not None
        and result["head_to_head_vs_rs63"][f]["confirmation_mean"] > 0
    ]
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", default="leadership/research/rs_persistence_output")
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
    events = er.extract_events(cl.momentum_mask(theme_pct, parent_pct, breadth), theme_pct, parent_pct, breadth, member_counts, start, end)

    stock_period = {p: er.period_return(stock_ret, p) for p in rs.RS_PERIODS}
    tables = build_persistence_tables(events, theme_members, stock_close, stock_period)

    tests: dict[str, Any] = {"ALL_MOMENTUM": {}, "CONFIRMED_PARENT80": {}}
    for h, table in tables.items():
        tests["ALL_MOMENTUM"][str(h)] = analyze_table(table, h)
        tests["CONFIRMED_PARENT80"][str(h)] = analyze_table(table[table["confirmed_parent80"]], h)
        table.to_csv(output / f"persistence_{h}d.csv.gz", index=False, compression="gzip")

    result = {
        "status": "PRELIMINARY_FIXED_CURRENT_TAXONOMY",
        "question": "Which RS period/blend best identifies stocks that remain within the same theme's top quintile?",
        "definition": "For each Momentum event and horizon, rank the common member set by each candidate at signal date and again at the future date; retention is the fraction of current top-quintile members still top-quintile later.",
        "comparison": "All candidates use the same members with complete 21/42/63/126/189/252-day data at both dates. Head-to-head inference versus RS63 uses horizon-sized time blocks and Bonferroni across 11 alternatives, with discovery and confirmation signs required to agree.",
        "bias_warning": "Current ticker-to-subtheme membership is applied retrospectively; preliminary until point-in-time membership exists.",
        "rs_periods": list(rs.RS_PERIODS),
        "rs_blends": rs.BLENDS,
        "coverage": {"selected_stocks": len(stock_cols), "momentum_events": int(len(events))},
        "download": download_diag,
        "taxonomy_candidates": taxonomy_candidates,
        "tests": tests,
    }
    safe_result = safe(result)
    (output / "summary.json").write_text(json.dumps(safe_result, ensure_ascii=False, indent=2), encoding="utf-8")

    compact: dict[str, Any] = {"status": safe_result["status"], "contexts": {}}
    for context in ("ALL_MOMENTUM", "CONFIRMED_PARENT80"):
        compact["contexts"][context] = {}
        for h in rs.HORIZONS:
            hr = safe_result["tests"][context][str(h)]
            compact["contexts"][context][str(h)] = {
                "ranked": hr["ranked_by_retention"],
                "retention": {f: hr["candidates"][f]["mean_retention"] for f in rs.CANDIDATES},
                "better_than_rs63": hr["significantly_better_than_rs63"],
                "h2h_advantage": {f: hr["head_to_head_vs_rs63"][f]["mean_advantage"] for f in rs.CANDIDATES},
                "h2h_p_bonf": {f: hr["head_to_head_vs_rs63"][f]["p_bonferroni"] for f in rs.CANDIDATES},
                "h2h_ci": {f: hr["head_to_head_vs_rs63"][f]["block_bonferroni_ci"] for f in rs.CANDIDATES},
            }
    print("=== RS_PERSISTENCE_RESULT_JSON ===", flush=True)
    print(json.dumps(compact, ensure_ascii=False, indent=2), flush=True)
    print("=== END_RS_PERSISTENCE_RESULT_JSON ===", flush=True)


if __name__ == "__main__":
    main()
