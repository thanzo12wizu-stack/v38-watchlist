from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import audit_major_leader_entry_delay as delay
import audit_ordinary_stock_market_mode_robustness as base
import audit_ordinary_stock_theme_leave_one_out as loo
import audit_ordinary_stock_exit_trail as ex


def safe(v: Any) -> Any:
    return base.safe(v)


def first_in_set(by_date: dict[pd.Timestamp, set[str]], sym: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.Timestamp | None:
    for d in sorted(k for k in by_date if start <= k <= end):
        if sym in by_date[d]:
            return pd.Timestamp(d)
    return None


def rolling126_top10(close: pd.DataFrame, pool: pd.DataFrame, idx: pd.DatetimeIndex) -> pd.DataFrame:
    """Quarter-overlapping 126-session future-leader labels, then 63-session same-symbol de-dup."""
    pos = {pd.Timestamp(d): i for i, d in enumerate(close.index)}
    analysis_pos = [pos[pd.Timestamp(d)] for d in idx if pd.Timestamp(d) in pos]
    if not analysis_pos:
        return pd.DataFrame()
    first, last = min(analysis_pos), max(analysis_pos)
    rows: list[dict[str, Any]] = []
    for p in range(first, last - 126 + 1, 21):
        d0 = pd.Timestamp(close.index[p])
        d1 = pd.Timestamp(close.index[p + 126])
        if d0 not in idx or d1 > idx[-1]:
            continue
        tradable = pool.loc[d0].fillna(False)
        ret = (close.loc[d1] / close.loc[d0] - 1.0).where(tradable).dropna().sort_values(ascending=False).head(10)
        for rank, (sym, r) in enumerate(ret.items(), start=1):
            rows.append({
                "event_type": "ROLL126_TOP10", "anchor_date": d0, "final_date": d1,
                "symbol": str(sym), "final_return": float(r), "rank": rank,
                "anchor_pos": p,
            })
    raw = pd.DataFrame(rows)
    if raw.empty:
        return raw
    keep: list[int] = []
    for _, g in raw.sort_values(["symbol", "anchor_pos"]).groupby("symbol", observed=True):
        last_kept = -10**9
        for j, r in g.iterrows():
            p = int(r["anchor_pos"])
            if p - last_kept >= 63:
                keep.append(j)
                last_kept = p
    return raw.loc[keep].sort_values(["anchor_date", "rank"]).reset_index(drop=True)


def annual_top5(close: pd.DataFrame, pool: pd.DataFrame, idx: pd.DatetimeIndex) -> pd.DataFrame:
    e = delay.annual_leader_events(close, pool, idx, include_partial_2026=False)
    x = e[e["top5"]].copy()
    return x[["anchor_date", "final_date", "symbol", "final_return"]].assign(event_type="ANNUAL_TOP5")


def make_event_detail(
    events: pd.DataFrame,
    close: pd.DataFrame,
    pool: pd.DataFrame,
    rs: dict[int, pd.DataFrame],
    eligible: pd.DataFrame,
    attack_rank: dict[pd.Timestamp, dict[str, int]],
    policy_candidates: dict[pd.Timestamp, list[str]],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    policy_sets = {pd.Timestamp(d): set(map(str, xs)) for d, xs in policy_candidates.items()}
    for ev in events.itertuples(index=False):
        sym = str(ev.symbol)
        start = pd.Timestamp(ev.anchor_date)
        end = pd.Timestamp(ev.final_date)
        ap = delay.px(close, start, sym, None)
        if ap is None:
            continue
        radar_mask = pool[sym] & ((rs[21][sym] >= 85.0) | (rs[42][sym] >= 85.0) | (rs[63][sym] >= 85.0))
        radar = delay.first_true_date(radar_mask, start, end)
        if radar is None:
            rows.append({
                "event_type": ev.event_type, "anchor_date": start, "final_date": end, "symbol": sym,
                "final_return": float(ev.final_return), "radar_date": pd.NaT, "radar_gain": np.nan,
                "eligibility_date": pd.NaT, "attack12_date": pd.NaT, "policy_candidate_date": pd.NaT,
            })
            continue
        rp = delay.px(close, radar, sym, None)
        eg = delay.first_true_date(eligible[sym], radar, end)
        ar = delay.first_rank_date(attack_rank, sym, radar, end, base.N_PORT)
        pc = first_in_set(policy_sets, sym, radar, end)
        rows.append({
            "event_type": ev.event_type, "anchor_date": start, "final_date": end, "symbol": sym,
            "final_return": float(ev.final_return), "radar_date": radar,
            "radar_gain": float(rp / ap - 1.0) if rp is not None else np.nan,
            "eligibility_date": eg, "attack12_date": ar, "policy_candidate_date": pc,
        })
    return pd.DataFrame(rows)


def greedy_max_count(intervals: list[tuple[pd.Timestamp, pd.Timestamp, int]], k: int) -> set[int]:
    """Maximum-cardinality subset of intervals with overlap <= k.

    Sweep starts in chronological order. Whenever active overlap exceeds k,
    discard the active interval with the latest end. This is optimal for
    unit-weight interval capacity selection.
    """
    if k <= 0:
        return set()
    selected: set[int] = set()
    active: list[tuple[pd.Timestamp, int]] = []
    for start, end, eid in sorted(intervals, key=lambda x: (x[0], x[1], x[2])):
        active = [(e, j) for e, j in active if e >= start and j in selected]
        active.append((end, eid))
        selected.add(eid)
        if len(active) > k:
            drop_end, drop_id = max(active, key=lambda x: (x[0], x[1]))
            selected.discard(drop_id)
            active = [(e, j) for e, j in active if j != drop_id]
    return selected


def capacity_summary(detail: pd.DataFrame, end_col: str, k: int, cutoff: float | None) -> dict[str, Any]:
    n = len(detail)
    if n == 0:
        return {"n": 0}
    x = detail.copy()
    valid = x["radar_date"].notna()
    if cutoff is not None:
        valid &= pd.to_numeric(x["radar_gain"], errors="coerce").le(cutoff)
    candidate_ids = list(x.index[valid])
    intervals: list[tuple[pd.Timestamp, pd.Timestamp, int]] = []
    for j in candidate_ids:
        r = x.loc[j]
        s = pd.Timestamp(r["radar_date"])
        # If current Core never accepts the leader in the label horizon, a perfect
        # staging sleeve would have to keep occupying the Early slot to horizon end.
        e = pd.Timestamp(r[end_col]) if pd.notna(r[end_col]) else pd.Timestamp(r["final_date"])
        if e < s:
            e = s
        intervals.append((s, e, int(j)))
    selected = greedy_max_count(intervals, k)

    # Peak simultaneous demand among perfect-knowledge true leaders before capacity pruning.
    points: list[tuple[pd.Timestamp, int]] = []
    for s, e, _ in intervals:
        points.append((s, +1))
        points.append((e + pd.Timedelta(nanoseconds=1), -1))
    active = peak = 0
    for _, delta in sorted(points, key=lambda z: (z[0], z[1])):
        active += delta
        peak = max(peak, active)

    return {
        "n_events": int(n),
        "radar_qualifying": int(len(candidate_ids)),
        "radar_qualifying_rate": float(len(candidate_ids) / n),
        "oracle_schedulable": int(len(selected)),
        "oracle_capture_rate_all_events": float(len(selected) / n),
        "oracle_capture_rate_given_qualifying_radar": float(len(selected) / len(candidate_ids)) if candidate_ids else None,
        "peak_true_leader_slot_demand": int(peak),
        "capacity_loss_events": int(len(candidate_ids) - len(selected)),
    }


def summarize_label(detail: pd.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {"n": int(len(detail))}
    for endpoint in ("eligibility_date", "attack12_date", "policy_candidate_date"):
        out[endpoint] = {}
        for cutoff_name, cutoff in (("ANY_RADAR", None), ("RADAR_BY_30PCT", 0.30), ("RADAR_BY_50PCT", 0.50)):
            out[endpoint][cutoff_name] = {
                f"K{k}": capacity_summary(detail, endpoint, k, cutoff) for k in range(1, 6)
            }
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
    out = root / args.output
    out.mkdir(parents=True, exist_ok=True)

    print("BUILD INPUTS", flush=True)
    meta, matrices = ex.build_inputs_ext(root, args.analysis_start, args.analysis_end, args.max_tickers, args.batch_size)
    idx = pd.DatetimeIndex(meta["analysis_idx"])
    close = matrices["close"]
    pool = delay.current_base_pool(root, matrices)
    rs = delay.rs_matrices(close, pool)

    print("BUILD CURRENT CORE RANK MAPS", flush=True)
    peer_ctx = loo.build_leave_one_out_scores(root, matrices)
    attack_rank, _, policy_candidates = delay.build_daily_rank_maps(meta, matrices, peer_ctx)

    labels = {
        "ANNUAL_TOP5_2016_2025": annual_top5(close, pool, idx),
        "ROLL126_TOP10_DEDUP": rolling126_top10(close, pool, idx),
    }
    result: dict[str, Any] = {
        "status": "EARLY_SLOT_CAPACITY_ORACLE",
        "scope": "research only; perfect future knowledge; production/main/UI untouched",
        "question": "If Early staging receives only true future leaders at first Any(RS21,RS42,RS63)>=85, are 3 slots physically sufficient until current Core accepts them?",
        "interpretation": "This is an optimistic upper bound, not a tradable strategy. If K3 is high, selection/ranking is the bottleneck. If K3 is materially below the qualifying-radar rate, capacity itself is a bottleneck.",
        "endpoints": {
            "eligibility_date": "first current Full Eligibility after radar; shortest optimistic bridge",
            "attack12_date": "first current ATTACK Top12 ranking after radar, ignoring market mode",
            "policy_candidate_date": "first date name is in current Core candidate list under actual market mode; closest current-Core bridge endpoint",
        },
        "labels": {},
    }
    for name, events in labels.items():
        print(f"DETAIL {name} n={len(events)}", flush=True)
        detail = make_event_detail(events, close, pool, rs, matrices["new_eligible"], attack_rank, policy_candidates)
        detail.to_csv(out / f"detail_{name.lower()}.csv", index=False)
        result["labels"][name] = summarize_label(detail)

    (out / "summary_early_slot_capacity_oracle.json").write_text(json.dumps(safe(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== EARLY_SLOT_CAPACITY_ORACLE_JSON ===", flush=True)
    print(json.dumps(safe(result), ensure_ascii=False, indent=2), flush=True)
    print("=== END_EARLY_SLOT_CAPACITY_ORACLE_JSON ===", flush=True)


if __name__ == "__main__":
    main()
