from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import validate_unique_stock_edge as ue


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
    if isinstance(v, pd.Timestamp):
        return v.isoformat()
    return v


def flow_summary(frame: pd.DataFrame, seed: int) -> dict[str, Any]:
    x = pd.to_numeric(frame["flow_share_ratio_5v20"], errors="coerce")
    valid = x.notna()
    result: dict[str, Any] = {
        "n": int(len(frame)),
        "dates": int(frame["entry_date"].nunique()) if len(frame) else 0,
        "themes": int(frame["theme"].nunique()) if len(frame) else 0,
        "valid_flow": int(valid.sum()),
    }
    if valid.sum() >= 30:
        q33, q67 = x.loc[valid].quantile([1 / 3, 2 / 3])
        result["continuous_top_vs_bottom_third"] = {
            "q33": float(q33),
            "q67": float(q67),
            **ue.group_summary(frame, valid & (x >= q67), valid & (x <= q33), seed),
        }
    for label, threshold in (("FLOW_ACCEL_1P50_PRIMARY", 1.50), ("FLOW_ACCEL_1P25_SENSITIVITY", 1.25)):
        hi = valid & (x >= threshold)
        lo = valid & (x < threshold)
        result[label] = ue.group_summary(frame, hi, lo, seed + int(threshold * 1000))
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", required=True)
    ap.add_argument("--base-summary", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    rows = pd.read_csv(args.rows)
    rows["entry_date"] = pd.to_datetime(rows["entry_date"], errors="coerce")
    base = json.loads(Path(args.base_summary).read_text(encoding="utf-8"))

    hidden = (
        (pd.to_numeric(rows["dist_prior_high20"], errors="coerce") <= -0.05)
        & (pd.to_numeric(rows["industry_rs"], errors="coerce") < 80)
    )

    periods = {
        "FULL_2016_2026H1": rows["entry_date"].between("2016-01-04", "2026-06-20", inclusive="both"),
        "EARLY_2016_2021": rows["entry_date"].between("2016-01-04", "2021-12-31", inclusive="both"),
        "LATE_2022_2026H1": rows["entry_date"].between("2022-01-01", "2026-06-20", inclusive="both"),
    }

    result: dict[str, Any] = {
        "status": "PRELIMINARY_FIXED_CURRENT_TAXONOMY_FULL_UNIVERSE_STABILITY",
        "interpretation_note": (
            "The full-universe run is a precision/canonical-denominator check, not a fresh independent holdout, "
            "because the factor was selected after earlier 2016-2026 research. The time split is temporal stability only."
        ),
        "primary_rule": "5d mean theme dollar-volume share / prior20d mean share >= 1.50",
        "sensitivity_rule": ">= 1.25",
        "base_coverage": base.get("coverage", {}),
        "base_download": base.get("download", {}),
        "taxonomy_candidates": base.get("taxonomy_candidates", []),
        "periods": {},
    }

    for i, (period, pmask) in enumerate(periods.items()):
        all_frame = rows.loc[pmask].copy()
        hidden_frame = rows.loc[pmask & hidden].copy()
        result["periods"][period] = {
            "ALL_CONTINUOUS": flow_summary(all_frame, 91000 + i * 10000),
            "HIDDEN_IGNITION": flow_summary(hidden_frame, 96000 + i * 10000),
        }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(safe(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== FULL_UNIVERSE_STABILITY_JSON ===", flush=True)
    print(json.dumps(safe(result), ensure_ascii=False, indent=2), flush=True)
    print("=== END_FULL_UNIVERSE_STABILITY_JSON ===", flush=True)


if __name__ == "__main__":
    main()
