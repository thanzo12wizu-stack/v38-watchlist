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
import validate_post_ignition_leaders as post
import validate_rsi_divergence_strong as rd
import validate_rsi_reset_reaccel as rr

H = (5, 10, 20, 40, 63)
COST = 5.0
DISC_END = pd.Timestamp("2021-12-31")
CONF_START = pd.Timestamp("2022-01-03")
METHODS = {
    "TOUCH_LE30_W20": ("touch", 30, 20),
    "RISE_LE30_W20": ("rise", 30, 20),
    "TOUCH_LE35_W20": ("touch", 35, 20),
    "TOUCH_LE40_W10": ("touch", 40, 10),
    "BAND_40_50_W10": ("bandwait", (40, 50), 10),
}

def safe(x: Any) -> Any:
    if isinstance(x, dict):
        return {str(k): safe(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [safe(v) for v in x]
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, (np.floating, float)):
        z = float(x)
        return z if math.isfinite(z) else None
    if isinstance(x, pd.Timestamp):
        return x.isoformat()
    return x

def top3(df: pd.DataFrame, col: str, name: str) -> pd.DataFrame:
    z = (
        df.dropna(subset=[col])
        .sort_values(["date", "theme", col, "symbol"], ascending=[True, True, False, True])
        .groupby(["date", "theme"], observed=True)
        .head(3)
        .copy()
    )
    z["rank_type"] = name
    return z.groupby(["date", "theme"], observed=True).filter(lambda g: len(g) == 3)

def trade_ret(op: pd.DataFrame, clz: pd.DataFrame, sym: str, entry: int, end: int) -> float:
    if entry < 0 or end < entry or end >= len(clz):
        return np.nan
    e = op.at[clz.index[entry], sym]
    z = clz.at[clz.index[end], sym]
    if pd.isna(e) or pd.isna(z) or e <= 0:
        return np.nan
    return float(z / e - 1.0 - 2 * COST / 10000.0)

def excursions(op: pd.DataFrame, hi: pd.DataFrame, lo: pd.DataFrame, sym: str, entry: int, end: int) -> tuple[float, float]:
    if entry < 0 or end < entry or end >= len(hi):
        return np.nan, np.nan
    e = op.at[hi.index[entry], sym]
    if pd.isna(e) or e <= 0:
        return np.nan, np.nan
    ix = hi.index[entry:end + 1]
    hs = hi.loc[ix, sym].dropna()
    ls = lo.loc[ix, sym].dropna()
    mfe = float(hs.max() / e - 1.0) if len(hs) else np.nan
    mae = float(ls.min() / e - 1.0) if len(ls) else np.nan
    return mfe, mae

def pf(x: pd.Series) -> float | None:
    z = pd.to_numeric(x, errors="coerce").dropna()
    if z.empty:
        return None
    pos = float(z[z > 0].sum())
    neg = float(-z[z < 0].sum())
    return None if neg == 0 else pos / neg

def block_id(dates: pd.Series, calendar: pd.DatetimeIndex, n: int = 20) -> pd.Series:
    p = pd.Series(np.arange(len(calendar)), index=calendar)
    z = p.reindex(pd.to_datetime(dates)).to_numpy(float)
    return pd.Series(np.floor(z / n).astype("int64"), index=dates.index)

def cluster_ci(df: pd.DataFrame, value: str, cluster: str, seed: int, reps: int = 2500) -> list[float | None]:
    z = df[[cluster, value]].dropna()
    if z.empty:
        return [None, None]
    a = z.groupby(cluster, observed=True)[value].mean().to_numpy(float)
    if len(a) < 2:
        return [None, None]
    rng = np.random.default_rng(seed)
    draws = rng.choice(a, size=(reps, len(a)), replace=True).mean(axis=1)
    q = np.quantile(draws, [0.025, 0.975])
    return [float(q[0]), float(q[1])]

def stats(g: pd.DataFrame, h: int, calendar: pd.DatetimeIndex, seed: int) -> dict[str, Any]:
    col = f"entry_{h}"
    z = g.dropna(subset=[col]).copy()
    if z.empty:
        return {"n": 0}
    z["block20"] = block_id(z.signal_date, calendar, 20)
    x = pd.to_numeric(z[col], errors="coerce")
    mae = pd.to_numeric(z[f"mae_{h}"], errors="coerce")
    mfe = pd.to_numeric(z[f"mfe_{h}"], errors="coerce")
    q = x.quantile([0.10, 0.90, 0.95])
    return {
        "n": int(len(z)),
        "events": int(z[["day0_date", "theme"]].drop_duplicates().shape[0]),
        "signal_dates": int(z.signal_date.nunique()),
        "themes": int(z.theme.nunique()),
        "mean": float(x.mean()),
        "median": float(x.median()),
        "win": float((x > 0).mean()),
        "pf": pf(x),
        "mae": float(mae.mean()),
        "mfe": float(mfe.mean()),
        "p10": float(q.loc[0.10]),
        "p90": float(q.loc[0.90]),
        "p95": float(q.loc[0.95]),
        "date_ci95": cluster_ci(z, col, "signal_date", seed),
        "block20_ci95": cluster_ci(z, col, "block20", seed + 1000),
        "theme_ci95": cluster_ci(z, col, "theme", seed + 2000),
    }

def rebuild_market(root: Path, analysis_start: str, analysis_end: str, max_tickers: int, batch_size: int, min_members: int):
    snap = er.load_json(root / "sector_snapshot.json")
    all_members, taxonomy = er.extract_theme_members(snap)
    industry_map = er.read_industry_map(root / "industry_map.json")
    universe = er.read_universe_symbols(root / "universe.csv")
    selected = er.stratified_symbols(all_members, set(industry_map) & universe, max_tickers)
    requested = selected + (["SPY"] if "SPY" not in selected else [])
    ohlcv, diag = post.rtv2.download_ohlcvo(
        requested,
        str((pd.Timestamp(analysis_start) - pd.Timedelta(days=900)).date()),
        str((pd.Timestamp(analysis_end) + pd.Timedelta(days=140)).date()),
        batch_size,
    )
    close_all, open_all, high_all, low_all, vol_all = (ohlcv[k] for k in ("close", "open", "high", "low", "volume"))
    cols = [s for s in selected if s in close_all.columns]
    close = close_all[cols]
    open_ = open_all[cols]
    high = high_all[cols]
    low = low_all[cols]
    stock_ret = close.pct_change(fill_method=None)
    spy_ret = close_all["SPY"].pct_change(fill_method=None)
    members = {t: [s for s in m if s in cols] for t, m in all_members.items()}
    theme_ret = er.grouped_equal_weight(stock_ret, members, min_members)
    theme63 = er.period_return(theme_ret, 63)
    spy63 = er.period_return(spy_ret, 63)
    theme_pct = theme63.sub(spy63, axis=0).rank(axis=1, pct=True) * 100.0
    breadth = er.breadth_above_ema21(close, members, min_members).reindex(columns=theme_ret.columns)
    delta20 = theme_pct - theme_pct.shift(20)
    active = (theme_pct >= 80.0) & (delta20 >= 15.0) & (breadth >= 60.0)
    return {
        "close": close, "open": open_, "high": high, "low": low,
        "theme_pct": theme_pct, "delta20": delta20, "breadth": breadth, "active": active,
        "members": members, "diag": diag, "taxonomy": taxonomy, "selected": selected,
    }

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--analysis-start", default="2016-01-04")
    ap.add_argument("--analysis-end", default="2026-06-30")
    ap.add_argument("--max-tickers", type=int, default=6000)
    ap.add_argument("--batch-size", type=int, default=75)
    ap.add_argument("--min-members", type=int, default=3)
    args = ap.parse_args()

    root = Path(args.root)
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    frozen = pd.read_csv(args.input, compression="gzip", parse_dates=["date"])
    cand = pd.concat(
        [top3(frozen, "ret63", "RS63_TOP3"), top3(frozen, "ret189", "RS189_TOP3")],
        ignore_index=True,
    )
    market = rebuild_market(root, args.analysis_start, args.analysis_end, args.max_tickers, args.batch_size, args.min_members)
    clz, op, hi, lo = market["close"], market["open"], market["high"], market["low"]
    common = sorted(set(cand.symbol.astype(str)) & set(clz.columns))
    cand = cand[cand.symbol.astype(str).isin(common)].copy()
    cand = cand.groupby(["date", "theme", "rank_type"], observed=True).filter(lambda g: len(g) == 3)
    rrsi = rd.rsi(clz[common], 14)
    pos = {pd.Timestamp(d): i for i, d in enumerate(clz.index)}
    rarr = {s: rrsi[s].to_numpy(float) for s in common}
    carr = {s: clz[s].to_numpy(float) for s in common}

    records: list[dict[str, Any]] = []
    for mname, (kind, arg, window) in METHODS.items():
        print("AUDIT_METHOD", mname, flush=True)
        for r in cand.itertuples(index=False):
            d0 = pd.Timestamp(r.date)
            ep = pos.get(d0, -1)
            sym = str(r.symbol)
            if ep < 0 or ep + 1 >= len(clz) or sym not in rarr:
                continue
            sp = rr.locate(rarr[sym], carr[sym], ep, kind, arg, window)
            if sp is None or sp + 1 >= len(clz):
                continue
            sigd = pd.Timestamp(clz.index[sp])
            entry = sp + 1
            theme = str(r.theme)
            active = False
            theme_pct = np.nan
            delta20 = np.nan
            breadth = np.nan
            if sigd in market["active"].index and theme in market["active"].columns:
                v = market["active"].at[sigd, theme]
                active = bool(v) if pd.notna(v) else False
                theme_pct = market["theme_pct"].at[sigd, theme]
                delta20 = market["delta20"].at[sigd, theme]
                breadth = market["breadth"].at[sigd, theme]
            rec = {
                "day0_date": d0, "signal_date": sigd, "entry_date": pd.Timestamp(clz.index[entry]),
                "theme": theme, "symbol": sym, "rank_type": str(r.rank_type), "method": mname,
                "delay": int(sp - ep), "rsi_signal": float(rarr[sym][sp]),
                "theme_active_signal": active,
                "theme_rs_pct_signal": float(theme_pct) if pd.notna(theme_pct) else np.nan,
                "theme_delta20_signal": float(delta20) if pd.notna(delta20) else np.nan,
                "theme_breadth_signal": float(breadth) if pd.notna(breadth) else np.nan,
            }
            for h in H:
                end = entry + h - 1
                rec[f"entry_{h}"] = trade_ret(op, clz, sym, entry, end) if end < len(clz) else np.nan
                rec[f"mfe_{h}"], rec[f"mae_{h}"] = excursions(op, hi, lo, sym, entry, end) if end < len(clz) else (np.nan, np.nan)
                term = ep + h
                rec[f"event_{h}"] = trade_ret(op, clz, sym, entry, term) if entry <= term < len(clz) else 0.0 if term < len(clz) else np.nan
                rec[f"base_event_{h}"] = trade_ret(op, clz, sym, ep + 1, term) if term < len(clz) else np.nan
            records.append(rec)

    trades = pd.DataFrame(records)
    trades.to_csv(out / "audit_trades.csv.gz", index=False, compression="gzip")
    if trades.empty:
        raise RuntimeError("no audit trades")

    trades["period"] = np.where(trades.day0_date <= DISC_END, "DISCOVERY", "CONFIRM")
    trades["signal_year"] = trades.signal_date.dt.year
    summary: dict[str, Any] = {}
    for (rank, method, period), g in trades.groupby(["rank_type", "method", "period"], observed=True):
        key = f"{rank}|{method}|{period}"
        block = {
            "n": int(len(g)),
            "events": int(g[["day0_date", "theme"]].drop_duplicates().shape[0]),
            "active_rate_at_signal": float(g.theme_active_signal.mean()),
            "active_n": int(g.theme_active_signal.sum()),
            "delay_mean": float(g.delay.mean()),
            "rsi_signal_mean": float(g.rsi_signal.mean()),
            "all": {str(h): stats(g, h, clz.index, 10000 + h) for h in H},
            "active_only": {str(h): stats(g[g.theme_active_signal], h, clz.index, 20000 + h) for h in H},
            "inactive_only": {str(h): stats(g[~g.theme_active_signal], h, clz.index, 30000 + h) for h in H},
            "by_signal_year_20d": {},
        }
        for y, yg in g.groupby("signal_year", observed=True):
            block["by_signal_year_20d"][str(int(y))] = stats(yg, 20, clz.index, 40000 + int(y))
        summary[key] = block

    union = trades.sort_values(["day0_date", "theme", "symbol", "method", "rank_type"]).drop_duplicates(
        ["day0_date", "theme", "symbol", "method"], keep="first"
    )
    union_summary: dict[str, Any] = {}
    for (method, period), g in union.groupby(["method", "period"], observed=True):
        key = f"{method}|{period}"
        union_summary[key] = {
            "n": int(len(g)),
            "active_rate_at_signal": float(g.theme_active_signal.mean()),
            "all_20": stats(g, 20, clz.index, 50000 + len(union_summary)),
            "active_20": stats(g[g.theme_active_signal], 20, clz.index, 60000 + len(union_summary)),
            "by_signal_year_20d": {
                str(int(y)): stats(yg, 20, clz.index, 70000 + int(y))
                for y, yg in g.groupby("signal_year", observed=True)
            },
        }

    result = {
        "status": "RSI_RESET_FOCUSED_ROBUST_AUDIT",
        "coverage": {
            "frozen_theme_events": int(frozen[["date", "theme"]].drop_duplicates().shape[0]),
            "candidate_rows": int(len(cand)),
            "candidate_symbols": int(cand.symbol.nunique()),
            "downloaded_symbols": int(len(clz.columns)),
        },
        "download": market["diag"],
        "taxonomy": market["taxonomy"],
        "methods": METHODS,
        "definitions": {
            "theme_active_signal": "same daily Subtheme Momentum mask: Theme RS pct>=80, delta20>=15, breadth>=60",
            "signal": "condition known at close; buy next open",
            "cost": "5 bps/side",
            "bootstrap": "conditional traded rows, clustered separately by signal date, 20-trading-day block, and theme",
        },
        "summary": summary,
        "union_dedup": union_summary,
        "limitations": [
            "current-universe/current-taxonomy retrospective bias",
            "Yahoo adjusted OHLCV may differ from TradingView",
            "theme active is reconstructed from the same current-taxonomy full-universe method, not inferred from Day0 only",
        ],
    }
    (out / "summary.json").write_text(json.dumps(safe(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(safe({
        "status": result["status"],
        "coverage": result["coverage"],
        "download": result["download"],
        "keys": list(summary)[:10],
    }), ensure_ascii=False, indent=2), flush=True)

if __name__ == "__main__":
    main()
