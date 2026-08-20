from pathlib import Path


def test_only_operational_workflows_remain():
    files = sorted(path.name for path in Path('.github/workflows').glob('*.y*ml'))
    assert files == [
        'dashboard.yml',
        'intelligence-engine.yml',
        'options.yml',
        'publish-public-site.yml',
    ]
