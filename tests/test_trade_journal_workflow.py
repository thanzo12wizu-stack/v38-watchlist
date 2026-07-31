from pathlib import Path


def test_operational_workflows_are_preserved() -> None:
    workflows = {path.name for path in Path(".github/workflows").glob("*.yml")}
    assert workflows == {
        "dashboard.yml",
        "intelligence-engine.yml",
        "publish-public-site.yml",
    }


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
