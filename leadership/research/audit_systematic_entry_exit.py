from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

import audit_rsi_reset_robust as market_base
import audit_market_rs189_context as ctx
import audit_rsi30_mc_nqsar as state_audit
import validate_rsi_divergence_strong as rsi_base
import validate_post_ignition_leaders as post

COST = 5.0 / 10000.0
DISC_END = pd.Timestamp("2021-12-31")
CONF_START = pd.Timestamp("2022-01-03")


def safe(x):
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


def pf(x):
    s = pd.to_numeric(pd.Series(x), errors="coerce").dropna()
    if s.empty:
        return None
    gp = float(s[s > 0].sum())
    gl = float(-s[s < 0].sum())
    return None if gl <= 0 else gp / gl


def period_of(d):
    d = pd.Timestamp(d)
    return "DISCOVERY" if d <= DISC_END else "CONFIRM"


def cluster_ci(rows, calendar, reps=1500, seed=1234):
    if rows.empty:
        return [None, None]
    pos = pd.Series(np.arange(len(calendar)), index=calendar)
    d = pd.to_datetime(rows["entry_date"])
    p = pos.reindex(d).to_numpy(float)
    ok = np.isfinite(p) & pd.to_numeric(rows["ret"], errors="coerce").notna().to_numpy()
    if ok.sum() < 2:
        return [None, None]
    z = rows.loc[ok].copy()
    z["block20"] = np.floor(p[ok] / 20).astype(int)
    a = z.groupby("block20", observed=True)["ret"].mean().to_numpy(float)
    if len(a) < 2:
        return [None, None]
    rng = np.random.default_rng(seed)
    boot = rng.choice(a, size=(reps, len(a)), replace=True).mean(axis=1)
    q = np.quantile(boot, [0.025, 0.975])
    return [float(q[0]), float(q[1])]


def summarize(g, calendar, seed=100):
    if g.empty:
        return {"n": 0}
    r = pd.to_numeric(g["ret"], errors="coerce").dropna()
    if r.empty:
        return {"n": 0}
    z = g.loc[r.index]
    top5 = r.quantile(0.95)
    trimmed = r[r <= top5]
    runner = z[pd.to_numeric(z.get("mfe40", np.nan), errors="coerce") >= 0.30] if "mfe40" in z else z.iloc[:0]
    avg_hold = float(pd.to_numeric(z["hold_days"], errors="coerce").mean())
    return {
        "n": int(len(r)),
        "signal_dates": int(pd.to_datetime(z["entry_date"]).nunique()),
        "symbols": int(z["symbol"].nunique()),
        "mean": float(r.mean()),
        "median": float(r.median()),
        "win": float((r > 0).mean()),
        "pf": pf(r),
        "p10": float(r.quantile(0.10)),
        "p05": float(r.quantile(0.05)),
        "avg_hold": avg_hold,
        "median_hold": float(pd.to_numeric(z["hold_days"], errors="coerce").median()),
        "return_per_20_slot_days": float(r.mean() / max(avg_hold, 1.0) * 20.0),
        "top5_removed_mean": float(trimmed.mean()) if len(trimmed) else None,
        "top5_removed_pf": pf(trimmed),
        "runner_n": int(len(runner)),
        "runner_mean_realized": float(pd.to_numeric(runner["ret"], errors="coerce").mean()) if len(runner) else None,
        "runner_median_realized": float(pd.to_numeric(runner["ret"], errors="coerce").median()) if len(runner) else None,
        "block20_ci95": cluster_ci(z, calendar, seed=seed),
    }


def price_at(df, d, s):
    if d not in df.index or s not in df.columns:
        return np.nan
    v = df.at[d, s]
    return float(v) if pd.notna(v) else np.nan


def exit_one(entry_date, sym, op, cl, hi, atr, ema10, ema21, exit_name, max_hold=60):
    if entry_date not in cl.index or sym not in cl.columns:
        return None
    ei = cl.index.get_loc(entry_date)
    ep = price_at(op, entry_date, sym)
    if not np.isfinite(ep) or ep <= 0:
        return None
    end = min(ei + max_hold, len(cl.index) - 1)
    buy_basis = ep * (1 + COST)
    h40_end = min(ei + 40, len(cl.index) - 1)
    hs = pd.to_numeric(hi[sym].iloc[ei:h40_end + 1], errors="coerce").dropna()
    mfe40 = float(hs.max() / ep - 1) if len(hs) else np.nan
    sold_frac = 0.0
    proceeds = 0.0
    partial_done = False
    fast20 = False
    peak_close = ep

    def sell(frac, px):
        nonlocal sold_frac, proceeds
        proceeds += frac * px * (1 - COST)
        sold_frac += frac

    if exit_name in {"FIX20", "FIX40"}:
        days = 20 if exit_name == "FIX20" else 40
        xi = min(ei + days, len(cl.index) - 1)
        px = price_at(op, cl.index[xi], sym)
        if not np.isfinite(px):
            px = price_at(cl, cl.index[xi - 1 if xi > ei else xi], sym)
        if not np.isfinite(px):
            return None
        sell(1.0, px)
        return {"ret": proceeds / buy_basis - 1, "exit_date": cl.index[xi], "hold_days": xi - ei, "mfe40": mfe40}

    for i in range(ei, end + 1):
        d = cl.index[i]
        c = price_at(cl, d, sym)
        if not np.isfinite(c):
            continue
        peak_close = max(peak_close, c)
        day = i - ei
        if day <= 15 and c / ep - 1 >= 0.20:
            fast20 = True
        if exit_name == "P25_AT20_EMA10" and (not partial_done) and c / ep - 1 >= 0.20 and i + 1 <= end:
            px = price_at(op, cl.index[i + 1], sym)
            if np.isfinite(px):
                sell(0.25, px)
                partial_done = True
        if day >= 1 and i + 1 <= end:
            do_exit = False
            if exit_name in {"EMA10", "P25_AT20_EMA10"}:
                ma = price_at(ema10, d, sym)
                do_exit = np.isfinite(ma) and c < ma
            elif exit_name == "EMA21":
                ma = price_at(ema21, d, sym)
                do_exit = np.isfinite(ma) and c < ma
            elif exit_name == "ATR3":
                a = price_at(atr, d, sym)
                do_exit = np.isfinite(a) and c < peak_close - 3.0 * a
            elif exit_name == "FAST20_EXTEND21":
                if day >= 19 and not fast20:
                    do_exit = True
                elif fast20:
                    ma = price_at(ema21, d, sym)
                    do_exit = np.isfinite(ma) and c < ma
            if do_exit:
                px = price_at(op, cl.index[i + 1], sym)
                if np.isfinite(px):
                    rem = 1.0 - sold_frac
                    if rem > 1e-12:
                        sell(rem, px)
                    return {"ret": proceeds / buy_basis - 1, "exit_date": cl.index[i + 1], "hold_days": i + 1 - ei, "mfe40": mfe40}
        if exit_name == "FAST20_EXTEND21" and day >= 39:
            xi = min(i + 1, len(cl.index) - 1)
            px = price_at(op, cl.index[xi], sym)
            if not np.isfinite(px):
                px = c
            rem = 1.0 - sold_frac
            sell(rem, px)
            return {"ret": proceeds / buy_basis - 1, "exit_date": cl.index[xi], "hold_days": xi - ei, "mfe40": mfe40}
    xi = end
    px = price_at(op, cl.index[xi], sym)
    if not np.isfinite(px):
        px = price_at(cl, cl.index[xi], sym)
    if not np.isfinite(px):
        return None
    rem = 1.0 - sold_frac
    if rem > 1e-12:
        sell(rem, px)
    return {"ret": proceeds / buy_basis - 1, "exit_date": cl.index[xi], "hold_days": xi - ei, "mfe40": mfe40}


def qqq_state(start, end):
    ohlcv, diag = post.rtv2.download_ohlcvo(["QQQ"], start, end, 10)
    q = ohlcv["close"]["QQQ"].dropna()
    return q, diag


def build_market_states(root, start, end, asof):
    market = market_base.rebuild_market(root, start, end, 6000, 75, 3)
    cl, op, hi, lo = market["close"], market["open"], market["high"], market["low"]
    prev = cl.shift(1)
    tr = (hi - lo).combine((hi - prev).abs(), np.maximum).combine((lo - prev).abs(), np.maximum)
    atr = tr.rolling(14, min_periods=14).mean()
    ema10 = cl.ewm(span=10, adjust=False).mean()
    ema21 = cl.ewm(span=21, adjust=False).mean()
    ema50 = cl.ewm(span=50, adjust=False).mean()
    rsi = rsi_base.rsi(cl, 14)
    age = cl.notna().cumsum()
    r63 = cl.pct_change(63, fill_method=None)
    r189 = cl.pct_change(189, fill_method=None)
    rs63 = r63.rank(axis=1, pct=True, method="average") * 100
    rs189 = r189.rank(axis=1, pct=True, method="average") * 100
    sec_pct, _breadth, sec_map = ctx.build_sector_state(cl, root)
    mc = state_audit.build_mc(asof).mc.reindex(cl.index)
    return {"market": market, "cl": cl, "op": op, "hi": hi, "lo": lo, "atr": atr, "ema10": ema10, "ema21": ema21, "ema50": ema50, "rsi": rsi, "age": age, "rs63": rs63, "rs189": rs189, "sec_pct": sec_pct, "sec_map": sec_map, "mc": mc}


def shallow_exit_audit(trades, st, qqq):
    cl, op, hi, atr, ema10, ema21, mc = st["cl"], st["op"], st["hi"], st["atr"], st["ema10"], st["ema21"], st["mc"]
    qema21 = qqq.ewm(span=21, adjust=False).mean()
    rows = []
    base = trades.copy()
    base["signal_date"] = pd.to_datetime(base["signal_date"])
    base["entry_date"] = pd.to_datetime(base["entry_date"])
    base = base[(base["cohort"] == "MATURE") & (base["liquid"] == True) & (pd.to_numeric(base["sector_signal"], errors="coerce") >= 70) & (base["method"].isin(["NOW", "M5_RSI65_DD050", "M10_RSI65_DD075"])) & (base["mc_band"].astype(str).isin(["50_65", "65_80"]))].copy()
    base["mc5_ge50"] = base["signal_date"].map(lambda d: bool(len(mc.loc[:d].tail(5)) == 5 and (mc.loc[:d].tail(5) >= 50).all()) if d in mc.index else False)
    base["qqq_gt21"] = base["signal_date"].map(lambda d: bool(d in qqq.index and d in qema21.index and qqq.at[d] > qema21.at[d]) if d in qqq.index else False)
    exits = ["FIX20", "FIX40", "EMA10", "EMA21", "ATR3", "P25_AT20_EMA10", "FAST20_EXTEND21"]
    for r in base.itertuples(index=False):
        for ex in exits:
            o = exit_one(pd.Timestamp(r.entry_date), r.symbol, op, cl, hi, atr, ema10, ema21, ex)
            if not o:
                continue
            rows.append({"episode_id": r.episode_id, "symbol": r.symbol, "sector": r.sector, "method": r.method, "period": r.period, "mc_band": str(r.mc_band), "delay": int(r.delay), "signal_date": pd.Timestamp(r.signal_date), "entry_date": pd.Timestamp(r.entry_date), "mc5_ge50": bool(r.mc5_ge50), "qqq_gt21": bool(r.qqq_gt21), "exit": ex, **o})
    out = pd.DataFrame(rows)
    sums = []
    seed = 1000
    for period in ["DISCOVERY", "CONFIRM"]:
        p = out[out.period == period]
        for band in ["50_65", "65_80"]:
            q = p[p.mc_band == band]
            for method in ["NOW", "M5_RSI65_DD050", "M10_RSI65_DD075"]:
                m = q[q.method == method]
                for delay_cap in ["ALL", "5"]:
                    md = m if delay_cap == "ALL" or method == "NOW" else m[m.delay <= 5]
                    for context in ["BASE", "MC5", "QQQ21", "BOTH"]:
                        c = md
                        if context in {"MC5", "BOTH"}:
                            c = c[c.mc5_ge50]
                        if context in {"QQQ21", "BOTH"}:
                            c = c[c.qqq_gt21]
                        for ex, g in c.groupby("exit", observed=True):
                            if len(g) < 20:
                                continue
                            sums.append({"period": period, "mc_band": band, "method": method, "delay_cap": delay_cap, "context": context, "exit": ex, **summarize(g, cl.index, seed=seed)})
                            seed += 1
    return out, pd.DataFrame(sums)


def correction_signals(st):
    cl, hi, lo, atr = st["cl"], st["hi"], st["lo"], st["atr"]
    ema10, ema21, ema50, rsi = st["ema10"], st["ema21"], st["ema50"], st["rsi"]
    age, rs63, rs189, sec_pct, sec_map, mc = st["age"], st["rs63"], st["rs189"], st["sec_pct"], st["sec_map"], st["mc"]
    high10 = hi.rolling(10, min_periods=5).max()
    rows = []
    for k, sym in enumerate(cl.columns, start=1):
        sec = sec_map.get(sym, "UNMAPPED")
        if sec not in sec_pct.columns:
            continue
        sp = sec_pct[sec].reindex(cl.index)
        c, rr, a = cl[sym], rsi[sym], atr[sym]
        rise = rr > rr.shift(1)
        strong = (age[sym] >= 189) & (rs189[sym] >= 85) & (rs63[sym] >= 80) & (sp >= 70) & (ema21[sym] > ema50[sym]) & (c > ema50[sym]) & (mc >= 35) & (mc < 50)
        dd = (high10[sym] - lo[sym]) / a
        methods = {"CORR_M10_RSI60": (ema10[sym], 60.0, 0.75), "CORR_M21_RSI55": (ema21[sym], 55.0, 1.00)}
        last = {m: -999 for m in methods}
        for method, (ma, rthr, dathr) in methods.items():
            touch = strong & (rr <= rthr) & (lo[sym] <= ma + 0.25 * a) & (dd >= dathr)
            sig = strong & rise & (c >= ma)
            for ti in np.flatnonzero(touch.fillna(False).to_numpy()):
                if ti - last[method] < 20:
                    continue
                found = None
                for sj in range(ti, min(ti + 4, len(cl.index) - 2) + 1):
                    if bool(sig.iat[sj]):
                        found = sj
                        break
                if found is None or found + 1 >= len(cl.index):
                    continue
                rows.append({"symbol": sym, "sector": sec, "method": method, "signal_date": cl.index[found], "entry_date": cl.index[found + 1], "mc_signal": float(mc.iat[found]), "sector_signal": float(sp.iat[found]), "rs63_signal": float(rs63[sym].iat[found]), "rs189_signal": float(rs189[sym].iat[found]), "rsi_signal": float(rr.iat[found]), "delay_touch_to_signal": int(found - ti)})
                last[method] = found
        if k % 500 == 0:
            print(f"CORRECTION_SCAN {k}/{len(cl.columns)}", flush=True)
    return pd.DataFrame(rows)


def add_liquidity(signals, st):
    if signals.empty:
        return signals, {}
    syms = sorted(signals.symbol.unique())
    start = str((pd.to_datetime(signals.signal_date).min() - pd.Timedelta(days=60)).date())
    end = str((pd.to_datetime(signals.signal_date).max() + pd.Timedelta(days=5)).date())
    ohlcv, diag = post.rtv2.download_ohlcvo(syms, start, end, 75)
    vol = ohlcv.get("volume", pd.DataFrame())
    avgvol = vol.rolling(20, min_periods=15).mean()
    adr = ((st["hi"] - st["lo"]) / st["cl"].replace(0, np.nan) * 100).rolling(20, min_periods=15).mean()
    price, av, ad = [], [], []
    for r in signals.itertuples(index=False):
        d, s = pd.Timestamp(r.signal_date), r.symbol
        price.append(price_at(st["cl"], d, s))
        av.append(price_at(avgvol, d, s))
        ad.append(price_at(adr, d, s))
    z = signals.copy()
    z["price_signal"], z["avgvol20"], z["adr20_pct"] = price, av, ad
    z["liquid"] = (z.price_signal >= 5) & (z.avgvol20 >= 1_000_000) & z.adr20_pct.between(3, 15, inclusive="both")
    return z, diag


def correction_exit_audit(signals, st):
    if signals.empty:
        return pd.DataFrame(), pd.DataFrame()
    rows = []
    for r in signals[signals.liquid].itertuples(index=False):
        for ex in ["FIX20", "EMA10", "EMA21", "FAST20_EXTEND21"]:
            o = exit_one(pd.Timestamp(r.entry_date), r.symbol, st["op"], st["cl"], st["hi"], st["atr"], st["ema10"], st["ema21"], ex)
            if o:
                rows.append({"symbol": r.symbol, "sector": r.sector, "method": r.method, "period": period_of(r.signal_date), "signal_date": pd.Timestamp(r.signal_date), "entry_date": pd.Timestamp(r.entry_date), "exit": ex, **o})
    rows = pd.DataFrame(rows)
    sums = []
    seed = 5000
    for period in ["DISCOVERY", "CONFIRM"]:
        p = rows[rows.period == period]
        for method in ["CORR_M10_RSI60", "CORR_M21_RSI55"]:
            q = p[p.method == method]
            for ex, g in q.groupby("exit", observed=True):
                if len(g) < 20:
                    continue
                sums.append({"period": period, "method": method, "exit": ex, **summarize(g, st["cl"].index, seed)})
                seed += 1
    return rows, pd.DataFrame(sums)


def deep_handoff_audit(threshold_rows, st):
    z = threshold_rows.copy()
    z["signal_date"] = pd.to_datetime(z["signal_date"])
    z["entry_date"] = pd.to_datetime(z["entry_date"])
    z = z[(z["kind"] == "RISE") & (z["threshold"] == 30) & (z["RS63_TOP3"] == True) & (z["signal_top3"] == True)].drop_duplicates("candidate_key").copy()
    cl, op, hi, ema10, ema21, active = st["cl"], st["op"], st["hi"], st["ema10"], st["ema21"], st["market"]["active"]
    rows = []
    for r in z.itertuples(index=False):
        if r.entry_date not in cl.index or r.symbol not in cl.columns:
            continue
        ei = cl.index.get_loc(pd.Timestamp(r.entry_date))
        ep = price_at(op, pd.Timestamp(r.entry_date), r.symbol)
        if not np.isfinite(ep) or ep <= 0:
            continue
        for ex in ["FIX20", "HANDOFF10_MAX40", "HANDOFF21_MAX40", "FAST20_EXTEND21"]:
            if ex == "FIX20":
                o = exit_one(pd.Timestamp(r.entry_date), r.symbol, op, cl, hi, st["atr"], ema10, ema21, "FIX20")
            elif ex == "FAST20_EXTEND21":
                o = exit_one(pd.Timestamp(r.entry_date), r.symbol, op, cl, hi, st["atr"], ema10, ema21, "FAST20_EXTEND21")
            else:
                d19i = min(ei + 19, len(cl.index) - 1)
                d19 = cl.index[d19i]
                c19 = price_at(cl, d19, r.symbol)
                ma_df = ema10 if ex == "HANDOFF10_MAX40" else ema21
                ma = price_at(ma_df, d19, r.symbol)
                theme_ok = bool(r.theme in active.columns and d19 in active.index and active.at[d19, r.theme])
                if np.isfinite(c19) and np.isfinite(ma) and c19 > ma and theme_ok:
                    buy_basis = ep * (1 + COST)
                    h40_end = min(ei + 40, len(cl.index) - 1)
                    hs = pd.to_numeric(hi[r.symbol].iloc[ei:h40_end + 1], errors="coerce").dropna()
                    mfe40 = float(hs.max() / ep - 1) if len(hs) else np.nan
                    o = None
                    for i in range(ei + 20, min(ei + 40, len(cl.index) - 2) + 1):
                        c = price_at(cl, cl.index[i], r.symbol)
                        m = price_at(ma_df, cl.index[i], r.symbol)
                        theme_now = bool(r.theme in active.columns and active.at[cl.index[i], r.theme])
                        if np.isfinite(c) and np.isfinite(m) and (c < m or not theme_now):
                            px = price_at(op, cl.index[i + 1], r.symbol)
                            if np.isfinite(px):
                                o = {"ret": px * (1 - COST) / buy_basis - 1, "exit_date": cl.index[i + 1], "hold_days": i + 1 - ei, "mfe40": mfe40}
                                break
                    if o is None:
                        xi = min(ei + 40, len(cl.index) - 1)
                        px = price_at(op, cl.index[xi], r.symbol)
                        if np.isfinite(px):
                            o = {"ret": px * (1 - COST) / buy_basis - 1, "exit_date": cl.index[xi], "hold_days": xi - ei, "mfe40": mfe40}
                else:
                    o = exit_one(pd.Timestamp(r.entry_date), r.symbol, op, cl, hi, st["atr"], ema10, ema21, "FIX20")
            if o:
                rows.append({"candidate_key": r.candidate_key, "symbol": r.symbol, "theme": r.theme, "period": period_of(r.signal_date), "signal_date": pd.Timestamp(r.signal_date), "entry_date": pd.Timestamp(r.entry_date), "exit": ex, **o})
    rows = pd.DataFrame(rows)
    sums = []
    seed = 7000
    for period in ["DISCOVERY", "CONFIRM"]:
        p = rows[rows.period == period]
        for ex, g in p.groupby("exit", observed=True):
            sums.append({"period": period, "exit": ex, **summarize(g, cl.index, seed)})
            seed += 1
    return rows, pd.DataFrame(sums)


def inventory():
    rows = [
        ("RSI30_THEME", "RSI threshold 25/30/35/40/45/50 touch/rise families", "DONE", "RSI30 first rise preferred; RSI35+ rejected; RSI25 too sparse/deep"),
        ("RSI30_THEME", "RS63 Top1/Top3, dual RS63/189, dual outperform, signal top3", "DONE", "RS63 Top3 + signal-day Top3 preferred; Top1/dual variants not better"),
        ("RSI30_THEME", "divergence / hidden divergence / reacceleration", "DONE", "Rejected"),
        ("RSI30_THEME", "volume/VCP/VWAP extras", "DONE", "Rejected / no robust gain"),
        ("RSI30_THEME", "hold 10/20/40", "DONE", "20 sessions preferred"),
        ("RSI30_THEME", "full vs tranche", "DONE", "Full preferred"),
        ("RSI30_THEME", "fixed -8% stop", "DONE", "Rejected"),
        ("RSI30_THEME", "MC57/NQSAR/VIX level hard entry gates", "DONE", "Rejected as signal gates"),
        ("RSI30_THEME", "VIX Sequence EVENT/ROLLOVER block on new entries", "DONE", "Integrated risk overlay improves sleeve DD"),
        ("MARKET_RS189", "RS189 percentile 80/85/90/95/99 x RSI30/35/40", "DONE", "85 + RSI30 best stable, but shadow/supplement only"),
        ("SHALLOW_MC50PLUS", "NOW vs 5EMA/10EMA/21EMA and RSI55/60/65", "DONE", "Waiting does not automatically reduce MAE; 5EMA/RSI65 is only live shallow candidate"),
        ("SHALLOW_MC50PLUS", "touch-low -0.25ATR defined-risk stop, risk cap 5/8%", "DONE", "Rejected: stop-hit too high, many eventual winners stopped"),
        ("TQQQ", "30->80/100, touch vs rise, D10 vs EMA21 early exit", "DONE", "80 floor + RSI30 touch + D10; 100 rejected; EMA21 early exit not robust"),
        ("CURRENT_AUDIT", "profit-taking/trend exits for shallow entries", "NEW", "This audit"),
        ("CURRENT_AUDIT", "MC35-50 exact standard-pullback split", "NEW", "Prior 20-50 bucket mixed recovery and correction"),
        ("CURRENT_AUDIT", "RSI30 day20 trend handoff extension", "NEW", "Prior handoff was descriptive only"),
        ("CURRENT_AUDIT", "MC>=50 persistence / QQQ>21EMA context on shallow entry", "NEW", "Not previously isolated"),
    ]
    return pd.DataFrame(rows, columns=["area", "test", "status", "prior_conclusion"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--shallow", required=True)
    ap.add_argument("--threshold", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--start", default="2016-01-04")
    ap.add_argument("--end", default="2026-06-30")
    ap.add_argument("--asof", default="2026-08-28")
    args = ap.parse_args()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    inventory().to_csv(out / "tested_inventory.csv", index=False)
    st = build_market_states(Path(args.root), args.start, args.end, args.asof)
    qqq, qdiag = qqq_state(args.start, args.end)
    shallow = pd.read_csv(args.shallow, compression="gzip")
    sh_rows, sh_sum = shallow_exit_audit(shallow, st, qqq)
    sh_rows.to_csv(out / "shallow_exit_rows.csv.gz", index=False, compression="gzip")
    sh_sum.to_csv(out / "shallow_exit_summary.csv", index=False)
    corr = correction_signals(st)
    corr, vdiag = add_liquidity(corr, st)
    corr.to_csv(out / "correction_signals.csv.gz", index=False, compression="gzip")
    corr_rows, corr_sum = correction_exit_audit(corr, st)
    corr_rows.to_csv(out / "correction_exit_rows.csv.gz", index=False, compression="gzip")
    corr_sum.to_csv(out / "correction_exit_summary.csv", index=False)
    threshold = pd.read_csv(args.threshold, compression="gzip")
    deep_rows, deep_sum = deep_handoff_audit(threshold, st)
    deep_rows.to_csv(out / "deep_handoff_rows.csv.gz", index=False, compression="gzip")
    deep_sum.to_csv(out / "deep_handoff_summary.csv", index=False)
    summary = {
        "status": "SYSTEMATIC_ENTRY_EXIT_AUDIT", "research_only": True,
        "scope": {
            "strong_uptrend": "MC65-80; existing leader recognition/shallow candidates; new work is exit/context only",
            "good_market": "MC50-65; existing shallow candidates; new work is exit/context only",
            "standard_correction": "MC35-50 exact split; new M10 RSI60 and M21 RSI55 comparison",
            "recovery": "MC20-35; no duplicate retest; rely on completed RSI30/market-RS189 studies",
            "panic": "MC<20; no duplicate retest; rely on completed RSI30/TQQQ panic studies",
        },
        "exit_methods": {
            "FIX20": "exit at open 20 sessions after entry",
            "FIX40": "exit at open 40 sessions after entry",
            "EMA10": "first close below EMA10 -> next open, max 60",
            "EMA21": "first close below EMA21 -> next open, max 60",
            "ATR3": "close below highest-close minus 3 ATR14 -> next open, max 60",
            "P25_AT20_EMA10": "sell 25% next open after first close >=+20%; remainder EMA10 trail, max 60",
            "FAST20_EXTEND21": "if +20% within first 15 sessions, extend to EMA21/max40; otherwise fixed20",
        },
        "execution": "signal at close, next-open execution for dynamic exits; 5 bps each side",
        "shallow_rows": int(len(sh_rows)), "correction_signals": int(len(corr)), "deep_rows": int(len(deep_rows)),
        "market_download": st["market"]["diag"], "qqq_download": qdiag, "correction_volume_download": vdiag,
        "limitations": [
            "Current-universe/current-sector survivorship bias remains.",
            "2022+ is confirmation, not pristine OOS.",
            "Daily OHLC cannot resolve intraday order beyond next-open rules.",
            "NOW is a leader-recognition benchmark, not the exact historical production normal-stock ledger.",
            "This audit intentionally does not repeat previously rejected threshold/divergence/VWAP/VCP/tranche/STOP8 grids.",
        ],
    }
    (out / "summary.json").write_text(json.dumps(safe(summary), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(safe(summary), ensure_ascii=False, indent=2), flush=True)
    print("\nSHALLOW TOP", flush=True)
    if not sh_sum.empty:
        print(sh_sum.sort_values(["period", "mc_band", "mean"], ascending=[True, True, False]).head(30).to_string(index=False), flush=True)
    print("\nCORRECTION", flush=True)
    if not corr_sum.empty:
        print(corr_sum.to_string(index=False), flush=True)
    print("\nDEEP", flush=True)
    if not deep_sum.empty:
        print(deep_sum.to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
