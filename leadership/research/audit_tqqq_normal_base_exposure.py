from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

BASES = (0.10, 0.20, 0.30, 0.40, 0.50)
TARGET_CURRENT = "target_CURRENT30"
TARGET_PANIC = "target_M30_TOUCH30_F80_D10"
ALLOC_COST_BPS = 10.0
TAX_RATE = 0.20315
TRADING_DAYS = 252


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


def effective(t: np.ndarray) -> np.ndarray:
    z = np.zeros(len(t), float)
    z[2:] = np.asarray(t, float)[:-2]
    return z


def allocator(tqqq: np.ndarray, ordinary: np.ndarray, reset: np.ndarray, floor: float = 0.80) -> np.ndarray:
    out = np.zeros((len(tqqq), 3), float)
    for i, (t, o, r) in enumerate(zip(tqqq, ordinary, reset)):
        t, o, r = max(float(t), 0.0), max(float(o), 0.0), max(float(r), 0.0)
        rem = 1.0
        ar = min(r, rem)
        out[i, 2] = ar
        rem -= ar
        if t + o <= rem + 1e-12:
            out[i, 0] = t
            out[i, 1] = o
            continue
        p = min(t, floor, rem)
        out[i, 0] = p
        rem -= p
        ao = min(o, rem)
        out[i, 1] = ao
        rem -= ao
        out[i, 0] += min(max(t - out[i, 0], 0.0), rem)
    return out


def metrics(ret: np.ndarray, dates: pd.Series) -> dict[str, Any]:
    r = np.nan_to_num(np.asarray(ret, float))
    d = pd.DatetimeIndex(pd.to_datetime(dates))
    eq = np.cumprod(1 + r)
    years = max((len(r) - 1) / TRADING_DAYS, 1 / TRADING_DAYS)
    cagr = float(eq[-1] ** (1 / years) - 1) if eq[-1] > 0 else -1.0
    peak = np.maximum.accumulate(eq)
    dd = eq / peak - 1
    ti = int(np.argmin(dd))
    pi = int(np.argmax(eq[: ti + 1]))
    sd = float(np.std(r, ddof=1))
    return {
        "cagr": cagr,
        "mdd": float(dd.min()),
        "sharpe": float(np.sqrt(TRADING_DAYS) * r.mean() / sd) if sd > 0 else None,
        "end": float(eq[-1]),
        "mdd_peak": str(d[pi].date()),
        "mdd_trough": str(d[ti].date()),
    }


def tax_proxy(ret: np.ndarray, dates: pd.Series) -> dict[str, float]:
    s = pd.Series(np.asarray(ret, float), index=pd.DatetimeIndex(pd.to_datetime(dates)))
    wealth = 1.0
    losses: list[list[float]] = []
    paid = 0.0
    for _, g in s.groupby(s.index.year):
        start = wealth
        pre = start * float(np.prod(1 + np.nan_to_num(g.to_numpy(float))))
        pnl = pre - start
        losses = [[rem, amt] for rem, amt in losses if rem > 0 and amt > 1e-15]
        taxable = max(0.0, pnl)
        losses.sort(key=lambda z: z[0])
        for z in losses:
            use = min(taxable, z[1])
            taxable -= use
            z[1] -= use
            if taxable <= 1e-15:
                break
        losses = [[rem - 1, amt] for rem, amt in losses if amt > 1e-15 and rem - 1 > 0]
        if pnl < 0:
            losses.append([3, -pnl])
        tx = taxable * TAX_RATE
        wealth = pre - tx
        paid += tx
    years = max((len(s) - 1) / TRADING_DAYS, 1 / TRADING_DAYS)
    return {"cagr": float(wealth ** (1 / years) - 1), "end": float(wealth), "tax_paid": float(paid)}


def monthly(ret: np.ndarray, dates: pd.Series) -> dict[str, float]:
    s = pd.Series(ret, index=pd.DatetimeIndex(pd.to_datetime(dates)))
    m = (1 + s).resample("ME").prod() - 1
    return {
        "geom": float(np.prod(1 + m.to_numpy(float)) ** (1 / len(m)) - 1),
        "worst": float(m.min()),
        "ge7": float((m >= 0.07).mean()),
        "positive": float((m > 0).mean()),
    }


def rolling2(ret: np.ndarray, dates: pd.Series) -> dict[str, float]:
    s = pd.Series(ret, index=pd.DatetimeIndex(pd.to_datetime(dates)))
    z = ((1 + s).rolling(504).apply(np.prod, raw=True) - 1).dropna()
    return {
        "worst": float(z.min()),
        "p10": float(z.quantile(0.10)),
        "median": float(z.median()),
        "positive": float((z > 0).mean()),
    }


def replace_normal_base(current30: np.ndarray, selected_panic: np.ndarray, base: float) -> np.ndarray:
    """Change only Stage34's normal base level while keeping all absolute hierarchy floors/boosts fixed.

    Stage34 constructs target as 0 under risk lock, otherwise base, then max(base, absolute
    RG/GB/strong/panic targets). Therefore CURRENT30 values are transformed as:
      0 -> 0; 0.30 baseline -> requested base; other positive targets -> max(existing, base).
    Stage56 M30_TOUCH30_F80_D10 then applies an 80% crash floor on the same event days.
    For base <=50%, days where the original current target was already >=80% are unchanged,
    so identifying floor-effective days by selected_panic > current30 is sufficient and exact.
    """
    cur = np.asarray(current30, float)
    chosen = np.asarray(selected_panic, float)
    new_cur = np.zeros(len(cur), float)
    pos = cur > 1e-12
    baseline = pos & np.isclose(cur, 0.30, atol=1e-10, rtol=0.0)
    other = pos & ~baseline
    new_cur[baseline] = base
    new_cur[other] = np.maximum(cur[other], base)
    floor_effective = chosen > cur + 1e-12
    out = new_cur.copy()
    out[floor_effective] = np.maximum(out[floor_effective], 0.80)
    return np.clip(out, 0.0, 1.0)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--components-dir", required=True)
    ap.add_argument("--stage56-dir", required=True)
    ap.add_argument("--lock-dir", required=True)
    ap.add_argument("--execution-dir", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    ordinary = pd.read_csv(next(Path(args.components_dir).rglob("ordinary_PEAK30_PART25_R3_daily.csv.gz")), compression="gzip")
    reset = pd.read_csv(next(Path(args.components_dir).rglob("rsi_RESET_RISE30_S029_P4_H20_daily.csv.gz")), compression="gzip")
    tq = pd.read_csv(next(Path(args.stage56_dir).rglob("tqqq_stage56_daily.csv.gz")), compression="gzip")
    gate = pd.read_csv(next(Path(args.lock_dir).rglob("daily_selective_fill_no_zero_override.csv.gz")), compression="gzip")
    exec10 = pd.read_csv(next(Path(args.execution_dir).rglob("daily_final_spec_10bp.csv.gz")), compression="gzip")

    for z in (ordinary, reset, tq, gate, exec10):
        z["date"] = pd.to_datetime(z["date"]).dt.normalize()

    d = ordinary.merge(reset, on="date", suffixes=("_ord", "_rsi"), validate="one_to_one")
    d = d.merge(tq[["date", "tqqq_ret_usd", TARGET_CURRENT, TARGET_PANIC]], on="date", validate="one_to_one")
    d = d.merge(gate[["date", "gate_attack_or_selective"]], on="date", validate="one_to_one")
    d = d.merge(exec10[["date", "ordinary_stressed_return", "return"]].rename(columns={"return": "reference_portfolio_return_30"}), on="date", validate="one_to_one")
    d = d.sort_values("date").reset_index(drop=True)

    go = d.gross_exposure_ord.to_numpy(float)
    gr = d.gross_exposure_rsi.to_numpy(float)
    ordinary_desired = np.minimum(go, 0.70)
    reset_desired = gr
    r_ord = d.ordinary_stressed_return.to_numpy(float)
    r_reset = d.return_rsi.to_numpy(float)
    r_tq = d.tqqq_ret_usd.to_numpy(float)
    gate_as = d.gate_attack_or_selective.astype(bool).to_numpy()
    current30 = d[TARGET_CURRENT].to_numpy(float)
    panic30 = d[TARGET_PANIC].to_numpy(float)

    results: dict[str, Any] = {}
    rows = []
    daily30 = None

    for base in BASES:
        target = replace_normal_base(current30, panic30, base)
        eff = effective(target)
        alloc0 = allocator(eff, ordinary_desired, reset_desired)
        base_tqqq = alloc0[:, 0].copy()
        residual = np.maximum(0.0, 1.0 - alloc0.sum(axis=1))
        allow_fill = gate_as & (eff > 1e-12)
        alloc = alloc0.copy()
        alloc[:, 0] += residual * allow_fill
        at, ao, ar = alloc.T

        so = np.divide(ao, go, out=np.zeros_like(ao), where=go > 1e-12)
        sr = np.divide(ar, gr, out=np.zeros_like(ar), where=gr > 1e-12)

        alloc_turn = np.zeros(len(d), float)
        for a in (at, ao, ar):
            z = np.zeros(len(a), float)
            z[1:] = np.abs(np.diff(a))
            alloc_turn += z
        alloc_drag = alloc_turn * (ALLOC_COST_BPS / 10000.0)
        ret = at * r_tq + so * r_ord + sr * r_reset - alloc_drag

        three_x = ao + ar + 3.0 * at
        actual_fill = at > base_tqqq + 1e-12
        full = metrics(ret, d.date)
        tax = tax_proxy(ret, d.date)
        mon = monthly(ret, d.date)
        roll = rolling2(ret, d.date)
        periods = {}
        for lab, lo, hi in (
            ("2016_2021", "2016-01-04", "2021-12-31"),
            ("2022_2026M3", "2022-01-01", "2026-03-20"),
            ("2022_2023", "2022-01-01", "2023-12-31"),
            ("2024_2026M3", "2024-01-01", "2026-03-20"),
        ):
            m = ((d.date >= lo) & (d.date <= hi)).to_numpy()
            periods[lab] = metrics(ret[m], d.date.loc[m])

        exposure = {
            "avg_tqqq": float(at.mean()),
            "avg_ordinary": float(ao.mean()),
            "avg_reset": float(ar.mean()),
            "avg_gross_capital": float(alloc.sum(axis=1).mean()),
            "gross100_rate": float((alloc.sum(axis=1) >= 0.999999).mean()),
            "avg_3x_notional_equiv": float(three_x.mean()),
            "median_3x_notional_equiv": float(np.median(three_x)),
            "pct_3x_equiv_ge100": float((three_x >= 1.00).mean()),
            "pct_3x_equiv_ge120": float((three_x >= 1.20).mean()),
            "pct_3x_equiv_ge150": float((three_x >= 1.50).mean()),
            "pct_3x_equiv_ge160": float((three_x >= 1.60).mean()),
            "native_zero_rate": float((eff <= 1e-12).mean()),
            "fill_days": int(actual_fill.sum()),
        }
        key = f"B{int(round(base * 100))}"
        results[key] = {
            "normal_base": base,
            "full": full,
            "tax_proxy": tax,
            "monthly": mon,
            "rolling2y": roll,
            "periods": periods,
            "exposure": exposure,
        }
        rows.append({
            "normal_base": base,
            "cagr": full["cagr"],
            "mdd": full["mdd"],
            "sharpe": full["sharpe"],
            "tax_proxy_cagr": tax["cagr"],
            "cagr_2016_2021": periods["2016_2021"]["cagr"],
            "cagr_2022_2026M3": periods["2022_2026M3"]["cagr"],
            "cagr_2022_2023": periods["2022_2023"]["cagr"],
            "rolling2y_worst": roll["worst"],
            "geom_month": mon["geom"],
            "avg_tqqq": exposure["avg_tqqq"],
            "avg_gross": exposure["avg_gross_capital"],
            "avg_3x_equiv": exposure["avg_3x_notional_equiv"],
            "pct_ge100": exposure["pct_3x_equiv_ge100"],
            "pct_ge120": exposure["pct_3x_equiv_ge120"],
            "pct_ge150": exposure["pct_3x_equiv_ge150"],
            "fill_days": exposure["fill_days"],
        })
        pd.DataFrame({
            "date": d.date,
            "return": ret,
            "target": target,
            "effective_target": eff,
            "alloc_tqqq": at,
            "alloc_ordinary": ao,
            "alloc_reset": ar,
            "notional_3x_equiv": three_x,
            "actual_fill": actual_fill,
        }).to_csv(out / f"daily_base_{int(base * 100)}.csv.gz", index=False, compression="gzip")
        if abs(base - 0.30) < 1e-12:
            daily30 = ret.copy()

    if daily30 is None:
        raise RuntimeError("30% control variant missing")
    ref = d.reference_portfolio_return_30.to_numpy(float)
    maxdiff = float(np.max(np.abs(daily30 - ref)))
    if maxdiff > 1e-12:
        raise RuntimeError(f"30% frozen final-spec reproduction failed: max abs daily return diff={maxdiff}")

    table = pd.DataFrame(rows).sort_values("normal_base")
    table.to_csv(out / "comparison.csv", index=False)
    summary = {
        "status": "V38_TQQQ_NORMAL_BASE_EXPOSURE_AUDIT",
        "spec_fixed": "Normal Stock cap70 + RSI Reset + Stage34 hierarchy/risk locks + M30_TOUCH30_F80_D10 + SELECTIVE_FILL_NO_ZERO_OVERRIDE + Gross100 + allocator10bp + Normal constituent10bp",
        "base_values": list(BASES),
        "method": "Only the Stage34 normal base level is changed. Risk-lock zero, RG/GB/strong absolute targets, Panic F80/D10, stock rules, Reset, Selective Fill and Gross100 are fixed.",
        "prior_research": "Stage20 already compared 30/32.5/35 with matched 1000-path normal bootstrap and 1000-path adversarial Bear stress; this audit only broadens the coarse base range inside the now-final integrated portfolio.",
        "reproduction": {"base30_max_abs_daily_return_diff_vs_frozen_final_10bp": maxdiff, "passed": True},
        "notional_note": "3x notional-equivalent = Normal Stock + Reset + 3*TQQQ allocated capital. This is a leverage/intended-market-exposure proxy, not realized beta and not a prediction of 3x long-horizon TQQQ return.",
        "variants": results,
    }
    (out / "summary.json").write_text(json.dumps(safe(summary), ensure_ascii=False, indent=2), encoding="utf-8")
    print(table.to_string(index=False), flush=True)
    print("=== BASE_EXPOSURE_JSON ===", flush=True)
    print(json.dumps(safe(summary), ensure_ascii=False, indent=2), flush=True)
    print("=== END_BASE_EXPOSURE_JSON ===", flush=True)


if __name__ == "__main__":
    main()
