from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

TRADING_DAYS = 252
TQQQ_COST = 5.0 / 10000.0
NORMAL_CAP = 0.70
TQQQ_PROTECT_CAP = 0.80
LIQUIDITY_LABELS = (10, 20, 50, 100)
EXPECTED_LEGACY_CAGR = 0.4637
EXPECTED_LEGACY_MDD = -0.2571


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


def rolling252(ret: np.ndarray) -> dict:
    z = (1.0 + pd.Series(np.asarray(ret, float))).rolling(252).apply(np.prod, raw=True) - 1.0
    z = z.dropna()
    return {
        "rolling252_positive": float((z > 0).mean()) if len(z) else np.nan,
        "rolling252_worst": float(z.min()) if len(z) else np.nan,
        "rolling252_median": float(z.median()) if len(z) else np.nan,
        "rolling252_p10": float(z.quantile(0.10)) if len(z) else np.nan,
        "rolling252_p90": float(z.quantile(0.90)) if len(z) else np.nan,
    }


def native_gross100(g: np.ndarray) -> np.ndarray:
    """Final pre-fill priority: Reset -> protected/native TQQQ -> Normal -> native TQQQ extra.

    g columns are [native TQQQ desired, Normal desired already capped at 70%, Reset desired].
    Gross is always <=100%.
    """
    out = np.zeros_like(g, dtype=float)
    for i, row in enumerate(g):
        t, o, r = [max(float(x), 0.0) for x in row]
        rem = 1.0
        ar = min(r, rem)
        out[i, 2] = ar
        rem -= ar

        protect = min(t, TQQQ_PROTECT_CAP, rem)
        out[i, 0] = protect
        rem -= protect

        ao = min(o, rem)
        out[i, 1] = ao
        rem -= ao

        out[i, 0] += min(max(t - out[i, 0], 0.0), rem)
    return out


def selective_fill_no_zero_override(g: np.ndarray, fill_allowed: np.ndarray) -> np.ndarray:
    """Adopted research overlay.

    Start from native Gross100 allocation. On prior-day Blue/Green + Breadth>=50 days,
    if the native TQQQ target is >0, fill only otherwise-unused Gross100 capacity with TQQQ.
    Reset and Normal allocations are never reduced. A native TQQQ target of 0 is never overridden.
    """
    out = native_gross100(g)
    allowed = np.asarray(fill_allowed, bool)
    for i in range(len(out)):
        if allowed[i] and float(g[i, 0]) > 1e-12:
            rem = max(0.0, 1.0 - float(out[i].sum()))
            out[i, 0] += rem
    return out


def scaled_returns(
    alloc: np.ndarray,
    component_o_gross: np.ndarray,
    component_r_gross: np.ndarray,
    ret_t: np.ndarray,
    ret_o: np.ndarray,
    ret_r: np.ndarray,
    all_turnover_cost_bps: float | None = None,
) -> tuple[np.ndarray, dict]:
    a_t, a_o, a_r = alloc.T
    s_o = np.divide(a_o, component_o_gross, out=np.zeros_like(a_o), where=component_o_gross > 1e-12)
    s_r = np.divide(a_r, component_r_gross, out=np.zeros_like(a_r), where=component_r_gross > 1e-12)
    ret = a_t * ret_t + s_o * ret_o + s_r * ret_r

    turn_t = np.zeros(len(ret), float)
    turn_t[1:] = np.abs(np.diff(a_t))
    if all_turnover_cost_bps is None:
        ret -= turn_t * TQQQ_COST
        return ret, {
            "turn_t": float(turn_t.sum()),
            "turn_o": np.nan,
            "turn_r": np.nan,
            "cost_mode": "TQQQ_5BP_ONLY_COMPONENT_RETURNS_AS_GENERATED",
        }

    c = float(all_turnover_cost_bps) / 10000.0
    turn_o = np.zeros(len(ret), float)
    turn_r = np.zeros(len(ret), float)
    turn_o[1:] = np.abs(np.diff(a_o))
    turn_r[1:] = np.abs(np.diff(a_r))
    ret -= (turn_t + turn_o + turn_r) * c
    return ret, {
        "turn_t": float(turn_t.sum()),
        "turn_o": float(turn_o.sum()),
        "turn_r": float(turn_r.sum()),
        "cost_mode": f"CONSERVATIVE_ALL_ALLOCATED_GROSS_{all_turnover_cost_bps:g}BP",
    }


def block_boot_pair(a: np.ndarray, b: np.ndarray, block: int, nsim: int, seed: int) -> dict:
    a = np.asarray(a, float)
    b = np.asarray(b, float)
    n = len(a)
    if n < block:
        return {"block": block, "nsim": 0}
    rng = np.random.default_rng(seed)
    nb = int(np.ceil(n / block))
    years = n / TRADING_DAYS
    wins_ret, wins_mdd, wins_calmar, cagr_diff = [], [], [], []
    offs = np.arange(block)
    for s0 in range(0, nsim, 250):
        m = min(250, nsim - s0)
        starts = rng.integers(0, n - block + 1, size=(m, nb))
        ix = (starts[:, :, None] + offs).reshape(m, -1)[:, :n]
        aa, bb = a[ix], b[ix]
        la, lb = np.log1p(aa).sum(axis=1), np.log1p(bb).sum(axis=1)
        ca, cb = np.exp(la / years) - 1.0, np.exp(lb / years) - 1.0
        eqa, eqb = np.cumprod(1.0 + aa, axis=1), np.cumprod(1.0 + bb, axis=1)
        mdda = (eqa / np.maximum.accumulate(eqa, axis=1) - 1.0).min(axis=1)
        mddb = (eqb / np.maximum.accumulate(eqb, axis=1) - 1.0).min(axis=1)
        cala = ca / np.maximum(np.abs(mdda), 1e-12)
        calb = cb / np.maximum(np.abs(mddb), 1e-12)
        wins_ret.append(la > lb)
        wins_mdd.append(mdda >= mddb)
        wins_calmar.append(cala > calb)
        cagr_diff.append(ca - cb)
    wr = np.concatenate(wins_ret)
    wm = np.concatenate(wins_mdd)
    wc = np.concatenate(wins_calmar)
    cd = np.concatenate(cagr_diff)
    return {
        "block": int(block),
        "nsim": int(nsim),
        "p_return_a_gt_b": float(wr.mean()),
        "p_mdd_a_no_worse": float(wm.mean()),
        "p_calmar_a_gt_b": float(wc.mean()),
        "cagr_diff_median": float(np.median(cd)),
        "cagr_diff_p05": float(np.quantile(cd, 0.05)),
        "cagr_diff_p95": float(np.quantile(cd, 0.95)),
    }


def load_ordinary(comp: Path, label: int) -> pd.DataFrame:
    p = comp / f"ordinary_PEAK30_PART25_R3_DDV{label}M_daily.csv.gz"
    if not p.exists() and label == 10:
        p = comp / "ordinary_PEAK30_PART25_R3_daily.csv.gz"
    x = pd.read_csv(p, compression="gzip")
    x["date"] = pd.to_datetime(x["date"])
    if "selective_fill_allowed" not in x.columns:
        raise RuntimeError(f"{p.name} missing selective_fill_allowed; component rebuild is required")
    return x


def main() -> None:
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

    reset = pd.read_csv(comp / "rsi_RESET_RISE30_S029_P4_H20_daily.csv.gz", compression="gzip")
    tq = pd.read_csv(args.tqqq_daily, compression="gzip")
    reset["date"] = pd.to_datetime(reset["date"])
    tq["date"] = pd.to_datetime(tq["date"])

    periods = [
        ("FULL", pd.Timestamp("2016-01-04"), pd.Timestamp("2026-03-20")),
        ("DEV_2016_2020", pd.Timestamp("2016-01-04"), pd.Timestamp("2020-12-31")),
        ("CONFIRM_2021_2023", pd.Timestamp("2021-01-01"), pd.Timestamp("2023-12-31")),
        ("HOLDOUT_2024_2026M3", pd.Timestamp("2024-01-01"), pd.Timestamp("2026-03-20")),
        ("SINCE_2021", pd.Timestamp("2021-01-01"), pd.Timestamp("2026-03-20")),
    ]
    cost_specs = [("BASE", None), ("ALL5", 5.0), ("ALL10", 10.0), ("ALL20", 20.0)]

    perf_rows: list[dict] = []
    period_rows: list[dict] = []
    roll_rows: list[dict] = []
    boot_returns: dict[tuple[int, str, str, str], np.ndarray] = {}
    daily_frames = []
    diagnostics = {}

    for label in LIQUIDITY_LABELS:
        ordinary = load_ordinary(comp, label)
        d = ordinary.merge(reset, on="date", suffixes=("_ord", "_rsi")).merge(tq, on="date", how="inner")
        if args.tqqq_target not in d.columns:
            raise KeyError(args.tqqq_target)
        n = len(d)
        native_target = pd.to_numeric(d[args.tqqq_target], errors="coerce").fillna(0.0).to_numpy(float)
        eff_t = np.zeros(n, float)
        # Preserve Stage56 from_target convention used by the frozen audited Gross100 series.
        if n > 2:
            eff_t[2:] = native_target[:-2]
        ret_t = pd.to_numeric(d["tqqq_ret_usd"], errors="coerce").fillna(0.0).to_numpy(float)
        ret_o = pd.to_numeric(d["return_ord"], errors="coerce").fillna(0.0).to_numpy(float)
        ret_r = pd.to_numeric(d["return_rsi"], errors="coerce").fillna(0.0).to_numpy(float)
        raw_o = pd.to_numeric(d["gross_exposure_ord"], errors="coerce").fillna(0.0).to_numpy(float)
        raw_r = pd.to_numeric(d["gross_exposure_rsi"], errors="coerce").fillna(0.0).to_numpy(float)
        gate0 = d["selective_fill_allowed"].astype(bool).to_numpy()

        timings = {
            "SAME_DAY_GROSS": (raw_o.copy(), raw_r.copy(), gate0.copy()),
            "LAG1_GROSS": (
                np.r_[0.0, raw_o[:-1]],
                np.r_[0.0, raw_r[:-1]],
                np.r_[False, gate0[:-1]],
            ),
        }

        diagnostics[str(label)] = {
            "days": int(n),
            "start": str(pd.Timestamp(d.date.min()).date()),
            "end": str(pd.Timestamp(d.date.max()).date()),
            "raw_o_avg": float(raw_o.mean()),
            "raw_o_max": float(raw_o.max()),
            "fill_gate_days": int(gate0.sum()),
            "native_t_positive_days": int((eff_t > 1e-12).sum()),
            "fill_eligible_days": int((gate0 & (eff_t > 1e-12)).sum()),
        }

        for timing, (comp_o, comp_r, gate) in timings.items():
            desired_o = np.minimum(np.maximum(comp_o, 0.0), NORMAL_CAP)
            desired_r = np.maximum(comp_r, 0.0)
            g = np.column_stack([np.maximum(eff_t, 0.0), desired_o, desired_r])
            policies = {
                "NATIVE_NO_FILL": native_gross100(g),
                "SELECTIVE_FILL_NO_ZERO_OVERRIDE": selective_fill_no_zero_override(g, gate),
            }
            for policy, alloc in policies.items():
                if float(alloc.sum(axis=1).max()) > 1.0 + 1e-9:
                    raise RuntimeError(f"Gross100 violation {label} {timing} {policy}")
                for cost_name, cbps in cost_specs:
                    rr, turn = scaled_returns(alloc, comp_o, comp_r, ret_t, ret_o, ret_r, cbps)
                    key = (label, timing, cost_name, policy)
                    boot_returns[key] = rr
                    met = metrics(rr)
                    perf_rows.append({
                        "ddv_m": label,
                        "timing": timing,
                        "cost": cost_name,
                        "policy": policy,
                        **met,
                        "avg_alloc_t": float(alloc[:, 0].mean()),
                        "avg_alloc_o": float(alloc[:, 1].mean()),
                        "avg_alloc_r": float(alloc[:, 2].mean()),
                        "avg_total_gross": float(alloc.sum(axis=1).mean()),
                        "max_total_gross": float(alloc.sum(axis=1).max()),
                        "pct_at_100": float((alloc.sum(axis=1) >= 1.0 - 1e-9).mean()),
                        "selective_fill_days": int((gate & (eff_t > 1e-12) & (alloc[:, 0] > native_gross100(g)[:, 0] + 1e-12)).sum()) if policy == "SELECTIVE_FILL_NO_ZERO_OVERRIDE" else 0,
                        **turn,
                    })
                    for plab, ps, pe in periods:
                        mask = ((d.date >= ps) & (d.date <= pe)).to_numpy()
                        period_rows.append({
                            "ddv_m": label,
                            "timing": timing,
                            "cost": cost_name,
                            "policy": policy,
                            "period": plab,
                            **metrics(rr[mask]),
                        })
                    roll_rows.append({
                        "ddv_m": label,
                        "timing": timing,
                        "cost": cost_name,
                        "policy": policy,
                        **rolling252(rr),
                    })
                    if timing == "SAME_DAY_GROSS" and cost_name == "BASE":
                        daily_frames.append(pd.DataFrame({
                            "date": d.date,
                            "ddv_m": label,
                            "policy": policy,
                            "return": rr,
                            "alloc_t": alloc[:, 0],
                            "alloc_o": alloc[:, 1],
                            "alloc_r": alloc[:, 2],
                            "total_gross": alloc.sum(axis=1),
                            "fill_allowed": gate,
                            "native_t_target_effective": eff_t,
                        }))

    perf = pd.DataFrame(perf_rows)
    sub = pd.DataFrame(period_rows)
    rolls = pd.DataFrame(roll_rows)
    perf.to_csv(out / "gross100_liquidity_variants.csv", index=False)
    sub.to_csv(out / "gross100_liquidity_subperiods.csv", index=False)
    rolls.to_csv(out / "gross100_liquidity_rolling252.csv", index=False)
    pd.concat(daily_frames, ignore_index=True).to_csv(
        out / "gross100_liquidity_primary_daily.csv.gz", index=False, compression="gzip"
    )

    primary_filter = (
        (perf.timing == "SAME_DAY_GROSS")
        & (perf.cost == "BASE")
        & (perf.policy == "SELECTIVE_FILL_NO_ZERO_OVERRIDE")
    )
    primary = perf[primary_filter].sort_values("ddv_m")
    p10 = primary[primary.ddv_m == 10].iloc[0]
    reproduction = {
        "observed_cagr": float(p10.cagr),
        "observed_mdd": float(p10.mdd),
        "expected_legacy_cagr": EXPECTED_LEGACY_CAGR,
        "expected_legacy_mdd": EXPECTED_LEGACY_MDD,
        "cagr_abs_diff": float(abs(p10.cagr - EXPECTED_LEGACY_CAGR)),
        "mdd_abs_diff": float(abs(p10.mdd - EXPECTED_LEGACY_MDD)),
        "pass_1ppt_tolerance": bool(
            abs(p10.cagr - EXPECTED_LEGACY_CAGR) <= 0.01
            and abs(p10.mdd - EXPECTED_LEGACY_MDD) <= 0.01
        ),
        "interpretation_guardrail": "Do not promote a DDV threshold if this reproduction check fails; first reconcile frozen-input or allocation differences.",
    }

    boot = []
    base_key = (10, "SAME_DAY_GROSS", "BASE", "SELECTIVE_FILL_NO_ZERO_OVERRIDE")
    for label in (20, 50, 100):
        akey = (label, "SAME_DAY_GROSS", "BASE", "SELECTIVE_FILL_NO_ZERO_OVERRIDE")
        for block in (20, 60):
            z = block_boot_pair(
                boot_returns[akey], boot_returns[base_key], block, args.bootstrap_sims,
                seed=904000 + label * 10 + block,
            )
            boot.append({"a_ddv_m": label, "b_ddv_m": 10, **z})
    pd.DataFrame(boot).to_csv(out / "gross100_liquidity_bootstrap.csv", index=False)

    dev = sub[
        (sub.timing == "SAME_DAY_GROSS")
        & (sub.cost == "BASE")
        & (sub.policy == "SELECTIVE_FILL_NO_ZERO_OVERRIDE")
        & (sub.period == "DEV_2016_2020")
    ].copy()
    dev10_mdd = float(dev.loc[dev.ddv_m == 10, "mdd"].iloc[0])
    guarded = dev[dev.mdd >= dev10_mdd - 0.03].sort_values(["cagr", "calmar"], ascending=False)
    dev_choice = int(guarded.iloc[0].ddv_m) if len(guarded) else 10

    result = {
        "status": "GROSS100_LIQUIDITY_INTEGRATION_AUDIT",
        "scope": "research only; no main/UI/live change",
        "frozen_inputs": {
            "normal": "PEAK30_PART25_R3; Attack 12 / Selective 4; Normal allocated max70%",
            "reset": "RS63_TOP3_RISE30_SIGTOP3; 2.9% x max4",
            "tqqq": args.tqqq_target,
            "gross100_priority": "Reset -> protected/native TQQQ up to 80% -> Normal -> native TQQQ extra",
            "selective_fill": "prior-day NQSAR Blue/Green + Breadth>=50; native TQQQ target must be >0; fill surplus only; never reduce Reset/Normal; never override native TQQQ=0",
        },
        "liquidity_definition": "Adopted DDV>=10M ranking universe remains unchanged. 20/50/100M are entry-only filters after ranking; next-ranked liquid candidates may fill; no forced liquidity exit.",
        "coverage": diagnostics,
        "baseline_reproduction": reproduction,
        "primary_same_day_base": primary.to_dict(orient="records"),
        "development_selection_protocol": {
            "period": "2016-2020",
            "rule": "highest CAGR among DDV10/20/50/100 with MDD no more than 3ppt worse than DDV10 development MDD",
            "development_choice_ddv_m": dev_choice,
            "warning": "DDV50 was already observed in earlier full-period liquidity sensitivity; this is robustness/confirmation discipline, not a pristine untouched OOS discovery.",
        },
        "bootstrap_vs_ddv10": boot,
        "acceptance": {
            "must_reproduce_baseline": True,
            "must_not_depend_on_same_day_only": True,
            "must_survive_cost_stress": True,
            "must_be_directionally_supported_in_2021_2023_and_2024_2026M3": True,
            "must_keep_gross_le_100": True,
        },
        "latest_external_reference": {
            "reported_2026_09_02_reproduction": {"cagr": 0.4700, "mdd": -0.2323},
            "use": "reference only; not used as apples-to-apples acceptance benchmark because the frozen artifact period/input identity has not been verified here",
        },
    }
    (out / "gross100_liquidity_summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )

    print("=== GROSS100 LIQUIDITY PRIMARY ===")
    print(primary[["ddv_m", "cagr", "mdd", "sharpe", "calmar", "avg_alloc_t", "avg_alloc_o", "avg_alloc_r", "avg_total_gross", "selective_fill_days"]].to_string(index=False))
    print("=== BASELINE REPRODUCTION ===")
    print(json.dumps(reproduction, indent=2))
    print("=== DEVELOPMENT CHOICE ===")
    print(dev_choice)
    print("=== BOOTSTRAP ===")
    print(pd.DataFrame(boot).to_string(index=False))


if __name__ == "__main__":
    main()
