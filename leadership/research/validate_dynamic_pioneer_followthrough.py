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
import validate_sector_stock_stack as ss
import validate_ignition_entry as ie
import validate_ignition_quality as iq

HORIZONS = (5, 10, 20)
DELAYS = (2, 3)
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


def cluster_ci(rows: pd.DataFrame, value_col: str, cluster_col: str, seed: int) -> list[float | None]:
    return iq.cluster_boot_ci(rows, value_col, cluster_col, seed)


def summarize(rows: pd.DataFrame, horizon: int, seed: int) -> dict[str, Any]:
    col = f"stock_minus_peers_{horizon}"
    spy = f"stock_minus_spy_{horizon}"
    mfe = f"mfe_{horizon}"
    mae = f"mae_{horizon}"
    use = rows[["entry_date", "theme", "symbol", col, spy, mfe, mae]].dropna(subset=[col]).copy()
    if use.empty:
        return {"n": 0}
    return {
        "n": int(len(use)),
        "dates": int(use["entry_date"].nunique()),
        "themes": int(use["theme"].nunique()),
        "peer_mean": float(use[col].mean()),
        "peer_median": float(use[col].median()),
        "peer_positive_rate": float((use[col] > 0).mean()),
        "peer_date_ci95": cluster_ci(use, col, "entry_date", seed),
        "peer_theme_ci95": cluster_ci(use, col, "theme", seed + 1000),
        "spy_mean": float(use[spy].mean()),
        "mfe_mean": float(use[mfe].mean()),
        "mae_mean": float(use[mae].mean()),
    }


def paired_wait_summary(rows: pd.DataFrame, horizon: int, seed: int) -> dict[str, Any]:
    c = f"stock_minus_peers_{horizon}"
    i = f"ignition_peer_{horizon}"
    use = rows[["ignition_date", "theme", c, i]].dropna().copy()
    if use.empty:
        return {"n": 0}
    use["delta"] = use[c] - use[i]
    return {
        "n": int(len(use)),
        "confirm_peer_mean": float(use[c].mean()),
        "ignition_peer_mean": float(use[i].mean()),
        "wait_minus_ignite": float(use["delta"].mean()),
        "date_ci95": cluster_ci(use, "delta", "ignition_date", seed),
        "theme_ci95": cluster_ci(use, "delta", "theme", seed + 1000),
    }


def build_followthrough_rows(
    hidden: pd.DataFrame,
    theme_members: dict[str, list[str]],
    close: pd.DataFrame,
    high: pd.DataFrame,
    low: pd.DataFrame,
    stock_ret: pd.DataFrame,
    spy_ret: pd.Series,
    delay: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    prior_high20 = high.shift(1).rolling(20, min_periods=15).max()
    date_pos = {pd.Timestamp(d): i for i, d in enumerate(close.index)}
    stock_fwd = {h: er.forward_return(stock_ret, h) for h in HORIZONS}
    spy_fwd = {h: er.forward_return(spy_ret, h) for h in HORIZONS}
    peer_cache: dict[tuple[tuple[str, ...], int, int], dict[str, float]] = {}

    def peer_returns(members: list[str], pos: int, horizon: int) -> dict[str, float]:
        key = (tuple(members), int(pos), int(horizon))
        if key not in peer_cache:
            peer_cache[key] = ie.rs.event_peer_returns(stock_ret, members, pos, horizon)
        return peer_cache[key]

    diag_records: list[dict[str, Any]] = []
    confirmed_records: list[dict[str, Any]] = []

    for row in hidden.itertuples(index=False):
        d0 = pd.Timestamp(row.entry_date)
        p0 = date_pos.get(d0, -1)
        sym = str(row.symbol)
        theme = str(row.theme)
        if p0 < 0 or p0 + delay >= len(close) or sym not in close.columns:
            continue
        members = [s for s in theme_members.get(theme, []) if s in close.columns]
        if len(members) < 3:
            continue

        p = p0 + delay
        d = close.index[p]
        c0 = close.at[d0, sym]
        c = close.at[d, sym]
        ph0 = high.shift(1).rolling(20, min_periods=15).max().at[d0, sym]
        ph = prior_high20.at[d, sym]
        if pd.isna(c0) or pd.isna(c) or pd.isna(ph0) or pd.isna(ph) or c0 <= 0 or ph0 <= 0 or ph <= 0:
            continue

        stock_since = float(c / c0 - 1.0)
        peer_since_map = ie.rs.event_peer_returns(stock_ret, members, p0, delay)
        peer_since = peer_since_map.get(sym, np.nan)
        peer_excess_since = stock_since - peer_since if pd.notna(peer_since) else np.nan
        dist0 = float(c0 / ph0 - 1.0)
        dist_now = float(c / ph - 1.0)

        fast_breakout = False
        for q in range(p0 + 1, p + 1):
            dq = close.index[q]
            cq = close.at[dq, sym]
            phq = prior_high20.at[dq, sym]
            if pd.notna(cq) and pd.notna(phq) and float(cq) > float(phq):
                fast_breakout = True
                break

        price_up = stock_since > 0.0
        peer_up = pd.notna(peer_excess_since) and float(peer_excess_since) > 0.0
        high_gap_shrinking = dist_now > dist0
        prebreakout_confirm = bool(price_up and peer_up and high_gap_shrinking and not fast_breakout)
        any_confirm = bool(price_up and peer_up and high_gap_shrinking)

        diag = {
            "ignition_date": d0,
            "check_date": d,
            "theme": theme,
            "symbol": sym,
            "delay": delay,
            "stock_since_ignite": stock_since,
            "peer_excess_since_ignite": float(peer_excess_since) if pd.notna(peer_excess_since) else np.nan,
            "dist_high20_ignite": dist0,
            "dist_high20_check": dist_now,
            "price_up": price_up,
            "peer_up": peer_up,
            "high_gap_shrinking": high_gap_shrinking,
            "fast_breakout_by_check": fast_breakout,
            "any_followthrough": any_confirm,
            "prebreakout_followthrough": prebreakout_confirm,
        }
        diag_records.append(diag)
        if not prebreakout_confirm:
            continue

        entry_price = float(c)
        rec: dict[str, Any] = {
            "entry_date": d,
            "ignition_date": d0,
            "theme": theme,
            "symbol": sym,
            "delay": delay,
            "stock_since_ignite": stock_since,
            "peer_excess_since_ignite": float(peer_excess_since),
            "dist_high20_ignite": dist0,
            "dist_high20_check": dist_now,
        }
        for h in HORIZONS:
            sr = stock_fwd[h].at[d, sym] if d in stock_fwd[h].index else np.nan
            sp = spy_fwd[h].at[d] if d in spy_fwd[h].index else np.nan
            pr = peer_returns(members, p, h).get(sym, np.nan)
            future_dates = close.index[p + 1:min(p + h + 1, len(close))]
            highs = high.loc[future_dates, sym].dropna()
            lows = low.loc[future_dates, sym].dropna()
            rec[f"stock_minus_peers_{h}"] = sr - pr if pd.notna(sr) and pd.notna(pr) else np.nan
            rec[f"stock_minus_spy_{h}"] = sr - sp if pd.notna(sr) and pd.notna(sp) else np.nan
            rec[f"mfe_{h}"] = float(highs.max() / entry_price - 1.0) if len(highs) else np.nan
            rec[f"mae_{h}"] = float(lows.min() / entry_price - 1.0) if len(lows) else np.nan
            rec[f"ignition_peer_{h}"] = getattr(row, f"stock_minus_peers_{h}")
        confirmed_records.append(rec)

    return pd.DataFrame(diag_records), pd.DataFrame(confirmed_records)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", required=True)
    parser.add_argument("--analysis-start", default="2016-01-04")
    parser.add_argument("--analysis-end", default="2026-06-20")
    parser.add_argument("--exclude-first", type=int, default=0)
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
    allowed = set(industry_map) & universe
    excluded = er.stratified_symbols(theme_members_all, allowed, args.exclude_first) if args.exclude_first > 0 else []
    selected = er.stratified_symbols(theme_members_all, allowed - set(excluded), args.max_tickers)
    requested = selected + (["SPY"] if "SPY" not in selected else [])

    download_start = str((pd.Timestamp(args.analysis_start) - pd.Timedelta(days=620)).date())
    download_end = str((pd.Timestamp(args.analysis_end) + pd.Timedelta(days=120)).date())
    ohlcv, download_diag = iq.download_ohlcv(requested, download_start, download_end, args.batch_size)
    close = ohlcv["close"]
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

    result: dict[str, Any] = {
        "status": "PRELIMINARY_FIXED_CURRENT_TAXONOMY",
        "frozen_definition": {
            "base": "continuous Subtheme Momentum + new within-theme RS21 top-third ignition + at least 5% below prior 20-day intraday high + Industry RS<80",
            "followthrough_at_Dn": "stock close above ignition close AND stock outperforms equal-weight same-theme peers since ignition AND distance to prior 20-day intraday high shrinks",
            "primary_prebreakout": "same three conditions AND no close above prior 20-day intraday high from D+1 through D+n",
            "fast_breakout": "any close above prior 20-day intraday high from D+1 through D+n; reported separately",
            "entry": "D+n close when primary pre-breakout follow-through is first assessed",
            "delays": list(DELAYS),
            "horizons": list(HORIZONS),
        },
        "coverage": {
            "excluded_first": len(excluded),
            "selected": len(stock_cols),
            "overlap_with_excluded": len(set(excluded) & set(stock_cols)),
            "hidden_rows": len(hidden),
            "hidden_dates": int(hidden["entry_date"].nunique()) if len(hidden) else 0,
            "hidden_themes": int(hidden["theme"].nunique()) if len(hidden) else 0,
        },
        "download": download_diag,
        "taxonomy_candidates": taxonomy_candidates,
        "delays": {},
    }

    for delay in DELAYS:
        diag, confirmed = build_followthrough_rows(hidden, theme_members, stock_close, stock_high, stock_low, stock_ret, spy_ret, delay)
        dres: dict[str, Any] = {
            "eligible": int(len(diag)),
            "fast_breakout": int(diag["fast_breakout_by_check"].sum()) if len(diag) else 0,
            "any_followthrough": int(diag["any_followthrough"].sum()) if len(diag) else 0,
            "prebreakout_followthrough": int(diag["prebreakout_followthrough"].sum()) if len(diag) else 0,
            "prebreakout_followthrough_rate": float(diag["prebreakout_followthrough"].mean()) if len(diag) else None,
            "forward": {},
            "paired_wait_vs_ignite": {},
        }
        for h in HORIZONS:
            dres["forward"][str(h)] = summarize(confirmed, h, 30000 + delay * 100 + h) if len(confirmed) else {"n": 0}
            dres["paired_wait_vs_ignite"][str(h)] = paired_wait_summary(confirmed, h, 40000 + delay * 100 + h) if len(confirmed) else {"n": 0}
        result["delays"][str(delay)] = dres
        diag.to_csv(output / f"followthrough_diag_D{delay}.csv.gz", index=False, compression="gzip")
        confirmed.to_csv(output / f"followthrough_entries_D{delay}.csv.gz", index=False, compression="gzip")

    safe_result = safe(result)
    (output / "summary.json").write_text(json.dumps(safe_result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== DYNAMIC_PIONEER_FOLLOWTHROUGH_RESULT_JSON ===", flush=True)
    print(json.dumps(safe_result, ensure_ascii=False, indent=2), flush=True)
    print("=== END_DYNAMIC_PIONEER_FOLLOWTHROUGH_RESULT_JSON ===", flush=True)


if __name__ == "__main__":
    main()
