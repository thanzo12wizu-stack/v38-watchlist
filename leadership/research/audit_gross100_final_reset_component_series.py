from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

import audit_gross100_component_series as old
import audit_ordinary_stock_exit_trail as ex
import audit_ordinary_stock_theme_leave_one_out as loo

FINAL_RESET_RULE = "RS63_TOP3_RISE30_SIGTOP3"


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
    ordinary = old.simulate_ordinary(meta, matrices, peer_ctx)

    cal = pd.DatetimeIndex(meta["analysis_idx"])
    reset_trades = prepare_final_reset_trades(Path(args.reset_trades), cal, matrices["close"].columns)
    reset, reset_turnover = old.simulate_reset(cal, matrices["open"], matrices["close"], reset_trades)

    ordinary.to_csv(out / "ordinary_PEAK30_PART25_R3_daily.csv.gz", index=False, compression="gzip")
    reset.to_csv(out / "rsi_RESET_RISE30_S029_P4_H20_daily.csv.gz", index=False, compression="gzip")
    summary = {
        "status": "GROSS100_FINAL_RESET_COMPONENT_RECHECK",
        "reset_rule": FINAL_RESET_RULE,
        "analysis_start": str(pd.Timestamp(ordinary.date.min()).date()),
        "analysis_end": str(pd.Timestamp(ordinary.date.max()).date()),
        "days": int(len(ordinary)),
        "ordinary_avg_gross": float(ordinary.gross_exposure.mean()),
        "ordinary_max_gross": float(ordinary.gross_exposure.max()),
        "reset_avg_gross": float(reset.gross_exposure.mean()),
        "reset_max_gross": float(reset.gross_exposure.max()),
        "reset_max_positions": int(reset.positions.max()),
        "reset_trades_input": int(len(reset_trades)),
        "reset_turnover_value": float(reset_turnover),
        "guardrail": "Normal sleeve mechanics unchanged; only Reset input changed from legacy broad RISE_LE30_W20 to final reproducible RS63_TOP3_RISE30_SIGTOP3.",
    }
    (out / "component_recheck_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
