from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf

SECTORS = ["XLB", "XLC", "XLE", "XLF", "XLI", "XLK", "XLP", "XLRE", "XLU", "XLV", "XLY"]
ASSETS = SECTORS + ["SPY"]
COST_BPS = (0, 5, 10)
VARIANTS = {
    "SECTOR_EW_BASE": "BASE",
    "EXCLUDE_W20_TO_SPY": "W20",
    "EXCLUDE_W20_FLOWOUT_TO_SPY": "W20_FLOW",
    "EXCLUDE_DISTRIBUTION_TRAP_TO_SPY": "DIST_TRAP",
}
START = pd.Timestamp("2022-04-18")
CONFIRM = pd.Timestamp("2024-01-01")
RECENT = pd.Timestamp("2025-01-01")


def safe(v: Any) -> Any:
    if isinstance(v, dict):
        return {str(k): safe(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [safe(x) for x in v]
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        x = float(v)
        return x if math.isfinite(x) else None
    if isinstance(v, pd.Timestamp):
        return v.isoformat()
    return v


def metrics(eq: pd.Series) -> dict[str, Any]:
    e = pd.to_numeric(eq, errors="coerce").dropna()
    if len(e) < 5:
        return {"n": int(len(e))}
    r = e.pct_change(fill_method=None).dropna()
    years = max(len(r) / 252.0, 1.0 / 252.0)
    cagr = float((e.iloc[-1] / e.iloc[0]) ** (1.0 / years) - 1.0) if e.iloc[0] > 0 else np.nan
    dd = e / e.cummax() - 1.0
    sd = float(r.std(ddof=1)) if len(r) > 1 else np.nan
    sharpe = float(r.mean() / sd * np.sqrt(252.0)) if np.isfinite(sd) and sd > 0 else np.nan
    return {
        "n": int(len(e)),
        "total_return": float(e.iloc[-1] / e.iloc[0] - 1.0),
        "cagr": cagr,
        "mdd": float(dd.min()),
        "sharpe": sharpe,
    }


def slices(eq: pd.Series) -> dict[str, Any]:
    return {
        "2022_plus": metrics(eq.loc[eq.index >= START]),
        "discovery_2022_2023": metrics(eq.loc[(eq.index >= START) & (eq.index < CONFIRM)]),
        "confirmation_2024_plus": metrics(eq.loc[eq.index >= CONFIRM]),
        "recent_2025_plus": metrics(eq.loc[eq.index >= RECENT]),
    }


def annual_returns(eq: pd.Series) -> dict[str, float | None]:
    e = eq.dropna()
    out: dict[str, float | None] = {}
    for year, g in e.groupby(e.index.year):
        if len(g) < 2:
            out[str(year)] = None
        else:
            out[str(year)] = float(g.iloc[-1] / g.iloc[0] - 1.0)
    return out


def block_win(a: pd.Series, b: pd.Series, start: pd.Timestamp, seed: int, reps: int = 5000, block: int = 20) -> float | None:
    aa = a.loc[a.index >= start]
    bb = b.reindex(aa.index)
    x = pd.concat([aa.pct_change(fill_method=None).rename("a"), bb.pct_change(fill_method=None).rename("b")], axis=1).dropna()
    if len(x) < block * 5:
        return None
    d = np.log1p(x["a"].clip(lower=-0.999999)).to_numpy() - np.log1p(x["b"].clip(lower=-0.999999)).to_numpy()
    starts = np.arange(0, len(d) - block + 1)
    rng = np.random.default_rng(seed)
    wins = 0
    for _ in range(reps):
        out: list[float] = []
        while len(out) < len(d):
            s = int(rng.choice(starts))
            out.extend(d[s:s + block])
        wins += float(np.sum(out[:len(d)])) > 0.0
    return float(wins / reps)


def download_open(start: str, end: str) -> pd.DataFrame:
    raw = yf.download(
        tickers=ASSETS,
        start=start,
        end=end,
        auto_adjust=True,
        actions=False,
        progress=False,
        group_by="column",
        threads=True,
    )
    if raw.empty:
        raise RuntimeError("ETF price download empty")
    if isinstance(raw.columns, pd.MultiIndex):
        if "Open" in raw.columns.get_level_values(0):
            op = raw["Open"].copy()
        else:
            raise RuntimeError("Open field missing")
    else:
        raise RuntimeError("unexpected single-ticker price shape")
    op.index = pd.to_datetime(op.index).tz_localize(None).normalize()
    op = op.reindex(columns=ASSETS).apply(pd.to_numeric, errors="coerce")
    if op[ASSETS].notna().sum().min() < 500:
        raise RuntimeError(f"ETF history coverage too low: {op.notna().sum().to_dict()}")
    return op


def load_panel(path: Path) -> pd.DataFrame:
    p = pd.read_csv(path)
    p["date"] = pd.to_datetime(p["date"]).dt.tz_localize(None).dt.normalize()
    for c in ("price_score", "internal_score", "internal_delta20", "flow20_pct_aum"):
        p[c] = pd.to_numeric(p[c], errors="coerce")
    p = p[p["sector"].isin(SECTORS)].copy()
    p = p.sort_values(["date", "sector"]).drop_duplicates(["date", "sector"], keep="last")
    return p


def warning_sets(panel: pd.DataFrame, kind: str) -> dict[pd.Timestamp, set[str]]:
    p = panel.copy()
    if kind == "BASE":
        mask = pd.Series(False, index=p.index)
    elif kind == "W20":
        mask = (p["price_score"] >= 70.0) & (p["internal_delta20"] <= -20.0)
    elif kind == "W20_FLOW":
        mask = (p["price_score"] >= 70.0) & (p["internal_delta20"] <= -20.0) & (p["flow20_pct_aum"] <= 0.0)
    elif kind == "DIST_TRAP":
        mask = (p["price_score"] >= 70.0) & (p["internal_score"] < 50.0) & (p["flow20_pct_aum"] <= 0.0)
    else:
        raise ValueError(kind)
    q = p[mask].groupby("date", observed=True)["sector"].agg(lambda x: set(map(str, x)))
    return {pd.Timestamp(d): set(v) for d, v in q.items()}


def target_weights(warned: set[str]) -> pd.Series:
    w = pd.Series(0.0, index=ASSETS, dtype=float)
    unit = 1.0 / len(SECTORS)
    for s in SECTORS:
        if s not in warned:
            w[s] = unit
    w["SPY"] = unit * len(warned)
    return w


def simulate(open_px: pd.DataFrame, panel: pd.DataFrame, kind: str, cost_bps: int) -> dict[str, Any]:
    sig = warning_sets(panel, kind)
    dates = open_px.index[(open_px.index >= START) & (open_px.index <= pd.Timestamp("2026-06-30"))]
    dates = dates[open_px.loc[dates, ASSETS].notna().all(axis=1)]
    if len(dates) < 500:
        raise RuntimeError("aligned ETF calendar too short")

    nav = 1.0
    eq: dict[pd.Timestamp, float] = {pd.Timestamp(dates[0]): nav}
    prev_w: pd.Series | None = None
    traded_notional = 0.0
    warning_asset_days = 0
    rebalance_days = 0
    warning_count_by_day: list[int] = []

    for i in range(1, len(dates) - 1):
        trade_day = pd.Timestamp(dates[i])
        signal_day = pd.Timestamp(dates[i - 1])
        next_open_day = pd.Timestamp(dates[i + 1])
        warned = sig.get(signal_day, set())
        warning_count_by_day.append(len(warned))
        warning_asset_days += len(warned)
        w = target_weights(warned)

        if prev_w is None:
            prev_w = w.copy()
        else:
            delta = (w - prev_w).abs()
            gross_trade_fraction = float(delta.sum())
            if gross_trade_fraction > 1e-12:
                rebalance_days += 1
                traded_notional += gross_trade_fraction
                nav *= max(0.0, 1.0 - gross_trade_fraction * cost_bps / 10000.0)
            prev_w = w.copy()

        r = open_px.loc[next_open_day, ASSETS] / open_px.loc[trade_day, ASSETS] - 1.0
        port_ret = float((w * r).sum())
        nav *= 1.0 + port_ret
        eq[next_open_day] = nav

    s = pd.Series(eq, dtype=float).sort_index()
    yrs = max((s.index[-1] - s.index[0]).days / 365.25, 1e-9) if len(s) > 1 else np.nan
    return {
        "equity": s,
        "metrics": slices(s),
        "annual_returns": annual_returns(s),
        "diagnostics": {
            "cost_bps_per_traded_dollar": int(cost_bps),
            "rebalance_days": int(rebalance_days),
            "gross_traded_notional_fraction_sum": float(traded_notional),
            "annualized_gross_traded_notional_fraction": float(traded_notional / yrs) if np.isfinite(yrs) else None,
            "warning_asset_days": int(warning_asset_days),
            "mean_warned_sectors_per_day": float(np.mean(warning_count_by_day)) if warning_count_by_day else 0.0,
            "days_with_any_warning": int(sum(x > 0 for x in warning_count_by_day)),
        },
    }


def spy_equity(open_px: pd.DataFrame) -> pd.Series:
    dates = open_px.index[(open_px.index >= START) & (open_px.index <= pd.Timestamp("2026-06-30"))]
    x = open_px.loc[dates, "SPY"].dropna()
    if len(x) < 2:
        return pd.Series(dtype=float)
    return (x / x.iloc[0]).rename("equity")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel", type=Path, required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    panel = load_panel(args.panel)
    open_px = download_open("2022-04-01", "2026-07-02")
    spy_eq = spy_equity(open_px)

    sims: dict[str, dict[int, dict[str, Any]]] = {}
    for name, kind in VARIANTS.items():
        sims[name] = {}
        for c in COST_BPS:
            print(f"SIM {name} cost={c}bp", flush=True)
            sim = simulate(open_px, panel, kind, c)
            sims[name][c] = sim
            sim["equity"].rename("equity").to_csv(out / f"equity_{name}_{c}bp.csv")

    result: dict[str, Any] = {
        "status": "ROTATION_SECTOR_ALLOCATION_RESEARCH",
        "research_only": True,
        "question": "Do validated Rotation deterioration warnings improve an 11-sector ETF allocation if warned sector weight is moved to SPY rather than cash?",
        "execution": "Prior session close signal; target applies from next open to following open. No same-close execution.",
        "baseline": "Constant 1/11 target weight in each of 11 SPDR sector ETFs; no SPY allocation.",
        "fallback": "Each warned sector's 1/11 target weight is moved to SPY; other sector target weights are unchanged.",
        "spy_benchmark": {"metrics": slices(spy_eq), "annual_returns": annual_returns(spy_eq)},
        "variants": {},
        "guardrails": [
            "No stock selection, V38 entry/exit, Command Center, Leadership, or production files are modified.",
            "Only thresholds already studied in strict PIT research are tested; there is no threshold grid search here.",
            "Transaction costs are stressed at 0, 5, and 10 bp per traded dollar, charged only when warning-driven target weights change.",
            "This is a separate sector-allocation research sleeve, not evidence for selling individual leaders.",
        ],
    }

    base0 = sims["SECTOR_EW_BASE"][0]["equity"]
    for i, (name, by_cost) in enumerate(sims.items()):
        result["variants"][name] = {}
        for c, sim in by_cost.items():
            item = {
                "metrics": sim["metrics"],
                "annual_returns": sim["annual_returns"],
                "diagnostics": sim["diagnostics"],
            }
            if name != "SECTOR_EW_BASE":
                item["block20_win_probability_vs_sector_ew"] = {
                    "2022_plus": block_win(sim["equity"], base0, START, 610000 + i * 100 + c),
                    "2024_plus": block_win(sim["equity"], base0, CONFIRM, 620000 + i * 100 + c),
                    "2025_plus": block_win(sim["equity"], base0, RECENT, 630000 + i * 100 + c),
                }
                item["block20_win_probability_vs_spy"] = {
                    "2022_plus": block_win(sim["equity"], spy_eq, START, 640000 + i * 100 + c),
                    "2024_plus": block_win(sim["equity"], spy_eq, CONFIRM, 650000 + i * 100 + c),
                    "2025_plus": block_win(sim["equity"], spy_eq, RECENT, 660000 + i * 100 + c),
                }
            result["variants"][name][f"{c}bp"] = item

    (out / "summary_rotation_sector_allocation.json").write_text(json.dumps(safe(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== ROTATION_SECTOR_ALLOCATION_JSON ===", flush=True)
    print(json.dumps(safe(result), ensure_ascii=False, indent=2), flush=True)
    print("=== END_ROTATION_SECTOR_ALLOCATION_JSON ===", flush=True)


if __name__ == "__main__":
    main()
