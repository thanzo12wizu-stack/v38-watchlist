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


def _exception_type_from_log(path: Path) -> str | None:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-80:]
    except OSError:
        return None
    for line in reversed(lines):
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception))(?::|$)", line.strip())
        if match:
            return match.group(1).split(".")[-1]
    return None


def _failure_payload(returncode: int, log_path: Path, *, stage: str) -> dict:
    if returncode in (-9, 137):
        error_type = "ProcessMemoryLimit"
        template = f"Research {stage} was killed by SIGKILL, usually because the runner exceeded memory."
    elif returncode in (-15, 143):
        error_type = "ProcessTerminated"
        template = f"Research {stage} was terminated before a clean exit."
    else:
        error_type = _exception_type_from_log(log_path) or "ResearchWorkerExit"
        template = f"Research {stage} returned exit code {returncode}."
    return {
        "schema_version": "2.1",
        "failure_kind": "process_exit",
        "stage": stage,
        "error_type": error_type,
        "exit_code": int(returncode),
        "error_template": template,
        "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "privacy": "No ticker, price, portfolio, financial or ranking values are persisted.",
    }


def _run(command: list[str], log_path: Path, *, append: bool = False) -> int:
    mode = "a" if append else "w"
    with log_path.open(mode, encoding="utf-8") as handle:
        completed = subprocess.run(command, stdout=handle, stderr=subprocess.STDOUT, check=False)
    return int(completed.returncode)


def main() -> None:
    arguments = list(sys.argv[1:])
    root = Path(_argument_value(arguments, "--root", "data/intelligence/research"))
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
    signal_partitions = list((root / "signals").glob("year=*.jsonl.gz"))
    ranking_partitions = list((root / "rankings").glob("year=*.jsonl.gz"))
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
    _write_json(
        success_path,
        {
            "schema_version": "2.1",
            "research_status": "PASS",
            "completed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "manifest_present": True,
            "summary_present": True,
            "model_audit_present": True,
            "model_audit_status": audit.get("status"),
            "signal_partition_count": len(signal_partitions),
            "ranking_partition_count": len(ranking_partitions),
            "years_retained": manifest.get("years_retained"),
            "learning_event_rows": (audit.get("sampling") or {}).get("learning_event_rows"),
            "privacy": "No ticker, price, portfolio, financial or ranking values are included.",
        },
    )

    print(
        json.dumps(
            {
                "research_status": "PASS",
                "signal_partitions": len(signal_partitions),
                "ranking_partitions": len(ranking_partitions),
                "years_retained": manifest.get("years_retained"),
                "model_audit_status": audit.get("status"),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
