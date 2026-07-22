from intelligence_engine.display_labels import (
    external_for_display,
    portfolio_for_display,
    quality_for_display,
)


def test_portfolio_display_preserves_codes_and_localizes_text():
    raw = {
        'positions': [
            {
                'ticker': 'AAA',
                'action': 'REDUCE',
                'reasons': ['stop_near', 'take_25pct_partial'],
            }
        ],
        'warnings': ['sector_concentration'],
    }
    display = portfolio_for_display(raw)
    position = display['positions'][0]
    assert position['action_code'] == 'REDUCE'
    assert position['action'] == '縮小'
    assert position['reason_codes'] == ['stop_near', 'take_25pct_partial']
    assert position['reasons'] == ['現在値が撤退水準に接近している', '+25%到達。部分利確を検討']
    assert display['warning_codes'] == ['sector_concentration']
    assert display['warnings'] == ['セクター集中が大きい']
    assert raw['positions'][0]['action'] == 'REDUCE'


def test_external_and_quality_display_keep_machine_codes():
    external = external_for_display([{'ticker': 'AAA', 'warnings': ['earnings_window']}])[0]
    assert external['warning_codes'] == ['earnings_window']
    assert external['warnings'] == ['決算前後3日以内']

    quality = quality_for_display({'status': 'WARN', 'warnings': ['price_coverage_low', 'external_stale:news.csv']})
    assert quality['warning_codes'] == ['price_coverage_low', 'external_stale:news.csv']
    assert quality['warnings'] == ['価格データの銘柄カバレッジが低い', '外部データが古い：news.csv']
