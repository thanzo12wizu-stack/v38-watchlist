from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

import audit_ordinary_stock_market_mode_robustness as base

ANCHORS = (pd.Timestamp("2026-07-13"), pd.Timestamp("2019-01-14"))
SLOTS = (3, 4, 5)


def trade_key(df: pd.DataFrame) -> pd.Series:
    if df.empty:
        return pd.Series(dtype=str)
    return (
        df["symbol"].astype(str) + "|" +
        pd.to_datetime(df["entry_date"]).dt.strftime("%Y-%m-%d") + "|" +
        pd.to_datetime(df["exit_date"]).dt.strftime("%Y-%m-%d")
    )


def summarize(df: pd.DataFrame) -> dict:
    if df is None or df.empty:
        return {"n": 0}
    r = pd.to_numeric(df["return"], errors="coerce").dropna()
    if r.empty:
        return {"n": 0}
    return {
        "n": int(len(r)),
        "mean": float(r.mean()),
        "median": float(r.median()),
        "win_rate": float((r > 0).mean()),
        "p10": float(r.quantile(0.10)),
        "p90": float(r.quantile(0.90)),
        "sum_log_return": float(np.log1p(r.clip(lower=-0.999999)).sum()),
        "by_period": {
            "discovery": summarize_simple(df.loc[pd.to_datetime(df["entry_date"]) <= pd.Timestamp("2021-12-31")]),
            "confirmation": summarize_simple(df.loc[pd.to_datetime(df["entry_date"]) >= pd.Timestamp("2022-01-03")]),
        },
        "by_year": {
            str(int(y)): summarize_simple(g)
            for y, g in df.groupby(pd.to_datetime(df["entry_date"]).dt.year)
        },
    }


def summarize_simple(df: pd.DataFrame) -> dict:
    if df is None or df.empty:
        return {"n": 0}
    r = pd.to_numeric(df["return"], errors="coerce").dropna()
    if r.empty:
        return {"n": 0}
    return {
        "n": int(len(r)),
        "mean": float(r.mean()),
        "median": float(r.median()),
        "win_rate": float((r > 0).mean()),
        "sum_log_return": float(np.log1p(r.clip(lower=-0.999999)).sum()),
    }


def cluster_bootstrap_mean(df: pd.DataFrame, reps: int = 5000, seed: int = 20260829) -> dict:
    if df is None or df.empty:
        return {"n": 0}
    x = df.copy()
    x["entry_date"] = pd.to_datetime(x["entry_date"])
    x["return"] = pd.to_numeric(x["return"], errors="coerce")
    x = x.dropna(subset=["entry_date", "return"])
    if x.empty:
        return {"n": 0}
    clusters = [g["return"].to_numpy(float) for _, g in x.groupby("entry_date")]
    rng = np.random.default_rng(seed)
    draws = []
    for _ in range(reps):
        pick = rng.integers(0, len(clusters), size=len(clusters))
        vals = np.concatenate([clusters[i] for i in pick])
        draws.append(float(np.mean(vals)))
    q = np.quantile(draws, [0.025, 0.5, 0.975])
    return {
        "n": int(len(x)),
        "entry_date_clusters": int(len(clusters)),
        "mean": float(x["return"].mean()),
        "ci95": [float(q[0]), float(q[2])],
        "bootstrap_prob_mean_gt0": float(np.mean(np.asarray(draws) > 0.0)),
    }


def marginal_extra(hi: pd.DataFrame, lo: pd.DataFrame) -> pd.DataFrame:
    if hi.empty:
        return hi.copy()
    h = hi.loc[hi["entry_bucket"] == 1].copy()
    l = lo.loc[lo["entry_bucket"] == 1].copy()
    hk = trade_key(h)
    lk = set(trade_key(l).tolist()) if len(l) else set()
    return h.loc[~hk.isin(lk)].copy()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--output", required=True)
    ap.add_argument("--analysis-start", default="2016-01-04")
    ap.add_argument("--analysis-end", default="2026-06-20")
    ap.add_argument("--max-tickers", type=int, default=6000)
    ap.add_argument("--batch-size", type=int, default=75)
    args = ap.parse_args()

    root = Path(args.root)
    out = root / args.output
    out.mkdir(parents=True, exist_ok=True)
    meta, matrices = base.build_inputs(root, args.analysis_start, args.analysis_end, args.max_tickers, args.batch_size)

    result = {
        "status": "SELECTIVE_BAND_MARGINAL_SLOT_AUDIT",
        "question": "Does the fifth selective slot add robust value beyond 4/12, and does the fourth add robust value beyond 3/12?",
        "anchors": {},
        "pooled_marginals": {},
    }
    pooled_4th = []
    pooled_5th = []

    for anchor in ANCHORS:
        base.REBAL_ANCHOR = anchor
        mm = dict(meta)
        mm["rebalance"] = base.build_rebalance_flags(matrices["close"].index)
        sims = {}
        for slots in SLOTS:
            print(f"SIM anchor={anchor.date()} slots={slots}", flush=True)
            sims[slots] = base.simulate(mm, matrices, selective_slots=slots, red_confirm_sessions=1, immediate_red_recovery=True)
        fourth = marginal_extra(sims[4]["trades"], sims[3]["trades"])
        fifth = marginal_extra(sims[5]["trades"], sims[4]["trades"])
        pooled_4th.append(fourth.assign(anchor=str(anchor.date())))
        pooled_5th.append(fifth.assign(anchor=str(anchor.date())))
        akey = str(anchor.date())
        result["anchors"][akey] = {
            "equity_metrics": {
                str(s): sims[s]["metrics"] for s in SLOTS
            },
            "equity_bootstrap_vs4": {
                "3_vs4": base.bootstrap_block_win(sims[3]["equity"], sims[4]["equity"], block=20, reps=5000, seed=31001),
                "5_vs4": base.bootstrap_block_win(sims[5]["equity"], sims[4]["equity"], block=20, reps=5000, seed=31002),
            },
            "fourth_slot_extra_trades": summarize(fourth),
            "fourth_slot_cluster_bootstrap": cluster_bootstrap_mean(fourth, reps=5000, seed=41001),
            "fifth_slot_extra_trades": summarize(fifth),
            "fifth_slot_cluster_bootstrap": cluster_bootstrap_mean(fifth, reps=5000, seed=41002),
        }
        if len(fourth): fourth.to_csv(out / f"fourth_slot_{anchor.strftime('%Y%m%d')}.csv", index=False)
        if len(fifth): fifth.to_csv(out / f"fifth_slot_{anchor.strftime('%Y%m%d')}.csv", index=False)

    p4 = pd.concat(pooled_4th, ignore_index=True) if pooled_4th else pd.DataFrame()
    p5 = pd.concat(pooled_5th, ignore_index=True) if pooled_5th else pd.DataFrame()
    result["pooled_marginals"] = {
        "fourth_slot": summarize(p4),
        "fourth_slot_cluster_bootstrap": cluster_bootstrap_mean(p4, reps=10000, seed=51001),
        "fifth_slot": summarize(p5),
        "fifth_slot_cluster_bootstrap": cluster_bootstrap_mean(p5, reps=10000, seed=51002),
    }

    (out / "summary_marginal.json").write_text(json.dumps(base.safe(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== SELECTIVE_MARGINAL_RESULT_JSON ===", flush=True)
    print(json.dumps(base.safe(result), ensure_ascii=False, indent=2), flush=True)
    print("=== END_SELECTIVE_MARGINAL_RESULT_JSON ===", flush=True)


if __name__ == "__main__":
    main()
