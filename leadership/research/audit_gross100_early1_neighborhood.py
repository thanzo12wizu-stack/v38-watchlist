from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

import audit_gross100_ddv_refill_mode as ddv
import audit_gross100_component_series as comp
import audit_gross100_early_slot_overlay as early
import audit_gross100_final_reset_component_series as final_reset
import audit_ordinary_stock_exit_trail as ex
import audit_ordinary_stock_theme_leave_one_out as loo
import audit_staged_leader_liquidity_return as stage

SCORES = ("RS21", "RS21_HIGH63", "RS21_HIGH_ACCEL")
GATES = ("CURRENT", "BG", "NOT_RED")
MAX_DAYS = (5, 10, 15, 20)
PRIMARY_KEY = ("SAME_DAY_GROSS", "BASE", "SELECTIVE_FILL_NO_ZERO_OVERRIDE")
FROZEN = ("RS21_HIGH_ACCEL", "NOT_RED", 10)


def make_gate(name: str):
    def gate_allowed(meta: dict[str, Any], d: pd.Timestamp) -> bool:
        color, bucket, _ = stage.delay.market_state(meta, d)
        if name == "CURRENT":
            return bool(color in ("Blue", "Green") and bucket >= 1)
        if name == "BG":
            return bool(color in ("Blue", "Green"))
        if name == "NOT_RED":
            return bool(color != "Red")
        raise ValueError(name)
    return gate_allowed


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
    ap.add_argument("--tqqq-target", default="target_M30_TOUCH30_F80_D10")
    args = ap.parse_args()

    root = Path(args.root)
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    meta, matrices = ex.build_inputs_ext(root, args.analysis_start, args.analysis_end, args.max_tickers, args.batch_size)
    peer_ctx = loo.build_leave_one_out_scores(root, matrices)
    ctx = stage.build_signal_context(root, matrices)
    core_attack, core_selective, early_by_score = stage.precompute_candidates(meta, matrices, peer_ctx, ctx)
    cal = pd.DatetimeIndex(meta["analysis_idx"])

    reset_trades = final_reset.prepare_final_reset_trades(Path(args.reset_trades), cal, matrices["close"].columns)
    reset, _ = comp.simulate_reset(cal, matrices["open"], matrices["close"], reset_trades)
    tq = pd.read_csv(args.tqqq_daily, compression="gzip")
    tq["date"] = pd.to_datetime(tq["date"])

    baseline_ord, _ = ddv.simulate_ordinary_mode(meta, matrices, peer_ctx, 20_000_000.0, "VACANCY_TOP12")
    baseline_rets, _, _ = ddv.combine_one(baseline_ord, reset, tq, args.tqqq_target)
    baseline = baseline_rets[PRIMARY_KEY]

    rows: list[dict[str, Any]] = []
    period_rows: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []

    old_score, old_gate, old_days, old_gate_fn = early.EARLY_SCORE, early.EARLY_GATE, early.EARLY_MAX_DAYS, early._gate_allowed
    try:
        for score in SCORES:
            for gate in GATES:
                for days in MAX_DAYS:
                    early.EARLY_SCORE = score
                    early.EARLY_GATE = gate
                    early.EARLY_MAX_DAYS = days
                    early._gate_allowed = make_gate(gate)
                    print(f"RUN score={score} gate={gate} days={days}", flush=True)
                    ordinary, diag = early.simulate_early_overlay(
                        1, meta, matrices, core_attack, core_selective, early_by_score
                    )
                    rets, perf, _ = ddv.combine_one(ordinary, reset, tq, args.tqqq_target)
                    rr = rets[PRIMARY_KEY]
                    m = ddv.ga.metrics(rr)
                    rows.append({
                        "score": score, "gate": gate, "days": days,
                        **m,
                        "delta_cagr_vs_early0": m["cagr"] - ddv.ga.metrics(baseline)["cagr"],
                        "delta_mdd_vs_early0": m["mdd"] - ddv.ga.metrics(baseline)["mdd"],
                        "is_frozen": bool((score, gate, days) == FROZEN),
                    })
                    diagnostics.append({"score": score, "gate": gate, "days": days, **diag})
                    dates = ordinary[["date"]].merge(reset[["date"]], on="date").merge(tq[["date"]], on="date", how="inner")["date"]
                    for p in ddv.subperiod_metrics(dates, rr):
                        period_rows.append({"score": score, "gate": gate, "days": days, **p})
    finally:
        early.EARLY_SCORE, early.EARLY_GATE, early.EARLY_MAX_DAYS, early._gate_allowed = old_score, old_gate, old_days, old_gate_fn

    grid = pd.DataFrame(rows).sort_values(["calmar", "cagr"], ascending=[False, False])
    periods = pd.DataFrame(period_rows)
    diags = pd.DataFrame(diagnostics)
    grid.to_csv(out / "early1_neighborhood_grid.csv", index=False)
    periods.to_csv(out / "early1_neighborhood_subperiods.csv", index=False)
    diags.to_csv(out / "early1_neighborhood_diagnostics.csv", index=False)

    b = ddv.ga.metrics(baseline)
    summary = {
        "status": "GROSS100_EARLY1_NEIGHBORHOOD",
        "base": "DDV20_VACANCY_EARLY0",
        "baseline": b,
        "grid_n": int(len(grid)),
        "positive_delta_cagr_share": float((grid["delta_cagr_vs_early0"] > 0).mean()),
        "nonworse_mdd_share": float((grid["delta_mdd_vs_early0"] >= 0).mean()),
        "positive_cagr_and_nonworse_mdd_share": float(((grid["delta_cagr_vs_early0"] > 0) & (grid["delta_mdd_vs_early0"] >= 0)).mean()),
        "median_delta_cagr": float(grid["delta_cagr_vs_early0"].median()),
        "frozen": grid[grid["is_frozen"]].to_dict(orient="records")[0],
        "top_by_calmar": grid.head(10).to_dict(orient="records"),
        "guardrail": "Robustness grid only; no winner is selected from this grid. Frozen prior winner is evaluated in neighborhood context.",
    }
    (out / "early1_neighborhood_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
