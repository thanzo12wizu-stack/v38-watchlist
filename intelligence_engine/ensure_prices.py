from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from .pipeline import load_universe
from .prices import load_price_map, save_price_map
from .providers import get_price_provider


def _latest_date(frame: pd.DataFrame | None) -> pd.Timestamp | None:
    if frame is None or frame.empty or not isinstance(frame.index, pd.DatetimeIndex):
        return None
    index = frame.index
    if index.tz is not None:
        index = index.tz_convert(None)
    return pd.Timestamp(index.max()).normalize()


def _merge_frame(existing: pd.DataFrame | None, update: pd.DataFrame) -> pd.DataFrame:
    if existing is None or existing.empty:
        return update.sort_index().loc[~update.index.duplicated(keep="last")]
    combined = pd.concat([existing, update], axis=0).sort_index()
    combined = combined.loc[~combined.index.duplicated(keep="last")]
    return combined


def _apply_download(
    existing: dict[str, pd.DataFrame],
    downloaded: dict[str, pd.DataFrame],
) -> None:
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
) -> dict:
    universe = load_universe(universe_path)
    requested = sorted(set(universe["ticker"].astype(str)) | {"QQQ"})
    existing = load_price_map(cache_path) if cache_path.exists() else {}
    provider = get_price_provider(provider_name)
    phases: list[dict] = []

    benchmark_update, benchmark_diagnostics = provider.download(["QQQ"], period="3mo")
    phases.append({"phase": "benchmark_refresh", **benchmark_diagnostics})
    _apply_download(existing, benchmark_update)
    if benchmark_update:
        save_price_map(cache_path, existing)

    missing = [ticker for ticker in requested if ticker not in existing]
    if missing:
        downloaded, diagnostics = provider.download(missing, period="18mo")
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

    covered = sum(ticker in existing and not existing[ticker].empty for ticker in requested)
    coverage = covered / len(requested) if requested else 0.0
    still_stale = []
    if benchmark_date is not None:
        still_stale = [
            ticker
            for ticker in requested
            if ticker in existing
            and ticker != "QQQ"
            and (_latest_date(existing.get(ticker)) is None or _latest_date(existing.get(ticker)) < benchmark_date)
        ]
    result = {
        "requested": len(requested),
        "covered": covered,
        "coverage": coverage,
        "qqq_available": "QQQ" in existing and not existing["QQQ"].empty,
        "qqq_latest_date": benchmark_date.date().isoformat() if benchmark_date is not None else None,
        "provider": provider.name,
        "missing_requested": len(missing),
        "stale_requested": len(stale),
        "still_stale": len(still_stale),
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
    args = parser.parse_args()
    print(
        json.dumps(
            run(
                Path(args.universe),
                Path(args.prices),
                min_coverage=args.min_coverage,
                provider_name=args.provider,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
