import math

import numpy as np
import pandas as pd

from build_v38_strict_loo_live import (
    build_live,
    compute_session_snapshot,
    extract_s2t,
    replacement_percentile,
)


def test_extract_s2t_uses_multiple_memberships_only():
    snapshot = {
        "s2t": {
            "AAA": ["Theme One", "Theme Two"],
            "BBB": {"themes": ["Theme One"]},
        },
        "s2i": {"AAA": "DISPLAY INDUSTRY"},
    }
    assert extract_s2t(snapshot)["AAA"] == ["Theme One", "Theme Two"]


def test_replacement_percentile_matches_replace_then_rank_semantics():
    ref = {"A": 1.0, "B": 2.0, "C": 3.0}
    # Replace B=2 with 4 => rank 3/3 = 100.
    assert math.isclose(replacement_percentile(4.0, ref, "B"), 100.0)
    # Replace B=2 with 0 => rank 1/3.
    assert math.isclose(replacement_percentile(0.0, ref, "B"), 100.0 / 3.0)


def test_session_snapshot_excludes_candidate_from_return_and_breadth():
    idx = pd.bdate_range("2026-04-01", periods=80)
    # AAA has a very different path. The peer Theme value for AAA must therefore
    # be determined only by BBB/CCC, not by AAA's own return or EMA status.
    close = pd.DataFrame(
        {
            "AAA": np.linspace(10, 40, len(idx)),
            "BBB": np.linspace(20, 24, len(idx)),
            "CCC": np.linspace(30, 33, len(idx)),
            "DDD": np.linspace(15, 18, len(idx)),
        },
        index=idx,
    )
    s2t = {
        "AAA": ["Theme 1"],
        "BBB": ["Theme 1", "Theme 2"],
        "CCC": ["Theme 1", "Theme 2"],
        "DDD": ["Theme 2"],
    }
    snap = compute_session_snapshot(close, s2t, idx[-1])
    assert "Theme 1" in snap["peer_theme_rs63_pct"]["AAA"]
    assert math.isclose(snap["peer_breadth21_pct"]["AAA"]["Theme 1"], 100.0)


def test_exact_20_session_history_is_required_for_acceleration():
    current = {
        "asof": "2026-08-31",
        "normal_theme_rs63_pct": {"T": 80.0, "U": 40.0},
        "peer_theme_rs63_pct": {"AAA": {"T": 90.0}},
        "peer_breadth21_pct": {"AAA": {"T": 75.0}},
        "theme_count": 2,
        "pair_count": 1,
        "taxonomy_sha256": "x",
    }
    s2t = {"AAA": ["T"]}
    no_base = {"schema": "v38-strict-loo-history-1", "sessions": [current]}
    live = build_live(no_base, s2t, current, "2026-08-03")
    assert live["status"] == "DATA REQUIRED"
    assert live["candidates"]["AAA"]["status"] == "DATA REQUIRED"

    old = {
        "asof": "2026-08-03",
        "normal_theme_rs63_pct": {"T": 60.0, "U": 50.0},
        "peer_theme_rs63_pct": {"AAA": {"T": 70.0}},
    }
    history = {"schema": "v38-strict-loo-history-1", "sessions": [old, current]}
    live = build_live(history, s2t, current, "2026-08-03")
    row = live["candidates"]["AAA"]
    assert live["status"] == "READY"
    assert row["status"] == "READY"
    assert row["themes"]["T"]["candidate_excluded_from_acceleration"] is True
    assert math.isfinite(row["themes"]["T"]["acceleration20_pct"])


def test_missing_exact_base_is_not_replaced_by_nearest_saved_snapshot():
    current = {
        "asof": "2026-08-31",
        "normal_theme_rs63_pct": {"T": 80.0},
        "peer_theme_rs63_pct": {"AAA": {"T": 90.0}},
        "peer_breadth21_pct": {"AAA": {"T": 75.0}},
        "theme_count": 1,
        "pair_count": 1,
        "taxonomy_sha256": "x",
    }
    almost = {
        "asof": "2026-08-04",
        "normal_theme_rs63_pct": {"T": 60.0},
        "peer_theme_rs63_pct": {"AAA": {"T": 70.0}},
    }
    history = {"schema": "v38-strict-loo-history-1", "sessions": [almost, current]}
    live = build_live(history, {"AAA": ["T"]}, current, "2026-08-03")
    assert live["history_has_exact_20_session_base"] is False
    assert live["status"] == "DATA REQUIRED"
