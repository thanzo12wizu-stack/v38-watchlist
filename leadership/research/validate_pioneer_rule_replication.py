from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import fisher_exact, beta

import validate_early_rotation as er
import validate_confirmed_leadership as cl
import validate_sector_stock_stack as ss
import validate_ignition_entry as ie
import validate_ignition_quality as iq
import validate_hidden_ignition_breakout as hib

HORIZONS = (5, 10, 20)
DISCOVERY_END = pd.Timestamp("2021-12-31")
CONFIRM_START = pd.Timestamp("2022-01-01")

# Frozen before disjoint-universe replication. These are rounded versions of
# the four discovery-sample medians that showed the strongest, non-redundant
# breakout discrimination. No threshold tuning is performed on this sample.
RULE = {
    "breadth_min": 80.0,
    "rvol20_min": 0.80,
    "ema21_atr_min": 0.60,
    "industry_delta20_min": 10.0,
}

HIDDEN_HIGH_GAP = -0.05
INDUSTRY_MAX = 80.0


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


def exact_binom_ci(k: int, n: int, alpha: float = 0.05) -> list[float | None]:
    if n <= 0:
        return [None, None]
    lo = 0.0 if k == 0 else float(beta.ppf(alpha / 2.0, k, n - k + 1))
    hi = 1.0 if k == n else float(beta.ppf(1.0 - alpha / 2.0, k + 1, n - k))
    return [lo, hi]


def peer_summary(rows: pd.DataFrame, mask: pd.Series, horizon: int, seed: int) -> dict[str, Any]:
    col = f"stock_minus_peers_{horizon}"
    spy = f"stock_minus_spy_{horizon}"
    use = rows.loc[mask, ["entry_date", "theme", col, spy]].dropna(subset=[col]).copy()
    if use.empty:
        return {"n": 0}
    return {
        "n": int(len(use)),
        "mean": float(use[col].mean()),
        "median": float(use[col].median()),
        "positive_rate": float((use[col] > 0).mean()),
        "date_ci95": iq.cluster_boot_ci(use, col, "entry_date", seed),
        "theme_ci95": iq.cluster_boot_ci(use, col, "theme", seed + 1000),
        "spy_mean": float(use[spy].mean()),
    }


def group_breakout_summary(rows: pd.DataFrame, mask: pd.Series) -> dict[str, Any]:
    use = rows.loc[mask].copy()
    n = int(len(use))
    k = int(use["later_breakout"].sum()) if n else 0
    return {
        "n": n,
        "breakouts": k,
        "breakout_rate": float(k / n) if n else None,
        "ci95": exact_binom_ci(k, n),
    }


def score_rows(rows: pd.DataFrame) -> pd.DataFrame:
    out = rows.copy()
    conditions = {
        "breadth_ok": pd.to_numeric(out["breadth"], errors="coerce") >= RULE["breadth_min"],
        "rvol_ok": pd.to_numeric(out["rvol20"], errors="coerce") >= RULE["rvol20_min"],
        "ema21_ok": pd.to_numeric(out["ema21_atr"], errors="coerce") >= RULE["ema21_atr_min"],
        "industry_accel_ok": pd.to_numeric(out["industry_delta20"], errors="coerce") >= RULE["industry_delta20_min"],
    }
    for name, cond in conditions.items():
        out[name] = cond.fillna(False)
    out["pioneer_score4"] = sum(out[name].astype(int) for name in conditions)
    out["pioneer_4of4"] = out["pioneer_score4"] == 4
    return out


def fixed_bucket_summary(rows: pd.DataFrame, feature: str, bins: list[tuple[str, float | None, float | None]]) -> dict[str, Any]:
    x = pd.to_numeric(rows[feature], errors="coerce")
    out: dict[str, Any] = {}
    for label, lo, hi in bins:
        mask = x.notna()
        if lo is not None:
            mask &= x >= lo
        if hi is not None:
            mask &= x < hi
        out[label] = group_breakout_summary(rows, mask)
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", default="leadership/research/pioneer_rule_replication_output")
    parser.add_argument("--analysis-start", default="2016-01-04")
    parser.add_argument("--analysis-end", default="2026-06-20")
    parser.add_argument("--primary-max-tickers", type=int, default=1500)
    parser.add_argument("--replication-max-tickers", type=int, default=1500)
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
    allowed = set(industry_map) & universe

    # The original research sample is deterministically reconstructed and then
    # excluded. The replication universe is therefore ticker-disjoint.
    primary_symbols = er.stratified_symbols(theme_members_all, allowed, args.primary_max_tickers)
    replication_allowed = allowed - set(primary_symbols)
    selected = er.stratified_symbols(theme_members_all, replication_allowed, args.replication_max_tickers)
    requested = selected + (["SPY"] if "SPY" not in selected else [])

    download_start = str((pd.Timestamp(args.analysis_start) - pd.Timedelta(days=620)).date())
    download_end = str((pd.Timestamp(args.analysis_end) + pd.Timedelta(days=120)).date())
    ohlcv, download_diag = iq.download_ohlcv(requested, download_start, download_end, args.batch_size)
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
    sector_weights = ss.build_sector_weights(theme_members_all, industry_map)
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
    momentum_mask = cl.momentum_mask(theme_pct, parent_industry_pct, breadth)
    events = er.extract_events(momentum_mask, theme_pct, parent_industry_pct, breadth, member_counts, start, end)
    stock_period21 = er.period_return(stock_ret, 21)

    original_peer = ie.rs.event_peer_returns
    peer_cache: dict[tuple[tuple[str, ...], int, int], dict[str, float]] = {}

    def cached_peer(stock_ret_arg: pd.DataFrame, members: list[str], pos: int, horizon: int) -> dict[str, float]:
        key = (tuple(members), int(pos), int(horizon))
        if key not in peer_cache:
            peer_cache[key] = original_peer(stock_ret_arg, members, pos, horizon)
        return peer_cache[key]

    ie.rs.event_peer_returns = cached_peer
    rows = ie.build_entry_rows(
        events,
        momentum_mask,
        theme_members,
        stock_close,
        stock_high,
        stock_low,
        stock_ret,
        spy_ret,
        stock_period21,
        theme_pct,
        parent_industry_pct,
        parent_sector_pct,
        breadth,
    )
    matrices = iq.compute_feature_matrices(ohlcv, stock_cols, stock_ret)
    rows = iq.enrich_rows(rows, matrices, theme_members)

    hidden_mask = (
        rows["continuous_momentum"].fillna(False)
        & (pd.to_numeric(rows["dist_prior_high20"], errors="coerce") <= HIDDEN_HIGH_GAP)
        & (pd.to_numeric(rows["industry_rs"], errors="coerce") < INDUSTRY_MAX)
    )
    hidden = rows.loc[hidden_mask].copy()
    hidden["row_key"] = hidden.apply(lambda r: f"{pd.Timestamp(r.entry_date).date()}|{r.theme}|{r.symbol}", axis=1)

    breakout, breakout_keys = hib.build_breakout_rows(hidden, theme_members, stock_close, stock_high, stock_low, stock_ret, spy_ret)
    hidden["later_breakout"] = hidden["row_key"].isin(breakout_keys)
    hidden = score_rows(hidden)

    result: dict[str, Any] = {
        "status": "PRELIMINARY_FIXED_CURRENT_TAXONOMY_DISJOINT_TICKER_REPLICATION",
        "question": "Does the frozen 4-factor Hidden-Ignition pioneer rule replicate on a ticker-disjoint universe?",
        "frozen_rule": {
            "base": "continuous Subtheme Momentum + new within-theme RS21 top-third ignition + at least 5% below prior 20-day intraday high + Industry RS<80",
            "pioneer_4of4": RULE,
            "label": "first close above prior 20-day intraday high within 10 trading days after ignition",
            "rule_selection_note": "thresholds fixed before this disjoint-ticker replication; no tuning on replication outcomes",
        },
        "coverage": {
            "primary_symbols_excluded": int(len(primary_symbols)),
            "replication_symbols_requested": int(len(selected)),
            "replication_symbols_downloaded": int(len(stock_cols)),
            "overlap_with_primary": int(len(set(primary_symbols) & set(stock_cols))),
            "themes_with_returns": int(len(common_themes)),
            "momentum_events": int(len(events)),
            "hidden_rows": int(len(hidden)),
            "hidden_dates": int(hidden["entry_date"].nunique()) if len(hidden) else 0,
            "hidden_themes": int(hidden["theme"].nunique()) if len(hidden) else 0,
        },
        "download": download_diag,
        "taxonomy_candidates": taxonomy_candidates,
        "all": {},
        "confirmation_2022_2026H1": {},
        "yearly": {},
        "fixed_context_buckets": {},
    }

    for label, frame in {
        "all": hidden,
        "confirmation_2022_2026H1": hidden[hidden["entry_date"] >= CONFIRM_START],
    }.items():
        if frame.empty:
            result[label] = {"n": 0}
            continue
        base = group_breakout_summary(frame, pd.Series(True, index=frame.index))
        selected_mask = frame["pioneer_4of4"].fillna(False)
        selected_summary = group_breakout_summary(frame, selected_mask)
        complement_summary = group_breakout_summary(frame, ~selected_mask)
        table = [
            [selected_summary["breakouts"], selected_summary["n"] - selected_summary["breakouts"]],
            [complement_summary["breakouts"], complement_summary["n"] - complement_summary["breakouts"]],
        ]
        if selected_summary["n"] and complement_summary["n"]:
            odds, p = fisher_exact(table, alternative="greater")
        else:
            odds, p = (np.nan, np.nan)
        score_levels = {
            str(score): group_breakout_summary(frame, frame["pioneer_score4"] == score)
            for score in range(5)
        }
        result[label] = {
            "base": base,
            "pioneer_4of4": selected_summary,
            "complement": complement_summary,
            "breakout_rate_lift_pp": (
                100.0 * (selected_summary["breakout_rate"] - base["breakout_rate"])
                if selected_summary["breakout_rate"] is not None and base["breakout_rate"] is not None else None
            ),
            "fisher_greater_odds": float(odds) if math.isfinite(float(odds)) else None,
            "fisher_greater_p": float(p) if math.isfinite(float(p)) else None,
            "score_levels": score_levels,
            "forward_peer": {
                str(h): {
                    "pioneer_4of4": peer_summary(frame, selected_mask, h, 20000 + h),
                    "complement": peer_summary(frame, ~selected_mask, h, 21000 + h),
                }
                for h in HORIZONS
            },
        }

    for year, frame in hidden.groupby(hidden["entry_date"].dt.year):
        sel = frame["pioneer_4of4"].fillna(False)
        result["yearly"][str(int(year))] = {
            "base": group_breakout_summary(frame, pd.Series(True, index=frame.index)),
            "pioneer_4of4": group_breakout_summary(frame, sel),
        }

    confirm = hidden[hidden["entry_date"] >= CONFIRM_START].copy()
    if len(confirm):
        result["fixed_context_buckets"] = {
            "sector_rs": fixed_bucket_summary(confirm, "sector_rs", [
                ("LT40", None, 40.0), ("40_60", 40.0, 60.0), ("60_80", 60.0, 80.0), ("GE80", 80.0, None)
            ]),
            "theme_rs": fixed_bucket_summary(confirm, "theme_rs", [
                ("80_90", 80.0, 90.0), ("GE90", 90.0, None)
            ]),
            "industry_rs": fixed_bucket_summary(confirm, "industry_rs", [
                ("LT40", None, 40.0), ("40_60", 40.0, 60.0), ("60_80", 60.0, 80.0)
            ]),
            "industry_delta20": fixed_bucket_summary(confirm, "industry_delta20", [
                ("LT10", None, 10.0), ("GE10", 10.0, None)
            ]),
        }

    safe_result = safe(result)
    hidden.to_csv(output / "replication_hidden_rows.csv.gz", index=False, compression="gzip")
    breakout.to_csv(output / "replication_breakout_rows.csv.gz", index=False, compression="gzip")
    (output / "summary.json").write_text(json.dumps(safe_result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== PIONEER_RULE_REPLICATION_RESULT_JSON ===", flush=True)
    print(json.dumps(safe_result, ensure_ascii=False, indent=2), flush=True)
    print("=== END_PIONEER_RULE_REPLICATION_RESULT_JSON ===", flush=True)


if __name__ == "__main__":
    main()
