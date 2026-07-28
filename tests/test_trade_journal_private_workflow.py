from pathlib import Path


def test_private_trade_journal_workflow_is_secure_and_automatic() -> None:
    text = Path('.github/workflows/trade-journal-private.yml').read_text(encoding='utf-8')
    assert 'workflow_run:' in text
    assert 'Intelligence Engine (sidecar)' in text
    assert 'trade_journal_sync' in text
    assert 'trade-journal-dashboard.html' in text
    assert 'private/trade-journal-state.enc.json' in text
    assert 'lock-html' in text
    assert 'Remove plaintext private data' in text
    assert 'rm -rf data/intelligence data/external data/trade_journal portfolio.csv' in text
    assert 'git add trade-journal-dashboard.html private/trade-journal-state.enc.json' in text
    assert 'artifacts/upload' not in text
