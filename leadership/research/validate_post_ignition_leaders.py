from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import validate_early_rotation as er
import validate_confirmed_leadership as cl
import validate_rrg_tail_system as rt
import validate_rrg_tail_system_v2 as rtv2

DISCOVERY_END = pd.Timestamp("2021-12-31")
CONFIRM_START = pd.Timestamp("2022-01-01")
SIGNAL_DAYS = (2, 3, 5)
HORIZONS = (10, 20, 40, 63)
TOP_N = 3
TOP_THIRD = 2.0 / 3.0
MIN_PRICE = 5.0
MIN_DOLLAR_VOLUME20 = 5_000_000.0


def safe(v: Any) -> Any:
    if isinstance(v, dict):
        return {str(k): safe(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [safe(x) for x in v]
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, (np.floating, float)):
        x = float(v)
        return x if math.isfinite(x) else None
    if isinstance(v, pd.Timestamp):
        return v.isoformat()
    return v


def buy_hold_returns_from_open(open_: pd.DataFrame, close: pd.DataFrame, symbols: list[str], entry_pos: int, end_pos: int) -> pd.Series:
    if entry_pos < 0 or end_pos < entry_pos or end_pos >= len(close.index):
        return pd.Series(dtype=float)
    d0 = close.index[entry_pos]
    d1 = close.index[end_pos]
    cols = [s for s in symbols if s in close.columns and s in open_.columns]
    if not cols:
        return pd.Series(dtype=float)
    e = pd.to_numeric(open_.loc[d0, cols], errors="coerce")
    z = pd.to_numeric(close.loc[d1, cols], errors="coerce")
    return (z / e - 1.0).replace([np.inf, -np.inf], np.nan).dropna()


def spy_return_from_open(open_all: pd.DataFrame, close_all: pd.DataFrame, entry_pos: int, end_pos: int) -> float:
    if entry_pos < 0 or end_pos < entry_pos or end_pos >= len(close_all.index):
        return np.nan
    d0 = close_all.index[entry_pos]
    d1 = close_all.index[end_pos]
    if "SPY" not in open_all.columns or "SPY" not in close_all.columns:
        return np.nan
    e = open_all.at[d0, "SPY"]
    z = close_all.at[d1, "SPY"]
    if pd.isna(e) or pd.isna(z) or float(e) <= 0:
        return np.nan
    return float(z / e - 1.0)


def relative_snapshot(close: pd.DataFrame, pool: list[str], event_pos: int, signal_pos: int) -> pd.DataFrame:
    if signal_pos <= event_pos or signal_pos >= len(close.index):
        return pd.DataFrame(columns=["symbol", "stock_ret", "peer_ret", "relative", "rank"])
    start_d = close.index[event_pos]
    signal_d = close.index[signal_pos]
    cols = [s for s in pool if s in close.columns]
    if len(cols) < 3:
        return pd.DataFrame(columns=["symbol", "stock_ret", "peer_ret", "relative", "rank"])
    start = pd.to_numeric(close.loc[start_d, cols], errors="coerce")
    end = pd.to_numeric(close.loc[signal_d, cols], errors="coerce")
    indiv = (end / start - 1.0).replace([np.inf, -np.inf], np.nan)
    rows: list[dict[str, Any]] = []
    for sym in cols:
        sr = indiv.get(sym, np.nan)
        peers = indiv.drop(labels=[sym], errors="ignore").dropna()
        if pd.isna(sr) or len(peers) < 2:
            continue
        pr = float(peers.mean())
        rows.append({"symbol": sym, "stock_ret": float(sr), "peer_ret": pr, "relative": float(sr - pr)})
    out = pd.DataFrame(rows)
    if out.empty:
        return pd.DataFrame(columns=["symbol", "stock_ret", "peer_ret", "relative", "rank"])
    out["rank"] = out["relative"].rank(pct=True, method="average")
    return out.sort_values(["relative", "symbol"], ascending=[False, True]).reset_index(drop=True)


def event_pool(date: pd.Timestamp, theme: str, theme_members: dict[str, list[str]], close: pd.DataFrame, dollar_volume20: pd.DataFrame, ema21: pd.DataFrame, sma50: pd.DataFrame) -> list[str]:
    if date not in close.index:
        return []
    members = [s for s in theme_members.get(theme, []) if s in close.columns and s in dollar_volume20.columns]
    if len(members) < 3:
        return []
    out: list[str] = []
    for sym in members:
        c = close.at[date, sym]
        e = ema21.at[date, sym]
        sm = sma50.at[date, sym]
        dv = dollar_volume20.at[date, sym]
        if any(pd.isna(x) for x in (c, e, sm, dv)):
            continue
        if float(c) < MIN_PRICE or float(dv) < MIN_DOLLAR_VOLUME20:
            continue
        if not (float(c) > float(e) and float(c) > float(sm)):
            continue
        out.append(sym)
    return out


def day0_rs63_top3(close: pd.DataFrame, pool: list[str], event_pos: int) -> list[str]:
    if event_pos < 63:
        return []
    d0 = close.index[event_pos - 63]
    d1 = close.index[event_pos]
    start = pd.to_numeric(close.loc[d0, pool], errors="coerce")
    end = pd.to_numeric(close.loc[d1, pool], errors="coerce")
    vals = (end / start - 1.0).replace([np.inf, -np.inf], np.nan).dropna()
    if len(vals) < 3:
        return []
    return list(vals.sort_values(ascending=False).head(TOP_N).index)


def select_wait_day(close: pd.DataFrame, pool: list[str], event_pos: int, day: int) -> tuple[int | None, list[str]]:
    signal_pos = event_pos + day
    snap = relative_snapshot(close, pool, event_pos, signal_pos)
    if snap.empty:
        return None, []
    chosen = snap[snap["relative"] > 0].head(TOP_N)
    return signal_pos, list(chosen["symbol"])


def select_confirm2(close: pd.DataFrame, pool: list[str], event_pos: int) -> tuple[int | None, list[str]]:
    previous: pd.DataFrame | None = None
    for day in range(1, 6):
        signal_pos = event_pos + day
        snap = relative_snapshot(close, pool, event_pos, signal_pos)
        if snap.empty:
            previous = snap
            continue
        if day >= 2 and previous is not None and not previous.empty:
            prev = previous.set_index("symbol")
            cur = snap.set_index("symbol")
            common = cur.index.intersection(prev.index)
            confirmed: list[str] = []
            for sym in common:
                if float(prev.at[sym, "relative"]) > 0 and float(cur.at[sym, "relative"]) > 0 and float(prev.at[sym, "rank"]) >= TOP_THIRD and float(cur.at[sym, "rank"]) >= TOP_THIRD:
                    confirmed.append(sym)
            if confirmed:
                ranked = cur.loc[confirmed].sort_values("relative", ascending=False)
                return signal_pos, list(ranked.head(TOP_N).index)
        previous = snap
    return None, []


def future_rank_metrics(open_: pd.DataFrame, close: pd.DataFrame, pool: list[str], selected: list[str], entry_pos: int, end_pos: int) -> tuple[float, float]:
    all_ret = buy_hold_returns_from_open(open_, close, pool, entry_pos, end_pos)
    if len(all_ret) < 3 or not selected:
        return np.nan, np.nan
    ranks = all_ret.rank(pct=True, method="average")
    picked = [s for s in selected if s in ranks.index]
    if not picked:
        return np.nan, np.nan
    top_third_hit = float((ranks.loc[picked] >= TOP_THIRD).mean())
    winner = str(all_ret.idxmax()) if len(all_ret) else ""
    return top_third_hit, float(winner in picked)


def evaluate_method(method: str, event: Any, pool: list[str], selected: list[str], signal_pos: int | None, event_pos: int, close: pd.DataFrame, open_: pd.DataFrame, high: pd.DataFrame, low: pd.DataFrame, close_all: pd.DataFrame, open_all: pd.DataFrame) -> dict[str, Any]:
    date = pd.Timestamp(event.date)
    theme = str(event.theme)
    rec: dict[str, Any] = {
        "date": date,
        "theme": theme,
        "strength": float(event.theme_rs_pct) if hasattr(event, "theme_rs_pct") and pd.notna(event.theme_rs_pct) else np.nan,
        "method": method,
        "event_pos": int(event_pos),
        "signal_pos": int(signal_pos) if signal_pos is not None else None,
        "signal_day": int(signal_pos - event_pos) if signal_pos is not None else None,
        "selected_count": int(len(selected)),
        "selected_symbols": ",".join(selected),
        "pool_count": int(len(pool)),
        "trade": bool(signal_pos is not None and len(selected) > 0),
    }
    entry_pos = signal_pos + 1 if signal_pos is not None else None
    rec["entry_date"] = close.index[entry_pos] if entry_pos is not None and entry_pos < len(close.index) else pd.NaT
    day0_entry_pos = event_pos + 1

    for h in HORIZONS:
        terminal_pos = event_pos + h
        event_theme = buy_hold_returns_from_open(open_, close, pool, day0_entry_pos, terminal_pos)
        event_theme_ret = float(event_theme.mean()) if len(event_theme) >= 3 else np.nan
        event_spy_ret = spy_return_from_open(open_all, close_all, day0_entry_pos, terminal_pos)
        if entry_pos is None or entry_pos >= len(close.index) or terminal_pos >= len(close.index) or entry_pos > terminal_pos or not selected:
            strategy_terminal = 0.0
        else:
            sr = buy_hold_returns_from_open(open_, close, selected, entry_pos, terminal_pos)
            strategy_terminal = float(sr.mean()) if len(sr) == len(selected) and len(sr) else np.nan
        rec[f"event_terminal_ret_{h}"] = strategy_terminal
        rec[f"event_terminal_vs_day0_theme_{h}"] = strategy_terminal - event_theme_ret if pd.notna(strategy_terminal) and pd.notna(event_theme_ret) else np.nan
        rec[f"event_terminal_vs_spy_{h}"] = strategy_terminal - event_spy_ret if pd.notna(strategy_terminal) and pd.notna(event_spy_ret) else np.nan

        if entry_pos is None or entry_pos >= len(close.index) or not selected:
            for key in ("entry_forward_ret", "entry_forward_vs_theme", "entry_forward_vs_spy", "top_third_hit", "winner_capture", "mfe", "mae"):
                rec[f"{key}_{h}"] = np.nan
            continue
        forward_end = entry_pos + h - 1
        if forward_end >= len(close.index):
            for key in ("entry_forward_ret", "entry_forward_vs_theme", "entry_forward_vs_spy", "top_third_hit", "winner_capture", "mfe", "mae"):
                rec[f"{key}_{h}"] = np.nan
            continue

        selected_ret = buy_hold_returns_from_open(open_, close, selected, entry_pos, forward_end)
        theme_ret = buy_hold_returns_from_open(open_, close, pool, entry_pos, forward_end)
        spy_ret = spy_return_from_open(open_all, close_all, entry_pos, forward_end)
        sr_mean = float(selected_ret.mean()) if len(selected_ret) == len(selected) and len(selected_ret) else np.nan
        tr_mean = float(theme_ret.mean()) if len(theme_ret) >= 3 else np.nan
        rec[f"entry_forward_ret_{h}"] = sr_mean
        rec[f"entry_forward_vs_theme_{h}"] = sr_mean - tr_mean if pd.notna(sr_mean) and pd.notna(tr_mean) else np.nan
        rec[f"entry_forward_vs_spy_{h}"] = sr_mean - spy_ret if pd.notna(sr_mean) and pd.notna(spy_ret) else np.nan
        hit, cap = future_rank_metrics(open_, close, pool, selected, entry_pos, forward_end)
        rec[f"top_third_hit_{h}"] = hit
        rec[f"winner_capture_{h}"] = cap

        entry_d = close.index[entry_pos]
        future_dates = close.index[entry_pos:forward_end + 1]
        mfes: list[float] = []
        maes: list[float] = []
        for sym in selected:
            ep = open_.at[entry_d, sym]
            if pd.isna(ep) or float(ep) <= 0:
                continue
            hs = pd.to_numeric(high.loc[future_dates, sym], errors="coerce").dropna()
            ls = pd.to_numeric(low.loc[future_dates, sym], errors="coerce").dropna()
            if len(hs):
                mfes.append(float(hs.max() / float(ep) - 1.0))
            if len(ls):
                maes.append(float(ls.min() / float(ep) - 1.0))
        rec[f"mfe_{h}"] = float(np.mean(mfes)) if mfes else np.nan
        rec[f"mae_{h}"] = float(np.mean(maes)) if maes else np.nan
    return rec


def summarize_method(rows: pd.DataFrame, family_map: dict[str, str], theme_sets: dict[str, set[str]], calendar: pd.DatetimeIndex, seed: int) -> dict[str, Any]:
    result: dict[str, Any] = {
        "events": int(len(rows)),
        "dates": int(rows.date.nunique()) if len(rows) else 0,
        "themes": int(rows.theme.nunique()) if len(rows) else 0,
        "trade_rate": float(rows["trade"].mean()) if len(rows) else None,
        "mean_signal_day": float(rows.loc[rows.trade, "signal_day"].mean()) if len(rows) and rows["trade"].any() else None,
        "mean_selected_count": float(rows.loc[rows.trade, "selected_count"].mean()) if len(rows) and rows["trade"].any() else None,
        "horizons": {},
    }
    metrics_template = (
        "event_terminal_ret_{h}", "event_terminal_vs_day0_theme_{h}", "event_terminal_vs_spy_{h}",
        "entry_forward_ret_{h}", "entry_forward_vs_theme_{h}", "entry_forward_vs_spy_{h}",
        "top_third_hit_{h}", "winner_capture_{h}", "mfe_{h}", "mae_{h}",
    )
    for h in HORIZONS:
        result["horizons"][str(h)] = {}
        for mi, template in enumerate(metrics_template):
            metric = template.format(h=h)
            modes = rt.aggregate_modes(rows, metric, family_map, theme_sets)
            result["horizons"][str(h)][metric] = {
                mode: rt.summary(frame, metric, calendar, seed + h * 1000 + mi * 100 + j)
                for j, (mode, frame) in enumerate(modes.items())
            }
    return result


def paired_advantage(all_rows: pd.DataFrame, method: str, baseline: str, metric: str, family_map: dict[str, str], theme_sets: dict[str, set[str]], calendar: pd.DatetimeIndex, seed: int) -> dict[str, Any]:
    a = all_rows[all_rows.method == method][["date", "theme", "strength", metric]].rename(columns={metric: "a"})
    b = all_rows[all_rows.method == baseline][["date", "theme", metric]].rename(columns={metric: "b"})
    m = a.merge(b, on=["date", "theme"], how="inner")
    m[metric] = m["a"] - m["b"]
    modes = rt.aggregate_modes(m, metric, family_map, theme_sets)
    return {mode: rt.summary(frame, metric, calendar, seed + i) for i, (mode, frame) in enumerate(modes.items())}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--output", required=True)
    ap.add_argument("--analysis-start", default="2016-01-04")
    ap.add_argument("--analysis-end", default="2026-06-30")
    ap.add_argument("--max-tickers", type=int, default=6000)
    ap.add_argument("--batch-size", type=int, default=75)
    ap.add_argument("--min-members", type=int, default=3)
    args = ap.parse_args()

    root = Path(args.root)
    out = root / args.output
    out.mkdir(parents=True, exist_ok=True)
    snap = er.load_json(root / "sector_snapshot.json")
    theme_members_all, taxonomy_diag = er.extract_theme_members(snap)
    industry_map = er.read_industry_map(root / "industry_map.json")
    universe = er.read_universe_symbols(root / "universe.csv")
    selected = er.stratified_symbols(theme_members_all, set(industry_map) & universe, args.max_tickers)
    requested = selected + (["SPY"] if "SPY" not in selected else [])
    download_start = str((pd.Timestamp(args.analysis_start) - pd.Timedelta(days=620)).date())
    download_end = str((pd.Timestamp(args.analysis_end) + pd.Timedelta(days=140)).date())
    ohlcv, download_diag = rtv2.download_ohlcvo(requested, download_start, download_end, args.batch_size)

    close_all = ohlcv["close"]
    open_all = ohlcv["open"]
    if "SPY" not in close_all.columns or "SPY" not in open_all.columns:
        raise RuntimeError("SPY missing from OHLCV download")
    stock_cols = [s for s in selected if s in close_all.columns]
    close = close_all[stock_cols]
    open_ = open_all[stock_cols]
    high = ohlcv["high"][stock_cols]
    low = ohlcv["low"][stock_cols]
    volume = ohlcv["volume"][stock_cols]
    stock_ret = close.pct_change(fill_method=None)
    spy_ret = close_all["SPY"].pct_change(fill_method=None)

    theme_members = {t: [s for s in members if s in stock_cols] for t, members in theme_members_all.items()}
    member_counts = {t: len(members) for t, members in theme_members.items()}
    theme_ret = er.grouped_equal_weight(stock_ret, theme_members, args.min_members)
    spy63 = er.period_return(spy_ret, 63)
    theme63 = er.period_return(theme_ret, 63)
    theme_pct = theme63.sub(spy63, axis=0).rank(axis=1, pct=True, method="average") * 100.0
    breadth = er.breadth_above_ema21(close, theme_members, args.min_members).reindex(columns=theme_ret.columns)

    industry_groups: dict[str, list[str]] = defaultdict(list)
    for sym in stock_cols:
        if sym in industry_map and industry_map[sym][1]:
            industry_groups[industry_map[sym][1]].append(sym)
    industry_ret = er.grouped_equal_weight(stock_ret, dict(industry_groups), args.min_members)
    industry_weights = er.build_parent_weights(theme_members_all, industry_map)
    industry63 = er.period_return(industry_ret, 63)
    industry_pct = industry63.sub(spy63, axis=0).rank(axis=1, pct=True, method="average") * 100.0
    parent = er.weighted_matrix(industry_pct, industry_weights, list(theme_ret.columns)).reindex(columns=theme_ret.columns)

    start, end = pd.Timestamp(args.analysis_start), pd.Timestamp(args.analysis_end)
    momentum_mask = cl.momentum_mask(theme_pct, parent, breadth)
    events = er.extract_events(momentum_mask, theme_pct, parent, breadth, member_counts, start, end)
    events = events.sort_values(["date", "theme"]).reset_index(drop=True)

    ema21 = close.ewm(span=21, adjust=False, min_periods=15).mean()
    sma50 = close.rolling(50, min_periods=40).mean()
    dollar_volume20 = (close * volume).rolling(20, min_periods=15).mean()
    date_pos = {pd.Timestamp(d): i for i, d in enumerate(close.index)}
    family_map = rt.primary_family(theme_members, industry_map)
    theme_sets = {t: set(members) for t, members in theme_members.items()}

    methods = ["DAY0_ALL_EQ", "DAY0_RS63_TOP3"] + [f"DAY{d}_REL_TOP3" for d in SIGNAL_DAYS] + ["CONFIRM2_EARLY"]
    records: list[dict[str, Any]] = []
    pool_events = 0
    for i, event in enumerate(events.itertuples(index=False)):
        date = pd.Timestamp(event.date)
        theme = str(event.theme)
        p = date_pos.get(date, -1)
        if p < 70 or p + max(HORIZONS) + 8 >= len(close.index):
            continue
        pool = event_pool(date, theme, theme_members, close, dollar_volume20, ema21, sma50)
        if len(pool) < 3:
            continue
        pool_events += 1
        selections: dict[str, tuple[int | None, list[str]]] = {
            "DAY0_ALL_EQ": (p, list(pool)),
            "DAY0_RS63_TOP3": (p, day0_rs63_top3(close, pool, p)),
        }
        for d in SIGNAL_DAYS:
            selections[f"DAY{d}_REL_TOP3"] = select_wait_day(close, pool, p, d)
        selections["CONFIRM2_EARLY"] = select_confirm2(close, pool, p)
        for method in methods:
            signal_pos, chosen = selections.get(method, (None, []))
            if signal_pos is not None and not chosen:
                signal_pos = None
            records.append(evaluate_method(method, event, pool, chosen, signal_pos, p, close, open_, high, low, close_all, open_all))
        if (i + 1) % 500 == 0:
            print(f"POST_IGNITION_EVENTS {i + 1}/{len(events)} retained={pool_events} rows={len(records)}", flush=True)

    rows = pd.DataFrame(records)
    if rows.empty:
        raise RuntimeError("No post-ignition rows produced")
    rows.to_csv(out / "post_ignition_event_rows.csv.gz", index=False, compression="gzip")

    result: dict[str, Any] = {
        "status": "PRELIMINARY_CURRENT_TAXONOMY_POST_IGNITION_LEADER_SELECTION",
        "bias_warning": "Current universe and current taxonomy are retrospectively applied; treat as hypothesis validation, not survivorship-free proof.",
        "question": "After validated Theme Momentum ignition, does waiting for realized within-theme leadership improve stock selection enough to offset the missed early move?",
        "frozen_design": {
            "theme_event": cl.MOMENTUM_CONFIG,
            "theme_eventization": "new Theme Momentum entry with existing 20-session Theme cooldown",
            "candidate_pool_frozen_at_day0": True,
            "candidate_filters": {"price_min": MIN_PRICE, "dollar_volume20_min": MIN_DOLLAR_VOLUME20, "close_above_ema21": True, "close_above_sma50": True, "rs_filter": False, "breakout_filter": False, "pre_ignition_filter": False},
            "relative_signal": "cumulative stock return since Theme event close minus mean cumulative return of the other eligible Theme members; rank is within the frozen Day0 pool",
            "methods": {
                "DAY0_ALL_EQ": "all eligible Theme members, signal Day0 close -> next open",
                "DAY0_RS63_TOP3": "top 3 by trailing 63-session return inside the Day0 pool, signal Day0 close -> next open",
                "DAY2_REL_TOP3": "top 3 positive post-event Theme-relative performers at Day2 close -> next open",
                "DAY3_REL_TOP3": "same at Day3 close",
                "DAY5_REL_TOP3": "same at Day5 close",
                "CONFIRM2_EARLY": "earliest Day2-5 with positive Theme-relative performance and top-third rank on two consecutive closes; choose up to top 3 -> next open"
            },
            "economic_test": "cash before actual entry; compare actual-entry strategy return to a Day0 equal-weight Theme basket and SPY at the same event-terminal date",
            "selection_test": "from actual entry, compare selected basket to same-day Theme basket and SPY over 10/20/40/63 sessions",
            "robustness": ["EVENT_WEIGHTED", "DATE_EQUAL", "FAMILY_DATE_EQUAL", "OVERLAP_DEDUP_DATE_EQUAL"]
        },
        "download": download_diag,
        "taxonomy_candidates": taxonomy_diag,
        "coverage": {"stocks": len(stock_cols), "themes": int(events.theme.nunique()) if len(events) else 0, "theme_events": int(len(events)), "eligible_pool_events": int(pool_events), "event_rows": int(len(rows))},
        "methods": {},
        "confirmation_2022_plus": {},
        "paired_vs_day0_rs63_top3": {},
        "paired_vs_day0_all_eq": {}
    }

    calendar = close.index
    for mi, method in enumerate(methods):
        part = rows[rows.method == method].copy()
        conf = part[part.date >= CONFIRM_START].copy()
        result["methods"][method] = summarize_method(part, family_map, theme_sets, calendar, 100000 + mi * 10000)
        result["confirmation_2022_plus"][method] = summarize_method(conf, family_map, theme_sets, calendar, 200000 + mi * 10000)

    for mi, method in enumerate(methods):
        if method == "DAY0_RS63_TOP3":
            continue
        result["paired_vs_day0_rs63_top3"][method] = {}
        for h in HORIZONS:
            for k, metric in enumerate((f"event_terminal_ret_{h}", f"entry_forward_vs_theme_{h}", f"entry_forward_vs_spy_{h}")):
                result["paired_vs_day0_rs63_top3"][method][metric] = paired_advantage(rows, method, "DAY0_RS63_TOP3", metric, family_map, theme_sets, calendar, 300000 + mi * 10000 + h * 100 + k * 10)

    for mi, method in enumerate(methods):
        if method == "DAY0_ALL_EQ":
            continue
        result["paired_vs_day0_all_eq"][method] = {}
        for h in HORIZONS:
            metric = f"event_terminal_ret_{h}"
            result["paired_vs_day0_all_eq"][method][metric] = paired_advantage(rows, method, "DAY0_ALL_EQ", metric, family_map, theme_sets, calendar, 400000 + mi * 10000 + h * 100)

    safe_result = safe(result)
    (out / "summary.json").write_text(json.dumps(safe_result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("===POST_IGNITION_LEADER_RESULT===")
    print(json.dumps(safe_result, ensure_ascii=False, separators=(",", ":")))
    print("===END===", flush=True)


if __name__ == "__main__":
    main()
