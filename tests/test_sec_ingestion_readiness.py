from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path


def test_research_success_marker_reports_actual_sec_ingestion(tmp_path, monkeypatch) -> None:
    runner = importlib.import_module("intelligence_engine.research_pipeline.__main__")
    root = tmp_path / "research"
    sec_dir = tmp_path / "sec"
    private = tmp_path / "private"
    for directory in (
        root / "facts",
        root / "signals",
        root / "outcomes",
        root / "rankings",
        sec_dir,
        private,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    for name, payload in (
        ("manifest.json", {"years_retained": 10}),
        ("expectancy.json", {"status": "OK"}),
        ("current_rankings.json", {"status": "OK"}),
        ("model-audit.json", {"status": "PASS", "sampling": {"learning_event_rows": 42}}),
    ):
        (root / name).write_text(json.dumps(payload), encoding="utf-8")

    for path in (
        root / "facts" / "year=2026.jsonl.gz",
        root / "signals" / "year=2026.jsonl.gz",
        root / "outcomes" / "year=2026.jsonl.gz",
        root / "rankings" / "year=2026.jsonl.gz",
    ):
        path.write_bytes(b"x")
    (sec_dir / "AAPL.json").write_text("{}", encoding="utf-8")
    (sec_dir / "MSFT.json").write_text("{}", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(runner, "_run", lambda *args, **kwargs: 0)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "research_pipeline",
            "--root",
            str(root),
            "--sec-dir",
            str(sec_dir),
        ],
    )

    runner.main()

    marker = json.loads((private / "research-success.json").read_text(encoding="utf-8"))
    assert marker["sec_cache_file_count"] == 2
    assert marker["fact_partition_count"] == 1
    assert marker["outcome_partition_count"] == 1
    assert marker["sec_data_present"] is True
    assert marker["learning_event_rows"] == 42


def test_readiness_distinguishes_configuration_from_ingestion() -> None:
    workflow = Path(".github/workflows/research-status-marker.yml").read_text(encoding="utf-8")

    assert "sec_user_agent_configured" in workflow
    assert "sec_cache_file_count" in workflow
    assert "sec_fact_partition_count" in workflow
    assert "sec_data_ready" in workflow
    assert "sec_data_not_ingested" in workflow
    assert "full_operational_ready" in workflow
