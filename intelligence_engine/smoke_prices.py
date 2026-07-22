from __future__ import annotations

import argparse
import json
from pathlib import Path

from .prices import compute_price_features, download_price_map
from .utils import atomic_write_json


def run(tickers: list[str]) -> dict:
    requested = sorted(set(ticker.upper().strip() for ticker in tickers if ticker.strip()) | {"QQQ"})
    prices, diagnostics = download_price_map(requested, period="18mo", batch_size=20)
    qqq = prices.get("QQQ")
    benchmark = qqq["close"] if qqq is not None and "close" in qqq else None
    feature_status: dict[str, dict] = {}
    if benchmark is not None:
        for ticker in requested:
            frame = prices.get(ticker)
            if frame is None:
                feature_status[ticker] = {"available": False}
                continue
            features = compute_price_features(frame, benchmark)
            feature_status[ticker] = {
                "available": bool(features),
                "rows": len(frame),
                "has_rs189": features.get("rs_raw_189") is not None if features else False,
                "has_liquidity": features.get("dollar_volume_20d") is not None if features else False,
            }
    report = {
        "requested": requested,
        "diagnostics": diagnostics,
        "benchmark_available": benchmark is not None,
        "features": feature_status,
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Small live-data smoke test for the price adapter")
    parser.add_argument("--tickers", default="AAPL,MSFT,NVDA,AMD")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    report = run(args.tickers.split(","))
    atomic_write_json(args.report, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    available = sum(1 for item in report["features"].values() if item.get("available"))
    if args.strict and (not report["benchmark_available"] or available < 3):
        raise SystemExit("live price smoke test below minimum coverage")


if __name__ == "__main__":
    main()
