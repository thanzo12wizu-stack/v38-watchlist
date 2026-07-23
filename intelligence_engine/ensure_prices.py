from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from .pipeline import load_universe
from .prices import load_price_map, save_price_map
from .providers import get_price_provider
from .research_contracts import RESEARCH_RETENTION_YEARS


def _latest_date(frame: pd.DataFrame | None) -> pd.Timestamp | None:
    if frame is None or frame.empty or not isinstance(frame.index, pd.DatetimeIndex):
        return None
    index = frame.index
    if index.tz is not None:
        index = index.tz_convert(None)
    return pd.Timestamp(index.max()).normalize()


def _earliest_date(frame: pd.DataFrame | None) -> pd.Timestamp | None:
    if frame is None or frame.empty or not isinstance(frame.index, pd.DatetimeIndex):
        return None
    index = frame.index
    if index.tz is not None:
        index = index.tz_convert(None)
    return pd.Timestamp(index.min()).normalize()


def _merge_frame(existing: pd.DataFrame | None, update: pd.DataFrame) -> pd.DataFrame:
    if existing is None or existing.empty:
        return update.sort_index().loc[~update.index.duplicated(keep="last")]
    combined = pd.concat([existing, update], axis=0).sort_index()
    return combined.loc[~combined.index.duplicated(keep="last")]


def _apply_download(existing: dict[str, pd.DataFrame], downloaded: dict[str, pd.DataFrame]) -> None:
    for ticker, frame in downloaded.items():
        if frame is None or frame.empty:
            continue
        existing[ticker] = _merge_frame(existing.get(ticker), frame)


def run(
    universe_path: Path,
    cache_path: Path,
    *,
    min_coverage: float = 0.70,
    provider_name: str | None = None,
    history_years: int | None = None,
    max_history_tickers: int = 0,
) -> dict:
    universe = load_universe(universe_path)
    requested = sorted(set(universe["ticker"].astype(str)) | {"QQQ"})
    existing = load_price_map(cache_path) if cache_path.exists() else {}
    provider = get_price_provider(provider_name)
    phases: list[dict] = []
    resolved_history_years = (
        max(RESEARCH_RETENTION_YEARS, int(history_years)) if history_years else None
    )

    benchmark_update, benchmark_diagnostics = provider.download(["QQQ"], period="3mo")
    phases.append({"phase": "benchmark_refresh", **benchmark_diagnostics})
    _apply_download(existing, benchmark_update)
    if benchmark_update:
        save_price_map(cache_path, existing)

    missing = [ticker for ticker in requested if ticker not in existing]
    if missing:
        missing_period = f"{resolved_history_years}y" if resolved_history_years else "18mo"
        downloaded, diagnostics = provider.download(missing, period=missing_period)
        phases.append({"phase": "missing_backfill", **diagnostics})
        _apply_download(existing, downloaded)
        if downloaded:
            save_price_map(cache_path, existing)

    benchmark_date = _latest_date(existing.get("QQQ"))
    stale: list[str] = []
    if benchmark_date is not None:
        for ticker in requested:
            if ticker == "QQQ" or ticker not in existing:
                continue
            latest = _latest_date(existing.get(ticker))
            if latest is None or latest < benchmark_date:
                stale.append(ticker)
    if stale:
        downloaded, diagnostics = provider.download(stale, period="3mo")
        phases.append({"phase": "stale_refresh", **diagnostics})
        _apply_download(existing, downloaded)
        if downloaded:
            save_price_map(cache_path, existing)

    history_requested = history_batch = history_received = 0
    if resolved_history_years and benchmark_date is not None:
        target_start = benchmark_date - pd.DateOffset(years=resolved_history_years)
        tolerance = target_start + pd.Timedelta(days=45)
        short = [
            ticker
            for ticker in requested
            if _earliest_date(existing.get(ticker)) is None
            or _earliest_date(existing.get(ticker)) > tolerance
        ]
        short.sort(
            key=lambda ticker: (
                ticker != "QQQ",
                _earliest_date(existing.get(ticker)) or pd.Timestamp.max,
                ticker,
            )
        )
        history_requested = len(short)
        selected = (
            short[:max_history_tickers]
            if max_history_tickers and max_history_tickers > 0
            else short
        )
        history_batch = len(selected)
        if selected:
            downloaded, diagnostics = provider.download(
                selected, period=f"{resolved_history_years}y"
            )
            phases.append({"phase": "research_history_backfill", **diagnostics})
            _apply_download(existing, downloaded)
            history_received = len(downloaded)
            if downloaded:
                save_price_map(cache_path, existing)

    covered = sum(ticker in existing and not existing[ticker].empty for ticker in requested)
    coverage = covered / len(requested) if requested else 0.0
    still_stale = []
    if benchmark_date is not None:
        still_stale = [
            ticker
            for ticker in requested
            if ticker in existing
            and ticker != "QQQ"
            and (
                _latest_date(existing.get(ticker)) is None
                or _latest_date(existing.get(ticker)) < benchmark_date
            )
        ]
    result = {
        "requested": len(requested),
        "covered": covered,
        "coverage": coverage,
        "qqq_available": "QQQ" in existing and not existing["QQQ"].empty,
        "qqq_latest_date": benchmark_date.date().isoformat()
        if benchmark_date is not None
        else None,
        "provider": provider.name,
        "missing_requested": len(missing),
        "stale_requested": len(stale),
        "still_stale": len(still_stale),
        "history_years_requested": history_years,
        "history_years": resolved_history_years,
        "history_requested": history_requested,
        "history_batch": history_batch,
        "history_received": history_received,
        "phases": phases,
    }
    if not result["qqq_available"]:
        raise RuntimeError("QQQ price history unavailable after retries")
    if coverage < min_coverage:
        raise RuntimeError(
            f"price coverage {coverage:.1%} is below required {min_coverage:.0%}"
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--universe", default="universe.csv")
    parser.add_argument("--prices", default="prices.pkl")
    parser.add_argument("--min-coverage", type=float, default=.70)
    parser.add_argument("--provider", default=None)
    parser.add_argument("--history-years", type=int, default=None)
    parser.add_argument("--max-history-tickers", type=int, default=0)
    args = parser.parse_args()
    print(
        json.dumps(
            run(
                Path(args.universe),
                Path(args.prices),
                min_coverage=args.min_coverage,
                provider_name=args.provider,
                history_years=args.history_years,
                max_history_tickers=max(0, args.max_history_tickers),
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
