from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

import audit_ordinary_stock_market_mode_robustness as base
import audit_ordinary_stock_theme_leave_one_out as loo
import audit_leadership_cycle as lc

DISC_END = pd.Timestamp("2021-12-31")
CONF_START = pd.Timestamp("2022-01-03")
N = 12
COST_SIDE = 0.001


def safe(v: Any) -> Any:
    return base.safe(v)


def metrics(eq: pd.Series) -> dict[str, Any]:
    e = pd.to_numeric(eq, errors="coerce").dropna()
    if len(e) < 5:
        return {"n": len(e)}
    r = e.pct_change(fill_method=None).dropna()
    yrs = max(len(r) / 252.0, 1 / 252)
    cagr = float((e.iloc[-1] / e.iloc[0]) ** (1 / yrs) - 1) if e.iloc[0] > 0 else np.nan
    dd = e / e.cummax() - 1.0
    sd = float(r.std(ddof=1)) if len(r) > 1 else np.nan
    sharpe = float(r.mean() / sd * np.sqrt(252)) if np.isfinite(sd) and sd > 0 else np.nan
    return {"n": len(e), "cagr": cagr, "mdd": float(dd.min()), "sharpe": sharpe,
            "total_return": float(e.iloc[-1] / e.iloc[0] - 1.0)}


def split_metrics(eq: pd.Series) -> dict[str, Any]:
    return {
        "full": metrics(eq),
        "discovery": metrics(eq.loc[eq.index <= DISC_END]),
        "confirmation": metrics(eq.loc[eq.index >= CONF_START]),
        "2016_2019": metrics(eq.loc[(eq.index >= "2016-01-01") & (eq.index <= "2019-12-31")]),
        "2020_2021": metrics(eq.loc[(eq.index >= "2020-01-01") & (eq.index <= "2021-12-31")]),
        "2022_2023": metrics(eq.loc[(eq.index >= "2022-01-01") & (eq.index <= "2023-12-31")]),
        "2024_2026": metrics(eq.loc[eq.index >= "2024-01-01"]),
    }


def stock_candidates(d: pd.Timestamp, matrices: dict[str, pd.DataFrame], n: int = N) -> list[str]:
    elig = matrices["new_eligible"].loc[d]
    rs = matrices["rs189"].loc[d].where(elig).dropna().sort_values(ascending=False)
    return [str(x) for x in rs.head(n).index]


def loo_candidates(d: pd.Timestamp, matrices: dict[str, pd.DataFrame], ctx: dict[str, Any], n: int = N) -> list[str]:
    return [sym for sym, _ in loo.peer_ranked_candidates(d, matrices, ctx, n)]


def overlay_capacity(base_capacity: int, overlay: str, f1: float, f2: float, f3: float) -> int:
    if base_capacity != N:
        return base_capacity
    f1w = np.isfinite(f1) and f1 >= 0.30
    f2w = np.isfinite(f2) and f2 >= 0.40
    f3s = np.isfinite(f3) and f3 >= 0.60
    if overlay == "NONE":
        return N
    if overlay == "F1_TO4" and f1w:
        return 4
    if overlay == "F2_TO4" and f2w:
        return 4
    if overlay == "F1F2_TO4" and f1w and f2w:
        return 4
    if overlay == "F1F2_STOP" and f1w and f2w:
        return 0
    if overlay == "F3_TO4" and f3s:
        return 4
    return N


def simulate(
    meta: dict[str, Any], matrices: dict[str, pd.DataFrame], sig: pd.DataFrame,
    overlay: str, ranking: str, peer_ctx: dict[str, Any] | None = None,
) -> dict[str, Any]:
    idx: pd.DatetimeIndex = meta["analysis_idx"]
    opens = matrices["open"]; closes = matrices["close"]
    breadth: pd.Series = meta["breadth"]
    nq: pd.DataFrame = meta["nq"]

    cash = 1.0
    pos: dict[str, dict[str, Any]] = {}
    equities: list[tuple[pd.Timestamp, float]] = []
    trades: list[dict[str, Any]] = []
    partials = 0; entries = 0; overlay_days = 0

    def px(frame: pd.DataFrame, d: pd.Timestamp, sym: str, fallback: float | None = None) -> float | None:
        try:
            x = float(frame.at[d, sym])
            return x if np.isfinite(x) and x > 0 else fallback
        except Exception:
            return fallback

    def sell(sym: str, d: pd.Timestamp, raw_price: float, fraction_of_original: float, reason: str) -> None:
        nonlocal cash, partials
        p = pos[sym]
        qty = min(float(p["shares"]), float(p["original_shares"]) * fraction_of_original)
        if qty <= 1e-14:
            return
        ex = raw_price * (1.0 - COST_SIDE)
        cash += qty * ex
        p["shares"] -= qty
        if reason == "PARTIAL25":
            p["partial_taken"] = True
            partials += 1
        if p["shares"] <= p["original_shares"] * 1e-10:
            trades.append({
                "symbol": sym, "entry_date": p["entry_date"], "exit_date": d,
                "entry_price": p["entry_price"], "exit_price": ex,
                "return": ex / p["entry_price"] - 1.0, "exit_reason": reason,
                "overlay": overlay, "ranking": ranking,
            })
            del pos[sym]

    for i, d0 in enumerate(idx):
        d = pd.Timestamp(d0)
        prev = None if i == 0 else pd.Timestamp(idx[i - 1])
        if prev is not None:
            color = str(nq.at[prev, "nq_color"]) if prev in nq.index and pd.notna(nq.at[prev, "nq_color"]) else ""
            red = color == "Red"

            # All decisions use prior completed close; all orders execute at today's open.
            if red:
                for sym in list(pos):
                    raw = px(opens, d, sym, px(closes, prev, sym, pos[sym]["entry_price"]))
                    if raw is not None:
                        sell(sym, d, raw, 1.0, "NQSAR_RED")
            else:
                for sym in list(pos):
                    p = pos.get(sym)
                    if p is None:
                        continue
                    pc = px(closes, prev, sym, p["entry_price"])
                    if pc is None:
                        continue
                    p["peak"] = max(float(p["peak"]), pc)
                    stop = max(float(p["entry_price"]) * 0.92, float(p["peak"]) * 0.70)
                    raw = px(opens, d, sym, pc)
                    if raw is None:
                        continue
                    if pc <= stop:
                        sell(sym, d, raw, 1.0, "STOP")
                    elif (not p["partial_taken"]) and pc >= float(p["entry_price"]) * 1.24:
                        sell(sym, d, raw, 0.25, "PARTIAL25")

            b = float(breadth.loc[prev]) if prev in breadth.index and pd.notna(breadth.loc[prev]) else np.nan
            bull = color in ("Blue", "Green")
            base_cap = N if bull and np.isfinite(b) and b >= 60 else 4 if bull and np.isfinite(b) and b >= 50 else 0
            sv = sig.loc[prev] if prev in sig.index else pd.Series(dtype=float)
            f1 = float(sv.get("f1")) if pd.notna(sv.get("f1", np.nan)) else np.nan
            f2 = float(sv.get("f2")) if pd.notna(sv.get("f2", np.nan)) else np.nan
            f3 = float(sv.get("f3")) if pd.notna(sv.get("f3", np.nan)) else np.nan
            cap = overlay_capacity(base_cap, overlay, f1, f2, f3)
            if cap != base_cap:
                overlay_days += 1

            # Capacity reduction never trims existing holdings. It only controls vacancy fills.
            if not red and cap > 0 and len(pos) < cap:
                if ranking == "LOO_THEME30_ATTACK" and base_cap == N and peer_ctx is not None:
                    cands = loo_candidates(prev, matrices, peer_ctx, N)
                else:
                    cands = stock_candidates(prev, matrices, N)
                nav_open = cash
                for sym, p in pos.items():
                    op = px(opens, d, sym, px(closes, prev, sym, p["entry_price"]))
                    if op is not None:
                        nav_open += float(p["shares"]) * op
                slot_cash = nav_open / N
                for sym in cands:
                    if len(pos) >= cap or cash <= 1e-12:
                        break
                    if sym in pos:
                        continue
                    raw = px(opens, d, sym, px(closes, prev, sym, None))
                    if raw is None:
                        continue
                    buy = raw * (1.0 + COST_SIDE)
                    alloc = min(slot_cash, cash)
                    if alloc <= 1e-12:
                        break
                    sh = alloc / buy
                    cash -= alloc
                    pos[sym] = {
                        "shares": sh, "original_shares": sh, "entry_price": buy,
                        "entry_date": d, "peak": buy, "partial_taken": False,
                    }
                    entries += 1

        nav = cash
        for sym, p in pos.items():
            cp = px(closes, d, sym, px(opens, d, sym, p["entry_price"]))
            if cp is None:
                cp = p["entry_price"]
            p["peak"] = max(float(p["peak"]), float(cp))
            nav += float(p["shares"]) * float(cp)
        equities.append((d, nav))

    eq = pd.Series(dict(equities), dtype=float).sort_index()
    return {
        "equity": eq, "metrics": split_metrics(eq), "trades": pd.DataFrame(trades),
        "entries": entries, "partials": partials, "overlay_days": overlay_days,
        "rolling_252": base.rolling_252_stats(eq),
    }


def pack(v: dict[str, Any]) -> dict[str, Any]:
    return {"metrics": v["metrics"], "entries": v["entries"], "partials": v["partials"],
            "overlay_days": v["overlay_days"], "rolling_252": v["rolling_252"],
            "trade_count": len(v["trades"])}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--output", required=True)
    ap.add_argument("--analysis-start", default="2016-01-04")
    ap.add_argument("--analysis-end", default="2026-06-20")
    ap.add_argument("--max-tickers", type=int, default=6000)
    ap.add_argument("--batch-size", type=int, default=75)
    args = ap.parse_args()
    root = Path(args.root); out = root / args.output; out.mkdir(parents=True, exist_ok=True)

    meta, matrices = base.build_inputs(root, args.analysis_start, args.analysis_end, args.max_tickers, args.batch_size)
    sig = lc.build_leadership_series(matrices).reindex(meta["analysis_idx"])

    stock_overlays = ["NONE", "F1_TO4", "F2_TO4", "F1F2_TO4", "F1F2_STOP", "F3_TO4"]
    sims: dict[str, dict[str, Any]] = {}
    for ov in stock_overlays:
        key = f"STOCK_RS189__{ov}"
        print("SIM", key, flush=True)
        sims[key] = simulate(meta, matrices, sig, ov, "STOCK_RS189")

    print("BUILD LOO CONTEXT", flush=True)
    peer_ctx = loo.build_leave_one_out_scores(root, matrices)
    for ov in ("NONE", "F1F2_TO4", "F1F2_STOP"):
        key = f"LOO_THEME30_ATTACK__{ov}"
        print("SIM", key, flush=True)
        sims[key] = simulate(meta, matrices, sig, ov, "LOO_THEME30_ATTACK", peer_ctx)

    result: dict[str, Any] = {
        "status": "LEADERSHIP_WARNING_OVERLAY_MODERN_EXIT_AUDIT",
        "method": {
            "signal": "prior close", "execution": "next open", "cost_side": COST_SIDE,
            "exit": "close -8% initial; first +24% -> next-open 25%; remainder max(entry*.92, peak close*.70); NQSAR Red next-open",
            "entry": "daily vacancy fill; Attack 12 / Selective 4 / Stop 0; capacity downgrade never trims existing holdings",
            "ranking": "Stock RS189 isolation plus strict LOO Theme30 verification in Attack",
        },
        "coverage": {"selected": meta.get("selected"), "downloaded": meta.get("downloaded"), "sessions": len(meta["analysis_idx"])},
        "variants": {k: pack(v) for k, v in sims.items()},
        "comparisons": {},
    }

    for prefix in ("STOCK_RS189", "LOO_THEME30_ATTACK"):
        bkey = f"{prefix}__NONE"; b = sims[bkey]
        for key, v in sims.items():
            if not key.startswith(prefix + "__") or key == bkey:
                continue
            result["comparisons"][key] = {
                "full_cagr_delta": v["metrics"]["full"]["cagr"] - b["metrics"]["full"]["cagr"],
                "confirmation_cagr_delta": v["metrics"]["confirmation"]["cagr"] - b["metrics"]["confirmation"]["cagr"],
                "full_mdd_delta": v["metrics"]["full"]["mdd"] - b["metrics"]["full"]["mdd"],
                "confirmation_mdd_delta": v["metrics"]["confirmation"]["mdd"] - b["metrics"]["confirmation"]["mdd"],
                "block20_win_vs_base_full": base.bootstrap_block_win(v["equity"], b["equity"], block=20, reps=5000, seed=20260902 + len(result["comparisons"])),
                "block20_win_vs_base_confirmation": base.bootstrap_block_win(v["equity"].loc[v["equity"].index >= CONF_START], b["equity"].loc[b["equity"].index >= CONF_START], block=20, reps=5000, seed=20261902 + len(result["comparisons"])),
            }

    for k, v in sims.items():
        v["equity"].rename("equity").to_csv(out / f"equity_{k}.csv")
        v["trades"].to_csv(out / f"trades_{k}.csv", index=False)
    (out / "summary_overlay.json").write_text(json.dumps(safe(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== LEADERSHIP_OVERLAY_RESULT ===", flush=True)
    print(json.dumps(safe(result), ensure_ascii=False, indent=2), flush=True)
    print("=== END_LEADERSHIP_OVERLAY_RESULT ===", flush=True)


if __name__ == "__main__":
    main()
