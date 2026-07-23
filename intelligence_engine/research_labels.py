from __future__ import annotations

from typing import Mapping

import numpy as np
import pandas as pd

from .research_prices import _normalize


def _index_positions(index: pd.DatetimeIndex, dates: pd.Series) -> np.ndarray:
    values = pd.to_datetime(dates, errors="coerce").to_numpy(dtype="datetime64[ns]")
    return index.to_numpy(dtype="datetime64[ns]").searchsorted(values, side="left")


def attach_forward_labels(signals: pd.DataFrame, prices: Mapping[str, pd.DataFrame], *, horizons: tuple[int, ...] = (5, 10, 21, 63)) -> pd.DataFrame:
    if signals.empty:
        return signals.copy()
    qqq_raw = prices.get("QQQ")
    if qqq_raw is None:
        raise RuntimeError("QQQ benchmark is required for forward labels")
    qqq = _normalize(qqq_raw)
    if qqq.empty:
        raise RuntimeError("QQQ benchmark history is empty")
    outputs = []
    max_horizon = max(horizons)
    for ticker, group in signals.groupby("ticker", sort=False):
        raw = prices.get(str(ticker).upper())
        if raw is None:
            continue
        stock = _normalize(raw)
        if stock.empty:
            continue
        common = stock.index.intersection(qqq.index).sort_values()
        if len(common) <= max_horizon:
            continue
        stock = stock.reindex(common); benchmark = qqq.reindex(common)
        close = pd.to_numeric(stock["close"], errors="coerce").to_numpy(dtype=float)
        high = pd.to_numeric(stock["high"], errors="coerce").to_numpy(dtype=float)
        low = pd.to_numeric(stock["low"], errors="coerce").to_numpy(dtype=float)
        bench_close = pd.to_numeric(benchmark["close"], errors="coerce").to_numpy(dtype=float)
        work = group.copy().reset_index(drop=True)
        positions = _index_positions(common, work["date"])
        valid_rows = []
        for row_idx, pos in enumerate(positions):
            if pos >= len(common) or pd.Timestamp(common[pos]).normalize() != pd.Timestamp(work.loc[row_idx, "date"]).normalize():
                continue
            record = work.loc[row_idx].to_dict(); entry = close[pos]
            if not np.isfinite(entry) or entry <= 0:
                continue
            stop = pd.to_numeric(record.get("stop_ema21_low"), errors="coerce")
            if pd.isna(stop): stop = pd.to_numeric(record.get("stop_sma10"), errors="coerce")
            pivot = pd.to_numeric(record.get("pivot_20d"), errors="coerce")
            outcome_ready = False
            for horizon in horizons:
                end_pos = pos + horizon
                if end_pos >= len(common):
                    record[f"outcome_ready_{horizon}"] = False
                    continue
                outcome_ready = True
                future_high = high[pos+1:end_pos+1]; future_low = low[pos+1:end_pos+1]
                stock_ret = close[end_pos]/entry-1; bench_ret = bench_close[end_pos]/bench_close[pos]-1
                record[f"outcome_ready_{horizon}"] = True
                record[f"outcome_date_{horizon}"] = pd.Timestamp(common[end_pos]).date().isoformat()
                record[f"return_{horizon}"] = float(stock_ret); record[f"benchmark_return_{horizon}"] = float(bench_ret); record[f"excess_{horizon}"] = float(stock_ret-bench_ret)
                record[f"mfe_{horizon}"] = float(np.nanmax(future_high)/entry-1) if len(future_high) else None
                record[f"mae_{horizon}"] = float(np.nanmin(future_low)/entry-1) if len(future_low) else None
                record[f"stop_hit_{horizon}"] = bool(pd.notna(stop) and np.nanmin(future_low) <= float(stop))
                target_hits = np.flatnonzero(future_high >= entry*1.25)
                record[f"target25_hit_{horizon}"] = bool(len(target_hits)); record[f"days_to_target25_{horizon}"] = int(target_hits[0]+1) if len(target_hits) else None
                progress_level = max(entry*1.05, float(pivot) if pd.notna(pivot) and float(pivot)>0 else entry*1.05)
                progress_hits = np.flatnonzero(future_high >= progress_level)
                record[f"progress_hit_{horizon}"] = bool(len(progress_hits)); record[f"days_to_progress_{horizon}"] = int(progress_hits[0]+1) if len(progress_hits) else None
            record["outcome_ready"] = outcome_ready; valid_rows.append(record)
        if valid_rows: outputs.append(pd.DataFrame(valid_rows))
    return pd.concat(outputs,ignore_index=True) if outputs else pd.DataFrame(columns=list(signals.columns)+["outcome_ready"])
