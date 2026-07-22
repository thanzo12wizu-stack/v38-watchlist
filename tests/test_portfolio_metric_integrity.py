import pandas as pd

from intelligence_engine.portfolio import build_portfolio_doctor


def _prices(base: float) -> pd.DataFrame:
    index = pd.date_range('2026-01-01', periods=40, freq='B')
    return pd.DataFrame({'close': [base + value for value in range(40)]}, index=index)


def test_portfolio_metrics_are_normalized_within_invested_sleeve():
    positions = pd.DataFrame(
        [
            {'ticker': 'AAA', 'weight': 0.08, 'cost_basis': 100, 'entry_date': '2026-02-01', 'entry_stage': 2},
            {'ticker': 'BBB', 'weight': 0.08, 'cost_basis': 100, 'entry_date': '2026-02-01', 'entry_stage': 2},
        ]
    )
    scored = pd.DataFrame(
        [
            {'ticker': 'AAA', 'price': 110, 'stop_ema21_low': 100, 'adr_pct': 4, 'sector': 'Tech', 'theme': 'AI'},
            {'ticker': 'BBB', 'price': 110, 'stop_ema21_low': 100, 'adr_pct': 6, 'sector': 'Tech', 'theme': 'Cloud'},
        ]
    )
    result = build_portfolio_doctor(
        positions,
        scored,
        {'AAA': _prices(100), 'BBB': _prices(120)},
        {'regime': 'YELLOW', 'entry_gate': 'NO_NEW'},
    )

    assert result['gross_exposure'] == 0.16
    assert result['portfolio_adr_pct'] == 5.0
    assert result['concentration_hhi'] == 0.5
    assert result['effective_position_count'] == 2.0
    assert result['sector_shares']['Tech'] == 1.0
    assert result['theme_shares'] == {'AI': 0.5, 'Cloud': 0.5}
    assert result['portfolio_stop_risk_pct'] == 1.6
    assert result['portfolio_stop_risk_on_invested_pct'] == 10.0
    assert 'sector_concentration' in result['warnings']
    assert 'theme_concentration' in result['warnings']


def test_missing_adr_is_excluded_instead_of_counted_as_zero():
    positions = pd.DataFrame(
        [
            {'ticker': 'AAA', 'weight': 0.08, 'cost_basis': 100, 'entry_stage': 2},
            {'ticker': 'BBB', 'weight': 0.08, 'cost_basis': 100, 'entry_stage': 2},
        ]
    )
    scored = pd.DataFrame(
        [
            {'ticker': 'AAA', 'price': 110, 'stop_ema21_low': 100, 'adr_pct': None, 'sector': 'Tech', 'theme': 'AI'},
            {'ticker': 'BBB', 'price': 110, 'stop_ema21_low': 100, 'adr_pct': 6, 'sector': 'Finance', 'theme': 'Banks'},
        ]
    )
    result = build_portfolio_doctor(
        positions,
        scored,
        {'AAA': _prices(100), 'BBB': _prices(120)},
        {'regime': 'GREEN', 'entry_gate': 'ALLOW'},
    )
    assert result['portfolio_adr_pct'] == 6.0
