from pathlib import Path
import json
import re
import subprocess

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


def test_options_keep_snapshot_basis_for_swing_distance(tmp_path, monkeypatch):
    option_json = tmp_path / "options.json"
    option_json.write_text(
        json.dumps(
            {
                "asof": "2026-08-20T13:33:45+00:00",
                "tickers": {
                    "MU": {
                        "asof": "2026-08-20T13:33:45+00:00",
                        "spot": 940.85,
                        "atr14": 56.2407,
                        "nearest": "2026-08-21",
                        "expiries": {
                            "2026-08-21": {"call_wall": 955, "put_wall": 910},
                            "2026-08-28": {
                                "call_wall": 975,
                                "put_wall": 925,
                                "gamma_flip": 940.9165,
                                "confidence": "OK",
                                "total_oi": 57935,
                                "n_strikes": 101,
                            },
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(dashboard, "OPT_JSON", str(option_json))
    monkeypatch.setattr(dashboard, "OPT_SCAN_CSV", str(tmp_path / "missing.csv"))

    option = dashboard.load_options()["MU"]

    assert option["basis"] == "swing"
    assert option["dte"] == 8
    assert option["spot"] == 940.85
    assert option["asof_label"] == "08/20 22:33 JST"
    assert option["cwp"] == round(975 / 940.85 - 1, 5)
    assert option["pwp"] == round(925 / 940.85 - 1, 5)


def test_options_ui_uses_adr_units_and_exposes_snapshot_basis():
    source = Path(dashboard.__file__).read_text(encoding="utf-8")
    assert "['オプション基準',_optBasis(d.opt)" in source
    assert "['スイング結論',_optSwingConclusion(d.opt)" in source
    assert "+Math.abs(a).toFixed(1)+' ADR'" in source


def test_options_swing_helpers_are_valid_javascript():
    source = Path(dashboard.__file__).read_text(encoding="utf-8")
    match = re.search(
        r"  function _optBasis\(o\)\{.*?(?=  function _optcell\(o,k\)\{)",
        source,
        flags=re.S,
    )
    assert match is not None
    checked = subprocess.run(
        ["node", "--check", "-"],
        input=match.group(0),
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert checked.returncode == 0, checked.stderr
