from pathlib import Path


def test_worker_completion_hook_is_archived_and_manual_only():
    workflow = Path('.github/workflows/research-worker-completion.yml').read_text(encoding='utf-8')
    assert 'workflow_dispatch:' in workflow
    assert 'workflow_run:' not in workflow
    assert 'schedule:' not in workflow
    assert 'actions: write' not in workflow
    assert 'gh workflow run research-bootstrap.yml' not in workflow
    assert 'automatic chaining is disabled' in workflow
