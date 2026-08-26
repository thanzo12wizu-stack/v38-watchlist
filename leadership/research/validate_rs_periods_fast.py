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
        return {"n": n, "mean": None, "median": None, "positive_rate": None, "ci": [None, None], "p_one_sided_gt0": None}
    mean = float(np.mean(x))
    se = float(np.std(x, ddof=1) / math.sqrt(n))
    if se == 0:
        ci = [mean, mean]
        p = 0.0 if mean > 0 else 1.0
    else:
        crit = float(stats.t.ppf(1 - alpha / 2, df=n - 1))
        ci = [mean - crit * se, mean + crit * se]
        tstat = mean / se
        p = float(stats.t.sf(tstat, df=n - 1))
    return {
        "n": int(n),
        "mean": mean,
        "median": float(np.median(x)),
        "positive_rate": float(np.mean(x > 0)),
        "ci": [float(ci[0]), float(ci[1])],
        "p_one_sided_gt0": p,
    }


def block_summary(table: pd.DataFrame, value_col: str, horizon: int, m_tests: int) -> dict[str, Any]:
    if table.empty:
        return {"events": 0, "event_mean": None, "event_ci95": [None, None], "blocks": 0, "block_mean": None, "block_ci95": [None, None], "block_bonferroni_ci": [None, None], "p_block_gt0": None, "p_bonferroni": None, "discovery_mean": None, "confirmation_mean": None, "confirmation_p_block_gt0": None}
    use = table.copy()
    use["time_block"] = use["date_pos"].astype(int) // int(horizon)
    event_s = t_summary(use[value_col], alpha=0.05)
    blocks = use.groupby("time_block", observed=True)[value_col].mean()
    block_s = t_summary(blocks, alpha=0.05)
    alpha_b = 0.05 / max(1, m_tests)
    block_b = t_summary(blocks, alpha=alpha_b)
    p_bonf = min(1.0, float(block_s["p_one_sided_gt0"]) * max(1, m_tests)) if block_s["p_one_sided_gt0"] is not None else None

    disc = use[use["date"] <= rs.DISCOVERY_END].copy()
    conf = use[use["date"] >= rs.CONFIRM_START].copy()
    disc_mean = float(disc[value_col].mean()) if len(disc) else None
    conf_mean = float(conf[value_col].mean()) if len(conf) else None
    if len(conf):
        conf["time_block"] = conf["date_pos"].astype(int) // int(horizon)
        conf_blocks = conf.groupby("time_block", observed=True)[value_col].mean()
        conf_stat = t_summary(conf_blocks, alpha=0.05)
        conf_p = conf_stat["p_one_sided_gt0"]
    else:
        conf_p = None
    return {
        "events": int(len(use)),
        "event_mean": event_s["mean"],
        "event_median": event_s["median"],
        "event_positive_rate": event_s["positive_rate"],
        "event_ci95": event_s["ci"],
        "blocks": int(len(blocks)),
        "block_mean": block_s["mean"],
        "block_ci95": block_s["ci"],
        "block_bonferroni_ci": block_b["ci"],
        "p_block_gt0": block_s["p_one_sided_gt0"],
        "p_bonferroni": p_bonf,
        "discovery_mean": disc_mean,
        "confirmation_mean": conf_mean,
        "confirmation_p_block_gt0": conf_p,
    }


def exact_event_ic_matrix(rows: pd.DataFrame, outcome: str) -> pd.DataFrame:
    cols = ["event_id", "date", "date_pos", "theme", outcome, *rs.CANDIDATES]
    use = rows[cols].dropna().copy()
    if use.empty:
        return pd.DataFrame()
    group = use.groupby("event_id", observed=True)
    # Common sample has every candidate present. Ranking once per event makes Pearson correlation of ranks exactly Spearman.
    feat_rank = group[list(rs.CANDIDATES)].rank(method="average", pct=True)
    y_rank = group[outcome].rank(method="average", pct=True)
    meta = use[["event_id", "date", "date_pos", "theme"]].copy()
    result = meta.groupby("event_id", observed=True).first().reset_index()
    counts = group.size()
    valid_events = counts[counts >= 4].index
    result = result[result["event_id"].isin(valid_events)].copy()

    for feature in rs.CANDIDATES:
        tmp = pd.DataFrame({"event_id": use["event_id"], "x": feat_rank[feature], "y": y_rank})
        tmp = tmp[tmp["event_id"].isin(valid_events)]
        g = tmp.groupby("event_id", observed=True)
        n = g.size().astype(float)
        sx = g["x"].sum(); sy = g["y"].sum()
        sxx = (tmp["x"] ** 2).groupby(tmp["event_id"], observed=True).sum()
        syy = (tmp["y"] ** 2).groupby(tmp["event_id"], observed=True).sum()
        sxy = (tmp["x"] * tmp["y"]).groupby(tmp["event_id"], observed=True).sum()
        cov = sxy - sx * sy / n
        vx = sxx - sx * sx / n
        vy = syy - sy * sy / n
        corr = cov / np.sqrt(vx * vy)
        result = result.merge(corr.rename(feature), left_on="event_id", right_index=True, how="left")
    return result


def top_bottom_matrix(rows: pd.DataFrame, outcome: str) -> pd.DataFrame:
    meta = rows[["event_id", "date", "date_pos", "theme"]].drop_duplicates("event_id")
    out = meta.copy()
    for feature in rs.CANDIDATES:
        use = rows[["event_id", feature, outcome]].dropna().copy()
        use["bucket"] = np.where(use[feature] >= rs.TOP_CUT, "TOP", np.where(use[feature] <= rs.BOTTOM_CUT, "BOTTOM", "MID"))
        use = use[use["bucket"] != "MID"]
        if use.empty:
            out[feature] = np.nan
            continue
        tab = use.groupby(["event_id", "bucket"], observed=True)[outcome].mean().unstack("bucket")
        if "TOP" not in tab.columns or "BOTTOM" not in tab.columns:
            out[feature] = np.nan
            continue
        diff = (tab["TOP"] - tab["BOTTOM"]).rename(feature)
        out = out.merge(diff, left_on="event_id", right_index=True, how="left")
    return out


def analyze_context(rows: pd.DataFrame) -> dict[str, Any]:
    # Exact candidate comparison uses only rows where every RS period exists.
    common = rows[rows["common_all_periods"]].copy()
    result: dict[str, Any] = {
        "rows": int(len(common)),
        "events": int(common["event_id"].nunique()),
        "dates": int(common["date"].nunique()),
        "themes": int(common["theme"].nunique()),
        "horizons": {},
    }
    for h in rs.HORIZONS:
        primary = f"stock_minus_peers_{h}"
        icm = exact_event_ic_matrix(common, primary)
        spreadm = top_bottom_matrix(common, primary)
        mfem = top_bottom_matrix(common, f"mfe_{h}")
        maem = top_bottom_matrix(common, f"mae_{h}")
        hres: dict[str, Any] = {"candidates": {}, "head_to_head_vs_rs63": {}}
        for feature in rs.CANDIDATES:
            ic_table = icm[["event_id", "date", "date_pos", "theme", feature]].dropna().rename(columns={feature: "value"})
            spread_table = spreadm[["event_id", "date", "date_pos", "theme", feature]].dropna().rename(columns={feature: "value"})
            mfe_table = mfem[["event_id", "date", "date_pos", "theme", feature]].dropna().rename(columns={feature: "value"})
            mae_table = maem[["event_id", "date", "date_pos", "theme", feature]].dropna().rename(columns={feature: "value"})
            ic = block_summary(ic_table, "value", h, len(rs.CANDIDATES))
            spread = block_summary(spread_table, "value", h, len(rs.CANDIDATES))
            mfe = block_summary(mfe_table, "value", h, len(rs.CANDIDATES))
            mae = block_summary(mae_table, "value", h, len(rs.CANDIDATES))
            supported = bool(
                ic["p_bonferroni"] is not None and ic["p_bonferroni"] < 0.05
                and ic["block_bonferroni_ci"][0] is not None and ic["block_bonferroni_ci"][0] > 0
                and ic["discovery_mean"] is not None and ic["discovery_mean"] > 0
                and ic["confirmation_mean"] is not None and ic["confirmation_mean"] > 0
                and ic["confirmation_p_block_gt0"] is not None and ic["confirmation_p_block_gt0"] < 0.05
            )
            hres["candidates"][feature] = {"ic": ic, "top_minus_bottom": spread, "mfe": mfe, "mae": mae, "supported": supported}

        baseline = icm[["event_id", "date", "date_pos", rs.BASELINE]].dropna().rename(columns={rs.BASELINE: "baseline"})
        for feature in rs.CANDIDATES:
            if feature == rs.BASELINE:
                hres["head_to_head_vs_rs63"][feature] = {"mean_ic_advantage": 0.0, "p_bonferroni": 1.0, "block_bonferroni_ci": [0.0, 0.0]}
                continue
            cand = icm[["event_id", feature]].dropna().rename(columns={feature: "candidate"})
            merged = baseline.merge(cand, on="event_id", how="inner")
            merged["value"] = merged["candidate"] - merged["baseline"]
            hh = block_summary(merged[["event_id", "date", "date_pos", "value"]].assign(theme="NA"), "value", h, len(rs.CANDIDATES) - 1)
            hres["head_to_head_vs_rs63"][feature] = {
                "mean_ic_advantage": hh["event_mean"],
                "p_bonferroni": hh["p_bonferroni"],
                "block_bonferroni_ci": hh["block_bonferroni_ci"],
                "discovery_mean": hh["discovery_mean"],
                "confirmation_mean": hh["confirmation_mean"],
            }
        supported = [f for f in rs.CANDIDATES if hres["candidates"][f]["supported"]]
        ranked = sorted(rs.CANDIDATES, key=lambda f: hres["candidates"][f]["ic"]["event_mean"] if hres["candidates"][f]["ic"]["event_mean"] is not None else -999, reverse=True)
        hres["supported_candidates"] = supported
        hres["ranked_by_mean_ic"] = ranked
        result["horizons"][str(h)] = hres
    return result


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
        raise RuntimeError("SPY benchmark missing")
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
    events = er.extract_events(cl.momentum_mask(theme_pct, parent_pct, breadth), theme_pct, parent_pct, breadth, member_counts, start, end)

    stock_period = {p: er.period_return(stock_ret, p) for p in rs.RS_PERIODS}
    rows = rs.extract_rows(events, theme_members, stock_close, stock_high, stock_low, stock_ret, spy_ret, stock_period)
    common_rows = rows[rows["common_all_periods"]]
    tests = {
        "ALL_MOMENTUM": analyze_context(rows),
        "CONFIRMED_PARENT80": analyze_context(rows[rows["confirmed_parent80"]]),
    }
    result = {
        "status": "PRELIMINARY_FIXED_CURRENT_TAXONOMY",
        "question": "Which RS period or predeclared rank blend has statistically robust stock-selection value inside Subtheme Momentum?",
        "bias_warning": "Current ticker-to-subtheme membership is applied retrospectively; this remains preliminary until point-in-time membership exists.",
        "momentum_definition_frozen": cl.MOMENTUM_CONFIG,
        "rs_periods": list(rs.RS_PERIODS),
        "rs_blends_frozen_before_outcomes": rs.BLENDS,
        "primary_sample": "COMMON_ALL_PERIODS",
        "primary_metric": "Per-event Spearman IC between candidate RS rank and future stock return minus equal-weight arithmetic return of the other theme members.",
        "significance_policy": "Horizon-sized time-block one-sided t test, Bonferroni across 12 predeclared candidates, adjusted two-sided CI >0, positive discovery and confirmation means, and confirmation block p<0.05.",
        "discovery": "2016-01-04..2021-12-31",
        "confirmation": "2022-01-01..2026-06-20",
        "coverage": {
            "selected_stocks": len(stock_cols),
            "momentum_events": int(len(events)),
            "event_stock_rows": int(len(rows)),
            "common_all_period_rows": int(len(common_rows)),
            "common_all_period_events": int(common_rows["event_id"].nunique()),
        },
        "download": download_diag,
        "taxonomy_candidates": taxonomy_candidates,
        "tests": tests,
    }
    safe_result = safe(result)
    rows.to_csv(output / "rs_period_event_stock_rows.csv.gz", index=False, compression="gzip")
    (output / "summary.json").write_text(json.dumps(safe_result, ensure_ascii=False, indent=2), encoding="utf-8")

    compact: dict[str, Any] = {"status": safe_result["status"], "coverage": safe_result["coverage"], "contexts": {}}
    for context in ("ALL_MOMENTUM", "CONFIRMED_PARENT80"):
        compact["contexts"][context] = {}
        for h in rs.HORIZONS:
            hr = safe_result["tests"][context]["horizons"][str(h)]
            compact["contexts"][context][str(h)] = {
                "supported": hr["supported_candidates"],
                "ranked": hr["ranked_by_mean_ic"],
                "mean_ic": {f: hr["candidates"][f]["ic"]["event_mean"] for f in rs.CANDIDATES},
                "p_bonf": {f: hr["candidates"][f]["ic"]["p_bonferroni"] for f in rs.CANDIDATES},
                "bonf_ci": {f: hr["candidates"][f]["ic"]["block_bonferroni_ci"] for f in rs.CANDIDATES},
                "disc": {f: hr["candidates"][f]["ic"]["discovery_mean"] for f in rs.CANDIDATES},
                "conf": {f: hr["candidates"][f]["ic"]["confirmation_mean"] for f in rs.CANDIDATES},
                "conf_p": {f: hr["candidates"][f]["ic"]["confirmation_p_block_gt0"] for f in rs.CANDIDATES},
                "spread": {f: hr["candidates"][f]["top_minus_bottom"]["event_mean"] for f in rs.CANDIDATES},
                "mfe": {f: hr["candidates"][f]["mfe"]["event_mean"] for f in rs.CANDIDATES},
                "mae": {f: hr["candidates"][f]["mae"]["event_mean"] for f in rs.CANDIDATES},
                "h2h_vs_rs63": {f: hr["head_to_head_vs_rs63"][f]["mean_ic_advantage"] for f in rs.CANDIDATES},
                "h2h_p_bonf": {f: hr["head_to_head_vs_rs63"][f]["p_bonferroni"] for f in rs.CANDIDATES},
                "h2h_ci": {f: hr["head_to_head_vs_rs63"][f]["block_bonferroni_ci"] for f in rs.CANDIDATES},
            }
    print("=== RS_PERIOD_FAST_RESULT_JSON ===", flush=True)
    print(json.dumps(compact, ensure_ascii=False, indent=2), flush=True)
    print("=== END_RS_PERIOD_FAST_RESULT_JSON ===", flush=True)


if __name__ == "__main__":
    main()
