from pathlib import Path


def test_research_worker_persists_partial_price_progress_and_skips_research_during_warmup():
    workflow = Path('.github/workflows/research-worker.yml').read_text(encoding='utf-8')

    assert "if: always() && hashFiles('prices.pkl') != ''" in workflow
    assert "if: inputs.action == 'YEAR_BACKFILL'" in workflow
    assert 'research-worker-result.json' in workflow
    assert '| tee /tmp/price-warmup-report.json' in workflow
    assert 'V38_PRICE_PROVIDER' in workflow


def test_bootstrap_chains_successes_and_keeps_failed_run_ids():
    workflow = Path('.github/workflows/research-bootstrap.yml').read_text(encoding='utf-8')

    assert 'workflow_run:' in workflow
    assert '- Ten-year research worker' in workflow
    assert "last_completed_workflow_run_id" in workflow
    assert "last_failed_workflow_run_id" in workflow
    assert "consecutive_failures" in workflow
    assert "handle.write('refresh_sec=false\\n')" in workflow
    assert 'RETRY_DEFERRED_AFTER_FAILURE' in workflow


def test_status_marker_reads_aggregate_worker_result():
    workflow = Path('.github/workflows/research-status-marker.yml').read_text(encoding='utf-8')

    assert "worker_result_path = private / 'research-worker-result.json'" in workflow
    assert "worker_result.get('sec_cache_file_count')" in workflow
    assert "bootstrap.get('last_completed_workflow_run_id')" in workflow
