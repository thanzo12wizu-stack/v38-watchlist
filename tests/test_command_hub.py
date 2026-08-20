from pathlib import Path


def test_command_hub_links_all_operational_surfaces():
    html = Path("index.html").read_text(encoding="utf-8")

    assert 'href="command-center.html"' in html
    assert 'href="swinote/"' in html
    assert 'href="intelligence-dashboard.html"' not in html
    assert 'href="research-dashboard.html"' not in html
    assert "日々の運用を開く" in html
    assert "運用ノートを開く" in html
