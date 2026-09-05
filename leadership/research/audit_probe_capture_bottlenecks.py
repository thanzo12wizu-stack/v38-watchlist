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
import audit_probe_basket_big_leader_capture as probe
import audit_staged_leader_liquidity_return as stage

LIQ = 20_000_000.0
RANKER = "RS21_HIGH63"
CAPACITY = 20
GATE = "NOT_RED"
THRESHOLDS = (0.30, 0.50)


def safe(v: Any) -> Any:
    return cap.safe(v)


def first_true(idx: pd.DatetimeIndex, mask: pd.Series) -> pd.Timestamp | None:
    z = idx[np.asarray(mask.fillna(False), dtype=bool)]
    return pd.Timestamp(z[0]) if len(z) else None


def gain_at(close: pd.DataFrame, d: pd.Timestamp | None, sym: str, anchor_price: float) -> float | None:
    if d is None:
        return None
    p = delay.px(close, d, sym, None)
    return float(p / anchor_price - 1.0) if p is not None and anchor_price > 0 else None


def classify_event(
    ev: pd.Series,
    threshold: float,
    idx: pd.DatetimeIndex,
    matrices: dict[str, pd.DataFrame],
    ctx: dict[str, Any],
    candidates: dict[pd.Timestamp, list[tuple[str, float]]],
    entries: pd.DataFrame,
) -> dict[str, Any]:
    close, dvol, opens = matrices["close"], matrices["dvol"], matrices["open"]
    sym = str(ev["symbol"]); a = pd.Timestamp(ev["anchor_date"]); e = pd.Timestamp(ev["end_date"]); ap = float(ev["anchor_price"])
    dates = idx[(idx >= a) & (idx <= e)]
    if not len(dates):
        return {"bottleneck": "NO_DATES"}

    gains = pd.Series(index=dates, dtype=float)
    for d in dates:
        p = delay.px(close, pd.Timestamp(d), sym, None)
        gains.loc[d] = float(p/ap - 1.0) if p is not None else np.nan
    within = gains.le(threshold)

    rs = ctx["rs"]; pool = ctx["pool"]
    radar = (pool[sym] & ((rs[21][sym] >= 85.0) | (rs[42][sym] >= 85.0) | (rs[63][sym] >= 85.0))).reindex(dates).fillna(False)
    active = ctx["active5"][sym].reindex(dates).fillna(False)
    dv_ok = pd.to_numeric(dvol[sym].reindex(dates), errors="coerce").ge(LIQ)

    rank_map: dict[pd.Timestamp, int] = {}
    for d in dates:
        arr = candidates.get(pd.Timestamp(d), [])
        rank_map[pd.Timestamp(d)] = next((i for i,(s,_v) in enumerate(arr, start=1) if s == sym), 10**9)
    rank = pd.Series(rank_map).reindex(dates)
    top20 = rank.le(CAPACITY)

    gate = pd.Series([probe.gate_allowed({}, pd.Timestamp(d), GATE) if False else True for d in dates], index=dates)
    # Call real gate using meta later; placeholder overwritten by caller through event field is not acceptable.
    # This series is replaced below by precomputed _gate_not_red if present.
    if "_gate_not_red" in ev.index:
        gate = pd.Series(ev["_gate_not_red"], index=dates)

    # Actual probe entry, and whether next-open threshold was crossed by a qualifying signal.
    zent = entries[(entries.symbol == sym) & (entries.entry_date >= a) & (entries.entry_date <= e)].sort_values("entry_date")
    actual_within = False; actual_date = None; actual_gain = None
    for r in zent.itertuples(index=False):
        op = float(r.entry_price)
        g = op/ap - 1.0
        if g <= threshold:
            actual_within = True; actual_date = pd.Timestamp(r.entry_date); actual_gain = float(g); break

    m_radar = within & radar
    m_active = within & active
    m_dv = m_active & dv_ok
    m_rank = m_dv & top20
    # gate will be supplied separately by caller after building real series.

    return {
        "radar_by_threshold": bool(m_radar.any()),
        "active5_by_threshold": bool(m_active.any()),
        "ddv20_active_by_threshold": bool(m_dv.any()),
        "top20_ddv20_active_by_threshold": bool(m_rank.any()),
        "actual_probe_by_threshold": bool(actual_within),
        "actual_probe_date": actual_date,
        "actual_probe_gain": actual_gain,
        "first_radar_date": first_true(dates, radar),
        "first_active_date": first_true(dates, active),
        "best_rank_by_threshold": int(rank[within & active & dv_ok].min()) if (within & active & dv_ok).any() else None,
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
    _ca, _cs, early = stage.precompute_candidates(meta, matrices, peer_ctx, ctx)
    idx = pd.DatetimeIndex(meta["analysis_idx"])

    print("TRACE CORE + PROBE20 NOT_RED", flush=True)
    core_fn = cap.traced_core_simulator()
    _daily, core_diag = core_fn(meta, matrices, peer_ctx, LIQ, "VACANCY_TOP12")
    core_iv = cap.to_frame(core_diag.pop("_audit_intervals"), ("entry_date", "exit_date"))
    entries, _probe_iv, pdiag = probe.simulate_probe(CAPACITY, GATE, meta, matrices, early[RANKER], core_iv)

    events = cap.standardize_event_sets(matrices["close"], ctx["pool"], idx)
    rows: list[dict[str, Any]] = []
    for event_set, evs in events.items():
        if event_set not in ("ANNUAL_TOP5", "ANNUAL_400PLUS", "ROLL126_TOP10_GE50"):
            continue
        for _, ev in evs.iterrows():
            sym = str(ev["symbol"]); a = pd.Timestamp(ev["anchor_date"]); e = pd.Timestamp(ev["end_date"]); apx = float(ev["anchor_price"])
            dates = idx[(idx >= a) & (idx <= e)]
            if not len(dates):
                continue
            # Build contemporaneous gate series once.
            gate_series = pd.Series([probe.gate_allowed(meta, pd.Timestamp(d), GATE) for d in dates], index=dates, dtype=bool)
            for th in THRESHOLDS:
                r = classify_event(ev, th, idx, matrices, ctx, early[RANKER], entries)
                close = matrices["close"]; dvol = matrices["dvol"]
                gains = pd.Series({pd.Timestamp(d): ((delay.px(close,pd.Timestamp(d),sym,None)/apx)-1.0) if delay.px(close,pd.Timestamp(d),sym,None) is not None else np.nan for d in dates})
                within = gains.le(th)
                active = ctx["active5"][sym].reindex(dates).fillna(False)
                dv_ok = pd.to_numeric(dvol[sym].reindex(dates), errors="coerce").ge(LIQ)
                rank = pd.Series({pd.Timestamp(d): next((i for i,(s,_v) in enumerate(early[RANKER].get(pd.Timestamp(d),[]),start=1) if s==sym),10**9) for d in dates})
                top20 = rank.le(CAPACITY)
                eligible = within & active & dv_ok & top20
                gate_eligible = eligible & gate_series
                r["notred_top20_ddv20_active_by_threshold"] = bool(gate_eligible.any())
                r["best_rank_notred_by_threshold"] = int(rank[within & active & dv_ok & gate_series].min()) if (within & active & dv_ok & gate_series).any() else None

                if r["actual_probe_by_threshold"]:
                    bottleneck = "FILLED_EARLY"
                elif not r["radar_by_threshold"]:
                    bottleneck = "RADAR_LATE"
                elif not r["active5_by_threshold"]:
                    bottleneck = "ACTIVE5_MISS"
                elif not r["ddv20_active_by_threshold"]:
                    bottleneck = "DDV20_LATE"
                elif not r["top20_ddv20_active_by_threshold"]:
                    bottleneck = "RANK_GT20"
                elif not r["notred_top20_ddv20_active_by_threshold"]:
                    bottleneck = "RED_GATE"
                else:
                    # All signal-day conditions existed but the cap20 portfolio did not fill it in time.
                    bottleneck = "SEAT_OCCUPANCY_OR_NEXT_OPEN_GAP"
                rows.append({
                    "event_set": event_set, "year": int(ev["year"]), "symbol": sym,
                    "anchor_date": a, "future_return": float(ev["future_return"]), "threshold": th,
                    "bottleneck": bottleneck, **r,
                })

    details = pd.DataFrame(rows)
    details.to_csv(out / "bottleneck_details.csv", index=False)
    summary = (details.groupby(["event_set","threshold","bottleneck"], observed=True).size().rename("n").reset_index())
    totals = details.groupby(["event_set","threshold"], observed=True).size().rename("total").reset_index()
    summary = summary.merge(totals,on=["event_set","threshold"])
    summary["share"] = summary["n"] / summary["total"]
    summary.to_csv(out / "bottleneck_summary.csv", index=False)

    sub = []
    for (es, th, period), g in details.assign(period=np.select([
        details.year.between(2016,2020), details.year.between(2021,2023), details.year>=2024
    ],["DEV_2016_2020","CONF_2021_2023","HOLDOUT_2024_2026"],default="OTHER")).groupby(["event_set","threshold","period"], observed=True):
        counts = g.bottleneck.value_counts()
        for k,n in counts.items():
            sub.append({"event_set":es,"threshold":th,"period":period,"bottleneck":k,"n":int(n),"total":int(len(g)),"share":float(n/len(g))})
    pd.DataFrame(sub).to_csv(out / "bottleneck_subperiods.csv", index=False)
    report = {"status":"PROBE_CAPTURE_BOTTLENECKS","probe_diag":pdiag,"summary":summary.to_dict(orient="records")}
    (out / "report.json").write_text(json.dumps(safe(report), ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== PROBE_CAPTURE_BOTTLENECKS ===", flush=True)
    print(json.dumps(safe(report), ensure_ascii=False, indent=2), flush=True)

if __name__ == "__main__":
    main()
