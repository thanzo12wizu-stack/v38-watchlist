from pathlib import Path


def test_only_operational_workflows_remain():
    files = sorted(path.name for path in Path('.github/workflows').glob('*.y*ml'))
    assert files == [
        'dashboard.yml',
        'options.yml',
        'publish-public-site.yml',
    ]


def test_workflows_do_not_use_deprecated_node20_actions():
    workflows = '\n'.join(
        path.read_text(encoding='utf-8')
        for path in Path('.github/workflows').glob('*.y*ml')
    )
    for legacy_ref in (
        'actions/upload-artifact@v4',
        'actions/cache@v4',
        'actions/cache/restore@v4',
        'actions/cache/save@v4',
    ):
        assert legacy_ref not in workflows
