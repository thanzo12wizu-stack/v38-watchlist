from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import fisher_exact

import validate_early_rotation as er
import validate_pioneer_leader as pl

HORIZONS = (5, 10, 20)
DISCOVERY_END = pd.Timestamp("2021-12-31")
CONFIRM_START = pd.Timestamp("2022-01-01")


def safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe(v) for v in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        x = float(value)
        return x if math.isfinite(x) else None
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


def quintiles(frame: pd.DataFrame) -> pd.DataFrame:
    pct = frame.rank(axis=1, pct=True, method="average")
    q = np.ceil(pct * 5.0).clip(1.0, 5.0)
    return q.where(frame.notna()).astype("float32")


def rolling_ratio(frame: pd.DataFrame, recent: int = 5, prior: int = 20) -> pd.DataFrame:
    recent_mean = frame.rolling(recent, min_periods=max(3, recent - 1)).mean()
    prior_mean = frame.shift(recent).rolling(prior, min_periods=max(10, int(prior * 0.6))).mean()
    return (recent_mean / prior_mean.replace(0.0, np.nan)).replace([np.inf, -np.inf], np.nan)


def future_mfe_mae(high: pd.DataFrame, low: pd.DataFrame, close: pd.DataFrame, horizon: int) -> tuple[np.ndarray, np.ndarray]:
    c = close.to_numpy(float)
    max_high = np.full(c.shape, np.nan, dtype=float)
    min_low = np.full(c.shape, np.nan, dtype=float)
    for k in range(1, horizon + 1):
        h = high.shift(-k).to_numpy(float)
        l = low.shift(-k).to_numpy(float)
        if k == 1:
            max_high = h.copy()
            min_low = l.copy()
        else:
            max_high = np.fmax(max_high, h)
            min_low = np.fmin(min_low, l)
    with np.errstate(divide="ignore", invalid="ignore"):
        mfe = max_high / c - 1.0
        mae = min_low / c - 1.0
    return mfe, mae


def cell_summary(mask: np.ndarray, market_excess: np.ndarray, sector_excess: np.ndarray,
                 winner: np.ndarray, mfe: np.ndarray, mae: np.ndarray) -> dict[str, Any]:
    valid = mask & np.isfinite(sector_excess) & np.isfinite(market_excess)
    n = int(valid.sum())
    if n == 0:
        return {"n": 0}
    return {
        "n": n,
        "market_excess_mean": float(np.nanmean(market_excess[valid])),
        "sector_excess_mean": float(np.nanmean(sector_excess[valid])),
        "sector_excess_median": float(np.nanmedian(sector_excess[valid])),
        "winner10_rate": float(np.nanmean(winner[valid].astype(float))),
        "mfe_mean": float(np.nanmean(mfe[valid])),
        "mae_mean": float(np.nanmean(mae[valid])),
    }


def q5_q1_test(q: np.ndarray, date_mask: np.ndarray, sector_excess: np.ndarray,
               winner: np.ndarray) -> dict[str, Any]:
    row_mask = date_mask[:, None]
    m5 = row_mask & (q == 5) & np.isfinite(sector_excess)
    m1 = row_mask & (q == 1) & np.isfinite(sector_excess)
    out: dict[str, Any] = {
        "q5_n": int(m5.sum()),
        "q1_n": int(m1.sum()),
    }
    if m5.any() and m1.any():
        out["sector_excess_q5_minus_q1"] = float(np.nanmean(sector_excess[m5]) - np.nanmean(sector_excess[m1]))
        w5 = winner[m5].astype(int)
        w1 = winner[m1].astype(int)
        out["winner10_q5_minus_q1_pp"] = float(100.0 * (w5.mean() - w1.mean()))
        _, p = fisher_exact(
            [[int(w5.sum()), int(len(w5) - w5.sum())], [int(w1.sum()), int(len(w1) - w1.sum())]],
            alternative="greater",
        )
        out["winner10_fisher_greater_p"] = float(p)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--output", required=True)
    ap.add_argument("--analysis-start", default="2016-01-04")
    ap.add_argument("--analysis-end", default="2026-06-20")
    ap.add_argument("--max-tickers", type=int, default=6000)
    ap.add_argument("--batch-size", type=int, default=75)
    args = ap.parse_args()

    root = Path(args.root)
    outdir = root / args.output
    outdir.mkdir(parents=True, exist_ok=True)

    industry_map = er.read_industry_map(root / "industry_map.json")
    universe = er.read_universe_symbols(root / "universe.csv")
    mapped = sorted(s for s in universe if s in industry_map and industry_map[s][0])
    if args.max_tickers and len(mapped) > args.max_tickers:
        mapped = mapped[: args.max_tickers]

    requested = mapped + (["SPY"] if "SPY" not in mapped else [])
    start = pd.Timestamp(args.analysis_start)
    end = pd.Timestamp(args.analysis_end)
    download_start = str((start - pd.Timedelta(days=120)).date())
    download_end = str((end + pd.Timedelta(days=60)).date())
    ohlcv, download_diag = pl.download_ohlcv(requested, download_start, download_end, args.batch_size)

    close_all = ohlcv["close"]
    if "SPY" not in close_all.columns:
        raise RuntimeError("SPY benchmark missing")
    stock_cols = [s for s in mapped if s in close_all.columns]
    close = close_all[stock_cols].copy()
    high = ohlcv["high"][stock_cols].copy()
    low = ohlcv["low"][stock_cols].copy()
    volume = ohlcv["volume"][stock_cols].copy()

    sector_groups: dict[str, list[str]] = {}
    for sym in stock_cols:
        sector = str(industry_map[sym][0])
        sector_groups.setdefault(sector, []).append(sym)
    sector_groups = {k: v for k, v in sector_groups.items() if len(v) >= 3}
    eligible = [s for s in stock_cols if str(industry_map[s][0]) in sector_groups]
    close = close[eligible]
    high = high[eligible]
    low = low[eligible]
    volume = volume[eligible]
    stock_cols = eligible

    # Deliberately simple hypothesis: follow changes in dollar-volume share only.
    dollar_volume = (close * volume).where((close > 0) & (volume >= 0))
    sector_dv = pd.DataFrame(index=close.index)
    for sector, members in sector_groups.items():
        cols = [s for s in members if s in stock_cols]
        if len(cols) >= 3:
            sector_dv[sector] = dollar_volume[cols].sum(axis=1, min_count=1)
    sector_groups = {k: [s for s in v if s in stock_cols] for k, v in sector_groups.items() if k in sector_dv.columns}

    market_dv = sector_dv.sum(axis=1, min_count=1)
    sector_share = sector_dv.div(market_dv.replace(0.0, np.nan), axis=0)
    sector_flow = rolling_ratio(sector_share, 5, 20)
    sector_q = quintiles(sector_flow)

    stock_capture = pd.DataFrame(index=close.index, columns=stock_cols, dtype="float32")
    for sector, members in sector_groups.items():
        members = [s for s in members if s in stock_cols]
        if not members:
            continue
        share = dollar_volume[members].div(sector_dv[sector].replace(0.0, np.nan), axis=0)
        stock_capture.loc[:, members] = rolling_ratio(share, 5, 20).astype("float32")
    stock_q = quintiles(stock_capture)

    sector_q_stock = pd.DataFrame(index=close.index, columns=stock_cols, dtype="float32")
    for sector, members in sector_groups.items():
        members = [s for s in members if s in stock_cols]
        if not members:
            continue
        vals = sector_q[sector].to_numpy(dtype="float32")[:, None]
        sector_q_stock.loc[:, members] = np.repeat(vals, len(members), axis=1)

    # Restrict evaluation dates only after factors are calculated.
    eval_dates = close.index[(close.index >= start) & (close.index <= end)]
    close = close.reindex(eval_dates)
    sector_q_stock = sector_q_stock.reindex(close.index)
    stock_q = stock_q.reindex(close.index)

    sq_arr = sector_q_stock.to_numpy(float)
    cq_arr = stock_q.to_numpy(float)
    dates = close.index
    split_masks = {
        "ALL": np.ones(len(dates), dtype=bool),
        "DISCOVERY_2016_2021": np.asarray(dates <= DISCOVERY_END, dtype=bool),
        "CONFIRMATION_2022_PLUS": np.asarray(dates >= CONFIRM_START, dtype=bool),
    }

    result: dict[str, Any] = {
        "status": "PRELIMINARY_FIXED_CURRENT_UNIVERSE_SIMPLE_CAPITAL_FLOW",
        "design": {
            "population": "all currently mapped stock-days; no Subtheme Momentum, RS, Stage, Base or EPS gate",
            "sector_flow": "Sector dollar-volume share of mapped market: recent 5d mean / prior 20d mean",
            "stock_capture": "Stock dollar-volume share within its Sector: recent 5d mean / prior 20d mean",
            "ranking": "daily cross-sectional quintiles; no optimized thresholds",
            "winner10": "at each stated horizon, stock return minus equal-weight same-Sector peers >= +10%",
            "market_excess": "stock forward return minus SPY forward return",
            "sector_excess": "stock forward return minus equal-weight same-Sector constituent forward return excluding the stock",
            "warning": "current universe and current Sector mapping are applied retrospectively",
        },
        "coverage": {
            "mapped_requested": len(mapped),
            "download": download_diag,
            "stocks": len(stock_cols),
            "sectors": len(sector_groups),
            "sector_member_counts": {k: len(v) for k, v in sorted(sector_groups.items())},
            "evaluation_start": str(dates.min().date()),
            "evaluation_end": str(dates.max().date()),
            "evaluation_days": len(dates),
        },
        "horizons": {},
    }

    # Full downloaded matrices retain future observations after analysis_end.
    close_full = close_all[stock_cols]
    high_full = ohlcv["high"][stock_cols]
    low_full = ohlcv["low"][stock_cols]
    spy_full = close_all["SPY"]

    for h in HORIZONS:
        print(f"HORIZON {h}", flush=True)
        stock_fwd_full = close_full.shift(-h) / close_full - 1.0
        stock_fwd = stock_fwd_full.reindex(dates)
        spy_fwd = (spy_full.shift(-h) / spy_full - 1.0).reindex(dates)
        market_excess = stock_fwd.sub(spy_fwd, axis=0).to_numpy(float)

        peer = pd.DataFrame(index=dates, columns=stock_cols, dtype="float64")
        for sector, members in sector_groups.items():
            members = [s for s in members if s in stock_cols]
            if len(members) < 3:
                continue
            part = stock_fwd[members]
            sums = part.sum(axis=1, skipna=True)
            counts = part.notna().sum(axis=1)
            for sym in members:
                sr = part[sym]
                denom = counts - sr.notna().astype(int)
                peer[sym] = (sums - sr.fillna(0.0)) / denom.replace(0, np.nan)
        sector_excess = (stock_fwd - peer).to_numpy(float)
        winner = sector_excess >= 0.10

        mfe_full, mae_full = future_mfe_mae(high_full, low_full, close_full, h)
        pos = pd.Series(np.arange(len(close_full.index)), index=close_full.index).reindex(dates).to_numpy(dtype=int)
        mfe = mfe_full[pos, :]
        mae = mae_full[pos, :]

        hres: dict[str, Any] = {"splits": {}}
        for split_name, dmask in split_masks.items():
            sres: dict[str, Any] = {"sector_flow_quintile": {}, "stock_capture_quintile": {}, "matrix_5x5": {}}
            row_mask = dmask[:, None]
            for q in range(1, 6):
                sm = row_mask & (sq_arr == q)
                cm = row_mask & (cq_arr == q)
                sres["sector_flow_quintile"][str(q)] = cell_summary(sm, market_excess, sector_excess, winner, mfe, mae)
                sres["stock_capture_quintile"][str(q)] = cell_summary(cm, market_excess, sector_excess, winner, mfe, mae)
            sres["sector_flow_q5_vs_q1"] = q5_q1_test(sq_arr, dmask, sector_excess, winner)
            sres["stock_capture_q5_vs_q1"] = q5_q1_test(cq_arr, dmask, sector_excess, winner)

            for qs in range(1, 6):
                for qc in range(1, 6):
                    m = row_mask & (sq_arr == qs) & (cq_arr == qc)
                    sres["matrix_5x5"][f"S{qs}_C{qc}"] = cell_summary(m, market_excess, sector_excess, winner, mfe, mae)
            hres["splits"][split_name] = sres
        result["horizons"][str(h)] = hres

    result["factor_diagnostics"] = {
        "sector_flow_ratio_quantiles": safe(sector_flow.stack().quantile([0.05, 0.2, 0.5, 0.8, 0.95]).to_dict()),
        "stock_capture_ratio_quantiles": safe(stock_capture.stack().quantile([0.05, 0.2, 0.5, 0.8, 0.95]).to_dict()),
    }

    (outdir / "simple_capital_flow_result.json").write_text(json.dumps(safe(result), ensure_ascii=False, indent=2), encoding="utf-8")
    sector_flow.to_csv(outdir / "sector_flow_ratio.csv")
    sector_q.to_csv(outdir / "sector_flow_quintile.csv")
    print("RESULT_JSON=" + json.dumps(safe(result), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
