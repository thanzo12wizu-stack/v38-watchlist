from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import build_dashboard as bd
from research import stock_mtf_nqsar_backtest as base

LABELS = {
    "V0": "BASE_RS189",
    "V1_WEEK": "STOCK_NQSAR_WEEK_BULL",
    "V2_MONTH": "STOCK_NQSAR_MONTH_BULL",
    "V3_ALIGN": "STOCK_NQSAR_WEEK_MONTH_BULL",
    "V4_BULL_BULL_GATE": "STOCK_NQSAR_WEEK_MONTH_BULL_GATE",
    "V5_BEAR_BEAR_EXCLUDE": "STOCK_NQSAR_BOTH_RED_EXCLUDE_PLUS_BULL_PRIORITY",
}


def exact_nqsar_flags(high: pd.DataFrame, low: pd.DataFrame, close: pd.DataFrame, min_rows: int = 30) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    bull = pd.DataFrame(False, index=close.index, columns=close.columns, dtype=bool)
    red = pd.DataFrame(False, index=close.index, columns=close.columns, dtype=bool)
    good = 0
    for j, sym in enumerate(close.columns, 1):
        z = pd.DataFrame({"h": high[sym], "l": low[sym], "c": close[sym]}).dropna()
        if len(z) < min_rows:
            continue
        h = z.h.to_numpy(float)
        l = z.l.to_numpy(float)
        c = z.c.to_numpy(float)
        sar = bd._psar(h, l, c, step=0.02, mx=0.08)
        ema21 = z.c.ewm(span=21, adjust=False).mean().to_numpy(float)
        d = z.c.diff()
        up = d.clip(lower=0)
        dn = -d.clip(upper=0)
        ru = up.ewm(alpha=1 / 14, adjust=False).mean()
        rd = dn.ewm(alpha=1 / 14, adjust=False).mean()
        rsi = (100.0 - 100.0 / (1.0 + ru / rd)).to_numpy(float)
        bd._onimine_state(c, sar, ema21, rsi)
        colors = list(bd._LAST_ONIMINE_SERIES or [])
        if len(colors) != len(z):
            continue
        bull.loc[z.index, sym] = [str(x) in {"Blue", "Green"} for x in colors]
        red.loc[z.index, sym] = [str(x) == "Red" for x in colors]
        good += 1
        if j % 500 == 0 or j == len(close.columns):
            print(f"STOCK_NQSAR {j}/{len(close.columns)} good={good}", flush=True)
    return bull, red, {"symbols_with_state": good, "symbols_total": len(close.columns)}


def period_ohlc(high: pd.DataFrame, low: pd.DataFrame, close: pd.DataFrame, freq: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    periods = close.index.to_period(freq)
    h = high.groupby(periods).max()
    l = low.groupby(periods).min()
    c = close.groupby(periods).last()
    actual = pd.Series(close.index, index=periods).groupby(level=0).max()
    idx = pd.DatetimeIndex(actual.reindex(c.index).to_numpy())
    h.index = idx; l.index = idx; c.index = idx
    return h, l, c


def map_completed(frame: pd.DataFrame, daily_index: pd.DatetimeIndex) -> pd.DataFrame:
    return frame.reindex(daily_index).ffill().fillna(False).astype(bool)


def build_inputs(root: Path, analysis_start: str, analysis_end: str, max_tickers: int, batch_size: int):
    symbols, bio_excluded, udiag = base.load_symbols_and_bio(root, max_tickers)
    warmup_start = str((pd.Timestamp(analysis_start) - pd.Timedelta(days=1600)).date())
    end_excl = str((pd.Timestamp(analysis_end) + pd.Timedelta(days=10)).date())
    ohlcv, ddiag = base.download_ohlcv(symbols, warmup_start, end_excl, batch_size)
    common = [s for s in ohlcv["close"].columns if s in ohlcv["volume"].columns and s in ohlcv["high"].columns and s in ohlcv["low"].columns]
    for k in ohlcv:
        ohlcv[k] = ohlcv[k].reindex(columns=common)
    close, volume = ohlcv["close"], ohlcv["volume"]

    sma50 = close.rolling(50, min_periods=50).mean()
    sma200 = close.rolling(200, min_periods=200).mean()
    vol20 = volume.rolling(20, min_periods=20).mean()
    dvol = close * vol20
    ret63 = close / close.shift(63) - 1.0
    ret189 = close / close.shift(189) - 1.0
    base_pool = (close >= 5.0) & (dvol >= base.DVOL_FLOOR)
    excols = [s for s in bio_excluded if s in base_pool.columns]
    if excols:
        base_pool.loc[:, excols] = False
    rs63 = ret63.where(base_pool & ret63.notna()).rank(axis=1, pct=True) * 100.0
    rs189 = ret189.where(base_pool & ret189.notna()).rank(axis=1, pct=True) * 100.0
    eligible = base_pool & (sma50 > sma200) & (close > sma200) & (rs63 >= base.RS_MIN) & (rs189 >= base.RS_MIN)

    nobs = close.notna().sum(axis=1)
    floor = max(5, min(30, int(max(1, close.shape[1]) * 0.20)))
    valid50 = sma50.notna().sum(axis=1)
    breadth = close.gt(sma50).sum(axis=1) / valid50.replace(0, np.nan) * 100.0
    breadth = breadth.where(valid50 >= np.maximum(floor, nobs * 0.45))

    print("EXACT STOCK NQSAR DAILY", flush=True)
    day_bull, day_red, day_diag = exact_nqsar_flags(ohlcv["high"], ohlcv["low"], close, min_rows=60)
    print("EXACT STOCK NQSAR WEEKLY", flush=True)
    wh, wl, wc = period_ohlc(ohlcv["high"], ohlcv["low"], close, "W-FRI")
    wb0, wr0, week_diag = exact_nqsar_flags(wh, wl, wc, min_rows=30)
    week_bull = map_completed(wb0, close.index)
    week_red = map_completed(wr0, close.index)
    print("EXACT STOCK NQSAR MONTHLY", flush=True)
    mh, ml, mc = period_ohlc(ohlcv["high"], ohlcv["low"], close, "M")
    mb0, mr0, month_diag = exact_nqsar_flags(mh, ml, mc, min_rows=24)
    month_bull = map_completed(mb0, close.index)
    month_red = map_completed(mr0, close.index)

    analysis_idx = close.index[(close.index >= pd.Timestamp(analysis_start)) & (close.index <= pd.Timestamp(analysis_end))]
    nq = base.download_nqsar(str((pd.Timestamp(analysis_start) - pd.Timedelta(days=60)).date()), end_excl)
    nq = nq.reindex(close.index).ffill(limit=2)
    cov = float(nq.loc[analysis_idx, "nq_color"].notna().mean())
    if cov < 0.95:
        raise RuntimeError(f"market NQSAR coverage too low {cov:.2%}")

    matrices = {
        "open": ohlcv["open"], "close": close, "rs63": rs63, "rs189": rs189, "eligible": eligible,
        "week_bull": week_bull, "week_bear": week_red,
        "month_bull": month_bull, "month_bear": month_red,
        "day_bull": day_bull, "day_red": day_red,
    }
    meta = {
        "analysis_idx": analysis_idx, "breadth": breadth, "nq": nq,
        "universe": {**udiag, **ddiag, "downloaded_common": len(common), "market_nqsar_coverage": cov},
        "stock_nqsar_coverage": {"daily": day_diag, "weekly": week_diag, "monthly": month_diag},
    }
    return meta, matrices


def sim_named(meta, matrices, label: str, base_variant: str, cost_bps: float = 0.0, transform=None):
    mx = dict(matrices)
    if transform is not None:
        transform(mx)
    res = base.simulate(meta, mx, base_variant, cost_bps)
    return label, res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--output", required=True)
    ap.add_argument("--analysis-start", default="2016-01-04")
    ap.add_argument("--analysis-end", default="2026-09-04")
    ap.add_argument("--max-tickers", type=int, default=6000)
    ap.add_argument("--batch-size", type=int, default=100)
    args = ap.parse_args()
    root = Path(args.root)
    out = root / args.output
    out.mkdir(parents=True, exist_ok=True)
    meta, matrices = build_inputs(root, args.analysis_start, args.analysis_end, args.max_tickers, args.batch_size)

    specs = [
        ("BASE_RS189", "V0", None),
        ("DAILY_NQSAR_BULL", "V1_WEEK", lambda mx: mx.update({"week_bull": matrices["day_bull"], "week_bear": matrices["day_red"]})),
        ("WEEK_NQSAR_BULL", "V1_WEEK", None),
        ("MONTH_NQSAR_BULL", "V2_MONTH", None),
        ("WEEK_MONTH_NQSAR_BULL", "V3_ALIGN", None),
        ("WEEK_MONTH_NQSAR_BULL_GATE", "V4_BULL_BULL_GATE", None),
        ("BOTH_NQSAR_RED_EXCLUDE_PLUS_BULL_PRIORITY", "V5_BEAR_BEAR_EXCLUDE", None),
        ("WEEK_BULL_MONTH_NOT_RED_GATE", "V4_BULL_BULL_GATE", lambda mx: mx.update({"month_bull": ~matrices["month_bear"]})),
        ("WEEK_BULL_MONTH_NOT_RED_PRIORITY", "V3_ALIGN", lambda mx: mx.update({"month_bull": ~matrices["month_bear"]})),
        ("WEEK_NQSAR_BULL_GATE", "V4_BULL_BULL_GATE", lambda mx: mx.update({"month_bull": matrices["week_bull"], "month_bear": matrices["week_bear"]})),
    ]

    results = {}
    metric_rows = []
    trade_rows = []
    for label, variant, transform in specs:
        print(f"SIM {label}", flush=True)
        _, res = sim_named(meta, matrices, label, variant, 0.0, transform)
        results[label] = res
        for sl, m in res["metrics"].items():
            metric_rows.append({"variant": label, "slice": sl, **m})
        trade_rows.append({"variant": label, **base.trade_summary(res["trades"]), "open_positions_end": res["open_positions"]})

    metric_df = pd.DataFrame(metric_rows)
    trade_df = pd.DataFrame(trade_rows)
    cohort = base.candidate_state_stats(matrices, meta["analysis_idx"])
    interaction = base.market_interactions(meta, matrices)

    bootstrap_rows = []
    base_eq = results["BASE_RS189"]["equity"]
    for label in results:
        if label == "BASE_RS189":
            continue
        for sl, start in (("full", None), ("confirmation_2022_plus", base.CONF_START)):
            p = base.block_bootstrap_prob_better(results[label]["equity"], base_eq, start=start, seed=20260907 + len(bootstrap_rows) * 13)
            bootstrap_rows.append({"variant": label, "slice": sl, "prob_outperform_base_block20": p})
    bootstrap = pd.DataFrame(bootstrap_rows)

    leader = base.leader_miss_table(meta, matrices)
    leader["variant"] = leader["variant"].map(LABELS).fillna(leader["variant"])

    cost_rows = []
    for label, variant, transform in specs:
        if label not in {"BASE_RS189", "WEEK_NQSAR_BULL", "MONTH_NQSAR_BULL", "WEEK_MONTH_NQSAR_BULL_GATE", "WEEK_BULL_MONTH_NOT_RED_GATE"}:
            continue
        for bps in (10.0, 25.0):
            print(f"COST {label} {bps}", flush=True)
            _, res = sim_named(meta, matrices, label, variant, bps, transform)
            cost_rows.append({"variant": label, "cost_bps_per_side": bps, **res["metrics"]["confirmation_2022_plus"]})
    cost_df = pd.DataFrame(cost_rows)

    metric_df.to_csv(out / "variant_metrics.csv", index=False)
    trade_df.to_csv(out / "trade_stats.csv", index=False)
    cohort.to_csv(out / "candidate_state_stats.csv", index=False)
    interaction.to_csv(out / "market_interaction.csv", index=False)
    bootstrap.to_csv(out / "bootstrap.csv", index=False)
    leader.to_csv(out / "leader_miss.csv", index=False)
    cost_df.to_csv(out / "cost_stress.csv", index=False)

    summary = {
        "methodology": {
            "stock_nqsar": "exact same PSAR(step=.02,max=.08)+EMA21+Wilder RSI14+bd._onimine_state FSM applied per stock",
            "bull": "Blue or Green",
            "bear_for_exclusion": "Red",
            "weekly_monthly_lookahead_guard": "resampled state released only on actual final trading close of each completed week/month",
            "portfolio_control": "same RS189 controlled current-rule simulator as structural MTF test; live Theme30 deliberately excluded to isolate NQSAR effect",
        },
        "analysis_start": args.analysis_start, "analysis_end": args.analysis_end,
        "universe": meta["universe"], "stock_nqsar_coverage": meta["stock_nqsar_coverage"],
        "metrics": {k: base.safe(v["metrics"]) for k, v in results.items()},
        "bootstrap": base.safe(bootstrap.to_dict("records")),
        "leader_miss": base.safe(leader.to_dict("records")),
    }
    (out / "summary.json").write_text(json.dumps(base.safe(summary), ensure_ascii=False, indent=2), encoding="utf-8")
    print("DONE_EXACT", json.dumps({"universe": meta["universe"], "stock_nqsar": meta["stock_nqsar_coverage"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
