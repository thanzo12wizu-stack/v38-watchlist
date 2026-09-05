from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import audit_ordinary_stock_exit_trail as ex
import audit_ordinary_stock_market_mode_robustness as base
import audit_ordinary_stock_theme_leave_one_out as loo
import audit_rotation_exit_overlays as core
import audit_rotation_exit_sensitivity as sens

SELECTIVE_SLOTS = 4
PANEL_START = pd.Timestamp("2022-04-18")
CONFIRM_START = pd.Timestamp("2024-01-01")
RECENT_START = pd.Timestamp("2025-01-01")


@dataclass(frozen=True)
class BlockVariant:
    name: str
    kind: str


VARIANTS = [
    BlockVariant("BASE", "NONE"),
    BlockVariant("BLOCK_STRONG_DETERIORATION_W10", "W10"),
    BlockVariant("BLOCK_STRONG_DETERIORATION_W20", "W20"),
    BlockVariant("BLOCK_STRONG_DETERIORATION_W20_FLOWOUT", "W20_FLOW"),
    BlockVariant("BLOCK_DISTRIBUTION_TRAP", "DIST_TRAP"),
]


def matches(st: dict[str, Any] | None, v: BlockVariant) -> bool:
    if v.kind == "NONE" or st is None:
        return False
    p = st.get("price_score", np.nan)
    i = st.get("internal_score", np.nan)
    d = st.get("internal_delta20", np.nan)
    f = st.get("flow20_pct_aum", np.nan)
    if v.kind == "DIST_TRAP":
        return bool(np.isfinite(p) and np.isfinite(i) and np.isfinite(f) and p >= 70.0 and i < 50.0 and f <= 0.0)
    threshold = -10.0 if v.kind == "W10" else -20.0
    ok = bool(np.isfinite(p) and np.isfinite(d) and p >= 70.0 and d <= threshold)
    if v.kind == "W20_FLOW":
        ok = ok and bool(np.isfinite(f) and f <= 0.0)
    return ok


def px(frame: pd.DataFrame, date: pd.Timestamp, sym: str, fallback=None):
    try:
        x = float(frame.at[date, sym])
        if np.isfinite(x) and x > 0:
            return x
    except Exception:
        pass
    return fallback


def simulate(meta, matrices, peer_ctx, state_source, v: BlockVariant):
    idx: pd.DatetimeIndex = meta["analysis_idx"]
    opens, closes = matrices["open"], matrices["close"]
    breadth, nq = meta["breadth"], meta["nq"]
    cash = 1.0
    pos: dict[str, dict[str, Any]] = {}
    equities: list[tuple[pd.Timestamp, float]] = []
    trades: list[dict[str, Any]] = []
    entries: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    red_run = 0
    coverage = {"candidate_decisions": 0, "mapped_sector": 0, "state_available": 0, "blocked_decisions": 0}

    def sell_partial(p, price: float):
        nonlocal cash
        sold = p["shares"] * 0.25
        if sold <= 0:
            return
        cash += sold * price
        p["shares"] -= sold
        p["realized_proceeds"] += sold * price
        p["partial_done"] = True

    def close_position(sym: str, date: pd.Timestamp, price: float, reason: str):
        nonlocal cash
        p = pos.pop(sym)
        final = p["shares"] * price
        cash += final
        proceeds = p["realized_proceeds"] + final
        total_ret = proceeds / p["initial_alloc"] - 1.0 if p["initial_alloc"] > 0 else np.nan
        trades.append({
            "variant": v.name,
            "symbol": sym,
            "entry_date": p["entry_date"],
            "exit_date": date,
            "entry_price": p["entry_price"],
            "exit_price": price,
            "total_return": total_ret,
            "exit_reason": reason,
            "entry_bucket": p["entry_bucket"],
        })

    for k, d0 in enumerate(idx):
        d = pd.Timestamp(d0)
        prev = None if k == 0 else pd.Timestamp(idx[k - 1])
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
                    stop = max(p["entry_price"] * 0.92, p["peak_close"] * 0.70)
                    reason = "PEAK30" if p["peak_close"] * 0.70 >= p["entry_price"] * 0.92 else "HARD8"
                    if pc <= stop:
                        opx = px(opens, d, sym, pc)
                        if opx is not None:
                            close_position(sym, d, opx, reason)
                        continue
                    if (not p["partial_done"]) and pc >= p["entry_price"] * 1.24:
                        opx = px(opens, d, sym, pc)
                        if opx is not None:
                            sell_partial(p, opx)

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

                for rank_i, (sym, c) in enumerate(candidates, start=1):
                    if len(pos) >= cap or cash <= 0:
                        break
                    if sym in pos:
                        continue
                    opx = px(opens, d, sym, px(closes, prev, sym, None))
                    if opx is None:
                        continue
                    coverage["candidate_decisions"] += 1
                    sec = state_source.sector(sym, prev)
                    if sec:
                        coverage["mapped_sector"] += 1
                    st = state_source.state(sym, prev)
                    if st is not None:
                        coverage["state_available"] += 1
                    if matches(st, v):
                        coverage["blocked_decisions"] += 1
                        blocked.append({
                            "variant": v.name,
                            "symbol": sym,
                            "signal_date": prev,
                            "would_entry_date": d,
                            "would_entry_price": opx,
                            "candidate_rank": rank_i,
                            "entry_bucket": bucket,
                            "sector": st.get("sector") if st else sec,
                            "price_score": st.get("price_score") if st else np.nan,
                            "internal_score": st.get("internal_score") if st else np.nan,
                            "internal_delta20": st.get("internal_delta20") if st else np.nan,
                            "flow20_pct_aum": st.get("flow20_pct_aum") if st else np.nan,
                        })
                        continue

                    alloc = min(slot_cash, cash)
                    if alloc <= 1e-10:
                        break
                    cash -= alloc
                    pos[sym] = {
                        "shares": alloc / opx,
                        "initial_alloc": alloc,
                        "realized_proceeds": 0.0,
                        "entry_price": opx,
                        "entry_date": d,
                        "peak_close": opx,
                        "entry_bucket": bucket,
                        "partial_done": False,
                        **c,
                    }
                    entries.append({
                        "variant": v.name,
                        "symbol": sym,
                        "signal_date": prev,
                        "entry_date": d,
                        "entry_price": opx,
                        "entry_bucket": bucket,
                        "candidate_rank": rank_i,
                    })

        nav = cash
        for sym, p in pos.items():
            cp = px(closes, d, sym, px(opens, d, sym, p["entry_price"]))
            if cp is None:
                cp = p["entry_price"]
            p["peak_close"] = max(p["peak_close"], cp)
            nav += p["shares"] * cp
        equities.append((d, nav))

    return {
        "equity": pd.Series(dict(equities), dtype=float).sort_index(),
        "trades": pd.DataFrame(trades),
        "entries": pd.DataFrame(entries),
        "blocked": pd.DataFrame(blocked),
        "coverage": coverage,
    }


def forward_block_diagnostics(blocked: pd.DataFrame, matrices, idx: pd.DatetimeIndex) -> dict[str, Any]:
    if blocked.empty:
        return {"decisions": 0, "unique20d_events": 0}
    closes = matrices["close"].reindex(idx)
    pos = {pd.Timestamp(d): i for i, d in enumerate(idx)}
    z = blocked.sort_values(["symbol", "would_entry_date"]).copy()
    keep = []
    last_by_sym: dict[str, int] = {}
    for j, r in z.iterrows():
        d = pd.Timestamp(r["would_entry_date"])
        i = pos.get(d)
        if i is None:
            continue
        sym = str(r["symbol"])
        if sym in last_by_sym and i - last_by_sym[sym] < 20:
            continue
        last_by_sym[sym] = i
        keep.append(j)
    u = z.loc[keep].copy() if keep else z.iloc[0:0].copy()
    rows = []
    for _, r in u.iterrows():
        sym = str(r["symbol"])
        d = pd.Timestamp(r["would_entry_date"])
        i = pos.get(d)
        ep = float(r["would_entry_price"])
        rec = r.to_dict()
        for h in (20, 40, 63):
            ret = np.nan
            max_up = np.nan
            if i is not None and sym in closes.columns and ep > 0:
                end = min(len(idx) - 1, i + h)
                if end > i:
                    path = pd.to_numeric(closes.iloc[i + 1:end + 1][sym], errors="coerce").dropna()
                    if len(path):
                        ret = float(path.iloc[-1] / ep - 1.0)
                        max_up = float(path.max() / ep - 1.0)
            rec[f"ret_{h}"] = ret
            rec[f"max_up_{h}"] = max_up
        rows.append(rec)
    d = pd.DataFrame(rows)
    out = {"decisions": int(len(blocked)), "unique20d_events": int(len(d))}
    for h in (20, 40, 63):
        x = pd.to_numeric(d.get(f"ret_{h}"), errors="coerce").dropna() if len(d) else pd.Series(dtype=float)
        m = pd.to_numeric(d.get(f"max_up_{h}"), errors="coerce").dropna() if len(d) else pd.Series(dtype=float)
        out[f"ret_{h}"] = {
            "n": int(len(x)),
            "mean": float(x.mean()) if len(x) else None,
            "median": float(x.median()) if len(x) else None,
            "negative_rate": float((x < 0).mean()) if len(x) else None,
        }
        out[f"max_up_{h}"] = {
            "mean": float(m.mean()) if len(m) else None,
            "ge20_rate": float((m >= 0.20).mean()) if len(m) else None,
            "ge50_rate": float((m >= 0.50).mean()) if len(m) else None,
        }
    return out


def period_metrics(eq: pd.Series) -> dict[str, Any]:
    return {
        "2022_plus": base.metrics(eq.loc[eq.index >= PANEL_START]),
        "2024_plus": base.metrics(eq.loc[eq.index >= CONFIRM_START]),
        "2025_plus": base.metrics(eq.loc[eq.index >= RECENT_START]),
    }


def boot_vs_base(eq: pd.Series, base_eq: pd.Series, start: pd.Timestamp, seed: int):
    a = eq.loc[eq.index >= start]
    b = base_eq.reindex(a.index)
    return base.bootstrap_block_win(a, b, block=20, reps=5000, seed=seed) if len(a) >= 100 else None


def run_source(label: str, state_source, meta, matrices, peer_ctx, out: Path) -> dict[str, Any]:
    sims = {}
    for j, v in enumerate(VARIANTS):
        print(f"{label} SIM {j+1}/{len(VARIANTS)} {v.name}", flush=True)
        sim = simulate(meta, matrices, peer_ctx, state_source, v)
        sims[v.name] = sim
        sim["equity"].rename("equity").to_csv(out / f"equity_{label}_{v.name}.csv")
        sim["blocked"].to_csv(out / f"blocked_{label}_{v.name}.csv", index=False)
    base_eq = sims["BASE"]["equity"]
    result = {}
    for j, v in enumerate(VARIANTS):
        sim = sims[v.name]
        item = {
            "metrics": period_metrics(sim["equity"]),
            "coverage": sim["coverage"],
            "blocked_forward": forward_block_diagnostics(sim["blocked"], matrices, meta["analysis_idx"]),
        }
        if v.name != "BASE":
            item["block20_win_probability_vs_base"] = {
                "2022_plus": boot_vs_base(sim["equity"], base_eq, PANEL_START, 510000 + j),
                "2024_plus": boot_vs_base(sim["equity"], base_eq, CONFIRM_START, 520000 + j),
                "2025_plus": boot_vs_base(sim["equity"], base_eq, RECENT_START, 530000 + j),
            }
        result[v.name] = item
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--panel", type=Path, required=True)
    ap.add_argument("--snapshots", type=Path, required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--analysis-start", default="2022-04-18")
    ap.add_argument("--analysis-end", default="2026-06-20")
    ap.add_argument("--max-tickers", type=int, default=6000)
    ap.add_argument("--batch-size", type=int, default=60)
    args = ap.parse_args()

    root = Path(args.root)
    out = root / args.output
    out.mkdir(parents=True, exist_ok=True)
    panel, snapshots = core.load_rotation(args.panel, args.snapshots)
    pit = core.PITState(panel, snapshots)
    current_map = sens.build_current_map(root / "universe.csv")
    current = sens.CurrentClassificationState(panel, current_map)
    mapper_validation = sens.latest_mapper_validation(root / "universe.csv", args.snapshots)

    meta, matrices = ex.build_inputs_ext(root, args.analysis_start, args.analysis_end, args.max_tickers, args.batch_size)
    peer_ctx = loo.build_leave_one_out_scores(root, matrices)

    strict = run_source("STRICT_PIT", pit, meta, matrices, peer_ctx, out)
    broad = run_source("BROAD_CURRENT_LOOKAHEAD", current, meta, matrices, peer_ctx, out)

    result = {
        "status": "ROTATION_NEW_ENTRY_BLOCK_RESEARCH",
        "research_only": True,
        "decision": "Does a Sector Rotation warning add value by blocking only fresh entries while leaving held leaders and all adopted exits unchanged?",
        "variants": [v.__dict__ for v in VARIANTS],
        "strict_pit": strict,
        "broad_current_classification_sensitivity": broad,
        "current_mapper_validation": mapper_validation,
        "guardrails": [
            "Existing holdings are never sold, trimmed, or trail-tightened by Rotation.",
            "Entry eligibility, ranking, market mode, and adopted V38 exits are unchanged; only a candidate can be skipped when its Sector warning is active.",
            "Strict PIT is primary evidence but only covers contemporaneous S&P500 historical sector membership.",
            "Broad current-classification mapping is look-ahead sensitivity only and cannot establish a production rule.",
            "Blocked-candidate forward returns are deduplicated with a 20-session symbol cooldown for diagnostics.",
        ],
    }
    (out / "summary_rotation_new_entry_block.json").write_text(json.dumps(core.safe(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== ROTATION_NEW_ENTRY_BLOCK_JSON ===", flush=True)
    print(json.dumps(core.safe(result), ensure_ascii=False, indent=2), flush=True)
    print("=== END_ROTATION_NEW_ENTRY_BLOCK_JSON ===", flush=True)


if __name__ == "__main__":
    main()
