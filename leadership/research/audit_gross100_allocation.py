from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path

import numpy as np
import pandas as pd

TQQQ_COST = 5.0 / 10000.0
TRADING_DAYS = 252


def metrics(ret: np.ndarray) -> dict:
    r = np.nan_to_num(np.asarray(ret, float), nan=0.0, posinf=0.0, neginf=0.0)
    if len(r) == 0:
        return {"cagr": np.nan, "mdd": np.nan, "sharpe": np.nan, "calmar": np.nan, "end": np.nan}
    eq = np.cumprod(1.0 + r)
    years = max((len(r) - 1) / TRADING_DAYS, 1e-9)
    end = float(eq[-1])
    cagr = float(end ** (1.0 / years) - 1.0) if end > 0 else -1.0
    peak = np.maximum.accumulate(eq)
    mdd = float(np.min(eq / peak - 1.0))
    sd = float(np.std(r, ddof=1))
    sharpe = float(np.sqrt(TRADING_DAYS) * np.mean(r) / sd) if sd > 0 else np.nan
    calmar = float(cagr / abs(mdd)) if mdd < 0 else np.nan
    return {"cagr": cagr, "mdd": mdd, "sharpe": sharpe, "calmar": calmar, "end": end}


def priority_alloc(g: np.ndarray, order: str) -> np.ndarray:
    out = np.zeros_like(g)
    ix = {"T": 0, "O": 1, "R": 2}
    for i, row in enumerate(g):
        rem = 1.0
        for name in order:
            j = ix[name]
            a = min(max(float(row[j]), 0.0), rem)
            out[i, j] = a
            rem -= a
            if rem <= 1e-12:
                break
    return out


def proportional_alloc(g: np.ndarray) -> np.ndarray:
    total = g.sum(axis=1)
    scale = np.ones(len(g), float)
    hit = total > 1.0
    scale[hit] = 1.0 / total[hit]
    return g * scale[:, None]


def weighted_waterfill(g: np.ndarray, weights: tuple[float, float, float]) -> np.ndarray:
    w = np.asarray(weights, float)
    out = np.zeros_like(g)
    for i, row in enumerate(g):
        if row.sum() <= 1.0:
            out[i] = row
            continue
        lo, hi = 0.0, 10.0
        for _ in range(60):
            mid = (lo + hi) / 2.0
            s = float(np.minimum(row, mid * w).sum())
            if s < 1.0:
                lo = mid
            else:
                hi = mid
        out[i] = np.minimum(row, hi * w)
    return out


def reset_first_tqqq_floor(g: np.ndarray, floor: float) -> np.ndarray:
    """
    Gross100 rule:
      1) keep RSI Reset desired gross first;
      2) if conflict remains, protect TQQQ up to floor;
      3) fill ordinary-stock desired gross;
      4) any remaining capacity returns to TQQQ up to its desired target.
    """
    out = np.zeros_like(g)
    for i, row in enumerate(g):
        t, o, r = [max(float(x), 0.0) for x in row]
        rem = 1.0
        ar = min(r, rem)
        out[i, 2] = ar
        rem -= ar
        if t + o <= rem + 1e-12:
            out[i, 0] = t
            out[i, 1] = o
            continue
        protect = min(t, floor, rem)
        out[i, 0] = protect
        rem -= protect
        ao = min(o, rem)
        out[i, 1] = ao
        rem -= ao
        out[i, 0] += min(max(t - out[i, 0], 0.0), rem)
    return out


def scaled_returns(
    alloc: np.ndarray,
    desired_o: np.ndarray,
    desired_r: np.ndarray,
    ret_t: np.ndarray,
    ret_o: np.ndarray,
    ret_r: np.ndarray,
    all_turnover_cost_bps: float | None = None,
) -> tuple[np.ndarray, dict]:
    a_t, a_o, a_r = alloc.T
    s_o = np.divide(a_o, desired_o, out=np.zeros_like(a_o), where=desired_o > 1e-12)
    s_r = np.divide(a_r, desired_r, out=np.zeros_like(a_r), where=desired_r > 1e-12)
    ret = a_t * ret_t + s_o * ret_o + s_r * ret_r

    if all_turnover_cost_bps is None:
        turn_t = np.zeros(len(ret), float)
        turn_t[1:] = np.abs(np.diff(a_t))
        ret -= turn_t * TQQQ_COST
        turnover = {
            "turn_t": float(turn_t.sum()),
            "turn_o": np.nan,
            "turn_r": np.nan,
            "cost_mode": "TQQQ_5BP_ONLY_COMPONENT_RETURNS_AS_GENERATED",
        }
    else:
        c = float(all_turnover_cost_bps) / 10000.0
        turn_t = np.zeros(len(ret), float)
        turn_o = np.zeros(len(ret), float)
        turn_r = np.zeros(len(ret), float)
        turn_t[1:] = np.abs(np.diff(a_t))
        turn_o[1:] = np.abs(np.diff(a_o))
        turn_r[1:] = np.abs(np.diff(a_r))
        ret -= (turn_t + turn_o + turn_r) * c
        turnover = {
            "turn_t": float(turn_t.sum()),
            "turn_o": float(turn_o.sum()),
            "turn_r": float(turn_r.sum()),
            "cost_mode": f"CONSERVATIVE_ALL_ALLOCATED_GROSS_{all_turnover_cost_bps:g}BP",
        }
    return ret, turnover


def rolling252(ret: np.ndarray) -> dict:
    s = pd.Series(np.asarray(ret, float))
    z = (1.0 + s).rolling(252).apply(np.prod, raw=True) - 1.0
    z = z.dropna()
    return {
        "rolling252_positive": float((z > 0).mean()),
        "rolling252_worst": float(z.min()),
        "rolling252_median": float(z.median()),
        "rolling252_p10": float(z.quantile(0.10)),
        "rolling252_p90": float(z.quantile(0.90)),
    }


def block_boot_pair(a: np.ndarray, b: np.ndarray, block: int, nsim: int, seed: int) -> dict:
    a = np.asarray(a, float)
    b = np.asarray(b, float)
    n = len(a)
    horizon = n
    rng = np.random.default_rng(seed)
    nb = int(np.ceil(horizon / block))
    starts = rng.integers(0, n - block + 1, size=(nsim, nb))
    offs = np.arange(block)
    ret_win = []
    mdd_win = []
    cal_win = []
    cagr_diff = []
    batch = 250
    years = horizon / TRADING_DAYS
    for s in range(0, nsim, batch):
        st = starts[s:s + batch]
        ix = (st[:, :, None] + offs).reshape(len(st), -1)[:, :horizon]
        aa = a[ix]
        bb = b[ix]
        la = np.log1p(aa).sum(axis=1)
        lb = np.log1p(bb).sum(axis=1)
        ca = np.exp(la / years) - 1.0
        cb = np.exp(lb / years) - 1.0
        eqa = np.cumprod(1.0 + aa, axis=1)
        eqb = np.cumprod(1.0 + bb, axis=1)
        mdda = (eqa / np.maximum.accumulate(eqa, axis=1) - 1.0).min(axis=1)
        mddb = (eqb / np.maximum.accumulate(eqb, axis=1) - 1.0).min(axis=1)
        cala = ca / np.maximum(np.abs(mdda), 1e-12)
        calb = cb / np.maximum(np.abs(mddb), 1e-12)
        ret_win.append(la > lb)
        mdd_win.append(mdda >= mddb)
        cal_win.append(cala > calb)
        cagr_diff.append(ca - cb)
    rw = np.concatenate(ret_win)
    mw = np.concatenate(mdd_win)
    cw = np.concatenate(cal_win)
    cd = np.concatenate(cagr_diff)
    return {
        "block": int(block),
        "nsim": int(nsim),
        "p_return_a_gt_b": float(rw.mean()),
        "p_mdd_a_no_worse": float(mw.mean()),
        "p_calmar_a_gt_b": float(cw.mean()),
        "cagr_diff_median": float(np.median(cd)),
        "cagr_diff_p05": float(np.quantile(cd, 0.05)),
        "cagr_diff_p95": float(np.quantile(cd, 0.95)),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--components-dir", required=True)
    ap.add_argument("--tqqq-daily", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--tqqq-target", default="target_M30_TOUCH30_F80_D10")
    ap.add_argument("--bootstrap-sims", type=int, default=5000)
    args = ap.parse_args()

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    comp = Path(args.components_dir)

    ordinary = pd.read_csv(comp / "ordinary_PEAK30_PART25_R3_daily.csv.gz", compression="gzip")
    reset = pd.read_csv(comp / "rsi_RESET_RISE30_S029_P4_H20_daily.csv.gz", compression="gzip")
    tq = pd.read_csv(args.tqqq_daily, compression="gzip")
    for x in (ordinary, reset, tq):
        x["date"] = pd.to_datetime(x["date"])

    d = ordinary.merge(reset, on="date", suffixes=("_ord", "_rsi")).merge(tq, on="date", how="inner")
    if args.tqqq_target not in d.columns:
        raise KeyError(args.tqqq_target)
    n = len(d)
    target = d[args.tqqq_target].to_numpy(float)
    eff_t = np.zeros(n, float)
    eff_t[2:] = target[:-2]
    ret_t = d["tqqq_ret_usd"].to_numpy(float)
    ret_o = d["return_ord"].to_numpy(float)
    ret_r = d["return_rsi"].to_numpy(float)
    base_o = d["gross_exposure_ord"].to_numpy(float)
    base_r = d["gross_exposure_rsi"].to_numpy(float)

    timings = {
        "SAME_DAY_GROSS": (base_o.copy(), base_r.copy()),
        "LAG1_GROSS": (np.r_[0.0, base_o[:-1]], np.r_[0.0, base_r[:-1]]),
    }
    periods = [
        ("FULL", d.date.min(), d.date.max()),
        ("2016_2021", pd.Timestamp("2016-01-04"), pd.Timestamp("2021-12-31")),
        ("2022_2026M3", pd.Timestamp("2022-01-01"), pd.Timestamp("2026-03-20")),
        ("2022_2023", pd.Timestamp("2022-01-01"), pd.Timestamp("2023-12-31")),
        ("2024_2026M3", pd.Timestamp("2024-01-01"), pd.Timestamp("2026-03-20")),
    ]

    all_perf = []
    all_period = []
    all_roll = []
    all_alloc = []
    daily_keep = {}
    variant_returns = {}

    for timing, (g_o, g_r) in timings.items():
        g = np.column_stack([eff_t, g_o, g_r])
        variants: dict[str, np.ndarray] = {}
        for p in itertools.permutations("TOR"):
            nm = "PRIORITY_" + "".join(p)
            variants[nm] = priority_alloc(g, "".join(p))
        variants["PROPORTIONAL"] = proportional_alloc(g)
        variants["WATER_T2"] = weighted_waterfill(g, (2.0, 1.0, 1.0))
        variants["WATER_R2"] = weighted_waterfill(g, (1.0, 1.0, 2.0))
        variants["WATER_T2R2"] = weighted_waterfill(g, (2.0, 1.0, 2.0))
        for k in range(30, 101, 5):
            variants[f"RESET_TFLOOR_{k:03d}"] = reset_first_tqqq_floor(g, k / 100.0)

        cost_specs = [("BASE", None), ("ALL5", 5.0), ("ALL10", 10.0), ("ALL20", 20.0)]
        for cname, cbps in cost_specs:
            for nm, a in variants.items():
                rr, turn = scaled_returns(a, g_o, g_r, ret_t, ret_o, ret_r, cbps)
                key = f"{timing}|{cname}|{nm}"
                variant_returns[key] = rr
                met = metrics(rr)
                all_perf.append({
                    "timing": timing, "cost": cname, "variant": nm, **met,
                    "avg_alloc_t": float(a[:, 0].mean()),
                    "avg_alloc_o": float(a[:, 1].mean()),
                    "avg_alloc_r": float(a[:, 2].mean()),
                    "avg_total_gross": float(a.sum(axis=1).mean()),
                    "max_total_gross": float(a.sum(axis=1).max()),
                    "pct_at_100": float((a.sum(axis=1) >= 1.0 - 1e-9).mean()),
                    "avg_clip_t": float(np.maximum(0.0, g[:, 0] - a[:, 0]).mean()),
                    "avg_clip_o": float(np.maximum(0.0, g[:, 1] - a[:, 1]).mean()),
                    "avg_clip_r": float(np.maximum(0.0, g[:, 2] - a[:, 2]).mean()),
                    **turn,
                })
                for plab, ps, pe in periods:
                    mask = (d.date >= ps) & (d.date <= pe)
                    all_period.append({
                        "timing": timing, "cost": cname, "variant": nm, "period": plab,
                        **metrics(rr[mask.to_numpy()]),
                    })
                all_roll.append({"timing": timing, "cost": cname, "variant": nm, **rolling252(rr)})

                if timing == "SAME_DAY_GROSS" and cname in ("BASE", "ALL5", "ALL10") and (
                    nm in {"PRIORITY_RTO", "PRIORITY_TRO", "PROPORTIONAL"} or
                    nm in {f"RESET_TFLOOR_{k:03d}" for k in (60, 65, 70, 75, 80, 85, 90, 95, 100)}
                ):
                    daily_keep[key] = pd.DataFrame({
                        "date": d.date,
                        "return": rr,
                        "alloc_t": a[:, 0],
                        "alloc_o": a[:, 1],
                        "alloc_r": a[:, 2],
                        "total_gross": a.sum(axis=1),
                    })

        raw = g.sum(axis=1)
        all_alloc.append({
            "timing": timing,
            "days": int(n),
            "raw_avg_gross": float(raw.mean()),
            "raw_max_gross": float(raw.max()),
            "raw_over_100_days": int((raw > 1.0 + 1e-9).sum()),
            "raw_over_100_pct": float((raw > 1.0 + 1e-9).mean()),
            "desired_avg_t": float(g[:, 0].mean()),
            "desired_avg_o": float(g[:, 1].mean()),
            "desired_avg_r": float(g[:, 2].mean()),
        })

    perf_df = pd.DataFrame(all_perf)
    period_df = pd.DataFrame(all_period)
    roll_df = pd.DataFrame(all_roll)
    perf_df.to_csv(out / "gross100_variants.csv", index=False)
    period_df.to_csv(out / "gross100_subperiods.csv", index=False)
    roll_df.to_csv(out / "gross100_rolling252.csv", index=False)
    pd.DataFrame(all_alloc).to_csv(out / "gross100_raw_overlap.csv", index=False)

    if daily_keep:
        pd.concat([v.assign(series=k) for k, v in daily_keep.items()], ignore_index=True).to_csv(
            out / "gross100_selected_daily.csv.gz", index=False, compression="gzip"
        )

    pairs = [
        ("RESET_TFLOOR_070", "RESET_TFLOOR_075"),
        ("RESET_TFLOOR_070", "RESET_TFLOOR_080"),
        ("RESET_TFLOOR_075", "RESET_TFLOOR_080"),
        ("RESET_TFLOOR_075", "RESET_TFLOOR_090"),
        ("RESET_TFLOOR_075", "RESET_TFLOOR_100"),
        ("RESET_TFLOOR_075", "PROPORTIONAL"),
        ("RESET_TFLOOR_075", "PRIORITY_TRO"),
        ("RESET_TFLOOR_075", "PRIORITY_RTO"),
    ]
    boot = []
    for timing in timings:
        for cname in ("BASE", "ALL5", "ALL10"):
            for va, vb in pairs:
                ka = f"{timing}|{cname}|{va}"
                kb = f"{timing}|{cname}|{vb}"
                for block in (20, 60):
                    z = block_boot_pair(
                        variant_returns[ka], variant_returns[kb],
                        block=block, nsim=args.bootstrap_sims,
                        seed=831000 + block + sum(ord(c) for c in ka + kb),
                    )
                    boot.append({"timing": timing, "cost": cname, "a": va, "b": vb, **z})
    pd.DataFrame(boot).to_csv(out / "gross100_pairwise_bootstrap.csv", index=False)

    focus = perf_df[(perf_df.timing == "SAME_DAY_GROSS") & (perf_df.cost == "BASE")].copy()
    floors = focus[focus.variant.str.startswith("RESET_TFLOOR_")].copy()
    best_cagr = floors.sort_values(["cagr", "mdd"], ascending=[False, False]).iloc[0].to_dict()
    best_calmar = floors.sort_values(["calmar", "cagr"], ascending=[False, False]).iloc[0].to_dict()
    best_sharpe = floors.sort_values(["sharpe", "cagr"], ascending=[False, False]).iloc[0].to_dict()

    sensitivity_best = {}
    for timing in timings:
        for cname in ("BASE", "ALL5", "ALL10", "ALL20"):
            q = perf_df[
                (perf_df.timing == timing) &
                (perf_df.cost == cname) &
                perf_df.variant.str.startswith("RESET_TFLOOR_")
            ].copy()
            sensitivity_best[f"{timing}|{cname}|CALMAR"] = q.sort_values(
                ["calmar", "cagr"], ascending=[False, False]
            ).iloc[0].to_dict()

    summary = {
        "status": "GROSS100_ALLOCATION_AUDIT",
        "coverage": {
            "start": str(pd.Timestamp(d.date.min()).date()),
            "end": str(pd.Timestamp(d.date.max()).date()),
            "days": int(n),
        },
        "inputs": {
            "ordinary": "PEAK30_PART25_R3 component daily series",
            "rsi_reset": "RESET_RISE30_S029_P4_H20 component daily series",
            "tqqq_target": args.tqqq_target,
            "tqqq_return": "USD daily series from Stage56",
            "tqqq_effective_timing": "Stage56 from_target convention: target lag 2",
        },
        "raw_overlap": all_alloc,
        "primary_same_day_base": {
            "best_cagr_floor": best_cagr,
            "best_calmar_floor": best_calmar,
            "best_sharpe_floor": best_sharpe,
        },
        "sensitivity_best_calmar": sensitivity_best,
        "limitations": [
            "This is an allocation-overlay audit over already-selected component strategies; it is not a fresh untouched OOS test.",
            "Ordinary/Reset component returns are scaled approximately linearly by allocated gross. Exact intraday integrated-account reconstruction would require per-position overlay execution.",
            "SAME_DAY_GROSS can use end-of-day marked gross and is paired with LAG1_GROSS as a no-lookahead timing sensitivity; only conclusions stable across both should be promoted.",
            "Primary comparison is pre-tax USD for consistency because ordinary/Reset series do not contain a matched tax/FX account model.",
            "Conservative ALL5/10/20 bps sensitivities overcharge some stock turnover by design; they are stress tests, not base estimates.",
        ],
    }
    (out / "gross100_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str))

    show = focus.sort_values(["calmar", "cagr"], ascending=[False, False]).head(20)
    print("\n=== SAME_DAY / BASE TOP CALMAR ===")
    print(show[[
        "variant", "cagr", "mdd", "sharpe", "calmar",
        "avg_alloc_t", "avg_alloc_o", "avg_alloc_r",
        "avg_clip_t", "avg_clip_o", "avg_clip_r"
    ]].to_string(index=False))
    print("\n=== RAW OVERLAP ===")
    print(pd.DataFrame(all_alloc).to_string(index=False))
    print("\n=== SENSITIVITY BEST CALMAR ===")
    for k, v in sensitivity_best.items():
        print(k, v["variant"], v["cagr"], v["mdd"], v["sharpe"], v["calmar"])


if __name__ == "__main__":
    main()
