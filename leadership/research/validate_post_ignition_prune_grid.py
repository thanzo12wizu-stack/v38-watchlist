from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import validate_post_ignition_leaders as base

HORIZONS = (10, 20, 40, 63)
WAIT_DAYS = (1, 2, 3, 5)
PRUNE_DAYS = (1, 2, 3, 5)


def safe(v: Any) -> Any:
    return base.safe(v)


def stock_return(open_: pd.DataFrame, close: pd.DataFrame, sym: str, entry_pos: int, terminal_pos: int) -> float:
    if entry_pos < 0 or terminal_pos < entry_pos or terminal_pos >= len(close.index):
        return np.nan
    e = open_.at[close.index[entry_pos], sym]
    z = close.at[close.index[terminal_pos], sym]
    if pd.isna(e) or pd.isna(z) or float(e) <= 0:
        return np.nan
    return float(z / e - 1.0)


def stock_return_to_open(open_: pd.DataFrame, close: pd.DataFrame, sym: str, entry_pos: int, exit_pos: int) -> float:
    if entry_pos < 0 or exit_pos < entry_pos or exit_pos >= len(close.index):
        return np.nan
    e = open_.at[close.index[entry_pos], sym]
    x = open_.at[close.index[exit_pos], sym]
    if pd.isna(e) or pd.isna(x) or float(e) <= 0:
        return np.nan
    return float(x / e - 1.0)


def portfolio_hold(open_: pd.DataFrame, close: pd.DataFrame, chosen: list[str], entry_pos: int, terminal_pos: int) -> float:
    vals = [stock_return(open_, close, s, entry_pos, terminal_pos) for s in chosen]
    vals = [v for v in vals if pd.notna(v)]
    return float(np.mean(vals)) if len(vals) == len(chosen) and vals else np.nan


def wait_selection(close: pd.DataFrame, pool: list[str], event_pos: int, day: int, topn: int) -> tuple[int | None, list[str]]:
    sig = event_pos + day
    snap = base.relative_snapshot(close, pool, event_pos, sig)
    if snap.empty:
        return None, []
    chosen = list(snap.loc[snap["relative"] > 0, "symbol"].head(topn))
    return (sig, chosen) if chosen else (None, [])


def relative_map(close: pd.DataFrame, pool: list[str], event_pos: int, day: int) -> dict[str, float]:
    snap = base.relative_snapshot(close, pool, event_pos, event_pos + day)
    if snap.empty:
        return {}
    return dict(zip(snap["symbol"].astype(str), snap["relative"].astype(float)))


def prune_return(
    open_: pd.DataFrame,
    close: pd.DataFrame,
    initial: list[str],
    rel: dict[str, float],
    event_pos: int,
    prune_day: int,
    terminal_pos: int,
) -> tuple[float, int]:
    entry_pos = event_pos + 1
    exit_pos = event_pos + prune_day + 1
    vals: list[float] = []
    survivors = 0
    for s in initial:
        rv = rel.get(s, np.nan)
        if pd.notna(rv) and float(rv) > 0:
            r = stock_return(open_, close, s, entry_pos, terminal_pos)
            survivors += 1
        else:
            if exit_pos <= terminal_pos:
                r = stock_return_to_open(open_, close, s, entry_pos, exit_pos)
            else:
                r = stock_return(open_, close, s, entry_pos, terminal_pos)
        if pd.isna(r):
            return np.nan, survivors
        vals.append(float(r))
    return (float(np.mean(vals)) if vals else np.nan), survivors


def prune_two_negative_return(
    open_: pd.DataFrame,
    close: pd.DataFrame,
    initial: list[str],
    rel_by_day: dict[int, dict[str, float]],
    event_pos: int,
    terminal_pos: int,
) -> tuple[float, int, float]:
    entry_pos = event_pos + 1
    vals: list[float] = []
    survivors = 0
    exit_days: list[int] = []
    for s in initial:
        exit_day: int | None = None
        for d in range(2, 6):
            a = rel_by_day.get(d - 1, {}).get(s, np.nan)
            b = rel_by_day.get(d, {}).get(s, np.nan)
            if pd.notna(a) and pd.notna(b) and float(a) <= 0 and float(b) <= 0:
                exit_day = d
                break
        if exit_day is None:
            r = stock_return(open_, close, s, entry_pos, terminal_pos)
            survivors += 1
        else:
            xp = event_pos + exit_day + 1
            if xp <= terminal_pos:
                r = stock_return_to_open(open_, close, s, entry_pos, xp)
                exit_days.append(exit_day)
            else:
                r = stock_return(open_, close, s, entry_pos, terminal_pos)
        if pd.isna(r):
            return np.nan, survivors, np.nan
        vals.append(float(r))
    return (float(np.mean(vals)) if vals else np.nan), survivors, (float(np.mean(exit_days)) if exit_days else np.nan)


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
    snap = base.er.load_json(root / "sector_snapshot.json")
    theme_members_all, taxonomy_diag = base.er.extract_theme_members(snap)
    industry_map = base.er.read_industry_map(root / "industry_map.json")
    universe = base.er.read_universe_symbols(root / "universe.csv")
    selected = base.er.stratified_symbols(theme_members_all, set(industry_map) & universe, args.max_tickers)
    requested = selected + (["SPY"] if "SPY" not in selected else [])
    download_start = str((pd.Timestamp(args.analysis_start) - pd.Timedelta(days=620)).date())
    download_end = str((pd.Timestamp(args.analysis_end) + pd.Timedelta(days=140)).date())
    ohlcv, download_diag = base.rtv2.download_ohlcvo(requested, download_start, download_end, args.batch_size)

    close_all, open_all = ohlcv["close"], ohlcv["open"]
    stock_cols = [s for s in selected if s in close_all.columns]
    close, open_, volume = close_all[stock_cols], open_all[stock_cols], ohlcv["volume"][stock_cols]
    stock_ret = close.pct_change(fill_method=None)
    spy_ret = close_all["SPY"].pct_change(fill_method=None)
    theme_members = {t: [s for s in members if s in stock_cols] for t, members in theme_members_all.items()}
    member_counts = {t: len(members) for t, members in theme_members.items()}
    theme_ret = base.er.grouped_equal_weight(stock_ret, theme_members, args.min_members)
    spy63 = base.er.period_return(spy_ret, 63)
    theme63 = base.er.period_return(theme_ret, 63)
    theme_pct = theme63.sub(spy63, axis=0).rank(axis=1, pct=True, method="average") * 100.0
    breadth = base.er.breadth_above_ema21(close, theme_members, args.min_members).reindex(columns=theme_ret.columns)

    industry_groups: dict[str, list[str]] = defaultdict(list)
    for sym in stock_cols:
        if sym in industry_map and industry_map[sym][1]:
            industry_groups[industry_map[sym][1]].append(sym)
    industry_ret = base.er.grouped_equal_weight(stock_ret, dict(industry_groups), args.min_members)
    weights = base.er.build_parent_weights(theme_members_all, industry_map)
    industry63 = base.er.period_return(industry_ret, 63)
    industry_pct = industry63.sub(spy63, axis=0).rank(axis=1, pct=True, method="average") * 100.0
    parent = base.er.weighted_matrix(industry_pct, weights, list(theme_ret.columns)).reindex(columns=theme_ret.columns)

    start, end = pd.Timestamp(args.analysis_start), pd.Timestamp(args.analysis_end)
    mask = base.cl.momentum_mask(theme_pct, parent, breadth)
    events = base.er.extract_events(mask, theme_pct, parent, breadth, member_counts, start, end).sort_values(["date", "theme"]).reset_index(drop=True)
    ema21 = close.ewm(span=21, adjust=False, min_periods=15).mean()
    sma50 = close.rolling(50, min_periods=40).mean()
    dollar_volume20 = (close * volume).rolling(20, min_periods=15).mean()
    date_pos = {pd.Timestamp(d): i for i, d in enumerate(close.index)}

    methods = ["BASE_RS3"]
    methods += [f"WAIT_D{d}_TOP{n}" for d in WAIT_DAYS for n in (1, 2, 3)]
    methods += [f"PRUNE_D{d}_NEG" for d in PRUNE_DAYS]
    methods += ["PRUNE_2NEG_CONSEC"]
    rows: list[dict[str, Any]] = []
    retained = 0

    for i, ev in enumerate(events.itertuples(index=False)):
        d, theme = pd.Timestamp(ev.date), str(ev.theme)
        p = date_pos.get(d, -1)
        if p < 70 or p + max(HORIZONS) + 8 >= len(close):
            continue
        pool = base.event_pool(d, theme, theme_members, close, dollar_volume20, ema21, sma50)
        if len(pool) < 3:
            continue
        initial = base.day0_rs63_top3(close, pool, p)
        if len(initial) != 3:
            continue
        retained += 1
        rel_by_day = {day: relative_map(close, pool, p, day) for day in range(1, 6)}
        waits = {(day, n): wait_selection(close, pool, p, day, n) for day in WAIT_DAYS for n in (1, 2, 3)}

        for h in HORIZONS:
            terminal = p + h
            base_ret = portfolio_hold(open_, close, initial, p + 1, terminal)
            theme_vals = base.buy_hold_returns_from_open(open_, close, pool, p + 1, terminal)
            theme_ret_h = float(theme_vals.mean()) if len(theme_vals) >= 3 else np.nan
            spy_ret_h = base.spy_return_from_open(open_all, close_all, p + 1, terminal)
            base_rec = {
                "date": d, "theme": theme, "event_pos": p, "horizon": h,
                "method": "BASE_RS3", "ret": base_ret,
                "vs_theme": base_ret - theme_ret_h if pd.notna(base_ret) and pd.notna(theme_ret_h) else np.nan,
                "vs_spy": base_ret - spy_ret_h if pd.notna(base_ret) and pd.notna(spy_ret_h) else np.nan,
                "signal_day": 0, "selected_count": 3, "survivors": 3,
            }
            rows.append(base_rec)

            for day in WAIT_DAYS:
                for n in (1, 2, 3):
                    sig, chosen = waits[(day, n)]
                    if sig is None or not chosen or sig + 1 > terminal:
                        r = 0.0
                        cnt = 0
                    else:
                        r = portfolio_hold(open_, close, chosen, sig + 1, terminal)
                        cnt = len(chosen)
                    rows.append({
                        "date": d, "theme": theme, "event_pos": p, "horizon": h,
                        "method": f"WAIT_D{day}_TOP{n}", "ret": r,
                        "vs_theme": r - theme_ret_h if pd.notna(r) and pd.notna(theme_ret_h) else np.nan,
                        "vs_spy": r - spy_ret_h if pd.notna(r) and pd.notna(spy_ret_h) else np.nan,
                        "signal_day": day, "selected_count": cnt, "survivors": cnt,
                    })

            for day in PRUNE_DAYS:
                r, surv = prune_return(open_, close, initial, rel_by_day[day], p, day, terminal)
                rows.append({
                    "date": d, "theme": theme, "event_pos": p, "horizon": h,
                    "method": f"PRUNE_D{day}_NEG", "ret": r,
                    "vs_theme": r - theme_ret_h if pd.notna(r) and pd.notna(theme_ret_h) else np.nan,
                    "vs_spy": r - spy_ret_h if pd.notna(r) and pd.notna(spy_ret_h) else np.nan,
                    "signal_day": day, "selected_count": 3, "survivors": surv,
                })

            r, surv, exit_day = prune_two_negative_return(open_, close, initial, rel_by_day, p, terminal)
            rows.append({
                "date": d, "theme": theme, "event_pos": p, "horizon": h,
                "method": "PRUNE_2NEG_CONSEC", "ret": r,
                "vs_theme": r - theme_ret_h if pd.notna(r) and pd.notna(theme_ret_h) else np.nan,
                "vs_spy": r - spy_ret_h if pd.notna(r) and pd.notna(spy_ret_h) else np.nan,
                "signal_day": exit_day, "selected_count": 3, "survivors": surv,
            })
        if (i + 1) % 250 == 0:
            print(f"PRUNE_GRID_EVENTS {i+1}/{len(events)} retained={retained} rows={len(rows)}", flush=True)

    df = pd.DataFrame(rows)
    if df.empty:
        raise RuntimeError("No rows produced")
    df.to_csv(out / "prune_grid_rows.csv.gz", index=False, compression="gzip")
    result = {
        "status": "PRELIMINARY_CURRENT_TAXONOMY_POST_IGNITION_PRUNE_GRID",
        "bias_warning": "Current universe and current taxonomy are retrospectively applied; hypothesis validation only.",
        "download": download_diag,
        "taxonomy": taxonomy_diag,
        "coverage": {"stocks": len(stock_cols), "theme_events": int(len(events)), "retained_events": retained, "rows": int(len(df))},
        "design": {
            "baseline": "Day0 signal close -> next open buy RS63 top3, equal one-third weights, hold to terminal",
            "wait": "stay in cash until Day1/2/3/5 close, then next open buy positive Theme-relative top N",
            "prune": "buy baseline RS3 on Day0->next open; at specified day close sell only names with cumulative Theme-relative return <=0 at next open; no reallocation",
            "prune_2neg": "sell an initial RS3 name only after two consecutive closes with cumulative Theme-relative return <=0 during Days1-5; no reallocation",
            "candidate_pool": "same Day0 price/liquidity/EMA21/SMA50 eligible pool as prior validation",
        },
    }
    (out / "design.json").write_text(json.dumps(safe(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print("===PRUNE_GRID_DONE===")
    print(json.dumps(safe(result), ensure_ascii=False, separators=(",", ":")))
    print("===END===", flush=True)


if __name__ == "__main__":
    main()
