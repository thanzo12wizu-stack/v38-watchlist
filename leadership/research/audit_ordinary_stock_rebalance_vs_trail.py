from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import audit_ordinary_stock_market_mode_robustness as base

ANCHORS = (pd.Timestamp("2026-07-13"), pd.Timestamp("2019-01-14"))
SELECTIVE_SLOTS = 4


def trade_stats(tdf: pd.DataFrame) -> dict[str, Any]:
    if tdf is None or tdf.empty:
        return {"closed_trades": 0}
    x = tdf.copy()
    x["entry_date"] = pd.to_datetime(x["entry_date"])
    x["exit_date"] = pd.to_datetime(x["exit_date"])
    x["return"] = pd.to_numeric(x["return"], errors="coerce")
    x["hold_days"] = (x["exit_date"] - x["entry_date"]).dt.days
    r = x["return"].dropna()
    reasons = x["exit_reason"].value_counts().to_dict() if "exit_reason" in x.columns else {}
    return {
        "closed_trades": int(len(x)),
        "mean_return": float(r.mean()) if len(r) else None,
        "median_return": float(r.median()) if len(r) else None,
        "win_rate": float((r > 0).mean()) if len(r) else None,
        "mean_hold_calendar_days": float(x["hold_days"].mean()) if len(x) else None,
        "median_hold_calendar_days": float(x["hold_days"].median()) if len(x) else None,
        "exit_reasons": {str(k): int(v) for k, v in reasons.items()},
        "by_period": {
            "discovery": simple_trade_stats(x.loc[x["entry_date"] <= pd.Timestamp("2021-12-31")]),
            "confirmation": simple_trade_stats(x.loc[x["entry_date"] >= pd.Timestamp("2022-01-03")]),
        },
    }


def simple_trade_stats(x: pd.DataFrame) -> dict[str, Any]:
    if x is None or x.empty:
        return {"n": 0}
    r = pd.to_numeric(x["return"], errors="coerce").dropna()
    return {
        "n": int(len(x)),
        "mean_return": float(r.mean()) if len(r) else None,
        "median_return": float(r.median()) if len(r) else None,
        "win_rate": float((r > 0).mean()) if len(r) else None,
    }


def simulate_trail(
    meta: dict[str, Any],
    matrices: dict[str, pd.DataFrame],
    candidate_refresh: str,
    selective_slots: int = SELECTIVE_SLOTS,
) -> dict[str, Any]:
    """Hold positions until the common trail/stop or NQSAR Red.

    candidate_refresh:
      - biweekly: candidate ranking cache refreshes on scheduled biweekly dates.
      - daily: candidate ranking refreshes every session close.

    Breadth affects only new-entry capacity and never trims existing holdings.
    Vacancies may be refilled the next session from the latest candidate cache.
    Red recovery refreshes candidates immediately so stale pre-Red rankings are not reused.
    """
    if candidate_refresh not in {"biweekly", "daily"}:
        raise ValueError(candidate_refresh)

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
    candidate_cache_date: pd.Timestamp | None = None

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
            "candidate_refresh": candidate_refresh,
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
                # Same ordinary trail/stop proxy as the baseline audit. The only removed
                # exit is scheduled REBAL_CONTINUATION.
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
            capacity = base.N_PORT if is_bull and bucket == 2 else selective_slots if is_bull and bucket == 1 else 0

            prior_color = ""
            if i >= 2:
                pp = pd.Timestamp(idx[i - 2])
                if pp in nq.index and pd.notna(nq.at[pp, "nq_color"]):
                    prior_color = str(nq.at[pp, "nq_color"])
            red_recovery = prior_color == "Red" and is_bull and bucket >= 1
            scheduled = bool(rebal.get(prev, False))

            refresh_now = candidate_refresh == "daily" or scheduled or red_recovery
            if refresh_now:
                candidate_cache = base.top_candidates(prev, matrices, base.N_PORT)
                candidate_cache_date = prev

            # No scheduled rank-based sell. Refill only if current holdings are below
            # the market-mode new-entry capacity. Existing holdings above a reduced
            # capacity are left untouched.
            if (not red_force) and capacity > 0 and len(pos) < capacity and candidate_cache:
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
                    shares = alloc / opx
                    cash -= alloc
                    pos[sym] = {
                        "shares": shares,
                        "entry_price": opx,
                        "entry_date": d,
                        "peak": opx,
                        "entry_bucket": bucket,
                        "candidate_cache_date": candidate_cache_date,
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
        "open_positions_end": int(len(pos)),
        "trade_stats": trade_stats(tdf),
    }


def pack(sim: dict[str, Any]) -> dict[str, Any]:
    return {
        "metrics": sim["metrics"],
        "trade_count": int(sim.get("trade_count", 0)),
        "entry_count": int(sim.get("entry_count", sim.get("trade_count", 0))),
        "open_positions_end": int(sim.get("open_positions_end", 0)),
        "trade_stats": sim.get("trade_stats", trade_stats(sim.get("trades", pd.DataFrame()))),
        "rolling_252": base.rolling_252_stats(sim["equity"]),
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
        "status": "ORDINARY_STOCK_REBALANCE_VS_TRAIL_AUDIT",
        "scope": "ordinary individual-stock sleeve only; RSI30/shallow-pullback/TQQQ untouched",
        "common_exit_proxy": "next-open after close <= max(entry*0.75, peak*0.70); NQSAR Red next-open overrides",
        "selective_slots": SELECTIVE_SLOTS,
        "anchors": {},
    }

    for anchor in ANCHORS:
        base.REBAL_ANCHOR = anchor
        meta = dict(meta0)
        meta["rebalance"] = base.build_rebalance_flags(matrices["close"].index)

        print(f"SIM anchor={anchor.date()} forced_biweekly", flush=True)
        forced = base.simulate(meta, matrices, selective_slots=SELECTIVE_SLOTS, red_confirm_sessions=1, immediate_red_recovery=True)
        forced["trade_stats"] = trade_stats(forced["trades"])

        print(f"SIM anchor={anchor.date()} trail_biweekly_candidates", flush=True)
        trail_bi = simulate_trail(meta, matrices, "biweekly", SELECTIVE_SLOTS)

        print(f"SIM anchor={anchor.date()} trail_daily_candidates", flush=True)
        trail_day = simulate_trail(meta, matrices, "daily", SELECTIVE_SLOTS)

        sims = {
            "FORCED_BIWEEKLY_REBALANCE": forced,
            "TRAIL_BIWEEKLY_CANDIDATES": trail_bi,
            "TRAIL_DAILY_CANDIDATES": trail_day,
        }
        akey = str(anchor.date())
        result["anchors"][akey] = {
            "variants": {k: pack(v) for k, v in sims.items()},
            "block20_win_probability": {
                "trail_biweekly_vs_forced": base.bootstrap_block_win(trail_bi["equity"], forced["equity"], block=20, reps=5000, seed=62001),
                "trail_daily_vs_forced": base.bootstrap_block_win(trail_day["equity"], forced["equity"], block=20, reps=5000, seed=62002),
                "trail_daily_vs_trail_biweekly": base.bootstrap_block_win(trail_day["equity"], trail_bi["equity"], block=20, reps=5000, seed=62003),
            },
        }
        for k, v in sims.items():
            v["equity"].rename("equity").to_csv(out / f"equity_{akey}_{k}.csv")
            if len(v.get("trades", pd.DataFrame())):
                v["trades"].to_csv(out / f"trades_{akey}_{k}.csv", index=False)

    (out / "summary_rebalance_vs_trail.json").write_text(
        json.dumps(base.safe(result), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("=== REBALANCE_VS_TRAIL_RESULT_JSON ===", flush=True)
    print(json.dumps(base.safe(result), ensure_ascii=False, indent=2), flush=True)
    print("=== END_REBALANCE_VS_TRAIL_RESULT_JSON ===", flush=True)


if __name__ == "__main__":
    main()
