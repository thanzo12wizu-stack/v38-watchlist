from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import audit_early1_big_leader_capture as cap
import audit_gross100_early_slot_overlay as early
import audit_ordinary_stock_exit_trail as ex
import audit_ordinary_stock_theme_leave_one_out as loo
import audit_staged_leader_liquidity_return as stage

LIQUIDITY_FLOOR = 20_000_000.0
EARLY_SCORE = "RS21_HIGH_ACCEL"
EARLY_GATE = "NOT_RED"
EARLY_MAX_DAYS = 10
SLOTS = (1, 2, 3)


def safe(v: Any) -> Any:
    return cap.safe(v)


def event_row(ev: pd.Series, intervals: pd.DataFrame, core_intervals: pd.DataFrame, slots: int) -> dict[str, Any]:
    sym = str(ev["symbol"])
    start = pd.Timestamp(ev["anchor_date"])
    end = pd.Timestamp(ev["end_date"])
    anchor_price = float(ev["anchor_price"])
    got = cap.find_capture(intervals, sym, start, end, anchor_price)
    core = cap.find_capture(core_intervals, sym, start, end, anchor_price)
    gain = float(got["gain"]) if got is not None else np.nan
    sleeve = str(got["sleeve"]) if got is not None else None
    core_gain = float(core["gain"]) if core is not None else np.nan
    saved = bool(
        got is not None
        and sleeve == "EARLY"
        and (core is None or pd.Timestamp(got["date"]) < pd.Timestamp(core["date"]))
    )
    return {
        "slots": int(slots),
        "event_set": str(ev["event_set"]),
        "year": int(ev["year"]),
        "period": "DEV_2016_2020" if int(ev["year"]) <= 2020 else "CONFIRM_2021_2025",
        "symbol": sym,
        "anchor_date": start,
        "end_date": end,
        "future_return": float(ev["future_return"]),
        "captured": got is not None,
        "entry_date": got["date"] if got is not None else pd.NaT,
        "actual_entry_date": got["actual_entry_date"] if got is not None else pd.NaT,
        "entry_gain": gain,
        "entry_sleeve": sleeve,
        "final_sleeve": got["final_sleeve"] if got is not None else None,
        "preheld": bool(got["preheld"]) if got is not None else False,
        "core20_captured": core is not None,
        "core20_entry_gain": core_gain,
        "saved_by_early": saved,
    }


def summarize(g: pd.DataFrame) -> dict[str, Any]:
    n = len(g)
    captured = g["captured"].astype(bool)
    gain = pd.to_numeric(g["entry_gain"], errors="coerce")
    early_hit = captured & g["entry_sleeve"].eq("EARLY")
    core = g["core20_captured"].astype(bool)
    core_gain = pd.to_numeric(g["core20_entry_gain"], errors="coerce")

    def frac(mask) -> float | None:
        return float(pd.Series(mask).fillna(False).mean()) if n else None

    return {
        "n": int(n),
        "capture_rate": frac(captured),
        "within30_all": frac(captured & gain.le(0.30)),
        "within50_all": frac(captured & gain.le(0.50)),
        "within100_all": frac(captured & gain.le(1.00)),
        "entry_gain_median": float(gain[captured].median()) if captured.any() else None,
        "early_sleeve_capture_rate_all": frac(early_hit),
        "early_sleeve_within30_all": frac(early_hit & gain.le(0.30)),
        "early_sleeve_within50_all": frac(early_hit & gain.le(0.50)),
        "early_sleeve_share_of_captures": float(early_hit[captured].mean()) if captured.any() else None,
        "saved_by_early_rate": frac(g["saved_by_early"].astype(bool)),
        "core20_capture_rate": frac(core),
        "core20_within30_all": frac(core & core_gain.le(0.30)),
        "core20_within50_all": frac(core & core_gain.le(0.50)),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--output", required=True)
    ap.add_argument("--analysis-start", default="2016-01-04")
    ap.add_argument("--analysis-end", default="2026-09-02")
    ap.add_argument("--max-tickers", type=int, default=6000)
    ap.add_argument("--batch-size", type=int, default=75)
    args = ap.parse_args()

    root = Path(args.root)
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    print("BUILD_INPUTS", flush=True)
    meta, matrices = ex.build_inputs_ext(root, args.analysis_start, args.analysis_end, args.max_tickers, args.batch_size)
    peer_ctx = loo.build_leave_one_out_scores(root, matrices)
    ctx = stage.build_signal_context(root, matrices)
    core_attack, core_selective, early_by_score = stage.precompute_candidates(meta, matrices, peer_ctx, ctx)
    idx = pd.DatetimeIndex(meta["analysis_idx"])

    print("TRACE_CORE_DDV20", flush=True)
    core_fn = cap.traced_core_simulator()
    _core_daily, core_diag = core_fn(meta, matrices, peer_ctx, LIQUIDITY_FLOOR, "VACANCY_TOP12")
    core_intervals = cap.to_frame(core_diag.pop("_audit_intervals"), ("entry_date", "exit_date"))
    core_diag.pop("_audit_entries", None)

    event_sets = cap.standardize_event_sets(matrices["close"], ctx["pool"], idx)

    old_floor = early.LIQUIDITY_FLOOR
    old_score, old_gate, old_days = early.EARLY_SCORE, early.EARLY_GATE, early.EARLY_MAX_DAYS
    all_rows: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    try:
        early.LIQUIDITY_FLOOR = LIQUIDITY_FLOOR
        early.EARLY_SCORE = EARLY_SCORE
        early.EARLY_GATE = EARLY_GATE
        early.EARLY_MAX_DAYS = EARLY_MAX_DAYS
        early_fn = cap.traced_early_simulator()

        for slots in SLOTS:
            print(f"TRACE_EARLY_SLOTS={slots}", flush=True)
            _daily, diag = early_fn(slots, meta, matrices, core_attack, core_selective, early_by_score)
            entries = cap.to_frame(diag.pop("_audit_entries"), ("signal_date", "entry_date"))
            intervals = cap.to_frame(diag.pop("_audit_intervals"), ("entry_date", "exit_date", "core_date"))
            promotions = cap.to_frame(diag.pop("_audit_promotions"), ("signal_date", "promotion_date", "entry_date"))
            diagnostics.append({
                "slots": int(slots),
                **{k: safe(v) for k, v in diag.items()},
                "trace_entries": int(len(entries)),
                "trace_promotions": int(len(promotions)),
            })
            entries.to_csv(out / f"entries_slots{slots}.csv", index=False)
            promotions.to_csv(out / f"promotions_slots{slots}.csv", index=False)

            for name, events in event_sets.items():
                print(f"EVAL slots={slots} {name} n={len(events)}", flush=True)
                for _, ev in events.iterrows():
                    all_rows.append(event_row(ev, intervals, core_intervals, slots))
    finally:
        early.LIQUIDITY_FLOOR = old_floor
        early.EARLY_SCORE, early.EARLY_GATE, early.EARLY_MAX_DAYS = old_score, old_gate, old_days

    details = pd.DataFrame(all_rows)
    details.to_csv(out / "slot_capture_event_details.csv", index=False)

    summary_rows: list[dict[str, Any]] = []
    for (slots, event_set), g in details.groupby(["slots", "event_set"], observed=True):
        summary_rows.append({"slots": int(slots), "event_set": str(event_set), "period": "ALL", **summarize(g)})
        for period, h in g.groupby("period", observed=True):
            summary_rows.append({"slots": int(slots), "event_set": str(event_set), "period": str(period), **summarize(h)})
    summary = pd.DataFrame(summary_rows)
    summary.to_csv(out / "slot_capture_summary.csv", index=False)
    pd.DataFrame(diagnostics).to_csv(out / "slot_capture_diagnostics.csv", index=False)

    focus = summary[
        summary["period"].eq("ALL")
        & summary["event_set"].isin(["ANNUAL_TOP5", "ANNUAL_400PLUS", "ROLL126_TOP10_GE50"])
    ].sort_values(["event_set", "slots"])

    report = {
        "status": "EARLY_SLOT_BIG_LEADER_CAPTURE",
        "research_only": True,
        "mechanics": {
            "liquidity_floor": LIQUIDITY_FLOOR,
            "core_mode": "VACANCY_TOP12",
            "early_score": EARLY_SCORE,
            "early_gate": EARLY_GATE,
            "early_max_days": EARLY_MAX_DAYS,
            "slots_tested": list(SLOTS),
            "signal_changed": False,
        },
        "focus": focus.to_dict(orient="records"),
        "diagnostics": diagnostics,
        "guardrail": "This audit changes only Early capacity (1/2/3 slots). Candidate score, gate, DDV floor, holding horizon, Core mechanics, labels, and promotion mechanics are fixed.",
    }
    (out / "slot_capture_report.json").write_text(json.dumps(safe(report), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(safe(report), ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
