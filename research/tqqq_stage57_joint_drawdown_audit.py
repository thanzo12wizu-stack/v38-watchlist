from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

COST = 0.0005


def metrics(r):
    x = np.asarray(r, float); x = np.nan_to_num(x, nan=0.0)
    eq = np.cumprod(1 + x); dd = eq / np.maximum.accumulate(eq) - 1
    return {"cagr": float(eq[-1] ** (252 / len(eq)) - 1), "mdd": float(dd.min()), "end": float(eq[-1])}


def window_min(r, n):
    return float((pd.Series(1 + np.asarray(r)).rolling(n).apply(np.prod, raw=True) - 1).min())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stock-series", required=True)
    ap.add_argument("--tqqq-daily", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args(); out = Path(args.output); out.mkdir(parents=True, exist_ok=True)
    s = pd.read_csv(args.stock_series, compression="gzip", parse_dates=["date"]).set_index("date")
    q = pd.read_csv(args.tqqq_daily, compression="gzip", parse_dates=["date"]).set_index("date")
    z = s.join(q, how="inner").sort_index()
    stock_scenarios = [c[:-4] for c in z.columns if c.endswith("_nav")]
    tq_scenarios = [c.replace("target_", "") for c in z.columns if c.startswith("target_")]
    base_eff = z["target_CURRENT30"].shift(2).fillna(0)
    rows = []; daily_out = pd.DataFrame(index=z.index)
    rng = np.random.default_rng(570827); block = 60; horizon = min(2520, len(z)); nsim = 1000
    nb = int(np.ceil(horizon / block)); offs = np.arange(block)
    starts = rng.integers(0, len(z)-block+1, size=(nsim, nb)); paths = (starts[:,:,None]+offs).reshape(nsim,-1)[:,:horizon]
    mcrows = []
    for ss in stock_scenarios:
        sr = z[f"{ss}_nav"].pct_change(fill_method=None).fillna(0)
        sexp = z[f"{ss}_exposure"].fillna(0)
        for tqname in tq_scenarios:
          raw_target = z[f"target_{tqname}"]
          for cap_mode in ("UNCAPPED", "CAP100"):
            raw_eff = raw_target.shift(2).fillna(0)
            eff = raw_eff if cap_mode == "UNCAPPED" else np.minimum(raw_eff, np.maximum(0, 1-sexp))
            # CAP100 represents the shared capital allocator at execution, after both order sets are known.
            turn = eff.diff().abs().fillna(0)
            tr = eff * z["tqqq_ret_jpy"].fillna(0) - turn * COST
            cr = sr + tr
            tactical = raw_eff > base_eff + 1e-12
            overlap = (sexp > 0) & tactical
            m = metrics(cr)
            row = {"stock_scenario": ss, "tqqq_scenario": tqname, "cap_mode": cap_mode, **m,
                   "worst_5d": window_min(cr, 5), "worst_10d": window_min(cr, 10), "worst_20d": window_min(cr, 20),
                   "max_total_exposure": float((sexp + eff).max()), "days_stock_active": int((sexp > 0).sum()),
                   "days_tactical_overlap": int(overlap.sum()),
                   "worst_overlap_day": float(cr[overlap].min()) if overlap.any() else None,
                   "overlap_return_corr": float(sr[overlap].corr(tr[overlap])) if overlap.sum() >= 3 else None}
            rows.append(row)
            key = f"{ss}__{tqname}__{cap_mode}"; daily_out[f"ret_{key}"] = cr; daily_out[f"overlap_{key}"] = overlap.astype(int)
            vals = cr.to_numpy(float)
            for sim, ix in enumerate(paths):
                mm = metrics(vals[ix]); mcrows.append({"sim": sim, "stock_scenario": ss, "tqqq_scenario": tqname, "cap_mode": cap_mode,
                                                       "cagr": mm["cagr"], "mdd": mm["mdd"], "end": mm["end"]})
    hist = pd.DataFrame(rows); mc = pd.DataFrame(mcrows)
    hist.to_csv(out / "joint_historical.csv", index=False); mc.to_csv(out / "joint_mc.csv.gz", index=False, compression="gzip")
    sm = mc.groupby(["stock_scenario","tqqq_scenario","cap_mode"], observed=True).agg(
        cagr_median=("cagr","median"), cagr_p05=("cagr",lambda x:x.quantile(.05)),
        mdd_median=("mdd","median"), mdd_p05=("mdd",lambda x:x.quantile(.05)),
        end_p05=("end",lambda x:x.quantile(.05))).reset_index()
    sm.to_csv(out / "joint_mc_summary.csv", index=False)
    daily_out.reset_index().to_csv(out / "joint_daily.csv.gz", index=False, compression="gzip")
    summary = {"status":"STAGE57_JOINT_DRAWDOWN_AUDIT", "coverage":{"start":str(z.index.min().date()),"end":str(z.index.max().date()),"days":len(z)},
      "definitions":{"stock":"exact close-marked panic-sleeve account from the Stage56 stock audit",
        "tqqq":"JPY open-to-open return times two-session-lag effective target, less 5 bp target-change cost",
        "joint":"sum of sleeve contributions to total NAV; normal individual-stock book is intentionally absent",
        "CAP100":"shared execution allocator caps effective TQQQ plus measured panic-stock exposure at 100%",
        "overlap":"stock panic exposure positive while TQQQ target exceeds CURRENT30 effective target"},
      "limitations":["Stock sleeve is close-marked while TQQQ is open-marked, so joint daily timing is an approximately synchronized risk test.",
        "The normal stock book return is unavailable; results measure incremental panic-sleeve plus TQQQ risk, not the complete 70/30 portfolio.",
        "Moving-block bootstrap preserves observed joint blocks but is not an untouched OOS test or forecast distribution."]}
    (out/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    print(hist.sort_values("mdd",ascending=False).to_string(index=False)); print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__ == "__main__": main()
