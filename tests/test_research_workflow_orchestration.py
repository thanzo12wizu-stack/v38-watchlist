from pathlib import Path


def _text(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_bootstrap_dispatches_one_bounded_worker_slice_per_controller_run():
    workflow = _text(".github/workflows/research-bootstrap.yml")

    assert 'cron: "12 * * * *"' in workflow
    assert "research-worker.yml" in workflow
    assert "research-worker-runs.json" in workflow
    assert "databaseId,status,conclusion,createdAt" in workflow
    assert workflow.count("gh workflow run research-worker.yml") == 1
    assert "for year in $(seq" not in workflow
    assert "for run in $(seq" not in workflow
    assert "research-bootstrap-status.json" in workflow
    assert "PRICE_WARMUP" in workflow
    assert "YEAR_BACKFILL" in workflow
    assert "awaiting_result" in workflow
    assert "warmup_runs_completed" in workflow
    assert "DISPATCH_NOT_FOUND_RETRY" in workflow
    assert "sec_data_ready" in workflow


def test_ten_year_worker_uses_hard_ten_year_contract_and_verified_sec():
    worker = _text(".github/workflows/research-worker.yml")

    assert "--history-years 10" in worker
    assert "--years 10" in worker
    assert "--report /tmp/sec-bulk-report.json" in worker
    assert "SEC Company Facts ingestion produced zero files" in worker
    assert "actions/cache/save@v4" in worker
    assert "Historical research did not complete" not in worker
    assert "concurrency:\n  group: intelligence-engine-main" in worker


def test_superseded_rotating_backfill_is_removed():
    assert not Path(".github/workflows/research-backfill.yml").exists()


def test_status_is_read_only_and_runs_after_both_research_workflows():
    workflow = _text(".github/workflows/research-status-marker.yml")

    assert "workflow_run:" in workflow
    assert "Intelligence Engine (sidecar)" in workflow
    assert "Ten-year research worker" in workflow
    assert "research-run-status.json research-readiness.json" in workflow
    assert "research-bootstrap-status.json" in workflow
    assert "backfill_status" in workflow
    assert "missing_years" in workflow
    assert "SEC_USER_AGENT_VALUE" in workflow
    assert "sec_data_ready" in workflow
    assert "WORKFLOW_RUN_CONCLUSION" not in workflow
    assert "failed_dispatches" not in workflow
    assert "git add research-run-status.json research-readiness.json" in workflow
    assert not Path(".github/workflows/research-readiness.yml").exists()


def test_status_bootstrap_and_worker_never_store_research_values():
    status = _text(".github/workflows/research-status-marker.yml")
    bootstrap = _text(".github/workflows/research-bootstrap.yml")
    worker = _text(".github/workflows/research-worker.yml")

    for forbidden in ("entry_candidates", "portfolio_doctor", "mean_excess_return", "entry_price_1"):
        assert forbidden not in status
        assert forbidden not in bootstrap
        assert forbidden not in worker
