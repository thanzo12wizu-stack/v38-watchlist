from pathlib import Path


def test_bootstrap_restart_hook_is_archived_and_manual_only():
    workflow = Path('.github/workflows/research-bootstrap-kick.yml').read_text(encoding='utf-8')
    assert 'workflow_dispatch:' in workflow
    assert 'push:' not in workflow
    assert 'actions: write' not in workflow
    assert 'gh workflow run research-bootstrap.yml' not in workflow
    assert 'automatic restart is disabled' in workflow
