from __future__ import annotations

import argparse
import json
from pathlib import Path

from .pipeline import load_universe
from .prices import download_price_map, load_price_map, save_price_map


def run(universe_path: Path, cache_path: Path, *, min_coverage: float = 0.70) -> dict:
    universe = load_universe(universe_path)
    requested = sorted(set(universe["ticker"].astype(str)) | {"QQQ"})
    existing = load_price_map(cache_path) if cache_path.exists() else {}
    missing = [ticker for ticker in requested if ticker not in existing]
    diagnostics = {"source": "cache", "requested": len(requested), "received": len(existing), "coverage": len(existing) / len(requested) if requested else 0.0}
    if missing:
        downloaded, diagnostics = download_price_map(missing)
        existing.update(downloaded)
        if downloaded:
            save_price_map(cache_path, existing)
    covered = sum(ticker in existing for ticker in requested)
    coverage = covered / len(requested) if requested else 0.0
    result = {
        "requested": len(requested), "covered": covered, "coverage": coverage,
        "qqq_available": "QQQ" in existing, "download": diagnostics,
    }
    if "QQQ" not in existing:
        raise RuntimeError("QQQ price history unavailable after retries")
    if coverage < min_coverage:
        raise RuntimeError(f"price coverage {coverage:.1%} is below required {min_coverage:.0%}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--universe", default="universe.csv")
    parser.add_argument("--prices", default="prices.pkl")
    parser.add_argument("--min-coverage", type=float, default=.70)
    args = parser.parse_args()
    print(json.dumps(run(Path(args.universe), Path(args.prices), min_coverage=args.min_coverage), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
