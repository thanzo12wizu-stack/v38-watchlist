from pathlib import Path

from kaview.run import run


def test_dashboard_is_single_html_with_real_almanac_tab_links(tmp_path: Path) -> None:
    output = tmp_path / "out"
    run(input_dir=tmp_path / "input", output_dir=output, starting_equity_jpy=7_300_000, demo=True)
    html = (output / "index.html").read_text(encoding="utf-8")

    for tab_id in ("today", "assets", "portfolio", "journal", "edge", "review", "share"):
        assert f'id="{tab_id}"' in html
        assert f'data-tab="{tab_id}"' in html
        assert f'href="#{tab_id}"' in html
        assert f'aria-controls="{tab_id}"' in html

    assert html.count('<a class="tab" href="#') == 7
    assert '<button class="tab"' not in html
    assert "window.addEventListener('hashchange'" in html
    assert 'document.documentElement.classList.add("js")' in html
    assert "html.js .tab-panel.active{display:block}" in html
    assert "html:not(.js) .tab-panel:target{display:block}" in html
    assert "html:not(.js):has(.tab-panel:target) .tab-panel.active:not(:target){display:none}" in html

    for legacy in ("assets.html", "portfolio.html", "trades.html", "edge.html", "review.html", "share.html"):
        assert not (output / legacy).exists(), legacy
        assert f'href="{legacy}"' not in html

    assert "Trade Journal Almanac" in html
    assert "--bg:#f5f2ea" in html
    assert "grid-template-columns:repeat(12,minmax(0,1fr))" in html
    assert ".tab:nth-child(n+5){grid-column:span 4}" in html
    assert "overflow-x:hidden" in html
    assert 'class="holding-card"' in html
    assert 'id="holdings-more"' in html
    assert "tickerKeys" in html
    assert "STOP逸脱" in html
    assert "window.V38_DATA=" in html
    assert 'id="j-search"' in html
    assert 'id="edge-axis"' in html
    assert 'id="assets-period"' in html
    assert 'src="data:image/png;base64,' in html
