from __future__ import annotations

import argparse
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
DDV_FLOOR = 20_000_000.0


def safe(v: Any) -> Any:
    if isinstance(v, dict):
        return {str(k): safe(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [safe(x) for x in v]
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, (np.floating, float)):
        x = float(v)
        return x if np.isfinite(x) else None
    if isinstance(v, pd.Timestamp):
        return v.isoformat()
    return v


def pct(frame: pd.DataFrame, mask: pd.DataFrame) -> pd.DataFrame:
    return (frame.where(mask).rank(axis=1, pct=True, method="average") * 100.0).astype(np.float32)


def add_aligned_scores(ctx: dict[str, Any], matrices: dict[str, pd.DataFrame]) -> None:
    """Add two frozen liquidity variants without changing any portfolio mechanics.

    LEGACY_LIQ_ACCEL isolates liquidity information on top of the legacy
    RS21_HIGH_ACCEL score. CURRENT_LIQ_ACCEL_PORT ports the later frozen
    LIQ_ACCEL definition exactly into the legacy Gross100 engine.
    """
    close = matrices["close"]
    dvol = matrices["dvol"]
    pool = ctx["pool"].fillna(False)
    rs = ctx["rs"]

    # Isolated liquidity addition: preserve the legacy RS21_HIGH_ACCEL score.
    liq_pool = pct(np.log(dvol.clip(lower=1.0)), pool)
    ddv_acc10_pool = pct(dvol / dvol.shift(10) - 1.0, pool)
    legacy_base = ctx["scores"]["RS21_HIGH_ACCEL"].astype(np.float32)
    ctx["scores"]["LEGACY_LIQ_ACCEL"] = (
        0.80 * legacy_base
        + 0.10 * liq_pool.fillna(50.0)
        + 0.10 * ddv_acc10_pool.fillna(50.0)
    ).astype(np.float32)

    # Exact later LIQ_ACCEL score definition, but evaluated inside this old engine.
    radar = (pool & ((rs[21] >= 85.0) | (rs[42] >= 85.0) | (rs[63] >= 85.0))).fillna(False)
    prior63 = close.shift(1).rolling(63, min_periods=40).max()
    high63 = pct(close / prior63, radar)
    acc10 = pct(rs[21] - rs[21].shift(10), radar)
    base10 = (
        0.50 * rs[21].where(radar).fillna(50.0)
        + 0.25 * high63.fillna(50.0)
        + 0.25 * acc10.fillna(50.0)
    ).astype(np.float32)
    liq_radar = pct(np.log(dvol.clip(lower=1.0)), radar)
    ddv_acc10_radar = pct(dvol / dvol.shift(10) - 1.0, radar)
    current = (
        0.80 * base10
        + 0.10 * liq_radar.fillna(50.0)
        + 0.10 * ddv_acc10_radar.fillna(50.0)
    ).astype(np.float32)
    ctx["scores"]["CURRENT_LIQ_ACCEL_PORT"] = current.where(radar)


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

    print("BUILD frozen old-engine inputs", flush=True)
    meta, matrices = ex.build_inputs_ext(root, args.analysis_start, args.analysis_end, args.max_tickers, args.batch_size)
    peer_ctx = loo.build_leave_one_out_scores(root, matrices)
    ctx = stage.build_signal_context(root, matrices)
    add_aligned_scores(ctx, matrices)
    core_attack, core_selective, early_by_score = stage.precompute_candidates(meta, matrices, peer_ctx, ctx)
    cal = pd.DatetimeIndex(meta["analysis_idx"])

    reset_trades = final_reset.prepare_final_reset_trades(Path(args.reset_trades), cal, matrices["close"].columns)
    reset, _ = comp.simulate_reset(cal, matrices["open"], matrices["close"], reset_trades)
    tq = pd.read_csv(args.tqqq_daily, compression="gzip")
    tq["date"] = pd.to_datetime(tq["date"])

    early.EARLY_GATE = "NOT_RED"
    early.EARLY_MAX_DAYS = 10

    base_ord, base_diag = ddv.simulate_ordinary_mode(meta, matrices, peer_ctx, DDV_FLOOR, "VACANCY_TOP12")

    variants: dict[str, tuple[pd.DataFrame, dict[str, Any]]] = {
        "EARLY0": (base_ord, {"early_score": None, **base_diag}),
    }
    for name, score_key in (
        ("EARLY1_LEGACY", "RS21_HIGH_ACCEL"),
        ("EARLY1_LEGACY_LIQ_ACCEL", "LEGACY_LIQ_ACCEL"),
        ("EARLY1_CURRENT_LIQ_ACCEL_PORT", "CURRENT_LIQ_ACCEL_PORT"),
    ):
        print(f"SIM {name}", flush=True)
        early.EARLY_SCORE = score_key
        ordinary, diag = early.simulate_early_overlay(1, meta, matrices, core_attack, core_selective, early_by_score)
        variants[name] = (ordinary, diag)

    perf_rows: list[dict[str, Any]] = []
    period_rows: list[dict[str, Any]] = []
    primary: dict[str, np.ndarray] = {}
    diagnostics: list[dict[str, Any]] = []

    for name, (ordinary, diag) in variants.items():
        rets, perf, _ = ddv.combine_one(ordinary, reset, tq, args.tqqq_target)
        perf.insert(0, "variant", name)
        perf_rows.extend(perf.to_dict(orient="records"))
        dates = ordinary[["date"]].merge(reset[["date"]], on="date").merge(tq[["date"]], on="date", how="inner")["date"]
        for key, rr in rets.items():
            for p in ddv.subperiod_metrics(dates, rr):
                period_rows.append({"variant": name, "timing": key[0], "cost": key[1], "policy": key[2], **p})
        primary[name] = rets[PRIMARY_KEY]
        diagnostics.append({"variant": name, **diag})
        ordinary.to_csv(out / f"ordinary_{name}.csv.gz", index=False, compression="gzip")

    pairs = [
        ("EARLY1_LEGACY", "EARLY0"),
        ("EARLY1_LEGACY_LIQ_ACCEL", "EARLY0"),
        ("EARLY1_CURRENT_LIQ_ACCEL_PORT", "EARLY0"),
        ("EARLY1_LEGACY_LIQ_ACCEL", "EARLY1_LEGACY"),
        ("EARLY1_CURRENT_LIQ_ACCEL_PORT", "EARLY1_LEGACY"),
        ("EARLY1_CURRENT_LIQ_ACCEL_PORT", "EARLY1_LEGACY_LIQ_ACCEL"),
    ]
    boot_rows: list[dict[str, Any]] = []
    for j, (a, b) in enumerate(pairs):
        for block in (20, 60):
            z = ddv.ga.block_boot_pair(primary[a], primary[b], block, args.bootstrap_sims, 9400 + 97 * j + block)
            boot_rows.append({"a": a, "b": b, **z})

    perf_df = pd.DataFrame(perf_rows)
    periods_df = pd.DataFrame(period_rows)
    diag_df = pd.DataFrame(diagnostics)
    boot_df = pd.DataFrame(boot_rows)
    perf_df.to_csv(out / "aligned_variants.csv", index=False)
    periods_df.to_csv(out / "aligned_subperiods.csv", index=False)
    diag_df.to_csv(out / "aligned_diagnostics.csv", index=False)
    boot_df.to_csv(out / "aligned_bootstrap.csv", index=False)

    primary_perf = perf_df[
        perf_df["timing"].eq(PRIMARY_KEY[0])
        & perf_df["cost"].eq(PRIMARY_KEY[1])
        & perf_df["policy"].eq(PRIMARY_KEY[2])
    ].copy()
    primary_periods = periods_df[
        periods_df["timing"].eq(PRIMARY_KEY[0])
        & periods_df["cost"].eq(PRIMARY_KEY[1])
        & periods_df["policy"].eq(PRIMARY_KEY[2])
    ].copy()

    summary = {
        "status": "GROSS100_EARLY1_LIQUIDITY_ALIGNED_AUDIT",
        "engine_lock": {
            "ddv_floor": DDV_FLOOR,
            "core_refill": "VACANCY_TOP12",
            "early_slots": 1,
            "early_gate": "NOT_RED",
            "early_max_days": 10,
            "direct_early_to_core_promotion": True,
            "tqqq_target": args.tqqq_target,
            "timing": PRIMARY_KEY[0],
            "cost": PRIMARY_KEY[1],
            "selective_policy": PRIMARY_KEY[2],
            "reset_input": str(args.reset_trades),
            "tqqq_input": str(args.tqqq_daily),
        },
        "score_lock": {
            "EARLY1_LEGACY": "legacy RS21_HIGH_ACCEL = 50% RS21 + 25% HIGH63 + 25% percentile(RS21 - RS21.shift(20))",
            "EARLY1_LEGACY_LIQ_ACCEL": "80% legacy RS21_HIGH_ACCEL + 10% DDV-level percentile + 10% 10-session DDV-acceleration percentile; liquidity percentiles computed in legacy pool",
            "EARLY1_CURRENT_LIQ_ACCEL_PORT": "ported later LIQ_ACCEL = 80% [50% RS21 +25% HIGH63 +25% percentile(RS21-RS21.shift(10))] +10% DDV-level percentile +10% DDV-acc10 percentile, components computed in later radar population",
        },
        "primary": primary_perf.to_dict(orient="records"),
        "primary_subperiods": primary_periods.to_dict(orient="records"),
        "diagnostics": diag_df.to_dict(orient="records"),
        "bootstrap": boot_df.to_dict(orient="records"),
        "guardrail": "Only Early ranking score changes across Early1 variants. Gross100 integration, Core, Reset, TQQQ, gate, hold period, promotion, cost, timing, and selective policy are source-identical.",
    }
    (out / "aligned_summary.json").write_text(json.dumps(safe(summary), ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== ALIGNED_EARLY1_JSON ===", flush=True)
    print(json.dumps(safe(summary), ensure_ascii=False, indent=2), flush=True)
    print("=== END_ALIGNED_EARLY1_JSON ===", flush=True)


if __name__ == "__main__":
    main()
