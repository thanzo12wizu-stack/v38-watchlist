from pathlib import Path


def test_successful_or_failed_worker_completion_rechecks_serial_bootstrap():
    workflow = Path('.github/workflows/research-worker-completion.yml').read_text(encoding='utf-8')

    assert 'workflow_run:' in workflow
    assert '- Ten-year research worker' in workflow
    assert "github.event.workflow_run.event == 'workflow_dispatch'" in workflow
    assert 'head_repository.full_name' not in workflow
    assert 'actions: write' in workflow
    assert 'contents: read' in workflow
    assert 'gh workflow run research-bootstrap.yml' in workflow
    assert '--ref main' in workflow
    assert 'command-center' not in workflow.lower()
