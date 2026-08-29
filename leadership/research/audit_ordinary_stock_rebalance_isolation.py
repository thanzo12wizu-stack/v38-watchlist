from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import audit_ordinary_stock_market_mode_robustness as base
import audit_ordinary_stock_rebalance_vs_trail as rt

ANCHORS = (pd.Timestamp("2026-07-13"), pd.Timestamp("2019-01-14"))
SELECTIVE_SLOTS = 4


def simulate_no_prune_scheduled_fill(meta: dict[str, Any], matrices: dict[str, pd.DataFrame]) -> dict[str, Any]:
    """Same biweekly schedule as baseline, but never sells just because rank fell.

    Candidate list refresh and ordinary vacancy fills occur only on scheduled biweekly
    dates, except immediate Red recovery. This isolates the effect of removing
    REBAL_CONTINUATION from the effect of faster vacancy refill.
    """
    idx: pd.DatetimeIndex = meta["analysis_idx"]
    opens = matrices["open"]
    closes = matrices["close"]
    breadth: pd.Series = meta["breadth"]
    nq: pd.DataFrame = meta["nq"]
    rebal: pd.Series = meta["rebalance"]

    cash = 1.0
    pos: dict[str, dict[str, Any]] = {}
    equities: list[tuple[pd.Timestamp, float]] = []
    trades: list[dict[str, Any]] = []
    entries = 0
    red_run = 0
    candidate_cache: list[str] = []

    def px_at(frame: pd.DataFrame, date: pd.Timestamp, sym: str, fallback: float | None = None) -> float | None:
        try:
            x = float(frame.at[date, sym])
            if np.isfinite(x) and x > 0:
                return x
        except Exception:
            pass
        return fallback

    def exit_symbol(sym: str, date: pd.Timestamp, price: float, reason: str) -> None:
        nonlocal cash
        p = pos.pop(sym)
        cash += float(p["shares"]) * price
        trades.append({
            "symbol": sym,
            "entry_date": p["entry_date"],
            "exit_date": date,
            "entry_price": p["entry_price"],
            "exit_price": price,
            "return": price / float(p["entry_price"]) - 1.0,
            "entry_bucket": p["entry_bucket"],
            "exit_reason": reason,
        })

    for i, d0 in enumerate(idx):
        d = pd.Timestamp(d0)
        prev = None if i == 0 else pd.Timestamp(idx[i - 1])
        if prev is not None:
            prev_color = str(nq.at[prev, "nq_color"]) if prev in nq.index and pd.notna(nq.at[prev, "nq_color"]) else ""
            if prev_color == "Red":
                red_run += 1
            else:
                red_run = 0
            red_force = prev_color == "Red" and red_run >= 1

            if red_force:
                for sym in list(pos):
                    fallback = px_at(closes, prev, sym, pos[sym]["entry_price"])
                    opx = px_at(opens, d, sym, fallback)
                    if opx is not None:
                        exit_symbol(sym, d, opx, "RED")
            else:
                for sym in list(pos):
                    p = pos[sym]
                    pc = px_at(closes, prev, sym, p["entry_price"])
                    if pc is None:
                        continue
                    stop = max(float(p["entry_price"]) * 0.75, float(p["peak"]) * 0.70)
                    if pc <= stop:
                        opx = px_at(opens, d, sym, pc)
                        if opx is not None:
                            exit_symbol(sym, d, opx, "WIDE_STOP")

            prev_b = float(breadth.loc[prev]) if prev in breadth.index and pd.notna(breadth.loc[prev]) else np.nan
            bucket = base.breadth_bucket(prev_b)
            is_bull = prev_color in ("Blue", "Green")
            capacity = base.N_PORT if is_bull and bucket == 2 else SELECTIVE_SLOTS if is_bull and bucket == 1 else 0
            scheduled = bool(rebal.get(prev, False))

            prior_color = ""
            if i >= 2:
                pp = pd.Timestamp(idx[i - 2])
                if pp in nq.index and pd.notna(nq.at[pp, "nq_color"]):
                    prior_color = str(nq.at[pp, "nq_color"])
            red_recovery = prior_color == "Red" and is_bull and bucket >= 1

            if scheduled or red_recovery:
                candidate_cache = base.top_candidates(prev, matrices, base.N_PORT)

            fill_allowed = (scheduled or red_recovery) and (not red_force) and capacity > 0
            if fill_allowed and len(pos) < capacity and candidate_cache:
                nav_open = cash
                for sym, p in pos.items():
                    fb = px_at(closes, prev, sym, p["entry_price"])
                    opx = px_at(opens, d, sym, fb)
                    if opx is not None:
                        nav_open += float(p["shares"]) * opx
                slot_cash = nav_open / base.N_PORT
                for sym in candidate_cache:
                    if len(pos) >= capacity or cash <= 0:
                        break
                    if sym in pos:
                        continue
                    opx = px_at(opens, d, sym, px_at(closes, prev, sym, None))
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
                        "peak": opx,
                        "entry_bucket": bucket,
                    }
                    entries += 1

        nav = cash
        for sym, p in pos.items():
            fb = px_at(opens, d, sym, p["entry_price"])
            cp = px_at(closes, d, sym, fb)
            if cp is None:
                cp = float(p["entry_price"])
            p["peak"] = max(float(p["peak"]), cp)
            nav += float(p["shares"]) * cp
        equities.append((d, nav))

    eq = pd.Series(dict(equities), dtype=float).sort_index()
    tdf = pd.DataFrame(trades)
    return {
        "equity": eq,
        "metrics": base.slice_metrics(eq),
        "trades": tdf,
        "trade_count": int(len(tdf)),
        "entry_count": int(entries),
        "trade_stats": rt.trade_stats(tdf),
    }


def pack(v: dict[str, Any]) -> dict[str, Any]:
    return {
        "metrics": v["metrics"],
        "trade_count": int(v.get("trade_count", 0)),
        "entry_count": int(v.get("entry_count", v.get("trade_count", 0))),
        "trade_stats": v.get("trade_stats", rt.trade_stats(v.get("trades", pd.DataFrame()))),
        "rolling_252": base.rolling_252_stats(v["equity"]),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--output", required=True)
    ap.add_argument("--analysis-start", default="2016-01-04")
    ap.add_argument("--analysis-end", default="2026-06-20")
    ap.add_argument("--max-tickers", type=int, default=6000)
    ap.add_argument("--batch-size", type=int, default=75)
    args = ap.parse_args()

    root = Path(args.root)
    out = root / args.output
    out.mkdir(parents=True, exist_ok=True)
    meta0, matrices = base.build_inputs(root, args.analysis_start, args.analysis_end, args.max_tickers, args.batch_size)

    result: dict[str, Any] = {
        "status": "ORDINARY_STOCK_REBALANCE_ISOLATION_AUDIT",
        "question": "Is scheduled rank-pruning itself useful, separated from vacancy-refill speed?",
        "anchors": {},
    }

    for anchor in ANCHORS:
        base.REBAL_ANCHOR = anchor
        meta = dict(meta0)
        meta["rebalance"] = base.build_rebalance_flags(matrices["close"].index)

        print(f"SIM {anchor.date()} forced", flush=True)
        forced = base.simulate(meta, matrices, selective_slots=SELECTIVE_SLOTS, red_confirm_sessions=1, immediate_red_recovery=True)
        forced["trade_stats"] = rt.trade_stats(forced["trades"])

        print(f"SIM {anchor.date()} no_prune_scheduled_fill", flush=True)
        no_prune_sched = simulate_no_prune_scheduled_fill(meta, matrices)

        print(f"SIM {anchor.date()} no_prune_biweekly_candidates_vacancy_fill", flush=True)
        no_prune_vacancy = rt.simulate_trail(meta, matrices, "biweekly", SELECTIVE_SLOTS)

        print(f"SIM {anchor.date()} no_prune_daily_candidates_vacancy_fill", flush=True)
        daily = rt.simulate_trail(meta, matrices, "daily", SELECTIVE_SLOTS)

        sims = {
            "FORCED_BIWEEKLY_REBALANCE": forced,
            "NO_PRUNE_SCHEDULED_FILL": no_prune_sched,
            "NO_PRUNE_BIWEEKLY_CANDIDATES_VACANCY_FILL": no_prune_vacancy,
            "NO_PRUNE_DAILY_CANDIDATES_VACANCY_FILL": daily,
        }
        result["anchors"][str(anchor.date())] = {
            "variants": {k: pack(v) for k, v in sims.items()},
            "block20_win_probability": {
                "no_prune_scheduled_fill_vs_forced": base.bootstrap_block_win(no_prune_sched["equity"], forced["equity"], block=20, reps=5000, seed=73001),
                "vacancy_fill_vs_no_prune_scheduled_fill": base.bootstrap_block_win(no_prune_vacancy["equity"], no_prune_sched["equity"], block=20, reps=5000, seed=73002),
                "daily_candidates_vs_biweekly_candidates": base.bootstrap_block_win(daily["equity"], no_prune_vacancy["equity"], block=20, reps=5000, seed=73003),
            },
        }

    (out / "summary_rebalance_isolation.json").write_text(
        json.dumps(base.safe(result), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("=== REBALANCE_ISOLATION_RESULT_JSON ===", flush=True)
    print(json.dumps(base.safe(result), ensure_ascii=False, indent=2), flush=True)
    print("=== END_REBALANCE_ISOLATION_RESULT_JSON ===", flush=True)


if __name__ == "__main__":
    main()
