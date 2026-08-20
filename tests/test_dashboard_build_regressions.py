from pathlib import Path

import numpy as np
import pandas as pd

import build_dashboard as dashboard


def test_rs189_quality_separates_history_from_selection_pool():
    metrics = pd.DataFrame(
        {
            "ret189": [0.20, 0.10, -0.05, np.nan],
            "rs_pool": [True, True, False, False],
            "rs189": [90.0, 50.0, np.nan, np.nan],
        },
        index=["A", "B", "C", "IPO"],
    )

    quality = dashboard._rs189_quality(metrics, universe_n=4)

    assert quality == {
        "history_n": 3,
        "history_cov": 0.75,
        "pool_n": 2,
        "rank_n": 2,
        "rank_cov": 1.0,
    }


def test_selftest_markers_match_checked_in_dashboard_artifact():
    html = (Path(__file__).resolve().parents[1] / "command-center.html").read_text(
        encoding="utf-8"
    )
    missing = [marker for marker in dashboard.SELFTEST_REQUIRED_MARKERS if marker not in html]
    assert not missing
