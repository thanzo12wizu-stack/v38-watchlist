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
EARLY_SCORE = "RS21_HIGH_ACCEL"
RANK_CUTS = (1, 3, 5, 10, 20, 40)
GAIN_CUTS = (0.30, 0.50)


def safe(v: Any) -> Any:
    return cap.safe(v)


def gain(close: pd.DataFrame, d: pd.Timestamp, sym: str, anchor_price: float) -> float:
    try:
        p = float(close.at[d, sym])
    except Exception:
        return np.nan
    return p / anchor_price - 1.0 if np.isfinite(p) and p > 0 and anchor_price > 0 else np.nan


def inspect_event(
    ev: pd.Series,
    *,
    idx: pd.DatetimeIndex,
    close: pd.DataFrame,
    dvol: pd.DataFrame,
    meta: dict[str, Any],
    cand_map: dict[pd.Timestamp, list[tuple[str, float]]],
) -> dict[str, Any]:
    sym = str(ev["symbol"])
    start, end = pd.Timestamp(ev["anchor_date"]), pd.Timestamp(ev["end_date"])
    anchor_price = float(ev["anchor_price"])
    days = idx[(idx >= start) & (idx <= end)]

    first_date = None
    first_rank = np.nan
    first_score = np.nan
    first_gain = np.nan
    best_by_gain = {c: np.nan for c in GAIN_CUTS}
    first_date_by_gain = {c: pd.NaT for c in GAIN_CUTS}
    qualifying_days_by_gain = {c: 0 for c in GAIN_CUTS}

    for d0 in days:
        d = pd.Timestamp(d0)
        color, _bucket, _cap = delay.market_state(meta, d)
        if color == "Red":
            continue
        try:
            dv = float(dvol.at[d, sym])
        except Exception:
            dv = np.nan
        if not np.isfinite(dv) or dv < LIQUIDITY_FLOOR:
            continue
        xs = cand_map.get(d, [])
        rank = None
        score = None
        for j, (s, sc) in enumerate(xs, start=1):
            if str(s) == sym:
                rank = j
                score = float(sc)
                break
        if rank is None:
            continue
        g = gain(close, d, sym, anchor_price)
        if first_date is None:
            first_date, first_rank, first_score, first_gain = d, int(rank), float(score), float(g)
        for c in GAIN_CUTS:
            if np.isfinite(g) and g <= c:
                qualifying_days_by_gain[c] += 1
                if not np.isfinite(best_by_gain[c]) or rank < best_by_gain[c]:
                    best_by_gain[c] = int(rank)
                    first_date_by_gain[c] = d

    out = {
        "event_set": str(ev["event_set"]),
        "year": int(ev["year"]),
        "period": "DEV_2016_2020" if int(ev["year"]) <= 2020 else "CONFIRM_2021_2025",
        "symbol": sym,
        "anchor_date": start,
        "end_date": end,
        "future_return": float(ev["future_return"]),
        "first_qualified_date": first_date,
        "first_qualified_rank": first_rank,
        "first_qualified_score": first_score,
        "first_qualified_gain": first_gain,
    }
    for c in GAIN_CUTS:
        tag = int(round(c * 100))
        out[f"best_rank_by_{tag}"] = best_by_gain[c]
        out[f"best_rank_by_{tag}_date"] = first_date_by_gain[c]
        out[f"qualifying_days_by_{tag}"] = int(qualifying_days_by_gain[c])
    return out


def summarize(g: pd.DataFrame) -> dict[str, Any]:
    n = len(g)
    out: dict[str, Any] = {"n": int(n)}
    first_rank = pd.to_numeric(g["first_qualified_rank"], errors="coerce")
    out["qualified_top40_rate"] = float(first_rank.notna().mean()) if n else None
    out["first_rank_median"] = float(first_rank.median()) if first_rank.notna().any() else None
    for c in GAIN_CUTS:
        tag = int(round(c * 100))
        r = pd.to_numeric(g[f"best_rank_by_{tag}"], errors="coerce")
        out[f"candidate_by_{tag}_rate"] = float(r.notna().mean()) if n else None
        out[f"best_rank_by_{tag}_median"] = float(r.median()) if r.notna().any() else None
        for k in RANK_CUTS:
            out[f"top{k}_by_{tag}_all"] = float((r <= k).fillna(False).mean()) if n else None
    return out


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
    _attack, _selective, early_by_score = stage.precompute_candidates(meta, matrices, peer_ctx, ctx)
    cand_map = early_by_score[EARLY_SCORE]
    idx = pd.DatetimeIndex(meta["analysis_idx"])
    event_sets = cap.standardize_event_sets(matrices["close"], ctx["pool"], idx)

    rows: list[dict[str, Any]] = []
    for name, events in event_sets.items():
        print(f"EVAL {name} n={len(events)}", flush=True)
        for _, ev in events.iterrows():
            rows.append(inspect_event(
                ev,
                idx=idx,
                close=matrices["close"],
                dvol=matrices["dvol"],
                meta=meta,
                cand_map=cand_map,
            ))
    details = pd.DataFrame(rows)
    details.to_csv(out / "rank_depth_event_details.csv", index=False)

    summary_rows: list[dict[str, Any]] = []
    for event_set, g in details.groupby("event_set", observed=True):
        summary_rows.append({"event_set": str(event_set), "period": "ALL", **summarize(g)})
        for period, h in g.groupby("period", observed=True):
            summary_rows.append({"event_set": str(event_set), "period": str(period), **summarize(h)})
    summary = pd.DataFrame(summary_rows)
    summary.to_csv(out / "rank_depth_summary.csv", index=False)

    focus = summary[
        summary["period"].eq("ALL")
        & summary["event_set"].isin(["ANNUAL_TOP5", "ANNUAL_400PLUS", "ROLL126_TOP10_GE50"])
    ].sort_values("event_set")
    report = {
        "status": "EARLY_LEADER_RANK_DEPTH",
        "research_only": True,
        "mechanics": {
            "liquidity_floor": LIQUIDITY_FLOOR,
            "early_score": EARLY_SCORE,
            "gate": "NOT_RED",
            "candidate_depth": 40,
            "signal_changed": False,
        },
        "focus": focus.to_dict(orient="records"),
        "guardrail": "Diagnostic only. Measures where future leaders rank inside the existing Early top-40 before +30%/+50%; no threshold or production rule is changed.",
    }
    (out / "rank_depth_report.json").write_text(json.dumps(safe(report), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(safe(report), ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
