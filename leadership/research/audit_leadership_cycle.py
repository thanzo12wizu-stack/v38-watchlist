from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf

import audit_ordinary_stock_market_mode_robustness as base

DISC_END = pd.Timestamp("2021-12-31")
CONF_START = pd.Timestamp("2022-01-03")
HORIZONS = (5, 10, 20, 40, 60)
COOLDOWN = 20

F1_CAUTION = 0.15
F1_WARN = 0.30
F2_CAUTION = 0.25
F2_WARN = 0.40
F2_SEVERE = 0.60
F3_WARN = 0.40
F3_SEVERE = 0.60
TEMP_EXHAUST = 10.0
TEMP_RECOVERY = 30.0


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


def download_market(start: str, end: str) -> dict[str, pd.DataFrame]:
    raw = yf.download(
        ["QQQ", "SPY"], start=start, end=end, auto_adjust=True,
        actions=False, progress=False, group_by="ticker", threads=True, timeout=30,
    )
    if raw is None or raw.empty:
        raise RuntimeError("market download empty")
    out: dict[str, pd.DataFrame] = {}
    for sym in ("QQQ", "SPY"):
        if isinstance(raw.columns, pd.MultiIndex):
            if sym not in raw.columns.get_level_values(0):
                raise RuntimeError(f"missing market symbol {sym}")
            p = raw[sym].copy()
        else:
            p = raw.copy()
        p.index = pd.to_datetime(p.index).tz_localize(None)
        out[sym] = p[[c for c in ("Open", "High", "Low", "Close") if c in p.columns]].apply(pd.to_numeric, errors="coerce")
    return out


def rolling_last_percentile(s: pd.Series, window: int = 504, min_periods: int = 60) -> pd.Series:
    return s.rolling(window, min_periods=min_periods).apply(
        lambda x: float(np.mean(x <= x[-1]) * 100.0), raw=True
    )


def build_leadership_series(matrices: dict[str, pd.DataFrame]) -> pd.DataFrame:
    close = matrices["close"].astype(float)
    sma50 = close.rolling(50, min_periods=45).mean()
    sma200 = close.rolling(200, min_periods=180).mean()
    dvol = matrices["dvol"].reindex_like(close)
    split_bad = (close.pct_change(fill_method=None).abs() > 1.5).rolling(189).max().fillna(0).astype(bool)
    pool = (sma50 > sma200) & (close >= 5.0) & (dvol >= base.DVOL_FLOOR) & ~split_bad

    ret20 = close.pct_change(20, fill_method=None)
    ret63 = close.pct_change(63, fill_method=None)
    ret189 = close.pct_change(189, fill_method=None)
    r189 = ret189.where(pool)
    rk = r189.rank(axis=1, ascending=False, method="min")
    rs189p = r189.rank(axis=1, pct=True, method="average") * 100.0
    rs63p = ret63.where(pool).rank(axis=1, pct=True, method="average") * 100.0
    d52 = close / close.rolling(252, min_periods=200).max() - 1.0

    observable = (
        close.notna() & sma50.notna() & sma200.notna() & dvol.notna()
        & close.shift(189).notna() & ~split_bad
    )
    was24 = rk.shift(20) <= 24
    rank_drop = was24 & observable & pool & (rk > 36)
    elig_drop = was24 & observable & ~pool
    den_all = was24.sum(axis=1).replace(0, np.nan)
    den_obs = (was24 & observable).sum(axis=1).replace(0, np.nan)
    coverage = den_obs / den_all
    f1 = (rank_drop | elig_drop).sum(axis=1) / den_obs
    f1 = f1.where(coverage >= 0.70)

    top24 = rk <= 24
    obs63 = top24 & rs63p.notna()
    f2 = ((rs63p < 85.0) & obs63).sum(axis=1) / obs63.sum(axis=1).replace(0, np.nan)

    qual = (rs189p >= 85.0) & (close > sma200) & pool
    f3 = (qual & ((ret20 <= 0.0) | (d52 < -0.15))).sum(axis=1) / qual.sum(axis=1).replace(0, np.nan)

    # Production Leader Temperature: top decile by 189d strength, mean 63d return,
    # then point-in-time rolling percentile. No future observations enter a historical percentile.
    raw_valid_n = ret189.notna().sum(axis=1)
    q90 = ret189.quantile(0.90, axis=1, interpolation="linear")
    top10 = ret189.ge(q90, axis=0) & ret63.notna()
    lead_strength = ret63.where(top10).mean(axis=1).where(raw_valid_n >= 30)
    temp = rolling_last_percentile(lead_strength, 504, 60)

    # Production-style Momentum Run, reconstructed point-in-time for every historical date.
    l1 = rs63p.shift(21)
    l2 = rs63p.shift(42)
    d_recent = rs63p - l1
    fade = top24 & rs63p.notna() & (
        (rs63p < 50.0)
        | ((rs63p < 85.0) & (d_recent <= -3.0))
        | (d_recent <= -8.0)
    )
    acc = top24 & rs63p.notna() & ~fade & (d_recent >= 3.0)
    run_n = top24.sum(axis=1).replace(0, np.nan)
    run_fade_n = fade.sum(axis=1)
    run_acc_n = acc.sum(axis=1)
    run_fade_share = run_fade_n / run_n
    run_acc_share = run_acc_n / run_n
    run_health = pd.Series("cruise", index=close.index, dtype=object)
    run_health.loc[run_fade_n > run_acc_n] = "fade"
    expansion = (run_acc_n >= 2 * run_fade_n) & (run_acc_n >= run_n * 0.30)
    run_health.loc[expansion] = "expansion"
    run_health.loc[run_n.isna()] = None

    out = pd.DataFrame({
        "f1": f1,
        "f1_coverage": coverage,
        "f2": f2,
        "f3": f3,
        "leader_temp": temp,
        "leader_strength": lead_strength,
        "run_fade_share": run_fade_share,
        "run_acc_share": run_acc_share,
        "run_health": run_health,
        "eligible_queue_n": qual.sum(axis=1),
        "leader_n": top24.sum(axis=1),
    })
    return out


def eventize(mask: pd.Series, cooldown: int = COOLDOWN) -> list[pd.Timestamp]:
    m = mask.fillna(False).astype(bool)
    cross = m & ~m.shift(1, fill_value=False)
    dates: list[pd.Timestamp] = []
    last_i = -10**9
    for i, v in enumerate(cross.to_numpy(bool)):
        if v and i - last_i >= cooldown:
            dates.append(pd.Timestamp(cross.index[i]))
            last_i = i
    return dates


def sampled_baseline(idx: pd.DatetimeIndex, start_offset: int = 0, step: int = COOLDOWN) -> list[pd.Timestamp]:
    return [pd.Timestamp(x) for x in idx[start_offset::step]]


def max_close_drawdown(x: pd.Series) -> float | None:
    z = pd.to_numeric(x, errors="coerce").dropna()
    if len(z) < 2:
        return None
    dd = z / z.cummax() - 1.0
    return float(dd.min())


def outcome_rows(
    name: str, dates: list[pd.Timestamp], qqq: pd.DataFrame, spy: pd.DataFrame,
    nq_color: pd.Series,
) -> pd.DataFrame:
    qidx = qqq.index
    rows: list[dict[str, Any]] = []
    for d0 in dates:
        if d0 not in qidx:
            pos = int(qidx.searchsorted(d0))
            if pos >= len(qidx):
                continue
            d = pd.Timestamp(qidx[pos])
        else:
            d = d0
            pos = int(qidx.get_loc(d))
        q0 = float(qqq.at[d, "Close"]) if pd.notna(qqq.at[d, "Close"]) else np.nan
        s0 = float(spy.at[d, "Close"]) if d in spy.index and pd.notna(spy.at[d, "Close"]) else np.nan
        rec: dict[str, Any] = {"event": name, "signal_date": d0, "market_date": d}
        for h in HORIZONS:
            j = pos + h
            if j >= len(qidx) or not np.isfinite(q0):
                rec[f"qqq_ret_{h}"] = np.nan
                rec[f"qqq_mfe_{h}"] = np.nan
                rec[f"qqq_mae_{h}"] = np.nan
                rec[f"qqq_mdd_{h}"] = np.nan
                rec[f"spy_ret_{h}"] = np.nan
                continue
            qwin = qqq.iloc[pos + 1:j + 1]
            qclose = qqq.iloc[pos:j + 1]["Close"]
            rec[f"qqq_ret_{h}"] = float(qqq.iloc[j]["Close"] / q0 - 1.0)
            rec[f"qqq_mfe_{h}"] = float(qwin["High"].max() / q0 - 1.0) if qwin["High"].notna().any() else np.nan
            rec[f"qqq_mae_{h}"] = float(qwin["Low"].min() / q0 - 1.0) if qwin["Low"].notna().any() else np.nan
            rec[f"qqq_mdd_{h}"] = max_close_drawdown(qclose)
            sd = qidx[j]
            rec[f"spy_ret_{h}"] = float(spy.at[sd, "Close"] / s0 - 1.0) if sd in spy.index and np.isfinite(s0) and pd.notna(spy.at[sd, "Close"]) else np.nan
        end60 = min(len(qidx) - 1, pos + 60)
        future_dates = qidx[pos + 1:end60 + 1]
        colors = nq_color.reindex(future_dates).ffill(limit=1)
        redpos = np.flatnonzero(colors.astype(str).eq("Red").to_numpy())
        rec["red_within_60"] = bool(len(redpos)) if len(future_dates) >= 20 else np.nan
        rec["red_lead"] = int(redpos[0] + 1) if len(redpos) else np.nan
        if end60 > pos and np.isfinite(q0):
            q60 = qqq.iloc[pos + 1:end60 + 1]
            if q60["Low"].notna().any():
                low_pos_rel = int(np.nanargmin(q60["Low"].to_numpy(float)))
                rec["future_low_lead_60"] = low_pos_rel + 1
                rec["future_low_from_signal_60"] = float(q60["Low"].iloc[low_pos_rel] / q0 - 1.0)
            else:
                rec["future_low_lead_60"] = np.nan
                rec["future_low_from_signal_60"] = np.nan
        rows.append(rec)
    return pd.DataFrame(rows)


def wilson(p_count: int, n: int, z: float = 1.96) -> tuple[float | None, float | None]:
    if n <= 0:
        return None, None
    p = p_count / n
    den = 1.0 + z * z / n
    center = (p + z * z / (2 * n)) / den
    half = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / den
    return center - half, center + half


def summarize_frame(df: pd.DataFrame) -> dict[str, Any]:
    if df.empty:
        return {"n_events": 0}
    out: dict[str, Any] = {"n_events": int(len(df))}
    for h in HORIZONS:
        r = pd.to_numeric(df.get(f"qqq_ret_{h}"), errors="coerce").dropna()
        mdd = pd.to_numeric(df.get(f"qqq_mdd_{h}"), errors="coerce").dropna()
        out[f"qqq_ret_{h}_n"] = int(len(r))
        out[f"qqq_ret_{h}_mean"] = float(r.mean()) if len(r) else None
        out[f"qqq_ret_{h}_median"] = float(r.median()) if len(r) else None
        out[f"qqq_ret_{h}_win_rate"] = float((r > 0).mean()) if len(r) else None
        out[f"qqq_mdd_{h}_mean"] = float(mdd.mean()) if len(mdd) else None
        if len(mdd):
            out[f"dd5_{h}_prob"] = float((mdd <= -0.05).mean())
            out[f"dd10_{h}_prob"] = float((mdd <= -0.10).mean())
    red = df.get("red_within_60", pd.Series(dtype=float)).dropna().astype(bool)
    out["red60_n"] = int(len(red))
    out["red60_prob"] = float(red.mean()) if len(red) else None
    if len(red):
        lo, hi = wilson(int(red.sum()), len(red))
        out["red60_ci95"] = [lo, hi]
    lead = pd.to_numeric(df.get("red_lead"), errors="coerce").dropna()
    out["red_lead_median"] = float(lead.median()) if len(lead) else None
    out["red_lead_mean"] = float(lead.mean()) if len(lead) else None
    lowlead = pd.to_numeric(df.get("future_low_lead_60"), errors="coerce").dropna()
    out["future_low_lead_60_median"] = float(lowlead.median()) if len(lowlead) else None
    return out


def split_summary(df: pd.DataFrame) -> dict[str, Any]:
    if df.empty:
        return {"full": {"n_events": 0}, "discovery": {"n_events": 0}, "confirmation": {"n_events": 0}}
    d = pd.to_datetime(df["signal_date"])
    return {
        "full": summarize_frame(df),
        "discovery": summarize_frame(df.loc[d <= DISC_END]),
        "confirmation": summarize_frame(df.loc[d >= CONF_START]),
    }


def odds_ratio(event_df: pd.DataFrame, baseline_df: pd.DataFrame, col: str, cutoff: float) -> float | None:
    a = pd.to_numeric(event_df.get(col), errors="coerce").dropna()
    b = pd.to_numeric(baseline_df.get(col), errors="coerce").dropna()
    if len(a) < 3 or len(b) < 20:
        return None
    ae = int((a <= cutoff).sum()); an = int(len(a) - ae)
    be = int((b <= cutoff).sum()); bn = int(len(b) - be)
    return float(((ae + 0.5) * (bn + 0.5)) / ((an + 0.5) * (be + 0.5)))


def bootstrap_mean_delta(a: pd.Series, b: pd.Series, reps: int = 3000, seed: int = 20260902) -> dict[str, Any]:
    x = pd.to_numeric(a, errors="coerce").dropna().to_numpy(float)
    y = pd.to_numeric(b, errors="coerce").dropna().to_numpy(float)
    if len(x) < 5 or len(y) < 20:
        return {"n_a": len(x), "n_b": len(y)}
    rng = np.random.default_rng(seed)
    vals = np.empty(reps, dtype=float)
    for i in range(reps):
        vals[i] = rng.choice(x, len(x), replace=True).mean() - rng.choice(y, len(y), replace=True).mean()
    return {
        "n_a": int(len(x)), "n_b": int(len(y)),
        "observed_delta": float(x.mean() - y.mean()),
        "ci05": float(np.quantile(vals, 0.05)),
        "ci95": float(np.quantile(vals, 0.95)),
        "prob_delta_gt0": float((vals > 0).mean()),
    }


def first_future(mask: pd.Series, d: pd.Timestamp, max_h: int = 60) -> int | None:
    idx = mask.index
    if d not in idx:
        return None
    p = int(idx.get_loc(d))
    z = mask.iloc[p + 1:min(len(idx), p + max_h + 1)].fillna(False).to_numpy(bool)
    hit = np.flatnonzero(z)
    return int(hit[0] + 1) if len(hit) else None


def sequence_stats(events: list[pd.Timestamp], targets: dict[str, pd.Series], split_start: pd.Timestamp | None = None, split_end: pd.Timestamp | None = None) -> dict[str, Any]:
    ds = [d for d in events if (split_start is None or d >= split_start) and (split_end is None or d <= split_end)]
    out: dict[str, Any] = {"n_source": len(ds)}
    for name, mask in targets.items():
        lags = [first_future(mask, d, 60) for d in ds]
        hits = [x for x in lags if x is not None]
        out[name] = {
            "hit60_prob": float(len(hits) / len(ds)) if ds else None,
            "median_lag": float(np.median(hits)) if hits else None,
            "mean_lag": float(np.mean(hits)) if hits else None,
            "n_hits": len(hits),
        }
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--output", required=True)
    ap.add_argument("--analysis-start", default="2016-01-04")
    ap.add_argument("--analysis-end", default="2026-08-31")
    ap.add_argument("--max-tickers", type=int, default=6000)
    ap.add_argument("--batch-size", type=int, default=75)
    args = ap.parse_args()

    root = Path(args.root)
    out = root / args.output
    out.mkdir(parents=True, exist_ok=True)

    print("BUILD INPUTS", flush=True)
    meta, matrices = base.build_inputs(root, args.analysis_start, args.analysis_end, args.max_tickers, args.batch_size)
    print("BUILD LEADERSHIP SERIES", flush=True)
    sig = build_leadership_series(matrices)
    idx = pd.DatetimeIndex(meta["analysis_idx"])
    sig = sig.reindex(idx)
    breadth = meta["breadth"].reindex(idx)
    nq = meta["nq"].reindex(idx)
    nq_color = nq["nq_color"].astype(object).ffill(limit=1)

    market_start = str((pd.Timestamp(args.analysis_start) - pd.Timedelta(days=10)).date())
    market_end = str((pd.Timestamp(args.analysis_end) + pd.Timedelta(days=120)).date())
    print("DOWNLOAD MARKET", flush=True)
    market = download_market(market_start, market_end)
    qqq = market["QQQ"]
    spy = market["SPY"].reindex(qqq.index).ffill(limit=1)

    bull = nq_color.isin(["Blue", "Green"])
    f1w = sig["f1"] >= F1_WARN
    f2w = sig["f2"] >= F2_WARN
    f2s = sig["f2"] >= F2_SEVERE
    f3w = sig["f3"] >= F3_WARN
    f3s = sig["f3"] >= F3_SEVERE
    temp_low = sig["leader_temp"] <= TEMP_EXHAUST
    run_fade = sig["run_health"].eq("fade")
    recent_warning = (f1w | f2w).rolling(60, min_periods=1).max().astype(bool)
    recent_temp_low = temp_low.shift(1).rolling(20, min_periods=1).max().astype(bool)

    masks: dict[str, pd.Series] = {
        "F1_WARN": f1w,
        "F1_WARN_PRERED": f1w & ~nq_color.eq("Red"),
        "F2_WARN": f2w,
        "F2_SEVERE": f2s,
        "F2_WARN_PRERED": f2w & ~nq_color.eq("Red"),
        "F3_WARN": f3w,
        "F3_SEVERE": f3s,
        "RUN_FADE": run_fade,
        "TEMP_LE10": temp_low,
        "TEMP_GE82": sig["leader_temp"] >= 82.0,
        "F1_AND_F2": f1w & f2w,
        "F1_F2_PRERED": f1w & f2w & ~nq_color.eq("Red"),
        "F1_F2_F3_SEVERE": f1w & f2w & f3s,
        "F1_F2_BULL_BREADTH60": f1w & f2w & bull & (breadth >= 60.0),
        "F1_F2_WEAK_GATE": f1w & f2w & (~bull | (breadth < 60.0)),
        "RUN_FADE_AFTER_F1": run_fade & f1w,
        "TEMP_EXHAUST_AFTER_WARNING": temp_low & recent_warning,
        "TEMP_RECOVERY30_AFTER_EXHAUST": (sig["leader_temp"] >= TEMP_RECOVERY) & recent_temp_low,
    }

    event_dates = {k: eventize(v, COOLDOWN) for k, v in masks.items()}
    baseline_dates = sampled_baseline(idx, 0, COOLDOWN)
    baseline_df = outcome_rows("BASELINE_20D_SAMPLE", baseline_dates, qqq, spy, nq_color)
    all_event_frames: list[pd.DataFrame] = [baseline_df]
    summaries: dict[str, Any] = {"BASELINE_20D_SAMPLE": split_summary(baseline_df)}
    comparisons: dict[str, Any] = {}

    print("EVENT STUDIES", flush=True)
    for n, ds in event_dates.items():
        ef = outcome_rows(n, ds, qqq, spy, nq_color)
        all_event_frames.append(ef)
        summaries[n] = split_summary(ef)
        conf = ef.loc[pd.to_datetime(ef["signal_date"]) >= CONF_START] if len(ef) else ef
        bconf = baseline_df.loc[pd.to_datetime(baseline_df["signal_date"]) >= CONF_START]
        comparisons[n] = {
            "confirmation_dd10_60_odds_vs_baseline": odds_ratio(conf, bconf, "qqq_mdd_60", -0.10),
            "confirmation_dd5_60_odds_vs_baseline": odds_ratio(conf, bconf, "qqq_mdd_60", -0.05),
            "confirmation_ret20_mean_delta_bootstrap": bootstrap_mean_delta(conf.get("qqq_ret_20", pd.Series(dtype=float)), bconf.get("qqq_ret_20", pd.Series(dtype=float)), seed=20260902 + len(comparisons)),
            "confirmation_mdd60_mean_delta_bootstrap": bootstrap_mean_delta(conf.get("qqq_mdd_60", pd.Series(dtype=float)), bconf.get("qqq_mdd_60", pd.Series(dtype=float)), seed=20261902 + len(comparisons)),
        }

    # Frozen threshold-neighborhood sensitivity. This is not an optimizer: current thresholds are central,
    # neighboring values are used only to reject brittle/non-monotone effects.
    sensitivity_rows: list[dict[str, Any]] = []
    grids = {
        "F1": (sig["f1"], [0.20, 0.25, 0.30, 0.35, 0.40], "ge"),
        "F2": (sig["f2"], [0.30, 0.40, 0.50, 0.60, 0.70], "ge"),
        "F3": (sig["f3"], [0.40, 0.50, 0.60, 0.70], "ge"),
        "TEMP_LOW": (sig["leader_temp"], [5.0, 10.0, 15.0, 20.0], "le"),
    }
    print("SENSITIVITY", flush=True)
    for fam, (series, thresholds, direction) in grids.items():
        for th in thresholds:
            mask = series >= th if direction == "ge" else series <= th
            ds = eventize(mask, COOLDOWN)
            ef = outcome_rows(f"{fam}_{th}", ds, qqq, spy, nq_color)
            for split, sdf in (
                ("discovery", ef.loc[pd.to_datetime(ef["signal_date"]) <= DISC_END] if len(ef) else ef),
                ("confirmation", ef.loc[pd.to_datetime(ef["signal_date"]) >= CONF_START] if len(ef) else ef),
            ):
                s = summarize_frame(sdf)
                sensitivity_rows.append({
                    "family": fam, "threshold": th, "direction": direction, "split": split,
                    "n_events": s.get("n_events"), "ret20_mean": s.get("qqq_ret_20_mean"),
                    "ret60_mean": s.get("qqq_ret_60_mean"), "mdd60_mean": s.get("qqq_mdd_60_mean"),
                    "dd10_60_prob": s.get("dd10_60_prob"), "red60_prob": s.get("red60_prob"),
                    "red_lead_median": s.get("red_lead_median"),
                })

    sequences = {
        "F1_WARN": {
            "full": sequence_stats(event_dates["F1_WARN"], {"F2_WARN": f2w, "F3_SEVERE": f3s, "TEMP_LE10": temp_low}),
            "discovery": sequence_stats(event_dates["F1_WARN"], {"F2_WARN": f2w, "F3_SEVERE": f3s, "TEMP_LE10": temp_low}, split_end=DISC_END),
            "confirmation": sequence_stats(event_dates["F1_WARN"], {"F2_WARN": f2w, "F3_SEVERE": f3s, "TEMP_LE10": temp_low}, split_start=CONF_START),
        },
        "F2_WARN": {
            "full": sequence_stats(event_dates["F2_WARN"], {"F3_SEVERE": f3s, "TEMP_LE10": temp_low}),
            "discovery": sequence_stats(event_dates["F2_WARN"], {"F3_SEVERE": f3s, "TEMP_LE10": temp_low}, split_end=DISC_END),
            "confirmation": sequence_stats(event_dates["F2_WARN"], {"F3_SEVERE": f3s, "TEMP_LE10": temp_low}, split_start=CONF_START),
        },
        "F3_SEVERE": {
            "full": sequence_stats(event_dates["F3_SEVERE"], {"TEMP_LE10": temp_low}),
            "discovery": sequence_stats(event_dates["F3_SEVERE"], {"TEMP_LE10": temp_low}, split_end=DISC_END),
            "confirmation": sequence_stats(event_dates["F3_SEVERE"], {"TEMP_LE10": temp_low}, split_start=CONF_START),
        },
    }

    last = sig.dropna(how="all").index.max()
    current = {
        "asof": last,
        "f1": sig.at[last, "f1"] if last in sig.index else None,
        "f1_coverage": sig.at[last, "f1_coverage"] if last in sig.index else None,
        "f2": sig.at[last, "f2"] if last in sig.index else None,
        "f3": sig.at[last, "f3"] if last in sig.index else None,
        "leader_temp": sig.at[last, "leader_temp"] if last in sig.index else None,
        "run_fade_share": sig.at[last, "run_fade_share"] if last in sig.index else None,
        "run_acc_share": sig.at[last, "run_acc_share"] if last in sig.index else None,
        "run_health": sig.at[last, "run_health"] if last in sig.index else None,
        "breadth50": breadth.get(last),
        "nqsar": nq_color.get(last),
    }

    events_df = pd.concat(all_event_frames, ignore_index=True) if all_event_frames else pd.DataFrame()
    sensitivity_df = pd.DataFrame(sensitivity_rows)
    sig.to_csv(out / "leadership_series.csv")
    events_df.to_csv(out / "events_outcomes.csv", index=False)
    sensitivity_df.to_csv(out / "threshold_sensitivity.csv", index=False)

    result = {
        "status": "LEADERSHIP_CYCLE_PIT_EVENT_STUDY",
        "scope": "F1/F2/F3 + Leader Temperature + Momentum Run + NQSAR/Breadth interactions; no production/main/dashboard changes",
        "method": {
            "analysis_start": args.analysis_start,
            "analysis_end": args.analysis_end,
            "discovery_end": str(DISC_END.date()),
            "confirmation_start": str(CONF_START.date()),
            "eventization": f"false->true transition, {COOLDOWN}-session cooldown",
            "horizons": list(HORIZONS),
            "pit_temperature": "504-session trailing percentile only; no full-sample rank",
            "f1_missingness": "unknown excluded from numerator; coverage<70% invalid",
            "baseline": "every 20th analysis session",
            "warning": "current-universe survivorship remains; confirmation is robustness split, not pristine prospective OOS",
        },
        "coverage": {
            "selected": meta.get("selected"), "downloaded": meta.get("downloaded"),
            "analysis_sessions": len(idx), "download": meta.get("download"),
        },
        "current": current,
        "summaries": summaries,
        "comparisons_vs_baseline": comparisons,
        "sequences": sequences,
        "sensitivity_file": "threshold_sensitivity.csv",
        "events_file": "events_outcomes.csv",
        "series_file": "leadership_series.csv",
    }
    (out / "summary.json").write_text(json.dumps(safe(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== LEADERSHIP_CYCLE_RESULT ===", flush=True)
    print(json.dumps(safe(result), ensure_ascii=False, indent=2), flush=True)
    print("=== END_LEADERSHIP_CYCLE_RESULT ===", flush=True)


if __name__ == "__main__":
    main()
