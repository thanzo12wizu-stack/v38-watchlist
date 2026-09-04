from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

import audit_gross100_allocation as alloc
import audit_gross100_component_series as comp
import audit_gross100_final_reset_component_series as final_reset
import audit_ordinary_stock_exit_trail as ex
import audit_ordinary_stock_theme_leave_one_out as loo


FLOORS_M = (10, 15, 20, 25, 30, 40, 50, 75, 100)
COSTS = (("BASE", None), ("ALL10", 10.0), ("ALL20", 20.0))
PERIODS = (
    ("DEV_2016_2020", "2016-01-04", "2020-12-31"),
    ("CONFIRM_2021_2023", "2021-01-01", "2023-12-31"),
    ("HOLDOUT_2024_2026M3", "2024-01-01", "2026-03-20"),
    ("SINCE_2021", "2021-01-01", "2026-03-20"),
)
HISTORICAL_FINAL_RESET_F80 = {
    "run_id": 33405477190,
    "cagr": 0.4758859572547668,
    "mdd": -0.249048,
    "note": "Gross100 final Reset recheck SAME_DAY_GROSS BASE RESET_TFLOOR_080; comparison reference only.",
}


def metric_row(floor_m: int, timing: str, cost: str, ret: np.ndarray) -> dict:
    return {"ddv_m": floor_m, "timing": timing, "cost": cost, **alloc.metrics(ret)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--reset-trades", required=True)
    ap.add_argument("--tqqq-daily", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--analysis-start", default="2016-01-04")
    ap.add_argument("--analysis-end", default="2026-03-20")
    ap.add_argument("--max-tickers", type=int, default=6000)
    ap.add_argument("--batch-size", type=int, default=75)
    ap.add_argument("--bootstrap-sims", type=int, default=5000)
    args = ap.parse_args()

    root = Path(args.root)
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    print("BUILD MARKET INPUTS ONCE", flush=True)
    meta, matrices = ex.build_inputs_ext(
        root, args.analysis_start, args.analysis_end, args.max_tickers, args.batch_size
    )
    print("BUILD LOO THEME ONCE", flush=True)
    peer_ctx = loo.build_leave_one_out_scores(root, matrices)

    cal = pd.DatetimeIndex(meta["analysis_idx"])
    reset_trades = final_reset.prepare_final_reset_trades(
        Path(args.reset_trades), cal, matrices["close"].columns
    )
    reset, _ = comp.simulate_reset(cal, matrices["open"], matrices["close"], reset_trades)
    reset["date"] = pd.to_datetime(reset["date"])

    tq = pd.read_csv(args.tqqq_daily, compression="gzip")
    tq["date"] = pd.to_datetime(tq["date"])
    target_name = "target_M30_TOUCH30_F80_D10"
    if target_name not in tq.columns:
        raise RuntimeError(f"missing frozen TQQQ target {target_name}")

    perf_rows: list[dict] = []
    period_rows: list[dict] = []
    returns: dict[tuple[int, str, str], np.ndarray] = {}
    component_stats: dict[str, dict] = {}
    native10_ref: dict | None = None

    for floor_m in FLOORS_M:
        print(f"SIM DDV {floor_m}M", flush=True)
        ordinary = comp.simulate_ordinary(
            meta, matrices, peer_ctx, liquidity_floor=float(floor_m) * 1_000_000.0
        )
        ordinary["date"] = pd.to_datetime(ordinary["date"])
        component_stats[str(floor_m)] = {
            "avg_gross": float(ordinary["gross_exposure"].mean()),
            "avg_positions": float(ordinary["positions"].mean()),
            "max_positions": int(ordinary["positions"].max()),
        }

        d = ordinary.merge(reset, on="date", suffixes=("_ord", "_rsi")).merge(tq, on="date", how="inner")
        n = len(d)
        native_target = pd.to_numeric(d[target_name], errors="coerce").fillna(0.0).to_numpy(float)
        eff_t = np.zeros(n, float)
        if n > 2:
            eff_t[2:] = native_target[:-2]
        ret_t = pd.to_numeric(d["tqqq_ret_usd"], errors="coerce").fillna(0.0).to_numpy(float)
        ret_o = pd.to_numeric(d["return_ord"], errors="coerce").fillna(0.0).to_numpy(float)
        ret_r = pd.to_numeric(d["return_rsi"], errors="coerce").fillna(0.0).to_numpy(float)
        raw_o = pd.to_numeric(d["gross_exposure_ord"], errors="coerce").fillna(0.0).to_numpy(float)
        raw_r = pd.to_numeric(d["gross_exposure_rsi"], errors="coerce").fillna(0.0).to_numpy(float)
        gate0 = d["selective_fill_allowed"].astype(bool).to_numpy()

        timings = {
            "SAME_DAY_GROSS": (raw_o, raw_r, gate0),
            "LAG1_GROSS": (
                np.r_[0.0, raw_o[:-1]],
                np.r_[0.0, raw_r[:-1]],
                np.r_[False, gate0[:-1]],
            ),
        }

        for timing, (comp_o, comp_r, gate) in timings.items():
            desired_o = np.minimum(np.maximum(comp_o, 0.0), alloc.NORMAL_CAP)
            desired_r = np.maximum(comp_r, 0.0)
            g = np.column_stack([np.maximum(eff_t, 0.0), desired_o, desired_r])
            native = alloc.native_gross100(g)
            selected = alloc.selective_fill_no_zero_override(g, gate)

            if floor_m == 10 and timing == "SAME_DAY_GROSS":
                native_ret, _ = alloc.scaled_returns(native, comp_o, comp_r, ret_t, ret_o, ret_r, None)
                native10_ref = alloc.metrics(native_ret)

            for cost_name, cost_bps in COSTS:
                rr, _ = alloc.scaled_returns(selected, comp_o, comp_r, ret_t, ret_o, ret_r, cost_bps)
                returns[(floor_m, timing, cost_name)] = rr
                perf_rows.append(metric_row(floor_m, timing, cost_name, rr))
                for plab, ps, pe in PERIODS:
                    mask = ((d["date"] >= pd.Timestamp(ps)) & (d["date"] <= pd.Timestamp(pe))).to_numpy()
                    period_rows.append({
                        "ddv_m": floor_m,
                        "timing": timing,
                        "cost": cost_name,
                        "period": plab,
                        **alloc.metrics(rr[mask]),
                    })

    perf = pd.DataFrame(perf_rows)
    periods = pd.DataFrame(period_rows)
    perf.to_csv(out / "neighborhood_variants.csv", index=False)
    periods.to_csv(out / "neighborhood_subperiods.csv", index=False)

    boot_rows = []
    for floor_m in FLOORS_M:
        if floor_m == 10:
            continue
        for timing in ("SAME_DAY_GROSS", "LAG1_GROSS"):
            a = returns[(floor_m, timing, "BASE")]
            b = returns[(10, timing, "BASE")]
            for block in (20, 60):
                z = alloc.block_boot_pair(
                    a, b, block, args.bootstrap_sims,
                    seed=20260904 + floor_m * 100 + block + (1 if timing == "LAG1_GROSS" else 0),
                )
                boot_rows.append({"a_ddv_m": floor_m, "b_ddv_m": 10, "timing": timing, **z})
    boot = pd.DataFrame(boot_rows)
    boot.to_csv(out / "neighborhood_bootstrap.csv", index=False)

    primary = perf[(perf["timing"] == "SAME_DAY_GROSS") & (perf["cost"] == "BASE")].copy()
    dev = periods[(periods["timing"] == "SAME_DAY_GROSS") & (periods["cost"] == "BASE") & (periods["period"] == "DEV_2016_2020")]
    confirm = periods[(periods["timing"] == "SAME_DAY_GROSS") & (periods["cost"] == "BASE") & (periods["period"] == "CONFIRM_2021_2023")]
    holdout = periods[(periods["timing"] == "SAME_DAY_GROSS") & (periods["cost"] == "BASE") & (periods["period"] == "HOLDOUT_2024_2026M3")]

    # Robustness score is diagnostic only: +1 for beating DDV10 CAGR in each untouched-forward segment,
    # +1 for no worse MDD by >2ppt in each segment, and +1 for full-period Calmar >= DDV10.
    base10 = primary[primary["ddv_m"] == 10].iloc[0]
    scores = []
    for f in FLOORS_M:
        pr = primary[primary["ddv_m"] == f].iloc[0]
        cf = confirm[confirm["ddv_m"] == f].iloc[0]
        hf = holdout[holdout["ddv_m"] == f].iloc[0]
        c10 = confirm[confirm["ddv_m"] == 10].iloc[0]
        h10 = holdout[holdout["ddv_m"] == 10].iloc[0]
        score = int(cf.cagr >= c10.cagr) + int(hf.cagr >= h10.cagr)
        score += int(cf.mdd >= c10.mdd - 0.02) + int(hf.mdd >= h10.mdd - 0.02)
        score += int(pr.calmar >= base10.calmar)
        scores.append({"ddv_m": f, "robustness_score_0_5": score})

    historical_reconciliation = {
        "historical_reference": HISTORICAL_FINAL_RESET_F80,
        "current_ddv10_native": native10_ref,
        "cagr_diff_ppt": None if native10_ref is None else (native10_ref["cagr"] - HISTORICAL_FINAL_RESET_F80["cagr"]) * 100.0,
        "mdd_diff_ppt": None if native10_ref is None else (native10_ref["mdd"] - HISTORICAL_FINAL_RESET_F80["mdd"]) * 100.0,
        "interpretation": "The correct legacy identity reference for current NATIVE allocation is historical final-Reset F80, not the older 46.37% constant used by the coarse-grid diagnostic gate.",
    }

    summary = {
        "status": "GROSS100_DDV_NEIGHBORHOOD_AUDIT",
        "scope": "research only; no main/UI/live changes",
        "floors_m": list(FLOORS_M),
        "rule": "ranking universe remains adopted >=10M; floor is entry-only among adopted Top12 candidates; no rank13+ backfill; no forced liquidity exit",
        "primary_policy": "SELECTIVE_FILL_NO_ZERO_OVERRIDE",
        "primary": primary.to_dict(orient="records"),
        "development": dev.to_dict(orient="records"),
        "confirmation": confirm.to_dict(orient="records"),
        "holdout": holdout.to_dict(orient="records"),
        "robustness_scores": scores,
        "component_stats": component_stats,
        "historical_reconciliation": historical_reconciliation,
        "guardrails": [
            "Threshold selection must not use full-period CAGR alone.",
            "Prefer a neighborhood plateau that survives 2021-2023, 2024-2026M3, LAG1 timing, costs, and bootstrap.",
            "DDV100 development winner is not automatically adoptable if forward segments degrade.",
        ],
    }
    (out / "summary_neighborhood.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
