from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

import audit_gross100_component_series as old
import audit_ordinary_stock_exit_trail as ex
import audit_ordinary_stock_theme_leave_one_out as loo

FINAL_RESET_RULE = "RS63_TOP3_RISE30_SIGTOP3"
LIQUIDITY_FLOORS = (10_000_000.0, 20_000_000.0, 50_000_000.0, 100_000_000.0)


def _truthy(s: pd.Series) -> pd.Series:
    if s.dtype == bool:
        return s.fillna(False)
    return s.astype(str).str.strip().str.lower().isin({"true", "1", "yes"})


def prepare_final_reset_trades(path: Path, calendar: pd.DatetimeIndex, columns: pd.Index) -> pd.DataFrame:
    t = pd.read_csv(path, compression="gzip", parse_dates=["day0_date", "signal_date", "entry_date"])
    required = {"kind", "threshold", "RS63_TOP3", "signal_top3", "rank63", "rsi_signal", "theme", "symbol"}
    missing = sorted(required - set(t.columns))
    if missing:
        raise RuntimeError(f"strict Reset artifact missing columns: {missing}")
    use = t[
        t["kind"].astype(str).str.upper().eq("RISE")
        & pd.to_numeric(t["threshold"], errors="coerce").eq(30)
        & _truthy(t["RS63_TOP3"])
        & _truthy(t["signal_top3"])
    ].copy()
    use["rank_priority"] = pd.to_numeric(use["rank63"], errors="coerce").fillna(99.0)
    use = use.sort_values(["day0_date", "theme", "symbol", "rank_priority", "signal_date"]).drop_duplicates(
        ["day0_date", "theme", "symbol"], keep="first"
    )
    use = use[use["entry_date"].isin(calendar) & use["symbol"].isin(columns)].copy()
    return use


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

    meta, matrices = ex.build_inputs_ext(root, args.analysis_start, args.analysis_end, args.max_tickers, args.batch_size)
    print("BUILD leave-one-out theme context", flush=True)
    peer_ctx = loo.build_leave_one_out_scores(root, matrices)

    ordinary_by_floor: dict[int, pd.DataFrame] = {}
    for floor in LIQUIDITY_FLOORS:
        label = int(floor / 1_000_000)
        print(f"SIM ordinary DDV>={label}M", flush=True)
        ordinary = old.simulate_ordinary(meta, matrices, peer_ctx, liquidity_floor=floor)
        ordinary_by_floor[label] = ordinary
        ordinary.to_csv(
            out / f"ordinary_PEAK30_PART25_R3_DDV{label}M_daily.csv.gz",
            index=False,
            compression="gzip",
        )

    # Preserve the historical filename as an exact DDV10 baseline alias.
    ordinary_by_floor[10].to_csv(
        out / "ordinary_PEAK30_PART25_R3_daily.csv.gz", index=False, compression="gzip"
    )

    cal = pd.DatetimeIndex(meta["analysis_idx"])
    reset_trades = prepare_final_reset_trades(Path(args.reset_trades), cal, matrices["close"].columns)
    reset, reset_turnover = old.simulate_reset(cal, matrices["open"], matrices["close"], reset_trades)
    reset.to_csv(out / "rsi_RESET_RISE30_S029_P4_H20_daily.csv.gz", index=False, compression="gzip")

    summary = {
        "status": "GROSS100_FINAL_RESET_LIQUIDITY_COMPONENT_RECHECK",
        "reset_rule": FINAL_RESET_RULE,
        "liquidity_floor_definition": "ranking universe remains adopted DDV>=10M; higher floors only block lower-DDV new entries and allow next-ranked liquid candidates; no forced liquidity exit",
        "liquidity_floors": list(ordinary_by_floor),
        "analysis_start": str(pd.Timestamp(ordinary_by_floor[10].date.min()).date()),
        "analysis_end": str(pd.Timestamp(ordinary_by_floor[10].date.max()).date()),
        "days": int(len(ordinary_by_floor[10])),
        "ordinary": {
            str(k): {
                "avg_gross": float(v.gross_exposure.mean()),
                "max_gross": float(v.gross_exposure.max()),
                "avg_positions": float(v.positions.mean()),
                "fill_allowed_days": int(v.selective_fill_allowed.astype(bool).sum()),
            }
            for k, v in ordinary_by_floor.items()
        },
        "reset_avg_gross": float(reset.gross_exposure.mean()),
        "reset_max_gross": float(reset.gross_exposure.max()),
        "reset_max_positions": int(reset.positions.max()),
        "reset_trades_input": int(len(reset_trades)),
        "reset_turnover_value": float(reset_turnover),
        "guardrail": "Normal mechanics unchanged except entry-only DDV sensitivity; final reproducible Reset input unchanged.",
    }
    (out / "component_recheck_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
