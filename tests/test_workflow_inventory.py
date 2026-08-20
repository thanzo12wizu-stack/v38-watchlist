from pathlib import Path


def test_only_operational_workflows_remain():
    files = sorted(path.name for path in Path('.github/workflows').glob('*.y*ml'))
    assert files == [
        'dashboard.yml',
        'intelligence-engine.yml',
        'options.yml',
        'publish-public-site.yml',
    ]


def test_optional_historical_research_timeout_does_not_block_core_publish():
    workflow = Path('.github/workflows/intelligence-engine.yml').read_text(encoding='utf-8')
    start = workflow.index('- name: Build five-year point-in-time research')
    end = workflow.index('- name: Validate generated contract', start)
    research_step = workflow[start:end]
    assert 'continue-on-error: true' in research_step
    assert 'timeout-minutes: 45' in research_step
