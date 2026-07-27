from pathlib import Path

from intelligence_engine.trade_journal_run import run


def test_dashboard_has_task_based_tabs_and_controls(tmp_path: Path) -> None:
    output = tmp_path / "out"
    run(input_dir=tmp_path / "input", output_dir=output, starting_equity_jpy=7_300_000, demo=True)
    html = (output / "index.html").read_text(encoding="utf-8")
    for tab_id in ("today", "performance", "portfolio", "journal", "edge", "review", "share"):
        assert f'id="{tab_id}"' in html
        assert f'data-tab="{tab_id}"' in html
    assert 'id="trade-search"' in html
    assert 'id="trade-setup"' in html
    assert 'id="trade-nq"' in html
    assert 'id="trade-result"' in html
    assert 'src="daily_card.png"' in html
    assert 'src="portfolio_card.png"' in html
    assert "history.replaceState" in html
