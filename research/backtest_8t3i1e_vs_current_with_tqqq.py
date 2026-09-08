from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from research import audit_stock_nqsar_theme30_pit as audit
from research import preimpl_core11_early1_pit as pit
from research import nqsar_centric_broad_scan as broad
from research import nqsar_exact_reconciled_final as exact
from research import nqsar_hybrid_three_role_exact as hybrid
import build_v38_sleeve_live as sleeve
import build_v38_early1_live as earlylive
from v38_rules import gross100_allocation

START = pd.Timestamp("2016-01-04")
END = pd.Timestamp("2026-03-20")
COST_BPS = (0, 25)
VARIANTS = (
    ("CURRENT_RULE", "CURRENT"),
    ("NEW_8T3I1E", "HYBRID8T3I_E1"),
)


def safe(x):
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
        return str(x.date())
    return x


def px(frame: pd.DataFrame, d: pd.Timestamp, s: str) -> float:
    try:
        z = float(frame.at[d, s])
        return z if np.isfinite(z) and z > 0 else np.nan
    except Exception:
        return np.nan


def simulate_stock(idx, mx, nq, e, m, kind: str) -> pd.DataFrame:
    first = pd.Timestamp(idx[0])
    state = {
        "status": "READY",
        "asof": str(first.date()),
        "cash": 1.0,
        "positions": [],
        "pending": {"full_exits": [], "partial25": [], "entries": []},
    }
    rows = []
    for d0 in idx:
        d = pd.Timestamp(d0)
        before = {str(p.get("symbol")): float(p.get("shares") or 0.0) for p in state.get("positions", [])}
        cash_before = float(state.get("cash") or 0.0)
        nav_open = cash_before
        for s, sh in before.items():
            p = px(mx["open"], d, s)
            if np.isfinite(p):
                nav_open += sh * p

        c = pit.companion(d, mx, {}, nq, e, True)
        if kind != "CURRENT":
            c = dict(c)
            c["candidates"] = hybrid.hybrid_rows(d, m, kind)
        state = sleeve.advance_normal(state, c, str(d.date()), mx["open"], mx["close"])

        after = {str(p.get("symbol")): float(p.get("shares") or 0.0) for p in state.get("positions", [])}
        buy_notional = sell_notional = 0.0
        for s in set(before) | set(after):
            delta = after.get(s, 0.0) - before.get(s, 0.0)
            if abs(delta) <= 1e-14:
                continue
            p = px(mx["open"], d, s)
            if not np.isfinite(p):
                continue
            notional = abs(delta) * p
            if delta > 0:
                buy_notional += notional
            else:
                sell_notional += notional
        turnover = (buy_notional + sell_notional) / max(nav_open, 1e-12)
        market = c.get("market") or {}
        rows.append({
            "date": d,
            "nav": float(state["nav"]),
            "gross_exposure": float(state.get("desired_pct") or 0.0) / 100.0,
            "positions": int(state.get("position_count") or 0),
            "turnover": float(turnover),
            "market_mode": str(market.get("mode") or "STOP"),
        })
    out = pd.DataFrame(rows).set_index("date")
    out["return"] = out["nav"].pct_change(fill_method=None).fillna(0.0)
    return out


def metrics(ret: pd.Series) -> dict:
    r = pd.to_numeric(ret, errors="coerce").fillna(0.0)
    if len(r) < 2:
        return {"cagr": None, "mdd": None, "sharpe": None, "end_multiple": None}
    eq = (1.0 + r).cumprod()
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = float(eq.iloc[-1] ** (1 / max(yrs, 1e-9)) - 1.0)
    mdd = float((eq / eq.cummax() - 1.0).min())
    sd = float(r.std(ddof=1))
    sharpe = float(r.mean() / sd * np.sqrt(252)) if sd > 0 else None
    return {"cagr": cagr, "mdd": mdd, "sharpe": sharpe, "end_multiple": float(eq.iloc[-1])}


def period_metrics(ret: pd.Series) -> list[dict]:
    periods = [
        ("FULL_2016_2026M3", START, END),
        ("2016_2021", START, pd.Timestamp("2021-12-31")),
        ("2022_2023", pd.Timestamp("2022-01-01"), pd.Timestamp("2023-12-31")),
        ("2024_2026M3", pd.Timestamp("2024-01-01"), END),
    ]
    rows = []
    for name, a, b in periods:
        z = ret.loc[(ret.index >= a) & (ret.index <= b)]
        rows.append({"period": name, **metrics(z)})
    return rows


def annual_rows(name: str, scenario: str, cost_bps: int, ret: pd.Series) -> list[dict]:
    rows = []
    for y, g in ret.groupby(ret.index.year):
        if len(g) < 2:
            continue
        rows.append({
            "variant": name,
            "scenario": scenario,
            "cost_bps": cost_bps,
            "year": int(y),
            "return": float((1.0 + g).prod() - 1.0),
        })
    return rows


def block_prob(a: pd.Series, b: pd.Series, block: int = 20, sims: int = 5000, seed: int = 20260908) -> float | None:
    x = (a - b).dropna().to_numpy(float)
    n = len(x)
    if n < block:
        return None
    rng = np.random.default_rng(seed + block)
    starts = np.arange(n - block + 1)
    wins = 0
    for _ in range(sims):
        z = []
        while len(z) < n:
            st = int(rng.choice(starts))
            z.extend(x[st:st + block])
        wins += float(np.mean(z[:n]) > 0)
    return wins / sims


def integrate(
    stock: pd.DataFrame,
    tq: pd.DataFrame,
    reset: pd.DataFrame | None,
    *,
    include_reset: bool,
    cost_bps: int,
    timing: str,
) -> tuple[pd.DataFrame, pd.Series]:
    d = stock.reset_index().merge(tq, on="date", how="inner").sort_values("date")
    if include_reset:
        if reset is None:
            raise RuntimeError("RESET_COMPONENT_REQUIRED")
        d = d.merge(reset[["date", "gross_exposure", "return"]].rename(
            columns={"gross_exposure": "reset_gross", "return": "reset_return"}
        ), on="date", how="inner")
    else:
        d["reset_gross"] = 0.0
        d["reset_return"] = 0.0
    d = d[(d["date"] >= START) & (d["date"] <= END)].copy().reset_index(drop=True)

    # Preserve the frozen Stage56 research timing convention used by the prior Gross100 audit.
    desired_t = np.zeros(len(d), float)
    native_t = np.zeros(len(d), float)
    target = d["target_M30_TOUCH30_F80_D10"].to_numpy(float)
    native = d["target_CURRENT30"].to_numpy(float)
    if len(d) > 2:
        desired_t[2:] = target[:-2]
        native_t[2:] = native[:-2]

    desired_o = d["gross_exposure"].to_numpy(float)
    desired_r = d["reset_gross"].to_numpy(float)
    modes = d["market_mode"].astype(str).to_numpy(object)
    if timing == "LAG1_GROSS":
        desired_o = np.r_[0.0, desired_o[:-1]]
        desired_r = np.r_[0.0, desired_r[:-1]]
        modes = np.r_["STOP", modes[:-1]]
    elif timing != "SAME_DAY_GROSS":
        raise ValueError(timing)

    alloc_t = np.zeros(len(d), float)
    alloc_o = np.zeros(len(d), float)
    alloc_r = np.zeros(len(d), float)
    fill = np.zeros(len(d), float)
    for i in range(len(d)):
        a = gross100_allocation(
            float(desired_r[i]), float(desired_t[i]), float(desired_o[i]),
            market_mode_name=str(modes[i]),
            native_tqqq_target=float(native_t[i]),
            apply_selective_fill=True,
        )
        alloc_t[i] = a.tqqq_allocated
        alloc_o[i] = a.normal_stock_allocated
        alloc_r[i] = a.reset_allocated
        fill[i] = a.selective_fill
        if a.gross_allocated > 1.0000001 or alloc_o[i] > 0.7000001:
            raise RuntimeError("GROSS100_INVARIANT_FAILED")
        if native_t[i] <= 0 and fill[i] > 1e-12:
            raise RuntimeError("SELECTIVE_FILL_OVERRODE_NATIVE_ZERO")

    stock_ret = d["return"].to_numpy(float)
    if cost_bps > 0:
        stock_ret = stock_ret - (float(cost_bps) / 10000.0) * d["turnover"].to_numpy(float)
    reset_ret = d["reset_return"].to_numpy(float)
    t_ret = d["tqqq_ret_usd"].to_numpy(float)

    scale_o = np.divide(alloc_o, desired_o, out=np.zeros(len(d), float), where=desired_o > 1e-12)
    scale_r = np.divide(alloc_r, desired_r, out=np.zeros(len(d), float), where=desired_r > 1e-12)
    ret = alloc_t * t_ret + scale_o * stock_ret + scale_r * reset_ret

    turn_t = np.r_[0.0, np.abs(np.diff(alloc_t))]
    turn_o = np.r_[0.0, np.abs(np.diff(alloc_o))]
    turn_r = np.r_[0.0, np.abs(np.diff(alloc_r))]
    if cost_bps == 0:
        # Match the frozen Gross100 base convention: 5bp on TQQQ allocation turnover.
        ret = ret - turn_t * (5.0 / 10000.0)
    else:
        # Conservative master-allocation turnover stress in addition to stock-internal turnover above.
        ret = ret - (turn_t + turn_o + turn_r) * (float(cost_bps) / 10000.0)

    out = pd.DataFrame({
        "date": pd.to_datetime(d["date"]),
        "return": ret,
        "alloc_tqqq": alloc_t,
        "alloc_stock": alloc_o,
        "alloc_reset": alloc_r,
        "selective_fill": fill,
        "total_gross": alloc_t + alloc_o + alloc_r,
        "stock_desired": desired_o,
        "tqqq_desired": desired_t,
        "tqqq_native": native_t,
        "market_mode": modes,
    }).set_index("date")
    return out, out["return"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--tqqq-daily", required=True)
    ap.add_argument("--reset-daily", default=None)
    ap.add_argument("--output", required=True)
    ap.add_argument("--batch-size", type=int, default=100)
    args = ap.parse_args()
    root = Path(args.root)
    out = root / args.output
    out.mkdir(parents=True, exist_ok=True)

    symbols, bio = audit.load_universe(root / "universe.csv")
    allowed = earlylive._industry_symbols(root / "industry_map.json")
    early_excluded = set(bio)
    if allowed:
        early_excluded.update(set(symbols) - set(allowed))
    warm = str((START - pd.Timedelta(days=1600)).date())
    end_download = str((END + pd.Timedelta(days=1)).date())
    print("DOWNLOAD_STOCKS", flush=True)
    ohlcv, diag = audit.download_ohlcv(symbols, warm, end_download, args.batch_size)
    if diag["coverage"] < 0.85:
        raise RuntimeError(diag)
    print("BUILD_STOCK_INPUTS", flush=True)
    m = broad.build_inputs(ohlcv, bio)
    mx = audit.build_stock_inputs(ohlcv, bio, END)
    e = pit.early_inputs(ohlcv["close"], ohlcv["volume"], early_excluded)
    nq = audit.market_nqsar(str((START - pd.Timedelta(days=120)).date()), end_download).reindex(mx["close"].index).ffill(limit=2)
    idx = mx["close"].index[(mx["close"].index >= START) & (mx["close"].index <= END)]

    stock_results = {}
    for name, kind in VARIANTS:
        print("SIM_STOCK", name, flush=True)
        s = simulate_stock(idx, mx, nq, e, m, kind)
        stock_results[name] = s
        s.to_csv(out / f"stock_component_{name}.csv.gz", compression="gzip")

    if not stock_results["CURRENT_RULE"]["market_mode"].equals(stock_results["NEW_8T3I1E"]["market_mode"]):
        raise RuntimeError("MARKET_MODE_CHANGED_BETWEEN_STOCK_VARIANTS")

    tq = pd.read_csv(args.tqqq_daily, compression="infer")
    tq["date"] = pd.to_datetime(tq["date"])
    need_tq = {"date", "tqqq_ret_usd", "target_CURRENT30", "target_M30_TOUCH30_F80_D10"}
    if not need_tq.issubset(tq.columns):
        raise RuntimeError(f"TQQQ_COLUMNS_REQUIRED missing={sorted(need_tq - set(tq.columns))}")
    reset = None
    if args.reset_daily:
        reset = pd.read_csv(args.reset_daily, compression="infer")
        reset["date"] = pd.to_datetime(reset["date"])

    metric_rows = []
    annual = []
    daily_series = {}
    allocation_rows = []
    scenarios = (("STOCK_PLUS_TQQQ", False), ("FULL_GROSS100_WITH_RESET", True)) if reset is not None else (("STOCK_PLUS_TQQQ", False),)
    for scenario, include_reset in scenarios:
        for timing in ("SAME_DAY_GROSS", "LAG1_GROSS"):
            for cost in COST_BPS:
                for name, _ in VARIANTS:
                    frame, ret = integrate(stock_results[name], tq, reset, include_reset=include_reset, cost_bps=cost, timing=timing)
                    key = f"{scenario}|{timing}|{cost}|{name}"
                    daily_series[key] = ret
                    frame.to_csv(out / f"integrated_{scenario}_{timing}_{cost}_{name}.csv.gz", compression="gzip")
                    for rec in period_metrics(ret):
                        metric_rows.append({"variant": name, "scenario": scenario, "timing": timing, "cost_bps": cost, **rec})
                    annual.extend(annual_rows(name, scenario + "|" + timing, cost, ret))
                    allocation_rows.append({
                        "variant": name,
                        "scenario": scenario,
                        "timing": timing,
                        "cost_bps": cost,
                        "avg_tqqq": float(frame["alloc_tqqq"].mean()),
                        "avg_stock": float(frame["alloc_stock"].mean()),
                        "avg_reset": float(frame["alloc_reset"].mean()),
                        "avg_total_gross": float(frame["total_gross"].mean()),
                        "pct_gross_100": float((frame["total_gross"] >= 1.0 - 1e-9).mean()),
                        "avg_selective_fill": float(frame["selective_fill"].mean()),
                        "max_stock": float(frame["alloc_stock"].max()),
                        "max_tqqq": float(frame["alloc_tqqq"].max()),
                    })

    metrics_df = pd.DataFrame(metric_rows)
    metrics_df.to_csv(out / "integrated_metrics.csv", index=False)
    annual_df = pd.DataFrame(annual)
    annual_df.to_csv(out / "annual_returns.csv", index=False)
    pd.DataFrame(allocation_rows).to_csv(out / "allocation_summary.csv", index=False)

    comparisons = []
    for scenario, _ in scenarios:
        for timing in ("SAME_DAY_GROSS", "LAG1_GROSS"):
            for cost in COST_BPS:
                cur = daily_series[f"{scenario}|{timing}|{cost}|CURRENT_RULE"]
                new = daily_series[f"{scenario}|{timing}|{cost}|NEW_8T3I1E"]
                common = cur.index.intersection(new.index)
                cur = cur.reindex(common)
                new = new.reindex(common)
                comparisons.append({
                    "scenario": scenario,
                    "timing": timing,
                    "cost_bps": cost,
                    "days": len(common),
                    "block20_prob_new_daily_mean_gt_current": block_prob(new, cur, 20),
                    "new_minus_current_total_log_return": float(np.log1p(new).sum() - np.log1p(cur).sum()),
                })
    pd.DataFrame(comparisons).to_csv(out / "comparison_robustness.csv", index=False)

    # Build explicit delta table for easy reading.
    delta_rows = []
    keys = ["cagr", "mdd", "sharpe", "end_multiple"]
    for (scenario, timing, cost, period), g in metrics_df.groupby(["scenario", "timing", "cost_bps", "period"]):
        z = g.set_index("variant")
        if not {"CURRENT_RULE", "NEW_8T3I1E"}.issubset(z.index):
            continue
        rec = {"scenario": scenario, "timing": timing, "cost_bps": cost, "period": period}
        for k in keys:
            rec[f"current_{k}"] = z.at["CURRENT_RULE", k]
            rec[f"new_{k}"] = z.at["NEW_8T3I1E", k]
            rec[f"delta_{k}"] = z.at["NEW_8T3I1E", k] - z.at["CURRENT_RULE", k]
        delta_rows.append(rec)
    pd.DataFrame(delta_rows).to_csv(out / "delta_summary.csv", index=False)

    summary = {
        "method": "Exact current Normal Stock vs exact 8T3I1E Normal Stock, each integrated with the same frozen Stage56 M30_TOUCH30_F80_D10 TQQQ daily target. Canonical 2026-09-01 Gross100 allocator with Selective Fill is used. Primary scenario excludes RSI Reset to isolate the requested Stock+TQQQ comparison; secondary scenario restores the same frozen final Reset component to both sides.",
        "coverage": {"start": str(START.date()), "end": str(END.date()), "stock_download": diag},
        "tqqq_source": "Frozen tqqq_stage56_daily.csv.gz from Actions run 33080590798; exact prior research Stage56 series, target effective lag2 convention.",
        "reset_source": "Frozen final Reset component from Gross100 run 33405477190 when supplied.",
        "costs": {"0": "Base: TQQQ allocation turnover 5bp as prior Gross100 audit; stock component has no added cost.", "25": "Stock internal executed-share turnover 25bp plus conservative master allocation turnover 25bp; frozen Reset keeps its generated internal cost."},
        "timing": {"SAME_DAY_GROSS": "Primary, same convention as prior Gross100 audit.", "LAG1_GROSS": "Sensitivity: stock/reset desired gross and market mode lagged one session."},
        "invariants": {"same_market_mode": True, "same_tqqq_rule": True, "same_tqqq_returns": True, "same_reset_when_included": True, "normal_stock_cap": 0.70, "gross_cap": 1.0, "native_tqqq_zero_not_overridden": True},
        "production_changed": False,
    }
    (out / "summary.json").write_text(json.dumps(safe(summary), ensure_ascii=False, indent=2), encoding="utf-8")
    print("DONE_INTEGRATED_CURRENT_VS_8T3I1E", flush=True)


if __name__ == "__main__":
    main()
