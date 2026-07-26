from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from .prices import load_price_map
from .research_postprocess import select_learning_events
from .research_prices import _normalize
from .research_storage import load_dataset

POLICY_VERSION = "1.0.0"
TRAIN_WINDOWS = (
    (2017, 2019, 2020), (2018, 2020, 2021), (2019, 2021, 2022),
    (2020, 2022, 2023), (2021, 2023, 2024), (2022, 2024, 2025),
    (2023, 2025, 2026),
)
HORIZONS = (5, 10, 15, 20)
STAGE_NUMERIC = {
    "4C": -4.0, "4B": -3.0, "4A": -2.0, "3B": -1.0, "3A": -0.5,
    "NA": 0.0, "1A": 0.5, "1B": 1.0, "2A": 2.0, "2B": 3.0, "2C": 2.5,
}


@dataclass(frozen=True)
class ExperimentConfig:
    research_root: Path
    prices_path: Path
    output_dir: Path
    start_year: int = 2017
    cooldown_sessions: int = 5
    roundtrip_cost: float = 0.002
    max_positions: int = 12
    risk_per_trade: float = 0.006
    max_position_weight: float = 0.08
    seed: int = 38


def num(value: Any, default: float = np.nan) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) else default


def series_num(frame: pd.DataFrame, column: str, default: float = np.nan) -> pd.Series:
    if column not in frame:
        return pd.Series(default, index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce")


def classify_stage_series(frame: pd.DataFrame) -> pd.Series:
    """Fixed stage policy; thresholds are never tuned inside this experiment."""
    close = pd.to_numeric(frame["close"], errors="coerce")
    high = pd.to_numeric(frame["high"], errors="coerce")
    low = pd.to_numeric(frame["low"], errors="coerce")
    prev = close.shift(1)
    tr = pd.concat([(high - low), (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    atr14 = tr.rolling(14).mean()
    sma10, sma50 = close.rolling(10).mean(), close.rolling(50).mean()
    sma150, sma200 = close.rolling(150).mean(), close.rolling(200).mean()
    ema21_low = low.ewm(span=21, adjust=False).mean()
    pivot20 = high.shift(1).rolling(20).max()
    extension = (close - sma50) / atr14.replace(0, np.nan)
    hard_block = (close < sma150) | (sma150 < sma150.shift(20))
    above_pivot = close > pivot20
    near_ema21 = (close / ema21_low - 1.0).abs() <= 0.025

    result = pd.Series("NA", index=frame.index, dtype="object")
    remaining = close.notna() & sma50.notna()
    long_bull = remaining & (close >= sma50) & (sma200.isna() | (sma50 >= sma200))
    rules = (
        (long_bull & (extension >= 7.0), "2C"),
        (long_bull & (close >= sma10) & above_pivot.fillna(False), "2B"),
        (long_bull & (close >= sma10), "2A"),
        (long_bull & (close < sma10), "3A"),
        (sma200.notna() & (close >= sma200) & (close < sma50), "3B"),
        (near_ema21.fillna(False) & (close >= sma50 * 0.95), "1B"),
        ((close >= sma10) & (close >= sma50 * 0.95), "1A"),
        ((extension <= -4.0), "4C"),
        (hard_block.fillna(False) | ((close < sma10) & (sma10 < sma50)) |
         (sma200.notna() & (close < sma50) & (sma50 < sma200)), "4B"),
    )
    for condition, label in rules:
        mask = remaining & condition
        result.loc[mask] = label
        remaining &= ~mask
    result.loc[remaining] = "4A"
    return result


def stage_history_features(stage: pd.Series) -> pd.DataFrame:
    stage = stage.astype("object").fillna("NA")
    changed = stage.ne(stage.shift(1))
    days = stage.groupby(changed.cumsum()).cumcount() + 1
    numeric = stage.map(STAGE_NUMERIC).fillna(0.0)
    delta = numeric.diff().fillna(0.0)
    return pd.DataFrame({
        "stage": stage, "stage_numeric": numeric, "stage_days": days.astype(float),
        "stage_change": changed.astype(float), "stage_upgrade": (delta > 0).astype(float),
        "stage_downgrade": (delta < 0).astype(float),
    }, index=stage.index)


def _positions(index: pd.DatetimeIndex, dates: pd.Series) -> np.ndarray:
    values = pd.to_datetime(dates, errors="coerce").to_numpy(dtype="datetime64[ns]")
    return index.to_numpy(dtype="datetime64[ns]").searchsorted(values, side="left")


def attach_individual_stage(signals: pd.DataFrame, prices: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    outputs = []
    for ticker, group in signals.groupby("ticker", sort=False):
        raw = prices.get(str(ticker).upper())
        if raw is None:
            continue
        price = _normalize(raw)
        if price.empty:
            continue
        history = stage_history_features(classify_stage_series(price))
        work = group.reset_index(drop=True)
        rows = []
        for row_index, position in enumerate(_positions(price.index, work["date"])):
            if position >= len(price) or pd.Timestamp(price.index[position]).normalize() != pd.Timestamp(work.loc[row_index, "date"]).normalize():
                continue
            item = history.iloc[position]
            record = work.loc[row_index].to_dict()
            record.update({
                "individual_stage": str(item["stage"]),
                "individual_stage_numeric": float(item["stage_numeric"]),
                "individual_stage_days": float(item["stage_days"]),
                "individual_stage_change": float(item["stage_change"]),
                "individual_stage_upgrade": float(item["stage_upgrade"]),
                "individual_stage_downgrade": float(item["stage_downgrade"]),
            })
            rows.append(record)
        if rows:
            outputs.append(pd.DataFrame(rows))
    return pd.concat(outputs, ignore_index=True, sort=False) if outputs else pd.DataFrame()


def build_market_stage(prices: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    qqq = _normalize(prices.get("QQQ"))
    if qqq.empty:
        raise RuntimeError("QQQ price history is unavailable")
    history = stage_history_features(classify_stage_series(qqq)).rename(columns={
        "stage": "market_stage", "stage_numeric": "market_stage_numeric",
        "stage_days": "market_stage_days", "stage_change": "market_stage_change",
        "stage_upgrade": "market_stage_upgrade", "stage_downgrade": "market_stage_downgrade",
    })
    history["date"] = history.index
    return history.reset_index(drop=True)


def attach_group_features(frame: pd.DataFrame, market_stage: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.normalize()
    for column in ("pct_rs_raw_63", "pct_rs_raw_126", "pct_rs_raw_189"):
        out[column] = series_num(out, column)
    out["rs_composite"] = out["pct_rs_raw_63"] * .2 + out["pct_rs_raw_126"] * .3 + out["pct_rs_raw_189"] * .5
    out["stage2_flag"] = out["individual_stage"].isin({"2A", "2B", "2C"}).astype(float)
    out["bear_flag"] = out["individual_stage"].isin({"4A", "4B", "4C"}).astype(float)
    sector = out.groupby(["date", "sector"], dropna=False).agg(
        sector_rs63_mean=("pct_rs_raw_63", "mean"), sector_rs126_mean=("pct_rs_raw_126", "mean"),
        sector_rs189_mean=("pct_rs_raw_189", "mean"), sector_rs_mean=("rs_composite", "mean"),
        sector_stage2_share=("stage2_flag", "mean"), sector_bear_share=("bear_flag", "mean"),
    ).reset_index()
    sector["sector_rs_rank"] = sector.groupby("date")["sector_rs_mean"].rank(pct=True) * 100
    sector["sector_stage_score"] = (sector["sector_rs_mean"] * .65 + sector["sector_stage2_share"] * 35 - sector["sector_bear_share"] * 25).clip(0, 100)
    sector = sector.sort_values(["sector", "date"])
    sector["sector_stage_change_21d"] = sector.groupby("sector")["sector_stage_score"].diff(21)
    industry = out.groupby(["date", "industry"], dropna=False)["rs_composite"].mean().rename("industry_rs_mean").reset_index()
    industry["industry_rs_rank"] = industry.groupby("date")["industry_rs_mean"].rank(pct=True) * 100
    breadth = out.groupby("date").agg(market_stage2_share=("stage2_flag", "mean"), market_bear_share=("bear_flag", "mean")).reset_index()
    market = market_stage.copy(); market["date"] = pd.to_datetime(market["date"]).dt.normalize()
    out = out.merge(sector, on=["date", "sector"], how="left", validate="many_to_one")
    out = out.merge(industry[["date", "industry", "industry_rs_rank"]], on=["date", "industry"], how="left", validate="many_to_one")
    out = out.merge(breadth, on="date", how="left", validate="many_to_one")
    out = out.merge(market, on="date", how="left", validate="many_to_one")
    return out.drop(columns=["stage2_flag", "bear_flag"], errors="ignore")


def first_hit(high: np.ndarray, low: np.ndarray, upper: float, lower: float) -> tuple[str, int | None]:
    for day, (high_value, low_value) in enumerate(zip(high, low), start=1):
        upper_hit = np.isfinite(high_value) and high_value >= upper
        lower_hit = np.isfinite(low_value) and low_value <= lower
        if lower_hit:
            return "LOWER", day  # same-day ambiguity is conservative
        if upper_hit:
            return "UPPER", day
    return "NONE", None


def attach_forward_contracts(events: pd.DataFrame, prices: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    qqq = _normalize(prices.get("QQQ"))
    if qqq.empty or "open" not in qqq:
        raise RuntimeError("QQQ open/high/low/close history is required")
    outputs = []
    for ticker, group in events.groupby("ticker", sort=False):
        stock = _normalize(prices.get(str(ticker).upper()))
        if stock.empty or "open" not in stock:
            continue
        common = stock.index.intersection(qqq.index).sort_values()
        stock, bench = stock.reindex(common), qqq.reindex(common)
        opens = pd.to_numeric(stock["open"], errors="coerce").to_numpy(float)
        closes = pd.to_numeric(stock["close"], errors="coerce").to_numpy(float)
        highs = pd.to_numeric(stock["high"], errors="coerce").to_numpy(float)
        lows = pd.to_numeric(stock["low"], errors="coerce").to_numpy(float)
        bench_open = pd.to_numeric(bench["open"], errors="coerce").to_numpy(float)
        bench_close = pd.to_numeric(bench["close"], errors="coerce").to_numpy(float)
        work = group.reset_index(drop=True)
        rows = []
        for row_index, signal_pos in enumerate(_positions(common, work["date"])):
            if signal_pos >= len(common) or pd.Timestamp(common[signal_pos]).normalize() != pd.Timestamp(work.loc[row_index, "date"]).normalize():
                continue
            entry_pos = signal_pos + 1
            max_end = entry_pos + max(HORIZONS) - 1
            if max_end >= len(common):
                continue
            entry, qqq_entry = opens[entry_pos], bench_open[entry_pos]
            if not np.isfinite(entry) or entry <= 0 or not np.isfinite(qqq_entry) or qqq_entry <= 0:
                continue
            record = work.loc[row_index].to_dict()
            stops = [num(record.get("stop_ema21_low")), num(record.get("stop_sma10"))]
            valid_stops = [value for value in stops if np.isfinite(value) and 0 < value < entry]
            stop, fallback = (max(valid_stops), 0.0) if valid_stops else (entry * .95, 1.0)
            risk = entry - stop
            if risk <= entry * .001:
                stop, risk, fallback = entry * .95, entry * .05, 1.0
            risk_fraction = risk / entry
            for horizon in HORIZONS:
                end_pos = entry_pos + horizon - 1
                stock_return = closes[end_pos] / entry - 1
                qqq_return = bench_close[end_pos] / qqq_entry - 1
                record[f"return_{horizon}"] = float(stock_return)
                record[f"benchmark_return_{horizon}"] = float(qqq_return)
                record[f"excess_{horizon}"] = float(stock_return - qqq_return)
                record[f"outcome_date_{horizon}"] = pd.Timestamp(common[end_pos])
            high15, low15 = highs[entry_pos:entry_pos + 15], lows[entry_pos:entry_pos + 15]
            result3, day3 = first_hit(high15, low15, entry + 3 * risk, entry - risk)
            result_fixed, day_fixed = first_hit(high15, low15, entry * 1.10, entry * .95)
            result1_5, _ = first_hit(highs[entry_pos:entry_pos + 5], lows[entry_pos:entry_pos + 5], entry + risk, entry - risk)
            if result3 == "UPPER":
                gross, exit_pos = 3 * risk_fraction, entry_pos + int(day3 or 1) - 1
            elif result3 == "LOWER":
                gross, exit_pos = -risk_fraction, entry_pos + int(day3 or 1) - 1
            else:
                gross, exit_pos = closes[entry_pos + 14] / entry - 1, entry_pos + 14
            record.update({
                "entry_date": pd.Timestamp(common[entry_pos]), "entry_price": float(entry),
                "structural_stop": float(stop), "risk_fraction": float(risk_fraction),
                "stop_fallback": fallback, "hit_3r_before_1r_15": float(result3 == "UPPER"),
                "stop_before_3r_15": float(result3 == "LOWER"), "neither_3r_nor_1r_15": float(result3 == "NONE"),
                "days_to_3r_or_stop": float(day3) if day3 else np.nan,
                "hit_10_before_5_15": float(result_fixed == "UPPER"),
                "days_to_10_or_5": float(day_fixed) if day_fixed else np.nan,
                "early_failure_5": float(result1_5 == "LOWER"),
                "mfe_15": float(np.nanmax(high15) / entry - 1), "mae_15": float(np.nanmin(low15) / entry - 1),
                "trade_exit_date": pd.Timestamp(common[exit_pos]), "trade_return_gross": float(gross),
                "label_end_date": pd.Timestamp(common[max_end]),
            })
            rows.append(record)
        if rows:
            outputs.append(pd.DataFrame(rows))
    return pd.concat(outputs, ignore_index=True, sort=False) if outputs else pd.DataFrame()


def prepare_dataset(config: ExperimentConfig):
    prices = load_price_map(config.prices_path)
    signals = load_dataset(config.research_root, "signals")
    if signals.empty:
        raise RuntimeError("research signals dataset is empty")
    signals["date"] = pd.to_datetime(signals["date"], errors="coerce").dt.normalize()
    signals = signals.dropna(subset=["date", "ticker"])
    signals = signals[signals["date"].dt.year >= config.start_year].copy()
    signals["hard_block_numeric"] = signals["hard_block"].fillna(False).astype(bool).astype(float) if "hard_block" in signals else 0.0
    staged = attach_individual_stage(signals, prices)
    if staged.empty:
        raise RuntimeError("stage enrichment produced no rows")
    grouped = attach_group_features(staged, build_market_stage(prices))
    sessions = sorted(pd.Timestamp(value).normalize() for value in _normalize(prices["QQQ"]).index.unique())
    learning = select_learning_events(grouped, sessions, cooldown_sessions=config.cooldown_sessions)
    labelled = attach_forward_contracts(learning, prices)
    if labelled.empty:
        raise RuntimeError("A/B label contract produced no rows")
    metadata = {
        "signal_rows": len(signals), "stage_rows": len(staged), "learning_event_rows": len(learning),
        "labelled_rows": len(labelled), "date_min": labelled["date"].min(),
        "date_max": labelled["date"].max(), "tickers": labelled["ticker"].nunique(),
    }
    return labelled, prices, metadata
