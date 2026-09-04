from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import audit_gross100_ddv_refill_mode as ddv
import audit_gross100_component_series as comp
import audit_gross100_final_reset_component_series as final_reset
import audit_ordinary_stock_exit_trail as ex
import audit_ordinary_stock_market_mode_robustness as base
import audit_ordinary_stock_theme_leave_one_out as loo
import audit_staged_leader_liquidity_return as stage

LIQUIDITY_FLOOR = 20_000_000.0
EARLY_SLOTS = (0, 1, 2, 3)
EARLY_SCORE = "RS21_HIGH_ACCEL"
EARLY_GATE = "NOT_RED"
EARLY_MAX_DAYS = 10
PRIMARY_TIMING = "SAME_DAY_GROSS"
PRIMARY_COST = "BASE"
PRIMARY_POLICY = "SELECTIVE_FILL_NO_ZERO_OVERRIDE"


def _px(frame: pd.DataFrame, date: pd.Timestamp, sym: str, fallback: float | None = None) -> float | None:
    return comp._px(frame, date, sym, fallback)


def _gate_allowed(meta: dict[str, Any], d: pd.Timestamp) -> bool:
    color, _bucket, _ = stage.delay.market_state(meta, d)
    return bool(color != "Red")


def simulate_early_overlay(
    early_slots: int,
    meta: dict[str, Any],
    matrices: dict[str, pd.DataFrame],
    core_attack: dict[pd.Timestamp, list[tuple[str, dict[str, Any]]]],
    core_selective: dict[pd.Timestamp, list[tuple[str, dict[str, Any]]]],
    early_by_score: dict[str, dict[pd.Timestamp, list[tuple[str, float]]]],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    if early_slots not in EARLY_SLOTS or early_slots == 0:
        raise ValueError(early_slots)

    idx = pd.DatetimeIndex(meta["analysis_idx"])
    opens, closes, dvol = matrices["open"], matrices["close"], matrices["dvol"]
    breadth, nq = meta["breadth"], meta["nq"]
    cash = 1.0
    pos: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    red_run = 0
    early_entries = 0
    core_entries = 0
    promoted_core = 0
    early_expiry = 0
    early_stop = 0
    early_partial = 0
    index_pos = {pd.Timestamp(d): i for i, d in enumerate(idx)}

    def close_position(sym: str, price: float, reason: str) -> None:
        nonlocal cash, early_expiry, early_stop
        p = pos.pop(sym)
        cash += p["shares"] * price
        if p["entry_sleeve"] == "EARLY" and reason == "EARLY_EXPIRY":
            early_expiry += 1
        if p["entry_sleeve"] == "EARLY" and reason == "STOP":
            early_stop += 1

    def nav_open_value(date: pd.Timestamp, prev: pd.Timestamp) -> float:
        total = cash
        for sym, p in pos.items():
            opx = _px(opens, date, sym, _px(closes, prev, sym, p["entry_price"]))
            if opx is not None:
                total += p["shares"] * opx
        return total

    for i, d0 in enumerate(idx):
        d = pd.Timestamp(d0)
        prev = None if i == 0 else pd.Timestamp(idx[i - 1])
        fill_allowed = False
        market_color = ""
        market_bucket = 0

        if prev is not None:
            color = str(nq.at[prev, "nq_color"]) if prev in nq.index and pd.notna(nq.at[prev, "nq_color"]) else ""
            red_run = red_run + 1 if color == "Red" else 0
            red_force = color == "Red" and red_run >= 1

            if red_force:
                for sym in list(pos):
                    opx = _px(opens, d, sym, _px(closes, prev, sym, pos[sym]["entry_price"]))
                    if opx is not None:
                        close_position(sym, opx, "RED")
            else:
                for sym in list(pos):
                    p = pos[sym]
                    pc = _px(closes, prev, sym, p["entry_price"])
                    if pc is None:
                        continue
                    p["sessions"] += 1
                    age = index_pos[prev] - index_pos[p["entry_signal_date"]]
                    if p["sleeve"] == "EARLY" and age >= EARLY_MAX_DAYS:
                        opx = _px(opens, d, sym, pc)
                        if opx is not None:
                            close_position(sym, opx, "EARLY_EXPIRY")
                        continue

                    if (not p["partial_done"]) and pc >= p["entry_price"] * 1.24:
                        opx = _px(opens, d, sym, pc)
                        if opx is not None:
                            sold = p["shares"] * comp.PARTIAL_FRAC
                            cash += sold * opx
                            p["shares"] -= sold
                            p["partial_done"] = True
                            if p["entry_sleeve"] == "EARLY":
                                early_partial += 1

                    stop = max(p["entry_price"] * 0.92, p["peak_close"] * (1.0 - comp.PEAK_PCT / 100.0))
                    if pc <= stop and sym in pos:
                        opx = _px(opens, d, sym, pc)
                        if opx is not None:
                            close_position(sym, opx, "STOP")

            b = float(breadth.loc[prev]) if prev in breadth.index and pd.notna(breadth.loc[prev]) else np.nan
            bucket = base.breadth_bucket(b)
            bull = color in ("Blue", "Green")
            core_cap = (base.N_PORT - early_slots) if bull and bucket == 2 else 3 if bull and bucket == 1 else 0
            desired_early = early_slots if bucket == 2 else 1 if bucket == 1 else 0
            fill_allowed = bool(bull and np.isfinite(b) and b >= 50.0)
            market_color = color
            market_bucket = int(bucket)

            if not red_force:
                core_raw = core_attack.get(prev, []) if bucket == 2 else core_selective.get(prev, []) if bucket == 1 else []
                core_top12 = core_raw[: base.N_PORT]
                core_liquid = []
                for raw_rank, (sym, info) in enumerate(core_top12, start=1):
                    dv = _px(dvol, prev, sym, None)
                    if dv is not None and dv >= LIQUIDITY_FLOOR:
                        core_liquid.append((raw_rank, sym, info))
                core_take = core_liquid[:core_cap]
                core_symbols = {sym for _rank, sym, _info in core_take}

                core_count = sum(1 for p in pos.values() if p["sleeve"] == "CORE")
                if core_cap > 0 and core_count < core_cap:
                    for sym in list(pos):
                        if core_count >= core_cap:
                            break
                        if pos[sym]["sleeve"] == "EARLY" and sym in core_symbols:
                            pos[sym]["sleeve"] = "CORE"
                            pos[sym]["core_date"] = d
                            promoted_core += 1
                            core_count += 1

                if core_cap > 0 and core_count < core_cap:
                    slot_cash = nav_open_value(d, prev) / base.N_PORT
                    for raw_rank, sym, info in core_take:
                        if core_count >= core_cap or cash <= 0:
                            break
                        if sym in pos:
                            continue
                        opx = _px(opens, d, sym, _px(closes, prev, sym, None))
                        if opx is None:
                            continue
                        alloc = min(slot_cash, cash)
                        if alloc <= 1e-10:
                            break
                        cash -= alloc
                        pos[sym] = {
                            "shares": alloc / opx,
                            "entry_price": opx,
                            "entry_date": d,
                            "entry_signal_date": prev,
                            "peak_close": opx,
                            "sessions": 0,
                            "partial_done": False,
                            "entry_dvol": _px(dvol, prev, sym, None),
                            "raw_rank": raw_rank,
                            "sleeve": "CORE",
                            "entry_sleeve": "CORE",
                            **info,
                        }
                        core_entries += 1
                        core_count += 1

                if _gate_allowed(meta, prev) and desired_early > 0:
                    early_count = sum(1 for p in pos.values() if p["sleeve"] == "EARLY")
                    if early_count < desired_early:
                        slot_cash = nav_open_value(d, prev) / base.N_PORT
                        for rank, (sym, score) in enumerate(early_by_score[EARLY_SCORE].get(prev, []), start=1):
                            if early_count >= desired_early or cash <= 0:
                                break
                            if sym in pos:
                                continue
                            dv = _px(dvol, prev, sym, None)
                            if dv is None or dv < LIQUIDITY_FLOOR:
                                continue
                            opx = _px(opens, d, sym, _px(closes, prev, sym, None))
                            if opx is None:
                                continue
                            alloc = min(slot_cash, cash)
                            if alloc <= 1e-10:
                                break
                            cash -= alloc
                            pos[sym] = {
                                "shares": alloc / opx,
                                "entry_price": opx,
                                "entry_date": d,
                                "entry_signal_date": prev,
                                "peak_close": opx,
                                "sessions": 0,
                                "partial_done": False,
                                "entry_dvol": dv,
                                "early_rank": rank,
                                "entry_score": score,
                                "sleeve": "EARLY",
                                "entry_sleeve": "EARLY",
                            }
                            early_entries += 1
                            early_count += 1

        gross = 0.0
        nav = cash
        core_n = 0
        early_n = 0
        for sym, p in pos.items():
            cp = _px(closes, d, sym, _px(opens, d, sym, p["entry_price"]))
            if cp is None:
                cp = p["entry_price"]
            p["peak_close"] = max(p["peak_close"], cp)
            mark = p["shares"] * cp
            gross += mark
            nav += mark
            if p["sleeve"] == "CORE":
                core_n += 1
            else:
                early_n += 1
        rows.append({
            "date": d,
            "nav": nav,
            "gross_value": gross,
            "gross_exposure": gross / nav if nav > 0 else np.nan,
            "positions": len(pos),
            "core_positions": core_n,
            "early_positions": early_n,
            "selective_fill_allowed": bool(fill_allowed),
            "market_color_prev": market_color,
            "market_bucket_prev": market_bucket,
            "liquidity_floor": LIQUIDITY_FLOOR,
            "early_slots": early_slots,
        })

    out = pd.DataFrame(rows).set_index("date")
    out["return"] = out["nav"].pct_change(fill_method=None).fillna(0.0)
    diag = {
        "early_slots": int(early_slots),
        "early_score": EARLY_SCORE,
        "early_gate": EARLY_GATE,
        "early_max_days": EARLY_MAX_DAYS,
        "core_entries": int(core_entries),
        "early_entries": int(early_entries),
        "promoted_core": int(promoted_core),
        "promotion_rate": float(promoted_core / early_entries) if early_entries else 0.0,
        "early_expiry": int(early_expiry),
        "early_stop": int(early_stop),
        "early_partial": int(early_partial),
        "avg_positions": float(out["positions"].mean()),
        "avg_core_positions": float(out["core_positions"].mean()),
        "avg_early_positions": float(out["early_positions"].mean()),
        "avg_gross": float(out["gross_exposure"].mean()),
        "max_gross": float(out["gross_exposure"].max()),
    }
    return out.reset_index(), diag


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
    reset, reset_turnover = comp.simulate_reset(cal, matrices["open"], matrices["close"], reset_trades)
    tq = pd.read_csv(args.tqqq_daily, compression="gzip")
    tq["date"] = pd.to_datetime(tq["date"])

    perf_all = []
    period_rows = []
    diagnostics = []
    primary_returns: dict[int, np.ndarray] = {}

    for e in EARLY_SLOTS:
        print(f"RUN EARLY_SLOTS={e}", flush=True)
        if e == 0:
            ordinary, cdiag = ddv.simulate_ordinary_mode(meta, matrices, peer_ctx, LIQUIDITY_FLOOR, "VACANCY_TOP12")
            cdiag = {"early_slots": 0, **cdiag}
        else:
            ordinary, cdiag = simulate_early_overlay(e, meta, matrices, core_attack, core_selective, early_by_score)
        diagnostics.append(cdiag)
        ordinary.to_csv(out / f"ordinary_DDV20_EARLY{e}_daily.csv.gz", index=False, compression="gzip")

        rets, perf, _gdiag = ddv.combine_one(ordinary, reset, tq, args.tqqq_target)
        perf.insert(0, "early_slots", e)
        perf_all.append(perf)
        dates = ordinary[["date"]].merge(reset[["date"]], on="date").merge(tq[["date"]], on="date", how="inner")["date"]
        for (timing, cost, policy), rr in rets.items():
            for row in ddv.subperiod_metrics(dates, rr):
                period_rows.append({"early_slots": e, "timing": timing, "cost": cost, "policy": policy, **row})
        primary_returns[e] = rets[(PRIMARY_TIMING, PRIMARY_COST, PRIMARY_POLICY)]

    perf_df = pd.concat(perf_all, ignore_index=True)
    periods_df = pd.DataFrame(period_rows)
    primary = perf_df[
        perf_df["timing"].eq(PRIMARY_TIMING)
        & perf_df["cost"].eq(PRIMARY_COST)
        & perf_df["policy"].eq(PRIMARY_POLICY)
    ].copy().sort_values(["calmar", "cagr", "mdd"], ascending=[False, False, False])

    boot_rows = []
    baseline = primary_returns[0]
    for e, rr in primary_returns.items():
        for block in (20, 60):
            b = ddv.ga.block_boot_pair(rr, baseline, block, args.bootstrap_sims, 20260940 + e * 100 + block)
            boot_rows.append({"early_slots": e, "comparison": "vs_EARLY0", **b})

    perf_df.to_csv(out / "early_slot_variants.csv", index=False)
    periods_df.to_csv(out / "early_slot_subperiods.csv", index=False)
    pd.DataFrame(diagnostics).to_csv(out / "early_slot_diagnostics.csv", index=False)
    pd.DataFrame(boot_rows).to_csv(out / "early_slot_bootstrap.csv", index=False)
    primary.to_csv(out / "early_slot_primary_ranking.csv", index=False)

    summary = {
        "status": "GROSS100_EARLY_SLOT_OVERLAY_AUDIT",
        "base": "VACANCY_TOP12_DDV20",
        "liquidity_floor": LIQUIDITY_FLOOR,
        "early_score": EARLY_SCORE,
        "early_gate": EARLY_GATE,
        "early_max_days": EARLY_MAX_DAYS,
        "structure": "Attack reserves E of 12 ordinary slots for Early; Selective uses Core3+Early1 when E>0; Early promotes directly to Core or expires at D10.",
        "tqqq_target": args.tqqq_target,
        "reset_rule": final_reset.FINAL_RESET_RULE,
        "primary": {"timing": PRIMARY_TIMING, "cost": PRIMARY_COST, "policy": PRIMARY_POLICY},
        "guardrails": [
            "No Confirmed sleeve.",
            "No main/UI/live changes.",
            "Core ranking/exit/NQSAR/Breadth, TQQQ F80 D10, final RSI30 Reset, Gross100 and Selective Fill are fixed.",
            "Early signal definition is frozen from the prior staged-leader development winner; only Early slot count is varied.",
        ],
        "reset_turnover_value": float(reset_turnover),
        "primary_ranking": primary[["early_slots", "cagr", "mdd", "sharpe", "calmar", "avg_alloc_t", "avg_alloc_o", "avg_alloc_r", "avg_total_gross"]].to_dict("records"),
        "diagnostics": diagnostics,
    }
    (out / "early_slot_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
