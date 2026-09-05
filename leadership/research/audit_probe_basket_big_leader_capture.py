from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import audit_early1_big_leader_capture as cap
import audit_major_leader_entry_delay as delay
import audit_ordinary_stock_exit_trail as ex
import audit_ordinary_stock_theme_leave_one_out as loo
import audit_staged_leader_liquidity_return as stage

LIQUIDITY_FLOOR = 20_000_000.0
RANKER = "RS21_HIGH63"
MAX_DAYS = 10
CAPACITIES = (1, 5, 10, 20)
GATES = ("CURRENT", "NOT_RED")


def safe(v: Any) -> Any:
    return cap.safe(v)


def px(frame: pd.DataFrame, d: pd.Timestamp, sym: str, fallback: float | None = None) -> float | None:
    return delay.px(frame, d, sym, fallback)


def gate_allowed(meta: dict[str, Any], d: pd.Timestamp, gate: str) -> bool:
    color, bucket, _ = delay.market_state(meta, d)
    if gate == "CURRENT":
        return bool(color in ("Blue", "Green") and bucket >= 1)
    if gate == "NOT_RED":
        return bool(color != "Red")
    raise ValueError(gate)


def core_entry_map(core_intervals: pd.DataFrame) -> dict[pd.Timestamp, set[str]]:
    out: dict[pd.Timestamp, set[str]] = {}
    if core_intervals.empty:
        return out
    for r in core_intervals.itertuples(index=False):
        d = pd.Timestamp(r.entry_date)
        out.setdefault(d, set()).add(str(r.symbol))
    return out


def core_held_map(core_intervals: pd.DataFrame, idx: pd.DatetimeIndex) -> dict[pd.Timestamp, set[str]]:
    adds: dict[pd.Timestamp, set[str]] = {}
    removes: dict[pd.Timestamp, set[str]] = {}
    if not core_intervals.empty:
        for r in core_intervals.itertuples(index=False):
            sym = str(r.symbol)
            en = pd.Timestamp(r.entry_date)
            exd = pd.Timestamp(r.exit_date)
            adds.setdefault(en, set()).add(sym)
            if not bool(getattr(r, "open_end", False)):
                removes.setdefault(exd, set()).add(sym)
    held: set[str] = set()
    out: dict[pd.Timestamp, set[str]] = {}
    for d0 in idx:
        d = pd.Timestamp(d0)
        held.difference_update(removes.get(d, set()))
        held.update(adds.get(d, set()))
        out[d] = set(held)
    return out


def simulate_probe(
    capacity: int,
    gate: str,
    meta: dict[str, Any],
    matrices: dict[str, pd.DataFrame],
    candidates: dict[pd.Timestamp, list[tuple[str, float]]],
    core_intervals: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    idx = pd.DatetimeIndex(meta["analysis_idx"])
    opens, closes, dvol = matrices["open"], matrices["close"], matrices["dvol"]
    pos: dict[str, dict[str, Any]] = {}
    entries: list[dict[str, Any]] = []
    intervals: list[dict[str, Any]] = []
    ipos = {pd.Timestamp(d): i for i, d in enumerate(idx)}
    core_entries = core_entry_map(core_intervals)
    core_held = core_held_map(core_intervals, idx)
    promoted = expired = stopped = red_exits = 0

    def close_probe(sym: str, d: pd.Timestamp, reason: str) -> None:
        nonlocal promoted, expired, stopped, red_exits
        p = pos.pop(sym)
        intervals.append({
            "symbol": sym,
            "entry_date": p["entry_date"],
            "entry_price": p["entry_price"],
            "exit_date": d,
            "entry_sleeve": "PROBE",
            "final_sleeve": "CORE" if reason == "PROMOTED_CORE" else "PROBE",
            "core_date": d if reason == "PROMOTED_CORE" else pd.NaT,
            "exit_reason": reason,
            "open_end": False,
        })
        if reason == "PROMOTED_CORE": promoted += 1
        elif reason == "EXPIRY": expired += 1
        elif reason == "STOP": stopped += 1
        elif reason == "RED": red_exits += 1

    for i, d0 in enumerate(idx):
        d = pd.Timestamp(d0)
        prev = None if i == 0 else pd.Timestamp(idx[i-1])
        if prev is None:
            continue

        color, _bucket, _ = delay.market_state(meta, prev)
        if color == "Red":
            for sym in list(pos):
                close_probe(sym, d, "RED")
        else:
            for sym in list(pos):
                if sym in core_entries.get(d, set()):
                    close_probe(sym, d, "PROMOTED_CORE")

            for sym in list(pos):
                p = pos[sym]
                pc = px(closes, prev, sym, p["entry_price"])
                if pc is None:
                    continue
                p["peak_close"] = max(float(p["peak_close"]), float(pc))
                age = ipos[prev] - ipos[p["signal_date"]]
                if age >= MAX_DAYS:
                    close_probe(sym, d, "EXPIRY")
                    continue
                stop = max(float(p["entry_price"]) * 0.92, float(p["peak_close"]) * 0.70)
                if pc <= stop:
                    close_probe(sym, d, "STOP")

        if not gate_allowed(meta, prev, gate):
            continue

        for rank, (sym, score) in enumerate(candidates.get(prev, []), start=1):
            if len(pos) >= capacity:
                break
            if sym in pos:
                continue
            if sym in core_held.get(d, set()):
                continue
            dv = px(dvol, prev, sym, None)
            if dv is None or dv < LIQUIDITY_FLOOR:
                continue
            opx = px(opens, d, sym, px(closes, prev, sym, None))
            if opx is None:
                continue
            pos[sym] = {
                "entry_date": d,
                "entry_price": float(opx),
                "signal_date": prev,
                "peak_close": float(opx),
                "entry_rank": rank,
                "entry_score": float(score),
            }
            entries.append({
                "capacity": capacity, "gate": gate, "symbol": sym,
                "signal_date": prev, "entry_date": d, "entry_price": float(opx),
                "entry_rank": rank, "entry_score": float(score), "entry_dvol": float(dv),
            })

    last = pd.Timestamp(idx[-1])
    for sym in list(pos):
        p = pos.pop(sym)
        intervals.append({
            "symbol": sym, "entry_date": p["entry_date"], "entry_price": p["entry_price"],
            "exit_date": last, "entry_sleeve": "PROBE", "final_sleeve": "PROBE",
            "core_date": pd.NaT, "exit_reason": "OPEN_END", "open_end": True,
        })

    ent = pd.DataFrame(entries)
    iv = pd.DataFrame(intervals)
    for x, cols in ((ent, ("signal_date", "entry_date")), (iv, ("entry_date", "exit_date", "core_date"))):
        for c in cols:
            if c in x.columns: x[c] = pd.to_datetime(x[c], errors="coerce")
    diag = {
        "capacity": capacity, "gate": gate, "entries": int(len(ent)),
        "promoted_core": int(promoted), "promotion_rate": float(promoted / len(ent)) if len(ent) else 0.0,
        "expired": int(expired), "stopped": int(stopped), "red_exits": int(red_exits),
    }
    return ent, iv, diag


def event_row(ev: pd.Series, probe: pd.DataFrame, core: pd.DataFrame, capacity: int, gate: str) -> dict[str, Any]:
    sym = str(ev["symbol"]); start = pd.Timestamp(ev["anchor_date"]); end = pd.Timestamp(ev["end_date"])
    ap = float(ev["anchor_price"])
    p = cap.find_capture(probe, sym, start, end, ap)
    c = cap.find_capture(core, sym, start, end, ap)
    choices = [z for z in (p, c) if z is not None]
    got = min(choices, key=lambda z: pd.Timestamp(z["date"])) if choices else None
    return {
        "capacity": capacity, "gate": gate, "event_set": str(ev["event_set"]),
        "year": int(ev["year"]), "symbol": sym, "anchor_date": start, "end_date": end,
        "future_return": float(ev["future_return"]),
        "captured": got is not None,
        "entry_date": got["date"] if got is not None else pd.NaT,
        "entry_gain": float(got["gain"]) if got is not None else np.nan,
        "entry_sleeve": str(got["sleeve"]) if got is not None else None,
        "probe_captured": p is not None,
        "probe_entry_gain": float(p["gain"]) if p is not None else np.nan,
        "core_captured": c is not None,
        "core_entry_gain": float(c["gain"]) if c is not None else np.nan,
    }


def summarize(g: pd.DataFrame) -> dict[str, Any]:
    n = len(g); captured = g.captured.astype(bool); gain = pd.to_numeric(g.entry_gain, errors="coerce")
    probe = g.probe_captured.astype(bool); pg = pd.to_numeric(g.probe_entry_gain, errors="coerce")
    def f(mask): return float(pd.Series(mask).fillna(False).mean()) if n else None
    return {
        "n": int(n), "capture_rate": f(captured),
        "within30_all": f(captured & gain.le(0.30)), "within50_all": f(captured & gain.le(0.50)),
        "within100_all": f(captured & gain.le(1.00)),
        "entry_gain_median": float(gain[captured].median()) if captured.any() else None,
        "probe_capture_rate": f(probe), "probe_within30_all": f(probe & pg.le(0.30)),
        "probe_within50_all": f(probe & pg.le(0.50)),
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
    root = Path(args.root); out = Path(args.output); out.mkdir(parents=True, exist_ok=True)

    print("BUILD INPUTS", flush=True)
    meta, matrices = ex.build_inputs_ext(root, args.analysis_start, args.analysis_end, args.max_tickers, args.batch_size)
    peer_ctx = loo.build_leave_one_out_scores(root, matrices)
    ctx = stage.build_signal_context(root, matrices)
    _core_attack, _core_selective, early_by_score = stage.precompute_candidates(meta, matrices, peer_ctx, ctx)
    idx = pd.DatetimeIndex(meta["analysis_idx"])

    print("TRACE CORE DDV20", flush=True)
    core_fn = cap.traced_core_simulator()
    _daily, core_diag = core_fn(meta, matrices, peer_ctx, LIQUIDITY_FLOOR, "VACANCY_TOP12")
    core_iv = cap.to_frame(core_diag.pop("_audit_intervals"), ("entry_date", "exit_date"))
    core_diag.pop("_audit_entries", None)
    events = cap.standardize_event_sets(matrices["close"], ctx["pool"], idx)

    all_rows: list[dict[str, Any]] = []
    diags = []
    for gate in GATES:
        for capacity in CAPACITIES:
            print(f"SIM PROBE gate={gate} cap={capacity}", flush=True)
            ent, iv, diag = simulate_probe(capacity, gate, meta, matrices, early_by_score[RANKER], core_iv)
            ent.to_csv(out / f"entries_{gate}_cap{capacity}.csv", index=False)
            diags.append(diag)
            for _name, evs in events.items():
                for _, ev in evs.iterrows():
                    all_rows.append(event_row(ev, iv, core_iv, capacity, gate))

    details = pd.DataFrame(all_rows)
    details.to_csv(out / "probe_capture_event_details.csv", index=False)
    rows = []
    for (gate, capn, event_set), g in details.groupby(["gate", "capacity", "event_set"], observed=True):
        rows.append({"gate": gate, "capacity": int(capn), "event_set": event_set, "period": "ALL", **summarize(g)})
        years = pd.to_numeric(g.year, errors="coerce")
        for period, mask in {
            "DEV_2016_2020": years.between(2016, 2020),
            "CONF_2021_2023": years.between(2021, 2023),
            "HOLDOUT_2024_2026": years >= 2024,
        }.items():
            rows.append({"gate": gate, "capacity": int(capn), "event_set": event_set, "period": period, **summarize(g.loc[mask])})
    summary = pd.DataFrame(rows)
    summary.to_csv(out / "probe_capture_summary.csv", index=False)
    pd.DataFrame(diags).to_csv(out / "probe_diagnostics.csv", index=False)

    focus = summary[(summary.period == "ALL") & summary.event_set.isin(["ANNUAL_TOP5", "ANNUAL_400PLUS", "ROLL126_TOP10_GE50"])].sort_values(["event_set", "gate", "capacity"])
    report = {
        "status": "PROBE_BASKET_BIG_LEADER_CAPTURE",
        "research_only": True,
        "mechanics": {
            "liquidity_floor": LIQUIDITY_FLOOR, "ranker": RANKER, "active_window": 5,
            "max_days": MAX_DAYS, "capacities": list(CAPACITIES), "gates": list(GATES),
            "portfolio_budget_note": "shadow capture audit; intended later portfolio budget is one Early slot total split equally across probes",
            "preemption": False,
            "core_overlap": "existing DDV20 Core holdings are excluded from probe candidates; same-day Core entry promotes/frees a probe seat",
        },
        "core_diag": core_diag, "focus": focus.to_dict(orient="records"), "diagnostics": diags,
    }
    (out / "report.json").write_text(json.dumps(safe(report), ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== PROBE_BASKET_RESULT ===", flush=True)
    print(json.dumps(safe(report), ensure_ascii=False, indent=2), flush=True)

if __name__ == "__main__":
    main()
