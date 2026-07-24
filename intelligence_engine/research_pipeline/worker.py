from __future__ import annotations

import argparse
import gc
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from . import legacy
from ..pipeline import load_universe
from ..prices import load_price_map
from ..research_contracts import (
    RESEARCH_POLICY_VERSION,
    RESEARCH_RETENTION_YEARS,
    RESEARCH_SCHEMA_VERSION,
    ResearchConfig,
    ResearchManifest,
)
from ..research_engine import add_research_scores, build_signal_pool
from ..research_expectancy import build_research_expectancy
from ..research_financials import build_financial_snapshots
from ..research_labels import attach_forward_labels
from ..research_prices import build_price_panel
from ..research_providers import (
    NullEstimateProvider,
    NullEventProvider,
    NullOwnershipProvider,
    SecCompanyFactsProvider,
)
from ..research_storage import (
    load_dataset,
    storage_bytes,
    upsert_year_partitions,
    write_json,
)


def _concat_bounded(frames: Iterable[pd.DataFrame], *, batch_size: int = 64) -> pd.DataFrame:
    """Concatenate small frames without retaining thousands of DataFrame objects."""
    batches: list[pd.DataFrame] = []
    buffer: list[pd.DataFrame] = []
    for frame in frames:
        if frame is None or frame.empty:
            continue
        buffer.append(frame)
        if len(buffer) >= batch_size:
            batches.append(pd.concat(buffer, ignore_index=True, sort=False))
            buffer.clear()
    if buffer:
        batches.append(pd.concat(buffer, ignore_index=True, sort=False))
    if not batches:
        return pd.DataFrame()
    while len(batches) > 1:
        reduced: list[pd.DataFrame] = []
        for index in range(0, len(batches), 8):
            reduced.append(pd.concat(batches[index : index + 8], ignore_index=True, sort=False))
        batches = reduced
    return batches[0]


def _snapshot_frames(provider: SecCompanyFactsProvider, tickers: Iterable[str]) -> Iterable[pd.DataFrame]:
    for ticker in tickers:
        history = provider.history(str(ticker))
        if history.empty:
            continue
        snapshot = build_financial_snapshots(history)
        if not snapshot.empty:
            yield snapshot
        del history


def _fact_frames(provider: SecCompanyFactsProvider, tickers: Iterable[str]) -> Iterable[pd.DataFrame]:
    for ticker in tickers:
        history = provider.history(str(ticker))
        if not history.empty:
            yield history


def _naive_utc_datetime(values: pd.Series) -> pd.Series:
    """Normalize mixed naive/aware timestamps to merge-safe datetime64[ns]."""
    normalized = pd.to_datetime(values, errors="coerce", utc=True)
    return normalized.dt.tz_convert(None)


def _merge_snapshots_indexed(price_panel: pd.DataFrame, snapshots: pd.DataFrame) -> pd.DataFrame:
    """Merge point-in-time snapshots with indexed, timezone-stable ticker lookups."""
    if price_panel.empty:
        return price_panel.copy()
    if snapshots is None or snapshots.empty:
        out = price_panel.copy()
        out["fundamental_confidence"] = 0.0
        return out

    left = price_panel.copy()
    left["ticker"] = left["ticker"].astype(str)
    left["date"] = _naive_utc_datetime(left["date"])
    invalid_left = left[left["date"].isna()].copy()
    left = left.dropna(subset=["date"])

    right = snapshots.copy()
    right["ticker"] = right["ticker"].astype(str)
    right["available_at"] = _naive_utc_datetime(right["available_at"])
    right = right.dropna(subset=["ticker", "available_at"])
    histories = {
        str(ticker): group.drop(columns=["ticker"], errors="ignore")
        .sort_values("available_at")
        .drop_duplicates("available_at", keep="last")
        for ticker, group in right.groupby("ticker", sort=False)
    }

    pieces: list[pd.DataFrame] = []
    for ticker, group in left.groupby("ticker", sort=False):
        history = histories.get(str(ticker))
        if history is None or history.empty:
            enriched = group.copy()
            enriched["fundamental_confidence"] = 0.0
        else:
            enriched = pd.merge_asof(
                group.sort_values("date"),
                history,
                left_on="date",
                right_on="available_at",
                direction="backward",
                allow_exact_matches=True,
            )
            if "fundamental_confidence" not in enriched:
                enriched["fundamental_confidence"] = 0.0
            else:
                enriched["fundamental_confidence"] = pd.to_numeric(
                    enriched["fundamental_confidence"], errors="coerce"
                ).fillna(0.0)
        pieces.append(enriched)

    if not invalid_left.empty:
        invalid_left["fundamental_confidence"] = 0.0
        pieces.append(invalid_left)
    return _concat_bounded(pieces, batch_size=128) if pieces else price_panel.copy()


def build_streaming(
    *,
    universe_path: Path,
    price_path: Path,
    sec_dir: Path,
    root: Path,
    mode: str = "incremental",
    years: int = RESEARCH_RETENTION_YEARS,
    year: int | None = None,
    start: str | None = None,
    end: str | None = None,
    stride: int = 1,
    max_daily_signals: int = 300,
    min_samples: int = 40,
) -> dict[str, Any]:
    generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    config = ResearchConfig(
        root=root,
        years=years,
        stride=max(1, stride),
        max_daily_signals=max_daily_signals,
        min_samples=min_samples,
    )
    universe = load_universe(universe_path).reset_index(drop=True)
    prices = load_price_map(price_path)
    existing_signals = load_dataset(root, "signals")
    range_start, range_end = legacy._date_range(
        prices,
        config,
        mode=mode,
        year=year,
        start=start,
        end=end,
        existing_signals=existing_signals,
    )
    warnings: list[str] = []
    if mode == "incremental" and existing_signals.empty and not start:
        warnings.append("initial_incremental_latest_session_only")
    if mode == "backfill" and year is None and not start:
        warnings.append("backfill_without_year_bounded_to_current_year")
    if range_start > range_end:
        range_start = range_end

    panel = build_price_panel(prices, universe, start=range_start, end=range_end, stride=config.stride)
    if panel.empty:
        raise RuntimeError("research price panel is empty")
    panel["market_regime"] = legacy._regime_series(panel, prices["QQQ"])
    tickers = sorted(panel["ticker"].astype(str).unique())
    panel_rows = int(len(panel))
    panel_ticker_count = int(panel["ticker"].nunique())

    fundamental_provider = SecCompanyFactsProvider(sec_dir, filing_limit=12, asof=range_end)
    estimate_provider = NullEstimateProvider()
    event_provider = NullEventProvider()
    ownership_provider = NullOwnershipProvider()

    snapshots = _concat_bounded(_snapshot_frames(fundamental_provider, tickers), batch_size=64)
    panel = _merge_snapshots_indexed(panel, snapshots)
    del snapshots
    gc.collect()

    scored = add_research_scores(panel)
    signals = build_signal_pool(scored, max_daily_signals=config.max_daily_signals)
    compact_signals = legacy._compact_columns(signals)
    signal_tickers = sorted(compact_signals["ticker"].astype(str).unique()) if not compact_signals.empty else []

    del panel, scored, signals
    gc.collect()

    # Persist only facts that support emitted signals. Raw SEC cache remains the source of truth,
    # while the audit store stays bounded enough for GitHub-hosted runners.
    facts = _concat_bounded(_fact_frames(fundamental_provider, signal_tickers), batch_size=32)
    facts_result = (
        upsert_year_partitions(
            root,
            "facts",
            facts,
            date_column="available_at",
            keys=("ticker", "metric", "period_end", "available_at", "accession"),
            retention_years=config.years,
            reference_date=range_end,
        )
        if not facts.empty
        else {"rows": 0, "partitions": 0}
    )
    del facts
    gc.collect()

    signals_result = upsert_year_partitions(
        root,
        "signals",
        compact_signals,
        date_column="date",
        keys=("ticker", "date", "candidate_archetype", "setup"),
        retention_years=config.years,
        reference_date=range_end,
    )
    all_signals = load_dataset(root, "signals")
    existing_outcomes = load_dataset(root, "outcomes")
    pending = legacy._pending_signals(all_signals, existing_outcomes)
    labelled = attach_forward_labels(pending, prices, horizons=config.horizons)
    ready_mask = pd.Series(False, index=labelled.index)
    for horizon in config.horizons:
        column = f"outcome_ready_{horizon}"
        if column in labelled:
            ready_mask |= labelled[column].fillna(False).astype(bool)
    ready_outcomes = labelled[ready_mask].copy()
    outcomes_result = (
        upsert_year_partitions(
            root,
            "outcomes",
            ready_outcomes,
            date_column="date",
            keys=("ticker", "date", "candidate_archetype", "setup"),
            retention_years=config.years,
            reference_date=range_end,
        )
        if not ready_outcomes.empty
        else {"rows": int(len(existing_outcomes)), "partitions": 0}
    )
    all_outcomes = load_dataset(root, "outcomes")
    expectancy = build_research_expectancy(
        all_outcomes,
        horizons=config.horizons,
        min_samples=config.min_samples,
        bootstrap_samples=config.bootstrap_samples,
        seed=config.seed,
        analysis_windows=config.analysis_windows,
        primary_window_years=config.primary_window_years,
    )
    ranked = legacy._point_in_time_rankings(all_signals, all_outcomes, config)
    ranking_result = (
        upsert_year_partitions(
            root,
            "rankings",
            ranked,
            date_column="date",
            keys=("ticker", "date", "candidate_archetype", "setup"),
            retention_years=config.years,
            reference_date=range_end,
        )
        if not ranked.empty
        else {"rows": 0, "partitions": 0}
    )
    if storage_bytes(root) > 85 * 1024 * 1024:
        warnings.append("research_store_above_85mb_split_encryption_recommended")

    manifest = ResearchManifest(
        generated_at=generated_at,
        mode=mode,
        start_date=range_start.date().isoformat(),
        end_date=range_end.date().isoformat(),
        years_retained=config.years,
        price_rows=panel_rows,
        fact_rows=int(facts_result.get("rows", 0)),
        signal_rows=int(len(all_signals)),
        outcome_rows=int(len(all_outcomes)),
        ranking_rows=int(len(ranked)),
        tickers=panel_ticker_count,
        data_provider={
            "price": "configured_price_cache",
            "fundamental": fundamental_provider.name,
            "estimate": estimate_provider.name,
            "event": event_provider.name,
            "ownership": ownership_provider.name,
        },
        warnings=warnings,
    ).to_dict()
    summary = legacy._research_summary(ranked, expectancy, manifest)
    write_json(root / "manifest.json", manifest)
    write_json(root / "expectancy.json", expectancy)
    write_json(root / "current_rankings.json", summary)
    legacy._attach_to_index(root.parent / "index.json", summary)
    return {
        **manifest,
        "facts_partitions": facts_result.get("partitions", 0),
        "signals_partitions": signals_result.get("partitions", 0),
        "outcomes_partitions": outcomes_result.get("partitions", 0),
        "rankings_partitions": ranking_result.get("partitions", 0),
        "storage_bytes": storage_bytes(root),
        "expectancy_status": expectancy.get("status"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--universe", default="universe.csv")
    parser.add_argument("--prices", default="prices.pkl")
    parser.add_argument("--sec-dir", default="data/sec_companyfacts")
    parser.add_argument("--root", default="data/intelligence/research")
    parser.add_argument("--mode", choices=("incremental", "backfill"), default="incremental")
    parser.add_argument("--years", type=int, default=RESEARCH_RETENTION_YEARS)
    parser.add_argument("--year", type=int, default=None)
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    parser.add_argument("--stride", type=int, default=1)
    parser.add_argument("--max-daily-signals", type=int, default=300)
    parser.add_argument("--min-samples", type=int, default=40)
    args = parser.parse_args()
    result = build_streaming(
        universe_path=Path(args.universe),
        price_path=Path(args.prices),
        sec_dir=Path(args.sec_dir),
        root=Path(args.root),
        mode=args.mode,
        years=max(RESEARCH_RETENTION_YEARS, args.years),
        year=args.year,
        start=args.start,
        end=args.end,
        stride=max(1, args.stride),
        max_daily_signals=max(25, args.max_daily_signals),
        min_samples=max(10, args.min_samples),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
