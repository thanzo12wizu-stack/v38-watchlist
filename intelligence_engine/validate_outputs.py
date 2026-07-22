from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


REQUIRED_INDEX_KEYS = {"generated_at", "schema_version", "stocks"}
REQUIRED_STOCK_KEYS = {"ticker", "scores", "features", "confidence"}


def _reject_nonstandard_constant(token: str) -> None:
    raise ValueError(f"non-standard JSON constant: {token}")


def _load(path: Path) -> Any:
    return json.loads(
        path.read_text(encoding="utf-8"),
        parse_constant=_reject_nonstandard_constant,
    )


def _valid_score(value: object) -> bool:
    if not isinstance(value, (int, float)):
        return False
    number = float(value)
    return math.isfinite(number) and 0 <= number <= 100


def validate(root: Path) -> list[str]:
    errors: list[str] = []
    index_path = root / "index.json"
    manifest_path = root / "manifest.json"
    if not index_path.exists():
        return ["missing index.json"]
    if not manifest_path.exists():
        errors.append("missing manifest.json")

    try:
        index = _load(index_path)
    except Exception as exc:
        return [f"invalid index.json: {type(exc).__name__}: {exc}"]

    missing = REQUIRED_INDEX_KEYS - set(index)
    if missing:
        errors.append(f"index.json missing keys: {sorted(missing)}")
    stocks = index.get("stocks")
    if not isinstance(stocks, list):
        errors.append("index.stocks must be a list")
        return errors

    seen: set[str] = set()
    for number, stock in enumerate(stocks):
        if not isinstance(stock, dict):
            errors.append(f"stocks[{number}] must be an object")
            continue
        missing_stock = REQUIRED_STOCK_KEYS - set(stock)
        if missing_stock:
            errors.append(f"stocks[{number}] missing keys: {sorted(missing_stock)}")
        ticker = stock.get("ticker")
        if not isinstance(ticker, str) or not ticker:
            errors.append(f"stocks[{number}].ticker must be non-empty string")
        elif ticker in seen:
            errors.append(f"duplicate ticker: {ticker}")
        else:
            seen.add(ticker)
        scores = stock.get("scores")
        if not isinstance(scores, dict):
            errors.append(f"{ticker or number}: scores must be object")
        else:
            for key, value in scores.items():
                if value is not None and not _valid_score(value):
                    errors.append(f"{ticker or number}: score {key} outside finite 0..100")
        confidence = stock.get("confidence")
        if confidence is not None and not _valid_score(confidence):
            errors.append(f"{ticker or number}: confidence outside finite 0..100")

    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate the stable intelligence JSON contract")
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    errors = validate(args.root)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        raise SystemExit(1)
    print("INTELLIGENCE OUTPUT CONTRACT OK")


if __name__ == "__main__":
    main()
