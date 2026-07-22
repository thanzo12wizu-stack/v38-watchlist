from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from .display_labels import (
    candidates_with_freshness,
    external_for_display,
    portfolio_for_display,
    quality_for_display,
)
from .expectancy import EXPECTANCY_POLICY_VERSION, build_expectancy, calibrate_candidates
from .external_data import EXTERNAL_DATA_POLICY_VERSION, apply_external_context, build_external_records, load_external_layer
from .leader_history import LEADER_HISTORY_POLICY_VERSION, build_price_leader_transitions
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
from .portfolio import PORTFOLIO_POLICY_VERSION, build_portfolio_doctor, load_positions
from .presentation import PRESENTATION_POLICY_VERSION, enrich_candidates, partition_candidates
from .prices import load_price_map
from .utils import atomic_write_json


def _scored_from_index(index: dict) -> pd.DataFrame:
    rows = []
    for stock in index.get("stocks", []):
        row = {
            "ticker": stock.get("ticker"),
            "sector": stock.get("sector"),
            "industry": stock.get("industry"),
            "score_confidence": stock.get("confidence"),
            "score_leader_confidence": stock.get("leader_confidence"),
            "score_entry_confidence": stock.get("entry_confidence"),
            "score_story_confidence": stock.get("story_confidence"),
        }
        row.update(stock.get("features") or {})
        row.update({f"score_{key}": value for key, value in (stock.get("scores") or {}).items()})
        rows.append(row)
    return pd.DataFrame(rows)


def _price_asof(prices: dict[str, pd.DataFrame]) -> str | None:
    qqq = prices.get("QQQ")
    if qqq is None or qqq.empty or not isinstance(qqq.index, pd.DatetimeIndex):
        return None
    value = pd.Timestamp(qqq.index.max())
    if value.tzinfo is not None:
        value = value.tz_convert(None)
    return value.date().isoformat()


def _leader_board_from_index(index: dict) -> dict[str, list[dict]]:
    stocks = index.get("stocks") or []
    output: dict[str, list[dict]] = {}
    for window in (63, 126, 189):
        key = f"pct_rs_raw_{window}"
        ranked = sorted(
            stocks,
            key=lambda stock: (
                -float((stock.get("features") or {}).get(key) or -1),
                str(stock.get("ticker") or ""),
            ),
        )[:10]
        output[f"rs{window}"] = [
            {
                "ticker": stock.get("ticker"),
                "rank": rank,
                "rs_percentile": (stock.get("features") or {}).get(key),
                "sector": stock.get("sector"),
                "industry": stock.get("industry"),
            }
            for rank, stock in enumerate(ranked, 1)
        ]
    return output


def _resolve_external_coverage(candidates: list[dict]) -> list[dict]:
    output = []
    for candidate in candidates:
        item = dict(candidate)
        external = item.get("external_data") or {}
        warnings = list(item.get("warnings") or [])
        if external.get("next_earnings_date") or external.get("earnings_date"):
            warnings = [warning for warning in warnings if warning != "earnings_unknown"]
        elif "earnings_unknown" not in warnings:
            warnings.append("earnings_unknown")
        item["warnings"] = list(dict.fromkeys(warnings))
        output.append(item)
    return output


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
    price_asof = _price_asof(prices)

    expectancy = build_expectancy(prices)
    candidates = calibrate_candidates(index.get("entry_candidates") or [], expectancy)
    layer = load_external_layer(external_root)
    tickers = scored.get("ticker", pd.Series(dtype=str)).dropna().astype(str).tolist()
    records = build_external_records(tickers, layer)
    candidates = apply_external_context(candidates, records)
    candidates = _resolve_external_coverage(candidates)
    candidates = enrich_candidates(candidates, generated_at=index.get("generated_at"), price_asof=price_asof)
    candidates = candidates_with_freshness(
        candidates,
        generated_at=index.get("generated_at"),
        price_asof=price_asof,
    )
    partitions = partition_candidates(candidates)
    index["entry_candidates"] = candidates
    index["candidate_partitions"] = partitions
    index["expectancy_rankings"] = expectancy
    index["external_data"] = records

    positions = load_positions(portfolio_path)
    doctor = build_portfolio_doctor(positions, scored, prices, index.get("market_state") or {})

    history_dir = root / "history"
    ledger_dir = root / "observations"
    previous = load_prior_history(history_dir, index)
    snapshot_transitions = detect_leader_transitions(index, history_dir)
    price_transitions = build_price_leader_transitions(prices)
    transitions = snapshot_transitions if snapshot_transitions.get("status") == "OK" else price_transitions
    transitions["snapshot_status"] = snapshot_transitions.get("status")
    transitions["price_history_status"] = price_transitions.get("status")
    leader_board = price_transitions.get("leader_board") or _leader_board_from_index(index)

    settled = settle_outcomes(ledger_dir, prices)
    snapshot = freeze_snapshot(index, ledger_dir)
    robust = build_robust_expectancy(ledger_dir)
    quality = build_quality_report(index, prices, external_root, previous)

    brief = build_morning_brief(
        index.get("market_state") or {},
        index.get("sector_rotation") or [],
        index.get("theme_intelligence") or [],
        candidates,
        doctor,
        leader_transitions=transitions,
        expectancy=expectancy,
        quality=quality,
    )
    index["external_data"] = external_for_display(records)
    index["portfolio_doctor"] = portfolio_for_display(doctor)
    index["morning_brief"] = brief
    index["leader_transitions"] = transitions
    index["leader_board"] = leader_board
    index["robust_expectancy"] = robust
    index["data_quality"] = quality_for_display(quality)

    market_state = index.setdefault("market_state", {})
    market_state["candidate_counts"] = {
        "actionable": len(partitions["ACTIONABLE"]),
        "ready": len(partitions["READY"]),
        "avoid": len(partitions["AVOID"]),
    }
    market_state["summary_20s"] = brief.get("summary_20s")

    manifest = index.setdefault("manifest", {})
    manifest.update(
        {
            "portfolio_position_count": doctor.get("position_count", 0),
            "expectancy_policy_version": EXPECTANCY_POLICY_VERSION,
            "expectancy_sample_count": expectancy.get("sample_count", 0),
            "external_data_policy_version": EXTERNAL_DATA_POLICY_VERSION,
            "external_data_covered_count": sum(any(record.get("coverage", {}).values()) for record in records),
            "portfolio_policy_version": PORTFOLIO_POLICY_VERSION,
            "operational_policy_version": OPERATIONAL_POLICY_VERSION,
            "presentation_policy_version": PRESENTATION_POLICY_VERSION,
            "leader_history_policy_version": LEADER_HISTORY_POLICY_VERSION,
            "quality_status": quality.get("status"),
            "settled_outcomes": settled.get("settled", 0),
            "actionable_candidate_count": len(partitions["ACTIONABLE"]),
            "ready_candidate_count": len(partitions["READY"]),
            "avoid_candidate_count": len(partitions["AVOID"]),
            "price_asof": price_asof,
        }
    )

    atomic_write_json(root / "expectancy_rankings.json", expectancy)
    atomic_write_json(root / "robust_expectancy.json", robust)
    atomic_write_json(root / "external_data.json", {"policy_version": EXTERNAL_DATA_POLICY_VERSION, "records": records})
    atomic_write_json(root / "leader_transitions.json", transitions)
    atomic_write_json(root / "leader_board.json", {"policy_version": LEADER_HISTORY_POLICY_VERSION, "boards": leader_board})
    atomic_write_json(root / "data_quality.json", quality)
    atomic_write_json(root / "portfolio_doctor.json", doctor)
    atomic_write_json(root / "morning_brief.json", brief)
    atomic_write_json(
        root / "entry_candidates.json",
        {
            "generated_at": index.get("generated_at"),
            "candidate_counts": market_state["candidate_counts"],
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
        "candidate_counts": market_state["candidate_counts"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="data/intelligence")
    parser.add_argument("--prices", default="prices.pkl")
    parser.add_argument("--portfolio", default="portfolio.csv")
    parser.add_argument("--external-root", default="data/external")
    args = parser.parse_args()
    print(json.dumps(run(Path(args.root), Path(args.prices), Path(args.portfolio), Path(args.external_root)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
