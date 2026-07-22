from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd


def evaluate_snapshot(
    snapshot: Sequence[Mapping[str, Any]],
    prices: Mapping[str, pd.DataFrame],
    asof: str | pd.Timestamp,
    benchmark: str = "QQQ",
    horizons: tuple[int, ...] = (5, 10, 21, 63),
) -> pd.DataFrame:
    """Evaluate score observations using only prices strictly after *asof*.

    The function is intentionally separate from score construction so future
    returns can never leak into live features or rankings.
    """
    asof_ts = pd.Timestamp(asof)
    benchmark_frame = prices.get(benchmark)
    if benchmark_frame is None:
        raise ValueError(f"missing benchmark: {benchmark}")
    benchmark_close = _close(benchmark_frame)

    rows: list[dict[str, Any]] = []
    for stock in snapshot:
        ticker = str(stock.get("ticker", "")).upper().strip()
        frame = prices.get(ticker)
        if not ticker or frame is None:
            continue
        close = _close(frame)
        row: dict[str, Any] = {
            "ticker": ticker,
            "asof": asof_ts.date().isoformat(),
            "scores": stock.get("scores", {}),
            "confidence": stock.get("confidence"),
        }
        for horizon in horizons:
            stock_return = _forward_return(close, asof_ts, horizon)
            benchmark_return = _forward_return(benchmark_close, asof_ts, horizon)
            row[f"return_{horizon}d"] = stock_return
            row[f"benchmark_return_{horizon}d"] = benchmark_return
            row[f"excess_return_{horizon}d"] = (
                stock_return - benchmark_return
                if stock_return is not None and benchmark_return is not None
                else None
            )
        rows.append(row)
    return pd.DataFrame(rows)


def summarize_by_score_bucket(
    evaluated: pd.DataFrame,
    score_name: str,
    horizon: int,
    buckets: int = 5,
) -> pd.DataFrame:
    """Summarize excess returns by score quantile without inventing missing data."""
    if evaluated.empty:
        return pd.DataFrame()
    score = evaluated["scores"].map(
        lambda value: value.get(score_name) if isinstance(value, Mapping) else None
    )
    excess_col = f"excess_return_{horizon}d"
    work = pd.DataFrame({"score": pd.to_numeric(score, errors="coerce"), "excess": pd.to_numeric(evaluated[excess_col], errors="coerce")}).dropna()
    if work.empty:
        return pd.DataFrame()
    distinct = int(work["score"].nunique())
    q = min(buckets, distinct)
    if q < 2:
        return pd.DataFrame()
    work["bucket"] = pd.qcut(work["score"], q=q, duplicates="drop")
    return work.groupby("bucket", observed=True).agg(
        count=("excess", "size"),
        mean_excess_return=("excess", "mean"),
        median_excess_return=("excess", "median"),
        win_rate=("excess", lambda values: float((values > 0).mean())),
        mean_score=("score", "mean"),
    ).reset_index()


def _close(frame: pd.DataFrame) -> pd.Series:
    columns = {str(column).lower().replace(" ", "_"): column for column in frame.columns}
    source = columns.get("close") or columns.get("adj_close") or columns.get("adjclose")
    if source is None:
        raise ValueError("price frame requires close or adjusted close")
    series = pd.to_numeric(frame[source], errors="coerce").dropna().sort_index()
    series.index = pd.to_datetime(series.index).tz_localize(None)
    return series


def _forward_return(close: pd.Series, asof: pd.Timestamp, horizon: int) -> float | None:
    eligible = close.loc[close.index <= asof]
    future = close.loc[close.index > asof]
    if eligible.empty or len(future) < horizon:
        return None
    start = float(eligible.iloc[-1])
    end = float(future.iloc[horizon - 1])
    value = end / start - 1 if start else np.nan
    return float(value) if np.isfinite(value) else None
