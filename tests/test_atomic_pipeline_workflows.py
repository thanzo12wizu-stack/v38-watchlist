import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

COMMAND_CENTER_OWNED = {
    "command-center.html",
    "command-center_share.html",
    "state.json",
    "trend_history.json",
    "daily_log.csv",
    "mktcap.json",
    "fred_cache.json",
    "fmp_reference_cache.json",
    "earnings.json",
    "inception_vwap.json",
    "industry_map.json",
    "universe.csv",
    "options_targets.json",
    "commit_manifest.json",
}


def _workflow(name: str) -> str:
    return (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")


def _env_file_list(text: str, key: str) -> set[str]:
    match = re.search(rf"^\s+{re.escape(key)}:\s*>-\n((?:\s{{8}}\S.*\n?)+)", text, re.MULTILINE)
    assert match, f"missing workflow file list: {key}"
    return {line.strip() for line in match.group(1).splitlines() if line.strip()}


def test_production_schedule_and_downstream_orchestrator_are_restored():
    dashboard = _workflow("dashboard.yml")
    assert "workflow_dispatch:" in dashboard
    assert "- cron: '17 22 * * 1-5'" in dashboard
    assert "- cron: '17 4 * * 2-6'" in dashboard
    assert "workflow_run:" not in dashboard

    for name in (
        "v38-live.yml",
        "v38-sleeve-refresh.yml",
        "rotation-live.yml",
        "publish-public-site.yml",
    ):
        text = _workflow(name)
        assert "workflow_dispatch:" in text
        assert "workflow_run:" not in text
        assert "schedule:" not in text

    chain = _workflow("production-downstream-chain.yml")
    assert 'workflows: ["Command Center daily build"]' in chain
    assert "types: [completed]" in chain
    assert "branches: [main]" in chain
    assert "github.event.workflow_run.conclusion == 'success'" in chain
    assert _env_file_list(chain, "DASHBOARD_OWNED") == COMMAND_CENTER_OWNED
    assert chain.index('run_stage v38-live.yml "V38/TQQQ/CURRENT30"') < chain.index(
        'run_stage v38-sleeve-refresh.yml "Sleeve/RSI Reset"'
    )
    assert chain.index('run_stage v38-sleeve-refresh.yml "Sleeve/RSI Reset"') < chain.index(
        'run_stage rotation-live.yml "Rotation"'
    )
    assert chain.index('run_stage rotation-live.yml "Rotation"') < chain.index(
        'run_stage publish-public-site.yml "Public mirror"'
    )
    assert "DOWNSTREAM_REVERSE_WRITE_CHECK_PASS" in chain
    assert "validate_atomic_publish.py" in chain

    options = _workflow("options.yml")
    assert "gh workflow run dashboard.yml" not in options


def test_command_center_is_standalone_and_has_complete_ownership_allowlist():
    text = _workflow("dashboard.yml")
    assert "name: Command Center daily build" in text
    assert _env_file_list(text, "DASHBOARD_ARTIFACTS") == COMMAND_CENTER_OWNED
    assert "git push origin HEAD:main" in text
    assert "PIPELINE_BRANCH" not in text
    assert "LAST_KNOWN_GOOD" not in text
    assert "Dashboard could not reach latest completed QQQ session" not in text
    assert "Candidate $candidate_date is older than current main" in text
    assert "Report Command Center status" in text
    assert "Comparison baseline" in text


def test_v38_reads_command_center_from_main_and_writes_only_v38_staging_files():
    text = _workflow("v38-live.yml")
    expected = {
        "v38-live-state.json",
        "v38-strict-loo-history.json",
        "v38-strict-loo-live.json",
        "tqqq-panic-state.json",
        "v38-tqqq-live-source-cache.json",
    }
    assert _env_file_list(text, "V38_LIVE_ARTIFACTS") == expected
    assert "ref: main" in text
    assert "git reset --hard origin/main" in text
    assert 'git show "origin/$PIPELINE_BRANCH:$file"' in text
    assert "--force-with-lease=" in text
    assert 'origin "HEAD:refs/heads/$PIPELINE_BRANCH"' in text
    assert "git push origin HEAD:main" not in text
    assert not (expected & COMMAND_CENTER_OWNED)


def test_sleeves_read_and_persist_only_downstream_staging_files():
    text = _workflow("v38-sleeve-refresh.yml")
    assert "ref: main" in text
    assert "git reset --hard \"origin/$PIPELINE_BRANCH\"" in text
    assert "git add v38-sleeve-state.json tqqq-panic-state.json v38-live-state.json" in text
    assert 'git push origin "HEAD:refs/heads/$PIPELINE_BRANCH"' in text
    assert "git push origin HEAD:main" not in text


def test_rotation_promotion_excludes_every_command_center_owned_file():
    text = _workflow("rotation-live.yml")
    promoted = _env_file_list(text, "ATOMIC_PRODUCTION_FILES")
    protected = _env_file_list(text, "COMMAND_CENTER_OWNED_FILES")
    assert protected == COMMAND_CENTER_OWNED
    assert not (promoted & COMMAND_CENTER_OWNED)
    assert 'git show "origin/main:state.json"' in text
    assert "git diff --quiet origin/main -- $COMMAND_CENTER_OWNED_FILES" in text
    assert "Rotation staged files outside its ownership" in text
    assert "validate_atomic_publish.py" in text
    assert "git push origin HEAD:main" in text


def test_public_mirror_is_read_only_against_source_repository():
    text = _workflow("publish-public-site.yml")
    assert "permissions:\n  contents: read" in text
    assert "ref: main" in text
    assert "validate_atomic_publish.py" in text
    assert "privacy_audit.py" in text
    assert 'cd "$target"' in text
