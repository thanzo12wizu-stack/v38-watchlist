from pathlib import Path


def test_completed_research_finalizer_is_manual_read_only_and_idempotent():
    workflow = Path('.github/workflows/research-finalize.yml').read_text(encoding='utf-8')
    assert 'workflow_dispatch:' in workflow
    assert 'schedule:' not in workflow
    assert 'workflow_run:' not in workflow
    assert 'contents: read' in workflow
    assert 'contents: write' not in workflow
    assert 'research-run-status.json' in workflow
    assert 'research-readiness.json' in workflow
    assert 'backfill_status' in workflow
    assert 'ten_year_backfill_complete' in workflow
    assert 'git commit' not in workflow
    assert 'updated_at' not in workflow
