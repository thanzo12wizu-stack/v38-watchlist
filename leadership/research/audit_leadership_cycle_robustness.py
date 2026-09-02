from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import audit_leadership_cycle as lc
import audit_ordinary_stock_market_mode_robustness as base

F2_GRID = (0.30, 0.40, 0.50)
TEMP_GRID = (10.0, 15.0, 20.0)
COOLDOWNS = (20, 40)
DD_CUTOFFS = (-0.08, -0.10, -0.12)
HORIZONS = (20, 40, 60)


def split_name(d: pd.Timestamp) -> str:
    return "DISCOVERY" if d <= lc.DISC_END else "CONFIRMATION"


def breadth_bucket(x: float) -> str:
    if not np.isfinite(x):
        return "NA"
    if x < 40: return "LT40"
    if x < 50: return "40_50"
    if x < 60: return "50_60"
    return "GE60"


def q20_bucket(x: float) -> str:
    if not np.isfinite(x): return "NA"
    if x < -0.10: return "LT_M10"
    if x < -0.05: return "M10_M5"
    if x < 0.0: return "M5_0"
    if x < 0.05: return "0_5"
    return "GE5"


def outcome_at_dates(name: str, dates: list[pd.Timestamp], market: dict[str, pd.DataFrame], nq: pd.Series) -> pd.DataFrame:
    return lc.outcome_rows(name, dates, market["QQQ"], market["SPY"], nq)


def compact(df: pd.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {"n": int(len(df))}
    for h in HORIZONS:
        q = pd.to_numeric(df.get(f"qqq_ret_{h}"), errors="coerce").dropna()
        s = pd.to_numeric(df.get(f"spy_ret_{h}"), errors="coerce").dropna()
        both = pd.concat([q.rename("q"), s.rename("s")], axis=1).dropna()
        mdd = pd.to_numeric(df.get(f"qqq_mdd_{h}"), errors="coerce").dropna()
        out[f"qqq_ret{h}_mean"] = float(q.mean()) if len(q) else None
        out[f"qqq_ret{h}_median"] = float(q.median()) if len(q) else None
        out[f"spy_ret{h}_mean"] = float(s.mean()) if len(s) else None
        out[f"qqq_minus_spy{h}_mean"] = float((both.q-both.s).mean()) if len(both) else None
        out[f"mdd{h}_mean"] = float(mdd.mean()) if len(mdd) else None
        for c in DD_CUTOFFS:
            out[f"p_mdd{h}_le_{abs(int(c*100))}"] = float((mdd <= c).mean()) if len(mdd) else None
    return out


def bootstrap_diff(event: pd.DataFrame, control: pd.DataFrame, col: str, seed: int = 1, reps: int = 5000) -> dict[str, Any]:
    a = pd.to_numeric(event.get(col), errors="coerce").dropna().to_numpy(float)
    b = pd.to_numeric(control.get(col), errors="coerce").dropna().to_numpy(float)
    if len(a) < 5 or len(b) < 10:
        return {"n_event": int(len(a)), "n_control": int(len(b))}
    rng = np.random.default_rng(seed)
    d = np.empty(reps)
    for i in range(reps):
        aa = rng.choice(a, size=len(a), replace=True)
        bb = rng.choice(b, size=len(b), replace=True)
        d[i] = aa.mean() - bb.mean()
    return {
        "n_event": int(len(a)), "n_control": int(len(b)),
        "mean_diff": float(a.mean()-b.mean()),
        "ci05": float(np.quantile(d, .05)), "ci95": float(np.quantile(d, .95)),
        "prob_event_gt_control": float((d > 0).mean()),
    }


def matched_controls(sig: pd.DataFrame, event_dates: list[pd.Timestamp], market: dict[str, pd.DataFrame], nq: pd.Series, breadth: pd.Series, cooldown: int) -> list[pd.Timestamp]:
    idx = sig.index.intersection(market["QQQ"].index)
    qqq = market["QQQ"]["Close"].reindex(idx)
    q20 = qqq.pct_change(20, fill_method=None)
    strata = pd.DataFrame(index=idx)
    strata["nq"] = nq.reindex(idx).astype(str)
    strata["bb"] = breadth.reindex(idx).map(breadth_bucket)
    strata["q20"] = q20.map(q20_bucket)
    strata["split"] = [split_name(pd.Timestamp(d)) for d in idx]
    event_set = set(event_dates)
    controls: list[pd.Timestamp] = []
    used: set[pd.Timestamp] = set()
    for e in event_dates:
        if e not in strata.index:
            continue
        row = strata.loc[e]
        cand = strata[(strata.nq == row.nq) & (strata.bb == row.bb) & (strata.q20 == row.q20) & (strata.split == row.split)].index
        cand = [pd.Timestamp(d) for d in cand if d not in event_set and d not in used and abs((pd.Timestamp(d)-e).days) > cooldown]
        if not cand:
            continue
        cand.sort(key=lambda d: abs((d-e).days))
        pick = cand[0]
        controls.append(pick); used.add(pick)
    return controls


def grid_audit(sig: pd.DataFrame, market: dict[str, pd.DataFrame], nq: pd.Series, breadth: pd.Series) -> pd.DataFrame:
    rows = []
    for f2 in F2_GRID:
        for temp in TEMP_GRID:
            mask = (sig.f2 >= f2) & (sig.leader_temp <= temp)
            for cd in COOLDOWNS:
                events = lc.eventize(mask, cooldown=cd)
                controls = matched_controls(sig, events, market, nq, breadth, cd)
                edf = outcome_at_dates("event", events, market, nq)
                cdf = outcome_at_dates("control", controls, market, nq)
                for split in ("DISCOVERY", "CONFIRMATION"):
                    e = edf[pd.to_datetime(edf.signal_date).map(split_name) == split] if len(edf) else edf
                    c = cdf[pd.to_datetime(cdf.signal_date).map(split_name) == split] if len(cdf) else cdf
                    rec = {"f2": f2, "temp": temp, "cooldown": cd, "split": split, **compact(e)}
                    rec["matched_n"] = int(len(c))
                    rec["qqq60_vs_matched"] = bootstrap_diff(e, c, "qqq_ret_60", seed=int(f2*1000+temp*10+cd))
                    rec["spy60_vs_matched"] = bootstrap_diff(e, c, "spy_ret_60", seed=int(f2*2000+temp*10+cd))
                    rec["mdd60_vs_matched"] = bootstrap_diff(e, c, "qqq_mdd_60", seed=int(f2*3000+temp*10+cd))
                    rows.append(rec)
    return pd.DataFrame(rows)


def correction_sequence(sig: pd.DataFrame, market: dict[str, pd.DataFrame]) -> list[dict[str, Any]]:
    q = market["QQQ"]["Close"].reindex(sig.index).dropna()
    high63 = q.rolling(63, min_periods=40).max()
    dd = q/high63 - 1.0
    out = []
    conditions = {
        "F1": sig.f1 >= 0.30,
        "F2": sig.f2 >= 0.40,
        "F3": sig.f3 >= 0.60,
        "EXH": sig.leader_temp <= 15.0,
    }
    for cut in (-0.08, -0.10, -0.12):
        crosses = (dd <= cut) & ~(dd.shift(1) <= cut)
        dates = lc.eventize(crosses, cooldown=60)
        for d in dates:
            if d not in q.index: continue
            p = q.index.get_loc(d)
            end = min(len(q)-1, p+40)
            trough_slice = q.iloc[p:end+1]
            trough = pd.Timestamp(trough_slice.idxmin())
            tp = q.index.get_loc(trough)
            start = max(0, tp-60)
            window = q.index[start:tp+1]
            firsts = {}
            for name, cond in conditions.items():
                z = cond.reindex(window).fillna(False)
                hit = z[z].index
                firsts[name] = pd.Timestamp(hit[0]) if len(hit) else None
            rec = {"cut": cut, "cross": d, "trough": trough, "split": split_name(d)}
            for name, fd in firsts.items():
                rec[name] = fd
                rec[f"{name}_lead_to_trough"] = int((q.index.get_loc(trough)-q.index.get_loc(fd))) if fd in q.index else None
            names = [n for n,v in firsts.items() if v is not None]
            rec["order"] = ">".join(sorted(names, key=lambda n: firsts[n]))
            out.append(rec)
    return out


def pairwise_sequence(seq: list[dict[str, Any]]) -> dict[str, Any]:
    pairs = [("F1","F2"),("F2","F3"),("F3","EXH"),("F2","EXH"),("F1","EXH")]
    out = {}
    for split in ("DISCOVERY","CONFIRMATION"):
        rows = [r for r in seq if r["split"] == split]
        s = {}
        for a,b in pairs:
            both = [r for r in rows if r.get(a) is not None and r.get(b) is not None]
            s[f"{a}_before_{b}"] = {"n": len(both), "share": float(np.mean([r[a] <= r[b] for r in both])) if both else None}
        out[split] = s
    return out


def hashed_subset(cols: list[str], frac: float) -> list[str]:
    keep = []
    for s in cols:
        h = int(hashlib.sha1(s.encode()).hexdigest()[:8], 16)/0xFFFFFFFF
        if h < frac: keep.append(s)
    return keep


def membership_audit(matrices: dict[str, pd.DataFrame], full_sig: pd.DataFrame, market: dict[str, pd.DataFrame], nq: pd.Series) -> list[dict[str, Any]]:
    cols = list(matrices["close"].columns)
    out = []
    for frac in (0.50, 0.75, 1.0):
        if frac == 1.0:
            sig = full_sig
            n = len(cols)
        else:
            sub = hashed_subset(cols, frac)
            n = len(sub)
            sig = lc.build_leadership_series({"close": matrices["close"][sub], "dvol": matrices["dvol"][sub]}).reindex(full_sig.index)
        mask = (sig.f2 >= .40) & (sig.leader_temp <= 15.0)
        ev = lc.eventize(mask, cooldown=20)
        edf = outcome_at_dates(f"frac{frac}", ev, market, nq)
        for split in ("DISCOVERY","CONFIRMATION"):
            z = edf[pd.to_datetime(edf.signal_date).map(split_name)==split] if len(edf) else edf
            out.append({"frac": frac, "symbols": n, "split": split, **compact(z)})
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
    root = Path(args.root); out = root/args.output; out.mkdir(parents=True, exist_ok=True)

    meta, matrices = base.build_inputs(root, args.analysis_start, args.analysis_end, args.max_tickers, args.batch_size)
    idx = pd.DatetimeIndex(meta["analysis_idx"])
    sig = lc.build_leadership_series(matrices).reindex(idx)
    breadth = meta["breadth"].reindex(idx)
    nq = meta["nq"]["nq_color"].reindex(idx)
    market = lc.download_market(str((idx.min()-pd.Timedelta(days=400)).date()), str((idx.max()+pd.Timedelta(days=100)).date()))

    grid = grid_audit(sig, market, nq, breadth)
    grid.to_json(out/"threshold_grid.json", orient="records", indent=2)
    seq = correction_sequence(sig, market)
    pd.DataFrame(seq).to_csv(out/"correction_sequence.csv", index=False)
    membership = membership_audit(matrices, sig, market, nq)
    pd.DataFrame(membership).to_json(out/"membership_perturbation.json", orient="records", indent=2)

    frozen = grid[(grid.f2 == .40) & (grid.temp == 15.0) & (grid.cooldown == 20)].to_dict("records")
    result = {
        "status": "LEADERSHIP_CYCLE_ROBUSTNESS_COMPLETE",
        "frozen_candidate": "F2>=40% AND Leader Temperature<=15; context-only, not hard gate",
        "frozen_results": frozen,
        "sequence_pairwise": pairwise_sequence(seq),
        "membership_perturbation": membership,
        "limitations": [
            "Historical delisted/removed-stock point-in-time membership is not available in the repository; deterministic membership perturbation tests composition sensitivity but does not eliminate survivorship bias.",
            "Threshold neighborhood is a robustness check, not authorization to optimize on Confirmation.",
            "Matched controls use NQSAR color, stock breadth bucket, QQQ 20-session return bucket, and same Discovery/Confirmation split.",
        ],
    }
    (out/"summary_robustness.json").write_text(json.dumps(lc.safe(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(lc.safe(result), ensure_ascii=False, indent=2), flush=True)

if __name__ == "__main__":
    main()
