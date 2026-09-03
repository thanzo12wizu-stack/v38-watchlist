from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import audit_ordinary_stock_market_mode_robustness as base
import audit_ordinary_stock_theme_leave_one_out as loo
import audit_ordinary_stock_exit_trail as ex

# Research only. Do not import from production UI or modify live rules.
SELECTIVE_SLOTS = 4
RS_PERIODS = (21, 42, 63, 126, 189, 252)
COMPLETE_YEARS = tuple(range(2016, 2026))
PRIMARY_GAIN_CUTS = (0.30, 0.50, 1.00)


def safe(v: Any) -> Any:
    return base.safe(v)


def px(frame: pd.DataFrame, date: pd.Timestamp, sym: str, fallback: float | None = None) -> float | None:
    try:
        x = float(frame.at[date, sym])
        if np.isfinite(x) and x > 0:
            return x
    except Exception:
        pass
    return fallback


def current_base_pool(root: Path, matrices: dict[str, pd.DataFrame]) -> pd.DataFrame:
    close = matrices["close"]
    pool = (close >= 5.0) & (matrices["dvol"] >= base.DVOL_FLOOR)
    excluded = base.read_structural_bio_exclusions(root, list(close.columns))
    if excluded:
        cols = [s for s in excluded if s in pool.columns]
        pool.loc[:, cols] = False
    return pool


def rs_matrices(close: pd.DataFrame, pool: pd.DataFrame) -> dict[int, pd.DataFrame]:
    out: dict[int, pd.DataFrame] = {}
    for p in RS_PERIODS:
        ret = close / close.shift(p) - 1.0
        out[p] = ret.where(pool & ret.notna()).rank(axis=1, pct=True, method="average") * 100.0
    return out


def annual_leader_events(
    close: pd.DataFrame,
    pool: pd.DataFrame,
    analysis_idx: pd.DatetimeIndex,
    include_partial_2026: bool = True,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    years = list(COMPLETE_YEARS) + ([2026] if include_partial_2026 else [])
    for year in years:
        dates = analysis_idx[analysis_idx.year == year]
        if len(dates) < (80 if year == 2026 else 180):
            continue
        first_d, last_d = pd.Timestamp(dates[0]), pd.Timestamp(dates[-1])
        first = close.loc[first_d].copy()
        last = close.loc[last_d].copy()
        # Require the name to be in the tradable liquidity/price pool near the start.
        first_window = dates[: min(20, len(dates))]
        tradable_near_start = pool.loc[first_window].fillna(False).any(axis=0)
        annual = (last / first - 1.0).where(tradable_near_start & first.notna() & last.notna())
        ranked = annual.dropna().sort_values(ascending=False)
        top5 = set(ranked.head(5).index)
        for sym, r in ranked.items():
            if r < 2.0 and sym not in top5:
                continue
            rows.append({
                "year": int(year),
                "complete_year": bool(year in COMPLETE_YEARS),
                "symbol": str(sym),
                "anchor_date": first_d,
                "anchor_price": float(first[sym]),
                "final_date": last_d,
                "final_price": float(last[sym]),
                "final_return": float(r),
                "top5": bool(sym in top5),
                "cohort_200_400": bool(2.0 <= r < 4.0),
                "cohort_400plus": bool(r >= 4.0),
            })
    return pd.DataFrame(rows).sort_values(["year", "final_return"], ascending=[True, False]).reset_index(drop=True)


def market_state(meta: dict[str, Any], d: pd.Timestamp) -> tuple[str, int, int]:
    nq = meta["nq"]
    breadth = meta["breadth"]
    color = str(nq.at[d, "nq_color"]) if d in nq.index and pd.notna(nq.at[d, "nq_color"]) else ""
    b = float(breadth.loc[d]) if d in breadth.index and pd.notna(breadth.loc[d]) else np.nan
    bucket = base.breadth_bucket(b)
    bull = color in ("Blue", "Green")
    cap = base.N_PORT if bull and bucket == 2 else SELECTIVE_SLOTS if bull and bucket == 1 else 0
    return color, bucket, cap


def build_daily_rank_maps(
    meta: dict[str, Any], matrices: dict[str, pd.DataFrame], peer_ctx: dict[str, Any]
) -> tuple[dict[pd.Timestamp, dict[str, int]], dict[pd.Timestamp, dict[str, int]], dict[pd.Timestamp, list[str]]]:
    attack_rank: dict[pd.Timestamp, dict[str, int]] = {}
    rs189_rank: dict[pd.Timestamp, dict[str, int]] = {}
    policy_candidates: dict[pd.Timestamp, list[str]] = {}
    idx = meta["analysis_idx"]
    for i, d0 in enumerate(idx):
        d = pd.Timestamp(d0)
        eligible = matrices["new_eligible"].loc[d]
        rs = matrices["rs189"].loc[d].where(eligible).dropna().sort_values(ascending=False)
        rs189_rank[d] = {str(s): int(j + 1) for j, s in enumerate(rs.index)}
        attack = loo.peer_ranked_candidates(d, matrices, peer_ctx, max(24, base.N_PORT))
        attack_rank[d] = {str(s): int(j + 1) for j, (s, _) in enumerate(attack)}
        _, bucket, cap = market_state(meta, d)
        if cap <= 0:
            policy_candidates[d] = []
        elif bucket == 1:
            policy_candidates[d] = [str(s) for s in rs.head(base.N_PORT).index]
        else:
            policy_candidates[d] = [str(s) for s, _ in attack[:base.N_PORT]]
        if (i + 1) % 250 == 0:
            print(f"RANK_MAP {i + 1}/{len(idx)}", flush=True)
    return attack_rank, rs189_rank, policy_candidates


def simulate_current_with_trace(
    meta: dict[str, Any], matrices: dict[str, pd.DataFrame], peer_ctx: dict[str, Any]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Current adopted Core mechanics: daily refresh/refill, Attack Stock70+Theme30,
    Selective RS189, no scheduled rank prune, hard -8%, +24% 25% partial, peak-close -30%, Red full exit.
    Trace is recorded at signal close, before next-open fills.
    """
    idx = meta["analysis_idx"]
    opens, closes = matrices["open"], matrices["close"]
    cash = 1.0
    pos: dict[str, dict[str, Any]] = {}
    entries: list[dict[str, Any]] = []
    trace: list[dict[str, Any]] = []
    red_run = 0

    def close_position(sym: str, date: pd.Timestamp, price: float, reason: str) -> None:
        nonlocal cash
        p = pos.pop(sym)
        cash += float(p["shares"]) * price

    for i, d0 in enumerate(idx):
        d = pd.Timestamp(d0)
        prev = None if i == 0 else pd.Timestamp(idx[i - 1])
        if prev is not None:
            color, bucket, cap = market_state(meta, prev)
            red_run = red_run + 1 if color == "Red" else 0
            red_force = color == "Red" and red_run >= 1

            if red_force:
                for sym in list(pos):
                    opx = px(opens, d, sym, px(closes, prev, sym, pos[sym]["entry_price"]))
                    if opx is not None:
                        close_position(sym, d, opx, "RED")
            else:
                for sym in list(pos):
                    p = pos[sym]
                    pc = px(closes, prev, sym, p["entry_price"])
                    if pc is None:
                        continue
                    if (not p["partial_done"]) and pc >= p["entry_price"] * 1.24:
                        opx = px(opens, d, sym, pc)
                        if opx is not None:
                            sold = p["shares"] * 0.25
                            cash += sold * opx
                            p["shares"] -= sold
                            p["partial_done"] = True
                    stop = max(p["entry_price"] * 0.92, p["peak_close"] * 0.70)
                    if pc <= stop:
                        opx = px(opens, d, sym, pc)
                        if opx is not None:
                            close_position(sym, d, opx, "STOP")

            before = len(pos)
            candidates = ex.ranked_candidates(prev, matrices, peer_ctx, bucket, base.N_PORT) if cap > 0 else []
            cand_syms = [str(s) for s, _ in candidates]
            slot_count = max(0, cap - before)
            trace.append({
                "signal_date": prev,
                "trade_date": d,
                "color": color,
                "bucket": bucket,
                "capacity": cap,
                "positions_before_fill": before,
                "slots_before_fill": slot_count,
                "candidate_symbols": "|".join(cand_syms),
            })

            if (not red_force) and cap > 0 and before < cap and candidates:
                nav_open = cash
                for sym, p in pos.items():
                    opx = px(opens, d, sym, px(closes, prev, sym, p["entry_price"]))
                    if opx is not None:
                        nav_open += p["shares"] * opx
                slot_cash = nav_open / base.N_PORT
                for rank, (sym0, c) in enumerate(candidates, start=1):
                    sym = str(sym0)
                    if len(pos) >= cap or cash <= 0:
                        break
                    if sym in pos:
                        continue
                    opx = px(opens, d, sym, px(closes, prev, sym, None))
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
                        "partial_done": False,
                    }
                    entries.append({
                        "symbol": sym,
                        "signal_date": prev,
                        "entry_date": d,
                        "entry_price": opx,
                        "entry_bucket": bucket,
                        "candidate_rank": rank,
                        "stock_rs189": c.get("stock_rs189"),
                        "peer_theme_score": c.get("peer_theme_score"),
                    })

        for sym, p in pos.items():
            cp = px(closes, d, sym, px(opens, d, sym, p["entry_price"]))
            if cp is not None:
                p["peak_close"] = max(p["peak_close"], cp)

    return pd.DataFrame(entries), pd.DataFrame(trace)


def session_distance(pos_map: dict[pd.Timestamp, int], a: Any, b: Any) -> float | None:
    if pd.isna(a) or pd.isna(b) or a is None or b is None:
        return None
    aa, bb = pd.Timestamp(a), pd.Timestamp(b)
    if aa not in pos_map or bb not in pos_map:
        return None
    return float(pos_map[bb] - pos_map[aa])


def gain_at(close: pd.DataFrame, sym: str, anchor_price: float, d: Any) -> float | None:
    if d is None or pd.isna(d):
        return None
    p = px(close, pd.Timestamp(d), sym, None)
    if p is None or anchor_price <= 0:
        return None
    return float(p / anchor_price - 1.0)


def first_true_date(mask: pd.Series, start: pd.Timestamp, end: pd.Timestamp) -> pd.Timestamp | None:
    z = mask.loc[(mask.index >= start) & (mask.index <= end)].fillna(False)
    hits = z.index[z]
    return pd.Timestamp(hits[0]) if len(hits) else None


def first_rank_date(rank_map: dict[pd.Timestamp, dict[str, int]], sym: str, start: pd.Timestamp, end: pd.Timestamp, n: int) -> pd.Timestamp | None:
    for d in sorted(k for k in rank_map if start <= k <= end):
        r = rank_map[d].get(sym)
        if r is not None and r <= n:
            return d
    return None


def decompose_events(
    events: pd.DataFrame,
    meta: dict[str, Any],
    matrices: dict[str, pd.DataFrame],
    pool: pd.DataFrame,
    rs: dict[int, pd.DataFrame],
    attack_rank: dict[pd.Timestamp, dict[str, int]],
    rs189_rank: dict[pd.Timestamp, dict[str, int]],
    entries: pd.DataFrame,
    trace: pd.DataFrame,
) -> pd.DataFrame:
    close = matrices["close"]
    idx = pd.DatetimeIndex(meta["analysis_idx"])
    pos_map = {pd.Timestamp(d): i for i, d in enumerate(idx)}
    out: list[dict[str, Any]] = []
    entry_groups = {str(k): v.sort_values("entry_date") for k, v in entries.groupby("symbol")} if len(entries) else {}
    trace2 = trace.copy()
    if len(trace2):
        trace2["candidate_set"] = trace2["candidate_symbols"].fillna("").map(lambda s: set(x for x in str(s).split("|") if x))

    structural = pool & (matrices["sma50"] > matrices["sma200"]) & (close > matrices["sma200"])
    alt_rank: dict[int, pd.DataFrame] = {}
    for p in RS_PERIODS:
        alt_rank[p] = rs[p].where(structural).rank(axis=1, ascending=False, method="min")

    for ev in events.itertuples(index=False):
        sym = str(ev.symbol)
        start = pd.Timestamp(ev.anchor_date)
        end = pd.Timestamp(ev.final_date)
        anchor = float(ev.anchor_price)

        # Transparent surviving-rules radar proxy: first short/mid RS85 observation in the tradable pool.
        radar_mask = pool[sym] & ((rs[21][sym] >= 85.0) | (rs[42][sym] >= 85.0) | (rs[63][sym] >= 85.0))
        radar = first_true_date(radar_mask, start, end)
        elig = first_true_date(matrices["new_eligible"][sym], start, end)
        attack12 = first_rank_date(attack_rank, sym, start, end, base.N_PORT)
        rs12 = first_rank_date(rs189_rank, sym, start, end, base.N_PORT)

        slot = None
        policy_ranked = None
        if len(trace2):
            z = trace2[(trace2["signal_date"] >= start) & (trace2["signal_date"] <= end)]
            for r in z.itertuples(index=False):
                if sym in r.candidate_set:
                    if policy_ranked is None:
                        policy_ranked = pd.Timestamp(r.signal_date)
                    if int(r.slots_before_fill) > 0 and int(r.capacity) > 0:
                        slot = pd.Timestamp(r.signal_date)
                        break

        actual_signal = actual_entry = None
        actual_price = None
        g = entry_groups.get(sym)
        if g is not None:
            z = g[(g["entry_date"] >= start) & (g["entry_date"] <= end)]
            if len(z):
                rr = z.iloc[0]
                actual_signal = pd.Timestamp(rr["signal_date"])
                actual_entry = pd.Timestamp(rr["entry_date"])
                actual_price = float(rr["entry_price"])

        rec: dict[str, Any] = {
            "year": int(ev.year), "complete_year": bool(ev.complete_year), "symbol": sym,
            "anchor_date": start, "anchor_price": anchor, "final_date": end,
            "final_return": float(ev.final_return), "top5": bool(ev.top5),
            "cohort_200_400": bool(ev.cohort_200_400), "cohort_400plus": bool(ev.cohort_400plus),
            "radar_proxy_date": radar,
            "eligibility_date": elig,
            "attack_rank12_date": attack12,
            "rs189_rank12_date": rs12,
            "policy_ranked_date": policy_ranked,
            "slot_available_date": slot,
            "actual_signal_date": actual_signal,
            "actual_entry_date": actual_entry,
            "actual_entry_price": actual_price,
        }
        stages = {
            "radar_proxy": radar, "eligibility": elig, "attack_rank12": attack12,
            "policy_ranked": policy_ranked, "slot_available": slot, "actual_signal": actual_signal,
        }
        for name, d in stages.items():
            rec[f"{name}_delay_sessions"] = session_distance(pos_map, start, d)
            rec[f"{name}_gain"] = gain_at(close, sym, anchor, d)
        if actual_entry is not None and actual_price is not None:
            rec["actual_entry_delay_sessions"] = session_distance(pos_map, start, actual_entry)
            rec["actual_entry_gain"] = float(actual_price / anchor - 1.0)
            rec["remaining_upside_from_entry"] = float(float(ev.final_price) / actual_price - 1.0)
            rec["progress_of_final_gain"] = float((actual_price / anchor - 1.0) / float(ev.final_return)) if float(ev.final_return) > 0 else None
        else:
            rec["actual_entry_delay_sessions"] = None
            rec["actual_entry_gain"] = None
            rec["remaining_upside_from_entry"] = None
            rec["progress_of_final_gain"] = None

        if elig is None:
            rec["first_blocker"] = "ELIGIBILITY"
        elif policy_ranked is None:
            rec["first_blocker"] = "RANKING_OR_MARKET_MODE"
        elif slot is None:
            rec["first_blocker"] = "SLOT_TIMING"
        elif actual_entry is None:
            rec["first_blocker"] = "CANDIDATE_COMPETITION_OR_EXECUTION"
        else:
            rec["first_blocker"] = "CAPTURED"

        for p in RS_PERIODS:
            d = first_true_date((alt_rank[p][sym] <= base.N_PORT), start, end)
            rec[f"alt_rs{p}_rank12_date"] = d
            rec[f"alt_rs{p}_rank12_delay_sessions"] = session_distance(pos_map, start, d)
            rec[f"alt_rs{p}_rank12_gain"] = gain_at(close, sym, anchor, d)
        out.append(rec)
    return pd.DataFrame(out)


def summarize_group(df: pd.DataFrame) -> dict[str, Any]:
    n = len(df)
    if n == 0:
        return {"n": 0}
    out: dict[str, Any] = {
        "n": int(n),
        "captured": int(df["actual_entry_date"].notna().sum()),
        "capture_rate": float(df["actual_entry_date"].notna().mean()),
        "blockers": {str(k): int(v) for k, v in df["first_blocker"].value_counts().items()},
    }
    for stage in ("radar_proxy", "eligibility", "attack_rank12", "policy_ranked", "slot_available", "actual_entry"):
        dcol = f"{stage}_delay_sessions"
        gcol = f"{stage}_gain"
        x = pd.to_numeric(df[dcol], errors="coerce").dropna() if dcol in df else pd.Series(dtype=float)
        g = pd.to_numeric(df[gcol], errors="coerce").dropna() if gcol in df else pd.Series(dtype=float)
        out[stage] = {
            "reached": int(df[dcol].notna().sum()) if dcol in df else 0,
            "reach_rate": float(df[dcol].notna().mean()) if dcol in df else None,
            "delay_median_sessions": float(x.median()) if len(x) else None,
            "delay_p75_sessions": float(x.quantile(0.75)) if len(x) else None,
            "gain_median": float(g.median()) if len(g) else None,
            "gain_p75": float(g.quantile(0.75)) if len(g) else None,
            "within_30pct": float((g <= 0.30).mean()) if len(g) else None,
            "within_50pct": float((g <= 0.50).mean()) if len(g) else None,
            "before_100pct": float((g < 1.00).mean()) if len(g) else None,
        }
    ae = pd.to_numeric(df["actual_entry_gain"], errors="coerce").dropna()
    rem = pd.to_numeric(df["remaining_upside_from_entry"], errors="coerce").dropna()
    prog = pd.to_numeric(df["progress_of_final_gain"], errors="coerce").dropna()
    out["actual_entry_extra"] = {
        "entry_gain_median": float(ae.median()) if len(ae) else None,
        "remaining_upside_median": float(rem.median()) if len(rem) else None,
        "progress_median": float(prog.median()) if len(prog) else None,
    }
    return out


def alternative_rank_summary(df: pd.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for p in RS_PERIODS:
        g = pd.to_numeric(df[f"alt_rs{p}_rank12_gain"], errors="coerce").dropna()
        d = pd.to_numeric(df[f"alt_rs{p}_rank12_delay_sessions"], errors="coerce").dropna()
        out[f"RS{p}"] = {
            "reached": int(len(g)),
            "reach_rate": float(len(g) / len(df)) if len(df) else None,
            "gain_median": float(g.median()) if len(g) else None,
            "delay_median_sessions": float(d.median()) if len(d) else None,
            "within_30pct_all_events": float((pd.to_numeric(df[f"alt_rs{p}_rank12_gain"], errors="coerce") <= 0.30).fillna(False).mean()) if len(df) else None,
            "within_50pct_all_events": float((pd.to_numeric(df[f"alt_rs{p}_rank12_gain"], errors="coerce") <= 0.50).fillna(False).mean()) if len(df) else None,
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
    outdir = root / args.output
    outdir.mkdir(parents=True, exist_ok=True)

    print("BUILD INPUTS", flush=True)
    meta, matrices = ex.build_inputs_ext(root, args.analysis_start, args.analysis_end, args.max_tickers, args.batch_size)
    print("BUILD PEER CONTEXT", flush=True)
    peer_ctx = loo.build_leave_one_out_scores(root, matrices)
    pool = current_base_pool(root, matrices)
    print("BUILD RS MATRICES", flush=True)
    rsm = rs_matrices(matrices["close"], pool)
    print("BUILD LEADER COHORTS", flush=True)
    events = annual_leader_events(matrices["close"], pool, pd.DatetimeIndex(meta["analysis_idx"]), True)
    print("BUILD DAILY RANK MAPS", flush=True)
    attack_rank, rs189_rank, _ = build_daily_rank_maps(meta, matrices, peer_ctx)
    print("SIM CURRENT TRACE", flush=True)
    entries, trace = simulate_current_with_trace(meta, matrices, peer_ctx)
    print("DECOMPOSE", flush=True)
    detail = decompose_events(events, meta, matrices, pool, rsm, attack_rank, rs189_rank, entries, trace)

    complete = detail[detail["complete_year"]].copy()
    groups = {
        "TOP1_5_COMPLETE_2016_2025": complete[complete["top5"]],
        "ALL_200_400_COMPLETE_2016_2025": complete[complete["cohort_200_400"]],
        "ALL_400PLUS_COMPLETE_2016_2025": complete[complete["cohort_400plus"]],
        "TOP1_5_2026_YTD": detail[(detail["year"] == 2026) & detail["top5"]],
    }
    result: dict[str, Any] = {
        "status": "MAJOR_LEADER_ENTRY_DELAY_AUDIT",
        "scope": "research only; production/main/UI untouched",
        "leader_label": {
            "primary": "calendar-year Top1-5 by adjusted close return, complete years 2016-2025",
            "large_return_sensitivity": "all tradable-near-year-start stocks finishing +200% to <+400%, and >=+400%",
            "2026": "reported separately as YTD because the year is incomplete",
            "anchor": "first analysis session close of the calendar year",
        },
        "current_core_rule_reconstructed": "daily refresh/refill; Attack Stock70+leave-one-out Theme30, Selective RS189; 12/4 slots; no scheduled rank prune; hard -8%; +24% first-hit next-open 25% partial; peak-close -30% trail; Red next-open full exit",
        "radar_note": "Exact deleted Leader Radar Precision run could not be recovered. radar_proxy is therefore transparently defined as first tradable day with any of cross-sectional RS21/RS42/RS63 >=85. It is not represented as the vanished exact radar.",
        "coverage": {
            "selected": int(meta["selected"]), "downloaded": int(meta["downloaded"]),
            "analysis_sessions": int(len(meta["analysis_idx"])), "leader_rows": int(len(detail)),
            "entries": int(len(entries)), "trace_rows": int(len(trace)),
        },
        "groups": {},
    }
    for name, g in groups.items():
        result["groups"][name] = {
            "delay": summarize_group(g),
            "alternative_rs_rank12": alternative_rank_summary(g),
        }

    detail.to_csv(outdir / "major_leader_entry_delay_detail.csv", index=False)
    entries.to_csv(outdir / "current_core_entries.csv", index=False)
    trace.drop(columns=["candidate_symbols"], errors="ignore").to_csv(outdir / "current_core_daily_trace.csv", index=False)
    (outdir / "summary_major_leader_entry_delay.json").write_text(json.dumps(safe(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== MAJOR_LEADER_ENTRY_DELAY_JSON ===", flush=True)
    print(json.dumps(safe(result), ensure_ascii=False, indent=2), flush=True)
    print("=== END_MAJOR_LEADER_ENTRY_DELAY_JSON ===", flush=True)


if __name__ == "__main__":
    main()
