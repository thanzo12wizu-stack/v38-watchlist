from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf


def plain(raw: pd.DataFrame) -> pd.DataFrame:
    x = raw.copy()
    if isinstance(x.columns, pd.MultiIndex):
        if len(set(x.columns.get_level_values(0))) == 1:
            x.columns = x.columns.get_level_values(1)
        elif len(set(x.columns.get_level_values(1))) == 1:
            x.columns = x.columns.get_level_values(0)
    x.index = pd.DatetimeIndex(pd.to_datetime(x.index))
    if x.index.tz is None:
        x.index = x.index.tz_localize("America/New_York", ambiguous="infer", nonexistent="shift_forward")
    else:
        x.index = x.index.tz_convert("America/New_York")
    return x.sort_index()


def wilder_rsi(close: np.ndarray, n: int = 14) -> np.ndarray:
    values = np.asarray(close, float)
    delta = np.diff(values, prepend=np.nan)
    up = np.where(delta > 0, delta, 0.0)
    down = np.where(delta < 0, -delta, 0.0)
    avg_up = np.full(len(values), np.nan)
    avg_down = np.full(len(values), np.nan)
    if len(values) > n:
        avg_up[n] = np.nanmean(up[1:n + 1])
        avg_down[n] = np.nanmean(down[1:n + 1])
        for i in range(n + 1, len(values)):
            avg_up[i] = (avg_up[i - 1] * (n - 1) + up[i]) / n
            avg_down[i] = (avg_down[i - 1] * (n - 1) + down[i]) / n
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = avg_up / avg_down
        result = 100 - 100 / (1 + ratio)
    result[(avg_down == 0) & np.isfinite(avg_up)] = 100.0
    result[(avg_up == 0) & (avg_down == 0)] = 50.0
    return result


def build_stage51_bars(raw: pd.DataFrame, *, min_count: int) -> pd.DataFrame:
    frame = plain(raw)
    frame = frame[["Open", "High", "Low", "Close"]].apply(pd.to_numeric, errors="coerce").dropna()
    minutes = frame.index.hour * 60 + frame.index.minute
    frame = frame[(minutes >= 570) & (minutes < 960)].copy()
    minutes = frame.index.hour * 60 + frame.index.minute
    frame["date"] = pd.DatetimeIndex(frame.index.date)
    frame["slot"] = np.where(minutes < 810, 0, 1)
    bars = (
        frame.groupby(["date", "slot"], sort=True)
        .agg(Open=("Open", "first"), High=("High", "max"), Low=("Low", "min"), Close=("Close", "last"), n=("Close", "size"))
        .reset_index()
    )
    bars = bars[bars["n"] >= min_count].copy().sort_values(["date", "slot"]).reset_index(drop=True)
    bars["rsi14"] = wilder_rsi(bars["Close"].to_numpy(float), 14)
    rsi = bars["rsi14"].to_numpy(float)
    bars["touch30"] = (rsi <= 30) & np.r_[False, rsi[:-1] > 30]
    return bars


def download(interval: str, period: str) -> pd.DataFrame:
    raw = yf.download(
        "QQQ", period=period, interval=interval, progress=False,
        auto_adjust=False, actions=False, prepost=False, threads=False,
    )
    if raw is None or raw.empty:
        raise RuntimeError(f"QQQ {interval} {period} returned no data")
    return raw


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    raw5 = download("5m", "60d")
    raw60 = download("60m", "730d")
    b5 = build_stage51_bars(raw5, min_count=6)
    b60 = build_stage51_bars(raw60, min_count=2)
    if b5.empty or b60.empty:
        raise RuntimeError("bridge bars empty")

    merged = b5.merge(b60, on=["date", "slot"], suffixes=("_5m", "_60m"), how="inner").sort_values(["date", "slot"]).reset_index(drop=True)
    if len(merged) < 40:
        raise RuntimeError(f"insufficient overlap bars: {len(merged)}")

    merged["close_diff_bps"] = (merged["Close_60m"] / merged["Close_5m"] - 1.0) * 10000.0
    merged["rsi_abs_diff"] = (merged["rsi14_60m"] - merged["rsi14_5m"]).abs()
    # Wilder seed differences from the shorter 5m history need burn-in before RSI comparison.
    compare = merged.iloc[min(40, len(merged) // 3):].copy()
    compare = compare[np.isfinite(compare["rsi_abs_diff"])].copy()
    if len(compare) < 25:
        raise RuntimeError(f"insufficient RSI overlap after burn-in: {len(compare)}")

    exact_touch_events = int(compare["touch30_5m"].sum())
    touch_match = float((compare["touch30_5m"] == compare["touch30_60m"]).mean())
    precision = None
    recall = None
    pred = compare["touch30_60m"].astype(bool)
    truth = compare["touch30_5m"].astype(bool)
    tp = int((pred & truth).sum())
    if int(pred.sum()) > 0:
        precision = tp / int(pred.sum())
    if int(truth.sum()) > 0:
        recall = tp / int(truth.sum())

    close_median = float(compare["close_diff_bps"].abs().median())
    close_p99 = float(compare["close_diff_bps"].abs().quantile(0.99))
    rsi_median = float(compare["rsi_abs_diff"].median())
    rsi_p99 = float(compare["rsi_abs_diff"].quantile(0.99))

    # Signal-safe acceptance is deliberately strict. If there are no actual touch30 events,
    # bar/RSi equivalence can be established but historical Stage56 extension is not approved.
    bar_pass = close_median <= 1.0 and close_p99 <= 5.0 and rsi_median <= 0.25 and rsi_p99 <= 1.0
    signal_pass = exact_touch_events > 0 and touch_match >= 0.995 and recall == 1.0 and precision == 1.0
    approved = bool(bar_pass and signal_pass)

    merged.to_csv(out / "stage56_hourly_bridge_overlap.csv", index=False)
    summary = {
        "status": "STAGE56_HOURLY_BRIDGE_AUDIT",
        "purpose": "Validate Yahoo 60m aggregation as a post-2026-03-20 bridge for the frozen Stage51 5m->4H RSI30 trigger.",
        "coverage": {
            "five_min_start": str(pd.Timestamp(b5.date.min()).date()),
            "five_min_end": str(pd.Timestamp(b5.date.max()).date()),
            "hourly_start": str(pd.Timestamp(b60.date.min()).date()),
            "hourly_end": str(pd.Timestamp(b60.date.max()).date()),
            "overlap_bars": int(len(merged)),
            "compare_bars": int(len(compare)),
        },
        "close_abs_diff_bps": {"median": close_median, "p99": close_p99},
        "rsi_abs_diff": {"median": rsi_median, "p99": rsi_p99},
        "touch30": {
            "five_min_events": exact_touch_events,
            "sixty_min_events": int(pred.sum()),
            "match_rate": touch_match,
            "precision": precision,
            "recall": recall,
        },
        "bar_equivalence_pass": bool(bar_pass),
        "signal_equivalence_pass": bool(signal_pass),
        "approved_for_stage56_history_extension": approved,
        "guardrail": "Do not extend frozen Stage56 history unless both bar and actual touch30 signal equivalence pass. No-event overlap is insufficient for approval.",
    }
    (out / "stage56_hourly_bridge_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
