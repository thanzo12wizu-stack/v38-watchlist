from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import audit_ordinary_stock_market_mode_robustness as base
import audit_ordinary_stock_rebalance_vs_trail as rt
import audit_ordinary_stock_theme_ranking as tr
import audit_ordinary_stock_theme_attack_only as atk
import validate_early_rotation as er

SELECTIVE_SLOTS = 4
MIN_THEME_MEMBERS = 3


def _replacement_percentile(values: np.ndarray, reference: np.ndarray, pair_theme_idx: np.ndarray) -> np.ndarray:
    """Exact row-wise percentile after replacing each pair's own theme value with its peer-only value."""
    d_n, p_n = values.shape
    out = np.full((d_n, p_n), np.nan, dtype=np.float32)
    for i in range(d_n):
        vals = values[i].astype(float, copy=False)
        mask = np.isfinite(vals)
        if not mask.any():
            continue
        ref = reference[i].astype(float, copy=False)
        ref_finite = ref[np.isfinite(ref)]
        if not len(ref_finite):
            continue
        sorted_ref = np.sort(ref_finite)
        pos = np.flatnonzero(mask)
        vv = vals[pos]
        ti = pair_theme_idx[pos]
        orig = ref[ti]
        counts = np.searchsorted(sorted_ref, vv, side="right").astype(float)
        orig_finite = np.isfinite(orig)
        counts -= (orig_finite & (orig <= vv)).astype(float)
        counts += 1.0
        denom = float(len(sorted_ref)) + (~orig_finite).astype(float)
        out[i, pos] = (counts / denom * 100.0).astype(np.float32)
    return out


def build_leave_one_out_scores(root: Path, matrices: dict[str, pd.DataFrame]) -> dict[str, Any]:
    close = matrices["close"]
    stock_cols = list(close.columns)
    stock_pos = {s: i for i, s in enumerate(stock_cols)}
    stock_set = set(stock_cols)
    stock_ret = er.arithmetic_returns(close)

    snapshot = er.load_json(root / "sector_snapshot.json")
    theme_members_all, _ = er.extract_theme_members(snapshot)
    theme_members = {t: [s for s in members if s in stock_set] for t, members in theme_members_all.items()}
    theme_members = {t: m for t, m in theme_members.items() if len(m) >= MIN_THEME_MEMBERS}

    normal_theme_ret = er.grouped_equal_weight(stock_ret, theme_members, MIN_THEME_MEMBERS)
    normal_theme63 = er.period_return(normal_theme_ret, 63)
    themes = list(normal_theme63.columns)
    theme_pos = {t: i for i, t in enumerate(themes)}
    normal_theme_pct = normal_theme63.rank(axis=1, pct=True, method="average") * 100.0
    normal_delta20 = normal_theme_pct - normal_theme_pct.shift(20)

    pairs: list[tuple[str, str]] = []
    theme_slices: dict[str, tuple[int, int, list[str]]] = {}
    pair_theme_idx: list[int] = []
    pair_stock_idx: list[int] = []
    for theme in themes:
        members = [s for s in theme_members.get(theme, []) if s in stock_pos]
        start = len(pairs)
        for sym in members:
            pairs.append((theme, sym))
            pair_theme_idx.append(theme_pos[theme])
            pair_stock_idx.append(stock_pos[sym])
        theme_slices[theme] = (start, len(pairs), members)

    d_n = len(close.index)
    p_n = len(pairs)
    peer63 = np.full((d_n, p_n), np.nan, dtype=np.float32)
    peer_breadth = np.full((d_n, p_n), np.nan, dtype=np.float32)

    ema21 = close.ewm(span=21, adjust=False, min_periods=15).mean()
    valid_b = close.notna() & ema21.notna()
    above_b = (close > ema21).where(valid_b)

    min_periods = int(math.ceil(63 * 0.8))
    for n_theme, theme in enumerate(themes, start=1):
        start, end, members = theme_slices[theme]
        if not members:
            continue
        vals = stock_ret[members].to_numpy(float)
        valid = np.isfinite(vals)
        sums = np.where(valid, vals, 0.0).sum(axis=1)
        counts = valid.sum(axis=1)
        den = counts[:, None] - valid.astype(np.int16)
        num = sums[:, None] - np.where(valid, vals, 0.0)
        peer_daily = np.divide(num, den, out=np.full_like(num, np.nan), where=den >= 2)
        peer_log = np.log1p(np.where(peer_daily > -0.999999, peer_daily, np.nan))
        peer_log_df = pd.DataFrame(peer_log, index=close.index)
        peer63[:, start:end] = np.expm1(peer_log_df.rolling(63, min_periods=min_periods).sum().to_numpy(float)).astype(np.float32)

        vb = valid_b[members].to_numpy(bool)
        ab_raw = above_b[members].astype(float).to_numpy()
        ab = np.nan_to_num(ab_raw, nan=0.0, posinf=0.0, neginf=0.0)
        total_valid = vb.sum(axis=1)
        total_above = ab.sum(axis=1)
        peer_valid = total_valid[:, None] - vb.astype(np.int16)
        peer_above = total_above[:, None] - ab
        peer_breadth[:, start:end] = np.divide(
            peer_above * 100.0,
            peer_valid,
            out=np.full_like(peer_above, np.nan, dtype=float),
            where=peer_valid >= 2,
        ).astype(np.float32)
        if n_theme % 25 == 0 or n_theme == len(themes):
            print(f"LEAVE_ONE_OUT_THEME {n_theme}/{len(themes)} pairs={end}", flush=True)

    pti = np.asarray(pair_theme_idx, dtype=np.int32)
    psi = np.asarray(pair_stock_idx, dtype=np.int32)
    ref63 = normal_theme63.to_numpy(float)
    peer_pct = _replacement_percentile(peer63, ref63, pti)
    peer_delta20 = np.full_like(peer_pct, np.nan, dtype=np.float32)
    peer_delta20[20:] = peer_pct[20:] - peer_pct[:-20]
    ref_delta = normal_delta20.to_numpy(float)
    peer_delta_pct = _replacement_percentile(peer_delta20, ref_delta, pti)

    score = np.full_like(peer_pct, np.nan, dtype=np.float32)
    ok = np.isfinite(peer_pct) & np.isfinite(peer_delta_pct) & np.isfinite(peer_breadth)
    score[ok] = ((peer_pct[ok] + peer_delta_pct[ok] + peer_breadth[ok]) / 3.0).astype(np.float32)

    best = np.full((d_n, len(stock_cols)), np.nan, dtype=np.float32)
    for j in range(p_n):
        sidx = psi[j]
        best[:, sidx] = np.fmax(best[:, sidx], score[:, j])

    return {
        "best_score": best,
        "date_pos": {pd.Timestamp(d): i for i, d in enumerate(close.index)},
        "stock_pos": stock_pos,
        "coverage": {
            "themes": len(themes),
            "stocks": len(stock_cols),
            "theme_stock_pairs": p_n,
            "mean_memberships_per_stock": float(p_n / max(1, len(stock_cols))),
        },
    }


def peer_ranked_candidates(d: pd.Timestamp, matrices: dict[str, pd.DataFrame], peer_ctx: dict[str, Any], n: int = base.N_PORT) -> list[tuple[str, dict[str, Any]]]:
    elig = matrices["new_eligible"].loc[d]
    stock_rs = matrices["rs189"].loc[d].where(elig).dropna()
    if stock_rs.empty:
        return []
    di = peer_ctx["date_pos"].get(pd.Timestamp(d))
    if di is None:
        return []
    records: list[tuple[str, float, dict[str, Any]]] = []
    for sym, rs0 in stock_rs.items():
        rs = float(rs0)
        si = peer_ctx["stock_pos"].get(str(sym))
        ps = float(peer_ctx["best_score"][di, si]) if si is not None else np.nan
        use_ps = ps if np.isfinite(ps) else 50.0
        score = 0.70 * rs + 0.30 * use_ps
        records.append((str(sym), float(score), {
            "stock_rs189": rs,
            "peer_theme_score": ps if np.isfinite(ps) else None,
            "rank_score": float(score),
        }))
    records.sort(key=lambda x: (x[1], x[2]["stock_rs189"]), reverse=True)
    return [(sym, c) for sym, _, c in records[:n]]


def stock_only_candidates(d: pd.Timestamp, matrices: dict[str, pd.DataFrame], n: int = base.N_PORT) -> list[tuple[str, dict[str, Any]]]:
    elig = matrices["new_eligible"].loc[d]
    stock_rs = matrices["rs189"].loc[d].where(elig).dropna().sort_values(ascending=False).head(n)
    return [(str(sym), {"stock_rs189": float(rs), "peer_theme_score": None, "rank_score": float(rs)}) for sym, rs in stock_rs.items()]


def simulate_peer_attack(meta: dict[str, Any], matrices: dict[str, pd.DataFrame], peer_ctx: dict[str, Any]) -> dict[str, Any]:
    idx: pd.DatetimeIndex = meta["analysis_idx"]
    opens, closes = matrices["open"], matrices["close"]
    breadth: pd.Series = meta["breadth"]
    nq: pd.DataFrame = meta["nq"]
    cash = 1.0
    pos: dict[str, dict[str, Any]] = {}
    equities: list[tuple[pd.Timestamp, float]] = []
    trades: list[dict[str, Any]] = []
    entries: list[dict[str, Any]] = []
    red_run = 0

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
            "stock_rs189": p.get("stock_rs189"),
            "peer_theme_score": p.get("peer_theme_score"),
        })

    for i, d0 in enumerate(idx):
        d = pd.Timestamp(d0)
        prev = None if i == 0 else pd.Timestamp(idx[i - 1])
        if prev is not None:
            prev_color = str(nq.at[prev, "nq_color"]) if prev in nq.index and pd.notna(nq.at[prev, "nq_color"]) else ""
            red_run = red_run + 1 if prev_color == "Red" else 0
            red_force = prev_color == "Red" and red_run >= 1
            if red_force:
                for sym in list(pos):
                    fb = px_at(closes, prev, sym, pos[sym]["entry_price"])
                    opx = px_at(opens, d, sym, fb)
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
            if (not red_force) and capacity > 0 and len(pos) < capacity:
                candidates = peer_ranked_candidates(prev, matrices, peer_ctx, base.N_PORT) if bucket == 2 else stock_only_candidates(prev, matrices, base.N_PORT)
                nav_open = cash
                for sym, p in pos.items():
                    fb = px_at(closes, prev, sym, p["entry_price"])
                    opx = px_at(opens, d, sym, fb)
                    if opx is not None:
                        nav_open += float(p["shares"]) * opx
                slot_cash = nav_open / base.N_PORT
                for sym, c in candidates:
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
                    rec = {"symbol": sym, "signal_date": prev, "entry_date": d, "entry_bucket": bucket, **c}
                    entries.append(rec)
                    pos[sym] = {
                        "shares": alloc / opx,
                        "entry_price": opx,
                        "entry_date": d,
                        "peak": opx,
                        "entry_bucket": bucket,
                        **c,
                    }

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
    edf = pd.DataFrame(entries)
    return {
        "equity": eq,
        "metrics": base.slice_metrics(eq),
        "rolling_252": base.rolling_252_stats(eq),
        "trades": tdf,
        "entries": edf,
        "trade_stats": rt.trade_stats(tdf),
    }


def pack_peer(v: dict[str, Any]) -> dict[str, Any]:
    edf = v["entries"]
    ps = pd.to_numeric(edf.get("peer_theme_score", pd.Series(dtype=float)), errors="coerce")
    return {
        "metrics": v["metrics"],
        "rolling_252": v["rolling_252"],
        "trade_stats": v["trade_stats"],
        "entry_diagnostics": {
            "n": int(len(edf)),
            "peer_theme_score_coverage": float(ps.notna().mean()) if len(edf) else None,
            "peer_theme_score_mean": float(ps.mean()) if ps.notna().any() else None,
            "peer_theme_score_median": float(ps.median()) if ps.notna().any() else None,
        },
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

    meta, matrices = base.build_inputs(root, args.analysis_start, args.analysis_end, args.max_tickers, args.batch_size)
    print("BUILD normal theme context", flush=True)
    tr.MIN_GROUP_MEMBERS = 3
    normal_ctx = tr.build_group_context(root, matrices)
    print("BUILD leave-one-out theme context", flush=True)
    peer_ctx = build_leave_one_out_scores(root, matrices)

    print("SIM STOCK_RS189", flush=True)
    baseline = tr.simulate(meta, matrices, normal_ctx, "STOCK_RS189")
    print("SIM NORMAL_THEME30_ATTACK_ONLY", flush=True)
    normal = atk.simulate_attack_only(meta, matrices, normal_ctx)
    print("SIM LEAVE_ONE_OUT_THEME30_ATTACK_ONLY", flush=True)
    peer = simulate_peer_attack(meta, matrices, peer_ctx)

    result = {
        "status": "THEME_LEAVE_ONE_OUT_AUDIT",
        "question": "Does Theme30 Attack-only survive when each candidate stock is removed from its own Theme return and EMA21 breadth calculations?",
        "coverage": peer_ctx["coverage"],
        "method_note": "Peer-only daily Theme return and peer-only EMA21 breadth are exact. Cross-sectional Theme percentile is recomputed after replacing that Theme's original value with the peer-only value on each date.",
        "variants": {
            "STOCK_RS189": atk.pack(baseline),
            "NORMAL_THEME30_ATTACK_ONLY": atk.pack(normal),
            "LEAVE_ONE_OUT_THEME30_ATTACK_ONLY": pack_peer(peer),
        },
        "comparisons": {
            "NORMAL_VS_BASELINE": {"block20_win": base.bootstrap_block_win(normal["equity"], baseline["equity"], block=20, reps=10000, seed=98101)},
            "LOO_VS_BASELINE": {"block20_win": base.bootstrap_block_win(peer["equity"], baseline["equity"], block=20, reps=10000, seed=98102)},
            "LOO_VS_NORMAL": {"block20_win": base.bootstrap_block_win(peer["equity"], normal["equity"], block=20, reps=10000, seed=98103)},
        },
    }
    for name, sim in (("stock_rs189", baseline), ("normal_theme30_attack", normal), ("loo_theme30_attack", peer)):
        sim["equity"].rename("equity").to_csv(out / f"equity_{name}.csv")
        sim["entries"].to_csv(out / f"entries_{name}.csv", index=False)
        sim["trades"].to_csv(out / f"trades_{name}.csv", index=False)
    (out / "summary_theme_leave_one_out.json").write_text(json.dumps(base.safe(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== THEME_LEAVE_ONE_OUT_JSON ===", flush=True)
    print(json.dumps(base.safe(result), ensure_ascii=False, indent=2), flush=True)
    print("=== END_THEME_LEAVE_ONE_OUT_JSON ===", flush=True)


if __name__ == "__main__":
    main()
