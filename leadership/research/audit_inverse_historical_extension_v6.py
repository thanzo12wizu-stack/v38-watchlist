from __future__ import annotations
import argparse, os, sys, json
from pathlib import Path
import numpy as np, pandas as pd, yfinance as yf

MAP = {0: "Red", 1: "Yellow", 2: "Green", 3: "Blue"}


def norm(x):
    z = pd.DatetimeIndex(pd.to_datetime(x))
    if z.tz is not None: z = z.tz_convert("America/New_York").tz_localize(None)
    return z.normalize()


def cooldown(cond, c=10):
    x = cond.fillna(False).astype(bool); raw = x & ~x.shift(1, fill_value=False)
    out = np.zeros(len(x), bool); last = -99999
    for i, z in enumerate(raw.to_numpy(bool)):
        if z and i - last > c: out[i] = 1; last = i
    return pd.Series(out, index=x.index)


def prod_returns(products, start, end, idx):
    x = yf.download(products, start=start, end=end, auto_adjust=True, actions=False, progress=False, threads=False)
    op = x["Open"].copy(); op.index = norm(op.index); out = pd.DataFrame(index=idx)
    for p in products:
        s = pd.to_numeric(op[p], errors="coerce").reindex(idx); out[p] = s.shift(-1) / s - 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--legacy-dir", required=True); ap.add_argument("--v2-features", required=True); ap.add_argument("--tqqq", required=True); ap.add_argument("--output", required=True)
    a = ap.parse_args(); out = Path(a.output); out.mkdir(parents=True, exist_ok=True)
    legacy_root = Path(a.legacy_dir).resolve()
    v2_path = Path(a.v2_features).resolve(); tqqq_path = Path(a.tqqq).resolve()
    cwd = os.getcwd(); sys.path.insert(0, str(legacy_root)); os.chdir(legacy_root)
    try:
        ns = {}; src = Path("research/tqqq_stage36_goal_first_taxaware.py").read_text(); prefix = src.split('print("\\n=== STAGE36')[0]
        exec(compile(prefix, "stage36-data-prefix", "exec"), ns)
    finally:
        os.chdir(cwd)
        if sys.path and sys.path[0] == str(legacy_root): sys.path.pop(0)
    A = ns["A"]; F = ns["F"]; qqq = ns["qqq"]; dates = norm(F["date"])
    legacy = pd.DataFrame(index=dates)
    legacy["nq_int"] = np.asarray(A["nq"], int); legacy["nq_color"] = legacy.nq_int.map(MAP)
    legacy["mc57"] = np.asarray(A["mc"], float); legacy["mc_chg5"] = legacy.mc57.diff(5); legacy["panic"] = np.asarray(A["panic"], bool)
    qc = pd.to_numeric(qqq["Close"], errors="coerce").copy(); qc.index = norm(qc.index); qc = qc.reindex(dates)
    sma50 = qc.rolling(50, min_periods=50).mean(); legacy["qqq_dist_sma50"] = qc / sma50 - 1; legacy["sma50_slope10"] = sma50.pct_change(10)
    legacy["core_mc"] = legacy.nq_color.eq("Red") & (legacy.qqq_dist_sma50 < 0) & (legacy.sma50_slope10 < 0) & (legacy.mc_chg5 < -3)
    tq = pd.read_csv(tqqq_path, compression="gzip", parse_dates=["date"]).set_index("date").sort_index(); tq.index = norm(tq.index); tq = tq.reindex(dates)
    legacy["stage56"] = (tq.target_M30_TOUCH30_F80_D10 > tq.target_CURRENT30 + 1e-9).fillna(False); legacy["guard"] = legacy.panic | legacy.stage56
    legacy["event"] = cooldown(legacy.core_mc, 10) & ~legacy.guard

    v2 = pd.read_csv(v2_path, compression="gzip", parse_dates=["date"]).set_index("date").sort_index(); v2.index = norm(v2.index)
    ov = legacy.join(v2[["nq_color", "mc57", "mc_chg5", "qqq_dist_sma50", "sma50_slope10", "panic_episode"]], how="inner", lsuffix="_legacy", rsuffix="_v2")
    ov["nq_match"] = ov.nq_color_legacy.eq(ov.nq_color_v2)
    ov["legacy_core"] = ov.nq_color_legacy.eq("Red") & (ov.qqq_dist_sma50_legacy < 0) & (ov.sma50_slope10_legacy < 0) & (ov.mc_chg5_legacy < -3)
    ov["v2_core"] = ov.nq_color_v2.eq("Red") & (ov.qqq_dist_sma50_v2 < 0) & (ov.sma50_slope10_v2 < 0) & (ov.mc_chg5_v2 < -3)
    ov["core_match"] = ov.legacy_core.eq(ov.v2_core)
    v2guard = pd.to_numeric(ov.panic_episode, errors="coerce").fillna(0) > 0
    st = legacy["stage56"].reindex(ov.index).fillna(False)
    lev = cooldown(ov.legacy_core, 10) & ~(ov.panic | st)
    vev = cooldown(ov.v2_core, 10) & ~(v2guard | st)
    ld = ov.index[lev]; vd = ov.index[vev]; exact = len(set(ld) & set(vd)); near = sum(any(abs((x - y).days) <= 2 for y in vd) for x in ld)
    comparison = {
        "overlap_days": len(ov), "nq_exact_match": float(ov.nq_match.mean()), "core_daily_match": float(ov.core_match.mean()),
        "mc57_corr": float(ov[["mc57_legacy", "mc57_v2"]].corr().iloc[0, 1]), "legacy_events": len(ld), "v2_events": len(vd),
        "event_exact_overlap": exact, "legacy_event_near_v2_within2d": near, "near_fraction_of_legacy": float(near / len(ld)) if len(ld) else None,
    }

    ret = prod_returns(["PSQ", "QID", "SQQQ"], "2010-01-01", "2026-04-01", dates); rows = []
    for period, aa, bb in [("PRE_2011_2015", "2011-01-03", "2015-12-31"), ("OVERLAP_2016_2026", "2016-01-04", "2026-03-20")]:
        ev = legacy.event & (legacy.index >= aa) & (legacy.index <= bb)
        for h in [2, 3, 4]:
            for p in ["PSQ", "QID", "SQQQ"]:
                vals = []; sigdates = []
                for i in np.flatnonzero(ev.to_numpy(bool)):
                    z = ret[p].iloc[i + 1:min(len(ret), i + 1 + h)]
                    if len(z) == h and z.notna().all(): vals.append(float(np.prod(1 + z) - 1)); sigdates.append(str(dates[i].date()))
                vals = np.asarray(vals, float)
                rows.append({
                    "period": period, "product": p, "hold": h, "n": len(vals), "mean": float(np.mean(vals)) if len(vals) else None,
                    "median": float(np.median(vals)) if len(vals) else None, "win": float(np.mean(vals > 0)) if len(vals) else None,
                    "worst": float(np.min(vals)) if len(vals) else None, "best": float(np.max(vals)) if len(vals) else None, "signal_dates": "|".join(sigdates),
                })
    result = pd.DataFrame(rows); result.to_csv(out / "historical_event_extension.csv", index=False)
    ov.reset_index(names="date").to_csv(out / "legacy_v2_overlap_diagnostics.csv.gz", index=False, compression="gzip")
    legacy.reset_index(names="date").to_csv(out / "legacy_state_2011_2026.csv.gz", index=False, compression="gzip")
    summary = {
        "status": "RESEARCH_ONLY_NO_PRODUCTION_CHANGE", "comparison": comparison,
        "pre2016": result[result.period.eq("PRE_2011_2015")].to_dict("records"),
        "limitation": "2011-2015 uses legacy Stage34 NQSAR/MC reconstruction. It is acceptable only to the degree overlap diagnostics agree with V2.",
    }
    (out / "summary_historical.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
