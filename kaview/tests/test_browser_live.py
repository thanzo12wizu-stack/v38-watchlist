from pathlib import Path

from kaview.live import render_live_dashboard


def test_browser_live_page_has_no_synthetic_financial_snapshot(tmp_path: Path) -> None:
    output = tmp_path / "index.html"
    render_live_dashboard(output)
    html = output.read_text(encoding="utf-8")

    assert "画面確認用デモ" not in html
    assert "2026-07-24" not in html
    assert "12,582,240" not in html
    assert "SNDK MU NVDA" not in html
    assert "window.V38_DATA=" not in html
    assert 'id="account-equity">—</strong>' in html
    assert 'id="registered-value">—</strong>' in html
    assert 'src="live.js"' in html


def test_browser_live_page_reads_command_center_without_modifying_it(tmp_path: Path) -> None:
    output = tmp_path / "index.html"
    render_live_dashboard(output)
    html = output.read_text(encoding="utf-8")
    script = Path("kaview/live.js").read_text(encoding="utf-8")

    assert html.count('<a class="tab" href="#') == 7
    assert 'href="../command-center.html"' in html
    assert 'fetchText("../command-center.html")' in script
    assert 'fetchText("../equity.csv")' in script
    assert 'readJsonStorage("v38_holdings", [])' in script
    assert 'localStorage.getItem("eqLast")' in script
    assert "localStorage.setItem" not in script
    assert "XMLHttpRequest" not in script


def test_published_kaview_matches_live_renderer(tmp_path: Path) -> None:
    output = tmp_path / "index.html"
    render_live_dashboard(output)
    assert output.read_bytes() == Path("kaview/index.html").read_bytes()
