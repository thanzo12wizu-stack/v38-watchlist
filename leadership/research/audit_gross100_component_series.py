from __future__ import annotations

import argparse
from pathlib import Path
import numpy as np
import pandas as pd

import audit_ordinary_stock_market_mode_robustness as base
import audit_ordinary_stock_exit_trail as ex
import audit_ordinary_stock_theme_leave_one_out as loo

SELECTIVE_SLOTS = 4
PEAK_PCT = 30
PARTIAL_FRAC = 0.25


def simulate_selected(meta, matrices, peer_ctx):
    """Exact PEAK30_PART25_R3 mechanics, with daily gross/exposure diagnostics added."""
    idx = meta["analysis_idx"]
    opens, closes = matrices["open"], matrices["close"]
    breadth, nq = meta["breadth"], meta["nq"]
    cash = 1.0
    pos = {}
    rows = []
    red_run = 0

    def px(frame, date, sym, fallback=None):
        try:
            x = float(frame.at[date, sym])
            if np.isfinite(x) and x > 0:
                return x
        except Exception:
            pass
        return fallback

    def close_position(sym, date, price):
        nonlocal cash
        p = pos.pop(sym)
        cash += p["shares"] * price

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
                        close_position(sym, d, opx)
            else:
                for sym in list(pos):
                    p = pos[sym]
                    pc = px(closes, prev, sym, p["entry_price"])
                    if pc is None:
                        continue
                    p["sessions"] += 1

                    if (not p["partial_done"]) and pc >= p["entry_price"] * 1.24:
                        opx = px(opens, d, sym, pc)
                        if opx is not None:
                            sold = p["shares"] * PARTIAL_FRAC
                            cash += sold * opx
                            p["shares"] -= sold
                            p["partial_done"] = True

                    stop = p["entry_price"] * 0.92
                    peak_stop = p["peak_close"] * (1.0 - PEAK_PCT / 100.0)
                    stop = max(stop, peak_stop)
                    if pc <= stop:
                        opx = px(opens, d, sym, pc)
                        if opx is not None:
                            close_position(sym, d, opx)

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
                        "shares": alloc / opx,
                        "entry_price": opx,
                        "entry_date": d,
                        "peak_close": opx,
                        "sessions": 0,
                        "partial_done": False,
                        **c,
                    }

        gross = 0.0
        nav = cash
        for sym, p in pos.items():
            cp = px(closes, d, sym, px(opens, d, sym, p["entry_price"]))
            if cp is None:
                cp = p["entry_price"]
            p["peak_close"] = max(p["peak_close"], cp)
            mark = p["shares"] * cp
            gross += mark
            nav += mark
        rows.append({
            "date": d,
            "nav": nav,
            "gross_value": gross,
            "gross_exposure": gross / nav if nav > 0 else np.nan,
            "positions": len(pos),
        })

    out = pd.DataFrame(rows).set_index("date")
    out["return"] = out["nav"].pct_change(fill_method=None).fillna(0.0)
    return out.reset_index()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--output", required=True)
    ap.add_argument("--analysis-start", default="2016-01-04")
    ap.add_argument("--analysis-end", default="2026-03-20")
    ap.add_argument("--max-tickers", type=int, default=6000)
    ap.add_argument("--batch-size", type=int, default=75)
    args = ap.parse_args()
    root = Path(args.root)
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    meta, matrices = ex.build_inputs_ext(root, args.analysis_start, args.analysis_end, args.max_tickers, args.batch_size)
    peer_ctx = loo.build_leave_one_out_scores(root, matrices)
    daily = simulate_selected(meta, matrices, peer_ctx)
    daily.to_csv(out / "ordinary_PEAK30_PART25_R3_daily.csv.gz", index=False, compression="gzip")
    print(daily.tail().to_string(index=False), flush=True)
    print({
        "start": str(pd.Timestamp(daily.date.min()).date()),
        "end": str(pd.Timestamp(daily.date.max()).date()),
        "days": int(len(daily)),
        "avg_gross": float(daily.gross_exposure.mean()),
        "max_gross": float(daily.gross_exposure.max()),
    }, flush=True)


if __name__ == "__main__":
    main()
