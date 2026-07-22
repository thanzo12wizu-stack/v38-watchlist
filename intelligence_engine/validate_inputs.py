from __future__ import annotations

import argparse
import json
import pickle
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pandas as pd


def _describe_price_object(obj: Any) -> dict[str, Any]:
    report: dict[str, Any] = {"python_type": type(obj).__name__}
    if isinstance(obj, Mapping):
        report["shape"] = "mapping"
        report["ticker_count"] = len(obj)
        sample = []
        for key, value in list(obj.items())[:5]:
            item = {"key": str(key), "value_type": type(value).__name__}
            if isinstance(value, pd.DataFrame):
                item.update({
                    "rows": len(value),
                    "columns": [str(c) for c in value.columns],
                    "index_type": type(value.index).__name__,
                })
            sample.append(item)
        report["sample"] = sample
    elif isinstance(obj, pd.DataFrame):
        report.update({
            "shape": "dataframe",
            "rows": len(obj),
            "columns": [str(c) for c in obj.columns],
            "column_index_type": type(obj.columns).__name__,
            "index_type": type(obj.index).__name__,
        })
    else:
        report["shape"] = "unsupported"
    return report


def inspect_inputs(universe_path: Path, prices_path: Path) -> dict[str, Any]:
    report: dict[str, Any] = {
        "contract_version": "1.0",
        "universe": {"path": str(universe_path), "exists": universe_path.exists()},
        "prices": {"path": str(prices_path), "exists": prices_path.exists()},
        "errors": [],
    }

    if universe_path.exists():
        try:
            universe = pd.read_csv(universe_path)
            report["universe"].update({
                "rows": len(universe),
                "columns": [str(c) for c in universe.columns],
                "ticker_candidates": [
                    c for c in universe.columns
                    if str(c).strip().lower() in {"ticker", "symbol", "tickers"}
                ],
            })
        except Exception as exc:  # diagnostic command must always emit a report
            report["errors"].append(f"universe: {type(exc).__name__}: {exc}")

    if prices_path.exists():
        try:
            # This command runs only on repository-owned cache files. It inspects
            # shape and metadata; production loading remains isolated elsewhere.
            with prices_path.open("rb") as handle:
                obj = pickle.load(handle)
            report["prices"].update(_describe_price_object(obj))
        except Exception as exc:
            report["errors"].append(f"prices: {type(exc).__name__}: {exc}")

    report["compatible"] = bool(
        report["universe"].get("ticker_candidates")
        and report["prices"].get("shape") in {"mapping", "dataframe"}
        and not report["errors"]
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect repository inputs without writing project data")
    parser.add_argument("--universe", type=Path, required=True)
    parser.add_argument("--prices", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    report = inspect_inputs(args.universe, args.prices)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if report["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
