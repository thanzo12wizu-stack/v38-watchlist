from pathlib import Path


def test_research_code_changes_resume_the_serial_bootstrap_controller():
    workflow = Path('.github/workflows/research-bootstrap-kick.yml').read_text(encoding='utf-8')

    for path in (
        'intelligence_engine/sec_bulk.py',
        'intelligence_engine/ensure_prices.py',
        'intelligence_engine/research_*.py',
        'intelligence_engine/research_pipeline/**',
        'universe.csv',
    ):
        assert f'- "{path}"' in workflow

    assert 'workflow_dispatch:' in workflow
    assert 'actions: write' in workflow
    assert 'gh workflow run research-bootstrap.yml' in workflow
    assert '--ref main' in workflow
    assert 'cancel-in-progress: true' in workflow
