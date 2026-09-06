from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

NORMAL_CAP = 0.70
TQQQ_PROTECT_CAP = 0.80


def _alloc(native_t: float, ordinary_gross: float, reset_gross: float, fill_allowed: bool) -> tuple[float, float, float]:
    """Exact Gross100 priority used by the research allocation engine.

    Reset -> protected/native TQQQ -> Normal -> native TQQQ extra, then
    SELECTIVE_FILL_NO_ZERO_OVERRIDE fills unused gross with TQQQ only when
    native TQQQ is already >0 and normal-stock fill is allowed.
    """
    t = max(float(native_t), 0.0)
    o = min(max(float(ordinary_gross), 0.0), NORMAL_CAP)
    r = max(float(reset_gross), 0.0)

    rem = 1.0
    ar = min(r, rem)
    rem -= ar
    at = min(t, TQQQ_PROTECT_CAP, rem)
    rem -= at
    ao = min(o, rem)
    rem -= ao
    at += min(max(t - at, 0.0), rem)
    rem = max(0.0, 1.0 - (at + ao + ar))
    if fill_allowed and t > 1e-12:
        at += rem
    return at, ao, ar


def _load_trace(path: Path) -> list[dict]:
    x = json.loads(path.read_text())
    if not isinstance(x, list):
        raise RuntimeError(f"{path} is not a trace list")
    return x


def _metrics(label: str, trace: list[dict], reset_trace: list[dict], ordinary: pd.DataFrame, tq: pd.DataFrame) -> dict:
    if len(trace) != len(reset_trace):
        raise RuntimeError(f"trace length mismatch {label}: {len(trace)} vs {len(reset_trace)}")

    dates = pd.DatetimeIndex(pd.to_datetime([x["date"] for x in trace]))
    ordinary = ordinary.copy()
    ordinary["date"] = pd.to_datetime(ordinary["date"])
    ordinary = ordinary.set_index("date").reindex(dates)
    tq = tq.copy()
    tq["date"] = pd.to_datetime(tq["date"])
    tq = tq.set_index("date").reindex(dates)

    # Same causal target convention as remote_audit.py: target decided one
    # session earlier for the open-to-open holding interval.
    native = pd.to_numeric(tq["target_M30_TOUCH30_F80_D10"], errors="coerce").shift(1).fillna(0.0)

    rows = []
    zero_funded_ordinary = 0
    zero_funded_reset = 0
    gross_violations = 0
    positive_virtual_positions_zero_weight = 0
    ordinary_scale = []
    reset_scale = []

    for i, d in enumerate(dates):
        ow = {str(s): float(w) for s, w, _layer, _miss in trace[i].get("positions", []) if float(w) > 0}
        rw = {str(s): float(w) for s, w, _layer, _miss in reset_trace[i].get("positions", []) if float(w) > 0}
        go = float(sum(ow.values()))
        gr = float(sum(rw.values()))
        fill_allowed = bool(ordinary.at[d, "selective_fill_allowed"]) if d in ordinary.index and pd.notna(ordinary.at[d, "selective_fill_allowed"]) else False
        at, ao, ar = _alloc(float(native.loc[d]), go, gr, fill_allowed)
        gross = at + ao + ar
        if gross > 1.0 + 1e-10:
            gross_violations += 1

        so = ao / go if go > 1e-12 else np.nan
        sr = ar / gr if gr > 1e-12 else np.nan
        if np.isfinite(so):
            ordinary_scale.append(so)
            if ao <= 1e-12:
                zero_funded_ordinary += 1
            positive_virtual_positions_zero_weight += sum(1 for _s, w in ow.items() if w * so <= 1e-12)
        if np.isfinite(sr):
            reset_scale.append(sr)
            if ar <= 1e-12:
                zero_funded_reset += 1

        rows.append({
            "date": str(d.date()),
            "native_tqqq": float(native.loc[d]),
            "virtual_ordinary_gross": go,
            "virtual_reset_gross": gr,
            "actual_tqqq": at,
            "actual_ordinary": ao,
            "actual_reset": ar,
            "ordinary_scale": so if np.isfinite(so) else None,
            "reset_scale": sr if np.isfinite(sr) else None,
            "gross": gross,
            "ordinary_positions": len(ow),
            "reset_positions": len(rw),
            "fill_allowed": fill_allowed,
        })

    os = np.asarray(ordinary_scale, float)
    rs = np.asarray(reset_scale, float)
    out = {
        "variant": label,
        "dates": int(len(dates)),
        "days_with_ordinary_positions": int(len(os)),
        "days_with_reset_positions": int(len(rs)),
        "zero_funded_ordinary_days": int(zero_funded_ordinary),
        "zero_funded_reset_days": int(zero_funded_reset),
        "positive_virtual_positions_zero_actual_weight": int(positive_virtual_positions_zero_weight),
        "gross_violations": int(gross_violations),
        "ordinary_scale_min": float(os.min()) if len(os) else None,
        "ordinary_scale_p01": float(np.quantile(os, 0.01)) if len(os) else None,
        "ordinary_scale_p05": float(np.quantile(os, 0.05)) if len(os) else None,
        "ordinary_scale_median": float(np.median(os)) if len(os) else None,
        "ordinary_scale_lt_1_days": int((os < 1.0 - 1e-10).sum()) if len(os) else 0,
        "reset_scale_min": float(rs.min()) if len(rs) else None,
        "reset_scale_median": float(np.median(rs)) if len(rs) else None,
        "max_total_gross": float(max(x["gross"] for x in rows)) if rows else None,
        "funding_state_invariant_pass": bool(
            zero_funded_ordinary == 0
            and zero_funded_reset == 0
            and positive_virtual_positions_zero_weight == 0
            and gross_violations == 0
        ),
        "interpretation": (
            "If PASS, every virtual Core/Early and Reset holding retains positive funded weight under Gross100 priority. "
            "Because Core/Early state transitions use prices, age, sleeve/slot counts, partial flags and promotion rather than dollar NAV, "
            "proportional funding cannot change the held-symbol state in the fractional-share research model. This does not model whole-share rounding or broker microstructure."
        ),
    }
    return out, rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", required=True)
    ap.add_argument("--tqqq-daily", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    results = Path(args.results)
    outdir = Path(args.output)
    outdir.mkdir(parents=True, exist_ok=True)
    reset_trace = _load_trace(results / "trace_reset.json")
    tq = pd.read_csv(args.tqqq_daily, compression="gzip")

    summary = []
    for label in ("EARLY1", "EARLY0"):
        trace = _load_trace(results / f"trace_{label}.json")
        ordinary = pd.read_csv(results / f"ordinary_{label}.csv.gz", compression="gzip")
        s, rows = _metrics(label, trace, reset_trace, ordinary, tq)
        summary.append(s)
        pd.DataFrame(rows).to_csv(outdir / f"funding_daily_{label}.csv.gz", index=False, compression="gzip")

    report = {
        "status": "CANONICAL_FUNDING_INVARIANT_AUDIT",
        "allocation": "Reset -> protected TQQQ (<=80%) -> Ordinary (<=70%) -> TQQQ extra; selective-fill only if native TQQQ >0",
        "variants": summary,
        "all_pass": bool(all(x["funding_state_invariant_pass"] for x in summary)),
    }
    (outdir / "funding_invariant.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print("CANONICAL_FUNDING_JSON", json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
