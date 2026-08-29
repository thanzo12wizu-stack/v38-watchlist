from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import audit_ordinary_stock_market_mode_robustness as base
import audit_ordinary_stock_theme_ranking as tr
import audit_ordinary_stock_theme_leave_one_out as loo
import validate_early_rotation as er

MIN_THEME_MEMBERS = 3
COMPONENTS = ("FULL", "RS63_ONLY", "ACCEL_ONLY", "BREADTH_ONLY")
WEIGHTS = (0.15, 0.30, 0.45)


def build_peer_component_scores(root: Path, matrices: dict[str, pd.DataFrame]) -> dict[str, Any]:
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

    d_n, p_n = len(close.index), len(pairs)
    peer63 = np.full((d_n, p_n), np.nan, dtype=np.float32)
    peer_breadth = np.full((d_n, p_n), np.nan, dtype=np.float32)
    ema21 = close.ewm(span=21, adjust=False, min_periods=15).mean()
    valid_b = close.notna() & ema21.notna()
    above_b = (close > ema21).where(valid_b)
    min_periods = int(math.ceil(63 * 0.8))

    for n_theme, theme in enumerate(themes, start=1):
        start, end, members = theme_slices[theme]
        vals = stock_ret[members].to_numpy(float)
        valid = np.isfinite(vals)
        sums = np.where(valid, vals, 0.0).sum(axis=1)
        counts = valid.sum(axis=1)
        den = counts[:, None] - valid.astype(np.int16)
        num = sums[:, None] - np.where(valid, vals, 0.0)
        peer_daily = np.divide(num, den, out=np.full_like(num, np.nan), where=den >= 2)
        peer_log = np.log1p(np.where(peer_daily > -0.999999, peer_daily, np.nan))
        peer63[:, start:end] = np.expm1(
            pd.DataFrame(peer_log, index=close.index).rolling(63, min_periods=min_periods).sum().to_numpy(float)
        ).astype(np.float32)

        vb = valid_b[members].to_numpy(bool)
        ab = np.nan_to_num(above_b[members].astype(float).to_numpy(), nan=0.0, posinf=0.0, neginf=0.0)
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
            print(f"PEER_COMPONENT_THEME {n_theme}/{len(themes)} pairs={end}", flush=True)

    pti = np.asarray(pair_theme_idx, dtype=np.int32)
    psi = np.asarray(pair_stock_idx, dtype=np.int32)
    peer_pct = loo._replacement_percentile(peer63, normal_theme63.to_numpy(float), pti)
    peer_delta20 = np.full_like(peer_pct, np.nan, dtype=np.float32)
    peer_delta20[20:] = peer_pct[20:] - peer_pct[:-20]
    peer_delta_pct = loo._replacement_percentile(peer_delta20, normal_delta20.to_numpy(float), pti)

    pair_scores: dict[str, np.ndarray] = {
        "RS63_ONLY": peer_pct,
        "ACCEL_ONLY": peer_delta_pct,
        "BREADTH_ONLY": peer_breadth,
    }
    full = np.full_like(peer_pct, np.nan, dtype=np.float32)
    ok = np.isfinite(peer_pct) & np.isfinite(peer_delta_pct) & np.isfinite(peer_breadth)
    full[ok] = ((peer_pct[ok] + peer_delta_pct[ok] + peer_breadth[ok]) / 3.0).astype(np.float32)
    pair_scores["FULL"] = full

    best_scores: dict[str, np.ndarray] = {}
    for name, pair_score in pair_scores.items():
        best = np.full((d_n, len(stock_cols)), np.nan, dtype=np.float32)
        for j in range(p_n):
            sidx = psi[j]
            best[:, sidx] = np.fmax(best[:, sidx], pair_score[:, j])
        best_scores[name] = best
        print(f"AGGREGATED {name}", flush=True)

    return {
        "best_scores": best_scores,
        "date_pos": {pd.Timestamp(d): i for i, d in enumerate(close.index)},
        "stock_pos": stock_pos,
        "coverage": {
            "themes": len(themes),
            "stocks": len(stock_cols),
            "theme_stock_pairs": p_n,
        },
    }


def make_ranker(component: str, weight: float):
    def ranker(d: pd.Timestamp, matrices: dict[str, pd.DataFrame], peer_ctx: dict[str, Any], n: int = base.N_PORT):
        elig = matrices["new_eligible"].loc[d]
        stock_rs = matrices["rs189"].loc[d].where(elig).dropna()
        if stock_rs.empty:
            return []
        di = peer_ctx["date_pos"].get(pd.Timestamp(d))
        arr = peer_ctx["best_scores"][component]
        records = []
        for sym, rs0 in stock_rs.items():
            rs = float(rs0)
            si = peer_ctx["stock_pos"].get(str(sym))
            ts = float(arr[di, si]) if di is not None and si is not None else np.nan
            use_ts = ts if np.isfinite(ts) else 50.0
            score = (1.0 - weight) * rs + weight * use_ts
            records.append((str(sym), float(score), {
                "stock_rs189": rs,
                "peer_theme_score": ts if np.isfinite(ts) else None,
                "rank_score": float(score),
            }))
        records.sort(key=lambda x: (x[1], x[2]["stock_rs189"]), reverse=True)
        return [(sym, c) for sym, _, c in records[:n]]
    return ranker


def run_variant(meta: dict[str, Any], matrices: dict[str, pd.DataFrame], peer_ctx: dict[str, Any], component: str, weight: float):
    original = loo.peer_ranked_candidates
    loo.peer_ranked_candidates = make_ranker(component, weight)
    try:
        return loo.simulate_peer_attack(meta, matrices, peer_ctx)
    finally:
        loo.peer_ranked_candidates = original


def pack(v: dict[str, Any]) -> dict[str, Any]:
    return {
        "metrics": v["metrics"],
        "rolling_252": v["rolling_252"],
        "trade_stats": v["trade_stats"],
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
    tr.MIN_GROUP_MEMBERS = 3
    normal_ctx = tr.build_group_context(root, matrices)
    baseline = tr.simulate(meta, matrices, normal_ctx, "STOCK_RS189")
    peer_ctx = build_peer_component_scores(root, matrices)

    variants: dict[str, Any] = {}
    for w in WEIGHTS:
        name = f"FULL_W{int(round(w*100))}"
        print(f"SIM {name}", flush=True)
        variants[name] = run_variant(meta, matrices, peer_ctx, "FULL", w)
    for component in ("RS63_ONLY", "ACCEL_ONLY", "BREADTH_ONLY"):
        name = f"{component}_W30"
        print(f"SIM {name}", flush=True)
        variants[name] = run_variant(meta, matrices, peer_ctx, component, 0.30)

    result = {
        "status": "THEME_LOO_SENSITIVITY_AUDIT",
        "question": "Which leave-one-out Theme weight and component is robust for Attack-only ordinary-stock ranking?",
        "coverage": peer_ctx["coverage"],
        "baseline": pack(baseline),
        "variants": {},
    }
    for i, (name, sim) in enumerate(variants.items()):
        result["variants"][name] = {
            **pack(sim),
            "block20_win_vs_stock_rs189": base.bootstrap_block_win(sim["equity"], baseline["equity"], block=20, reps=10000, seed=99100+i),
        }
        sim["equity"].rename("equity").to_csv(out / f"equity_{name}.csv")
        sim["entries"].to_csv(out / f"entries_{name}.csv", index=False)
    baseline["equity"].rename("equity").to_csv(out / "equity_STOCK_RS189.csv")
    (out / "summary_theme_loo_sensitivity.json").write_text(json.dumps(base.safe(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== THEME_LOO_SENSITIVITY_JSON ===", flush=True)
    print(json.dumps(base.safe(result), ensure_ascii=False, indent=2), flush=True)
    print("=== END_THEME_LOO_SENSITIVITY_JSON ===", flush=True)


if __name__ == "__main__":
    main()
