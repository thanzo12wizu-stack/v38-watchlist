from __future__ import annotations

import argparse
import inspect
import json
import textwrap
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import audit_early_leader_entry_candidates as old_early
import audit_gross100_ddv_refill_mode as ddv
import audit_gross100_early_slot_overlay as early
import audit_major_leader_entry_delay as delay
import audit_ordinary_stock_exit_trail as ex
import audit_ordinary_stock_theme_leave_one_out as loo
import audit_staged_leader_liquidity_return as stage

LIQUIDITY_FLOOR = 20_000_000.0
EARLY_SCORE = "RS21_HIGH_ACCEL"
EARLY_GATE = "NOT_RED"
EARLY_MAX_DAYS = 10
EARLY_SLOTS = 1
COMPLETE_END = pd.Timestamp("2025-12-31")


def safe(v: Any) -> Any:
    return delay.safe(v)


def replace_once(src: str, needle: str, repl: str, label: str) -> str:
    n = src.count(needle)
    if n != 1:
        raise RuntimeError(f"{label}: expected 1 occurrence, got {n}")
    return src.replace(needle, repl, 1)


def traced_core_simulator():
    """Source-identical DDV vacancy simulator with entry/holding trace only."""
    src = inspect.getsource(ddv.simulate_ordinary_mode)
    src = replace_once(
        src,
        "    entry_count = 0\n",
        "    entry_count = 0\n"
        "    _audit_entries = []\n"
        "    _audit_intervals = []\n",
        "core trace init",
    )
    src = replace_once(
        src,
        '        p = pos.pop(sym)\n        cash += p["shares"] * price\n',
        '        p = pos.pop(sym)\n'
        '        cash += p["shares"] * price\n'
        '        _audit_intervals.append({\n'
        '            "symbol": sym, "entry_date": p["entry_date"], "entry_price": p["entry_price"],\n'
        '            "exit_date": d, "entry_sleeve": "CORE", "final_sleeve": "CORE", "open_end": False,\n'
        '        })\n',
        "core close trace",
    )
    src = replace_once(
        src,
        "                    entry_count += 1\n",
        '                    _audit_entries.append({\n'
        '                        "symbol": str(sym), "signal_date": prev, "entry_date": d, "entry_price": float(opx),\n'
        '                        "entry_sleeve": "CORE", "raw_rank": int(raw_rank), "entry_dvol": float(dv),\n'
        '                    })\n'
        "                    entry_count += 1\n",
        "core entry trace",
    )
    src = replace_once(
        src,
        '    out = pd.DataFrame(rows).set_index("date")\n',
        '    _last_d = pd.Timestamp(idx[-1])\n'
        '    for _sym, _p in pos.items():\n'
        '        _audit_intervals.append({\n'
        '            "symbol": str(_sym), "entry_date": _p["entry_date"], "entry_price": _p["entry_price"],\n'
        '            "exit_date": _last_d, "entry_sleeve": "CORE", "final_sleeve": "CORE", "open_end": True,\n'
        '        })\n'
        '    out = pd.DataFrame(rows).set_index("date")\n',
        "core open-end trace",
    )
    src = replace_once(
        src,
        "    return out.reset_index(), diag\n",
        '    diag["_audit_entries"] = _audit_entries\n'
        '    diag["_audit_intervals"] = _audit_intervals\n'
        "    return out.reset_index(), diag\n",
        "core return trace",
    )
    ns = dict(ddv.__dict__)
    exec(textwrap.dedent(src), ns)
    return ns["simulate_ordinary_mode"]


def traced_early_simulator():
    """Source-identical Early1 overlay with entries/promotions/holding trace only."""
    src = inspect.getsource(early.simulate_early_overlay)
    src = replace_once(
        src,
        "    early_entries = 0\n",
        "    early_entries = 0\n"
        "    _audit_entries = []\n"
        "    _audit_promotions = []\n"
        "    _audit_intervals = []\n",
        "early trace init",
    )
    src = replace_once(
        src,
        '        p = pos.pop(sym)\n        cash += p["shares"] * price\n',
        '        p = pos.pop(sym)\n'
        '        cash += p["shares"] * price\n'
        '        _audit_intervals.append({\n'
        '            "symbol": str(sym), "entry_date": p["entry_date"], "entry_price": p["entry_price"],\n'
        '            "exit_date": d, "entry_sleeve": p["entry_sleeve"], "final_sleeve": p["sleeve"],\n'
        '            "core_date": p.get("core_date"), "exit_reason": reason, "open_end": False,\n'
        '        })\n',
        "early close trace",
    )
    src = replace_once(
        src,
        "                            promoted_core += 1\n",
        '                            _audit_promotions.append({\n'
        '                                "symbol": str(sym), "signal_date": prev, "promotion_date": d,\n'
        '                                "entry_date": pos[sym]["entry_date"], "entry_price": pos[sym]["entry_price"],\n'
        '                            })\n'
        "                            promoted_core += 1\n",
        "promotion trace",
    )
    src = replace_once(
        src,
        "                        core_entries += 1\n",
        '                        _audit_entries.append({\n'
        '                            "symbol": str(sym), "signal_date": prev, "entry_date": d, "entry_price": float(opx),\n'
        '                            "entry_sleeve": "CORE", "raw_rank": int(raw_rank),\n'
        '                            "entry_dvol": float(pos[sym]["entry_dvol"]) if pos[sym]["entry_dvol"] is not None else np.nan,\n'
        '                            "entry_score": np.nan,\n'
        '                        })\n'
        "                        core_entries += 1\n",
        "early-overlay core entry trace",
    )
    src = replace_once(
        src,
        "                            early_entries += 1\n",
        '                            _audit_entries.append({\n'
        '                                "symbol": str(sym), "signal_date": prev, "entry_date": d, "entry_price": float(opx),\n'
        '                                "entry_sleeve": "EARLY", "raw_rank": np.nan,\n'
        '                                "early_rank": int(rank), "entry_dvol": float(dv), "entry_score": float(score),\n'
        '                            })\n'
        "                            early_entries += 1\n",
        "early entry trace",
    )
    src = replace_once(
        src,
        '    out = pd.DataFrame(rows).set_index("date")\n',
        '    _last_d = pd.Timestamp(idx[-1])\n'
        '    for _sym, _p in pos.items():\n'
        '        _audit_intervals.append({\n'
        '            "symbol": str(_sym), "entry_date": _p["entry_date"], "entry_price": _p["entry_price"],\n'
        '            "exit_date": _last_d, "entry_sleeve": _p["entry_sleeve"], "final_sleeve": _p["sleeve"],\n'
        '            "core_date": _p.get("core_date"), "exit_reason": "OPEN_END", "open_end": True,\n'
        '        })\n'
        '    out = pd.DataFrame(rows).set_index("date")\n',
        "early open-end trace",
    )
    src = replace_once(
        src,
        "    return out.reset_index(), diag\n",
        '    diag["_audit_entries"] = _audit_entries\n'
        '    diag["_audit_promotions"] = _audit_promotions\n'
        '    diag["_audit_intervals"] = _audit_intervals\n'
        "    return out.reset_index(), diag\n",
        "early return trace",
    )
    ns = dict(early.__dict__)
    exec(textwrap.dedent(src), ns)
    return ns["simulate_early_overlay"]


def to_frame(rows: list[dict[str, Any]], date_cols: tuple[str, ...]) -> pd.DataFrame:
    x = pd.DataFrame(rows)
    for c in date_cols:
        if c in x.columns:
            x[c] = pd.to_datetime(x[c], errors="coerce")
    return x


def standardize_event_sets(
    close: pd.DataFrame,
    pool: pd.DataFrame,
    idx: pd.DatetimeIndex,
) -> dict[str, pd.DataFrame]:
    annual = delay.annual_leader_events(close, pool, idx, include_partial_2026=False).copy()
    annual["end_date"] = pd.to_datetime(annual["final_date"])
    annual["future_return"] = pd.to_numeric(annual["final_return"], errors="coerce")
    annual["anchor_price"] = pd.to_numeric(annual["anchor_price"], errors="coerce")
    sets: dict[str, pd.DataFrame] = {
        "ANNUAL_TOP5": annual[annual["top5"]].copy(),
        "ANNUAL_200_400": annual[annual["cohort_200_400"]].copy(),
        "ANNUAL_400PLUS": annual[annual["cohort_400plus"]].copy(),
    }

    top10 = old_early.annual_topk_events(close, pool, idx, 10).copy()
    if not top10.empty:
        top10["anchor_price"] = [
            float(close.at[pd.Timestamp(d), str(s)])
            for d, s in zip(top10["anchor_date"], top10["symbol"])
        ]
    sets["ANNUAL_TOP10"] = top10

    roll = old_early.rolling126_events(close, pool, idx, None).copy()
    roll_big = old_early.rolling126_events(close, pool, idx, 0.50).copy()
    for x in (roll, roll_big):
        if not x.empty:
            x["anchor_price"] = [
                float(close.at[pd.Timestamp(d), str(s)])
                for d, s in zip(x["anchor_date"], x["symbol"])
            ]
    sets["ROLL126_TOP10"] = roll
    sets["ROLL126_TOP10_GE50"] = roll_big

    cols = ["symbol", "anchor_date", "end_date", "anchor_price", "future_return"]
    out: dict[str, pd.DataFrame] = {}
    for name, x in sets.items():
        if x.empty:
            out[name] = pd.DataFrame(columns=cols)
            continue
        z = x.copy()
        z["symbol"] = z["symbol"].astype(str)
        z["anchor_date"] = pd.to_datetime(z["anchor_date"])
        z["end_date"] = pd.to_datetime(z["end_date"])
        z["future_return"] = pd.to_numeric(z["future_return"], errors="coerce")
        if "year" not in z:
            z["year"] = z["anchor_date"].dt.year
        z["event_set"] = name
        out[name] = z
    return out


def first_signal_date(
    dates: pd.DatetimeIndex,
    start: pd.Timestamp,
    end: pd.Timestamp,
    predicate,
) -> pd.Timestamp | None:
    for d in dates:
        dd = pd.Timestamp(d)
        if dd < start:
            continue
        if dd > end:
            break
        if predicate(dd):
            return dd
    return None


def gain_close(close: pd.DataFrame, sym: str, anchor_price: float, d: pd.Timestamp | None) -> float:
    if d is None or not np.isfinite(anchor_price) or anchor_price <= 0:
        return np.nan
    try:
        p = float(close.at[pd.Timestamp(d), sym])
    except Exception:
        return np.nan
    return p / anchor_price - 1.0 if np.isfinite(p) and p > 0 else np.nan


def find_capture(
    intervals: pd.DataFrame,
    sym: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    anchor_price: float,
) -> dict[str, Any] | None:
    if intervals.empty:
        return None
    z = intervals[
        intervals["symbol"].eq(sym)
        & (intervals["entry_date"] <= end)
        & (intervals["exit_date"] >= start)
    ].sort_values(["entry_date", "exit_date"])
    if z.empty:
        return None
    r = z.iloc[0]
    entry_date = pd.Timestamp(r["entry_date"])
    preheld = bool(entry_date <= start)
    gain = 0.0 if preheld else float(r["entry_price"]) / anchor_price - 1.0
    return {
        "date": start if preheld else entry_date,
        "actual_entry_date": entry_date,
        "gain": gain,
        "sleeve": str(r.get("entry_sleeve", "CORE")),
        "final_sleeve": str(r.get("final_sleeve", r.get("entry_sleeve", "CORE"))),
        "preheld": preheld,
    }


def session_delta(idx_pos: dict[pd.Timestamp, int], a: pd.Timestamp | None, b: pd.Timestamp | None) -> float:
    if a is None or b is None:
        return np.nan
    aa, bb = pd.Timestamp(a), pd.Timestamp(b)
    if aa not in idx_pos or bb not in idx_pos:
        return np.nan
    return float(idx_pos[bb] - idx_pos[aa])


def evaluate_event(
    ev: pd.Series,
    *,
    close: pd.DataFrame,
    dvol: pd.DataFrame,
    idx: pd.DatetimeIndex,
    idx_pos: dict[pd.Timestamp, int],
    ctx: dict[str, Any],
    early_by_score: dict[str, dict[pd.Timestamp, list[tuple[str, float]]]],
    meta: dict[str, Any],
    core_intervals: pd.DataFrame,
    early_intervals: pd.DataFrame,
    early_daily: pd.DataFrame,
    promotions: pd.DataFrame,
) -> dict[str, Any]:
    sym = str(ev["symbol"])
    start, end = pd.Timestamp(ev["anchor_date"]), pd.Timestamp(ev["end_date"])
    anchor_price = float(ev["anchor_price"])
    days = idx[(idx >= start) & (idx <= end)]

    radar_mask = (
        ctx["pool"][sym]
        & (
            (ctx["rs"][21][sym] >= 85.0)
            | (ctx["rs"][42][sym] >= 85.0)
            | (ctx["rs"][63][sym] >= 85.0)
        )
    ).fillna(False)
    radar_date = first_signal_date(days, start, end, lambda d: bool(radar_mask.at[d]))

    cand_map = early_by_score[EARLY_SCORE]
    cand_dates: list[pd.Timestamp] = []
    qual_dates: list[pd.Timestamp] = []
    red_good_dates: list[pd.Timestamp] = []
    for d in days:
        dd = pd.Timestamp(d)
        syms = {s for s, _v in cand_map.get(dd, [])}
        if sym not in syms:
            continue
        cand_dates.append(dd)
        color, _bucket, _cap = delay.market_state(meta, dd)
        gate_ok = color != "Red"
        if gate_ok:
            red_good_dates.append(dd)
        try:
            dv = float(dvol.at[dd, sym])
        except Exception:
            dv = np.nan
        if gate_ok and np.isfinite(dv) and dv >= LIQUIDITY_FLOOR:
            qual_dates.append(dd)

    candidate_date = cand_dates[0] if cand_dates else None
    qualified_date = qual_dates[0] if qual_dates else None

    core_cap = find_capture(core_intervals, sym, start, end, anchor_price)
    early_cap = find_capture(early_intervals, sym, start, end, anchor_price)

    promo_date = None
    if not promotions.empty:
        pz = promotions[
            promotions["symbol"].eq(sym)
            & (promotions["promotion_date"] >= start)
            & (promotions["promotion_date"] <= end)
        ].sort_values("promotion_date")
        if len(pz):
            promo_date = pd.Timestamp(pz.iloc[0]["promotion_date"])

    saved_strict = bool(
        early_cap is not None
        and early_cap["sleeve"] == "EARLY"
        and (
            core_cap is None
            or pd.Timestamp(early_cap["date"]) < pd.Timestamp(core_cap["date"])
        )
    )

    miss_reason = None
    if early_cap is None:
        if radar_date is None:
            miss_reason = "RADAR_NEVER"
        elif candidate_date is None:
            miss_reason = "EARLY_TOP40_NEVER"
        elif qualified_date is None:
            if not red_good_dates:
                miss_reason = "RED_GATE_BLOCK"
            else:
                miss_reason = "DDV20_BLOCK"
        else:
            qd = pd.Timestamp(qualified_date)
            next_candidates = idx[idx > qd]
            td = pd.Timestamp(next_candidates[0]) if len(next_candidates) else None
            row = None
            if td is not None and td in early_daily.index:
                row = early_daily.loc[td]
            if row is not None and float(row.get("early_positions", 0)) >= 1:
                miss_reason = "EARLY_SLOT_OCCUPIED"
            elif row is not None and float(row.get("positions", 0)) >= 12:
                miss_reason = "PORTFOLIO_CAPACITY"
            else:
                miss_reason = "NO_FILL_OTHER"

    core_gain = core_cap["gain"] if core_cap else np.nan
    early_gain = early_cap["gain"] if early_cap else np.nan
    remaining = (
        float(ev["future_return"])
        if early_cap is not None and early_cap["preheld"]
        else (
            (1.0 + float(ev["future_return"])) / (1.0 + early_gain) - 1.0
            if early_cap is not None and np.isfinite(early_gain) and (1.0 + early_gain) > 0
            else np.nan
        )
    )

    return {
        "event_set": str(ev["event_set"]),
        "year": int(ev["year"]),
        "period": "DEV_2016_2020" if int(ev["year"]) <= 2020 else "CONFIRM_2021_2025",
        "symbol": sym,
        "anchor_date": start,
        "end_date": end,
        "future_return": float(ev["future_return"]),
        "radar_date": radar_date,
        "radar_gain": gain_close(close, sym, anchor_price, radar_date),
        "early_candidate_date": candidate_date,
        "early_candidate_gain": gain_close(close, sym, anchor_price, candidate_date),
        "early_qualified_date": qualified_date,
        "early_qualified_gain": gain_close(close, sym, anchor_price, qualified_date),
        "core20_captured": core_cap is not None,
        "core20_entry_date": core_cap["date"] if core_cap else pd.NaT,
        "core20_entry_gain": core_gain,
        "early1_captured": early_cap is not None,
        "early1_entry_date": early_cap["date"] if early_cap else pd.NaT,
        "early1_actual_entry_date": early_cap["actual_entry_date"] if early_cap else pd.NaT,
        "early1_entry_gain": early_gain,
        "early1_entry_sleeve": early_cap["sleeve"] if early_cap else None,
        "early1_final_sleeve": early_cap["final_sleeve"] if early_cap else None,
        "early1_preheld": early_cap["preheld"] if early_cap else False,
        "promotion_date": promo_date,
        "promotion_gain": gain_close(close, sym, anchor_price, promo_date),
        "saved_by_early": saved_strict,
        "early_vs_core_sessions": (
            session_delta(idx_pos, pd.Timestamp(early_cap["date"]), pd.Timestamp(core_cap["date"]))
            if early_cap and core_cap
            else np.nan
        ),
        "remaining_return_after_early1": remaining,
        "miss_reason": miss_reason,
    }


def summarize_group(g: pd.DataFrame) -> dict[str, Any]:
    n = len(g)
    def frac(mask) -> float | None:
        return float(pd.Series(mask).fillna(False).mean()) if n else None

    radar_gain = pd.to_numeric(g["radar_gain"], errors="coerce")
    qual_gain = pd.to_numeric(g["early_qualified_gain"], errors="coerce")
    core_gain = pd.to_numeric(g["core20_entry_gain"], errors="coerce")
    early_gain = pd.to_numeric(g["early1_entry_gain"], errors="coerce")
    early_c = g["early1_captured"].astype(bool)
    core_c = g["core20_captured"].astype(bool)

    return {
        "n": int(n),
        "radar_seen": int(radar_gain.notna().sum()),
        "radar_rate": frac(radar_gain.notna()),
        "radar_within30_all": frac(radar_gain.notna() & (radar_gain <= 0.30)),
        "radar_within50_all": frac(radar_gain.notna() & (radar_gain <= 0.50)),
        "early_qualified_rate": frac(qual_gain.notna()),
        "early_qualified_within30_all": frac(qual_gain.notna() & (qual_gain <= 0.30)),
        "early_qualified_within50_all": frac(qual_gain.notna() & (qual_gain <= 0.50)),
        "core20_capture_rate": frac(core_c),
        "core20_within30_all": frac(core_c & (core_gain <= 0.30)),
        "core20_within50_all": frac(core_c & (core_gain <= 0.50)),
        "core20_within100_all": frac(core_c & (core_gain <= 1.00)),
        "core20_entry_gain_median": float(core_gain[core_c].median()) if core_c.any() else None,
        "early1_capture_rate": frac(early_c),
        "early1_within30_all": frac(early_c & (early_gain <= 0.30)),
        "early1_within50_all": frac(early_c & (early_gain <= 0.50)),
        "early1_within100_all": frac(early_c & (early_gain <= 1.00)),
        "early1_entry_gain_median": float(early_gain[early_c].median()) if early_c.any() else None,
        "early_sleeve_share_of_captures": (
            float(g.loc[early_c, "early1_entry_sleeve"].eq("EARLY").mean()) if early_c.any() else None
        ),
        "saved_by_early_rate": frac(g["saved_by_early"].astype(bool)),
        "promoted_big_leader_rate": frac(g["promotion_date"].notna()),
        "misses": int((~early_c).sum()),
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
    meta, matrices = ex.build_inputs_ext(
        root, args.analysis_start, args.analysis_end, args.max_tickers, args.batch_size
    )
    peer_ctx = loo.build_leave_one_out_scores(root, matrices)
    ctx = stage.build_signal_context(root, matrices)
    core_attack, core_selective, early_by_score = stage.precompute_candidates(
        meta, matrices, peer_ctx, ctx
    )

    old_floor = early.LIQUIDITY_FLOOR
    old_score, old_gate, old_days = early.EARLY_SCORE, early.EARLY_GATE, early.EARLY_MAX_DAYS
    try:
        early.LIQUIDITY_FLOOR = LIQUIDITY_FLOOR
        early.EARLY_SCORE = EARLY_SCORE
        early.EARLY_GATE = EARLY_GATE
        early.EARLY_MAX_DAYS = EARLY_MAX_DAYS

        print("TRACE_CORE_DDV20", flush=True)
        core_fn = traced_core_simulator()
        core_daily, core_diag = core_fn(
            meta, matrices, peer_ctx, LIQUIDITY_FLOOR, "VACANCY_TOP12"
        )

        print("TRACE_EARLY1", flush=True)
        early_fn = traced_early_simulator()
        early_daily_df, early_diag = early_fn(
            EARLY_SLOTS, meta, matrices, core_attack, core_selective, early_by_score
        )
    finally:
        early.LIQUIDITY_FLOOR = old_floor
        early.EARLY_SCORE, early.EARLY_GATE, early.EARLY_MAX_DAYS = old_score, old_gate, old_days

    core_entries = to_frame(core_diag.pop("_audit_entries"), ("signal_date", "entry_date"))
    core_intervals = to_frame(core_diag.pop("_audit_intervals"), ("entry_date", "exit_date"))
    early_entries = to_frame(early_diag.pop("_audit_entries"), ("signal_date", "entry_date"))
    early_intervals = to_frame(
        early_diag.pop("_audit_intervals"), ("entry_date", "exit_date", "core_date")
    )
    promotions = to_frame(
        early_diag.pop("_audit_promotions"), ("signal_date", "promotion_date", "entry_date")
    )

    idx = pd.DatetimeIndex(meta["analysis_idx"])
    idx_pos = {pd.Timestamp(d): i for i, d in enumerate(idx)}
    early_daily = early_daily_df.copy()
    early_daily["date"] = pd.to_datetime(early_daily["date"])
    early_daily = early_daily.set_index("date")

    print("BUILD_BIG_LEADER_LABELS", flush=True)
    event_sets = standardize_event_sets(matrices["close"], ctx["pool"], idx)
    event_rows: list[dict[str, Any]] = []
    for name, events in event_sets.items():
        print(f"EVALUATE {name} N={len(events)}", flush=True)
        for _, ev in events.iterrows():
            event_rows.append(
                evaluate_event(
                    ev,
                    close=matrices["close"],
                    dvol=matrices["dvol"],
                    idx=idx,
                    idx_pos=idx_pos,
                    ctx=ctx,
                    early_by_score=early_by_score,
                    meta=meta,
                    core_intervals=core_intervals,
                    early_intervals=early_intervals,
                    early_daily=early_daily,
                    promotions=promotions,
                )
            )

    details = pd.DataFrame(event_rows)
    if details.empty:
        raise RuntimeError("no big-leader events")
    details.to_csv(out / "big_leader_event_details.csv", index=False)
    core_entries.to_csv(out / "core20_entries.csv", index=False)
    early_entries.to_csv(out / "early1_entries.csv", index=False)
    promotions.to_csv(out / "early1_promotions.csv", index=False)

    summary_rows: list[dict[str, Any]] = []
    for event_set, g in details.groupby("event_set", observed=True):
        summary_rows.append({"event_set": event_set, "period": "ALL", **summarize_group(g)})
        for period, h in g.groupby("period", observed=True):
            summary_rows.append(
                {"event_set": event_set, "period": str(period), **summarize_group(h)}
            )
    summary_df = pd.DataFrame(summary_rows)
    summary_df.to_csv(out / "big_leader_capture_summary.csv", index=False)

    misses = (
        details[~details["early1_captured"]]
        .groupby(["event_set", "period", "miss_reason"], dropna=False)
        .size()
        .reset_index(name="n")
    )
    misses.to_csv(out / "big_leader_miss_reasons.csv", index=False)

    top5 = summary_df[
        summary_df["event_set"].eq("ANNUAL_TOP5") & summary_df["period"].eq("ALL")
    ]
    plus400 = summary_df[
        summary_df["event_set"].eq("ANNUAL_400PLUS") & summary_df["period"].eq("ALL")
    ]
    rollbig = summary_df[
        summary_df["event_set"].eq("ROLL126_TOP10_GE50") & summary_df["period"].eq("ALL")
    ]

    objective = {}
    for label, z in (
        ("ANNUAL_TOP5", top5),
        ("ANNUAL_400PLUS", plus400),
        ("ROLL126_TOP10_GE50", rollbig),
    ):
        if len(z):
            r = z.iloc[0]
            objective[label] = {
                "capture_rate": safe(r["early1_capture_rate"]),
                "within30_all": safe(r["early1_within30_all"]),
                "within50_all": safe(r["early1_within50_all"]),
                "median_entry_gain": safe(r["early1_entry_gain_median"]),
                "radar_within30_all": safe(r["radar_within30_all"]),
                "radar_within50_all": safe(r["radar_within50_all"]),
                "saved_by_early_rate": safe(r["saved_by_early_rate"]),
            }

    report = {
        "status": "EARLY1_BIG_LEADER_CAPTURE_AUDIT",
        "research_only": True,
        "analysis": {
            "start": str(pd.Timestamp(idx.min()).date()),
            "end": str(pd.Timestamp(idx.max()).date()),
            "liquidity_floor": LIQUIDITY_FLOOR,
            "core_mode": "VACANCY_TOP12",
            "early_slots": EARLY_SLOTS,
            "early_score": EARLY_SCORE,
            "early_gate": EARLY_GATE,
            "early_max_days": EARLY_MAX_DAYS,
            "promotion": "DIRECT_EARLY_TO_CORE",
        },
        "trace_guards": {
            "core_source_instrumented": "ddv.simulate_ordinary_mode",
            "early_source_instrumented": "early.simulate_early_overlay",
            "mechanics_changed": False,
        },
        "core_diag": {k: safe(v) for k, v in core_diag.items()},
        "early_diag": {k: safe(v) for k, v in early_diag.items()},
        "objective": objective,
        "summary": summary_df.to_dict(orient="records"),
        "miss_reasons": misses.to_dict(orient="records"),
        "guardrail": (
            "Primary objective is actual early capture of future big leaders, not CAGR. "
            "Annual labels are complemented by de-duplicated rolling-126-session leaders "
            "to avoid January-anchor bias. No new threshold is selected in this audit."
        ),
    }
    (out / "big_leader_capture_report.json").write_text(
        json.dumps(safe(report), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(safe(report), ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
