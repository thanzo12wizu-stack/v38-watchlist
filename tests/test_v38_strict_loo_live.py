import math

import numpy as np
import pandas as pd
import pytest

from build_v38_strict_loo_live import (
    backfill_required_snapshots,
    build_live,
    compute_session_snapshot,
    extract_s2t,
    has_verified_bootstrap,
    PIT_BOOTSTRAP_EFFECTIVE_ASOF,
    PIT_BOOTSTRAP_SOURCE,
    PIT_BOOTSTRAP_TAXONOMY_SHA256,
    register_taxonomy_snapshot,
    replacement_percentile,
    taxonomy_for_asof,
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


def test_taxonomy_timeline_never_applies_snapshot_before_effective_date():
    history = {"schema": "v38-strict-loo-history-1", "sessions": []}
    history = register_taxonomy_snapshot(history, "2026-06-22", {"AAA": ["OLD"]}, "git:old")
    history = register_taxonomy_snapshot(history, "2026-08-01", {"AAA": ["NEW"]}, "daily:new")
    assert taxonomy_for_asof(history, "2026-07-31")[0]["AAA"] == ["OLD"]
    assert taxonomy_for_asof(history, "2026-08-01")[0]["AAA"] == ["NEW"]
    with pytest.raises(RuntimeError, match="PIT_TAXONOMY_REQUIRED"):
        taxonomy_for_asof(history, "2026-06-19")


def test_verified_bootstrap_requires_exact_source_date_and_membership_payload():
    history = {"schema": "v38-strict-loo-history-1", "sessions": [], "taxonomy_snapshots": [{
        "effective_asof": PIT_BOOTSTRAP_EFFECTIVE_ASOF,
        "source": PIT_BOOTSTRAP_SOURCE,
        "taxonomy_sha256": PIT_BOOTSTRAP_TAXONOMY_SHA256,
        "s2t": {"AAA": ["Theme"]},
    }]}
    assert has_verified_bootstrap(history) is True
    history["taxonomy_snapshots"][0]["source"] = "daily:sector_snapshot.json"
    assert has_verified_bootstrap(history) is False


def test_first_run_backfills_exact_t20_and_is_ready_without_waiting_21_days():
    idx = pd.bdate_range("2026-04-01", periods=80)
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
    history = {"schema": "v38-strict-loo-history-1", "sessions": []}
    history = register_taxonomy_snapshot(
        history, str(idx[0].date()), s2t, "git:verified-bootstrap",
    )

    history, current, base_asof = backfill_required_snapshots(history, close, idx[-1])
    live = build_live(history, s2t, current, base_asof)

    assert base_asof == str(idx[-21].date())
    assert {row["asof"] for row in history["sessions"]} == {base_asof, str(idx[-1].date())}
    assert history["covered_market_sessions"] == 80
    assert history["computed_snapshot_count"] == 2
    assert live["history_sessions"] == 80
    assert live["computed_snapshot_count"] == 2
    assert live["history_has_exact_20_session_base"] is True
    assert live["status"] == "READY"
    assert live["candidates"]["AAA"]["history_sessions"] == 80


def test_first_run_fails_closed_when_t20_predates_first_saved_taxonomy():
    idx = pd.bdate_range("2026-07-01", periods=80)
    close = pd.DataFrame({"AAA": np.linspace(10, 20, len(idx))}, index=idx)
    history = {"schema": "v38-strict-loo-history-1", "sessions": []}
    history = register_taxonomy_snapshot(
        history, str(idx[-10].date()), {"AAA": ["Theme"]}, "git:too-new",
    )
    with pytest.raises(RuntimeError, match="PIT_TAXONOMY_REQUIRED"):
        backfill_required_snapshots(history, close, idx[-1])
