from pathlib import Path


def test_bootstrap_controller_no_longer_schedules_or_mutates_status():
    workflow = Path('.github/workflows/research-bootstrap.yml').read_text(encoding='utf-8')
    assert 'workflow_dispatch:' in workflow
    assert 'schedule:' not in workflow
    assert 'workflow_run:' not in workflow
    assert 'contents: write' not in workflow
    assert 'actions: write' not in workflow
    assert 'research-bootstrap-status.json' in workflow
    assert "payload.get('status') != 'COMPLETE'" in workflow
    assert 'gh workflow run research-worker.yml' not in workflow
    assert 'git commit' not in workflow
