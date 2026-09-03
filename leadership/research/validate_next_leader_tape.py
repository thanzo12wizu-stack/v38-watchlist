from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import validate_dynamic_pioneer_followthrough as dpf

HORIZONS = (5, 10, 20)


def safe(v: Any) -> Any:
    if isinstance(v, dict):
        return {str(k): safe(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [safe(x) for x in v]
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, (np.floating, float)):
        x = float(v)
        return x if math.isfinite(x) else None
    return v


def score_rows(hidden: pd.DataFrame) -> pd.DataFrame:
    out = hidden.copy()
    # Frozen before tranche-2/tranche-3 evaluation. These are rounded, simple
    # tape/price conditions whose direction agreed in discovery, 2022+ and the
    # previously recovered ticker-disjoint holdout. No Industry acceleration or
    # past-leader memory is used.
    conds = {
        "close_location_ok": pd.to_numeric(out["close_location"], errors="coerce") >= 0.50,
        "signed_rvol_ok": pd.to_numeric(out["signed_rvol20"], errors="coerce") > 0.0,
        "ema21_impulse_ok": pd.to_numeric(out["ema21_atr"], errors="coerce") >= 0.60,
        "near_high_ok": pd.to_numeric(out["dist_prior_high20"], errors="coerce") >= -0.10,
    }
    for k, c in conds.items():
        out[k] = c.fillna(False)
    out["tape_score4"] = sum(out[k].astype(int) for k in conds)
    return out


def group_summary(rows: pd.DataFrame, mask: pd.Series, seed: int) -> dict[str, Any]:
    use = rows.loc[mask].copy()
    out: dict[str, Any] = {"rows": int(len(use)), "dates": int(use["entry_date"].nunique()) if len(use) else 0, "themes": int(use["theme"].nunique()) if len(use) else 0}
    for h in HORIZONS:
        out[str(h)] = dpf.summarize(use, h, seed + h)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--output", required=True)
    ap.add_argument("--analysis-start", default="2016-01-04")
    ap.add_argument("--analysis-end", default="2026-06-20")
    ap.add_argument("--exclude-first", type=int, default=0)
    ap.add_argument("--max-tickers", type=int, default=1500)
    ap.add_argument("--batch-size", type=int, default=75)
    ap.add_argument("--min-members", type=int, default=3)
    args = ap.parse_args()

    root = Path(args.root)
    out = root / args.output
    out.mkdir(parents=True, exist_ok=True)
    capture = out / "_enriched_rows.csv.gz"
    tmp = out / "_dynamic_tmp"

    original = dpf.iq.enrich_rows
    def capture_enrich(rows, matrices, theme_members):
        enriched = original(rows, matrices, theme_members)
        enriched.to_csv(capture, index=False, compression="gzip")
        return enriched
    dpf.iq.enrich_rows = capture_enrich
    old_argv = sys.argv[:]
    try:
        sys.argv = [
            "validate_dynamic_pioneer_followthrough.py",
            "--root", str(root), "--output", str(tmp.relative_to(root)),
            "--analysis-start", args.analysis_start, "--analysis-end", args.analysis_end,
            "--exclude-first", str(args.exclude_first), "--max-tickers", str(args.max_tickers),
            "--batch-size", str(args.batch_size), "--min-members", str(args.min_members),
        ]
        dpf.main()
    finally:
        sys.argv = old_argv
        dpf.iq.enrich_rows = original

    rows = pd.read_csv(capture, parse_dates=["entry_date"])
    hidden = rows[
        rows["continuous_momentum"].fillna(False).astype(bool)
        & (pd.to_numeric(rows["dist_prior_high20"], errors="coerce") <= dpf.HIDDEN_HIGH_GAP)
        & (pd.to_numeric(rows["industry_rs"], errors="coerce") < dpf.INDUSTRY_MAX)
    ].copy()
    hidden = score_rows(hidden)

    result: dict[str, Any] = {
        "status": "NEXT_LEADER_TAPE_FROZEN_TRANCHE_VALIDATION",
        "purpose": "Test whether ignition-day price/tape quality selects stronger future leaders without waiting for breakout/follow-through.",
        "base_hidden_ignition": "continuous Subtheme Momentum + new within-theme RS21 top-third ignition + >=5% below prior 20d intraday high + Industry RS<80",
        "frozen_tape4": {
            "close_location_min": 0.50,
            "signed_rvol20_min_exclusive": 0.0,
            "ema21_atr_min": 0.60,
            "dist_prior_high20_min": -0.10,
            "note": "Industry acceleration and past-leader memory intentionally excluded after failed replication.",
        },
        "coverage": {"exclude_first": args.exclude_first, "hidden_rows": int(len(hidden)), "dates": int(hidden.entry_date.nunique()), "themes": int(hidden.theme.nunique())},
        "all": group_summary(hidden, pd.Series(True, index=hidden.index), 51000),
        "score3plus": group_summary(hidden, hidden["tape_score4"] >= 3, 52000),
        "score4": group_summary(hidden, hidden["tape_score4"] == 4, 53000),
        "score_buckets": {str(i): group_summary(hidden, hidden["tape_score4"] == i, 54000 + i * 100) for i in range(5)},
        "confirmation_2022_plus": {
            "all": group_summary(hidden, hidden["entry_date"] >= pd.Timestamp("2022-01-01"), 55000),
            "score3plus": group_summary(hidden, (hidden["entry_date"] >= pd.Timestamp("2022-01-01")) & (hidden["tape_score4"] >= 3), 56000),
            "score4": group_summary(hidden, (hidden["entry_date"] >= pd.Timestamp("2022-01-01")) & (hidden["tape_score4"] == 4), 57000),
        },
    }
    hidden.to_csv(out / "next_leader_tape_rows.csv.gz", index=False, compression="gzip")
    (out / "summary.json").write_text(json.dumps(safe(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print("===NEXT_LEADER_TAPE===", flush=True)
    print(json.dumps(safe(result), ensure_ascii=False, separators=(",", ":")), flush=True)
    print("===END===", flush=True)


if __name__ == "__main__":
    main()
