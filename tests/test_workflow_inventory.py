from pathlib import Path


def test_only_operational_workflows_remain():
    files = sorted(path.name for path in Path('.github/workflows').glob('*.y*ml'))
    assert files == [
        'dashboard.yml',
        'intelligence-engine.yml',
        'publish-public-site.yml',
        'trade-journal-almanac-sidecar.yml',
        'trade-journal-analytics.yml',
        'trade-journal-private.yml',
    ]
