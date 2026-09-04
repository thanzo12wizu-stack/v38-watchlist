from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

URL_5M = "https://raw.githubusercontent.com/lvrusu/QQQ_price_data/main/QQQ5m_Ext_J_23_to_Mar_20a_2026.csv"
URL_1M = "https://raw.githubusercontent.com/lvrusu/QQQ_price_data/main/QQQ1m_Ext_J_26_to_Mar_26B_2026.csv"
CUTOFF = pd.Timestamp("2026-03-20")


def normalize_yf(raw: pd.DataFrame) -> pd.DataFrame:
    x = raw.copy()
    if isinstance(x.columns, pd.MultiIndex):
        if len(set(x.columns.get_level_values(0))) == 1:
            x.columns = x.columns.get_level_values(1)
        elif len(set(x.columns.get_level_values(1))) == 1:
            x.columns = x.columns.get_level_values(0)
    x.index = pd.DatetimeIndex(pd.to_datetime(x.index))
    if x.index.tz is None:
        x.index = x.index.tz_localize("America/New_York", ambiguous="infer", nonexistent="shift_forward")
    else:
        x.index = x.index.tz_convert("America/New_York")
    x = x[["Open", "High", "Low", "Close"]].apply(pd.to_numeric, errors="coerce").dropna()
    return x.sort_index()


def load_external(url: str) -> pd.DataFrame:
    x = pd.read_csv(url)
    lower = {str(c).lower(): c for c in x.columns}
    time_col = lower.get("ds") or lower.get("datetime") or lower.get("date") or lower.get("timestamp")
    if time_col is None:
        raise RuntimeError(f"no datetime column in {url}: {list(x.columns)}")
    rename = {time_col: "ds"}
    for want in ("Open", "High", "Low", "Close"):
        src = lower.get(want.lower())
        if src is None:
            raise RuntimeError(f"missing {want} in {url}: {list(x.columns)}")
        rename[src] = want
    x = x.rename(columns=rename)[["ds", "Open", "High", "Low", "Close"]]
    x["ds"] = pd.to_datetime(x["ds"], errors="coerce")
    if getattr(x["ds"].dt, "tz", None) is not None:
        x["ds"] = x["ds"].dt.tz_convert("America/New_York").dt.tz_localize(None)
    for c in ("Open", "High", "Low", "Close"):
        x[c] = pd.to_numeric(x[c], errors="coerce")
    return x.dropna().sort_values("ds")


def aggregate_external(x: pd.DataFrame, min_count: int) -> pd.DataFrame:
    y = x.copy()
    minutes = y.ds.dt.hour * 60 + y.ds.dt.minute
    y = y[(minutes >= 570) & (minutes < 960)].copy()
    minutes = y.ds.dt.hour * 60 + y.ds.dt.minute
    y["date"] = y.ds.dt.normalize()
    y["slot"] = np.where(minutes < 810, 0, 1)
    z = y.groupby(["date", "slot"], sort=True).agg(
        Open=("Open", "first"), High=("High", "max"), Low=("Low", "min"), Close=("Close", "last"), n=("Close", "size")
    ).reset_index()
    return z[z.n >= min_count].copy().sort_values(["date", "slot"]).reset_index(drop=True)


def aggregate_yf(raw: pd.DataFrame, min_count: int) -> pd.DataFrame:
    y = normalize_yf(raw)
    minutes = y.index.hour * 60 + y.index.minute
    y = y[(minutes >= 570) & (minutes < 960)].copy()
    minutes = y.index.hour * 60 + y.index.minute
    y["date"] = pd.DatetimeIndex(y.index.date)
    y["slot"] = np.where(minutes < 810, 0, 1)
    z = y.groupby(["date", "slot"], sort=True).agg(
        Open=("Open", "first"), High=("High", "max"), Low=("Low", "min"), Close=("Close", "last"), n=("Close", "size")
    ).reset_index()
    return z[z.n >= min_count].copy().sort_values(["date", "slot"]).reset_index(drop=True)


def wilder_full(close: np.ndarray, n: int = 14):
    a = np.asarray(close, float)
    d = np.diff(a, prepend=np.nan)
    up = np.where(d > 0, d, 0.0)
    dn = np.where(d < 0, -d, 0.0)
    au = np.full(len(a), np.nan)
    ad = np.full(len(a), np.nan)
    if len(a) > n:
        au[n] = np.nanmean(up[1:n + 1])
        ad[n] = np.nanmean(dn[1:n + 1])
        for i in range(n + 1, len(a)):
            au[i] = (au[i - 1] * (n - 1) + up[i]) / n
            ad[i] = (ad[i - 1] * (n - 1) + dn[i]) / n
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = au / ad
        r = 100 - 100 / (1 + rs)
    r[(ad == 0) & np.isfinite(au)] = 100.0
    r[(au == 0) & (ad == 0)] = 50.0
    return r, au, ad


def wilder_continue(last_close: float, au: float, ad: float, closes: np.ndarray, n: int = 14):
    out = []
    prev = float(last_close)
    u = float(au)
    d = float(ad)
    for c0 in np.asarray(closes, float):
        delta = float(c0) - prev
        up = max(delta, 0.0)
        dn = max(-delta, 0.0)
        u = (u * (n - 1) + up) / n
        d = (d * (n - 1) + dn) / n
        if d == 0 and np.isfinite(u):
            r = 100.0
        elif u == 0 and d == 0:
            r = 50.0
        else:
            rs = u / d
            r = 100 - 100 / (1 + rs)
        out.append((r, u, d))
        prev = float(c0)
    return np.asarray([x[0] for x in out]), float(u), float(d)


def touch(rsi: np.ndarray, prior_rsi: float | None = None) -> np.ndarray:
    r = np.asarray(rsi, float)
    prev = np.r_[np.nan if prior_rsi is None else prior_rsi, r[:-1]]
    return (r <= 30) & (prev > 30)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    ext5 = load_external(URL_5M)
    b5hist = aggregate_external(ext5, min_count=6)
    b5hist = b5hist[b5hist.date <= CUTOFF].copy()
    if len(b5hist) < 500:
        raise RuntimeError(f"insufficient historical 5m bars: {len(b5hist)}")
    r_hist, au_hist, ad_hist = wilder_full(b5hist.Close.to_numpy(float), 14)
    valid = np.flatnonzero(np.isfinite(r_hist) & np.isfinite(au_hist) & np.isfinite(ad_hist))
    if not len(valid):
        raise RuntimeError("no valid historical Wilder state")
    k = int(valid[-1])
    state = {
        "date": str(pd.Timestamp(b5hist.iloc[k].date).date()),
        "slot": int(b5hist.iloc[k].slot),
        "close": float(b5hist.iloc[k].Close),
        "rsi": float(r_hist[k]),
        "au": float(au_hist[k]),
        "ad": float(ad_hist[k]),
    }

    raw60 = yf.download("QQQ", period="730d", interval="60m", progress=False, auto_adjust=False, actions=False, prepost=False, threads=False)
    if raw60 is None or raw60.empty:
        raise RuntimeError("Yahoo 60m unavailable")
    b60 = aggregate_yf(raw60, min_count=2)
    post60 = b60[b60.date > CUTOFF].copy().sort_values(["date", "slot"]).reset_index(drop=True)
    if post60.empty:
        raise RuntimeError("no hourly bars after cutoff")
    r_bridge, _, _ = wilder_continue(state["close"], state["au"], state["ad"], post60.Close.to_numpy(float), 14)
    post60["bridge_rsi14"] = r_bridge
    post60["bridge_touch30"] = touch(r_bridge, state["rsi"])

    # Independent immediate-post-cutoff check using the repository's later 1-minute file.
    ext1 = load_external(URL_1M)
    b1 = aggregate_external(ext1, min_count=30)
    b1 = b1[(b1.date > CUTOFF) & (b1.date <= pd.Timestamp("2026-03-26"))].copy()
    immediate = b1.merge(post60, on=["date", "slot"], suffixes=("_1m", "_60m"), how="inner").sort_values(["date", "slot"]).reset_index(drop=True)
    if len(immediate) < 4:
        raise RuntimeError(f"insufficient immediate 1m/hourly overlap: {len(immediate)}")
    immediate["close_diff_bps"] = (immediate.Close_60m / immediate.Close_1m - 1.0) * 10000.0

    # Propagate the exact March-20 state through the independent 1m closes and compare RSI to hourly propagation.
    r1, _, _ = wilder_continue(state["close"], state["au"], state["ad"], immediate.Close_1m.to_numpy(float), 14)
    rh, _, _ = wilder_continue(state["close"], state["au"], state["ad"], immediate.Close_60m.to_numpy(float), 14)
    immediate["rsi_1m_state"] = r1
    immediate["rsi_60m_state"] = rh
    immediate["rsi_abs_diff"] = np.abs(r1 - rh)
    t1 = touch(r1, state["rsi"])
    th = touch(rh, state["rsi"])
    immediate["touch30_1m_state"] = t1
    immediate["touch30_60m_state"] = th

    # Current 5m overlap: verify the hourly 4H closes still match exactly months later.
    raw5cur = yf.download("QQQ", period="60d", interval="5m", progress=False, auto_adjust=False, actions=False, prepost=False, threads=False)
    if raw5cur is None or raw5cur.empty:
        raise RuntimeError("Yahoo current 5m unavailable")
    b5cur = aggregate_yf(raw5cur, min_count=6)
    current = b5cur.merge(post60, on=["date", "slot"], suffixes=("_5m", "_60m"), how="inner").sort_values(["date", "slot"]).reset_index(drop=True)
    if len(current) < 40:
        raise RuntimeError(f"insufficient current 5m/hourly overlap: {len(current)}")
    current["close_diff_bps"] = (current.Close_60m / current.Close_5m - 1.0) * 10000.0

    # Quantify current live 60-day RSI reseed drift versus the bridged long-state RSI on the same current bars.
    cur_rsi, _, _ = wilder_full(b5cur.Close.to_numpy(float), 14)
    b5cur["live60d_rsi14"] = cur_rsi
    b5cur["live60d_touch30"] = touch(cur_rsi)
    bridge_view = post60[["date", "slot", "bridge_rsi14", "bridge_touch30"]]
    livecmp = b5cur.merge(bridge_view, on=["date", "slot"], how="inner").sort_values(["date", "slot"]).reset_index(drop=True)
    # Ignore the first 40 bars of current 5m history to give the truncated seed substantial burn-in.
    livecmp_eval = livecmp.iloc[min(40, len(livecmp) // 3):].copy()
    livecmp_eval = livecmp_eval[np.isfinite(livecmp_eval.live60d_rsi14)].copy()
    livecmp_eval["rsi_abs_diff"] = (livecmp_eval.live60d_rsi14 - livecmp_eval.bridge_rsi14).abs()
    live_signal_mismatch = int((livecmp_eval.live60d_touch30.astype(bool) != livecmp_eval.bridge_touch30.astype(bool)).sum())

    immediate_close_max = float(immediate.close_diff_bps.abs().max())
    immediate_rsi_max = float(immediate.rsi_abs_diff.max())
    immediate_touch_match = bool((t1 == th).all())
    current_close_max = float(current.close_diff_bps.abs().max())
    bars_supported = bool(immediate_close_max <= 1.0 and current_close_max <= 1.0)
    state_supported = bool(immediate_rsi_max <= 1e-8 and immediate_touch_match)

    immediate.to_csv(out / "stage56_state_bridge_immediate.csv", index=False)
    current.to_csv(out / "stage56_state_bridge_current_overlap.csv", index=False)
    livecmp.to_csv(out / "stage56_live60d_vs_bridge.csv", index=False)
    post60[["date", "slot", "Close", "bridge_rsi14", "bridge_touch30"]].to_csv(out / "stage56_hourly_state_bridge.csv", index=False)

    summary = {
        "status": "STAGE56_STATE_INHERITANCE_BRIDGE_AUDIT",
        "cutoff_state": state,
        "hourly_coverage": {"start": str(pd.Timestamp(post60.date.min()).date()), "end": str(pd.Timestamp(post60.date.max()).date()), "bars": int(len(post60))},
        "immediate_independent_1m_check": {
            "bars": int(len(immediate)),
            "start": str(pd.Timestamp(immediate.date.min()).date()),
            "end": str(pd.Timestamp(immediate.date.max()).date()),
            "close_abs_diff_bps_max": immediate_close_max,
            "rsi_abs_diff_max_with_same_state": immediate_rsi_max,
            "touch30_all_match": immediate_touch_match,
        },
        "current_5m_hourly_check": {
            "bars": int(len(current)),
            "close_abs_diff_bps_max": current_close_max,
        },
        "live_60d_reseed_vs_continuous_state": {
            "compare_bars": int(len(livecmp_eval)),
            "rsi_abs_diff_median": float(livecmp_eval.rsi_abs_diff.median()),
            "rsi_abs_diff_p99": float(livecmp_eval.rsi_abs_diff.quantile(.99)),
            "touch30_mismatches": live_signal_mismatch,
        },
        "hourly_bar_bridge_supported": bars_supported,
        "wilder_state_inheritance_supported": state_supported,
        "historical_extension_status": "SUPPORTED_WITH_PROXY_GAP" if bars_supported and state_supported else "REJECTED",
        "limitation": "There is no independent 1m/5m source for every session from 2026-03-27 through the start of Yahoo's current 60d 5m window. Hourly closes are independently exact immediately after cutoff and again in the current overlap, but the middle gap remains proxy data.",
        "guardrail": "Do not call the Mar-Sep extension pristine OOS. Use only as a sensitivity extension unless continuous exact intraday history is obtained.",
    }
    (out / "stage56_state_bridge_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
