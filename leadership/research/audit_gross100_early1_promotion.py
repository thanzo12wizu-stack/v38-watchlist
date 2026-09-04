from __future__ import annotations

import argparse
import inspect
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import audit_gross100_ddv_refill_mode as ddv
import audit_gross100_component_series as comp
import audit_gross100_early_slot_overlay as early
import audit_gross100_final_reset_component_series as final_reset
import audit_ordinary_stock_exit_trail as ex
import audit_ordinary_stock_theme_leave_one_out as loo
import audit_staged_leader_liquidity_return as stage

PRIMARY_KEY = ("SAME_DAY_GROSS", "BASE", "SELECTIVE_FILL_NO_ZERO_OVERRIDE")


def no_promotion_simulator():
    src = inspect.getsource(early.simulate_early_overlay)
    needle = 'if pos[sym]["sleeve"] == "EARLY" and sym in core_symbols:'
    if src.count(needle) != 1:
        raise RuntimeError(f"promotion guard occurrence changed: {src.count(needle)}")
    src = src.replace(needle, 'if False and pos[sym]["sleeve"] == "EARLY" and sym in core_symbols:')
    ns = dict(early.__dict__)
    exec(src, ns)
    return ns["simulate_early_overlay"]


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

    early.EARLY_SCORE = "RS21_HIGH_ACCEL"
    early.EARLY_GATE = "NOT_RED"
    early.EARLY_MAX_DAYS = 10

    base_ord, base_diag = ddv.simulate_ordinary_mode(meta, matrices, peer_ctx, 20_000_000.0, "VACANCY_TOP12")
    promote_ord, promote_diag = early.simulate_early_overlay(1, meta, matrices, core_attack, core_selective, early_by_score)
    no_promote_fn = no_promotion_simulator()
    no_promote_ord, no_promote_diag = no_promote_fn(1, meta, matrices, core_attack, core_selective, early_by_score)

    variants = {
        "EARLY0": (base_ord, base_diag),
        "EARLY1_PROMOTE": (promote_ord, promote_diag),
        "EARLY1_NO_PROMOTE": (no_promote_ord, no_promote_diag),
    }

    perf_rows: list[dict[str, Any]] = []
    period_rows: list[dict[str, Any]] = []
    primary: dict[str, np.ndarray] = {}
    diagnostics = []
    dates_by_name = {}

    for name, (ordinary, diag) in variants.items():
        rets, perf, _ = ddv.combine_one(ordinary, reset, tq, args.tqqq_target)
        perf.insert(0, "variant", name)
        perf_rows.extend(perf.to_dict(orient="records"))
        dates = ordinary[["date"]].merge(reset[["date"]], on="date").merge(tq[["date"]], on="date", how="inner")["date"]
        dates_by_name[name] = dates
        for key, rr in rets.items():
            for p in ddv.subperiod_metrics(dates, rr):
                period_rows.append({"variant": name, "timing": key[0], "cost": key[1], "policy": key[2], **p})
        primary[name] = rets[PRIMARY_KEY]
        diagnostics.append({"variant": name, **diag})

    boot_rows = []
    for a, b in (("EARLY1_PROMOTE", "EARLY0"), ("EARLY1_NO_PROMOTE", "EARLY0"), ("EARLY1_PROMOTE", "EARLY1_NO_PROMOTE")):
        for block in (20, 60):
            z = ddv.ga.block_boot_pair(primary[a], primary[b], block, args.bootstrap_sims, 9100 + block + len(boot_rows))
            boot_rows.append({"a": a, "b": b, **z})

    perf_df = pd.DataFrame(perf_rows)
    periods_df = pd.DataFrame(period_rows)
    diag_df = pd.DataFrame(diagnostics)
    boot_df = pd.DataFrame(boot_rows)
    perf_df.to_csv(out / "early1_promotion_variants.csv", index=False)
    periods_df.to_csv(out / "early1_promotion_subperiods.csv", index=False)
    diag_df.to_csv(out / "early1_promotion_diagnostics.csv", index=False)
    boot_df.to_csv(out / "early1_promotion_bootstrap.csv", index=False)

    primary_perf = perf_df[
        perf_df["timing"].eq(PRIMARY_KEY[0]) & perf_df["cost"].eq(PRIMARY_KEY[1]) & perf_df["policy"].eq(PRIMARY_KEY[2])
    ].copy()
    summary = {
        "status": "GROSS100_EARLY1_PROMOTION_ATTRIBUTION",
        "primary": primary_perf.to_dict(orient="records"),
        "diagnostics": diag_df.to_dict(orient="records"),
        "bootstrap": boot_df.to_dict(orient="records"),
        "guardrail": "NO_PROMOTE is generated by disabling exactly the direct Early->Core promotion condition; all other mechanics are source-identical.",
    }
    (out / "early1_promotion_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
