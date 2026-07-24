from pathlib import Path


def test_completed_bootstrap_finalizes_authoritative_status_without_command_center_changes():
    workflow = Path('.github/workflows/research-finalize.yml').read_text(encoding='utf-8')

    assert 'Bootstrap complete ten-year research' in workflow
    assert 'research-bootstrap-status.json' in workflow
    assert 'research-run-status.json' in workflow
    assert 'research-readiness.json' in workflow
    assert 'private/research-worker-result.json' in workflow
    assert 'private/research-success.json' in workflow
    assert "bootstrap.get('status') != 'COMPLETE'" in workflow
    assert "'backfill_status': 'COMPLETE'" in workflow
    assert "'bootstrap_status': 'COMPLETE'" in workflow
    assert "'ten_year_backfill_complete': True" in workflow
    assert "'missing_years': []" in workflow
    assert "'blockers': []" in workflow
    assert 'price_history_complete' in workflow
    assert 'model_audit_status' in workflow
    assert 'consecutive_failures' in workflow
    assert 'command center' not in workflow.lower()
    assert 'build_dashboard' not in workflow
