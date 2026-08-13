from pathlib import Path


def test_workflow_prioritizes_active_candidates_before_backfill():
    text = Path('.github/workflows/intelligence-engine.yml').read_text(encoding='utf-8')
    priority = text.index('Refresh candidate external data first')
    backfill = text.index('Backfill external data incrementally')
    operational = text.index('Build operational intelligence and settle observations')
    assert priority < backfill < operational
    assert "payload.get('entry_candidates')" in text
    assert '--universe /tmp/external-priority.csv' in text
    assert '--max-tickers 50' in text
    assert '--max-tickers 20' in text


def test_workflow_keeps_privacy_gate_strict():
    text = Path('.github/workflows/intelligence-engine.yml').read_text(encoding='utf-8')
    assert "grep -q 'ciphertext' intelligence-dashboard.html" in text
    assert 'rm -rf -- data/intelligence data/external portfolio.csv' in text
    assert 'plaintext private intelligence files remain' in text
