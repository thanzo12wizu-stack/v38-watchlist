from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

TRADING_DAYS = 252
TAX_RATE = 0.20315
COST_BPS = 10.0


def safe(x: Any) -> Any:
    if isinstance(x, dict):
        return {str(k): safe(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [safe(v) for v in x]
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, (np.floating, float)):
        z = float(x)
        return z if math.isfinite(z) else None
    if isinstance(x, pd.Timestamp):
        return x.isoformat()
    return x


def allocator(tqqq: np.ndarray, ordinary_demand: np.ndarray, reset: np.ndarray, floor: float = 0.80) -> np.ndarray:
    """Exact prior Gross100 priority: Reset -> protect TQQQ to 80 on conflict -> Ordinary -> remaining desired TQQQ."""
    g = np.column_stack([tqqq, ordinary_demand, reset])
    out = np.zeros_like(g)
    for i, row in enumerate(g):
        t, o, r = [max(float(x), 0.0) for x in row]
        rem = 1.0
        ar = min(r, rem); out[i, 2] = ar; rem -= ar
        if t + o <= rem + 1e-12:
            out[i, 0] = t; out[i, 1] = o
            continue
        protect = min(t, floor, rem); out[i, 0] = protect; rem -= protect
        ao = min(o, rem); out[i, 1] = ao; rem -= ao
        out[i, 0] += min(max(t - out[i, 0], 0.0), rem)
    return out


def effective_target(target: np.ndarray) -> np.ndarray:
    z = np.zeros(len(target), float)
    z[2:] = np.asarray(target, float)[:-2]
    return z


def scaled_returns(alloc: np.ndarray, original_gross_o: np.ndarray, original_gross_r: np.ndarray,
                   ret_t: np.ndarray, ret_o: np.ndarray, ret_r: np.ndarray, cost_bps: float) -> tuple[np.ndarray, dict[str, float]]:
    """Scale component NAV returns by allocated gross / original standalone gross.

    Important: when the *demand* for Ordinary is capped at 70%, the denominator stays
    the original standalone gross. Otherwise a 70% cap would incorrectly receive 100%
    of the standalone sleeve return on days the standalone sleeve itself was >70% invested.
    """
    a_t, a_o, a_r = alloc.T
    s_o = np.divide(a_o, original_gross_o, out=np.zeros_like(a_o), where=original_gross_o > 1e-12)
    s_r = np.divide(a_r, original_gross_r, out=np.zeros_like(a_r), where=original_gross_r > 1e-12)
    ret = a_t * ret_t + s_o * ret_o + s_r * ret_r
    c = float(cost_bps) / 10000.0
    turns = []
    for a in (a_t, a_o, a_r):
        x = np.zeros(len(a), float); x[1:] = np.abs(np.diff(a)); turns.append(x)
    ret -= sum(turns) * c
    return ret, {
        "turn_tqqq": float(turns[0].sum()),
        "turn_ordinary_allocated_gross": float(turns[1].sum()),
        "turn_reset_allocated_gross": float(turns[2].sum()),
        "total_allocated_gross_turnover": float(sum(z.sum() for z in turns)),
    }


def metrics(ret: np.ndarray, dates) -> dict[str, Any]:
    r = np.nan_to_num(np.asarray(ret, float), nan=0.0, posinf=0.0, neginf=0.0)
    d = pd.DatetimeIndex(pd.to_datetime(dates))
    eq = np.cumprod(1.0 + r)
    years = max((len(r) - 1) / TRADING_DAYS, 1.0 / TRADING_DAYS)
    cagr = float(eq[-1] ** (1.0 / years) - 1.0) if len(eq) and eq[-1] > 0 else -1.0
    peak = np.maximum.accumulate(eq)
    dd = eq / peak - 1.0
    ti = int(np.argmin(dd)); pi = int(np.argmax(eq[:ti + 1]))
    sd = float(np.std(r, ddof=1)) if len(r) > 1 else np.nan
    return {
        "cagr": cagr,
        "mdd": float(dd.min()),
        "sharpe": float(np.sqrt(TRADING_DAYS) * np.mean(r) / sd) if np.isfinite(sd) and sd > 0 else np.nan,
        "end": float(eq[-1]),
        "mdd_peak_date": str(d[pi].date()),
        "mdd_trough_date": str(d[ti].date()),
    }


def tax_proxy(ret: np.ndarray, dates) -> dict[str, float]:
    r = pd.Series(np.asarray(ret, float), index=pd.DatetimeIndex(pd.to_datetime(dates)))
    wealth = 1.0; losses: list[list[float]] = []; taxes = 0.0
    for _, g in r.groupby(r.index.year):
        start = wealth
        pre = start * float(np.prod(1.0 + np.nan_to_num(g.to_numpy(float), nan=0.0)))
        pnl = pre - start
        losses = [[rem, amt] for rem, amt in losses if rem > 0 and amt > 1e-15]
        taxable = max(0.0, pnl)
        if taxable > 0:
            losses.sort(key=lambda z: z[0])
            for z in losses:
                use = min(taxable, z[1]); taxable -= use; z[1] -= use
                if taxable <= 1e-15: break
        losses = [[rem - 1, amt] for rem, amt in losses if amt > 1e-15 and rem - 1 > 0]
        if pnl < 0: losses.append([3, -pnl])
        tax = taxable * TAX_RATE; wealth = pre - tax; taxes += tax
    years = max((len(r) - 1) / TRADING_DAYS, 1.0 / TRADING_DAYS)
    return {"tax_proxy_cagr": float(wealth ** (1.0 / years) - 1.0), "tax_proxy_end": float(wealth), "tax_proxy_paid": float(taxes)}


def monthly(ret: np.ndarray, dates) -> dict[str, float]:
    s = pd.Series(np.asarray(ret, float), index=pd.DatetimeIndex(pd.to_datetime(dates)))
    m = (1.0 + s).resample("ME").prod() - 1.0
    return {
        "geom_month": float(np.prod(1.0 + m.to_numpy(float)) ** (1.0 / len(m)) - 1.0),
        "worst_month": float(m.min()),
        "pct_months_ge7": float((m >= 0.07).mean()),
        "positive_months": float((m > 0).mean()),
    }


def rolling2y(ret: np.ndarray, dates) -> dict[str, float]:
    s = pd.Series(np.asarray(ret, float), index=pd.DatetimeIndex(pd.to_datetime(dates)))
    z = ((1.0 + s).rolling(504).apply(np.prod, raw=True) - 1.0).dropna()
    return {"worst": float(z.min()), "p10": float(z.quantile(.10)), "median": float(z.median()), "positive_rate": float((z > 0).mean())}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--components-dir", required=True)
    ap.add_argument("--tqqq-spec-dir", required=True)
    ap.add_argument("--lock-guard-dir", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    out = Path(args.output); out.mkdir(parents=True, exist_ok=True)

    comp = Path(args.components_dir)
    o = pd.read_csv(comp / "ordinary_PEAK30_PART25_R3_daily.csv.gz", compression="gzip")
    r = pd.read_csv(comp / "rsi_RESET_RISE30_S029_P4_H20_daily.csv.gz", compression="gzip")
    tq = pd.read_csv(Path(args.tqqq_spec_dir) / "tqqq_fixed30_spec_daily.csv.gz", compression="gzip")
    lg = Path(args.lock_guard_dir)
    gate_path = lg / "daily_selective_fill_no_zero_override.csv.gz"
    if not gate_path.is_file():
        raise FileNotFoundError(gate_path)
    g = pd.read_csv(gate_path, compression="gzip")
    for x in (o, r, tq, g): x["date"] = pd.to_datetime(x["date"]).dt.normalize()
    d = o.merge(r, on="date", suffixes=("_ord", "_rsi")).merge(tq, on="date", how="inner")
    d = d.merge(g[["date", "gate_attack_or_selective", "breadth_prev_close", "nqsar_prev_close", "return_10bp"]].rename(columns={"return_10bp":"prior_nozero_return_10bp"}), on="date", validate="one_to_one")
    d = d.sort_values("date").reset_index(drop=True)

    ret_t = d["tqqq_ret_usd"].to_numpy(float)
    ret_o = d["return_ord"].to_numpy(float)
    ret_r = d["return_rsi"].to_numpy(float)
    gross_o = d["gross_exposure_ord"].to_numpy(float)
    gross_r = d["gross_exposure_rsi"].to_numpy(float)
    gate = d["gate_attack_or_selective"].astype(bool).to_numpy()
    dates = d["date"]
    native = {
        "CURRENT30": effective_target(d["target_current30_panic80"].to_numpy(float)),
        "FIXED30": effective_target(d["target_fixed30_panic80"].to_numpy(float)),
    }

    variants: dict[str, dict[str, Any]] = {}
    daily_map: dict[str, np.ndarray] = {}
    for tname, eff_t in native.items():
        for cap_name, demand_o in (("UNCAPPED", gross_o.copy()), ("CAP70", np.minimum(gross_o, 0.70))):
            base = allocator(eff_t, demand_o, gross_r, 0.80)
            residual = np.maximum(0.0, 1.0 - base.sum(axis=1))
            for fill_name, fill in (("NOFILL", False), ("SELECTIVE_FILL", True)):
                a = base.copy()
                if fill:
                    # Preserve native full-off semantics. For FIXED30 this is always true after warm-up.
                    m = gate & (eff_t > 1e-12)
                    a[:, 0] += residual * m.astype(float)
                name = f"{tname}_{cap_name}_{fill_name}"
                if float(a.sum(axis=1).max()) > 1.0 + 1e-9:
                    raise RuntimeError(f"Gross100 violation {name}")
                rr, turn = scaled_returns(a, gross_o, gross_r, ret_t, ret_o, ret_r, COST_BPS)
                daily_map[name] = rr
                periods = {}
                for label, lo, hi in (
                    ("2016_2021", "2016-01-04", "2021-12-31"),
                    ("2022_2026M3", "2022-01-01", "2026-03-20"),
                    ("2022_2023", "2022-01-01", "2023-12-31"),
                    ("2024_2026M3", "2024-01-01", "2026-03-20"),
                ):
                    m = ((dates >= pd.Timestamp(lo)) & (dates <= pd.Timestamp(hi))).to_numpy(bool)
                    periods[label] = metrics(rr[m], dates.loc[m])
                variants[name] = {
                    "full": metrics(rr, dates), "periods": periods,
                    "monthly": monthly(rr, dates), "rolling2y": rolling2y(rr, dates),
                    "tax_proxy": tax_proxy(rr, dates), "turnover": turn,
                    "allocation": {
                        "avg_tqqq": float(a[:,0].mean()), "avg_ordinary": float(a[:,1].mean()), "avg_reset": float(a[:,2].mean()),
                        "avg_gross": float(a.sum(axis=1).mean()), "pct_gross100": float((a.sum(axis=1) >= 1-1e-9).mean()),
                        "normal_cap_binding_days": int(np.sum(gross_o > 0.70 + 1e-12)) if cap_name == "CAP70" else 0,
                        "normal_alloc_over70_days": int(np.sum(a[:,1] > 0.70 + 1e-12)),
                        "fill_days": int(np.sum((a[:,0] - base[:,0]) > 1e-12)),
                        "max_normal_alloc": float(a[:,1].max()),
                    },
                }
                pd.DataFrame({"date":dates,"return_10bp":rr,"alloc_tqqq":a[:,0],"alloc_ordinary":a[:,1],"alloc_reset":a[:,2],"total_gross":a.sum(axis=1),"native_eff_tqqq":eff_t,"original_ordinary_gross":gross_o,"ordinary_demand":demand_o,"gate_selective":gate}).to_csv(out / f"daily_{name.lower()}.csv.gz", index=False, compression="gzip")

    # Reproduction guard: the uncapped CURRENT30 Selective Fill must exactly reproduce
    # the prior Lock-Guard NO_ZERO_OVERRIDE return path from the frozen artifact.
    repro = daily_map["CURRENT30_UNCAPPED_SELECTIVE_FILL"]
    prior = d["prior_nozero_return_10bp"].to_numpy(float)
    max_abs = float(np.max(np.abs(repro - prior)))
    if max_abs > 1e-12:
        raise RuntimeError(f"prior NO_ZERO_OVERRIDE reproduction failed max_abs={max_abs}")

    rows = []
    for name, v in variants.items():
        rows.append({
            "variant": name, "cagr": v["full"]["cagr"], "mdd": v["full"]["mdd"], "sharpe": v["full"]["sharpe"],
            "tax_proxy_cagr": v["tax_proxy"]["tax_proxy_cagr"], "cagr_2016_2021": v["periods"]["2016_2021"]["cagr"],
            "cagr_2022_2026M3": v["periods"]["2022_2026M3"]["cagr"], "rolling2y_worst": v["rolling2y"]["worst"],
            "avg_gross": v["allocation"]["avg_gross"], "avg_tqqq": v["allocation"]["avg_tqqq"], "avg_ordinary": v["allocation"]["avg_ordinary"],
            "normal_alloc_over70_days": v["allocation"]["normal_alloc_over70_days"], "fill_days": v["allocation"]["fill_days"],
        })
    pd.DataFrame(rows).sort_values("cagr", ascending=False).to_csv(out / "comparison.csv", index=False)

    result = {
        "status": "V38_FINAL_SPEC_FACTORIAL_AUDIT",
        "coverage": {"start": str(d.date.min().date()), "end": str(d.date.max().date()), "sessions": int(len(d))},
        "method": {
            "dimensions": ["CURRENT30 vs FIXED30", "ordinary standalone demand uncapped vs capped at 70%", "no fill vs SELECTIVE_FILL_NO_ZERO_OVERRIDE"],
            "purpose": "Resolve specification conflicts only; no threshold optimization.",
            "cost": "10bp on day-to-day changes in allocated sleeve gross, for exact comparability with prior combined audits.",
            "ordinary_return_scaling": "Always allocated ordinary gross / original standalone ordinary gross, even when demand is capped at 70%.",
            "tax": "20.315% annual-net portfolio proxy with 3-year loss carry; not exact constituent lot taxation.",
        },
        "reproduction_guard": {"prior_nozero_max_abs_daily_return_diff": max_abs, "passed": True},
        "ordinary_original_gross": {"max": float(gross_o.max()), "days_over70": int(np.sum(gross_o > .70 + 1e-12)), "mean": float(gross_o.mean())},
        "variants": variants,
    }
    (out / "summary.json").write_text(json.dumps(safe(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print(pd.DataFrame(rows).sort_values("cagr", ascending=False).to_string(index=False))
    print("=== V38_FINAL_SPEC_FACTORIAL_JSON ===")
    print(json.dumps(safe(result), ensure_ascii=False, indent=2))
    print("=== END_V38_FINAL_SPEC_FACTORIAL_JSON ===")

if __name__ == "__main__":
    main()
