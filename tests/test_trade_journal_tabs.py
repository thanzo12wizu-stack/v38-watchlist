from pathlib import Path

from intelligence_engine.trade_journal_multipage import PAGE_FILES
from intelligence_engine.trade_journal_run import run


def test_dashboard_has_task_based_pages_and_controls(tmp_path: Path) -> None:
    output = tmp_path / "out"
    run(input_dir=tmp_path / "input", output_dir=output, starting_equity_jpy=7_300_000, demo=True)

    for tab_id, filename in PAGE_FILES.items():
        page = output / filename
        assert page.exists(), filename
        html = page.read_text(encoding="utf-8")
        assert f'id="{tab_id}"' in html
        assert f'href="{filename}"' in html
        assert f'id="{tab_id}" role="tabpanel"' in html
        assert f'class="tab-panel active" id="{tab_id}"' in html
        assert 'history.replaceState' not in html

    journal = (output / PAGE_FILES["journal"]).read_text(encoding="utf-8")
    assert 'id="trade-search"' in journal
    assert 'id="trade-setup"' in journal
    assert 'id="trade-nq"' in journal
    assert 'id="trade-result"' in journal

    share = (output / PAGE_FILES["share"]).read_text(encoding="utf-8")
    assert 'src="daily_card.png"' in share
    assert 'src="portfolio_card.png"' in share


def test_every_page_links_to_all_sections(tmp_path: Path) -> None:
    output = tmp_path / "out"
    run(input_dir=tmp_path / "input", output_dir=output, starting_equity_jpy=7_300_000, demo=True)
    for filename in PAGE_FILES.values():
        html = (output / filename).read_text(encoding="utf-8")
        for target in PAGE_FILES.values():
            assert f'href="{target}"' in html
