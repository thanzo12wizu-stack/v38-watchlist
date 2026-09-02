from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import audit_leadership_cycle as lc
import audit_ordinary_stock_market_mode_robustness as base

DISC_END = pd.Timestamp("2021-12-31")
CONF_START = pd.Timestamp("2022-01-03")


def safe(v: Any) -> Any:
    if isinstance(v, dict):
        return {str(k): safe(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [safe(x) for x in v]
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        x = float(v)
        return x if math.isfinite(x) else None
    if isinstance(v, pd.Timestamp):
        return v.isoformat()
    return v


def market_mode(nq: pd.Series, breadth: pd.Series) -> pd.Series:
    out = pd.Series("UNKNOWN", index=nq.index, dtype=object)
    out.loc[nq.eq("Red")] = "DEFENSE"
    out.loc[nq.eq("Yellow")] = "STOP"
    bull = nq.isin(["Blue", "Green"])
    out.loc[bull & (breadth < 50.0)] = "STOP"
    out.loc[bull & (breadth >= 50.0) & (breadth < 60.0)] = "SELECTIVE"
    out.loc[bull & (breadth >= 60.0)] = "ATTACK"
    return out


def cross_below(s: pd.Series, th: float) -> pd.Series:
    return (s < th) & (s.shift(1) >= th)


def recent_low(s: pd.Series, th: float, lookback: int) -> pd.Series:
    return s.shift(1).rolling(lookback, min_periods=1).min() <= th


def recent_high(s: pd.Series, th: float, lookback: int) -> pd.Series:
    return s.shift(1).rolling(lookback, min_periods=1).max() >= th


def add_market_features(sig: pd.DataFrame, breadth: pd.Series, nq: pd.Series, qqq: pd.DataFrame) -> pd.DataFrame:
    x = sig.copy()
    x["breadth50"] = breadth
    x["nqsar"] = nq
    x["mode"] = market_mode(nq, breadth)
    x["gate_on"] = x["mode"].isin(["ATTACK", "SELECTIVE"])
    qclose = qqq["Close"].reindex(x.index)
    x["qqq_close"] = qclose
    x["qqq_ret20_back"] = qclose.pct_change(20, fill_method=None)
    x["split"] = np.where(x.index <= DISC_END, "DISCOVERY", "CONFIRMATION")
    return x


def eventize(mask: pd.Series, cooldown: int) -> list[pd.Timestamp]:
    m = mask.fillna(False).astype(bool)
    cross = m & ~m.shift(1, fill_value=False)
    out: list[pd.Timestamp] = []
    last = -10**9
    for i, v in enumerate(cross.to_numpy(bool)):
        if v and i - last >= cooldown:
            out.append(pd.Timestamp(cross.index[i]))
            last = i
    return out


def outcome_table(dates: list[pd.Timestamp], qqq: pd.DataFrame, spy: pd.DataFrame, nq: pd.Series) -> pd.DataFrame:
    z = lc.outcome_rows("COMBO", dates, qqq, spy, nq)
    if z.empty:
        return z
    for h in (20, 40, 60):
        q = pd.to_numeric(z.get(f"qqq_ret_{h}"), errors="coerce")
        s = pd.to_numeric(z.get(f"spy_ret_{h}"), errors="coerce")
        z[f"excess_{h}"] = q - s
    return z


def bootstrap_pair_delta(a: np.ndarray, b: np.ndarray, seed: int, n_boot: int = 10000) -> dict[str, Any]:
    ok = np.isfinite(a) & np.isfinite(b)
    d = np.asarray(a[ok] - b[ok], float)
    if len(d) < 3:
        return {"n": int(len(d))}
    rng = np.random.default_rng(seed)
    draw = rng.integers(0, len(d), size=(n_boot, len(d)))
    means = d[draw].mean(axis=1)
    return {
        "n": int(len(d)),
        "mean_delta": float(d.mean()),
        "median_delta": float(np.median(d)),
        "ci025": float(np.quantile(means, 0.025)),
        "ci05": float(np.quantile(means, 0.05)),
        "ci95": float(np.quantile(means, 0.95)),
        "ci975": float(np.quantile(means, 0.975)),
        "prob_delta_gt0": float((means > 0).mean()),
    }


def nearest_pairs(frame: pd.DataFrame, event_dates: list[pd.Timestamp], signal_mask: pd.Series, require_f2_below40: bool) -> list[tuple[pd.Timestamp, pd.Timestamp, float]]:
    feats = ["breadth50", "qqq_ret20_back", "f1", "f2", "f3", "leader_temp"]
    pairs: list[tuple[pd.Timestamp, pd.Timestamp, float]] = []
    used: set[pd.Timestamp] = set()
    for d in event_dates:
        if d not in frame.index:
            continue
        r = frame.loc[d]
        pool = frame.loc[(frame["split"] == r["split"]) & (frame["mode"] == r["mode"]) & (frame["nqsar"] == r["nqsar"]) & (~signal_mask.reindex(frame.index).fillna(False))].copy()
        if require_f2_below40:
            pool = pool.loc[pool["f2"] < 0.40]
        if pool.empty:
            continue
        pos = frame.index.get_loc(d)
        keep = []
        for c in pool.index:
            cp = frame.index.get_loc(c)
            if abs(int(cp) - int(pos)) > 40 and c not in used:
                keep.append(c)
        pool = pool.loc[keep]
        if pool.empty:
            continue
        split_frame = frame.loc[frame["split"] == r["split"], feats]
        scale = (split_frame.quantile(0.75) - split_frame.quantile(0.25)).replace(0.0, np.nan)
        dist = ((pool[feats] - r[feats]).divide(scale) ** 2).sum(axis=1, skipna=False).dropna()
        if dist.empty:
            continue
        c = pd.Timestamp(dist.idxmin())
        used.add(c)
        pairs.append((d, c, float(dist.loc[c])))
    return pairs


def pair_report(name: str, frame: pd.DataFrame, mask: pd.Series, qqq: pd.DataFrame, spy: pd.DataFrame, nq: pd.Series, cooldown: int, require_f2_below40: bool, seed: int) -> dict[str, Any]:
    dates = eventize(mask, cooldown)
    result: dict[str, Any] = {"name": name, "cooldown": cooldown, "splits": {}}
    for split in ("DISCOVERY", "CONFIRMATION"):
        ds = [d for d in dates if d in frame.index and frame.at[d, "split"] == split]
        pairs = nearest_pairs(frame, ds, mask, require_f2_below40)
        ed = [a for a, _, _ in pairs]
        cd = [b for _, b, _ in pairs]
        eo = outcome_table(ed, qqq, spy, nq).set_index("signal_date") if ed else pd.DataFrame()
        co = outcome_table(cd, qqq, spy, nq).set_index("signal_date") if cd else pd.DataFrame()
        rec: dict[str, Any] = {
            "n_events": len(ds),
            "n_pairs": len(pairs),
            "event_dates": [str(d.date()) for d in ds],
            "mean_match_distance": float(np.mean([x[2] for x in pairs])) if pairs else None,
        }
        if pairs:
            for h in (20, 40, 60):
                for col in (f"qqq_ret_{h}", f"spy_ret_{h}", f"excess_{h}"):
                    a = pd.to_numeric(eo.reindex(ed).get(col), errors="coerce").to_numpy(float)
                    b = pd.to_numeric(co.reindex(cd).get(col), errors="coerce").to_numpy(float)
                    rec[col] = bootstrap_pair_delta(a, b, seed + h + len(col))
            for col in ("qqq_mdd_20", "qqq_mdd_40", "qqq_mdd_60"):
                a = pd.to_numeric(eo.reindex(ed).get(col), errors="coerce").to_numpy(float)
                b = pd.to_numeric(co.reindex(cd).get(col), errors="coerce").to_numpy(float)
                # Positive delta here means less-negative / better drawdown.
                rec[col] = bootstrap_pair_delta(a, b, seed + len(col))
            er = pd.to_numeric(eo.reindex(ed).get("qqq_ret_60"), errors="coerce").dropna()
            cr = pd.to_numeric(co.reindex(cd).get("qqq_ret_60"), errors="coerce").dropna()
            rec["event_ret60_mean"] = float(er.mean()) if len(er) else None
            rec["event_ret60_median"] = float(er.median()) if len(er) else None
            rec["event_ret60_win_rate"] = float((er > 0).mean()) if len(er) else None
            rec["control_ret60_mean"] = float(cr.mean()) if len(cr) else None
            rec["control_ret60_win_rate"] = float((cr > 0).mean()) if len(cr) else None
        result["splits"][split] = rec
    return result


def subset_matrices(matrices: dict[str, pd.DataFrame], fraction: float) -> dict[str, pd.DataFrame]:
    cols = list(matrices["close"].columns)
    keep = []
    for c in cols:
        h = int(hashlib.sha256(str(c).encode("utf-8")).hexdigest()[:12], 16) / float(16**12 - 1)
        if h < fraction:
            keep.append(c)
    return {k: v.loc[:, [c for c in keep if c in v.columns]].copy() for k, v in matrices.items() if isinstance(v, pd.DataFrame)}


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
    idx = pd.DatetimeIndex(meta["analysis_idx"])
    breadth = meta["breadth"].reindex(idx)
    nqf = meta["nq"].reindex(idx)
    nq = nqf["nq_color"].astype(object).ffill(limit=1)

    print("BUILD LEADERSHIP", flush=True)
    sig = lc.build_leadership_series(matrices).reindex(idx)

    market_start = str((pd.Timestamp(args.analysis_start) - pd.Timedelta(days=10)).date())
    market_end = str((pd.Timestamp(args.analysis_end) + pd.Timedelta(days=120)).date())
    print("DOWNLOAD MARKET", flush=True)
    market = lc.download_market(market_start, market_end)
    qqq = market["QQQ"]
    spy = market["SPY"].reindex(qqq.index).ffill(limit=1)
    frame = add_market_features(sig, breadth, nq, qqq)

    f1w = frame["f1"] >= 0.30
    f2w = frame["f2"] >= 0.40
    f3w = frame["f3"] >= 0.40
    f3s = frame["f3"] >= 0.60
    t15 = frame["leader_temp"] <= 15.0
    f2rec = cross_below(frame["f2"], 0.40)
    gate = frame["gate_on"]
    attack = frame["mode"].eq("ATTACK")

    state_masks = {
        "F1_F2": f1w & f2w,
        "F1_F3": f1w & f3w,
        "F2_F3": f2w & f3w,
        "F1_TEMP15": f1w & t15,
        "F3_TEMP15": f3w & t15,
        "F1_F2_TEMP15": f1w & f2w & t15,
        "F2_F3_TEMP15": f2w & f3w & t15,
    }

    regen_masks = {
        "F2_RECOVER_GATEON": f2rec & gate,
        "TEMP15_40_F2_RECOVER_GATEON": recent_low(frame["leader_temp"], 15.0, 40) & f2rec & gate,
        "TEMP15_40_F2_RECOVER_ATTACK": recent_low(frame["leader_temp"], 15.0, 40) & f2rec & attack,
        "F1WARN_40_F2_RECOVER_GATEON": recent_high(frame["f1"], 0.30, 40) & f2rec & gate,
        "F3SEV_40_F2_RECOVER_GATEON": recent_high(frame["f3"], 0.60, 40) & f2rec & gate,
    }

    reports: dict[str, Any] = {}
    print("STATE COMBOS", flush=True)
    for i, (name, mask) in enumerate(state_masks.items()):
        reports[name] = pair_report(name, frame, mask, qqq, spy, nq, 20, False, 20260920 + i)

    print("REGENERATION COMBOS", flush=True)
    for i, (name, mask) in enumerate(regen_masks.items()):
        reports[name] = pair_report(name, frame, mask, qqq, spy, nq, 20, True, 20261020 + i)
        reports[name + "_CD40"] = pair_report(name, frame, mask, qqq, spy, nq, 40, True, 20261120 + i)

    print("FROZEN REGEN SENSITIVITY", flush=True)
    sensitivity: list[dict[str, Any]] = []
    for temp in (10.0, 15.0, 20.0):
        for lookback in (20, 40, 60):
            for recut in (0.25, 0.40):
                rec = cross_below(frame["f2"], recut)
                for gate_name, gmask in (("GATE50", gate), ("ATTACK60", attack)):
                    mask = recent_low(frame["leader_temp"], temp, lookback) & rec & gmask
                    for cooldown in (20, 40):
                        rr = pair_report("SENS", frame, mask, qqq, spy, nq, cooldown, True, int(20262000 + temp * 10 + lookback + recut * 100 + cooldown))
                        for split in ("DISCOVERY", "CONFIRMATION"):
                            sr = rr["splits"][split]
                            q60 = sr.get("qqq_ret_60", {})
                            x60 = sr.get("excess_60", {})
                            d60 = sr.get("qqq_mdd_60", {})
                            sensitivity.append({
                                "temp": temp, "lookback": lookback, "f2_recover_below": recut,
                                "gate": gate_name, "cooldown": cooldown, "split": split,
                                "n_events": sr.get("n_events"), "n_pairs": sr.get("n_pairs"),
                                "event_ret60_mean": sr.get("event_ret60_mean"),
                                "event_ret60_win_rate": sr.get("event_ret60_win_rate"),
                                "qqq60_delta": q60.get("mean_delta"), "qqq60_ci05": q60.get("ci05"), "qqq60_ci95": q60.get("ci95"), "qqq60_prob_gt0": q60.get("prob_delta_gt0"),
                                "excess60_delta": x60.get("mean_delta"), "excess60_ci05": x60.get("ci05"), "excess60_ci95": x60.get("ci95"), "excess60_prob_gt0": x60.get("prob_delta_gt0"),
                                "mdd60_delta": d60.get("mean_delta"), "mdd60_prob_gt0": d60.get("prob_delta_gt0"),
                            })

    print("2020 EXCLUSION", flush=True)
    frozen = regen_masks["TEMP15_40_F2_RECOVER_GATEON"]
    frozen_dates = eventize(frozen, 20)
    ex2020: dict[str, Any] = {}
    for split in ("DISCOVERY", "CONFIRMATION"):
        dates = [d for d in frozen_dates if frame.at[d, "split"] == split and d.year != 2020]
        temp_mask = frozen.copy()
        temp_mask.loc[temp_mask.index.year == 2020] = False
        ex2020[split] = pair_report("EX2020", frame, temp_mask, qqq, spy, nq, 20, True, 20263020)["splits"][split]

    print("MEMBERSHIP PERTURBATION", flush=True)
    membership: list[dict[str, Any]] = []
    full_dates = set(eventize(frozen, 20))
    for frac in (0.50, 0.75, 1.00):
        if frac == 1.0:
            fsig = sig
            ncols = matrices["close"].shape[1]
        else:
            sub = subset_matrices(matrices, frac)
            ncols = sub["close"].shape[1]
            fsig = lc.build_leadership_series(sub).reindex(idx)
        ff = add_market_features(fsig, breadth, nq, qqq)
        fmask = recent_low(ff["leader_temp"], 15.0, 40) & cross_below(ff["f2"], 0.40) & ff["gate_on"]
        fdates = eventize(fmask, 20)
        fset = set(fdates)
        overlap = len(full_dates & fset) / len(full_dates | fset) if (full_dates | fset) else None
        for split in ("DISCOVERY", "CONFIRMATION"):
            ds = [d for d in fdates if ff.at[d, "split"] == split]
            oo = outcome_table(ds, qqq, spy, nq)
            rr = pd.to_numeric(oo.get("qqq_ret_60"), errors="coerce").dropna() if len(oo) else pd.Series(dtype=float)
            xx = pd.to_numeric(oo.get("excess_60"), errors="coerce").dropna() if len(oo) else pd.Series(dtype=float)
            membership.append({
                "fraction": frac, "symbols": ncols, "split": split, "n_events": len(ds),
                "event_ret60_mean": float(rr.mean()) if len(rr) else None,
                "event_ret60_win_rate": float((rr > 0).mean()) if len(rr) else None,
                "event_excess60_mean": float(xx.mean()) if len(xx) else None,
                "event_date_jaccard_vs_full": overlap,
            })

    pd.DataFrame(sensitivity).to_csv(out / "combination_sensitivity.csv", index=False)
    pd.DataFrame(membership).to_csv(out / "regeneration_membership.csv", index=False)
    frame.to_csv(out / "combination_series.csv")

    result = {
        "status": "LEADERSHIP_COMBINATION_AUDIT",
        "scope": "Combination and ordered-regeneration tests only; no production/main/dashboard changes",
        "coverage": {"selected": meta.get("selected"), "downloaded": meta.get("downloaded"), "analysis_sessions": len(idx)},
        "method": {
            "discovery_end": str(DISC_END.date()), "confirmation_start": str(CONF_START.date()),
            "matching": "same split + same current market mode + same NQSAR color; nearest current breadth, QQQ20 return, F1/F2/F3/Temperature; controls outside +/-40 sessions; no replacement",
            "bootstrap": "paired event-minus-matched-control, 10,000 resamples; 90% and 95% intervals",
            "warning": "Regeneration candidate was discovered during retrospective research; Confirmation is robustness evidence, not pristine prospective OOS. Current-universe survivorship remains.",
        },
        "reports": reports,
        "exclude_2020": ex2020,
        "membership": membership,
        "sensitivity_file": "combination_sensitivity.csv",
        "membership_file": "regeneration_membership.csv",
    }
    (out / "summary_combinations.json").write_text(json.dumps(safe(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== COMBINATION_AUDIT_RESULT ===", flush=True)
    print(json.dumps(safe(result), ensure_ascii=False, indent=2), flush=True)
    print("=== END_COMBINATION_AUDIT_RESULT ===", flush=True)


if __name__ == "__main__":
    main()
