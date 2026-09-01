from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from audit_tqqq_attack_fill import (
    COST_BPS,
    TARGET_COL,
    TAX_RATE,
    annual_net_tax_proxy,
    metrics,
    monthly_stats,
    period_slices,
    rolling_2y,
    scaled_returns,
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--components-dir", required=True)
    ap.add_argument("--tqqq-daily", required=True)
    ap.add_argument("--prior-audit-dir", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    comp = Path(args.components_dir)
    ordinary = pd.read_csv(comp / "ordinary_PEAK30_PART25_R3_daily.csv.gz", compression="gzip")
    reset = pd.read_csv(comp / "rsi_RESET_RISE30_S029_P4_H20_daily.csv.gz", compression="gzip")
    tq = pd.read_csv(args.tqqq_daily, compression="gzip")
    prior = Path(args.prior_audit_dir)
    base_daily = pd.read_csv(prior / "daily_base.csv.gz", compression="gzip")
    gate_daily = pd.read_csv(prior / "daily_attack_selective_fill.csv.gz", compression="gzip")
    for x in (ordinary, reset, tq, base_daily, gate_daily):
        x["date"] = pd.to_datetime(x["date"]).dt.normalize()

    d = ordinary.merge(reset, on="date", suffixes=("_ord", "_rsi")).merge(tq, on="date", how="inner")
    d = d.merge(
        base_daily[["date", "alloc_tqqq", "alloc_ordinary", "alloc_reset", "total_gross"]].rename(
            columns={
                "alloc_tqqq": "base_alloc_tqqq",
                "alloc_ordinary": "base_alloc_ordinary",
                "alloc_reset": "base_alloc_reset",
                "total_gross": "base_total_gross",
            }
        ),
        on="date",
        how="inner",
        validate="one_to_one",
    )
    d = d.merge(
        gate_daily[["date", "gate_attack_or_selective", "base_residual_cash", "breadth_prev_close", "nqsar_prev_close"]],
        on="date",
        how="inner",
        validate="one_to_one",
    )
    d = d.sort_values("date").reset_index(drop=True)
    if TARGET_COL not in d.columns:
        raise KeyError(TARGET_COL)

    n = len(d)
    target = d[TARGET_COL].to_numpy(float)
    eff_t = np.zeros(n, float)
    eff_t[2:] = target[:-2]  # exact prior Gross100 convention

    ret_t = d["tqqq_ret_usd"].to_numpy(float)
    ret_o = d["return_ord"].to_numpy(float)
    ret_r = d["return_rsi"].to_numpy(float)
    desired_o = d["gross_exposure_ord"].to_numpy(float)
    desired_r = d["gross_exposure_rsi"].to_numpy(float)
    base = np.column_stack([
        d["base_alloc_tqqq"].to_numpy(float),
        d["base_alloc_ordinary"].to_numpy(float),
        d["base_alloc_reset"].to_numpy(float),
    ])
    residual = d["base_residual_cash"].to_numpy(float)
    gate_sel = d["gate_attack_or_selective"].astype(bool).to_numpy()

    masks = {
        "SELECTIVE_FILL_RAW": gate_sel,
        "SELECTIVE_FILL_NO_ZERO_OVERRIDE": gate_sel & (eff_t > 1e-12),
        "SELECTIVE_FILL_T30_ONLY": gate_sel & np.isclose(eff_t, 0.30, atol=1e-12),
    }

    variants = {"BASE": base.copy()}
    for name, m in masks.items():
        a = base.copy()
        a[:, 0] += residual * m.astype(float)
        variants[name] = a

    for name, a in variants.items():
        if float(a.sum(axis=1).max()) > 1.0 + 1e-9:
            raise RuntimeError(f"Gross100 violated: {name} {a.sum(axis=1).max()}")
        if np.any(a[:, 1] + 1e-12 < base[:, 1]) or np.any(a[:, 2] + 1e-12 < base[:, 2]):
            raise RuntimeError(f"stock/reset displacement detected: {name}")

    result = {
        "status": "TQQQ_SELECTIVE_FILL_LOCK_GUARD_AUDIT",
        "coverage": {
            "start": str(d.date.min().date()),
            "end": str(d.date.max().date()),
            "sessions": int(len(d)),
        },
        "definitions": {
            "SELECTIVE_FILL_RAW": "Prior winning fill rule: prior-close NQSAR Blue/Green and ordinary-stock breadth >=50%; residual Gross100 cash goes to TQQQ even if the native effective TQQQ target is 0.",
            "SELECTIVE_FILL_NO_ZERO_OVERRIDE": "Same fill rule, but never adds TQQQ when the native effective TQQQ target is 0; preserves full-off TQQQ risk locks.",
            "SELECTIVE_FILL_T30_ONLY": "Same fill rule, but only adds TQQQ when the native effective TQQQ target is exactly the normal 30% state.",
            "unchanged": "No stock or Reset displacement; Gross<=100%; breadth 50/60 thresholds unchanged; 10bp turnover-cost convention unchanged.",
        },
        "native_target_state_diagnostics": {},
        "variants": {},
        "comparisons_vs_raw": {},
        "comparisons_vs_base": {},
    }

    # Attribute candidate fill days by the native TQQQ target state.
    for val in sorted(np.unique(np.round(eff_t, 6))):
        m = gate_sel & (residual > 1e-12) & np.isclose(eff_t, val, atol=1e-6)
        if not m.any():
            continue
        result["native_target_state_diagnostics"][f"target_{val:.6f}"] = {
            "days": int(m.sum()),
            "share_of_fill_days": float(m.sum() / max(1, (gate_sel & (residual > 1e-12)).sum())),
            "avg_residual_fill": float(residual[m].mean()),
            "median_residual_fill": float(np.median(residual[m])),
            "mean_tqqq_return_same_day": float(np.mean(ret_t[m])),
            "median_tqqq_return_same_day": float(np.median(ret_t[m])),
            "positive_tqqq_days": float(np.mean(ret_t[m] > 0)),
        }

    return_map: dict[str, np.ndarray] = {}
    dates = d["date"]
    for name, a in variants.items():
        rr, turn = scaled_returns(a, desired_o, desired_r, ret_t, ret_o, ret_r, COST_BPS)
        return_map[name] = rr
        periods = {}
        for label, ps, pe in period_slices(dates):
            mask = ((dates >= ps) & (dates <= pe)).to_numpy(bool)
            periods[label] = metrics(rr[mask], dates.loc[mask])
        tx = annual_net_tax_proxy(rr, dates, TAX_RATE)
        extra = a[:, 0] - base[:, 0]
        result["variants"][name] = {
            "full": metrics(rr, dates),
            "periods": periods,
            "monthly": monthly_stats(rr, dates),
            "rolling_2y": rolling_2y(rr, dates),
            "tax_proxy": {k: v for k, v in tx.items() if k != "annual"},
            "turnover": turn,
            "allocation": {
                "avg_tqqq": float(a[:, 0].mean()),
                "avg_total_gross": float(a.sum(axis=1).mean()),
                "pct_at_100": float((a.sum(axis=1) >= 1.0 - 1e-9).mean()),
                "fill_days": int((extra > 1e-12).sum()),
                "avg_extra_tqqq": float(extra.mean()),
                "avg_extra_on_fill_days": float(extra[extra > 1e-12].mean()) if (extra > 1e-12).any() else 0.0,
                "max_extra_tqqq": float(extra.max()),
            },
        }
        pd.DataFrame({
            "date": dates,
            "return_10bp": rr,
            "native_effective_tqqq_target": eff_t,
            "alloc_tqqq": a[:, 0],
            "alloc_ordinary": a[:, 1],
            "alloc_reset": a[:, 2],
            "total_gross": a.sum(axis=1),
            "extra_tqqq_vs_base": extra,
            "gate_attack_or_selective": gate_sel,
            "breadth_prev_close": d["breadth_prev_close"],
            "nqsar_prev_close": d["nqsar_prev_close"],
        }).to_csv(out / f"daily_{name.lower()}.csv.gz", index=False, compression="gzip")

    raw = result["variants"]["SELECTIVE_FILL_RAW"]
    basev = result["variants"]["BASE"]
    for name in ("SELECTIVE_FILL_NO_ZERO_OVERRIDE", "SELECTIVE_FILL_T30_ONLY"):
        v = result["variants"][name]
        result["comparisons_vs_raw"][name] = {
            "cagr_delta": v["full"]["cagr"] - raw["full"]["cagr"],
            "mdd_delta": v["full"]["mdd"] - raw["full"]["mdd"],
            "tax_proxy_cagr_delta": v["tax_proxy"]["tax_proxy_cagr"] - raw["tax_proxy"]["tax_proxy_cagr"],
            "2016_2021_cagr_delta": v["periods"]["2016_2021"]["cagr"] - raw["periods"]["2016_2021"]["cagr"],
            "2022_2026M3_cagr_delta": v["periods"]["2022_2026M3"]["cagr"] - raw["periods"]["2022_2026M3"]["cagr"],
            "rolling2y_worst_delta": v["rolling_2y"]["worst"] - raw["rolling_2y"]["worst"],
        }
    for name in ("SELECTIVE_FILL_RAW", "SELECTIVE_FILL_NO_ZERO_OVERRIDE", "SELECTIVE_FILL_T30_ONLY"):
        v = result["variants"][name]
        result["comparisons_vs_base"][name] = {
            "cagr_delta": v["full"]["cagr"] - basev["full"]["cagr"],
            "mdd_delta": v["full"]["mdd"] - basev["full"]["mdd"],
            "tax_proxy_cagr_delta": v["tax_proxy"]["tax_proxy_cagr"] - basev["tax_proxy"]["tax_proxy_cagr"],
            "2016_2021_cagr_delta": v["periods"]["2016_2021"]["cagr"] - basev["periods"]["2016_2021"]["cagr"],
            "2022_2026M3_cagr_delta": v["periods"]["2022_2026M3"]["cagr"] - basev["periods"]["2022_2026M3"]["cagr"],
            "rolling2y_worst_delta": v["rolling_2y"]["worst"] - basev["rolling_2y"]["worst"],
        }

    rows = []
    for name, v in result["variants"].items():
        rows.append({
            "variant": name,
            "cagr_10bp": v["full"]["cagr"],
            "mdd": v["full"]["mdd"],
            "cagr_2016_2021": v["periods"]["2016_2021"]["cagr"],
            "cagr_2022_2026M3": v["periods"]["2022_2026M3"]["cagr"],
            "tax_proxy_cagr": v["tax_proxy"]["tax_proxy_cagr"],
            "worst_month": v["monthly"]["worst_month"],
            "pct_months_ge7": v["monthly"]["pct_months_ge_7pct"],
            "rolling2y_worst": v["rolling_2y"]["worst"],
            "rolling2y_median": v["rolling_2y"]["median"],
            "avg_total_gross": v["allocation"]["avg_total_gross"],
            "avg_tqqq": v["allocation"]["avg_tqqq"],
            "fill_days": v["allocation"]["fill_days"],
            "avg_extra_tqqq": v["allocation"]["avg_extra_tqqq"],
            "max_extra_tqqq": v["allocation"]["max_extra_tqqq"],
        })
    pd.DataFrame(rows).to_csv(out / "comparison.csv", index=False)
    (out / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(pd.DataFrame(rows).to_string(index=False), flush=True)
    print("=== TQQQ_SELECTIVE_FILL_LOCK_GUARD_JSON ===", flush=True)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str), flush=True)
    print("=== END_TQQQ_SELECTIVE_FILL_LOCK_GUARD_JSON ===", flush=True)


if __name__ == "__main__":
    main()
