import pandas as pd

from intelligence_engine.story import add_story_intelligence


def test_single_dilution_metric_is_data_insufficient_not_diluting():
    frame = pd.DataFrame(
        [
            {
                'ticker': 'AAA',
                'shares_yoy': 0.20,
            }
        ]
    )
    result = add_story_intelligence(frame).iloc[0]
    assert result['story_evidence_count'] == 1
    assert result['story_phase'] == 'DATA_INSUFFICIENT'


def test_dilution_label_requires_minimum_evidence_and_confidence():
    frame = pd.DataFrame(
        [
            {
                'ticker': 'AAA',
                'shares_yoy': 0.20,
                'eps_yoy': 0.25,
                'revenue_yoy': 0.18,
            },
            {
                'ticker': 'BBB',
                'shares_yoy': 0.01,
                'eps_yoy': 0.05,
                'revenue_yoy': 0.04,
            },
        ]
    )
    result = add_story_intelligence(frame).set_index('ticker')
    assert result.loc['AAA', 'story_evidence_count'] == 3
    assert result.loc['AAA', 'story_phase'] == 'DILUTING'
