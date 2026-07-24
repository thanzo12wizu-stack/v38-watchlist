from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _argument_value(arguments: list[str], name: str, default: str) -> str:
    try:
        index = arguments.index(name)
    except ValueError:
        return default
    return arguments[index + 1] if index + 1 < len(arguments) else default


def _exception_from_log(path: Path) -> tuple[str | None, str | None]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-120:]
    except OSError:
        return None, None
    for line in reversed(lines):
        match = re.match(
            r"^([A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception))(?::\s*(.*))?$",
            line.strip(),
        )
        if not match:
            continue
        error_type = match.group(1).split(".")[-1]
        detail = (match.group(2) or "").strip()
        # Persist detailed text only for pandas MergeError. Its messages describe
        # column/dtype contracts, not ticker, price, financial, or ranking values.
        if error_type != "MergeError":
            detail = ""
        return error_type, detail[:500] or None
    return None, None


def _failure_payload(returncode: int, log_path: Path, *, stage: str = "worker") -> dict:
    detail: str | None = None
    if returncode in (-9, 137):
        error_type = "ProcessMemoryLimit"
        template = f"Research {stage} was killed by SIGKILL, usually because the runner exceeded memory."
    elif returncode in (-15, 143):
        error_type = "ProcessTerminated"
        template = f"Research {stage} was terminated before a clean exit."
    else:
        parsed_type, detail = _exception_from_log(log_path)
        error_type = parsed_type or "ResearchWorkerExit"
        template = f"Research {stage} returned exit code {returncode}."
    payload = {
        "schema_version": "2.2",
        "failure_kind": "process_exit",
        "stage": stage,
        "error_type": error_type,
        "exit_code": int(returncode),
        "error_template": template,
        "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "privacy": "No ticker, price, portfolio, financial or ranking values are persisted.",
    }
    if detail:
        payload["error_detail"] = detail
    return payload


def _run(command: list[str], log_path: Path, *, append: bool = False) -> int:
    mode = "a" if append else "w"
    with log_path.open(mode, encoding="utf-8") as handle:
        completed = subprocess.run(command, stdout=handle, stderr=subprocess.STDOUT, check=False)
    return int(completed.returncode)


def main() -> None:
    arguments = list(sys.argv[1:])
    root = Path(_argument_value(arguments, "--root", "data/intelligence/research"))
    sec_dir = Path(_argument_value(arguments, "--sec-dir", "data/sec_companyfacts"))
    private = Path("private")
    success_path = private / "research-success.json"
    error_path = private / "research-error-detail.json"
    success_path.unlink(missing_ok=True)
    error_path.unlink(missing_ok=True)

    log_path = Path(os.environ.get("V38_RESEARCH_LOG_PATH", "/tmp/v38-research-worker.log"))
    worker = [sys.executable, "-m", "intelligence_engine.research_pipeline.worker", *arguments]
    worker_code = _run(worker, log_path)
    if worker_code != 0:
        _write_json(error_path, _failure_payload(worker_code, log_path, stage="worker"))
        raise SystemExit(1)

    postprocess = [sys.executable, "-m", "intelligence_engine.research_postprocess", *arguments]
    postprocess_code = _run(postprocess, log_path, append=True)
    if postprocess_code != 0:
        _write_json(error_path, _failure_payload(postprocess_code, log_path, stage="postprocess"))
        raise SystemExit(1)

    required = [
        root / "manifest.json",
        root / "expectancy.json",
        root / "current_rankings.json",
        root / "model-audit.json",
    ]
    fact_partitions = list((root / "facts").glob("year=*.jsonl.gz"))
    signal_partitions = list((root / "signals").glob("year=*.jsonl.gz"))
    outcome_partitions = list((root / "outcomes").glob("year=*.jsonl.gz"))
    ranking_partitions = list((root / "rankings").glob("year=*.jsonl.gz"))
    sec_cache_files = list(sec_dir.glob("*.json")) if sec_dir.exists() else []
    missing = [path.name for path in required if not path.exists()]
    if missing or not signal_partitions or not ranking_partitions:
        _write_json(
            error_path,
            {
                "schema_version": "2.1",
                "failure_kind": "output_contract",
                "error_type": "MissingResearchOutputs",
                "error_template": "Research completed but required normalized outputs were not produced.",
                "missing_output_count": len(missing) + int(not signal_partitions) + int(not ranking_partitions),
                "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "privacy": "No ticker, price, portfolio, financial or ranking values are persisted.",
            },
        )
        raise SystemExit(1)

    try:
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        audit = json.loads((root / "model-audit.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        manifest = {}
        audit = {}

    sec_cache_file_count = len(sec_cache_files)
    fact_partition_count = len(fact_partitions)
    sec_data_present = sec_cache_file_count > 0 and fact_partition_count > 0
    _write_json(
        success_path,
        {
            "schema_version": "2.2",
            "research_status": "PASS",
            "completed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "manifest_present": True,
            "summary_present": True,
            "model_audit_present": True,
            "model_audit_status": audit.get("status"),
            "fact_partition_count": fact_partition_count,
            "signal_partition_count": len(signal_partitions),
            "outcome_partition_count": len(outcome_partitions),
            "ranking_partition_count": len(ranking_partitions),
            "sec_cache_file_count": sec_cache_file_count,
            "sec_data_present": sec_data_present,
            "years_retained": manifest.get("years_retained"),
            "learning_event_rows": (audit.get("sampling") or {}).get("learning_event_rows"),
            "privacy": "No ticker, price, portfolio, financial or ranking values are included.",
        },
    )

    print(
        json.dumps(
            {
                "research_status": "PASS",
                "fact_partitions": fact_partition_count,
                "signal_partitions": len(signal_partitions),
                "outcome_partitions": len(outcome_partitions),
                "ranking_partitions": len(ranking_partitions),
                "sec_cache_files": sec_cache_file_count,
                "sec_data_present": sec_data_present,
                "years_retained": manifest.get("years_retained"),
                "model_audit_status": audit.get("status"),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
