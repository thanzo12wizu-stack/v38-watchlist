from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import audit_gross100_allocation as ga
import audit_gross100_component_series as comp
import audit_gross100_final_reset_component_series as final_reset
import audit_ordinary_stock_exit_trail as ex
import audit_ordinary_stock_market_mode_robustness as base
import audit_ordinary_stock_theme_leave_one_out as loo

TRADING_DAYS = 252
LIQUIDITY_FLOORS = (10_000_000.0, 20_000_000.0, 50_000_000.0, 100_000_000.0)
MODES = ("VACANCY_TOP12", "REFILL_TOP40")
PRIMARY_TIMING = "SAME_DAY_GROSS"
PRIMARY_COST = "BASE"
PRIMARY_POLICY = "SELECTIVE_FILL_NO_ZERO_OVERRIDE"


def _px(frame: pd.DataFrame, date: pd.Timestamp, sym: str, fallback: float | None = None) -> float | None:
    return comp._px(frame, date, sym, fallback)


def simulate_ordinary_mode(
    meta: dict[str, Any],
    matrices: dict[str, pd.DataFrame],
    peer_ctx: dict[str, Any],
    liquidity_floor: float,
    mode: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Exact adopted ordinary-stock mechanics with one isolated DDV implementation switch.

    VACANCY_TOP12: build adopted Top12 first; a DDV failure leaves the slot vacant.
    REFILL_TOP40: rank Top40 first; apply DDV entry filter; then take the same market-mode cap. This refills only DDV-rejected ranks, not vacancies caused by already-held names.

    Existing positions are never sold only because DDV later falls.
    """
    if mode not in MODES:
        raise ValueError(mode)

    idx = pd.DatetimeIndex(meta["analysis_idx"])
    opens, closes, dvol = matrices["open"], matrices["close"], matrices["dvol"]
    breadth, nq = meta["breadth"], meta["nq"]
    cash = 1.0
    pos: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    red_run = 0
    entry_count = 0
    refill_beyond12_entries = 0
    refill_beyond_cap_entries = 0
    blocked_top12_candidates = 0

    def close_position(sym: str, price: float) -> None:
        nonlocal cash
        p = pos.pop(sym)
        cash += p["shares"] * price

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
                        close_position(sym, opx)
            else:
                for sym in list(pos):
                    p = pos[sym]
                    pc = _px(closes, prev, sym, p["entry_price"])
                    if pc is None:
                        continue
                    p["sessions"] += 1
                    if (not p["partial_done"]) and pc >= p["entry_price"] * 1.24:
                        opx = _px(opens, d, sym, pc)
                        if opx is not None:
                            sold = p["shares"] * comp.PARTIAL_FRAC
                            cash += sold * opx
                            p["shares"] -= sold
                            p["partial_done"] = True
                    stop = max(p["entry_price"] * 0.92, p["peak_close"] * (1.0 - comp.PEAK_PCT / 100.0))
                    if pc <= stop:
                        opx = _px(opens, d, sym, pc)
                        if opx is not None:
                            close_position(sym, opx)

            b = float(breadth.loc[prev]) if prev in breadth.index and pd.notna(breadth.loc[prev]) else np.nan
            bucket = base.breadth_bucket(b)
            bull = color in ("Blue", "Green")
            cap = base.N_PORT if bull and bucket == 2 else comp.SELECTIVE_SLOTS if bull and bucket == 1 else 0
            fill_allowed = bool(bull and np.isfinite(b) and b >= 50.0)
            market_color = color
            market_bucket = int(bucket)

            if (not red_force) and cap > 0 and len(pos) < cap:
                depth = base.N_PORT if mode == "VACANCY_TOP12" else 40
                candidates_raw = ex.ranked_candidates(prev, matrices, peer_ctx, bucket, depth)

                if float(liquidity_floor) > 10_000_000.0:
                    for raw_rank, (sym0, _info0) in enumerate(candidates_raw[: base.N_PORT], start=1):
                        if sym0 in pos:
                            continue
                        dv0 = _px(dvol, prev, sym0, None)
                        if dv0 is None or dv0 < float(liquidity_floor):
                            blocked_top12_candidates += 1

                if mode == "VACANCY_TOP12":
                    candidates = [(rank, sym, info) for rank, (sym, info) in enumerate(candidates_raw, start=1)]
                else:
                    liquid = []
                    for raw_rank, (sym, info) in enumerate(candidates_raw, start=1):
                        dv = _px(dvol, prev, sym, None)
                        if dv is not None and dv >= float(liquidity_floor):
                            liquid.append((raw_rank, sym, info))
                    candidates = liquid[:cap]

                nav_open = cash
                for sym, p in pos.items():
                    opx = _px(opens, d, sym, _px(closes, prev, sym, p["entry_price"]))
                    if opx is not None:
                        nav_open += p["shares"] * opx
                slot_cash = nav_open / base.N_PORT

                for raw_rank, sym, c in candidates:
                    if len(pos) >= cap or cash <= 0:
                        break
                    if sym in pos:
                        continue
                    dv = _px(dvol, prev, sym, None)
                    if dv is None or dv < float(liquidity_floor):
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
                        "peak_close": opx,
                        "sessions": 0,
                        "partial_done": False,
                        "entry_dvol": dv,
                        "raw_rank": raw_rank,
                        **c,
                    }
                    entry_count += 1
                    if mode == "REFILL_TOP40":
                        if raw_rank > base.N_PORT:
                            refill_beyond12_entries += 1
                        if raw_rank > cap:
                            refill_beyond_cap_entries += 1

        gross = 0.0
        nav = cash
        for sym, p in pos.items():
            cp = _px(closes, d, sym, _px(opens, d, sym, p["entry_price"]))
            if cp is None:
                cp = p["entry_price"]
            p["peak_close"] = max(p["peak_close"], cp)
            mark = p["shares"] * cp
            gross += mark
            nav += mark
        rows.append({
            "date": d,
            "nav": nav,
            "gross_value": gross,
            "gross_exposure": gross / nav if nav > 0 else np.nan,
            "positions": len(pos),
            "selective_fill_allowed": bool(fill_allowed),
            "market_color_prev": market_color,
            "market_bucket_prev": market_bucket,
            "liquidity_floor": float(liquidity_floor),
            "ddv_mode": mode,
        })

    out = pd.DataFrame(rows).set_index("date")
    out["return"] = out["nav"].pct_change(fill_method=None).fillna(0.0)
    diag = {
        "mode": mode,
        "liquidity_floor": float(liquidity_floor),
        "entry_count": int(entry_count),
        "blocked_top12_candidates": int(blocked_top12_candidates),
        "refill_beyond12_entries": int(refill_beyond12_entries),
        "refill_beyond12_share": float(refill_beyond12_entries / entry_count) if entry_count else 0.0,
        "refill_beyond_cap_entries": int(refill_beyond_cap_entries),
        "refill_beyond_cap_share": float(refill_beyond_cap_entries / entry_count) if entry_count else 0.0,
        "avg_positions": float(out["positions"].mean()),
        "avg_gross": float(out["gross_exposure"].mean()),
        "max_gross": float(out["gross_exposure"].max()),
    }
    return out.reset_index(), diag


def combine_one(
    ordinary: pd.DataFrame,
    reset: pd.DataFrame,
    tq: pd.DataFrame,
    tqqq_target: str,
) -> tuple[dict[tuple[str, str, str], np.ndarray], pd.DataFrame, dict[str, Any]]:
    d = ordinary.merge(reset, on="date", suffixes=("_ord", "_rsi")).merge(tq, on="date", how="inner")
    if tqqq_target not in d.columns:
        raise KeyError(tqqq_target)
    n = len(d)
    native_target = pd.to_numeric(d[tqqq_target], errors="coerce").fillna(0.0).to_numpy(float)
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
        "SAME_DAY_GROSS": (raw_o.copy(), raw_r.copy(), gate0.copy()),
        "LAG1_GROSS": (np.r_[0.0, raw_o[:-1]], np.r_[0.0, raw_r[:-1]], np.r_[False, gate0[:-1]]),
    }
    costs = {"BASE": None, "ALL5": 5.0, "ALL10": 10.0, "ALL20": 20.0}
    returns: dict[tuple[str, str, str], np.ndarray] = {}
    perf_rows: list[dict[str, Any]] = []

    for timing, (comp_o, comp_r, gate) in timings.items():
        desired_o = np.minimum(np.maximum(comp_o, 0.0), ga.NORMAL_CAP)
        desired_r = np.maximum(comp_r, 0.0)
        g = np.column_stack([np.maximum(eff_t, 0.0), desired_o, desired_r])
        policies = {
            "NATIVE_NO_FILL": ga.native_gross100(g),
            "SELECTIVE_FILL_NO_ZERO_OVERRIDE": ga.selective_fill_no_zero_override(g, gate),
        }
        native_alloc = policies["NATIVE_NO_FILL"]
        for policy, alloc in policies.items():
            if float(alloc.sum(axis=1).max()) > 1.0 + 1e-9:
                raise RuntimeError(f"Gross100 violation {timing} {policy}")
            for cost_name, cbps in costs.items():
                rr, turn = ga.scaled_returns(alloc, comp_o, comp_r, ret_t, ret_o, ret_r, cbps)
                returns[(timing, cost_name, policy)] = rr
                perf_rows.append({
                    "timing": timing,
                    "cost": cost_name,
                    "policy": policy,
                    **ga.metrics(rr),
                    "avg_alloc_t": float(alloc[:, 0].mean()),
                    "avg_alloc_o": float(alloc[:, 1].mean()),
                    "avg_alloc_r": float(alloc[:, 2].mean()),
                    "avg_total_gross": float(alloc.sum(axis=1).mean()),
                    "max_total_gross": float(alloc.sum(axis=1).max()),
                    "pct_at_100": float((alloc.sum(axis=1) >= 1.0 - 1e-9).mean()),
                    "selective_fill_days": int((gate & (eff_t > 1e-12) & (alloc[:, 0] > native_alloc[:, 0] + 1e-12)).sum()) if policy == "SELECTIVE_FILL_NO_ZERO_OVERRIDE" else 0,
                    **turn,
                })

    diag = {
        "days": int(n),
        "start": str(pd.Timestamp(d.date.min()).date()),
        "end": str(pd.Timestamp(d.date.max()).date()),
        "raw_o_avg": float(raw_o.mean()),
        "raw_o_max": float(raw_o.max()),
        "fill_gate_days": int(gate0.sum()),
        "native_t_positive_days": int((eff_t > 1e-12).sum()),
        "fill_eligible_days": int((gate0 & (eff_t > 1e-12)).sum()),
    }
    return returns, pd.DataFrame(perf_rows), diag


def subperiod_metrics(dates: pd.Series, rr: np.ndarray) -> list[dict[str, Any]]:
    periods = [
        ("FULL", pd.Timestamp("2016-01-04"), pd.Timestamp("2026-03-20")),
        ("DEV_2016_2020", pd.Timestamp("2016-01-04"), pd.Timestamp("2020-12-31")),
        ("CONFIRM_2021_2023", pd.Timestamp("2021-01-01"), pd.Timestamp("2023-12-31")),
        ("HOLDOUT_2024_2026M3", pd.Timestamp("2024-01-01"), pd.Timestamp("2026-03-20")),
        ("SINCE_2021", pd.Timestamp("2021-01-01"), pd.Timestamp("2026-03-20")),
    ]
    out = []
    dt = pd.to_datetime(dates)
    for label, start, end in periods:
        mask = ((dt >= start) & (dt <= end)).to_numpy()
        out.append({"period": label, **ga.metrics(rr[mask])})
    return out


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
    cal = pd.DatetimeIndex(meta["analysis_idx"])

    reset_trades = final_reset.prepare_final_reset_trades(Path(args.reset_trades), cal, matrices["close"].columns)
    reset, reset_turnover = comp.simulate_reset(cal, matrices["open"], matrices["close"], reset_trades)
    tq = pd.read_csv(args.tqqq_daily, compression="gzip")
    tq["date"] = pd.to_datetime(tq["date"])

    perf_all: list[pd.DataFrame] = []
    period_rows: list[dict[str, Any]] = []
    component_diags: list[dict[str, Any]] = []
    combine_diags: dict[str, Any] = {}
    primary_returns: dict[tuple[str, int], np.ndarray] = {}

    for mode in MODES:
        for floor in LIQUIDITY_FLOORS:
            label = int(floor / 1_000_000)
            print(f"RUN {mode} DDV>={label}M", flush=True)
            ordinary, cdiag = simulate_ordinary_mode(meta, matrices, peer_ctx, floor, mode)
            component_diags.append(cdiag)
            ordinary.to_csv(out / f"ordinary_{mode}_DDV{label}M_daily.csv.gz", index=False, compression="gzip")

            rets, perf, gdiag = combine_one(ordinary, reset, tq, args.tqqq_target)
            perf.insert(0, "ddv_m", label)
            perf.insert(0, "mode", mode)
            perf_all.append(perf)
            combine_diags[f"{mode}_DDV{label}M"] = gdiag

            merged_dates = ordinary[["date"]].merge(reset[["date"]], on="date").merge(tq[["date"]], on="date", how="inner")["date"]
            for key, rr in rets.items():
                timing, cost_name, policy = key
                for row in subperiod_metrics(merged_dates, rr):
                    period_rows.append({
                        "mode": mode,
                        "ddv_m": label,
                        "timing": timing,
                        "cost": cost_name,
                        "policy": policy,
                        **row,
                    })
            primary_returns[(mode, label)] = rets[(PRIMARY_TIMING, PRIMARY_COST, PRIMARY_POLICY)]

    perf_df = pd.concat(perf_all, ignore_index=True)
    periods_df = pd.DataFrame(period_rows)
    comp_df = pd.DataFrame(component_diags)

    primary = perf_df[
        perf_df["timing"].eq(PRIMARY_TIMING)
        & perf_df["cost"].eq(PRIMARY_COST)
        & perf_df["policy"].eq(PRIMARY_POLICY)
    ].copy()
    primary = primary.sort_values(["calmar", "cagr", "mdd"], ascending=[False, False, False])

    boot_rows: list[dict[str, Any]] = []
    baseline = primary_returns[("VACANCY_TOP12", 10)]
    for (mode, label), rr in primary_returns.items():
        for block in (20, 60):
            b = ga.block_boot_pair(rr, baseline, block, args.bootstrap_sims, 20260904 + label + block + (1000 if mode == "REFILL_TOP40" else 0))
            boot_rows.append({"comparison": "vs_VACANCY_TOP12_DDV10", "mode": mode, "ddv_m": label, **b})

    for label in (10, 20, 50, 100):
        a = primary_returns[("REFILL_TOP40", label)]
        b0 = primary_returns[("VACANCY_TOP12", label)]
        for block in (20, 60):
            b = ga.block_boot_pair(a, b0, block, args.bootstrap_sims, 20261904 + label + block)
            boot_rows.append({"comparison": "REFILL_vs_VACANCY_same_DDV", "mode": "REFILL_TOP40", "ddv_m": label, **b})

    perf_df.to_csv(out / "ddv_refill_variants.csv", index=False)
    periods_df.to_csv(out / "ddv_refill_subperiods.csv", index=False)
    comp_df.to_csv(out / "ddv_refill_component_diagnostics.csv", index=False)
    pd.DataFrame(boot_rows).to_csv(out / "ddv_refill_bootstrap.csv", index=False)
    primary.to_csv(out / "ddv_refill_primary_ranking.csv", index=False)

    summary = {
        "status": "GROSS100_DDV_IMPLEMENTATION_MODE_AUDIT",
        "analysis_start": args.analysis_start,
        "analysis_end": args.analysis_end,
        "tqqq_target": args.tqqq_target,
        "reset_rule": final_reset.FINAL_RESET_RULE,
        "primary": {
            "timing": PRIMARY_TIMING,
            "cost": PRIMARY_COST,
            "policy": PRIMARY_POLICY,
        },
        "modes": {
            "VACANCY_TOP12": "Rank adopted Top12 first; DDV failures create vacancies; never reach rank 13+.",
            "REFILL_TOP40": "Rank Top40 first; filter by DDV; then take the same market-mode cap. Already-held names can still leave vacancies, matching the single-stock DDV audit structure.",
        },
        "guardrails": [
            "No main/UI/live changes.",
            "Existing positions are not exited only because DDV later falls.",
            "Ordinary stock exit/partial-profit/NQSAR/Breadth mechanics are held fixed.",
            "TQQQ F80 D10, final RSI30 Reset, Gross100 and Selective Fill are held fixed.",
        ],
        "reset_turnover_value": float(reset_turnover),
        "primary_ranking": primary[["mode", "ddv_m", "cagr", "mdd", "sharpe", "calmar", "avg_alloc_t", "avg_alloc_o", "avg_alloc_r", "avg_total_gross"]].to_dict("records"),
        "component_diagnostics": component_diags,
        "combine_diagnostics": combine_diags,
    }
    (out / "ddv_refill_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
