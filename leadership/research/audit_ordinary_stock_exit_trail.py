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
import audit_rsi30_mc_nqsar as market_audit
import validate_early_rotation as er
import validate_ignition_quality as iq

SELECTIVE_SLOTS = 4
VARIANTS = ("HARD8_ONLY", "SMA10", "EMA21_LOW", "ATR2", "ATR3", "ATR4", "WIDE_PROXY")


def build_inputs_ext(root: Path, analysis_start: str, analysis_end: str, max_tickers: int, batch_size: int):
    snapshot = er.load_json(root / "sector_snapshot.json")
    theme_members_all, _ = er.extract_theme_members(snapshot)
    industry_map = er.read_industry_map(root / "industry_map.json")
    universe = er.read_universe_symbols(root / "universe.csv")
    allowed = set(industry_map) & universe
    selected = er.stratified_symbols(theme_members_all, allowed, max_tickers)
    if len(selected) < 500:
        raise RuntimeError(f"selected universe too small: {len(selected)}")
    warmup = str((pd.Timestamp(analysis_start) - pd.Timedelta(days=1150)).date())
    download_end = str((pd.Timestamp(analysis_end) + pd.Timedelta(days=10)).date())
    ohlcv, diag = iq.download_ohlcv(selected, warmup, download_end, batch_size)
    close = ohlcv["close"]
    stock_cols = [s for s in selected if s in close.columns]
    if len(stock_cols) < 500:
        raise RuntimeError(f"downloaded stock coverage too small: {len(stock_cols)}")
    ohlcv = {k: v[stock_cols].copy() for k, v in ohlcv.items()}
    opn, high, low, close, volume = ohlcv["open"], ohlcv["high"], ohlcv["low"], ohlcv["close"], ohlcv["volume"]

    sma10 = close.rolling(10, min_periods=10).mean()
    sma50 = close.rolling(50, min_periods=50).mean()
    sma200 = close.rolling(200, min_periods=200).mean()
    ema21_low = low.ewm(span=21, adjust=False, min_periods=21).mean()
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    true_range = pd.DataFrame(np.maximum.reduce([tr1.to_numpy(float), tr2.to_numpy(float), tr3.to_numpy(float)]), index=close.index, columns=close.columns)
    atr14 = true_range.ewm(alpha=1.0 / 14.0, adjust=False, min_periods=14).mean()

    vol20 = volume.rolling(20, min_periods=20).mean()
    dvol = close * vol20
    ret63 = close / close.shift(63) - 1.0
    ret189 = close / close.shift(189) - 1.0
    bio_excluded = base.read_structural_bio_exclusions(root, stock_cols)
    base_pool = (close >= 5.0) & (dvol >= base.DVOL_FLOOR)
    if bio_excluded:
        base_pool.loc[:, [s for s in bio_excluded if s in base_pool.columns]] = False
    rs63 = ret63.where(base_pool & ret63.notna()).rank(axis=1, pct=True) * 100.0
    rs189 = ret189.where(base_pool & ret189.notna()).rank(axis=1, pct=True) * 100.0
    new_eligible = base_pool & (sma50 > sma200) & (close > sma200) & (rs189 >= base.RS_MIN) & (rs63 >= base.RS_MIN)
    continuation_eligible = base_pool & (sma50 > sma200) & (rs189 >= base.RS_MIN)

    nobs = close.notna().sum(axis=1)
    floor = max(5, min(30, int(max(1, close.shape[1]) * 0.20)))
    v50 = sma50.notna().sum(axis=1)
    pa50 = close.gt(sma50).sum(axis=1) / v50.replace(0, np.nan) * 100.0
    pa50 = pa50.where(v50 >= np.maximum(floor, nobs * 0.45))
    analysis_idx = close.index[(close.index >= pd.Timestamp(analysis_start)) & (close.index <= pd.Timestamp(analysis_end))]
    nq = market_audit.build_nqsar(str((pd.Timestamp(analysis_start) - pd.Timedelta(days=40)).date()), download_end)
    nq = nq.reindex(close.index).ffill(limit=1)

    matrices = {
        "open": opn, "high": high, "low": low, "close": close,
        "sma10": sma10, "sma50": sma50, "sma200": sma200,
        "ema21_low": ema21_low, "atr14": atr14,
        "dvol": dvol, "rs63": rs63, "rs189": rs189,
        "new_eligible": new_eligible, "continuation_eligible": continuation_eligible,
    }
    meta = {
        "selected": len(selected), "downloaded": len(stock_cols), "bio_excluded": len(bio_excluded),
        "download": diag, "analysis_idx": analysis_idx, "breadth": pa50, "nq": nq,
    }
    return meta, matrices


def ranked_candidates(d: pd.Timestamp, matrices: dict[str, pd.DataFrame], peer_ctx: dict[str, Any], bucket: int, n: int = base.N_PORT):
    elig = matrices["new_eligible"].loc[d]
    rs = matrices["rs189"].loc[d].where(elig).dropna()
    if rs.empty:
        return []
    if bucket == 1:
        return [(str(s), {"stock_rs189": float(v), "peer_theme_score": None, "rank_score": float(v)}) for s, v in rs.nlargest(n).items()]
    return loo.peer_ranked_candidates(d, matrices, peer_ctx, n)


def simulate(meta, matrices, peer_ctx, variant: str):
    idx = meta["analysis_idx"]
    opens, closes = matrices["open"], matrices["close"]
    breadth, nq = meta["breadth"], meta["nq"]
    cash = 1.0
    pos: dict[str, dict[str, Any]] = {}
    equities, trades, entries = [], [], []
    red_run = 0

    def px(frame, date, sym, fallback=None):
        try:
            x = float(frame.at[date, sym])
            if np.isfinite(x) and x > 0:
                return x
        except Exception:
            pass
        return fallback

    def exit_symbol(sym, date, price, reason):
        nonlocal cash
        p = pos.pop(sym)
        cash += p["shares"] * price
        trades.append({
            "variant": variant, "symbol": sym, "entry_date": p["entry_date"], "exit_date": date,
            "entry_price": p["entry_price"], "exit_price": price,
            "return": price / p["entry_price"] - 1.0, "exit_reason": reason,
            "entry_bucket": p["entry_bucket"], "stock_rs189": p.get("stock_rs189"),
            "peer_theme_score": p.get("peer_theme_score"),
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
                        exit_symbol(sym, d, opx, "RED")
            else:
                for sym in list(pos):
                    p = pos[sym]
                    pc = px(closes, prev, sym, p["entry_price"])
                    if pc is None:
                        continue
                    hard = p["entry_price"] * 0.92
                    stop = hard
                    reason = "HARD8"
                    if variant == "SMA10":
                        x = px(matrices["sma10"], prev, sym, None)
                        if x is not None and x > stop:
                            stop, reason = x, "SMA10"
                    elif variant == "EMA21_LOW":
                        x = px(matrices["ema21_low"], prev, sym, None)
                        if x is not None and x > stop:
                            stop, reason = x, "EMA21_LOW"
                    elif variant.startswith("ATR"):
                        k = float(variant.replace("ATR", ""))
                        a = px(matrices["atr14"], prev, sym, None)
                        if a is not None:
                            x = p["peak_close"] - k * a
                            if x > stop:
                                stop, reason = x, f"ATR{k:g}"
                    elif variant == "WIDE_PROXY":
                        x = p["peak_close"] * 0.70
                        if x > stop:
                            stop, reason = x, "WIDE_PROXY"
                    if pc <= stop:
                        opx = px(opens, d, sym, pc)
                        if opx is not None:
                            exit_symbol(sym, d, opx, reason)

            b = float(breadth.loc[prev]) if prev in breadth.index and pd.notna(breadth.loc[prev]) else np.nan
            bucket = base.breadth_bucket(b)
            bull = color in ("Blue", "Green")
            cap = base.N_PORT if bull and bucket == 2 else SELECTIVE_SLOTS if bull and bucket == 1 else 0
            if (not red_force) and cap > 0 and len(pos) < cap:
                candidates = ranked_candidates(prev, matrices, peer_ctx, bucket, base.N_PORT)
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
                        "shares": alloc / opx, "entry_price": opx, "entry_date": d, "peak_close": opx,
                        "entry_bucket": bucket, **c,
                    }
                    entries.append({"variant": variant, "symbol": sym, "signal_date": prev, "entry_date": d, "entry_bucket": bucket, **c})

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
    edf = pd.DataFrame(entries)
    return {
        "equity": eq, "metrics": base.slice_metrics(eq), "rolling_252": base.rolling_252_stats(eq),
        "trades": tdf, "entries": edf, "trade_stats": rt.trade_stats(tdf),
    }


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
    meta, matrices = build_inputs_ext(root, args.analysis_start, args.analysis_end, args.max_tickers, args.batch_size)
    print("BUILD leave-one-out theme context", flush=True)
    peer_ctx = loo.build_leave_one_out_scores(root, matrices)
    sims = {}
    for v in VARIANTS:
        print(f"SIM {v}", flush=True)
        sims[v] = simulate(meta, matrices, peer_ctx, v)
    result = {
        "status": "ORDINARY_STOCK_EXIT_TRAIL_AUDIT",
        "frozen_selection": "Attack: Stock RS189 70% + leave-one-out peer Theme 30%; Selective: Stock RS189; daily refresh/refill; no scheduled prune; same market mode.",
        "common_initial_stop": "close <= 92% of entry -> next-open exit; all variants share this 8% initial-loss ceiling",
        "variants": {}, "pairwise_block20": {},
    }
    for v, sim in sims.items():
        result["variants"][v] = {"metrics": sim["metrics"], "rolling_252": sim["rolling_252"], "trade_stats": sim["trade_stats"]}
        sim["equity"].rename("equity").to_csv(out / f"equity_{v}.csv")
        sim["trades"].to_csv(out / f"trades_{v}.csv", index=False)
    for a in VARIANTS:
        result["pairwise_block20"][a] = {}
        for b in VARIANTS:
            if a == b:
                continue
            result["pairwise_block20"][a][b] = base.bootstrap_block_win(sims[a]["equity"], sims[b]["equity"], block=20, reps=10000, seed=110000 + 17 * VARIANTS.index(a) + VARIANTS.index(b))
    (out / "summary_exit_trail.json").write_text(json.dumps(base.safe(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== EXIT_TRAIL_JSON ===", flush=True)
    print(json.dumps(base.safe(result), ensure_ascii=False, indent=2), flush=True)
    print("=== END_EXIT_TRAIL_JSON ===", flush=True)


if __name__ == "__main__":
    main()
