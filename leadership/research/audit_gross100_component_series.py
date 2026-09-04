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
RESET_SLOT = 0.029
RESET_MAX_POS = 4
RESET_HOLD = 20
RESET_COST = 5.0 / 10000.0


def _px(frame, date, sym, fallback=None):
    try:
        x = float(frame.at[date, sym])
        if np.isfinite(x) and x > 0:
            return x
    except Exception:
        pass
    return fallback


def simulate_ordinary(meta, matrices, peer_ctx, liquidity_floor: float = 10_000_000.0):
    """Exact PEAK30_PART25_R3 mechanics plus an entry-only DDV floor.

    The ranking universe remains the adopted >=$10M universe. A higher floor only
    blocks a new entry after ranking and allows the next ranked liquid candidate to
    fill the slot. Existing positions are not sold merely because DDV later falls.
    """
    idx = meta["analysis_idx"]
    opens, closes, dvol = matrices["open"], matrices["close"], matrices["dvol"]
    breadth, nq = meta["breadth"], meta["nq"]
    cash = 1.0
    pos = {}
    rows = []
    red_run = 0

    def close_position(sym, date, price):
        nonlocal cash
        p = pos.pop(sym)
        cash += p["shares"] * price

    for i, d0 in enumerate(idx):
        d = pd.Timestamp(d0)
        prev = None if i == 0 else pd.Timestamp(idx[i - 1])
        fill_allowed = False
        market_color = ""
        market_bucket = 0
        if prev is not None:
            color = str(nq.at[prev, "nq_color"]) if prev in nq.index and pd.notna(nq.at[prev, "nq_color"]) else ""
            red_run = red_run + 1 if color == "Red" else 0
            red_force = color == "Red" and red_run >= 1

            if red_force:
                for sym in list(pos):
                    opx = _px(opens, d, sym, _px(closes, prev, sym, pos[sym]["entry_price"]))
                    if opx is not None:
                        close_position(sym, d, opx)
            else:
                for sym in list(pos):
                    p = pos[sym]
                    pc = _px(closes, prev, sym, p["entry_price"])
                    if pc is None:
                        continue
                    p["sessions"] += 1
                    if (not p["partial_done"]) and pc >= p["entry_price"] * 1.24:
                        opx = _px(opens, d, sym, pc)
                        if opx is not None:
                            sold = p["shares"] * PARTIAL_FRAC
                            cash += sold * opx
                            p["shares"] -= sold
                            p["partial_done"] = True
                    stop = max(p["entry_price"] * 0.92, p["peak_close"] * (1.0 - PEAK_PCT / 100.0))
                    if pc <= stop:
                        opx = _px(opens, d, sym, pc)
                        if opx is not None:
                            close_position(sym, d, opx)

            b = float(breadth.loc[prev]) if prev in breadth.index and pd.notna(breadth.loc[prev]) else np.nan
            bucket = base.breadth_bucket(b)
            bull = color in ("Blue", "Green")
            cap = base.N_PORT if bull and bucket == 2 else SELECTIVE_SLOTS if bull and bucket == 1 else 0
            fill_allowed = bool(bull and np.isfinite(b) and b >= 50.0)
            market_color = color
            market_bucket = int(bucket)

            if (not red_force) and cap > 0 and len(pos) < cap:
                # Ask for a deeper ranked list so an excluded low-DDV top name does
                # not artificially leave the account under-filled.
                candidates = ex.ranked_candidates(prev, matrices, peer_ctx, bucket, max(40, base.N_PORT))
                nav_open = cash
                for sym, p in pos.items():
                    opx = _px(opens, d, sym, _px(closes, prev, sym, p["entry_price"]))
                    if opx is not None:
                        nav_open += p["shares"] * opx
                slot_cash = nav_open / base.N_PORT
                for sym, c in candidates:
                    if len(pos) >= cap or cash <= 0:
                        break
                    if sym in pos:
                        continue
                    dv = _px(dvol, prev, sym, None)
                    if dv is None or dv < float(liquidity_floor):
                        continue
                    opx = _px(opens, d, sym, _px(closes, prev, sym, None))
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
                        "entry_dvol": dv,
                        **c,
                    }

        gross = 0.0
        nav = cash
        for sym, p in pos.items():
            cp = _px(closes, d, sym, _px(opens, d, sym, p["entry_price"]))
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
            "selective_fill_allowed": bool(fill_allowed),
            "market_color_prev": market_color,
            "market_bucket_prev": market_bucket,
            "liquidity_floor": float(liquidity_floor),
        })

    out = pd.DataFrame(rows).set_index("date")
    out["return"] = out["nav"].pct_change(fill_method=None).fillna(0.0)
    return out.reset_index()


def prepare_reset_trades(path: Path, calendar: pd.DatetimeIndex, columns: pd.Index) -> pd.DataFrame:
    t = pd.read_csv(path, compression="gzip", parse_dates=["day0_date", "signal_date", "entry_date"])
    t = t[t.method.eq("RISE_LE30_W20")].copy()
    t["rank_priority"] = t.rank_type.map({"RS63_TOP3": 0, "RS189_TOP3": 1}).fillna(9)
    t = t.sort_values(["day0_date", "theme", "symbol", "rank_priority"]).drop_duplicates(
        ["day0_date", "theme", "symbol"], keep="first")
    t = t[t.entry_date.isin(calendar) & t.symbol.isin(columns)].copy()
    return t


def simulate_reset(calendar, opens, closes, trades):
    """Exact selected RSI Reset portfolio: 2.9% x max4, full entry, fixed 20 sessions, max2/theme."""
    cash = 1.0
    lots = []
    rows = []
    turnover = 0.0
    by_entry = {pd.Timestamp(d): g for d, g in trades.groupby("entry_date", observed=True)}
    for i, d0 in enumerate(calendar):
        d = pd.Timestamp(d0)
        keep = []
        for z in lots:
            px = _px(opens, d, z["symbol"])
            if i >= z["exit_i"] and px is not None:
                gross = z["shares"] * px
                cash += gross * (1 - RESET_COST)
                turnover += gross
            else:
                keep.append(z)
        lots = keep

        if d in by_entry:
            day = by_entry[d].sort_values(["rank_priority", "rsi_signal", "symbol"])
            for r in day.itertuples(index=False):
                if len(lots) >= RESET_MAX_POS:
                    continue
                if sum(q["theme"] == r.theme for q in lots) >= 2:
                    continue
                px = _px(opens, d, r.symbol)
                if px is None:
                    continue
                mark = cash
                for q in lots:
                    qpx = _px(opens, d, q["symbol"])
                    if qpx is not None:
                        mark += q["shares"] * qpx
                amount = RESET_SLOT * mark
                if cash < amount * (1 + RESET_COST):
                    continue
                cash -= amount * (1 + RESET_COST)
                turnover += amount
                lots.append({
                    "symbol": r.symbol,
                    "theme": r.theme,
                    "shares": amount / px,
                    "entry_i": i,
                    "exit_i": min(i + RESET_HOLD, len(calendar) - 1),
                })

        gross = 0.0
        nav = cash
        for z in lots:
            cp = _px(closes, d, z["symbol"])
            if cp is not None:
                mark = z["shares"] * cp
                gross += mark
                nav += mark
        rows.append({
            "date": d,
            "nav": nav,
            "gross_value": gross,
            "gross_exposure": gross / nav if nav > 0 else np.nan,
            "positions": len(lots),
        })
    out = pd.DataFrame(rows).set_index("date")
    out["return"] = out["nav"].pct_change(fill_method=None).fillna(0.0)
    return out.reset_index(), turnover


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--reset-trades", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--analysis-start", default="2016-01-04")
    ap.add_argument("--analysis-end", default="2026-03-20")
    ap.add_argument("--max-tickers", type=int, default=6000)
    ap.add_argument("--batch-size", type=int, default=75)
    ap.add_argument("--liquidity-floor", type=float, default=10_000_000.0)
    args = ap.parse_args()
    root = Path(args.root)
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    meta, matrices = ex.build_inputs_ext(root, args.analysis_start, args.analysis_end, args.max_tickers, args.batch_size)
    peer_ctx = loo.build_leave_one_out_scores(root, matrices)
    ordinary = simulate_ordinary(meta, matrices, peer_ctx, args.liquidity_floor)
    cal = pd.DatetimeIndex(meta["analysis_idx"])
    reset_trades = prepare_reset_trades(Path(args.reset_trades), cal, matrices["close"].columns)
    reset, reset_turnover = simulate_reset(cal, matrices["open"], matrices["close"], reset_trades)

    ordinary.to_csv(out / "ordinary_PEAK30_PART25_R3_daily.csv.gz", index=False, compression="gzip")
    reset.to_csv(out / "rsi_RESET_RISE30_S029_P4_H20_daily.csv.gz", index=False, compression="gzip")
    print({
        "start": str(pd.Timestamp(ordinary.date.min()).date()),
        "end": str(pd.Timestamp(ordinary.date.max()).date()),
        "days": int(len(ordinary)),
        "ordinary_avg_gross": float(ordinary.gross_exposure.mean()),
        "ordinary_max_gross": float(ordinary.gross_exposure.max()),
        "ordinary_liquidity_floor": float(args.liquidity_floor),
        "reset_avg_gross": float(reset.gross_exposure.mean()),
        "reset_max_gross": float(reset.gross_exposure.max()),
        "reset_max_positions": int(reset.positions.max()),
        "reset_trades_input": int(len(reset_trades)),
        "reset_turnover_value": float(reset_turnover),
    }, flush=True)


if __name__ == "__main__":
    main()
