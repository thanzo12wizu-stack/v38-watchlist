from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

import validate_post_ignition_leaders as base


def stat(df: pd.DataFrame, col: str) -> dict[str, object]:
    x = df[["date", "theme", col]].dropna()
    if x.empty:
        return {"n": 0}
    s = x[col].astype(float)
    date_eq = x.groupby("date", observed=True)[col].mean()
    return {
        "n": int(len(x)),
        "dates": int(x.date.nunique()),
        "themes": int(x.theme.nunique()),
        "mean": float(s.mean()),
        "median": float(s.median()),
        "positive_rate": float((s > 0).mean()),
        "date_equal_mean": float(date_eq.mean()),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--output", required=True)
    ap.add_argument("--analysis-start", default="2022-01-03")
    ap.add_argument("--analysis-end", default="2026-06-30")
    ap.add_argument("--max-tickers", type=int, default=1500)
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
    if "SPY" not in close_all.columns:
        raise RuntimeError("SPY missing")
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
    methods = ["DAY0_ALL_EQ", "DAY0_RS63_TOP3", "DAY2_REL_TOP3", "DAY3_REL_TOP3", "DAY5_REL_TOP3", "CONFIRM2_EARLY"]
    rows: list[dict[str, object]] = []

    for i, ev in enumerate(events.itertuples(index=False)):
        d, theme = pd.Timestamp(ev.date), str(ev.theme)
        p = date_pos.get(d, -1)
        if p < 70 or p + 68 >= len(close):
            continue
        pool = base.event_pool(d, theme, theme_members, close, dollar_volume20, ema21, sma50)
        if len(pool) < 3:
            continue
        selections: dict[str, tuple[int | None, list[str]]] = {
            "DAY0_ALL_EQ": (p, list(pool)),
            "DAY0_RS63_TOP3": (p, base.day0_rs63_top3(close, pool, p)),
            "DAY2_REL_TOP3": base.select_wait_day(close, pool, p, 2),
            "DAY3_REL_TOP3": base.select_wait_day(close, pool, p, 3),
            "DAY5_REL_TOP3": base.select_wait_day(close, pool, p, 5),
            "CONFIRM2_EARLY": base.select_confirm2(close, pool, p),
        }
        theme_returns: dict[int, float] = {}
        spy_returns: dict[int, float] = {}
        for h in base.HORIZONS:
            terminal = p + h
            tr = base.buy_hold_returns_from_open(open_, close, pool, p + 1, terminal)
            theme_returns[h] = float(tr.mean()) if len(tr) >= 3 else np.nan
            spy_returns[h] = base.spy_return_from_open(open_all, close_all, p + 1, terminal)
        for method in methods:
            sig, chosen = selections[method]
            if sig is not None and not chosen:
                sig = None
            rec: dict[str, object] = {
                "date": d, "theme": theme, "method": method,
                "signal_day": int(sig - p) if sig is not None else None,
                "selected_count": len(chosen), "trade": bool(sig is not None and chosen),
            }
            entry = sig + 1 if sig is not None else None
            for h in base.HORIZONS:
                terminal = p + h
                if entry is None or entry > terminal or not chosen:
                    r = 0.0
                else:
                    z = base.buy_hold_returns_from_open(open_, close, chosen, entry, terminal)
                    r = float(z.mean()) if len(z) == len(chosen) and len(z) else np.nan
                rec[f"ret_{h}"] = r
                rec[f"vs_theme_{h}"] = r - theme_returns[h] if pd.notna(r) and pd.notna(theme_returns[h]) else np.nan
                rec[f"vs_spy_{h}"] = r - spy_returns[h] if pd.notna(r) and pd.notna(spy_returns[h]) else np.nan
            rows.append(rec)
        if (i + 1) % 250 == 0:
            print(f"ECON_EVENTS {i+1}/{len(events)} rows={len(rows)}", flush=True)

    df = pd.DataFrame(rows)
    if df.empty:
        raise RuntimeError("No rows")
    df.to_csv(out / "economic_rows.csv.gz", index=False, compression="gzip")
    result: dict[str, object] = {
        "status": "PRELIMINARY_ECONOMIC_FAST",
        "bias_warning": "Current universe/current taxonomy; directional confirmation only.",
        "download": download_diag,
        "taxonomy": taxonomy_diag,
        "coverage": {"stocks": len(stock_cols), "theme_events": int(events.shape[0]), "rows": int(df.shape[0])},
        "methods": {},
        "paired_vs_rs63": {},
        "paired_vs_all_eq": {},
    }
    for method in methods:
        part = df[df.method == method]
        item = {"trade_rate": float(part.trade.mean()), "mean_signal_day": float(part.loc[part.trade, "signal_day"].mean()) if part.trade.any() else None, "horizons": {}}
        for h in base.HORIZONS:
            item["horizons"][str(h)] = {k: stat(part, f"{k}_{h}") for k in ("ret", "vs_theme", "vs_spy")}
        result["methods"][method] = item

    for method in methods:
        if method != "DAY0_RS63_TOP3":
            a = df[df.method == method][["date", "theme"] + [f"ret_{h}" for h in base.HORIZONS]]
            b = df[df.method == "DAY0_RS63_TOP3"][["date", "theme"] + [f"ret_{h}" for h in base.HORIZONS]]
            m = a.merge(b, on=["date", "theme"], suffixes=("_a", "_b"))
            result["paired_vs_rs63"][method] = {str(h): stat(m.assign(**{f"diff_{h}": m[f"ret_{h}_a"] - m[f"ret_{h}_b"]}), f"diff_{h}") for h in base.HORIZONS}
        if method != "DAY0_ALL_EQ":
            a = df[df.method == method][["date", "theme"] + [f"ret_{h}" for h in base.HORIZONS]]
            b = df[df.method == "DAY0_ALL_EQ"][["date", "theme"] + [f"ret_{h}" for h in base.HORIZONS]]
            m = a.merge(b, on=["date", "theme"], suffixes=("_a", "_b"))
            result["paired_vs_all_eq"][method] = {str(h): stat(m.assign(**{f"diff_{h}": m[f"ret_{h}_a"] - m[f"ret_{h}_b"]}), f"diff_{h}") for h in base.HORIZONS}

    safe = base.safe(result)
    (out / "summary.json").write_text(json.dumps(safe, ensure_ascii=False, indent=2), encoding="utf-8")
    print("===ECONOMIC_FAST_RESULT===")
    print(json.dumps(safe, ensure_ascii=False, separators=(",", ":")))
    print("===END===", flush=True)


if __name__ == "__main__":
    main()
