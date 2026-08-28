from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

import audit_ordinary_stock_market_mode_robustness as base

ANCHORS = (pd.Timestamp("2026-07-13"), pd.Timestamp("2019-01-14"))
SLOTS = (0, 3, 4, 5, 6, 7, 8)


def yearly_mode_occupancy(meta: dict) -> dict:
    idx = meta["analysis_idx"]
    breadth = meta["breadth"].reindex(idx)
    nq = meta["nq"].reindex(idx)
    rows = []
    for d in idx:
        color = str(nq.at[d, "nq_color"]) if d in nq.index and pd.notna(nq.at[d, "nq_color"]) else "Missing"
        b = float(breadth.loc[d]) if d in breadth.index and pd.notna(breadth.loc[d]) else np.nan
        bucket = base.breadth_bucket(b)
        if color == "Red":
            mode = "RED"
        elif color == "Yellow":
            mode = "YELLOW"
        elif color in ("Blue", "Green") and bucket == 2:
            mode = "ATTACK"
        elif color in ("Blue", "Green") and bucket == 1:
            mode = "SELECTIVE"
        elif color in ("Blue", "Green") and bucket == 0:
            mode = "BREADTH_STOP"
        else:
            mode = "MISSING"
        rows.append((d, color, b, mode))
    df = pd.DataFrame(rows, columns=["date", "color", "breadth", "mode"]).set_index("date")
    out = {}
    for y, g in df.groupby(df.index.year):
        out[str(y)] = {
            "sessions": int(len(g)),
            "color_counts": {str(k): int(v) for k, v in g["color"].value_counts().to_dict().items()},
            "mode_counts": {str(k): int(v) for k, v in g["mode"].value_counts().to_dict().items()},
            "breadth_mean": float(g["breadth"].mean()) if g["breadth"].notna().any() else None,
        }
    return out


def marginal_selective_stats(trades: pd.DataFrame) -> dict:
    if trades is None or trades.empty or "entry_bucket" not in trades:
        return {"n": 0}
    s = trades.loc[trades["entry_bucket"] == 1].copy()
    if s.empty:
        return {"n": 0}
    r = pd.to_numeric(s["return"], errors="coerce").dropna()
    return {
        "n": int(len(r)),
        "mean": float(r.mean()) if len(r) else None,
        "median": float(r.median()) if len(r) else None,
        "win_rate": float((r > 0).mean()) if len(r) else None,
        "p10": float(r.quantile(0.10)) if len(r) else None,
        "p90": float(r.quantile(0.90)) if len(r) else None,
        "years": {
            str(int(y)): {
                "n": int(len(g)),
                "mean": float(pd.to_numeric(g["return"], errors="coerce").mean()),
                "median": float(pd.to_numeric(g["return"], errors="coerce").median()),
            }
            for y, g in s.groupby(pd.to_datetime(s["entry_date"]).dt.year)
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
    result = {
        "status": "ORDINARY_STOCK_REBALANCE_PHASE_AUDIT",
        "scope": "ordinary individual stocks only",
        "coverage": {
            "selected": meta["selected"],
            "downloaded": meta["downloaded"],
            "analysis_sessions": int(len(meta["analysis_idx"])),
            "download": meta["download"],
        },
        "yearly_market_mode_occupancy": yearly_mode_occupancy(meta),
        "anchors": {},
    }

    for anchor in ANCHORS:
        base.REBAL_ANCHOR = anchor
        mm = dict(meta)
        mm["rebalance"] = base.build_rebalance_flags(matrices["close"].index)
        akey = anchor.strftime("%Y-%m-%d")
        sims = {}
        for slots in SLOTS:
            print(f"ANCHOR {akey} SLOTS {slots}", flush=True)
            sims[slots] = base.simulate(mm, matrices, selective_slots=slots, red_confirm_sessions=1, immediate_red_recovery=True)
        b4 = sims[4]
        ad = {
            "calibration_4slot": base.calibration_check(b4),
            "variants": {},
        }
        for slots in SLOTS:
            sim = sims[slots]
            ad["variants"][str(slots)] = {
                "metrics": sim["metrics"],
                "rolling252": base.rolling_252_stats(sim["equity"]),
                "trade_count": sim["trade_count"],
                "selective_trades": marginal_selective_stats(sim["trades"]),
                "vs_4slot_block20_win_prob": None if slots == 4 else base.bootstrap_block_win(
                    sim["equity"], b4["equity"], block=20, reps=2000, seed=20260829 + slots * 31
                ),
            }
        result["anchors"][akey] = ad

    # Rank the two phases by distance from the previously reported reconstruction.
    dist = {}
    for akey, ad in result["anchors"].items():
        cal = ad["calibration_4slot"]
        delta = cal["delta"]
        score = 0.0
        used = 0
        for k, tol in cal["tolerance"].items():
            if delta.get(k) is not None:
                score += abs(float(delta[k])) / float(tol)
                used += 1
        dist[akey] = score / max(1, used)
    result["calibration_distance_normalized"] = dist

    (out / "summary_phase.json").write_text(json.dumps(base.safe(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== ORDINARY_STOCK_PHASE_RESULT_JSON ===", flush=True)
    print(json.dumps(base.safe(result), ensure_ascii=False, indent=2), flush=True)
    print("=== END_ORDINARY_STOCK_PHASE_RESULT_JSON ===", flush=True)


if __name__ == "__main__":
    main()
