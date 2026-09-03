from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _workflow(name: str) -> str:
    return (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")


def _assert_pipeline_branch_contract(text: str) -> None:
    assert "PIPELINE_BRANCH: pipeline-live" in text
    assert "refs/heads/$PIPELINE_BRANCH" in text or "origin/$PIPELINE_BRANCH" in text


def test_command_center_stages_instead_of_publishing_main():
    text = _workflow("dashboard.yml")
    _assert_pipeline_branch_contract(text)
    assert 'origin "HEAD:refs/heads/$PIPELINE_BRANCH"' in text
    assert "git push origin HEAD:main" not in text


def test_v38_reads_and_persists_only_staging_branch():
    text = _workflow("v38-live.yml")
    assert 'workflows: ["Command Center daily build"]' in text
    assert "ref: pipeline-live" in text
    _assert_pipeline_branch_contract(text)
    assert 'git push origin "HEAD:refs/heads/$PIPELINE_BRANCH"' in text
    assert "git push origin HEAD:main" not in text


def test_sleeves_read_and_persist_only_staging_branch():
    text = _workflow("v38-sleeve-refresh.yml")
    assert 'workflows: ["V38 live build"]' in text
    assert "ref: pipeline-live" in text
    _assert_pipeline_branch_contract(text)
    assert 'git push origin "HEAD:refs/heads/$PIPELINE_BRANCH"' in text
    assert "git push origin HEAD:main" not in text
    assert "Publish clean public mirror" not in text


def test_rotation_is_the_only_pipeline_stage_that_promotes_to_main():
    text = _workflow("rotation-live.yml")
    assert 'workflows: ["V38 sleeve live refresh"]' in text
    _assert_pipeline_branch_contract(text)
    assert "validate_atomic_publish.py" in text
    assert "ATOMIC_PRODUCTION_FILES" in text
    assert "git push origin HEAD:main" in text


def test_public_mirror_runs_after_rotation_and_has_atomic_gate():
    text = _workflow("publish-public-site.yml")
    assert 'workflows: ["Rotation Theme56 live build"]' in text
    assert "validate_atomic_publish.py" in text
