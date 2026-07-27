from pathlib import Path

from intelligence_engine.trade_journal_run import run


def test_dashboard_is_single_html_with_all_sections(tmp_path: Path) -> None:
    output = tmp_path / "out"
    run(input_dir=tmp_path / "input", output_dir=output, starting_equity_jpy=7_300_000, demo=True)
    html = (output / "index.html").read_text(encoding="utf-8")
    for tab_id in ("today", "performance", "portfolio", "journal", "edge", "review", "share"):
        assert f'id="{tab_id}"' in html
        assert f'data-tab="{tab_id}"' in html
        assert f'href="#{tab_id}"' in html
    for legacy in ("assets.html", "portfolio.html", "trades.html", "edge.html", "review.html", "share.html"):
        assert not (output / legacy).exists(), legacy
        assert f'href="{legacy}"' not in html
    assert "Single-file, no-JS readable mode" in html
    assert 'src="data:image/png;base64,' in html
    assert 'id="trade-search"' in html
    assert 'id="trade-setup"' in html
    assert 'id="trade-nq"' in html
    assert 'id="trade-result"' in html
