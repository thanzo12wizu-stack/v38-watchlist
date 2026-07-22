from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from .expectancy import (
    EXPECTANCY_POLICY_VERSION,
    build_expectancy,
    calibrate_candidates,
)
from .external_data import (
    EXTERNAL_DATA_POLICY_VERSION,
    apply_external_context,
    build_external_records,
    load_external_layer,
)
from .morning_brief import build_morning_brief
from .operational_pipeline import (
    OPERATIONAL_POLICY_VERSION,
    build_quality_report,
    build_robust_expectancy,
    detect_leader_transitions,
    freeze_snapshot,
    load_prior_history,
    settle_outcomes,
)
from .portfolio import (
    PORTFOLIO_POLICY_VERSION,
    build_portfolio_doctor,
    load_positions,
)
from .prices import load_price_map
from .utils import atomic_write_json


def _scored_from_index(index: dict) -> pd.DataFrame:
    rows = []
    for stock in index.get("stocks", []):
        row = {
            "ticker": stock.get("ticker"),
            "sector": stock.get("sector"),
            "industry": stock.get("industry"),
        }
        row.update(stock.get("features") or {})
        row.update(
            {f"score_{key}": value for key, value in (stock.get("scores") or {}).items()}
        )
        rows.append(row)
    return pd.DataFrame(rows)


def run(
    root: Path,
    prices_path: Path,
    portfolio_path: Path,
    external_root: Path | None = None,
) -> dict:
    index_path = root / "index.json"
    if not index_path.exists():
        raise FileNotFoundError(f"missing intelligence index: {index_path}")
    index = json.loads(index_path.read_text(encoding="utf-8"))
    if not isinstance(index, dict):
        raise TypeError("intelligence index must be a JSON object")

    scored = _scored_from_index(index)
    prices = load_price_map(prices_path) if prices_path.exists() else {}
    external_root = external_root or Path("data/external")

    expectancy = build_expectancy(prices)
    candidates = calibrate_candidates(
        index.get("entry_candidates") or [],
        expectancy,
    )
    layer = load_external_layer(external_root)
    tickers = (
        scored.get("ticker", pd.Series(dtype=str))
        .dropna()
        .astype(str)
        .tolist()
    )
    records = build_external_records(tickers, layer)
    candidates = apply_external_context(candidates, records)
    index["entry_candidates"] = candidates
    index["expectancy_rankings"] = expectancy
    index["external_data"] = records

    positions = load_positions(portfolio_path)
    doctor = build_portfolio_doctor(
        positions,
        scored,
        prices,
        index.get("market_state") or {},
    )
    brief = build_morning_brief(
        index.get("market_state") or {},
        index.get("sector_rotation") or [],
        index.get("theme_intelligence") or [],
        candidates,
        doctor,
    )
    index["portfolio_doctor"] = doctor
    index["morning_brief"] = brief

    history_dir = root / "history"
    ledger_dir = root / "observations"
    previous = load_prior_history(history_dir, index)
    transitions = detect_leader_transitions(index, history_dir)
    settled = settle_outcomes(ledger_dir, prices)
    snapshot = freeze_snapshot(index, ledger_dir)
    robust = build_robust_expectancy(ledger_dir)
    quality = build_quality_report(
        index,
        prices,
        external_root,
        previous,
    )
    index["leader_transitions"] = transitions
    index["robust_expectancy"] = robust
    index["data_quality"] = quality

    manifest = index.setdefault("manifest", {})
    manifest.update(
        {
            "portfolio_position_count": doctor.get("position_count", 0),
            "expectancy_policy_version": EXPECTANCY_POLICY_VERSION,
            "expectancy_sample_count": expectancy.get("sample_count", 0),
            "external_data_policy_version": EXTERNAL_DATA_POLICY_VERSION,
            "external_data_covered_count": sum(
                any(record.get("coverage", {}).values()) for record in records
            ),
            "portfolio_policy_version": PORTFOLIO_POLICY_VERSION,
            "operational_policy_version": OPERATIONAL_POLICY_VERSION,
            "quality_status": quality.get("status"),
            "settled_outcomes": settled.get("settled", 0),
        }
    )

    atomic_write_json(root / "expectancy_rankings.json", expectancy)
    atomic_write_json(root / "robust_expectancy.json", robust)
    atomic_write_json(
        root / "external_data.json",
        {"policy_version": EXTERNAL_DATA_POLICY_VERSION, "records": records},
    )
    atomic_write_json(root / "leader_transitions.json", transitions)
    atomic_write_json(root / "data_quality.json", quality)
    atomic_write_json(root / "portfolio_doctor.json", doctor)
    atomic_write_json(root / "morning_brief.json", brief)
    atomic_write_json(
        root / "entry_candidates.json",
        {
            "generated_at": index.get("generated_at"),
            "candidates": candidates,
        },
    )
    atomic_write_json(index_path, index)
    if (root / "manifest.json").exists():
        atomic_write_json(root / "manifest.json", manifest)

    return {
        "portfolio": doctor.get("status"),
        "expectancy": expectancy.get("status"),
        "robust_expectancy": robust.get("status"),
        "external_covered": manifest["external_data_covered_count"],
        "quality": quality.get("status"),
        "snapshot": snapshot.get("status"),
        "settled": settled.get("settled", 0),
        "leader_transitions": transitions.get("status"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="data/intelligence")
    parser.add_argument("--prices", default="prices.pkl")
    parser.add_argument("--portfolio", default="portfolio.csv")
    parser.add_argument("--external-root", default="data/external")
    args = parser.parse_args()
    print(
        json.dumps(
            run(
                Path(args.root),
                Path(args.prices),
                Path(args.portfolio),
                Path(args.external_root),
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
