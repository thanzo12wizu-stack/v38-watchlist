from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _partition_count(root: Path, dataset: str) -> int:
    return sum(1 for path in (root / dataset).glob("year=*.jsonl.gz") if path.is_file())


def build_status(
    *,
    action: str,
    research_year: int,
    price_report: Path,
    sec_dir: Path,
    research_root: Path,
    private_dir: Path,
) -> dict[str, Any]:
    action = str(action).strip().upper()
    if action not in {"PRICE_WARMUP", "YEAR_BACKFILL"}:
        raise ValueError(f"unsupported research worker action: {action}")

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    price = _read_json(price_report)
    sec_cache_file_count = sum(1 for path in sec_dir.glob("*.json") if path.is_file() and path.stat().st_size > 0)
    fact_partition_count = _partition_count(research_root, "facts")
    signal_partition_count = _partition_count(research_root, "signals")
    outcome_partition_count = _partition_count(research_root, "outcomes")
    ranking_partition_count = _partition_count(research_root, "rankings")

    result = {
        "schema_version": "1.0",
        "completed_at": now,
        "workflow_run_id": os.environ.get("GITHUB_RUN_ID") or None,
        "action": action,
        "research_year": int(research_year),
        "status": "PASS",
        "price_provider": price.get("provider"),
        "price_coverage": price.get("coverage"),
        "price_history_requested": price.get("history_requested"),
        "price_history_batch": price.get("history_batch"),
        "price_history_received": price.get("history_received"),
        "sec_cache_file_count": sec_cache_file_count,
        "sec_cache_ready": sec_cache_file_count > 0,
        "fact_partition_count": fact_partition_count,
        "signal_partition_count": signal_partition_count,
        "outcome_partition_count": outcome_partition_count,
        "ranking_partition_count": ranking_partition_count,
        "sec_data_ready": sec_cache_file_count > 0 and fact_partition_count > 0,
        "privacy": "Only aggregate worker progress is included; no ticker, price, financial, ranking or portfolio values are stored.",
    }
    _write_json(private_dir / "research-worker-result.json", result)

    if action == "YEAR_BACKFILL":
        success_path = private_dir / "research-success.json"
        prior = _read_json(success_path)
        success = {
            "schema_version": "2.2",
            "research_status": "PASS",
            "completed_at": now,
            "manifest_present": (research_root / "manifest.json").exists(),
            "summary_present": (private_dir / "research-summary.enc.json").exists(),
            "model_audit_present": bool(prior.get("model_audit_present")),
            "model_audit_status": prior.get("model_audit_status"),
            "signal_partition_count": signal_partition_count,
            "ranking_partition_count": ranking_partition_count,
            "fact_partition_count": fact_partition_count,
            "outcome_partition_count": outcome_partition_count,
            "years_retained": 10,
            "learning_event_rows": prior.get("learning_event_rows"),
            "sec_cache_file_count": sec_cache_file_count,
            "sec_data_present": sec_cache_file_count > 0 and fact_partition_count > 0,
            "last_worker_run_id": result["workflow_run_id"],
            "last_worker_action": action,
            "last_worker_year": int(research_year),
            "privacy": "No ticker, price, portfolio, financial or ranking values are included.",
        }
        _write_json(success_path, success)

    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", required=True)
    parser.add_argument("--research-year", required=True, type=int)
    parser.add_argument("--price-report", default="/tmp/price-warmup-report.json")
    parser.add_argument("--sec-dir", default="data/sec_companyfacts")
    parser.add_argument("--research-root", default="data/intelligence/research")
    parser.add_argument("--private-dir", default="private")
    args = parser.parse_args()
    result = build_status(
        action=args.action,
        research_year=args.research_year,
        price_report=Path(args.price_report),
        sec_dir=Path(args.sec_dir),
        research_root=Path(args.research_root),
        private_dir=Path(args.private_dir),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
