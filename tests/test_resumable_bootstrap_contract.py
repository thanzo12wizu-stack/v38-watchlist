from pathlib import Path


def test_research_worker_persists_partial_price_progress_and_skips_research_during_warmup():
    workflow = Path('.github/workflows/research-worker.yml').read_text(encoding='utf-8')

    assert "if: always() && hashFiles('prices.pkl') != ''" in workflow
    assert "if: inputs.action == 'YEAR_BACKFILL'" in workflow
    assert 'research-worker-result.json' in workflow
    assert '/tmp/price-warmup-report.json' in workflow
    assert 'V38_PRICE_PROVIDER' in workflow


def test_research_worker_processes_bounded_price_slices_until_complete():
    workflow = Path('.github/workflows/research-worker.yml').read_text(encoding='utf-8')

    assert 'max_slices=14' in workflow
    assert 'for slice in $(seq 1 "$max_slices")' in workflow
    assert 'history_remaining' in workflow
    assert 'No long-history responses in this slice' in workflow
    assert 'timeout-minutes: 140' in workflow


def test_bootstrap_chains_successes_and_keeps_failed_run_ids():
    workflow = Path('.github/workflows/research-bootstrap.yml').read_text(encoding='utf-8')

    assert 'workflow_run:' in workflow
    assert '- Ten-year research worker' in workflow
    assert '- Intelligence Engine (sidecar)' in workflow
    assert "github.event.workflow_run.event != 'pull_request'" in workflow
    assert "last_completed_workflow_run_id" in workflow
    assert "last_failed_workflow_run_id" in workflow
    assert "consecutive_failures" in workflow
    assert "handle.write('refresh_sec=false\\n')" in workflow
    assert 'RETRY_DEFERRED_AFTER_FAILURE' in workflow


def test_bootstrap_reconciles_successful_reruns_and_exact_history_completion():
    workflow = Path('.github/workflows/research-bootstrap.yml').read_text(encoding='utf-8')

    assert 'TRIGGER_RUN_ID' in workflow
    assert "SUCCESS:RERUN_RECONCILED" in workflow
    assert "worker_result.get('workflow_run_id')" in workflow
    assert "price_history_remaining" in workflow
    assert "price_history_complete" in workflow
    assert "warmup_completed = warmup_target" in workflow


def test_status_marker_reads_aggregate_worker_result():
    workflow = Path('.github/workflows/research-status-marker.yml').read_text(encoding='utf-8')

    assert "worker_result_path = private / 'research-worker-result.json'" in workflow
    assert "worker_result.get('sec_cache_file_count')" in workflow
    assert "bootstrap.get('last_completed_workflow_run_id')" in workflow
