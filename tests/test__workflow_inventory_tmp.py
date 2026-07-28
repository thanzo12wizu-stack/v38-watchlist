from pathlib import Path


def test_workflow_inventory_for_cleanup():
    files = sorted(path.name for path in Path('.github/workflows').glob('*.y*ml'))
    raise AssertionError('WORKFLOW_INVENTORY=' + ','.join(files))
