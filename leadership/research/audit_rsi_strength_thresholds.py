from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

import audit_rsi_reset_robust as prior
import audit_rsi_reset_portfolio as portfolio
import validate_rsi_divergence_strong as rd
import validate_rsi_reset_reaccel as rr

H = (5, 10, 20, 40)
COST = 5.0
DISC_END = pd.Timestamp("2021-12-31")
CONF_START = pd.Timestamp("2022-01-03")
THRESHOLDS = (25, 30, 35, 40, 45, 50)
KINDS = ("TOUCH", "RISE")
GROUPS = ("RS63_TOP3", "RS63_TOP1", "DUAL_TOP3", "DUAL_TOP2", "DUAL_TOP1", "DUAL_OUTPERFORM")


def safe(x):
    if isinstance(x, dict): return {str(k): safe(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)): return [safe(v) for v in x]
    if isinstance(x, np.integer): return int(x)
    if isinstance(x, (np.floating, float)):
        z = float(x); return z if math.isfinite(z) else None
    if isinstance(x, pd.Timestamp): return x.isoformat()
    return x


def candidates(rows):
    x = rows.sort_values(["date", "theme", "symbol"]).drop_duplicates(["date", "theme", "symbol"]).copy()
    x["rank63"] = x.groupby(["date", "theme"], observed=True).ret63.rank(method="first", ascending=False)
    x["rank189"] = x.groupby(["date", "theme"], observed=True).ret189.rank(method="first", ascending=False)
    complete = x.groupby(["date", "theme"], observed=True).agg(n63=("ret63", "count"), n189=("ret189", "count"))
    good = complete[(complete.n63 >= 3) & (complete.n189 >= 3)].index
    x = x.set_index(["date", "theme"]).loc[good].reset_index()
    x["RS63_TOP3"] = x.rank63 <= 3
    x["RS63_TOP1"] = x.rank63 <= 1
    x["DUAL_TOP3"] = (x.rank63 <= 3) & (x.rank189 <= 3)
    x["DUAL_TOP2"] = (x.rank63 <= 2) & (x.rank189 <= 2)
    x["DUAL_TOP1"] = (x.rank63 <= 1) & (x.rank189 <= 1)
    x["DUAL_OUTPERFORM"] = x.DUAL_TOP3 & (x.ret63 > x.ret63_spy) & (x.ret189 > x.ret189_spy)
    x = x[x.RS63_TOP3 | (x.rank189 <= 3)].copy()
    x["candidate_key"] = x.date.dt.strftime("%Y-%m-%d") + "|" + x.theme.astype(str) + "|" + x.symbol.astype(str)
    return x


def trade_return(op, cl, sym, entry, end):
    if entry < 0 or end < entry or end >= len(cl): return np.nan
    a, b = op.at[cl.index[entry], sym], cl.at[cl.index[end], sym]
    if pd.isna(a) or pd.isna(b) or a <= 0: return np.nan
    return float(b / a - 1 - 2 * COST / 10000)


def excursions(op, hi, lo, sym, entry, end):
    if entry < 0 or end < entry or end >= len(hi): return np.nan, np.nan
    a = op.at[hi.index[entry], sym]
    if pd.isna(a) or a <= 0: return np.nan, np.nan
    ix = hi.index[entry:end+1]
    return float(hi.loc[ix, sym].max()/a-1), float(lo.loc[ix, sym].min()/a-1)


def cluster_ci(df, value, cluster, seed, reps=2500):
    z = df[[cluster, value]].dropna().groupby(cluster, observed=True)[value].mean().to_numpy(float)
    if len(z) < 2: return (np.nan, np.nan)
    rng = np.random.default_rng(seed); q = np.quantile(rng.choice(z, size=(reps, len(z)), replace=True).mean(axis=1), [.025, .975])
    return float(q[0]), float(q[1])


def summarize(g, denominator, calendar, seed):
    x = g.dropna(subset=["entry_20"]).copy()
    if x.empty: return {"n": 0, "denominator": denominator, "trade_rate": 0.0}
    p = pd.Series(np.arange(len(calendar)), index=calendar)
    x["block20"] = np.floor(p.reindex(pd.to_datetime(x.signal_date)).to_numpy(float)/20).astype("int64")
    r = x.entry_20.astype(float); pos = r[r > 0].sum(); neg = -r[r < 0].sum()
    dlo, dhi = cluster_ci(x, "entry_20", "signal_date", seed)
    blo, bhi = cluster_ci(x, "entry_20", "block20", seed+1)
    tlo, thi = cluster_ci(x, "entry_20", "theme", seed+2)
    return {"n": len(x), "denominator": denominator, "trade_rate": len(x)/denominator if denominator else np.nan,
            "events": x[["day0_date","theme"]].drop_duplicates().shape[0], "symbols": x.symbol.nunique(),
            "mean20": r.mean(), "median20": r.median(), "win20": (r>0).mean(), "pf20": None if neg == 0 else pos/neg,
            "mae20": x.mae_20.mean(), "mfe20": x.mfe_20.mean(), "p10_20": r.quantile(.1),
            "date_lo": dlo, "date_hi": dhi, "block_lo": blo, "block_hi": bhi, "theme_lo": tlo, "theme_hi": thi,
            "delay_mean": x.delay.mean(), "rsi_signal_mean": x.rsi_signal.mean()}


def portfolio_rules(trades):
    """Pre-registered rule set for the already selected 2.9% / max-four sleeve."""
    rise30 = trades[(trades.kind == "RISE") & (trades.threshold == 30)].copy()
    rise35 = trades[(trades.kind == "RISE") & (trades.threshold == 35)].copy()
    touch35 = trades[(trades.kind == "TOUCH") & (trades.threshold == 35)].copy()
    rules = {
        "UNION_RISE30": rise30,
        "RS63_TOP3_RISE30": rise30[rise30.RS63_TOP3],
        "RS63_TOP1_RISE30": rise30[rise30.RS63_TOP1],
        "RS63_TOP1_RISE35": rise35[rise35.RS63_TOP1],
        "RS63_TOP1_TOUCH35": touch35[touch35.RS63_TOP1],
        "TIER_R1_RISE35_R23_RISE30": pd.concat([
            rise35[rise35.rank63 == 1], rise30[rise30.rank63.isin([2, 3])]
        ], ignore_index=True),
        "TIER_R1_TOUCH35_R23_RISE30": pd.concat([
            touch35[touch35.rank63 == 1], rise30[rise30.rank63.isin([2, 3])]
        ], ignore_index=True),
        "DUAL_TOP3_RISE30": rise30[rise30.DUAL_TOP3],
    }
    out = {}
    for name, x in rules.items():
        x = x.sort_values(["day0_date", "theme", "symbol", "signal_date"]).drop_duplicates(
            ["day0_date", "theme", "symbol"], keep="first").copy()
        x["rank_priority"] = np.where(x.rank63 <= 3, x.rank63 - 1, 3 + x.rank189)
        out[name] = x
    return out


def run_portfolios(trades, market, out):
    cl, op, active = market["close"], market["open"], market["active"]
    cal = cl.index; ema21 = cl.ewm(span=21, adjust=False).mean(); rows = []
    rules = portfolio_rules(trades)
    for period, start, end in (("ALL", "2016-01-04", "2026-06-30"),
                               ("DISCOVERY", "2016-01-04", "2021-12-31"),
                               ("CONFIRM", "2022-01-03", "2026-06-30")):
        ix = cal[(cal >= start) & (cal <= end)]
        for name, x in rules.items():
            z = x[x.entry_date.isin(ix) & x.symbol.isin(cl.columns)].copy()
            m, _ = portfolio.simulate(ix, op, cl, active, ema21, z, 0.029, 4, 20, "full", False)
            rows.append({"period": period, "rule": name, "slot": 0.029, "max_pos": 4,
                         "hold": 20, "input_signals": len(z), **m})
    pd.DataFrame(rows).to_csv(out / "portfolio_rule_comparison.csv", index=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args(); root = Path(args.root); out = Path(args.output); out.mkdir(parents=True, exist_ok=True)
    frozen = pd.read_csv(args.input, compression="gzip", parse_dates=["date"])
    cand = candidates(frozen)
    market = prior.rebuild_market(root, "2016-01-04", "2026-06-30", 6000, 75, 3)
    cl, op, hi, lo = market["close"], market["open"], market["high"], market["low"]
    cand = cand[cand.symbol.isin(cl.columns)].copy()
    rsi = rd.rsi(cl, 14); pos = {pd.Timestamp(d): i for i, d in enumerate(cl.index)}
    ra = {s: rsi[s].to_numpy(float) for s in cand.symbol.unique()}; ca = {s: cl[s].to_numpy(float) for s in cand.symbol.unique()}
    records = []
    for kind in KINDS:
        for threshold in THRESHOLDS:
            print("METHOD", kind, threshold, flush=True)
            for r in cand.itertuples(index=False):
                ep = pos.get(pd.Timestamp(r.date), -1); sym = str(r.symbol)
                if ep < 0 or sym not in ra: continue
                sp = rr.locate(ra[sym], ca[sym], ep, kind.lower(), threshold, 20)
                if sp is None or sp+1 >= len(cl): continue
                entry = sp+1
                rec = {"candidate_key": r.candidate_key, "day0_date": pd.Timestamp(r.date), "theme": str(r.theme), "symbol": sym,
                       "kind": kind, "threshold": threshold, "signal_date": pd.Timestamp(cl.index[sp]),
                       "entry_date": pd.Timestamp(cl.index[entry]), "delay": sp-ep, "rsi_signal": ra[sym][sp],
                       "rank63": r.rank63, "rank189": r.rank189}
                for group in GROUPS: rec[group] = bool(getattr(r, group))
                for h in H:
                    end = entry+h-1
                    rec[f"entry_{h}"] = trade_return(op, cl, sym, entry, end) if end < len(cl) else np.nan
                    rec[f"mfe_{h}"], rec[f"mae_{h}"] = excursions(op, hi, lo, sym, entry, end) if end < len(cl) else (np.nan, np.nan)
                records.append(rec)
    trades = pd.DataFrame(records); trades.to_csv(out/"threshold_trade_rows.csv.gz", index=False, compression="gzip")
    run_portfolios(trades, market, out)
    rows = []
    periods = (("DISCOVERY", None, DISC_END), ("CONFIRM", CONF_START, None))
    for group in GROUPS:
        for period, start, end in periods:
            den = cand[cand[group]].copy()
            if start is not None: den = den[den.date >= start]
            if end is not None: den = den[den.date <= end]
            for (kind, threshold), g in trades[trades[group]].groupby(["kind","threshold"], observed=True):
                z = g
                if start is not None: z = z[z.day0_date >= start]
                if end is not None: z = z[z.day0_date <= end]
                rows.append({"group": group, "period": period, "kind": kind, "threshold": threshold,
                             **summarize(z, len(den), cl.index, 100000+len(rows)*7)})
    summary = pd.DataFrame(rows); summary.to_csv(out/"threshold_summary.csv", index=False)

    # Matched-candidate entry comparison. Positive diff means the higher RSI threshold entered better.
    pairs = []
    for group in GROUPS:
        for period, start, end in periods:
            for kind in KINDS:
                z = trades[(trades[group]) & (trades.kind == kind)].copy()
                if start is not None: z = z[z.day0_date >= start]
                if end is not None: z = z[z.day0_date <= end]
                for low_t, high_t in ((25,30),(30,35),(35,40),(40,45),(45,50),(30,40),(30,50)):
                    a = z[z.threshold==low_t][["candidate_key","day0_date","theme","entry_20"]].rename(columns={"entry_20":"low_ret"})
                    b = z[z.threshold==high_t][["candidate_key","entry_20"]].rename(columns={"entry_20":"high_ret"})
                    m = a.merge(b,on="candidate_key").dropna(); m["diff"] = m.high_ret-m.low_ret
                    lo_ci, hi_ci = cluster_ci(m,"diff","day0_date",900000+len(pairs)*5) if len(m) else (np.nan,np.nan)
                    pairs.append({"group":group,"period":period,"kind":kind,"low_threshold":low_t,"high_threshold":high_t,
                                  "n":len(m),"high_minus_low":m["diff"].mean() if len(m) else np.nan,
                                  "win_high":(m["diff"]>0).mean() if len(m) else np.nan,"date_lo":lo_ci,"date_hi":hi_ci})
    pd.DataFrame(pairs).to_csv(out/"threshold_pairwise.csv",index=False)
    group_sizes = {g:int(cand[g].sum()) for g in GROUPS}
    meta = {"status":"RSI_STRENGTH_THRESHOLD_INTERACTION_AUDIT", "coverage":{"candidate_rows":len(cand),"symbols":cand.symbol.nunique(),"group_sizes":group_sizes},
            "definitions":{"strength_freeze":"all strength groups use only Theme Momentum Day0 fields",
              "RS63_TOP3":"top three 63-day returns inside the Day0 theme",
              "RS63_TOP1":"top one 63-day return inside the Day0 theme",
              "DUAL_TOP3":"top three on both 63-day and 189-day returns",
              "DUAL_TOP2":"top two on both 63-day and 189-day returns",
              "DUAL_TOP1":"top one on both 63-day and 189-day returns",
              "DUAL_OUTPERFORM":"DUAL_TOP3 and both 63-day/189-day return above SPY on Day0",
              "TOUCH":"first RSI14 observation at or below threshold within 20 sessions of Day0",
              "RISE":"first RSI14 up-day after TOUCH, still searched inside the same 20-session window",
              "entry":"signal known at close; buy next open; 5 bps per side"},
            "download":market["diag"],
            "limitations":["Current-universe/current-taxonomy retrospective bias remains.","Nested strength groups and six thresholds create multiple comparisons; require discovery/confirmation agreement and clustered intervals.","Yahoo adjusted OHLCV may differ from TradingView."]}
    (out/"summary.json").write_text(json.dumps(safe(meta),ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(safe(meta),ensure_ascii=False,indent=2),flush=True)


if __name__ == "__main__": main()
