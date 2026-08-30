#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

from research import tqqq_backtest_once as bt
from tqqq_live_engine import build_4h_bars, current30_trace, stage56_overlay

START = pd.Timestamp("2011-01-03")


def psar(h, l, step=.02, mx=.08):
    h = np.asarray(h, float); l = np.asarray(l, float); n = len(h)
    s = np.zeros(n); bull = True; af = step; ep = l[0]; s[0] = l[0]
    for i in range(1, n):
        s[i] = s[i - 1] + af * (ep - s[i - 1])
        if bull:
            if l[i] < s[i]: bull = False; s[i] = ep; ep = l[i]; af = step
            elif h[i] > ep: ep = h[i]; af = min(af + step, mx)
        else:
            if h[i] > s[i]: bull = True; s[i] = ep; ep = h[i]; af = step
            elif l[i] < ep: ep = l[i]; af = min(af + step, mx)
    return s


def daily_rsi(c, n=14):
    x = pd.Series(c, dtype=float); d = x.diff(); u = d.clip(lower=0); dn = (-d).clip(lower=0)
    au = u.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    ad = dn.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = au / ad.replace(0, np.nan)
    y = 100 - 100 / (1 + rs)
    return y.where(ad.ne(0), 100.0).to_numpy()


def nq_colors(nq: pd.DataFrame) -> pd.Series:
    c = nq.Close.astype(float).to_numpy(); h = nq.High.astype(float).to_numpy(); l = nq.Low.astype(float).to_numpy()
    s = psar(h, l); e = pd.Series(c, index=nq.index).ewm(span=21, adjust=False).mean().to_numpy(); r = daily_rsi(c)
    above = c > s; state = "Green" if above[0] else "Yellow"; up = dn = 99; prev = None; out = []
    for i in range(len(c)):
        up = 0 if i > 0 and above[i] and not above[i - 1] else up + 1
        dn = 0 if i > 0 and (not above[i]) and above[i - 1] else dn + 1
        ri = float(r[i]) if np.isfinite(r[i]) else 50.0; dr = ri - prev if prev is not None else 0.0
        if above[i]:
            if state == "Blue": state = "Green" if c[i] < e[i] else "Blue"
            else: state = "Blue" if ri > 52 and up >= 2 and dr <= 3 else "Green"
        else:
            if state == "Red": state = "Yellow" if ri > 50 else "Red"
            else: state = "Red" if ri < 47 and dn >= 2 and dr >= -3 else "Yellow"
        prev = ri; out.append(state)
    return pd.Series(out, index=nq.index, dtype="object")


def build_daily_inputs() -> tuple[pd.DataFrame, dict[str, np.ndarray], pd.Series, pd.Series, dict]:
    qqq = bt.dl_one("QQQ", "2009-01-01")
    tq = bt.dl_one("TQQQ", "2010-01-01")
    nqraw = bt.dl_one("NQ=F", "2000-01-01")
    vix = bt.dl_one("^VIX", "1990-01-01")
    mc, mc_cov = bt.compute_mc()
    vix_state, _ = bt.vix_state_series(vix)
    nq = nq_colors(nqraw)

    c = qqq.Close.astype(float); h = qqq.High.astype(float); l = qqq.Low.astype(float); v = qqq.Volume.astype(float); pc = c.shift(1)
    tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    e10 = c.ewm(span=10, adjust=False).mean(); e21 = c.ewm(span=21, adjust=False).mean()
    s50 = c.rolling(50).mean(); s200 = c.rolling(200).mean()
    tp = (h + l + c) / 3
    v63 = (tp * v).rolling(63).sum() / v.rolling(63).sum()
    v252 = (tp * v).rolling(252, min_periods=200).sum() / v.rolling(252, min_periods=200).sum()
    s50a = (c - s50) / atr
    dd10 = c / c.rolling(10, min_periods=2).max() - 1

    idx = qqq.index.intersection(tq.index); idx = idx[idx >= START]
    f = pd.DataFrame(index=idx); f["date"] = idx
    f["mc"] = mc.reindex(idx).ffill(); f["mc_cov"] = mc_cov.reindex(idx).ffill()
    f["nq"] = nq.reindex(idx).ffill(); f["panic"] = vix_state.reindex(idx).ffill().astype(str).isin(["BOTTOM", "RE-EXTREME"])
    f["a50"] = (c > s50).reindex(idx); f["a63"] = (c > v63).reindex(idx); f["a200"] = (c > s200).reindex(idx); f["a252"] = (c > v252).reindex(idx)
    f["gte10"] = (c > e10).reindex(idx); f["lte21"] = (c < e21).reindex(idx); f["s50a"] = s50a.reindex(idx); f["dd10"] = dd10.reindex(idx)
    f["vix_close"] = vix.Close.astype(float).reindex(idx).ffill()
    f = f.dropna().reset_index(drop=True)
    mp = {"Red": 0, "Yellow": 1, "Green": 2, "Blue": 3}
    f["nq_i"] = np.array([mp.get(str(x), 1) for x in f.nq], dtype=np.int8)
    b = {
        "mc": f.mc.to_numpy(float), "nq": f.nq_i.to_numpy(np.int8), "panic": f.panic.to_numpy(bool),
        "a50": f.a50.to_numpy(bool), "a63": f.a63.to_numpy(bool), "a200": f.a200.to_numpy(bool), "a252": f.a252.to_numpy(bool),
        "gte10": f.gte10.to_numpy(bool), "lte21": f.lte21.to_numpy(bool), "s50a": f.s50a.to_numpy(float), "dd10": f.dd10.to_numpy(float),
    }
    diagnostics = {"mc_coverage_latest": float(f.mc_cov.iloc[-1]), "daily_rows": len(f)}
    return f, b, f.vix_close, f.nq, diagnostics


def download_qqq_5m() -> pd.DataFrame:
    raw = yf.download("QQQ", period="60d", interval="5m", auto_adjust=False, actions=False, progress=False, threads=False)
    raw = bt._plain(raw)
    need = ["Open", "High", "Low", "Close"]
    if raw is None or raw.empty or any(c not in raw.columns for c in need):
        raise RuntimeError("QQQ 5m data unavailable")
    return raw[need].dropna()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path("tqqq-panic-state.json"))
    args = ap.parse_args()

    f, b, vix_close, nq_text, diag = build_daily_inputs()
    current = current30_trace(b)
    bars = build_4h_bars(download_qqq_5m())
    if bars.empty:
        raise RuntimeError("No valid QQQ 4H bars")
    touch_day = bars.groupby("date").touch30.max().astype(bool)
    dates = pd.DatetimeIndex(pd.to_datetime(f.date)).tz_localize(None).normalize()
    touch = touch_day.reindex(dates).fillna(False).to_numpy(bool)
    overlay = stage56_overlay(b, vix_close.to_numpy(float), touch, underlying=current["target"])

    i = len(f) - 1
    asof = str(pd.Timestamp(f.date.iloc[i]).date())
    latest_intraday_date = str(pd.Timestamp(bars.date.iloc[-1]).date())
    intraday_current = latest_intraday_date == asof
    latest_bars = bars[bars.date == pd.Timestamp(asof)] if intraday_current else pd.DataFrame()
    if not latest_bars.empty and bool(latest_bars.touch30.any()):
        touch_idx = int(latest_bars[latest_bars.touch30].index[-1])
        rsi_idx = touch_idx
    else:
        rsi_idx = int(bars.index[-1])
    rsi4h = float(bars.loc[rsi_idx, "rsi14"]) if np.isfinite(bars.loc[rsi_idx, "rsi14"]) else None
    prior_rsi4h = None
    if rsi_idx > 0 and np.isfinite(bars.loc[rsi_idx - 1, "rsi14"]):
        prior_rsi4h = float(bars.loc[rsi_idx - 1, "rsi14"])

    active_at_open = bool(overlay["active_at_open"][i])
    active_after_close = bool(overlay["active_after_close"][i])
    entered = bool(overlay["entered_close"][i])
    exited = bool(overlay["exited_close"][i])
    underlying_pct = float(current["target"][i] * 100.0)
    requested_pct = float(overlay["target"][i] * 100.0)
    seed_age_raw = int(overlay["seed_age"][i])
    seed_age = seed_age_raw if seed_age_raw <= 1_000_000 else None

    status = "LIVE" if intraday_current else "4H_DATA_STALE"
    out = {
        "schema": "v38-tqqq-panic-state-1",
        "status": status,
        "asof": asof,
        "strategy": "M30_TOUCH30_F80_D10",
        "source": {
            "daily": "Yahoo Finance adjusted daily; Stage16/34 formulas",
            "mc57": "build_dashboard.mri_frame via research.tqqq_backtest_once.compute_mc",
            "nqsar": "NQ=F reconstructed Stage16 PSAR/EMA21/RSI state",
            "vix_sequence": "production VIX state machine via tqqq_backtest_once.vix_state_series",
            "intraday": "Yahoo Finance QQQ 5m; Stage51 RTH 09:30-13:30 + 13:30-16:00 bars",
        },
        "vix_close": float(f.vix_close.iloc[i]),
        "qqq_sma50_atr_deviation": float(f.s50a.iloc[i]),
        "qqq_drawdown10": float(f.dd10.iloc[i]),
        "seed_today": bool(overlay["seed"][i]),
        "seed_age_sessions": seed_age,
        "rsi4h": rsi4h if intraday_current else None,
        "prior_rsi4h": prior_rsi4h if intraday_current else None,
        "touch30_today": bool(latest_bars.touch30.any()) if intraday_current and not latest_bars.empty else None,
        "mc57": float(f.mc.iloc[i]),
        "nqsar": str(nq_text.iloc[i]),
        "active": active_at_open,
        "active_after_close": active_after_close,
        "entry_pending_next_open": entered,
        "exit_pending_next_open": exited and active_at_open,
        "held_sessions": int(max(0, overlay["held_signal_sessions"][i])) if overlay["held_signal_sessions"][i] >= 0 else 0,
        "underlying_target_pct": underlying_pct,
        "panic_requested_target_pct": requested_pct,
        "other_sleeve_exposure_pct": None,
        "allocation_priority": "NOT REPRODUCED",
        "current30": {
            "risklock": bool(current["risklock"][i]),
            "slow_lock": bool(current["slow_lock"][i]),
            "fast_lock": bool(current["fast_lock"][i]),
            "mc_lock": bool(current["mc_lock"][i]),
            "sleeve": int(current["sleeve"][i]),
            "strong": bool(current["strong"][i]),
        },
        "intraday": {
            "latest_date": latest_intraday_date,
            "bars4h": int(len(bars)),
            "current_for_daily_asof": intraday_current,
        },
        "diagnostics": diag,
    }
    args.output.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("asof", "status", "vix_close", "qqq_sma50_atr_deviation", "qqq_drawdown10", "seed_age_sessions", "rsi4h", "prior_rsi4h", "mc57", "nqsar", "active", "entry_pending_next_open", "exit_pending_next_open", "underlying_target_pct", "panic_requested_target_pct")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
