from pathlib import Path


def test_options_chart_bridge_fast_path_contract():
    text = Path('options-chart-bridge.js').read_text(encoding='utf-8')
    assert "cache: 'default'" in text
    assert 'Date.now()' not in text
    assert 'Promise.all([payloadP, broadP])' not in text
    assert 'const broadP = loadShard(ticker)' in text
    assert 'const payload = await loadPayload(false)' in text
    assert 'if (detailRec?.bars?.length)' in text


def test_options_intelligence_uses_fast_production_bridge():
    html = Path('options-intelligence.html').read_text(encoding='utf-8')
    assert 'options-chart-bridge.js?v=20260909-fast2' in html
