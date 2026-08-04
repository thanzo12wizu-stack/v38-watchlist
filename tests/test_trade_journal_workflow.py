from pathlib import Path


def test_operational_workflows_are_preserved() -> None:
    workflows = {path.name for path in Path(".github/workflows").glob("*.yml")}
    assert workflows == {
        "dashboard.yml",
        "intelligence-engine.yml",
        "publish-public-site.yml",
    }


def test_dashboard_push_cannot_publish_feature_branch_builds_to_main() -> None:
    workflow = Path(".github/workflows/dashboard.yml").read_text(encoding="utf-8")
    trigger_block = workflow.split("permissions:", 1)[0]

    assert "push:\n    branches:\n      - main" in trigger_block


def test_encrypted_state_changes_trigger_intelligence_rebuild() -> None:
    workflow = Path(".github/workflows/intelligence-engine.yml").read_text(encoding="utf-8")
    trigger_block = workflow.split("permissions:", 1)[0]
    push_block = trigger_block.split("  push:", 1)[1].split("  workflow_dispatch:", 1)[0]

    assert '"private/intelligence-state.enc.json"' in push_block
    assert '"private/trade-journal-state.enc.json"' in push_block
    assert '"private/research-*.enc.json"' in push_block


def test_intelligence_workflow_supports_explicit_maintenance_skip() -> None:
    workflow = Path(".github/workflows/intelligence-engine.yml").read_text(encoding="utf-8")

    assert "!contains(github.event.head_commit.message, '[skip intelligence]')" in workflow


def test_five_year_research_timeout_allows_incremental_run_to_finish() -> None:
    workflow = Path(".github/workflows/intelligence-engine.yml").read_text(encoding="utf-8")
    step = workflow.split("- name: Build five-year point-in-time research", 1)[1]

    assert step.lstrip().startswith("timeout-minutes: 90")


def test_trade_journal_runs_inside_existing_intelligence_workflow() -> None:
    workflow = Path(".github/workflows/intelligence-engine.yml").read_text(encoding="utf-8")

    required = (
        "private/trade-journal-state.enc.json",
        "V38_ACCOUNT_EQUITY_JPY",
        "V38_EXECUTIONS_CSV_B64",
        "V38_EQUITY_HISTORY_CSV_B64",
        "V38_HOLDINGS_CSV_B64",
        "V38_CASH_FLOWS_CSV_B64",
        "intelligence_engine.trade_journal_ingest",
        "intelligence_engine.trade_journal_sync",
        "intelligence_engine.trade_journal_almanac_run",
        "--require-live-data",
        "trade-journal-almanac.html",
        "data/trade_journal",
    )
    for token in required:
        assert token in workflow


def test_public_mirror_tracks_locked_trade_journal_entrypoint() -> None:
    workflow = Path(".github/workflows/publish-public-site.yml").read_text(encoding="utf-8")
    hub = Path("index.html").read_text(encoding="utf-8")

    assert '"trade-journal-almanac.html"' in workflow
    assert 'href="trade-journal-almanac.html"' in hub


def test_intelligence_build_calls_existing_publication_workflow() -> None:
    intelligence = Path(".github/workflows/intelligence-engine.yml").read_text(encoding="utf-8")
    publication = Path(".github/workflows/publish-public-site.yml").read_text(encoding="utf-8")

    assert "  workflow_call: {}" in publication
    assert "  publish-public-site:" in intelligence
    assert "    needs: build" in intelligence
    assert "    uses: ./.github/workflows/publish-public-site.yml" in intelligence
    assert "    secrets: inherit" in intelligence


def test_publication_manifest_uses_checked_out_main_commit() -> None:
    workflow = Path(".github/workflows/publish-public-site.yml").read_text(encoding="utf-8")

    assert 'source_commit="$(git rev-parse HEAD)"' in workflow
    assert '--source-commit "$source_commit"' in workflow
