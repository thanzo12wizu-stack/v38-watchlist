from __future__ import annotations

import pandas as pd

from .ab_stage_data import (
    ExperimentConfig,
    attach_forward_contracts,
    attach_group_features,
    attach_individual_stage,
    build_market_stage,
)
from .prices import load_price_map
from .research_postprocess import select_learning_events
from .research_prices import _normalize
from .research_storage import load_dataset


def normalize_dimension(series: pd.Series) -> pd.Series:
    values = series.astype("string").str.strip()
    values = values.mask(values.isna() | values.eq(""), "Unclassified")
    return values.astype(str)


def prepare_dataset(config: ExperimentConfig):
    prices = load_price_map(config.prices_path)
    signals = load_dataset(config.research_root, "signals")
    if signals.empty:
        raise RuntimeError("research signals dataset is empty")
    signals["date"] = pd.to_datetime(
        signals["date"], errors="coerce"
    ).dt.normalize()
    signals = signals.dropna(subset=["date", "ticker"])
    signals = signals[signals["date"].dt.year >= config.start_year].copy()
    for column in ("sector", "industry"):
        if column not in signals:
            signals[column] = "Unclassified"
        signals[column] = normalize_dimension(signals[column])
    signals["hard_block_numeric"] = (
        signals["hard_block"].fillna(False).astype(bool).astype(float)
        if "hard_block" in signals
        else 0.0
    )
    staged = attach_individual_stage(signals, prices)
    if staged.empty:
        raise RuntimeError("stage enrichment produced no rows")
    for column in ("sector", "industry"):
        staged[column] = normalize_dimension(staged[column])
    grouped = attach_group_features(staged, build_market_stage(prices))
    sessions = sorted(
        pd.Timestamp(value).normalize()
        for value in _normalize(prices["QQQ"]).index.unique()
    )
    learning = select_learning_events(
        grouped,
        sessions,
        cooldown_sessions=config.cooldown_sessions,
    )
    labelled = attach_forward_contracts(learning, prices)
    if labelled.empty:
        raise RuntimeError("A/B label contract produced no rows")
    metadata = {
        "signal_rows": len(signals),
        "stage_rows": len(staged),
        "learning_event_rows": len(learning),
        "labelled_rows": len(labelled),
        "date_min": labelled["date"].min(),
        "date_max": labelled["date"].max(),
        "tickers": labelled["ticker"].nunique(),
        "dimension_normalization": "string+Unclassified",
    }
    return labelled, prices, metadata
