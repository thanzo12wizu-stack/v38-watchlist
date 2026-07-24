from pathlib import Path


def test_research_code_changes_resume_the_serial_bootstrap_controller():
    workflow = Path('.github/workflows/research-bootstrap-kick.yml').read_text(encoding='utf-8')

    for path in (
        '.github/workflows/research-worker-completion.yml',
        'intelligence_engine/sec_bulk.py',
        'intelligence_engine/ensure_prices.py',
        'intelligence_engine/research_*.py',
        'intelligence_engine/research_pipeline/**',
        'private/research-worker-result.json',
        'universe.csv',
    ):
        assert f'- "{path}"' in workflow

    assert 'research-bootstrap-status.json' not in workflow
    assert 'research-run-status.json' not in workflow
    assert 'workflow_dispatch:' in workflow
    assert 'actions: write' in workflow
    assert 'for attempt in 1 2' in workflow
    assert 'sleep 30' in workflow
    assert workflow.count('gh workflow run research-bootstrap.yml') == 1
    assert '--ref main' in workflow
    assert 'cancel-in-progress: true' in workflow
