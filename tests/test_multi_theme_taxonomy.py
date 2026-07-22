import pandas as pd

from intelligence_engine import theme as theme_module
from intelligence_engine.theme import apply_theme_context, attach_theme_context, build_theme_intelligence


def _row(ticker, rs, accel, leader, setup):
    return {
        'ticker': ticker,
        'sector': 'Technology',
        'industry': 'Semiconductors',
        'rs_raw_63': rs,
        'rs_raw_126': rs,
        'rs_raw_189': rs,
        'rs_change_raw_63': accel,
        'rs_change_raw_126': accel,
        'score_leader': leader,
        'leader_rank_pct': leader,
        'score_entry': leader,
        'setup': setup,
    }


def test_ticker_can_belong_to_multiple_curated_themes(tmp_path, monkeypatch):
    taxonomy = tmp_path / 'themes.csv'
    taxonomy.write_text(
        'ticker,theme,theme_ja,sector_hint\n'
        'MRVL,AI Accelerators,AIアクセラレータ,Technology\n'
        'MRVL,Data Center Connectivity,データセンター接続,Technology\n'
        'NVDA,AI Accelerators,AIアクセラレータ,Technology\n'
        'ALAB,Data Center Connectivity,データセンター接続,Technology\n',
        encoding='utf-8',
    )
    monkeypatch.setenv('V38_THEME_TAXONOMY', str(taxonomy))
    theme_module._load_taxonomy.cache_clear()

    frame = pd.DataFrame(
        [
            _row('MRVL', 0.45, 0.15, 92, 'PRE_BREAKOUT'),
            _row('NVDA', 0.55, 0.20, 98, 'BREAKOUT'),
            _row('ALAB', -0.10, -0.05, 55, 'WATCH'),
        ]
    )
    themes = build_theme_intelligence(frame)
    lookup = {item['theme']: item for item in themes}

    assert lookup['AI Accelerators']['member_count'] == 2
    assert lookup['Data Center Connectivity']['member_count'] == 2
    assert 'MRVL' in lookup['AI Accelerators']['leaders']
    assert 'MRVL' in lookup['Data Center Connectivity']['leaders']

    enriched = attach_theme_context(frame, themes)
    mrvl = enriched.set_index('ticker').loc['MRVL']
    assert set(mrvl['themes']) == {'AI Accelerators', 'Data Center Connectivity'}
    assert set(mrvl['themes_ja']) == {'AIアクセラレータ', 'データセンター接続'}
    assert mrvl['theme'] == 'AI Accelerators'

    candidate = apply_theme_context([{'ticker': 'MRVL', 'warnings': []}], enriched)[0]
    assert set(candidate['themes']) == {'AI Accelerators', 'Data Center Connectivity'}
    assert candidate['theme'] == 'AI Accelerators'
    assert candidate['theme_confirmed'] is True

    theme_module._load_taxonomy.cache_clear()
