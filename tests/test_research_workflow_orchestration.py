from pathlib import Path


def _text(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_bootstrap_dispatches_one_bounded_slice_per_controller_run():
    workflow = _text(".github/workflows/research-bootstrap.yml")

    assert 'cron: "12 * * * *"' in workflow
    assert "gh run list" in workflow
    assert "active > 0" in workflow
    assert workflow.count("gh workflow run intelligence-engine.yml") == 1
    assert "for year in" not in workflow
    assert "for run in" not in workflow
    assert "research-bootstrap-status.json" in workflow
    assert "PRICE_WARMUP" in workflow
    assert "YEAR_BACKFILL" in workflow


def test_status_is_published_from_workflow_completion_not_bot_push_chain():
    workflow = _text(".github/workflows/research-status-marker.yml")

    assert "workflow_run:" in workflow
    assert "Intelligence Engine (sidecar)" in workflow
    assert "research-run-status.json research-readiness.json" in workflow
    assert "backfill_status" in workflow
    assert "missing_years" in workflow
    assert "SEC_USER_AGENT_VALUE" in workflow
    assert not Path(".github/workflows/research-readiness.yml").exists()


def test_status_and_bootstrap_files_never_store_research_values():
    status = _text(".github/workflows/research-status-marker.yml")
    bootstrap = _text(".github/workflows/research-bootstrap.yml")

    for forbidden in ('entry_candidates', 'portfolio_doctor', 'mean_excess_return', 'entry_price_1'):
        assert forbidden not in status
        assert forbidden not in bootstrap
