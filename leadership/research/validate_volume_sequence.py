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
import validate_dynamic_pioneer_followthrough as dpf

HORIZONS = (5, 10, 20)
DELAYS = (2, 3)
HIDDEN_HIGH_GAP = -0.05
INDUSTRY_MAX = 80.0

STATIC_RULES = {
    "DRY5": ("pre5_over_pre20", "le", 0.75),
    "DRY10": ("pre10_over_pre20", "le", 0.85),
    "IGNITION_RVOL_GE1P2": ("ignition_rvol20", "ge", 1.20),
    "IGNITION_VS_PRE5_GE1P5": ("ignition_vs_pre5", "ge", 1.50),
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


def exact_rate(frame: pd.DataFrame, mask: pd.Series) -> dict[str, Any]:
    use = frame.loc[mask].copy()
    n = int(len(use))
    k = int(use["later_breakout"].sum()) if n else 0
    return {"n": n, "breakouts": k, "breakout_rate": float(k / n) if n else None}


def peer_summary(frame: pd.DataFrame, mask: pd.Series, horizon: int, seed: int) -> dict[str, Any]:
    col = f"stock_minus_peers_{horizon}"
    use = frame.loc[mask, ["entry_date", "theme", col]].dropna(subset=[col]).copy()
    if use.empty:
        return {"n": 0}
    return {
        "n": int(len(use)),
        "mean": float(use[col].mean()),
        "median": float(use[col].median()),
        "positive_rate": float((use[col] > 0).mean()),
        "date_ci95": iq.cluster_boot_ci(use, col, "entry_date", seed),
        "theme_ci95": iq.cluster_boot_ci(use, col, "theme", seed + 1000),
    }


def fisher_lift(frame: pd.DataFrame, mask: pd.Series) -> dict[str, Any]:
    a = exact_rate(frame, mask)
    b = exact_rate(frame, ~mask)
    if a["n"] and b["n"]:
        odds, p = fisher_exact([[a["breakouts"], a["n"] - a["breakouts"]], [b["breakouts"], b["n"] - b["breakouts"]]], alternative="greater")
    else:
        odds, p = (np.nan, np.nan)
    return {
        "selected": a,
        "complement": b,
        "lift_pp": (100.0 * (a["breakout_rate"] - b["breakout_rate"])) if a["breakout_rate"] is not None and b["breakout_rate"] is not None else None,
        "odds": float(odds) if np.isfinite(odds) else None,
        "fisher_greater_p": float(p) if np.isfinite(p) else None,
    }


def add_volume_features(hidden: pd.DataFrame, volume: pd.DataFrame) -> pd.DataFrame:
    prev = volume.shift(1)
    pre5 = prev.rolling(5, min_periods=4).mean()
    pre10 = prev.rolling(10, min_periods=7).mean()
    pre20 = prev.rolling(20, min_periods=12).mean()
    out = hidden.copy()
    vals = {k: [] for k in ("pre5_over_pre20", "pre10_over_pre20", "ignition_rvol20", "ignition_vs_pre5")}
    for row in out.itertuples(index=False):
        d = pd.Timestamp(row.entry_date)
        s = str(row.symbol)
        if d not in volume.index or s not in volume.columns:
            for k in vals: vals[k].append(np.nan)
            continue
        v0 = volume.at[d, s]
        v5 = pre5.at[d, s]
        v10 = pre10.at[d, s]
        v20 = pre20.at[d, s]
        vals["pre5_over_pre20"].append(float(v5 / v20) if pd.notna(v5) and pd.notna(v20) and v20 > 0 else np.nan)
        vals["pre10_over_pre20"].append(float(v10 / v20) if pd.notna(v10) and pd.notna(v20) and v20 > 0 else np.nan)
        vals["ignition_rvol20"].append(float(v0 / v20) if pd.notna(v0) and pd.notna(v20) and v20 > 0 else np.nan)
        vals["ignition_vs_pre5"].append(float(v0 / v5) if pd.notna(v0) and pd.notna(v5) and v5 > 0 else np.nan)
    for k, v in vals.items(): out[k] = v
    return out


def rule_mask(frame: pd.DataFrame, rule: str) -> pd.Series:
    feature, op, threshold = STATIC_RULES[rule]
    x = pd.to_numeric(frame[feature], errors="coerce")
    return (x <= threshold if op == "le" else x >= threshold).fillna(False)


def dynamic_volume_summary(diag: pd.DataFrame, volume: pd.DataFrame, hidden: pd.DataFrame, delay: int) -> dict[str, Any]:
    if diag.empty:
        return {"n": 0}
    prev20 = volume.shift(1).rolling(20, min_periods=12).mean()
    hidden_key = {(pd.Timestamp(r.entry_date), str(r.theme), str(r.symbol)): r for r in hidden.itertuples(index=False)}
    vals = []
    for row in diag.itertuples(index=False):
        d0 = pd.Timestamp(row.ignition_date); d = pd.Timestamp(row.check_date); s = str(row.symbol); t = str(row.theme)
        if d0 not in volume.index or d not in volume.index or s not in volume.columns: continue
        p0 = volume.index.get_loc(d0); p = volume.index.get_loc(d)
        if not isinstance(p0, (int, np.integer)) or not isinstance(p, (int, np.integer)): continue
        base = prev20.at[d0, s]
        if pd.isna(base) or base <= 0: continue
        seg = volume.iloc[p0 + 1:p + 1][s].dropna()
        if len(seg) != delay: continue
        vals.append({
            "ignition_date": d0, "theme": t, "symbol": s,
            "prebreakout_followthrough": bool(row.prebreakout_followthrough),
            "follow_volume_rvol": float(seg.mean() / base),
        })
    tab = pd.DataFrame(vals)
    if tab.empty: return {"n": 0}
    out = {"n": int(len(tab))}
    for label, lo, hi in (("LT0P8", None, 0.8), ("0P8_1P2", 0.8, 1.2), ("GE1P2", 1.2, None)):
        x = tab["follow_volume_rvol"]
        mask = x.notna()
        if lo is not None: mask &= x >= lo
        if hi is not None: mask &= x < hi
        use = tab[mask]
        out[label] = {
            "n": int(len(use)),
            "prebreakout_followthrough_rate": float(use["prebreakout_followthrough"].mean()) if len(use) else None,
        }
    return out


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

    root = Path(args.root); output = root / args.output; output.mkdir(parents=True, exist_ok=True)
    snapshot = er.load_json(root / "sector_snapshot.json")
    theme_members_all, taxonomy_candidates = er.extract_theme_members(snapshot)
    industry_map = er.read_industry_map(root / "industry_map.json")
    universe = er.read_universe_symbols(root / "universe.csv")
    allowed = set(industry_map) & universe
    excluded = er.stratified_symbols(theme_members_all, allowed, args.exclude_first) if args.exclude_first > 0 else []
    selected = er.stratified_symbols(theme_members_all, allowed - set(excluded), args.max_tickers)
    requested = selected + (["SPY"] if "SPY" not in selected else [])

    ds = str((pd.Timestamp(args.analysis_start) - pd.Timedelta(days=620)).date())
    de = str((pd.Timestamp(args.analysis_end) + pd.Timedelta(days=120)).date())
    ohlcv, download_diag = iq.download_ohlcv(requested, ds, de, args.batch_size)
    close = ohlcv["close"]; stock_cols = [s for s in selected if s in close.columns]
    stock_close = close[stock_cols]; stock_high = ohlcv["high"][stock_cols]; stock_low = ohlcv["low"][stock_cols]; stock_volume = ohlcv["volume"][stock_cols]
    stock_ret = er.arithmetic_returns(stock_close); spy_ret = er.arithmetic_returns(close[["SPY"]])["SPY"]
    theme_members = {t: [s for s in m if s in stock_cols] for t, m in theme_members_all.items()}; member_counts = {t: len(m) for t, m in theme_members.items()}
    theme_ret = er.grouped_equal_weight(stock_ret, theme_members, args.min_members)
    industry_groups, sector_groups = {}, {}
    for s in stock_cols:
        pair = industry_map.get(s)
        if not pair: continue
        sec, ind = pair
        if sec: sector_groups.setdefault(sec, []).append(s)
        if ind: industry_groups.setdefault(ind, []).append(s)
    industry_ret = er.grouped_equal_weight(stock_ret, industry_groups, args.min_members); sector_ret = er.grouped_equal_weight(stock_ret, sector_groups, args.min_members)
    industry_weights = er.build_parent_weights(theme_members_all, industry_map); sector_weights = ss.build_sector_weights(theme_members_all, industry_map)
    common_themes = sorted(set(theme_ret.columns) & set(industry_weights) & set(sector_weights)); theme_ret = theme_ret[common_themes]
    theme63 = er.period_return(theme_ret, 63); spy63 = er.period_return(spy_ret, 63)
    theme_pct = theme63.sub(spy63, axis=0).rank(axis=1, pct=True, method="average") * 100.0
    industry63 = er.period_return(industry_ret, 63); industry_pct = industry63.sub(spy63, axis=0).rank(axis=1, pct=True, method="average") * 100.0
    parent_industry_pct = er.weighted_matrix(industry_pct, industry_weights, common_themes)
    sector63 = er.period_return(sector_ret, 63); sector_pct = sector63.sub(spy63, axis=0).rank(axis=1, pct=True, method="average") * 100.0
    parent_sector_pct = er.weighted_matrix(sector_pct, sector_weights, common_themes)
    breadth = er.breadth_above_ema21(stock_close, theme_members, args.min_members).reindex(columns=common_themes)
    start, end = pd.Timestamp(args.analysis_start), pd.Timestamp(args.analysis_end)
    momentum_mask = cl.momentum_mask(theme_pct, parent_industry_pct, breadth)
    events = er.extract_events(momentum_mask, theme_pct, parent_industry_pct, breadth, member_counts, start, end)
    stock_period21 = er.period_return(stock_ret, 21)
    rows = ie.build_entry_rows(events, momentum_mask, theme_members, stock_close, stock_high, stock_low, stock_ret, spy_ret, stock_period21, theme_pct, parent_industry_pct, parent_sector_pct, breadth)
    matrices = iq.compute_feature_matrices(ohlcv, stock_cols, stock_ret); rows = iq.enrich_rows(rows, matrices, theme_members)
    hidden = rows[rows["continuous_momentum"].fillna(False) & (pd.to_numeric(rows["dist_prior_high20"], errors="coerce") <= HIDDEN_HIGH_GAP) & (pd.to_numeric(rows["industry_rs"], errors="coerce") < INDUSTRY_MAX)].copy()
    hidden = add_volume_features(hidden, stock_volume)
    hidden["row_key"] = hidden.apply(lambda r: f"{pd.Timestamp(r.entry_date).date()}|{r.theme}|{r.symbol}", axis=1)
    breakout, breakout_keys = hib.build_breakout_rows(hidden, theme_members, stock_close, stock_high, stock_low, stock_ret, spy_ret)
    hidden["later_breakout"] = hidden["row_key"].isin(breakout_keys)

    result = {
        "status": "PRELIMINARY_FIXED_CURRENT_TAXONOMY_VOLUME_SEQUENCE",
        "frozen_definition": {
            "base": "continuous Subtheme Momentum + new within-theme RS21 top-third ignition + at least 5% below prior 20-day intraday high + Industry RS<80",
            "volume_features": {
                "pre5_over_pre20": "prior 5-day mean volume / prior 20-day mean volume, excluding ignition day",
                "pre10_over_pre20": "prior 10-day mean volume / prior 20-day mean volume, excluding ignition day",
                "ignition_rvol20": "ignition volume / prior 20-day mean volume",
                "ignition_vs_pre5": "ignition volume / prior 5-day mean volume",
                "follow_volume_rvol": "D+1..D+n average volume / ignition-date prior20 mean volume",
            },
            "static_thresholds": STATIC_RULES,
            "future_label": "first close above prior 20-day intraday high within 10 trading days after ignition",
            "dynamic_delays": list(DELAYS),
        },
        "coverage": {"excluded_first": len(excluded), "selected": len(stock_cols), "hidden_rows": len(hidden), "hidden_dates": int(hidden["entry_date"].nunique()) if len(hidden) else 0, "hidden_themes": int(hidden["theme"].nunique()) if len(hidden) else 0},
        "download": download_diag,
        "taxonomy_candidates": taxonomy_candidates,
        "static": {},
        "dynamic_volume": {},
    }

    allmask = pd.Series(True, index=hidden.index)
    result["static"]["BASE"] = exact_rate(hidden, allmask)
    masks = {name: rule_mask(hidden, name) for name in STATIC_RULES}
    masks["DRY5_AND_EXPAND"] = masks["DRY5"] & masks["IGNITION_RVOL_GE1P2"]
    masks["DRY10_AND_EXPAND"] = masks["DRY10"] & masks["IGNITION_RVOL_GE1P2"]
    masks["DRY5_AND_VS_PRE5"] = masks["DRY5"] & masks["IGNITION_VS_PRE5_GE1P5"]
    for i, (name, mask) in enumerate(masks.items()):
        result["static"][name] = {"breakout": fisher_lift(hidden, mask), "forward_peer": {str(h): peer_summary(hidden, mask, h, 30000 + i * 100 + h) for h in HORIZONS}}

    for delay in DELAYS:
        diag, confirmed = dpf.build_followthrough_rows(hidden, theme_members, stock_close, stock_high, stock_low, stock_ret, spy_ret, delay)
        result["dynamic_volume"][str(delay)] = dynamic_volume_summary(diag, stock_volume, hidden, delay)

    safe_result = safe(result)
    hidden.to_csv(output / "volume_hidden_rows.csv.gz", index=False, compression="gzip")
    (output / "summary.json").write_text(json.dumps(safe_result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== VOLUME_SEQUENCE_RESULT_JSON ===", flush=True)
    print(json.dumps(safe_result, ensure_ascii=False, indent=2), flush=True)
    print("=== END_VOLUME_SEQUENCE_RESULT_JSON ===", flush=True)

if __name__ == "__main__":
    main()
