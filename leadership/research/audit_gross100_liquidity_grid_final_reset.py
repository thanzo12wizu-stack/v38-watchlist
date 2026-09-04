from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

import audit_gross100_component_series as comp
import audit_gross100_final_reset_component_series as final_reset
import audit_ordinary_stock_exit_trail as ex
import audit_ordinary_stock_theme_leave_one_out as loo


LIQUIDITY_FLOORS = (10_000_000.0, 20_000_000.0, 50_000_000.0, 100_000_000.0)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--reset-trades", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--analysis-start", default="2016-01-04")
    ap.add_argument("--analysis-end", default="2026-03-20")
    ap.add_argument("--max-tickers", type=int, default=6000)
    ap.add_argument("--batch-size", type=int, default=75)
    args = ap.parse_args()

    root = Path(args.root)
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    print("BUILD INPUTS ONCE", flush=True)
    meta, matrices = ex.build_inputs_ext(
        root,
        args.analysis_start,
        args.analysis_end,
        args.max_tickers,
        args.batch_size,
    )
    print("BUILD LOO THEME CONTEXT ONCE", flush=True)
    peer_ctx = loo.build_leave_one_out_scores(root, matrices)

    cal = pd.DatetimeIndex(meta["analysis_idx"])
    reset_trades = final_reset.prepare_final_reset_trades(
        Path(args.reset_trades), cal, matrices["close"].columns
    )
    reset, reset_turnover = comp.simulate_reset(
        cal, matrices["open"], matrices["close"], reset_trades
    )
    reset_path = out / "rsi_RESET_RISE30_S029_P4_H20_daily.csv.gz"
    reset.to_csv(reset_path, index=False, compression="gzip")

    floors_summary = {}
    for floor in LIQUIDITY_FLOORS:
        label = int(round(floor / 1_000_000.0))
        print(f"SIM ORDINARY DDV{label}M", flush=True)
        ordinary = comp.simulate_ordinary(
            meta, matrices, peer_ctx, liquidity_floor=floor
        )
        p = out / f"ordinary_PEAK30_PART25_R3_DDV{label}M_daily.csv.gz"
        ordinary.to_csv(p, index=False, compression="gzip")
        floors_summary[str(label)] = {
            "floor": float(floor),
            "days": int(len(ordinary)),
            "start": str(pd.Timestamp(ordinary.date.min()).date()),
            "end": str(pd.Timestamp(ordinary.date.max()).date()),
            "avg_gross": float(ordinary.gross_exposure.mean()),
            "max_gross": float(ordinary.gross_exposure.max()),
            "avg_positions": float(ordinary.positions.mean()),
            "max_positions": int(ordinary.positions.max()),
        }

    summary = {
        "status": "GROSS100_FINAL_RESET_LIQUIDITY_GRID_COMPONENTS",
        "scope": "research only; no main/UI/live changes",
        "ordinary_rule": "PEAK30_PART25_R3 with entry-only DDV floor; ranking depth remains adopted Top12 and does not backfill rank13+",
        "reset_rule": final_reset.FINAL_RESET_RULE,
        "liquidity_floors_m": [10, 20, 50, 100],
        "floors": floors_summary,
        "reset": {
            "days": int(len(reset)),
            "avg_gross": float(reset.gross_exposure.mean()),
            "max_gross": float(reset.gross_exposure.max()),
            "max_positions": int(reset.positions.max()),
            "trades_input": int(len(reset_trades)),
            "turnover_value": float(reset_turnover),
        },
        "guardrails": [
            "Only new-entry DDV floor changes across ordinary variants.",
            "Existing positions are not sold because DDV later falls.",
            "RSI30 Reset signal set is identical across all DDV variants.",
            "TQQQ is not rebuilt here; frozen audited Stage56 series is used by the downstream Gross100 allocation audit.",
        ],
    }
    (out / "component_liquidity_grid_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
