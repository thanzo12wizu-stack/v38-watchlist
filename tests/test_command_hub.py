from pathlib import Path


def test_command_hub_links_all_operational_surfaces():
    html = Path("index.html").read_text(encoding="utf-8")

    assert 'href="command-center.html"' in html
    assert 'href="intelligence-dashboard.html"' in html
    assert 'href="research-dashboard.html"' in html
    assert "毎日・候補確認" in html
    assert "週末・検証用" in html
