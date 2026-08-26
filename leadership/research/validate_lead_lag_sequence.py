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
import validate_rs_periods as rs
import validate_sector_stock_stack as ss

HORIZONS = (5, 10, 20)
DISCOVERY_END = pd.Timestamp("2021-12-31")
CONFIRM_START = pd.Timestamp("2022-01-01")
STOCK_IGNITION_CUT = 2.0 / 3.0
STOCK_LOOKBACK = 20
STOCK_FUTURE = 20
INDUSTRY_CONFIRM_CUT = 80.0
INDUSTRY_LOOKBACK = 40
INDUSTRY_FUTURE = 20


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


def upward_cross_offsets(series: pd.Series, pos: int, threshold: float, lookback: int, future: int) -> list[int]:
    if pos < 1 or pos >= len(series):
        return []
    lo = max(1, pos - lookback)
    hi = min(len(series) - 1, pos + future)
    out: list[int] = []
    vals = pd.to_numeric(series, errors="coerce")
    for i in range(lo, hi + 1):
        cur = vals.iloc[i]
        prev = vals.iloc[i - 1]
        if pd.notna(cur) and pd.notna(prev) and float(cur) >= threshold and float(prev) < threshold:
            out.append(i - pos)
    return out


def choose_cross_offset(offsets: list[int]) -> tuple[float, float, float]:
    prior = [x for x in offsets if x <= 0]
    future = [x for x in offsets if x > 0]
    last_prior = max(prior) if prior else np.nan
    first_future = min(future) if future else np.nan
    chosen = last_prior if prior else (first_future if future else np.nan)
    return float(chosen) if pd.notna(chosen) else np.nan, float(last_prior) if pd.notna(last_prior) else np.nan, float(first_future) if pd.notna(first_future) else np.nan


def generic_order(stock_offset: float, industry_offset: float) -> str:
    s_ok = pd.notna(stock_offset)
    i_ok = pd.notna(industry_offset)
    if not s_ok and not i_ok:
        return "NEITHER_CROSS_20D"
    if s_ok and not i_ok:
        return "STOCK_ONLY"
    if i_ok and not s_ok:
        return "INDUSTRY_ONLY"
    items = [("STOCK", float(stock_offset)), ("THEME", 0.0), ("INDUSTRY", float(industry_offset))]
    offsets = [x[1] for x in items]
    if len(set(offsets)) < 3:
        return "SIMULTANEOUS"
    items.sort(key=lambda x: x[1])
    return "_".join(x[0] for x in items)


def prelead_bucket(last_prior: float) -> str:
    if pd.isna(last_prior):
        return "NO_PRELEAD"
    age = -int(last_prior)
    if age == 0:
        return "CROSS_AT_THEME"
    if 1 <= age <= 5:
        return "PRELEAD_1_5"
    if 6 <= age <= 10:
        return "PRELEAD_6_10"
    if 11 <= age <= 20:
        return "PRELEAD_11_20"
    return "NO_PRELEAD"


def actionable_sequence(stock_last_prior: float, industry_last_prior: float, industry_at_event: float) -> str:
    if pd.isna(stock_last_prior):
        return "NO_STOCK_PRELEAD"
    if int(stock_last_prior) == 0:
        return "STOCK_CROSS_AT_THEME"
    if float(stock_last_prior) > 0:
        return "NO_STOCK_PRELEAD"
    if pd.notna(industry_at_event) and float(industry_at_event) >= INDUSTRY_CONFIRM_CUT:
        if pd.notna(industry_last_prior):
            if float(industry_last_prior) < float(stock_last_prior):
                return "INDUSTRY_STOCK_THEME"
            if float(stock_last_prior) < float(industry_last_prior):
                return "STOCK_INDUSTRY_THEME"
            return "STOCK_INDUSTRY_SAME_DAY_THEN_THEME"
        return "INDUSTRY_ALREADY_STRONG_STOCK_THEME"
    return "STOCK_THEME_INDUSTRY_NOT_YET_CONFIRMED"


def event_selection_table(rows: pd.DataFrame, mask: pd.Series, horizon: int) -> pd.DataFrame:
    peer = f"stock_minus_peers_{horizon}"
    spy = f"stock_minus_spy_{horizon}"
    mfe = f"mfe_{horizon}"
    mae = f"mae_{horizon}"
    base = rows.groupby(["event_id", "date", "theme"], observed=True).agg(
        baseline_peer=(peer, "mean"),
        baseline_spy=(spy, "mean"),
        baseline_mfe=(mfe, "mean"),
        baseline_mae=(mae, "mean"),
        eligible_stocks=("symbol", "nunique"),
    ).reset_index()
    chosen = rows[mask.fillna(False)].copy()
    if chosen.empty:
        return pd.DataFrame()
    sel = chosen.groupby(["event_id", "date", "theme"], observed=True).agg(
        selected_peer=(peer, "mean"),
        selected_spy=(spy, "mean"),
        selected_mfe=(mfe, "mean"),
        selected_mae=(mae, "mean"),
        selected_stocks=("symbol", "nunique"),
    ).reset_index()
    out = base.merge(sel, on=["event_id", "date", "theme"], how="inner")
    out["peer_lift"] = out["selected_peer"] - out["baseline_peer"]
    out["spy_lift"] = out["selected_spy"] - out["baseline_spy"]
    out["mfe_lift"] = out["selected_mfe"] - out["baseline_mfe"]
    out["mae_lift"] = out["selected_mae"] - out["baseline_mae"]
    return out


def summarize_lift(tab: pd.DataFrame, seed: int) -> dict[str, Any]:
    if tab.empty:
        return {"events": 0, "mean_selected_stocks": None, "peer_lift": None, "peer_date_ci95": [None, None], "peer_theme_ci95": [None, None], "spy_lift": None, "mfe_lift": None, "mae_lift": None, "discovery_peer_lift": None, "confirmation_peer_lift": None}
    disc = tab.loc[tab["date"] <= DISCOVERY_END, "peer_lift"]
    conf = tab.loc[tab["date"] >= CONFIRM_START, "peer_lift"]
    return {
        "events": int(len(tab)),
        "dates": int(tab["date"].nunique()),
        "themes": int(tab["theme"].nunique()),
        "mean_selected_stocks": float(tab["selected_stocks"].mean()),
        "peer_lift": float(tab["peer_lift"].mean()),
        "peer_date_ci95": ss.cluster_ci(tab, "peer_lift", "date", seed),
        "peer_theme_ci95": ss.cluster_ci(tab, "peer_lift", "theme", seed + 1000),
        "spy_lift": float(tab["spy_lift"].mean()),
        "mfe_lift": float(tab["mfe_lift"].mean()),
        "mae_lift": float(tab["mae_lift"].mean()),
        "discovery_peer_lift": float(disc.mean()) if len(disc) else None,
        "confirmation_peer_lift": float(conf.mean()) if len(conf) else None,
    }


def summarize_group_absolute(rows: pd.DataFrame, horizon: int, seed: int) -> dict[str, Any]:
    if rows.empty:
        return {"rows": 0, "events": 0}
    peer = f"stock_minus_peers_{horizon}"
    spy = f"stock_minus_spy_{horizon}"
    mfe = f"mfe_{horizon}"
    mae = f"mae_{horizon}"
    ev = rows.groupby(["event_id", "date", "theme"], observed=True).agg(
        peer=(peer, "mean"), spy=(spy, "mean"), mfe=(mfe, "mean"), mae=(mae, "mean"), selected_stocks=("symbol", "nunique")
    ).reset_index()
    return {
        "rows": int(len(rows)),
        "events": int(len(ev)),
        "dates": int(ev["date"].nunique()),
        "themes": int(ev["theme"].nunique()),
        "mean_selected_stocks": float(ev["selected_stocks"].mean()),
        "peer_mean": float(ev["peer"].mean()),
        "peer_date_ci95": ss.cluster_ci(ev, "peer", "date", seed),
        "peer_theme_ci95": ss.cluster_ci(ev, "peer", "theme", seed + 1000),
        "spy_mean": float(ev["spy"].mean()),
        "mfe_mean": float(ev["mfe"].mean()),
        "mae_mean": float(ev["mae"].mean()),
    }


def build_sequence_features(
    events: pd.DataFrame,
    theme_members: dict[str, list[str]],
    stock_period21: pd.DataFrame,
    stock_close: pd.DataFrame,
    parent_industry_pct: pd.DataFrame,
    parent_sector_pct: pd.DataFrame,
) -> pd.DataFrame:
    date_pos = {pd.Timestamp(d): i for i, d in enumerate(stock_close.index)}
    rank_cache: dict[tuple[str, pd.Timestamp], pd.Series] = {}

    def ranks(theme: str, date: pd.Timestamp) -> pd.Series:
        key = (theme, date)
        if key in rank_cache:
            return rank_cache[key]
        members = [s for s in theme_members.get(theme, []) if s in stock_period21.columns]
        if date not in stock_period21.index or len(members) < 3:
            out = pd.Series(np.nan, index=members)
        else:
            out = rs.rank_within(stock_period21.loc[date, members])
        rank_cache[key] = out
        return out

    records: list[dict[str, Any]] = []
    for ei, event in enumerate(events.itertuples(index=False)):
        date = pd.Timestamp(event.date)
        theme = str(event.theme)
        pos = date_pos.get(date, -1)
        if pos < 1:
            continue
        members = [s for s in theme_members.get(theme, []) if s in stock_period21.columns]
        if len(members) < 3:
            continue

        industry_series = parent_industry_pct[theme] if theme in parent_industry_pct.columns else pd.Series(dtype=float)
        sector_series = parent_sector_pct[theme] if theme in parent_sector_pct.columns else pd.Series(dtype=float)
        if len(industry_series) == 0 or date not in industry_series.index:
            continue
        ipos = industry_series.index.get_indexer([date])[0]
        if ipos < 0:
            continue
        ind_offsets = upward_cross_offsets(industry_series, ipos, INDUSTRY_CONFIRM_CUT, INDUSTRY_LOOKBACK, INDUSTRY_FUTURE)
        industry_chosen, industry_last_prior, industry_first_future = choose_cross_offset(ind_offsets)
        industry_at_event = industry_series.iloc[ipos]
        sector_at_event = sector_series.loc[date] if len(sector_series) and date in sector_series.index else np.nan

        window_lo = max(1, pos - STOCK_LOOKBACK)
        window_hi = min(len(stock_close.index) - 1, pos + STOCK_FUTURE)
        rank_by_pos: dict[int, pd.Series] = {}
        for p in range(window_lo - 1, window_hi + 1):
            if p < 0:
                continue
            rank_by_pos[p] = ranks(theme, stock_close.index[p])

        event_id = f"{date.date()}|{theme}"
        for sym in members:
            offsets: list[int] = []
            for p in range(window_lo, window_hi + 1):
                cur = rank_by_pos[p].get(sym, np.nan)
                prev = rank_by_pos[p - 1].get(sym, np.nan)
                if pd.notna(cur) and pd.notna(prev) and float(cur) >= STOCK_IGNITION_CUT and float(prev) < STOCK_IGNITION_CUT:
                    offsets.append(p - pos)
            stock_chosen, stock_last_prior, stock_first_future = choose_cross_offset(offsets)
            event_rank = rank_by_pos[pos].get(sym, np.nan)
            action = actionable_sequence(stock_last_prior, industry_last_prior, industry_at_event)
            full_order = generic_order(stock_chosen, industry_chosen)
            ex_post = full_order
            if action == "STOCK_THEME_INDUSTRY_NOT_YET_CONFIRMED" and pd.notna(industry_first_future):
                ex_post = "STOCK_THEME_INDUSTRY"
            elif action == "STOCK_THEME_INDUSTRY_NOT_YET_CONFIRMED" and pd.isna(industry_first_future):
                ex_post = "STOCK_THEME_NO_INDUSTRY20"
            records.append({
                "event_id": event_id,
                "date": date,
                "theme": theme,
                "symbol": sym,
                "stock_rs21_event": float(event_rank) if pd.notna(event_rank) else np.nan,
                "stock_cross_offset": stock_chosen,
                "stock_last_prior_offset": stock_last_prior,
                "stock_first_future_offset": stock_first_future,
                "prelead_bucket": prelead_bucket(stock_last_prior),
                "stock_prelead": bool(pd.notna(stock_last_prior) and -STOCK_LOOKBACK <= float(stock_last_prior) <= -1),
                "industry_rs_event": float(industry_at_event) if pd.notna(industry_at_event) else np.nan,
                "industry_cross_offset": industry_chosen,
                "industry_last_prior_offset": industry_last_prior,
                "industry_first_future_offset": industry_first_future,
                "industry_ge80_event": bool(pd.notna(industry_at_event) and float(industry_at_event) >= INDUSTRY_CONFIRM_CUT),
                "sector_rs_event": float(sector_at_event) if pd.notna(sector_at_event) else np.nan,
                "sector_ge80_event": bool(pd.notna(sector_at_event) and float(sector_at_event) >= 80.0),
                "actionable_sequence": action,
                "ex_post_order": ex_post,
            })
        if (ei + 1) % 500 == 0:
            print(f"SEQUENCE_FEATURES {ei + 1}/{len(events)} rows={len(records)} cache={len(rank_cache)}", flush=True)
    return pd.DataFrame(records)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", default="leadership/research/lead_lag_output")
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
    mask = cl.momentum_mask(theme_pct, parent_industry_pct, breadth)
    events = er.extract_events(mask, theme_pct, parent_industry_pct, breadth, member_counts, start, end)
    events["sector_rs_pct"] = [
        float(parent_sector_pct.at[pd.Timestamp(d), str(t)]) if str(t) in parent_sector_pct.columns and pd.Timestamp(d) in parent_sector_pct.index and pd.notna(parent_sector_pct.at[pd.Timestamp(d), str(t)]) else np.nan
        for d, t in zip(events["date"], events["theme"])
    ]

    stock_period21 = er.period_return(stock_ret, 21)
    seq = build_sequence_features(events, theme_members, stock_period21, stock_close, parent_industry_pct, parent_sector_pct)
    stock_period = {p: er.period_return(stock_ret, p) for p in rs.RS_PERIODS}
    rows = rs.extract_rows(events, theme_members, stock_close, stock_high, stock_low, stock_ret, spy_ret, stock_period)
    rows = rows.merge(seq.drop(columns=["date", "theme"]), on=["event_id", "symbol"], how="left")

    result: dict[str, Any] = {
        "status": "PRELIMINARY_FIXED_CURRENT_TAXONOMY",
        "question": "Does the timing order Stock RS21 ignition -> Subtheme Momentum -> Industry confirmation identify pioneer stocks better than static RS strength?",
        "frozen_definitions": {
            "subtheme_momentum": cl.MOMENTUM_CONFIG,
            "stock_ignition": "within-theme 21d return percentile crosses upward into top third (>=2/3) from below",
            "stock_prelead_window_trading_days": STOCK_LOOKBACK,
            "stock_future_window_trading_days": STOCK_FUTURE,
            "industry_confirmation": "theme-weighted parent TradingView Industry 63d RS percentile crosses upward through 80",
            "industry_prior_window_trading_days": INDUSTRY_LOOKBACK,
            "industry_future_window_trading_days": INDUSTRY_FUTURE,
            "prelead_age_buckets": ["1-5", "6-10", "11-20"],
            "sector_role": "background variable only; not a gate",
            "horizons": list(HORIZONS),
            "outcome_anchor": "Subtheme Momentum event date; no future information is needed for primary actionable tests",
            "ex_post_warning": "ex_post_order uses future stock/industry crossings and is diagnostic only, never a real-time signal",
        },
        "coverage": {
            "selected_stocks": int(len(stock_cols)),
            "events": int(len(events)),
            "event_stock_rows": int(len(rows)),
            "themes": int(events["theme"].nunique()),
            "dates": int(events["date"].nunique()),
            "sequence_rows": int(len(seq)),
        },
        "download": download_diag,
        "taxonomy_candidates": taxonomy_candidates,
        "primary_actionable": {},
        "actionable_sequence_absolute": {},
        "ex_post_order_diagnostic": {},
        "sector_background": {},
    }

    strategy_masks = {
        "PRELEAD_ANY": lambda x: x["stock_prelead"],
        "PRELEAD_1_5": lambda x: x["prelead_bucket"] == "PRELEAD_1_5",
        "PRELEAD_6_10": lambda x: x["prelead_bucket"] == "PRELEAD_6_10",
        "PRELEAD_11_20": lambda x: x["prelead_bucket"] == "PRELEAD_11_20",
        "CROSS_AT_THEME": lambda x: x["prelead_bucket"] == "CROSS_AT_THEME",
        "NO_PRELEAD": lambda x: x["prelead_bucket"] == "NO_PRELEAD",
    }
    contexts = {
        "ALL": lambda x: pd.Series(True, index=x.index),
        "INDUSTRY_GE80": lambda x: x["industry_ge80_event"],
        "INDUSTRY_LT80": lambda x: ~x["industry_ge80_event"],
    }
    for context_name, context_fn in contexts.items():
        part = rows[context_fn(rows).fillna(False)].copy()
        result["primary_actionable"][context_name] = {}
        for h in HORIZONS:
            result["primary_actionable"][context_name][str(h)] = {}
            for name, fn in strategy_masks.items():
                tab = event_selection_table(part, fn(part), h)
                result["primary_actionable"][context_name][str(h)][name] = summarize_lift(tab, 10000 + h + len(name) + len(context_name))

    actionable_categories = sorted(str(x) for x in rows["actionable_sequence"].dropna().unique())
    for h in HORIZONS:
        result["actionable_sequence_absolute"][str(h)] = {}
        for i, category in enumerate(actionable_categories):
            part = rows[rows["actionable_sequence"] == category]
            result["actionable_sequence_absolute"][str(h)][category] = summarize_group_absolute(part, h, 20000 + h * 100 + i)

    ex_post_categories = sorted(str(x) for x in rows["ex_post_order"].dropna().unique())
    for h in HORIZONS:
        result["ex_post_order_diagnostic"][str(h)] = {}
        for i, category in enumerate(ex_post_categories):
            part = rows[rows["ex_post_order"] == category]
            result["ex_post_order_diagnostic"][str(h)][category] = summarize_group_absolute(part, h, 30000 + h * 100 + i)

    for sector_label, sector_mask in {
        "SECTOR_GE80": rows["sector_ge80_event"],
        "SECTOR_LT80": ~rows["sector_ge80_event"],
    }.items():
        part = rows[sector_mask.fillna(False)].copy()
        result["sector_background"][sector_label] = {}
        for h in HORIZONS:
            tab = event_selection_table(part, part["stock_prelead"], h)
            result["sector_background"][sector_label][str(h)] = summarize_lift(tab, 40000 + h + len(sector_label))

    safe_result = safe(result)
    rows.to_csv(output / "lead_lag_event_stock_rows.csv.gz", index=False, compression="gzip")
    (output / "summary.json").write_text(json.dumps(safe_result, ensure_ascii=False, indent=2), encoding="utf-8")

    compact = {
        "status": safe_result["status"],
        "coverage": safe_result["coverage"],
        "primary_actionable": safe_result["primary_actionable"],
        "actionable_sequence_absolute": safe_result["actionable_sequence_absolute"],
        "ex_post_order_diagnostic": safe_result["ex_post_order_diagnostic"],
        "sector_background": safe_result["sector_background"],
    }
    print("=== LEAD_LAG_RESULT_JSON ===", flush=True)
    print(json.dumps(compact, ensure_ascii=False, indent=2), flush=True)
    print("=== END_LEAD_LAG_RESULT_JSON ===", flush=True)


if __name__ == "__main__":
    main()
