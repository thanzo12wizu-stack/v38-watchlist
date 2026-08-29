from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import audit_ordinary_stock_market_mode_robustness as base
import audit_ordinary_stock_rebalance_vs_trail as rt
import audit_ordinary_stock_theme_ranking as tr

SELECTIVE_SLOTS = 4


def simulate_attack_only(meta: dict[str, Any], matrices: dict[str, pd.DataFrame], ctx: dict[str, Any]) -> dict[str, Any]:
    """Theme30 only in Attack (breadth >=60); Selective 50-60 keeps stock-RS189 ranking."""
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
            "variant": "THEME30_ATTACK_ONLY",
            "symbol": sym,
            "entry_date": p["entry_date"],
            "exit_date": date,
            "entry_price": p["entry_price"],
            "exit_price": price,
            "return": price / float(p["entry_price"]) - 1.0,
            "entry_bucket": p["entry_bucket"],
            "exit_reason": reason,
            "best_theme": p.get("best_theme"),
            "theme_score": p.get("theme_score"),
            "theme_active": p.get("theme_active"),
            "sector": p.get("sector"),
            "sector_score": p.get("sector_score"),
            "industry": p.get("industry"),
            "industry_score": p.get("industry_score"),
            "stock_rs189": p.get("stock_rs189"),
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
                rank_variant = "THEME30" if bucket == 2 else "STOCK_RS189"
                candidates = tr.ranked_candidates(prev, matrices, ctx, rank_variant, base.N_PORT)
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
                    rec = {
                        "variant": "THEME30_ATTACK_ONLY",
                        "rank_variant": rank_variant,
                        "symbol": sym,
                        "signal_date": prev,
                        "entry_date": d,
                        "entry_bucket": bucket,
                        **c,
                    }
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


def pack(v: dict[str, Any]) -> dict[str, Any]:
    return {
        "metrics": v["metrics"],
        "rolling_252": v["rolling_252"],
        "trade_stats": v["trade_stats"],
        "entry_diagnostics": tr.entry_diagnostics(v["entries"]),
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
    ctx = tr.build_group_context(root, matrices)
    print("SIM STOCK_RS189", flush=True)
    baseline = tr.simulate(meta, matrices, ctx, "STOCK_RS189")
    print("SIM THEME30", flush=True)
    theme30 = tr.simulate(meta, matrices, ctx, "THEME30")
    print("SIM THEME30_ATTACK_ONLY", flush=True)
    attack_only = simulate_attack_only(meta, matrices, ctx)

    sims = {"STOCK_RS189": baseline, "THEME30": theme30, "THEME30_ATTACK_ONLY": attack_only}
    result = {
        "status": "THEME_ATTACK_ONLY_AUDIT",
        "question": "Should the 30% Theme overlay be used only in Attack breadth>=60, leaving Selective 50-60 on stock RS189?",
        "taxonomy_warning": "Current taxonomy is applied retrospectively; require material and period-stable improvement.",
        "variants": {k: pack(v) for k, v in sims.items()},
        "comparisons": {},
    }
    for k in ("THEME30", "THEME30_ATTACK_ONLY"):
        v = sims[k]
        result["comparisons"][k] = {
            "block20_win_vs_baseline": base.bootstrap_block_win(v["equity"], baseline["equity"], block=20, reps=10000, seed=95100 + len(k)),
            "full_cagr_delta": v["metrics"]["full"]["cagr"] - baseline["metrics"]["full"]["cagr"],
            "confirmation_cagr_delta": v["metrics"]["confirmation"]["cagr"] - baseline["metrics"]["confirmation"]["cagr"],
        }
    result["comparisons"]["ATTACK_ONLY_VS_THEME30"] = {
        "block20_win_attack_only_vs_theme30": base.bootstrap_block_win(attack_only["equity"], theme30["equity"], block=20, reps=10000, seed=95200),
        "full_cagr_delta": attack_only["metrics"]["full"]["cagr"] - theme30["metrics"]["full"]["cagr"],
        "confirmation_cagr_delta": attack_only["metrics"]["confirmation"]["cagr"] - theme30["metrics"]["confirmation"]["cagr"],
    }
    for k, v in sims.items():
        v["equity"].rename("equity").to_csv(out / f"equity_{k}.csv")
        v["entries"].to_csv(out / f"entries_{k}.csv", index=False)
        v["trades"].to_csv(out / f"trades_{k}.csv", index=False)
    (out / "summary_theme_attack_only.json").write_text(json.dumps(base.safe(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== THEME_ATTACK_ONLY_JSON ===", flush=True)
    print(json.dumps(base.safe(result), ensure_ascii=False, indent=2), flush=True)
    print("=== END_THEME_ATTACK_ONLY_JSON ===", flush=True)


if __name__ == "__main__":
    main()
