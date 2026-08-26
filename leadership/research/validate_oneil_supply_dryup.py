from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import fisher_exact

import validate_early_rotation as er
import validate_confirmed_leadership as cl
import validate_sector_stock_stack as ss
import validate_ignition_entry as ie
import validate_ignition_quality as iq
import validate_hidden_ignition_breakout as hib

HORIZONS = (5, 10, 20)
HIDDEN_HIGH_GAP = -0.05
INDUSTRY_MAX = 80.0
DISCOVERY_END = pd.Timestamp("2021-12-31")
CONFIRM_START = pd.Timestamp("2022-01-01")

# Frozen before outcomes. These are deliberately simple operational proxies for
# O'Neil chart annotations such as tight closes, volume drying up in the base,
# accumulation on strength, and weekly tightness. They are not claimed to be
# exact CAN SLIM definitions.
THRESHOLDS = {
    "tr5_over_tr20_max": 0.75,
    "close_range5_max": 0.06,
    "downvol10_over_vol20_max": 0.80,
    "net_accum20_min": 1,
    "weekly_close_range3_max": 0.08,
    "weekly_vol3_over10_max": 0.85,
    "ignition_rvol20_min": 1.20,
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


def cluster_boot_ci(table: pd.DataFrame, value_col: str, cluster_col: str, seed: int, reps: int = 3000) -> list[float | None]:
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


def exact_rate(frame: pd.DataFrame, mask: pd.Series) -> dict[str, Any]:
    use = frame.loc[mask]
    n = int(len(use))
    k = int(use["later_breakout"].sum()) if n else 0
    return {"n": n, "breakouts": k, "breakout_rate": float(k / n) if n else None}


def fisher_lift(frame: pd.DataFrame, mask: pd.Series) -> dict[str, Any]:
    a = exact_rate(frame, mask)
    b = exact_rate(frame, ~mask)
    if a["n"] and b["n"]:
        odds, p = fisher_exact(
            [[a["breakouts"], a["n"] - a["breakouts"]], [b["breakouts"], b["n"] - b["breakouts"]]],
            alternative="greater",
        )
    else:
        odds, p = np.nan, np.nan
    return {
        "selected": a,
        "complement": b,
        "lift_pp": 100.0 * (a["breakout_rate"] - b["breakout_rate"]) if a["breakout_rate"] is not None and b["breakout_rate"] is not None else None,
        "odds": float(odds) if np.isfinite(odds) else None,
        "fisher_greater_p": float(p) if np.isfinite(p) else None,
    }


def forward_summary(frame: pd.DataFrame, mask: pd.Series, horizon: int, seed: int) -> dict[str, Any]:
    peer = f"stock_minus_peers_{horizon}"
    cols = ["entry_date", "theme", peer]
    for optional in (f"mfe_{horizon}", f"mae_{horizon}"):
        if optional in frame.columns:
            cols.append(optional)
    use = frame.loc[mask, cols].dropna(subset=[peer]).copy()
    if use.empty:
        return {"n": 0}
    out = {
        "n": int(len(use)),
        "dates": int(use["entry_date"].nunique()),
        "themes": int(use["theme"].nunique()),
        "peer_mean": float(use[peer].mean()),
        "peer_median": float(use[peer].median()),
        "peer_positive_rate": float((use[peer] > 0).mean()),
        "peer_date_ci95": cluster_boot_ci(use, peer, "entry_date", seed),
        "peer_theme_ci95": cluster_boot_ci(use, peer, "theme", seed + 1000),
    }
    if f"mfe_{horizon}" in use.columns:
        out["mfe_mean"] = float(use[f"mfe_{horizon}"].mean())
    if f"mae_{horizon}" in use.columns:
        out["mae_mean"] = float(use[f"mae_{horizon}"].mean())
    return out


def add_supply_features(hidden: pd.DataFrame, ohlcv: dict[str, pd.DataFrame], stock_cols: list[str]) -> pd.DataFrame:
    close = ohlcv["close"][stock_cols]
    high = ohlcv["high"][stock_cols]
    low = ohlcv["low"][stock_cols]
    volume = ohlcv["volume"][stock_cols]
    ret = close.pct_change()

    tr = iq.true_range(high, low, close)
    tr_prev = tr.shift(1)
    tr5 = tr_prev.rolling(5, min_periods=4).mean()
    tr20 = tr_prev.rolling(20, min_periods=12).mean()
    tr5_over_tr20 = tr5 / tr20.replace(0.0, np.nan)

    prev_close = close.shift(1)
    close5_max = prev_close.rolling(5, min_periods=4).max()
    close5_min = prev_close.rolling(5, min_periods=4).min()
    close_range5 = close5_max / close5_min.replace(0.0, np.nan) - 1.0

    prev_vol20 = volume.shift(1).rolling(20, min_periods=12).mean()
    down_vol = volume.where(ret < 0).shift(1)
    down_count10 = (ret < 0).shift(1).rolling(10, min_periods=7).sum()
    down_sum10 = down_vol.rolling(10, min_periods=7).sum()
    down_mean10 = down_sum10 / down_count10.replace(0.0, np.nan)
    downvol10_over_vol20 = down_mean10 / prev_vol20.replace(0.0, np.nan)

    prior_rvol20 = volume / volume.shift(1).rolling(20, min_periods=12).mean().replace(0.0, np.nan)
    accum_flag = ((ret >= 0.01) & (prior_rvol20 >= 1.20)).shift(1)
    dist_flag = ((ret <= -0.01) & (prior_rvol20 >= 1.20)).shift(1)
    accum20 = accum_flag.rolling(20, min_periods=12).sum()
    dist20 = dist_flag.rolling(20, min_periods=12).sum()
    net_accum20 = accum20 - dist20
    ignition_rvol20 = volume / prev_vol20.replace(0.0, np.nan)

    # Weekly features use only completed weeks strictly before the ignition date.
    weekly_close = close.resample("W-FRI").last()
    weekly_volume = volume.resample("W-FRI").sum(min_count=1)
    weekly_close_range3 = weekly_close.rolling(3, min_periods=3).max() / weekly_close.rolling(3, min_periods=3).min().replace(0.0, np.nan) - 1.0
    weekly_vol3 = weekly_volume.rolling(3, min_periods=3).mean()
    weekly_vol10 = weekly_volume.rolling(10, min_periods=7).mean()
    weekly_vol3_over10 = weekly_vol3 / weekly_vol10.replace(0.0, np.nan)
    weekly_index = weekly_close.index

    out = hidden.copy()
    feature_names = (
        "tr5_over_tr20",
        "close_range5",
        "downvol10_over_vol20",
        "net_accum20",
        "weekly_close_range3",
        "weekly_vol3_over10",
        "ignition_rvol20",
    )
    values = {k: [] for k in feature_names}

    for row in out.itertuples(index=False):
        d = pd.Timestamp(row.entry_date)
        s = str(row.symbol)
        if s not in close.columns or d not in close.index:
            for k in feature_names:
                values[k].append(np.nan)
            continue
        for k, matrix in (
            ("tr5_over_tr20", tr5_over_tr20),
            ("close_range5", close_range5),
            ("downvol10_over_vol20", downvol10_over_vol20),
            ("net_accum20", net_accum20),
            ("ignition_rvol20", ignition_rvol20),
        ):
            v = matrix.at[d, s]
            values[k].append(float(v) if pd.notna(v) else np.nan)

        # Strictly prior completed Friday; no ignition-week lookahead.
        pos = weekly_index.searchsorted(d, side="left") - 1
        if pos >= 0:
            wd = weekly_index[pos]
            wcr = weekly_close_range3.at[wd, s] if s in weekly_close_range3.columns else np.nan
            wvr = weekly_vol3_over10.at[wd, s] if s in weekly_vol3_over10.columns else np.nan
        else:
            wcr = np.nan
            wvr = np.nan
        values["weekly_close_range3"].append(float(wcr) if pd.notna(wcr) else np.nan)
        values["weekly_vol3_over10"].append(float(wvr) if pd.notna(wvr) else np.nan)

    for k, vals in values.items():
        out[k] = vals
    return out


def build_rule_masks(frame: pd.DataFrame) -> dict[str, pd.Series]:
    t = THRESHOLDS
    tr = pd.to_numeric(frame["tr5_over_tr20"], errors="coerce")
    cr = pd.to_numeric(frame["close_range5"], errors="coerce")
    dv = pd.to_numeric(frame["downvol10_over_vol20"], errors="coerce")
    na = pd.to_numeric(frame["net_accum20"], errors="coerce")
    wr = pd.to_numeric(frame["weekly_close_range3"], errors="coerce")
    wv = pd.to_numeric(frame["weekly_vol3_over10"], errors="coerce")
    rv = pd.to_numeric(frame["ignition_rvol20"], errors="coerce")

    price_tight = (tr <= t["tr5_over_tr20_max"]) & (cr <= t["close_range5_max"])
    supply_dry = dv <= t["downvol10_over_vol20_max"]
    accum_dom = na >= t["net_accum20_min"]
    weekly_tight_dry = (wr <= t["weekly_close_range3_max"]) & (wv <= t["weekly_vol3_over10_max"])
    ignition_expand = rv >= t["ignition_rvol20_min"]

    return {
        "PRICE_TIGHT": price_tight.fillna(False),
        "SUPPLY_DRY_DOWN": supply_dry.fillna(False),
        "TIGHT_AND_SUPPLY_DRY": (price_tight & supply_dry).fillna(False),
        "ACCUM_DOM": accum_dom.fillna(False),
        "WEEKLY_TIGHT_DRY": weekly_tight_dry.fillna(False),
        "DRY_TO_IGNITION_EXPAND": (price_tight & supply_dry & ignition_expand).fillna(False),
        "ONEIL_CORE": (price_tight & supply_dry & accum_dom).fillna(False),
        "ONEIL_PLUS_WEEKLY": (price_tight & supply_dry & accum_dom & weekly_tight_dry).fillna(False),
    }


def summarize_rule(frame: pd.DataFrame, mask: pd.Series, idx: int) -> dict[str, Any]:
    result = {
        "breakout": fisher_lift(frame, mask),
        "forward": {str(h): forward_summary(frame, mask, h, 50000 + idx * 100 + h) for h in HORIZONS},
        "time_splits": {},
    }
    dates = pd.to_datetime(frame["entry_date"])
    splits = {
        "2016_2021": dates <= DISCOVERY_END,
        "2022_2026H1": dates >= CONFIRM_START,
    }
    for label, smask in splits.items():
        usemask = mask & smask
        result["time_splits"][label] = {
            "breakout": exact_rate(frame, usemask),
            "forward": {str(h): forward_summary(frame, usemask, h, 60000 + idx * 100 + h) for h in HORIZONS},
        }
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--output", required=True)
    ap.add_argument("--analysis-start", default="2016-01-04")
    ap.add_argument("--analysis-end", default="2026-06-20")
    ap.add_argument("--exclude-first", type=int, default=0)
    ap.add_argument("--max-tickers", type=int, default=1500)
    ap.add_argument("--batch-size", type=int, default=75)
    ap.add_argument("--min-members", type=int, default=3)
    args = ap.parse_args()

    root = Path(args.root)
    output = root / args.output
    output.mkdir(parents=True, exist_ok=True)

    snapshot = er.load_json(root / "sector_snapshot.json")
    theme_members_all, taxonomy_candidates = er.extract_theme_members(snapshot)
    industry_map = er.read_industry_map(root / "industry_map.json")
    universe = er.read_universe_symbols(root / "universe.csv")
    allowed = set(industry_map) & universe
    excluded = er.stratified_symbols(theme_members_all, allowed, args.exclude_first) if args.exclude_first > 0 else []
    selected = er.stratified_symbols(theme_members_all, allowed - set(excluded), args.max_tickers)
    requested = selected + (["SPY"] if "SPY" not in selected else [])

    ds = str((pd.Timestamp(args.analysis_start) - pd.Timedelta(days=900)).date())
    de = str((pd.Timestamp(args.analysis_end) + pd.Timedelta(days=120)).date())
    ohlcv, download_diag = iq.download_ohlcv(requested, ds, de, args.batch_size)
    close = ohlcv["close"]
    stock_cols = [s for s in selected if s in close.columns]
    stock_close = close[stock_cols]
    stock_high = ohlcv["high"][stock_cols]
    stock_low = ohlcv["low"][stock_cols]
    stock_ret = er.arithmetic_returns(stock_close)
    spy_ret = er.arithmetic_returns(close[["SPY"]])["SPY"]

    theme_members = {t: [s for s in m if s in stock_cols] for t, m in theme_members_all.items()}
    member_counts = {t: len(m) for t, m in theme_members.items()}
    theme_ret = er.grouped_equal_weight(stock_ret, theme_members, args.min_members)

    industry_groups: dict[str, list[str]] = {}
    sector_groups: dict[str, list[str]] = {}
    for s in stock_cols:
        pair = industry_map.get(s)
        if not pair:
            continue
        sec, ind = pair
        if sec:
            sector_groups.setdefault(sec, []).append(s)
        if ind:
            industry_groups.setdefault(ind, []).append(s)
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
    rows = ie.build_entry_rows(
        events, momentum_mask, theme_members, stock_close, stock_high, stock_low,
        stock_ret, spy_ret, stock_period21, theme_pct, parent_industry_pct,
        parent_sector_pct, breadth,
    )
    matrices = iq.compute_feature_matrices(ohlcv, stock_cols, stock_ret)
    rows = iq.enrich_rows(rows, matrices, theme_members)
    hidden = rows[
        rows["continuous_momentum"].fillna(False)
        & (pd.to_numeric(rows["dist_prior_high20"], errors="coerce") <= HIDDEN_HIGH_GAP)
        & (pd.to_numeric(rows["industry_rs"], errors="coerce") < INDUSTRY_MAX)
    ].copy()
    hidden = add_supply_features(hidden, ohlcv, stock_cols)
    hidden["row_key"] = hidden.apply(lambda r: f"{pd.Timestamp(r.entry_date).date()}|{r.theme}|{r.symbol}", axis=1)
    breakout, breakout_keys = hib.build_breakout_rows(hidden, theme_members, stock_close, stock_high, stock_low, stock_ret, spy_ret)
    hidden["later_breakout"] = hidden["row_key"].isin(breakout_keys)

    rules = build_rule_masks(hidden)
    allmask = pd.Series(True, index=hidden.index)
    result = {
        "status": "PRELIMINARY_FIXED_CURRENT_TAXONOMY_ONEIL_SUPPLY_DRYUP",
        "frozen_definition": {
            "base": "continuous Subtheme Momentum + new within-theme RS21 top-third ignition + at least 5% below prior 20-day intraday high + Industry RS<80",
            "source_inspiration": "O'Neil chart patterns: tight closes/base, volume drying up on pullbacks, accumulation on strength, weekly tightness; operational proxies frozen before outcomes",
            "thresholds": THRESHOLDS,
            "rule_definitions": {
                "PRICE_TIGHT": "prior 5d TR/prior20d TR<=0.75 AND prior5d close range<=6%",
                "SUPPLY_DRY_DOWN": "mean volume on prior10d down days / prior20d mean volume<=0.80",
                "TIGHT_AND_SUPPLY_DRY": "PRICE_TIGHT AND SUPPLY_DRY_DOWN",
                "ACCUM_DOM": "prior20d count(+1% day & RVOL>=1.2) - count(-1% day & RVOL>=1.2) >= 1",
                "WEEKLY_TIGHT_DRY": "3 completed weekly closes within 8% AND prior3wk avg volume/prior10wk avg<=0.85",
                "DRY_TO_IGNITION_EXPAND": "TIGHT_AND_SUPPLY_DRY AND ignition RVOL20>=1.2",
                "ONEIL_CORE": "TIGHT_AND_SUPPLY_DRY AND ACCUM_DOM",
                "ONEIL_PLUS_WEEKLY": "ONEIL_CORE AND WEEKLY_TIGHT_DRY",
            },
            "future_label": "first close above prior 20-day intraday high within 10 trading days after ignition",
        },
        "coverage": {
            "excluded_first": len(excluded),
            "selected": len(stock_cols),
            "overlap_with_excluded": len(set(stock_cols) & set(excluded)),
            "hidden_rows": len(hidden),
            "hidden_dates": int(hidden["entry_date"].nunique()) if len(hidden) else 0,
            "hidden_themes": int(hidden["theme"].nunique()) if len(hidden) else 0,
        },
        "download": download_diag,
        "taxonomy_candidates": taxonomy_candidates,
        "base": {
            "breakout": exact_rate(hidden, allmask),
            "forward": {str(h): forward_summary(hidden, allmask, h, 49000 + h) for h in HORIZONS},
        },
        "rules": {},
    }

    for idx, (name, mask) in enumerate(rules.items()):
        result["rules"][name] = summarize_rule(hidden, mask, idx)

    hidden.to_csv(output / "hidden_supply_features.csv", index=False)
    (output / "summary.json").write_text(json.dumps(safe(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== ONEIL_SUPPLY_DRYUP_RESULT_JSON ===", flush=True)
    print(json.dumps(safe(result), ensure_ascii=False, indent=2), flush=True)
    print("=== END_ONEIL_SUPPLY_DRYUP_RESULT_JSON ===", flush=True)


if __name__ == "__main__":
    main()
