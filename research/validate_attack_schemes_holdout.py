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
from research import nqsar_hybrid_three_role_exact as hybrid
from research import backtest_8t3i1e_vs_current_with_tqqq as frozen
from research import run_backtest_8t3i1e_tqqq_resilient as resilient
import build_v38_sleeve_live as sleeve
import build_v38_early1_live as earlylive

START = pd.Timestamp("2016-01-04")
HOLDOUT_START = pd.Timestamp("2022-01-03")
END = pd.Timestamp("2026-03-20")
COST_BPS = (0, 25)
VARIANTS = (
    "CURRENT_RULE",
    "NEW_8T3I1E",
    "MIX6C5N_E1",
    "SWITCH_BLUE_B70_RISING5",
    "SWITCH_BLUE_B80",
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


def mixed_rows(current_rows: list[dict], new_rows: list[dict]) -> list[dict]:
    lists = {"C": current_rows, "N": new_rows}
    ptr = {"C": 0, "N": 0}
    chosen: list[dict] = []
    seen: set[str] = set()
    pattern = ["C", "N"] * 6

    def take(src: str):
        arr = lists[src]
        while ptr[src] < len(arr):
            row = dict(arr[ptr[src]])
            ptr[src] += 1
            sym = str(row.get("ticker") or "")
            if not sym or sym in seen:
                continue
            seen.add(sym)
            row["mix_source"] = "CURRENT" if src == "C" else "8T3I1E"
            chosen.append(row)
            return True
        return False

    for src in pattern:
        if len(chosen) >= 12:
            break
        take(src)
    for src in ("C", "N"):
        while len(chosen) < 12 and take(src):
            pass
    for i, row in enumerate(chosen[:12], 1):
        row["final_rank"] = i
    return chosen[:12]


def simulate_variant(idx, mx, nq, e, m, variant: str) -> pd.DataFrame:
    breadth = pd.to_numeric(mx["breadth"].reindex(idx), errors="coerce")
    breadth_d5 = breadth - breadth.shift(5)
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
        cur_rows = list(c.get("candidates") or [])
        new_rows = hybrid.hybrid_rows(d, m, "HYBRID8T3I_E1")
        market = c.get("market") or {}
        mode = str(market.get("mode") or "STOP")
        color = str(nq.at[d, "nq_color"]) if d in nq.index and pd.notna(nq.at[d, "nq_color"]) else ""
        b = float(breadth.get(d, np.nan))
        b5 = float(breadth_d5.get(d, np.nan))
        choice = "CURRENT"

        if variant == "CURRENT_RULE":
            choice = "CURRENT"
        elif variant == "NEW_8T3I1E":
            c = dict(c); c["candidates"] = new_rows; choice = "8T3I1E"
        elif variant == "MIX6C5N_E1":
            c = dict(c); c["candidates"] = mixed_rows(cur_rows, new_rows); choice = "MIX6C5N"
        elif variant == "SWITCH_BLUE_B70_RISING5":
            use_current = mode == "ATTACK" and color.title() == "Blue" and np.isfinite(b) and b >= 70.0 and np.isfinite(b5) and b5 >= 0.0
            if not use_current:
                c = dict(c); c["candidates"] = new_rows; choice = "8T3I1E"
            else:
                choice = "CURRENT"
        elif variant == "SWITCH_BLUE_B80":
            use_current = mode == "ATTACK" and color.title() == "Blue" and np.isfinite(b) and b >= 80.0
            if not use_current:
                c = dict(c); c["candidates"] = new_rows; choice = "8T3I1E"
            else:
                choice = "CURRENT"
        else:
            raise ValueError(variant)

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
        rows.append({
            "date": d,
            "nav": float(state["nav"]),
            "gross_exposure": float(state.get("desired_pct") or 0.0) / 100.0,
            "positions": int(state.get("position_count") or 0),
            "turnover": float(turnover),
            "market_mode": mode,
            "nq_color": color,
            "breadth": b,
            "breadth_d5": b5,
            "engine_choice": choice,
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
    dd = eq / eq.cummax() - 1.0
    sd = float(r.std(ddof=1))
    return {
        "cagr": float(eq.iloc[-1] ** (1.0 / max(yrs, 1e-9)) - 1.0),
        "mdd": float(dd.min()),
        "sharpe": float(r.mean() / sd * np.sqrt(252)) if sd > 0 else None,
        "end_multiple": float(eq.iloc[-1]),
    }


def metric_slices(ret: pd.Series) -> list[dict]:
    periods = (
        ("HOLDOUT_2022_2026M3", HOLDOUT_START, END),
        ("2022_2023", pd.Timestamp("2022-01-03"), pd.Timestamp("2023-12-29")),
        ("2024_2026M3", pd.Timestamp("2024-01-02"), END),
    )
    out = []
    for name, a, b in periods:
        z = ret.loc[(ret.index >= a) & (ret.index <= b)]
        out.append({"period": name, **metrics(z)})
    return out


def regime_rows(stock: pd.DataFrame, variant: str) -> list[dict]:
    z = stock.loc[stock.index >= HOLDOUT_START]
    rows = []
    for mode, g in z.groupby("market_mode"):
        r = pd.to_numeric(g["return"], errors="coerce").fillna(0.0)
        rows.append({
            "variant": variant,
            "market_mode": str(mode),
            "days": int(len(g)),
            "mean_daily_return": float(r.mean()),
            "annualized_arithmetic_return": float(r.mean() * 252.0),
            "log_return_sum": float(np.log1p(r).sum()),
            "avg_gross_exposure": float(g["gross_exposure"].mean()),
        })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--tqqq-daily", required=True)
    ap.add_argument("--reset-daily", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--batch-size", type=int, default=100)
    args = ap.parse_args()
    root = Path(args.root)
    out = root / args.output
    out.mkdir(parents=True, exist_ok=True)

    audit.download_ohlcv = resilient.resilient_download_ohlcv
    resilient.patch_numpy_string_concat()

    symbols, bio = audit.load_universe(root / "universe.csv")
    allowed = earlylive._industry_symbols(root / "industry_map.json")
    early_excluded = set(bio)
    if allowed:
        early_excluded.update(set(symbols) - set(allowed))
    warm = str((START - pd.Timedelta(days=1600)).date())
    end_download = str((END + pd.Timedelta(days=1)).date())

    print("HOLDOUT_DOWNLOAD_STOCKS", flush=True)
    ohlcv, diag = audit.download_ohlcv(symbols, warm, end_download, args.batch_size)
    if float(diag.get("coverage") or 0) < 0.85:
        raise RuntimeError(diag)
    print("HOLDOUT_BUILD_INPUTS", flush=True)
    m = broad.build_inputs(ohlcv, bio)
    mx = audit.build_stock_inputs(ohlcv, bio, END)
    e = pit.early_inputs(ohlcv["close"], ohlcv["volume"], early_excluded)
    nq = audit.market_nqsar(str((START - pd.Timedelta(days=120)).date()), end_download).reindex(mx["close"].index).ffill(limit=2)
    idx = mx["close"].index[(mx["close"].index >= START) & (mx["close"].index <= END)]

    stock = {}
    for v in VARIANTS:
        print("SIM", v, flush=True)
        stock[v] = simulate_variant(idx, mx, nq, e, m, v)
        stock[v].to_csv(out / f"stock_{v}.csv.gz", compression="gzip")

    ref_cur = frozen.simulate_stock(idx, mx, nq, e, m, "CURRENT")
    ref_new = frozen.simulate_stock(idx, mx, nq, e, m, "HYBRID8T3I_E1")
    cur_err = float((stock["CURRENT_RULE"]["nav"] - ref_cur["nav"]).abs().max())
    new_err = float((stock["NEW_8T3I1E"]["nav"] - ref_new["nav"]).abs().max())
    if cur_err > 1e-10 or new_err > 1e-10:
        raise RuntimeError(f"BASE_REPRODUCTION_FAILED current={cur_err} new={new_err}")

    tq = pd.read_csv(args.tqqq_daily, compression="infer")
    tq["date"] = pd.to_datetime(tq["date"])
    reset = pd.read_csv(args.reset_daily, compression="infer")
    reset["date"] = pd.to_datetime(reset["date"])

    metric_rows = []
    regime = []
    choice_rows = []
    for v, s in stock.items():
        for rec in metric_slices(s["return"]):
            metric_rows.append({"variant": v, "scenario": "STOCK_ONLY", "timing": "NA", "cost_bps": 0, **rec})
        regime.extend(regime_rows(s, v))
        h = s.loc[s.index >= HOLDOUT_START]
        for choice, g in h.groupby("engine_choice"):
            choice_rows.append({
                "variant": v,
                "engine_choice": str(choice),
                "days": int(len(g)),
                "attack_days": int((g["market_mode"] == "ATTACK").sum()),
                "avg_breadth": float(g["breadth"].mean()),
            })

    scenarios = (("STOCK_PLUS_TQQQ", False), ("FULL_GROSS100_WITH_RESET", True))
    for scenario, include_reset in scenarios:
        for timing in ("SAME_DAY_GROSS", "LAG1_GROSS"):
            for cost in COST_BPS:
                for v in VARIANTS:
                    frame, ret = frozen.integrate(stock[v], tq, reset, include_reset=include_reset, cost_bps=cost, timing=timing)
                    frame.to_csv(out / f"integrated_{scenario}_{timing}_{cost}_{v}.csv.gz", compression="gzip")
                    for rec in metric_slices(ret):
                        metric_rows.append({"variant": v, "scenario": scenario, "timing": timing, "cost_bps": cost, **rec})

    metrics_df = pd.DataFrame(metric_rows)
    metrics_df.to_csv(out / "metrics.csv", index=False)
    pd.DataFrame(regime).to_csv(out / "stock_regime_holdout.csv", index=False)
    pd.DataFrame(choice_rows).to_csv(out / "engine_choice_holdout.csv", index=False)

    primary = metrics_df[
        (metrics_df["scenario"] == "STOCK_PLUS_TQQQ")
        & (metrics_df["timing"] == "SAME_DAY_GROSS")
        & (metrics_df["cost_bps"] == 25)
        & (metrics_df["period"] == "HOLDOUT_2022_2026M3")
    ].copy()
    primary.to_csv(out / "primary_holdout_comparison.csv", index=False)

    summary = {
        "method": "Pre-registered ATTACK role-split holdout validation. Candidate ranking engine affects only new Core fills/promotions through canonical advance_normal; existing holdings and all exits remain unchanged.",
        "holdout_start": str(HOLDOUT_START.date()),
        "holdout_end": str(END.date()),
        "variants": {
            "CURRENT_RULE": "frozen current candidates every eligible entry day",
            "NEW_8T3I1E": "frozen 8T3I1E candidates every eligible entry day",
            "MIX6C5N_E1": "alternating Current/New candidate streams; first 11 Core slots 6 Current + 5 New, slot12 New spare; original Early1 unchanged",
            "SWITCH_BLUE_B70_RISING5": "Current only when ATTACK + NQSAR Blue + Breadth>=70 + 5-session Breadth delta>=0; otherwise 8T3I1E",
            "SWITCH_BLUE_B80": "Current only when ATTACK + NQSAR Blue + Breadth>=80; otherwise 8T3I1E",
        },
        "base_reproduction_max_nav_error": {"CURRENT_RULE": cur_err, "NEW_8T3I1E": new_err},
        "coverage": diag,
        "primary": "STOCK_PLUS_TQQQ | SAME_DAY_GROSS | 25bp | HOLDOUT_2022_2026M3",
        "tqqq_source": "same frozen Stage56 M30_TOUCH30_F80_D10 / CURRENT30 artifact as prior 8T3I1E comparison",
        "reset_source": "same frozen final Gross100 Reset component as prior comparison",
        "production_changed": False,
        "strategy_files_changed_in_production": False,
    }
    (out / "summary.json").write_text(json.dumps(safe(summary), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("DONE_ATTACK_HOLDOUT", json.dumps(safe(summary), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
