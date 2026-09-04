from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

import audit_gross100_component_series as comp
import audit_gross100_ddv_refill_mode as ddv
import audit_gross100_early_slot_overlay as early
import audit_gross100_final_reset_component_series as final_reset
import audit_ordinary_stock_exit_trail as ex
import audit_ordinary_stock_theme_leave_one_out as loo
import audit_staged_leader_liquidity_return as stage

FLOORS = (10_000_000.0, 20_000_000.0, 50_000_000.0, 100_000_000.0)
PRIMARY = ("SAME_DAY_GROSS", "BASE", "SELECTIVE_FILL_NO_ZERO_OVERRIDE")


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
    ap.add_argument("--bootstrap-sims", type=int, default=5000)
    args = ap.parse_args()

    out = Path(args.output); out.mkdir(parents=True, exist_ok=True)
    root = Path(args.root)
    meta, matrices = ex.build_inputs_ext(root, args.analysis_start, args.analysis_end, args.max_tickers, args.batch_size)
    peer_ctx = loo.build_leave_one_out_scores(root, matrices)
    ctx = stage.build_signal_context(root, matrices)
    core_attack, core_selective, early_by_score = stage.precompute_candidates(meta, matrices, peer_ctx, ctx)
    cal = pd.DatetimeIndex(meta["analysis_idx"])

    reset_trades = final_reset.prepare_final_reset_trades(Path(args.reset_trades), cal, matrices["close"].columns)
    reset, _ = comp.simulate_reset(cal, matrices["open"], matrices["close"], reset_trades)
    tq = pd.read_csv(args.tqqq_daily, compression="gzip"); tq["date"] = pd.to_datetime(tq["date"])

    old_floor = early.LIQUIDITY_FLOOR
    old_score, old_gate, old_days = early.EARLY_SCORE, early.EARLY_GATE, early.EARLY_MAX_DAYS
    early.EARLY_SCORE = "RS21_HIGH_ACCEL"; early.EARLY_GATE = "NOT_RED"; early.EARLY_MAX_DAYS = 10

    perf_rows: list[dict[str, Any]] = []
    sub_rows: list[dict[str, Any]] = []
    diag_rows: list[dict[str, Any]] = []
    primary_ret: dict[tuple[int, int], Any] = {}
    try:
        for floor in FLOORS:
            label = int(floor / 1_000_000)
            print(f"DDV{label} E0", flush=True)
            ord0, diag0 = ddv.simulate_ordinary_mode(meta, matrices, peer_ctx, floor, "VACANCY_TOP12")
            print(f"DDV{label} E1", flush=True)
            early.LIQUIDITY_FLOOR = floor
            ord1, diag1 = early.simulate_early_overlay(1, meta, matrices, core_attack, core_selective, early_by_score)
            for es, ordinary, diag in ((0, ord0, diag0), (1, ord1, diag1)):
                rets, perf, _ = ddv.combine_one(ordinary, reset, tq, args.tqqq_target)
                perf.insert(0, "early_slots", es); perf.insert(0, "ddv_m", label)
                perf_rows.extend(perf.to_dict(orient="records"))
                dates = ordinary[["date"]].merge(reset[["date"]], on="date").merge(tq[["date"]], on="date", how="inner")["date"]
                for key, rr in rets.items():
                    for p in ddv.subperiod_metrics(dates, rr):
                        sub_rows.append({"ddv_m": label, "early_slots": es, "timing": key[0], "cost": key[1], "policy": key[2], **p})
                primary_ret[(label, es)] = rets[PRIMARY]
                diag_rows.append({"ddv_m": label, "early_slots": es, **diag})
    finally:
        early.LIQUIDITY_FLOOR = old_floor
        early.EARLY_SCORE, early.EARLY_GATE, early.EARLY_MAX_DAYS = old_score, old_gate, old_days

    perf_df = pd.DataFrame(perf_rows)
    sub_df = pd.DataFrame(sub_rows)
    diag_df = pd.DataFrame(diag_rows)
    primary_df = perf_df[(perf_df.timing == PRIMARY[0]) & (perf_df.cost == PRIMARY[1]) & (perf_df.policy == PRIMARY[2])].copy()

    boot = []
    for label in (10, 20, 50, 100):
        for block in (20, 60):
            z = ddv.ga.block_boot_pair(primary_ret[(label, 1)], primary_ret[(label, 0)], block, args.bootstrap_sims, 12000 + label + block)
            boot.append({"comparison": f"DDV{label}_E1_vs_E0", **z})
    for block in (20, 60):
        z = ddv.ga.block_boot_pair(primary_ret[(20, 1)], primary_ret[(10, 0)], block, args.bootstrap_sims, 13000 + block)
        boot.append({"comparison": "DDV20_E1_vs_DDV10_E0", **z})
    boot_df = pd.DataFrame(boot)

    perf_df.to_csv(out / "ddv_early1_variants.csv", index=False)
    sub_df.to_csv(out / "ddv_early1_subperiods.csv", index=False)
    diag_df.to_csv(out / "ddv_early1_diagnostics.csv", index=False)
    boot_df.to_csv(out / "ddv_early1_bootstrap.csv", index=False)

    piv = primary_df[["ddv_m","early_slots","cagr","mdd","sharpe","calmar","avg_alloc_t","avg_alloc_o","avg_alloc_r","avg_total_gross"]].sort_values(["ddv_m","early_slots"])
    summary = {
        "status": "GROSS100_DDV_EARLY1_INTERACTION",
        "frozen_early": {"slots": 1, "score": "RS21_HIGH_ACCEL", "gate": "NOT_RED", "max_days": 10, "promotion": "DIRECT_TO_CORE"},
        "primary": piv.to_dict(orient="records"),
        "bootstrap": boot_df.to_dict(orient="records"),
        "guardrail": "Interaction audit only. DDV floor and Early presence are the only varied design dimensions; no new threshold is selected from this run alone."
    }
    (out / "ddv_early1_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
