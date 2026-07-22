import pandas as pd

from intelligence_engine import theme as theme_module
from intelligence_engine.theme import attach_theme_context


def test_primary_theme_prefers_scored_theme_over_unranked_membership(tmp_path, monkeypatch):
    taxonomy = tmp_path / 'themes.csv'
    taxonomy.write_text(
        'ticker,theme,theme_ja,sector_hint\n'
        'AAA,Unranked Theme,未算出テーマ,Technology\n'
        'AAA,Leading Theme,主力テーマ,Technology\n',
        encoding='utf-8',
    )
    monkeypatch.setenv('V38_THEME_TAXONOMY', str(taxonomy))
    theme_module._load_taxonomy.cache_clear()

    frame = pd.DataFrame([{'ticker': 'AAA', 'sector': 'Technology', 'industry': 'Software'}])
    themes = [
        {
            'theme': 'Leading Theme',
            'theme_ja': '主力テーマ',
            'score_theme': 0.82,
            'phase': 'LEADING',
        }
    ]
    enriched = attach_theme_context(frame, themes).iloc[0]

    assert enriched['theme'] == 'Leading Theme'
    assert enriched['theme_ja'] == '主力テーマ'
    assert enriched['score_theme'] == 0.82
    assert enriched['themes'] == ['Leading Theme', 'Unranked Theme']

    theme_module._load_taxonomy.cache_clear()
