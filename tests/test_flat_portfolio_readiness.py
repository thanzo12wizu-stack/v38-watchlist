from pathlib import Path


def test_flat_portfolio_is_a_valid_operational_state():
    workflow = Path('.github/workflows/research-status-marker.yml').read_text(encoding='utf-8')

    assert "portfolio_mode = 'POSITIONS' if portfolio_secret_configured else 'FLAT'" in workflow
    assert "'portfolio_configured': True" in workflow
    assert "'portfolio_secret_configured': portfolio_secret_configured" in workflow
    assert "'full_operational_ready': passed and not missing_years and sec_data_ready" in workflow
    assert 'portfolio_not_configured' not in workflow
