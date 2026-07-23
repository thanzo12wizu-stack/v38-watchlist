from pathlib import Path

import pandas as pd

from intelligence_engine.research_postprocess import select_learning_events


def test_learning_events_keep_daily_display_but_dedupe_training_samples():
    sessions = list(pd.bdate_range("2026-01-02", periods=20))
    signals = pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "date": sessions[index],
                "candidate_archetype": "EMERGING_LEADER",
                "setup": "PRE_BREAKOUT",
                "score": 80 + index,
            }
            for index in range(10)
        ]
    )

    selected = select_learning_events(signals, sessions, cooldown_sessions=5)

    assert list(selected["date"]) == [sessions[0], sessions[5]]
    assert len(signals) == 10
    assert len(selected) == 2


def test_learning_events_are_independent_by_ticker_and_setup():
    sessions = list(pd.bdate_range("2026-01-02", periods=10))
    signals = pd.DataFrame(
        [
            {"ticker": "AAA", "date": sessions[0], "candidate_archetype": "EMERGING_LEADER", "setup": "PRE_BREAKOUT"},
            {"ticker": "AAA", "date": sessions[1], "candidate_archetype": "EMERGING_LEADER", "setup": "BREAKOUT"},
            {"ticker": "BBB", "date": sessions[1], "candidate_archetype": "EMERGING_LEADER", "setup": "PRE_BREAKOUT"},
            {"ticker": "AAA", "date": sessions[2], "candidate_archetype": "EMERGING_LEADER", "setup": "PRE_BREAKOUT"},
        ]
    )

    selected = select_learning_events(signals, sessions, cooldown_sessions=5)

    assert len(selected) == 3
    keys = set(zip(selected["ticker"], selected["setup"]))
    assert keys == {("AAA", "PRE_BREAKOUT"), ("AAA", "BREAKOUT"), ("BBB", "PRE_BREAKOUT")}


def test_learning_events_ignore_non_session_dates():
    sessions = list(pd.bdate_range("2026-01-02", periods=5))
    signals = pd.DataFrame(
        [
            {"ticker": "AAA", "date": "2026-01-03", "candidate_archetype": "EMERGING_LEADER", "setup": "PRE_BREAKOUT"},
            {"ticker": "AAA", "date": sessions[0], "candidate_archetype": "EMERGING_LEADER", "setup": "PRE_BREAKOUT"},
        ]
    )

    selected = select_learning_events(signals, sessions)

    assert len(selected) == 1
    assert pd.Timestamp(selected.iloc[0]["date"]).normalize() == sessions[0]
