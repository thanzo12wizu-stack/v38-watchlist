from pathlib import Path


def test_kaview_has_no_existing_workflow_or_hub_integration() -> None:
    workflows = sorted(Path(".github/workflows").glob("*.yml"))
    assert [path.name for path in workflows] == [
        "dashboard.yml",
        "intelligence-engine.yml",
        "publish-public-site.yml",
    ]

    integration_files = [*workflows, Path("index.html"), Path("scripts/export_public_site.py")]
    forbidden = ("kaview", "trade_journal", "trade-journal", "almanac")
    for path in integration_files:
        text = path.read_text(encoding="utf-8").lower()
        assert not any(token in text for token in forbidden), path


def test_obsolete_kaview_prototypes_are_absent() -> None:
    obsolete = (
        "intelligence_engine/trade_journal_render.py",
        "intelligence_engine/trade_journal_demo15.py",
        "intelligence_engine/trade_journal_html.py",
        "trade-journal-almanac.html",
    )
    assert not [path for path in obsolete if Path(path).exists()]
