from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

import audit_rsi_reset_portfolio as portfolio
import audit_rsi_reset_robust as market_base
import validate_early_rotation as universe_base
import validate_rsi_divergence_strong as rsi_base


COST = 5.0 / 10000.0
DISC_END = pd.Timestamp("2021-12-31")
CONF_START = pd.Timestamp("2022-01-03")
RS_CUTS = (80, 85, 90, 95, 99)
RSI_CUTS = (30, 35, 40)


def safe(x):
    if isinstance(x, dict): return {str(k): safe(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)): return [safe(v) for v in x]
    if isinstance(x, np.integer): return int(x)
    if isinstance(x, (np.floating, float)):
        z = float(x); return z if math.isfinite(z) else None
    return x


def cluster_ci(df, value, cluster, seed, reps=2500):
    z = df[[cluster, value]].dropna().groupby(cluster, observed=True)[value].mean().to_numpy(float)
    if len(z) < 2: return (np.nan, np.nan)
    rng = np.random.default_rng(seed)
    q = np.quantile(rng.choice(z, size=(reps, len(z)), replace=True).mean(axis=1), [.025, .975])
    return float(q[0]), float(q[1])


def summarize(x, calendar, seed):
    z = x.dropna(subset=["entry_20"]).copy()
    if z.empty: return {"n": 0}
    pos = pd.Series(np.arange(len(calendar)), index=calendar)
    z["block20"] = np.floor(pos.reindex(z.signal_date).to_numpy(float) / 20).astype("int64")
    r = z.entry_20; gp = r[r > 0].sum(); gl = -r[r < 0].sum()
    dlo, dhi = cluster_ci(z, "entry_20", "signal_date", seed)
    blo, bhi = cluster_ci(z, "entry_20", "block20", seed + 1)
    slo, shi = cluster_ci(z, "entry_20", "symbol", seed + 2)
    return {"n": len(z), "signal_dates": z.signal_date.nunique(), "symbols": z.symbol.nunique(),
            "mean20": r.mean(), "median20": r.median(), "win20": (r > 0).mean(),
            "pf20": np.nan if gl == 0 else gp / gl, "mae20": z.mae_20.mean(),
            "mfe20": z.mfe_20.mean(), "p10_20": r.quantile(.1),
            "date_lo": dlo, "date_hi": dhi, "block_lo": blo, "block_hi": bhi,
            "symbol_lo": slo, "symbol_hi": shi,
            "rs189_touch_mean": z.rs189_touch.mean(), "rs189_signal_mean": z.rs189_signal.mean(),
            "delay_mean": z.delay.mean()}


def scan_rule(cl, op, hi, lo, rsi, rs189, rs_cut, rsi_cut):
    records = []; n = len(cl); dates = cl.index
    for sym in cl.columns:
        ca = cl[sym].to_numpy(float); oa = op[sym].to_numpy(float)
        ha = hi[sym].to_numpy(float); la = lo[sym].to_numpy(float)
        ra = rsi[sym].to_numpy(float); sa = rs189[sym].to_numpy(float)
        touches = np.flatnonzero(np.isfinite(ra) & np.isfinite(sa) & (ra <= rsi_cut) & (sa >= rs_cut))
        rises = np.flatnonzero(np.isfinite(ra) & np.isfinite(np.roll(ra, 1)) & np.isfinite(sa)
                               & (ra > np.roll(ra, 1)) & (sa >= rs_cut))
        touches = touches[(touches >= 190) & (touches < n - 20)]
        rises = rises[(rises > 190) & (rises < n - 20)]
        k = 0; next_allowed = 190
        while k < len(touches):
            k = int(np.searchsorted(touches, next_allowed, side="left", sorter=None))
            if k >= len(touches): break
            touch = int(touches[k]); deadline = min(touch + 20, n - 21)
            q = int(np.searchsorted(rises, touch + 1, side="left"))
            signal = int(rises[q]) if q < len(rises) and rises[q] <= deadline else None
            if signal is None:
                next_allowed = touch + 1; k += 1; continue
            entry, end = signal + 1, signal + 20
            a, b = oa[entry], ca[end]
            if np.isfinite(a) and a > 0 and np.isfinite(b):
                window_h = ha[entry:end+1]; window_l = la[entry:end+1]
                records.append({"symbol": sym, "rs_cut": rs_cut, "rsi_cut": rsi_cut,
                    "touch_date": dates[touch], "signal_date": dates[signal], "entry_date": dates[entry],
                    "delay": signal-touch, "rsi_touch": ra[touch], "rsi_signal": ra[signal],
                    "rs189_touch": sa[touch], "rs189_signal": sa[signal],
                    "entry_20": b/a - 1 - 2*COST,
                    "mfe_20": np.nanmax(window_h)/a - 1 if np.isfinite(window_h).any() else np.nan,
                    "mae_20": np.nanmin(window_l)/a - 1 if np.isfinite(window_l).any() else np.nan})
            # No overlapping same-symbol positions or repeated versions of the same reset.
            next_allowed = signal + 21; k += 1
    return records


def run_portfolios(trades, market, out, root):
    cl, op, active = market["close"], market["open"], market["active"]
    cal = cl.index; ema21 = cl.ewm(span=21, adjust=False).mean(); rows = []
    imap = universe_base.read_industry_map(root / "industry_map.json")
    sector = {s: imap.get(s, (s, s))[0] or s for s in cl.columns}
    for period, start, end in (("ALL", "2016-01-04", "2026-06-30"),
                               ("DISCOVERY", "2016-01-04", "2021-12-31"),
                               ("CONFIRM", "2022-01-03", "2026-06-30")):
        ix = cal[(cal >= start) & (cal <= end)]
        for (rs_cut, rsi_cut), x in trades.groupby(["rs_cut", "rsi_cut"], observed=True):
            z = x[x.entry_date.isin(ix)].copy()
            # Theme-free by construction. Unique group labels disable the theme cap while retaining max-four.
            z["theme"] = z.symbol; z["rank_priority"] = 100.0 - z.rs189_signal
            m, _ = portfolio.simulate(ix, op, cl, active, ema21, z, .029, 4, 20, "full", False)
            rows.append({"period": period, "rs_cut": rs_cut, "rsi_cut": rsi_cut,
                         "scenario": "P4_RS_PRIORITY_NO_GROUP_CAP", "input_signals": len(z),
                         "slot": .029, "max_pos": 4, "group_cap": "none", "priority": "rs189", "hold": 20, **m})
        # Capacity and concentration sensitivity only for the two decision candidates.
        for rs_cut, rsi_cut in ((85, 30), (95, 35)):
            z0 = trades[(trades.rs_cut == rs_cut) & (trades.rsi_cut == rsi_cut)
                        & trades.entry_date.isin(ix)].copy()
            for max_pos, group_cap, priority in ((1, "none", "rs189"), (2, "none", "rs189"),
                                                  (4, "sector2", "rs189"), (4, "none", "rsi")):
                z = z0.copy()
                z["theme"] = z.symbol.map(sector) if group_cap == "sector2" else z.symbol
                z["rank_priority"] = (100.0 - z.rs189_signal) if priority == "rs189" else z.rsi_signal
                m, _ = portfolio.simulate(ix, op, cl, active, ema21, z, .029, max_pos, 20, "full", False)
                scenario = f"P{max_pos}_{priority.upper()}_" + ("SECTOR2" if group_cap == "sector2" else "NO_GROUP_CAP")
                rows.append({"period": period, "rs_cut": rs_cut, "rsi_cut": rsi_cut,
                             "scenario": scenario, "input_signals": len(z), "slot": .029,
                             "max_pos": max_pos, "group_cap": group_cap, "priority": priority,
                             "hold": 20, **m})
    pd.DataFrame(rows).to_csv(out / "market_rs189_portfolio.csv", index=False)


def simulate_combined(cal, op, cl, trades, market_cap):
    cash = 1.0; lots = []; navs = []; expos = []; accepted_theme = accepted_market = 0
    skipped_total = skipped_market = skipped_theme = skipped_duplicate = 0; turnover = 0.0
    by_entry = {d: g for d, g in trades.groupby("entry_date", observed=True)}
    for i, d in enumerate(cal):
        keep = []
        for z in lots:
            px = op.at[d, z["symbol"]]
            if i >= z["exit_i"] and pd.notna(px):
                gross = z["shares"] * px; cash += gross * (1-COST); turnover += gross
            else: keep.append(z)
        lots = keep
        if d in by_entry:
            day = by_entry[d].sort_values(["source_priority", "rank_priority", "rsi_signal", "symbol"])
            for r in day.itertuples(index=False):
                if any(z["symbol"] == r.symbol for z in lots): skipped_duplicate += 1; continue
                if len(lots) >= 4: skipped_total += 1; continue
                if r.source == "market" and sum(z["source"] == "market" for z in lots) >= market_cap:
                    skipped_market += 1; continue
                if r.source == "theme" and sum(z["source"] == "theme" and z["theme"] == r.theme for z in lots) >= 2:
                    skipped_theme += 1; continue
                px = op.at[d, r.symbol]
                if pd.isna(px) or px <= 0: continue
                mark = cash + sum(z["shares"] * op.at[d, z["symbol"]] for z in lots
                                  if pd.notna(op.at[d, z["symbol"]]))
                amount = .029 * mark
                if cash < amount * (1+COST): skipped_total += 1; continue
                cash -= amount * (1+COST); turnover += amount
                lots.append({"symbol": r.symbol, "theme": r.theme, "source": r.source,
                             "shares": amount/px, "exit_i": min(i+20, len(cal)-1)})
                if r.source == "theme": accepted_theme += 1
                else: accepted_market += 1
        gross = sum(z["shares"] * cl.at[d, z["symbol"]] for z in lots
                    if pd.notna(cl.at[d, z["symbol"]]))
        nav = cash + gross; navs.append(nav); expos.append(gross/nav if nav > 0 else np.nan)
    ns = pd.Series(navs, index=cal); m = portfolio.metrics(ns)
    return {**m, "avg_exposure": float(np.nanmean(expos)), "max_exposure": float(np.nanmax(expos)),
            "accepted_theme": accepted_theme, "accepted_market": accepted_market,
            "skipped_total_cap": skipped_total, "skipped_market_cap": skipped_market,
            "skipped_theme_cap": skipped_theme, "skipped_duplicate": skipped_duplicate,
            "turnover_nav": float(turnover/np.mean(navs))}


def run_combined(theme_path, market_trades, market, out):
    if theme_path is None or not theme_path.exists(): return
    theme = pd.read_csv(theme_path, compression="gzip", parse_dates=["entry_date", "signal_date"])
    theme = theme[(theme.kind == "RISE") & (theme.threshold == 30) & theme.RS63_TOP3 & theme.signal_top3].copy()
    theme["source"] = "theme"; theme["source_priority"] = 0
    theme["rank_priority"] = theme.rank63; theme = theme[["entry_date","signal_date","symbol","theme","source","source_priority","rank_priority","rsi_signal"]]
    mk = market_trades[(market_trades.rs_cut == 85) & (market_trades.rsi_cut == 30)].copy()
    mk["theme"] = mk.symbol; mk["source"] = "market"; mk["source_priority"] = 1
    mk["rank_priority"] = 100.0 - mk.rs189_signal
    mk = mk[["entry_date","signal_date","symbol","theme","source","source_priority","rank_priority","rsi_signal"]]
    both = pd.concat([theme, mk], ignore_index=True)
    cl, op = market["close"], market["open"]; cal = cl.index; rows = []
    for period, start, end in (("ALL","2016-01-04","2026-06-30"),
                               ("DISCOVERY","2016-01-04","2021-12-31"),
                               ("CONFIRM","2022-01-03","2026-06-30")):
        ix = cal[(cal >= start) & (cal <= end)]; z = both[both.entry_date.isin(ix)]
        for market_cap in (0, 1, 2):
            m = simulate_combined(ix, op, cl, z, market_cap)
            rows.append({"period": period, "scenario": f"THEME_PRIORITY_MARKET_CAP{market_cap}",
                         "market_cap": market_cap, "input_theme": int((z.source=='theme').sum()),
                         "input_market": int((z.source=='market').sum()), **m})
    pd.DataFrame(rows).to_csv(out / "combined_theme_market_portfolio.csv", index=False)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--root", default="."); ap.add_argument("--output", required=True)
    ap.add_argument("--theme-trades")
    args = ap.parse_args(); root = Path(args.root); out = Path(args.output); out.mkdir(parents=True, exist_ok=True)
    market = market_base.rebuild_market(root, "2016-01-04", "2026-06-30", 6000, 75, 3)
    cl, op, hi, lo = market["close"], market["open"], market["high"], market["low"]
    rsi = rsi_base.rsi(cl, 14)
    ret189 = cl.pct_change(189, fill_method=None)
    rs189 = ret189.rank(axis=1, pct=True, method="average") * 100.0
    records = []
    for rs_cut in RS_CUTS:
        for rsi_cut in RSI_CUTS:
            print("SCAN", rs_cut, rsi_cut, flush=True)
            records.extend(scan_rule(cl, op, hi, lo, rsi, rs189, rs_cut, rsi_cut))
    trades = pd.DataFrame(records)
    trades = trades[(trades.signal_date >= "2016-01-04") & (trades.signal_date <= "2026-06-30")]
    trades = trades.sort_values(["rs_cut", "rsi_cut", "signal_date", "symbol"])
    trades.to_csv(out / "market_rs189_trades.csv.gz", index=False, compression="gzip")
    rows = []
    for (rs_cut, rsi_cut), x in trades.groupby(["rs_cut", "rsi_cut"], observed=True):
        for period, z in (("DISCOVERY", x[x.signal_date <= DISC_END]),
                          ("CONFIRM", x[x.signal_date >= CONF_START])):
            rows.append({"period": period, "rs_cut": rs_cut, "rsi_cut": rsi_cut,
                         **summarize(z, cl.index, 2100000 + len(rows)*13)})
    pd.DataFrame(rows).to_csv(out / "market_rs189_summary.csv", index=False)
    run_portfolios(trades, market, out, root)
    run_combined(Path(args.theme_trades) if args.theme_trades else None, trades, market, out)
    meta = {"status": "MARKET_WIDE_RS189_RSI_RESET_AUDIT",
            "definitions": {"universe": "same 3,596-stock current V38 universe; no Theme Momentum condition",
                "RS189": "daily cross-sectional percentile of trailing 189-session return",
                "touch": "RSI14 at or below threshold while RS189 remains at or above cutoff",
                "signal": "first subsequent RSI14 up-day within 20 sessions; RS189 cutoff must still hold",
                "cooldown": "after a signal, same symbol cannot signal again for 20 sessions",
                "entry": "next open; 20-session outcome; 5 bps per side",
                "portfolio": "2.9% of NAV, maximum four, 20-session hold; no theme cap"},
            "coverage": market["diag"],
            "limitations": ["Current-universe survivorship bias remains.",
                "Market-wide strategy has no natural Theme event clock, so reset touch is the anchor.",
                "No theme cap is applied; portfolio comparison should consider concentration separately.",
                "Yahoo adjusted OHLCV may differ from TradingView."]}
    (out / "summary.json").write_text(json.dumps(safe(meta), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(safe(meta), ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__": main()
