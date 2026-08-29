from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import audit_ordinary_stock_market_mode_robustness as base
import audit_ordinary_stock_rebalance_vs_trail as rt
import audit_ordinary_stock_theme_leave_one_out as loo
import audit_ordinary_stock_exit_trail as ex

SELECTIVE_SLOTS = 4
PEAK_PCTS = (25, 30, 35)
OVERLAYS = ("BASE", "BE8", "PART25_R3", "PART30_R3", "BE8_PART25_R3", "EIGHT_WEEK")
VARIANTS = tuple(f"PEAK{p}_{o}" for p in PEAK_PCTS for o in OVERLAYS)


def simulate(meta, matrices, peer_ctx, peak_pct: int, overlay: str):
    idx = meta["analysis_idx"]
    opens, closes = matrices["open"], matrices["close"]
    breadth, nq = meta["breadth"], meta["nq"]
    cash = 1.0
    pos: dict[str, dict[str, Any]] = {}
    equities, trades = [], []
    red_run = 0
    variant = f"PEAK{peak_pct}_{overlay}"

    def px(frame, date, sym, fallback=None):
        try:
            x = float(frame.at[date, sym])
            if np.isfinite(x) and x > 0:
                return x
        except Exception:
            pass
        return fallback

    def close_position(sym, date, price, reason):
        nonlocal cash
        p = pos.pop(sym)
        cash += p["shares"] * price
        trades.append({
            "variant": variant, "symbol": sym, "entry_date": p["entry_date"], "exit_date": date,
            "entry_price": p["entry_price"], "exit_price": price,
            "return": price / p["entry_price"] - 1.0, "exit_reason": reason,
            "entry_bucket": p["entry_bucket"], "partial_done": p.get("partial_done", False),
            "eight_week_triggered": p.get("eight_week_triggered", False),
        })

    for i, d0 in enumerate(idx):
        d = pd.Timestamp(d0)
        prev = None if i == 0 else pd.Timestamp(idx[i - 1])
        if prev is not None:
            color = str(nq.at[prev, "nq_color"]) if prev in nq.index and pd.notna(nq.at[prev, "nq_color"]) else ""
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
                    p["sessions"] += 1

                    if overlay in ("BE8", "BE8_PART25_R3") and pc >= p["entry_price"] * 1.08:
                        p["be_armed"] = True
                    if overlay == "EIGHT_WEEK" and p["sessions"] <= 15 and pc >= p["entry_price"] * 1.20:
                        p["eight_week_triggered"] = True

                    partial_frac = 0.0
                    if overlay in ("PART25_R3", "BE8_PART25_R3"):
                        partial_frac = 0.25
                    elif overlay == "PART30_R3":
                        partial_frac = 0.30
                    if partial_frac and (not p["partial_done"]) and pc >= p["entry_price"] * 1.24:
                        opx = px(opens, d, sym, pc)
                        if opx is not None:
                            sold = p["shares"] * partial_frac
                            cash += sold * opx
                            p["shares"] -= sold
                            p["partial_done"] = True

                    stop = p["entry_price"] * 0.92
                    reason = "HARD8"
                    if p.get("be_armed", False) and p["entry_price"] > stop:
                        stop, reason = p["entry_price"], "BREAKEVEN"

                    hold_lock = overlay == "EIGHT_WEEK" and p.get("eight_week_triggered", False) and p["sessions"] < 40
                    if not hold_lock:
                        peak_stop = p["peak_close"] * (1.0 - peak_pct / 100.0)
                        if peak_stop > stop:
                            stop, reason = peak_stop, f"PEAK{peak_pct}"
                    if pc <= stop:
                        opx = px(opens, d, sym, pc)
                        if opx is not None:
                            close_position(sym, d, opx, reason)

            b = float(breadth.loc[prev]) if prev in breadth.index and pd.notna(breadth.loc[prev]) else np.nan
            bucket = base.breadth_bucket(b)
            bull = color in ("Blue", "Green")
            cap = base.N_PORT if bull and bucket == 2 else SELECTIVE_SLOTS if bull and bucket == 1 else 0
            if (not red_force) and cap > 0 and len(pos) < cap:
                candidates = ex.ranked_candidates(prev, matrices, peer_ctx, bucket, base.N_PORT)
                nav_open = cash
                for sym, p in pos.items():
                    opx = px(opens, d, sym, px(closes, prev, sym, p["entry_price"]))
                    if opx is not None:
                        nav_open += p["shares"] * opx
                slot_cash = nav_open / base.N_PORT
                for sym, c in candidates:
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
                        "shares": alloc / opx, "entry_price": opx, "entry_date": d,
                        "peak_close": opx, "entry_bucket": bucket, "sessions": 0,
                        "be_armed": False, "partial_done": False, "eight_week_triggered": False, **c,
                    }

        nav = cash
        for sym, p in pos.items():
            cp = px(closes, d, sym, px(opens, d, sym, p["entry_price"]))
            if cp is None:
                cp = p["entry_price"]
            p["peak_close"] = max(p["peak_close"], cp)
            nav += p["shares"] * cp
        equities.append((d, nav))

    eq = pd.Series(dict(equities), dtype=float).sort_index()
    tdf = pd.DataFrame(trades)
    return {"equity": eq, "metrics": base.slice_metrics(eq), "rolling_252": base.rolling_252_stats(eq), "trades": tdf, "trade_stats": rt.trade_stats(tdf)}


def main():
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
    meta, matrices = ex.build_inputs_ext(root, args.analysis_start, args.analysis_end, args.max_tickers, args.batch_size)
    peer_ctx = loo.build_leave_one_out_scores(root, matrices)
    sims = {}
    for p in PEAK_PCTS:
        for overlay in OVERLAYS:
            v = f"PEAK{p}_{overlay}"
            print(f"SIM {v}", flush=True)
            sims[v] = simulate(meta, matrices, peer_ctx, p, overlay)
    result = {"status": "ORDINARY_STOCK_EXIT_OVERLAY_AUDIT", "variants": {}, "vs_same_peak_base": {}}
    for v, sim in sims.items():
        result["variants"][v] = {"metrics": sim["metrics"], "rolling_252": sim["rolling_252"], "trade_stats": sim["trade_stats"]}
        sim["equity"].rename("equity").to_csv(out / f"equity_{v}.csv")
        sim["trades"].to_csv(out / f"trades_{v}.csv", index=False)
    for p in PEAK_PCTS:
        b = f"PEAK{p}_BASE"
        result["vs_same_peak_base"][str(p)] = {}
        for overlay in OVERLAYS[1:]:
            v = f"PEAK{p}_{overlay}"
            result["vs_same_peak_base"][str(p)][overlay] = base.bootstrap_block_win(sims[v]["equity"], sims[b]["equity"], block=20, reps=10000, seed=130000 + p * 10 + OVERLAYS.index(overlay))
    (out / "summary_exit_overlays.json").write_text(json.dumps(base.safe(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== EXIT_OVERLAYS_JSON ===")
    print(json.dumps(base.safe(result), ensure_ascii=False, indent=2))
    print("=== END_EXIT_OVERLAYS_JSON ===")


if __name__ == "__main__":
    main()
