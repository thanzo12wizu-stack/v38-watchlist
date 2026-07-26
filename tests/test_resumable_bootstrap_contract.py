from pathlib import Path


def test_research_worker_persists_partial_price_progress_and_skips_research_during_warmup():
    workflow = Path('.github/workflows/research-worker.yml').read_text(encoding='utf-8')

    assert "if: always() && hashFiles('prices.pkl') != ''" in workflow
    assert "if: inputs.action == 'YEAR_BACKFILL'" in workflow
    assert 'research-worker-result.json' in workflow
    assert '/tmp/price-warmup-report.json' in workflow
    assert 'V38_PRICE_PROVIDER' in workflow


def test_privacy_safe_worker_result_is_versionable():
    ignore = Path('.gitignore').read_text(encoding='utf-8')

    assert '!/private/research-worker-result.json' in ignore


def test_research_worker_processes_bounded_price_slices_until_complete():
    workflow = Path('.github/workflows/research-worker.yml').read_text(encoding='utf-8')

    assert 'max_slices=14' in workflow
    assert 'for slice in $(seq 1 "$max_slices")' in workflow
    assert 'history_remaining' in workflow
    assert 'No long-history responses in this slice' in workflow
    assert 'timeout-minutes: 140' in workflow


def test_completed_bootstrap_no_longer_chains_workers_or_rewrites_progress():
    workflow = Path('.github/workflows/research-bootstrap.yml').read_text(encoding='utf-8')

    assert 'workflow_dispatch:' in workflow
    assert 'workflow_run:' not in workflow
    assert 'schedule:' not in workflow
    assert 'gh workflow run research-worker.yml' not in workflow
    assert 'git commit' not in workflow
    assert 'contents: write' not in workflow
    assert 'actions: write' not in workflow


def test_archived_bootstrap_confirms_exact_completion_state():
    workflow = Path('.github/workflows/research-bootstrap.yml').read_text(encoding='utf-8')

    assert 'research-bootstrap-status.json' in workflow
    assert "payload.get('status') != 'COMPLETE'" in workflow
    assert "payload.get('missing_years')" in workflow
    assert 'No worker will be dispatched' in workflow


def test_status_marker_reads_aggregate_worker_result():
    workflow = Path('.github/workflows/research-status-marker.yml').read_text(encoding='utf-8')

    assert "worker_result_path = private / 'research-worker-result.json'" in workflow
    assert "worker_result.get('sec_cache_file_count')" in workflow
    assert "bootstrap.get('last_completed_workflow_run_id')" in workflow
