from pathlib import Path

from kaview.live import render_legacy_redirect, render_live_dashboard


def test_browser_live_page_has_no_synthetic_financial_snapshot(tmp_path: Path) -> None:
    output = tmp_path / "index.html"
    render_live_dashboard(output)
    html = output.read_text(encoding="utf-8")

    assert "画面確認用デモ" not in html
    assert "2026-07-24" not in html
    assert "12,582,240" not in html
    assert "SNDK MU NVDA" not in html
    for forbidden in (
        "V38",
        "Almanac",
        "Kaview",
        "Command Center",
        "command-center.html",
        "equity.csv",
        "eqLast",
        "localStorage",
        "データ品質",
        "データ範囲",
        "固定値",
        "外部送信",
    ):
        assert forbidden not in html
    assert "<title>Swinote</title>" in html
    assert "<small>SWINOTE</small>Trade Journal" in html
    assert 'id="account-equity">—</strong>' in html
    assert 'id="registered-value">—</strong>' in html
    assert 'src="live.js"' in html


def test_browser_live_page_reads_command_center_without_modifying_it(tmp_path: Path) -> None:
    output = tmp_path / "index.html"
    render_live_dashboard(output)
    html = output.read_text(encoding="utf-8")
    script = Path("swinote/live.js").read_text(encoding="utf-8")

    assert html.count('<a class="tab" href="#') == 7
    assert 'href="../command-center.html"' not in html
    assert 'fetchText("../command-center.html")' in script
    assert 'fetchText("../equity.csv")' in script
    assert 'readJsonStorage("v38_holdings", [])' in script
    assert 'localStorage.getItem("eqLast")' in script
    assert "Command Center" not in script
    assert "V38" not in script
    assert "Almanac" not in script
    assert "localStorage.setItem" not in script
    assert "XMLHttpRequest" not in script


def test_published_swinote_matches_live_renderer(tmp_path: Path) -> None:
    output = tmp_path / "index.html"
    render_live_dashboard(output)
    assert output.read_bytes() == Path("swinote/index.html").read_bytes()


def test_legacy_path_is_a_brand_free_redirect(tmp_path: Path) -> None:
    output = tmp_path / "index.html"
    render_legacy_redirect(output)
    html = output.read_text(encoding="utf-8")

    assert "../swinote/" in html
    for forbidden in ("V38", "Almanac", "Kaview", "Command Center"):
        assert forbidden not in html
