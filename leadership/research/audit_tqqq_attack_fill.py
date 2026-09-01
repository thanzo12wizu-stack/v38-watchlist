from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import audit_ordinary_stock_market_mode_robustness as mm

TRADING_DAYS = 252
TAX_RATE = 0.20315
COST_BPS = 10.0
TARGET_COL = "target_M30_TOUCH30_F80_D10"


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


def reset_first_tqqq_floor(g: np.ndarray, floor: float = 0.80) -> np.ndarray:
    """Exact allocator used by the prior Gross100 audit."""
    out = np.zeros_like(g)
    for i, row in enumerate(g):
        t, o, r = [max(float(x), 0.0) for x in row]
        rem = 1.0
        ar = min(r, rem)
        out[i, 2] = ar
        rem -= ar
        if t + o <= rem + 1e-12:
            out[i, 0] = t
            out[i, 1] = o
            continue
        protect = min(t, floor, rem)
        out[i, 0] = protect
        rem -= protect
        ao = min(o, rem)
        out[i, 1] = ao
        rem -= ao
        out[i, 0] += min(max(t - out[i, 0], 0.0), rem)
    return out


def scaled_returns(
    alloc: np.ndarray,
    desired_o: np.ndarray,
    desired_r: np.ndarray,
    ret_t: np.ndarray,
    ret_o: np.ndarray,
    ret_r: np.ndarray,
    cost_bps: float = COST_BPS,
) -> tuple[np.ndarray, dict[str, float]]:
    a_t, a_o, a_r = alloc.T
    s_o = np.divide(a_o, desired_o, out=np.zeros_like(a_o), where=desired_o > 1e-12)
    s_r = np.divide(a_r, desired_r, out=np.zeros_like(a_r), where=desired_r > 1e-12)
    ret = a_t * ret_t + s_o * ret_o + s_r * ret_r
    c = float(cost_bps) / 10000.0
    turn_t = np.zeros(len(ret), float)
    turn_o = np.zeros(len(ret), float)
    turn_r = np.zeros(len(ret), float)
    turn_t[1:] = np.abs(np.diff(a_t))
    turn_o[1:] = np.abs(np.diff(a_o))
    turn_r[1:] = np.abs(np.diff(a_r))
    ret -= (turn_t + turn_o + turn_r) * c
    return ret, {
        "turn_t": float(turn_t.sum()),
        "turn_o": float(turn_o.sum()),
        "turn_r": float(turn_r.sum()),
        "total_turnover": float(turn_t.sum() + turn_o.sum() + turn_r.sum()),
    }


def metrics(ret: np.ndarray, dates: pd.Series | pd.DatetimeIndex) -> dict[str, Any]:
    r = np.nan_to_num(np.asarray(ret, float), nan=0.0, posinf=0.0, neginf=0.0)
    d = pd.DatetimeIndex(pd.to_datetime(dates))
    if len(r) == 0:
        return {}
    eq = np.cumprod(1.0 + r)
    years = max((len(r) - 1) / TRADING_DAYS, 1.0 / TRADING_DAYS)
    cagr = float(eq[-1] ** (1.0 / years) - 1.0) if eq[-1] > 0 else -1.0
    peak = np.maximum.accumulate(eq)
    dd = eq / peak - 1.0
    trough_i = int(np.argmin(dd))
    peak_i = int(np.argmax(eq[: trough_i + 1])) if trough_i >= 0 else 0
    sd = float(np.std(r, ddof=1)) if len(r) > 1 else np.nan
    sharpe = float(np.sqrt(TRADING_DAYS) * np.mean(r) / sd) if np.isfinite(sd) and sd > 0 else np.nan
    return {
        "cagr": cagr,
        "mdd": float(dd.min()),
        "sharpe": sharpe,
        "end": float(eq[-1]),
        "mdd_peak_date": str(d[peak_i].date()),
        "mdd_trough_date": str(d[trough_i].date()),
    }


def monthly_stats(ret: np.ndarray, dates: pd.Series | pd.DatetimeIndex) -> dict[str, Any]:
    s = pd.Series(np.asarray(ret, float), index=pd.DatetimeIndex(pd.to_datetime(dates)))
    m = (1.0 + s).resample("ME").prod() - 1.0
    if m.empty:
        return {}
    return {
        "months": int(len(m)),
        "mean_month": float(m.mean()),
        "geom_month": float((np.prod(1.0 + m.to_numpy(float)) ** (1.0 / len(m))) - 1.0),
        "worst_month": float(m.min()),
        "worst_month_date": str(m.idxmin().date()),
        "pct_months_ge_7pct": float((m >= 0.07).mean()),
        "pct_positive_months": float((m > 0).mean()),
    }


def rolling_2y(ret: np.ndarray, dates: pd.Series | pd.DatetimeIndex) -> dict[str, Any]:
    s = pd.Series(np.asarray(ret, float), index=pd.DatetimeIndex(pd.to_datetime(dates)))
    z = (1.0 + s).rolling(504).apply(np.prod, raw=True) - 1.0
    z = z.dropna()
    if z.empty:
        return {}
    return {
        "n": int(len(z)),
        "worst": float(z.min()),
        "p10": float(z.quantile(0.10)),
        "median": float(z.median()),
        "p90": float(z.quantile(0.90)),
        "positive_rate": float((z > 0).mean()),
    }


def annual_net_tax_proxy(ret: np.ndarray, dates: pd.Series | pd.DatetimeIndex, rate: float = TAX_RATE) -> dict[str, Any]:
    """
    Conservative mixed-sleeve tax proxy.
    Treat each calendar year's net portfolio P/L as realized, apply 20.315% tax,
    use a 3-year loss carry, and tax the final partial year. This is deliberately
    NOT labelled an exact trade-lot tax result because component artifacts do not
    expose every underlying stock realization/basis lot.
    """
    r = pd.Series(np.asarray(ret, float), index=pd.DatetimeIndex(pd.to_datetime(dates)))
    wealth = 1.0
    losses: list[list[float]] = []  # [remaining tax years, loss amount in wealth units]
    taxes = 0.0
    rows = []
    for year, g in r.groupby(r.index.year):
        start = wealth
        gross_factor = float(np.prod(1.0 + np.nan_to_num(g.to_numpy(float), nan=0.0)))
        pre_tax_end = start * gross_factor
        pnl = pre_tax_end - start
        losses = [[rem, amt] for rem, amt in losses if rem > 0 and amt > 1e-15]
        taxable = max(0.0, pnl)
        if taxable > 0:
            losses.sort(key=lambda x: x[0])
            for z in losses:
                if taxable <= 0:
                    break
                use = min(taxable, z[1])
                taxable -= use
                z[1] -= use
        losses = [[rem - 1, amt] for rem, amt in losses if amt > 1e-15 and rem - 1 > 0]
        if pnl < 0:
            losses.append([3, -pnl])
        tax = taxable * rate
        wealth = pre_tax_end - tax
        taxes += tax
        rows.append({"year": int(year), "start": start, "pre_tax_end": pre_tax_end, "pnl": pnl, "tax": tax, "after_tax_end": wealth})
    years = max((len(r) - 1) / TRADING_DAYS, 1.0 / TRADING_DAYS)
    cagr = float(wealth ** (1.0 / years) - 1.0) if wealth > 0 else -1.0
    return {"tax_proxy_cagr": cagr, "tax_proxy_end": float(wealth), "tax_proxy_paid": float(taxes), "annual": rows}


def period_slices(dates: pd.Series) -> list[tuple[str, pd.Timestamp, pd.Timestamp]]:
    return [
        ("FULL", pd.Timestamp(dates.min()), pd.Timestamp(dates.max())),
        ("2016_2021", pd.Timestamp("2016-01-04"), pd.Timestamp("2021-12-31")),
        ("2022_2026M3", pd.Timestamp("2022-01-01"), pd.Timestamp("2026-03-20")),
        ("2022_2023", pd.Timestamp("2022-01-01"), pd.Timestamp("2023-12-31")),
        ("2024_2026M3", pd.Timestamp("2024-01-01"), pd.Timestamp("2026-03-20")),
    ]


def load_inputs(components_dir: Path, tqqq_daily: Path) -> pd.DataFrame:
    ordinary = pd.read_csv(components_dir / "ordinary_PEAK30_PART25_R3_daily.csv.gz", compression="gzip")
    reset = pd.read_csv(components_dir / "rsi_RESET_RISE30_S029_P4_H20_daily.csv.gz", compression="gzip")
    tq = pd.read_csv(tqqq_daily, compression="gzip")
    for x in (ordinary, reset, tq):
        x["date"] = pd.to_datetime(x["date"]).dt.normalize()
    d = ordinary.merge(reset, on="date", suffixes=("_ord", "_rsi")).merge(tq, on="date", how="inner")
    if TARGET_COL not in d.columns:
        raise KeyError(TARGET_COL)
    return d.sort_values("date").reset_index(drop=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--components-dir", required=True)
    ap.add_argument("--tqqq-daily", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--analysis-start", default="2016-01-04")
    ap.add_argument("--analysis-end", default="2026-03-20")
    ap.add_argument("--max-tickers", type=int, default=6000)
    ap.add_argument("--batch-size", type=int, default=75)
    args = ap.parse_args()

    root = Path(args.root)
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    d = load_inputs(Path(args.components_dir), Path(args.tqqq_daily))

    print("[1/3] rebuild exact ordinary-stock breadth + NQSAR definitions", flush=True)
    meta, _matrices = mm.build_inputs(root, args.analysis_start, args.analysis_end, args.max_tickers, args.batch_size)
    calendar = pd.DatetimeIndex(d["date"])
    b = pd.to_numeric(meta["breadth"], errors="coerce").reindex(calendar)
    nq = meta["nq"].reindex(calendar)
    color = nq["nq_color"].astype("object") if "nq_color" in nq else pd.Series(index=calendar, dtype="object")

    # Signals known at prior close govern current-open fill. No same-day look-ahead.
    gate_breadth = b.shift(1)
    gate_color = color.shift(1)
    bull = gate_color.isin(["Blue", "Green"])
    gate_attack = (bull & (gate_breadth >= 60.0)).fillna(False).to_numpy(bool)
    gate_attack_selective = (bull & (gate_breadth >= 50.0)).fillna(False).to_numpy(bool)

    n = len(d)
    target = d[TARGET_COL].to_numpy(float)
    eff_t = np.zeros(n, float)
    eff_t[2:] = target[:-2]  # exact prior Gross100 convention
    ret_t = d["tqqq_ret_usd"].to_numpy(float)
    ret_o = d["return_ord"].to_numpy(float)
    ret_r = d["return_rsi"].to_numpy(float)
    desired_o = d["gross_exposure_ord"].to_numpy(float)
    desired_r = d["gross_exposure_rsi"].to_numpy(float)
    desired = np.column_stack([eff_t, desired_o, desired_r])

    base = reset_first_tqqq_floor(desired, 0.80)
    residual = np.maximum(0.0, 1.0 - base.sum(axis=1))
    variants = {
        "BASE": base.copy(),
        "ATTACK_FILL": base.copy(),
        "ATTACK_SELECTIVE_FILL": base.copy(),
    }
    variants["ATTACK_FILL"][:, 0] += residual * gate_attack.astype(float)
    variants["ATTACK_SELECTIVE_FILL"][:, 0] += residual * gate_attack_selective.astype(float)

    for name, a in variants.items():
        if float(a.sum(axis=1).max()) > 1.0 + 1e-9:
            raise RuntimeError(f"Gross100 violated by {name}: {a.sum(axis=1).max()}")
        if np.any(a[:, 1] + 1e-12 < base[:, 1]) or np.any(a[:, 2] + 1e-12 < base[:, 2]):
            raise RuntimeError(f"stock/reset displacement detected in {name}")

    print("[2/3] evaluate BASE / ATTACK_FILL / ATTACK_SELECTIVE_FILL", flush=True)
    result: dict[str, Any] = {
        "status": "TQQQ_ATTACK_CASH_FILL_AUDIT",
        "definitions": {
            "BASE": "Prior Gross100 RESET_TFLOOR_080 allocation: Reset first, protect TQQQ to 80% on conflict, ordinary stocks, then remaining desired TQQQ.",
            "ATTACK_FILL": "After BASE allocation only, fill unused Gross100 capacity with TQQQ when prior-close ordinary-stock Market Mode is Attack: NQSAR Blue/Green and all-stock Close>SMA50 breadth >=60%.",
            "ATTACK_SELECTIVE_FILL": "After BASE allocation only, fill unused Gross100 capacity with TQQQ when prior-close NQSAR is Blue/Green and all-stock Close>SMA50 breadth >=50% (Attack or Selective).",
            "no_displacement": "Normal-stock and Reset allocated gross are identical to BASE; extra TQQQ uses residual cash only.",
            "tqqq_target": TARGET_COL,
            "tqqq_effective_lag": "2 rows, identical to prior Gross100 audit",
            "cost": "10bp times day-to-day absolute change in each allocated sleeve gross, identical to prior ALL10 allocator convention.",
            "tax": "20.315% annual-net mark-to-market proxy with 3-year loss carry; conservative comparison only, not exact underlying trade-lot taxation.",
        },
        "coverage": {
            "start": str(d.date.min().date()),
            "end": str(d.date.max().date()),
            "sessions": int(len(d)),
            "breadth_valid": int(b.notna().sum()),
            "nqsar_valid": int(color.notna().sum()),
        },
        "gate_stats": {
            "attack_days": int(gate_attack.sum()),
            "attack_share": float(gate_attack.mean()),
            "attack_or_selective_days": int(gate_attack_selective.sum()),
            "attack_or_selective_share": float(gate_attack_selective.mean()),
            "base_residual_cash_mean": float(residual.mean()),
            "base_residual_cash_days": int((residual > 1e-12).sum()),
        },
        "variants": {},
        "comparisons_vs_base": {},
    }

    return_map: dict[str, np.ndarray] = {}
    dates = d["date"]
    for name, a in variants.items():
        rr, turn = scaled_returns(a, desired_o, desired_r, ret_t, ret_o, ret_r, COST_BPS)
        return_map[name] = rr
        periods: dict[str, Any] = {}
        for label, ps, pe in period_slices(dates):
            mask = ((dates >= ps) & (dates <= pe)).to_numpy(bool)
            periods[label] = metrics(rr[mask], dates.loc[mask])
        tx = annual_net_tax_proxy(rr, dates, TAX_RATE)
        result["variants"][name] = {
            "full": metrics(rr, dates),
            "periods": periods,
            "monthly": monthly_stats(rr, dates),
            "rolling_2y": rolling_2y(rr, dates),
            "tax_proxy": {k: v for k, v in tx.items() if k != "annual"},
            "turnover": turn,
            "allocation": {
                "avg_tqqq": float(a[:, 0].mean()),
                "avg_ordinary": float(a[:, 1].mean()),
                "avg_reset": float(a[:, 2].mean()),
                "avg_total_gross": float(a.sum(axis=1).mean()),
                "pct_at_100": float((a.sum(axis=1) >= 1.0 - 1e-9).mean()),
                "avg_extra_tqqq_vs_base": float((a[:, 0] - base[:, 0]).mean()),
                "max_extra_tqqq_vs_base": float((a[:, 0] - base[:, 0]).max()),
            },
        }
        pd.DataFrame({
            "date": dates,
            "return_10bp": rr,
            "alloc_tqqq": a[:, 0],
            "alloc_ordinary": a[:, 1],
            "alloc_reset": a[:, 2],
            "total_gross": a.sum(axis=1),
            "breadth_prev_close": gate_breadth.to_numpy(float),
            "nqsar_prev_close": gate_color.astype(str).to_numpy(),
            "gate_attack": gate_attack,
            "gate_attack_or_selective": gate_attack_selective,
            "base_residual_cash": residual,
        }).to_csv(out / f"daily_{name.lower()}.csv.gz", index=False, compression="gzip")

    bm = result["variants"]["BASE"]
    for name in ("ATTACK_FILL", "ATTACK_SELECTIVE_FILL"):
        vm = result["variants"][name]
        result["comparisons_vs_base"][name] = {
            "full_cagr_delta": vm["full"]["cagr"] - bm["full"]["cagr"],
            "full_mdd_delta": vm["full"]["mdd"] - bm["full"]["mdd"],
            "tax_proxy_cagr_delta": vm["tax_proxy"]["tax_proxy_cagr"] - bm["tax_proxy"]["tax_proxy_cagr"],
            "pct_months_ge7_delta": vm["monthly"]["pct_months_ge_7pct"] - bm["monthly"]["pct_months_ge_7pct"],
            "2016_2021_cagr_delta": vm["periods"]["2016_2021"]["cagr"] - bm["periods"]["2016_2021"]["cagr"],
            "2022_2026M3_cagr_delta": vm["periods"]["2022_2026M3"]["cagr"] - bm["periods"]["2022_2026M3"]["cagr"],
            "rolling2y_worst_delta": vm["rolling_2y"]["worst"] - bm["rolling_2y"]["worst"],
            "rolling2y_median_delta": vm["rolling_2y"]["median"] - bm["rolling_2y"]["median"],
            "avg_total_gross_delta": vm["allocation"]["avg_total_gross"] - bm["allocation"]["avg_total_gross"],
        }

    # Compact comparison table for artifact consumption.
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
            "avg_extra_tqqq": v["allocation"]["avg_extra_tqqq_vs_base"],
        })
    pd.DataFrame(rows).to_csv(out / "comparison.csv", index=False)
    (out / "summary.json").write_text(json.dumps(safe(result), ensure_ascii=False, indent=2), encoding="utf-8")

    print("[3/3] result", flush=True)
    print(pd.DataFrame(rows).to_string(index=False), flush=True)
    print("=== TQQQ_ATTACK_FILL_RESULT_JSON ===", flush=True)
    print(json.dumps(safe(result), ensure_ascii=False, indent=2), flush=True)
    print("=== END_TQQQ_ATTACK_FILL_RESULT_JSON ===", flush=True)


if __name__ == "__main__":
    main()
