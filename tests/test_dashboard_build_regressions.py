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
                        "stale": True,
                        "spot": 940.85,
                        "atr14": 56.2407,
                        "tech": {"21EMA": 924.8, "50MA": 800, "63VWAP": 975.5},
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
                                "call_wall_share": 0.24,
                                "put_wall_share": 0.21,
                            },
                            "2026-09-11": {
                                "call_wall": 976,
                                "put_wall": 924,
                                "gamma_flip": 940.5,
                                "confidence": "HIGH",
                                "total_oi": 42000,
                                "n_strikes": 90,
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

    option = dashboard.load_options(now="2026-08-21T13:00:00+00:00")["MU"]

    assert option["basis"] == "swing"
    assert option["dte"] == 7
    assert option["stale"] is False
    assert option["refresh_failed"] is True
    assert option["spot"] == 940.85
    assert option["asof_label"] == "08/20 22:33 JST"
    assert option["cwp"] == round(975 / 940.85 - 1, 5)
    assert option["pwp"] == round(925 / 940.85 - 1, 5)
    assert option["conf"] == "MEDIUM"
    assert option["xexp_n"] == 2
    assert option["cwx"] == 1
    assert option["pwx"] == 1
    assert option["gfx"] == 1
    assert option["cfl"]["cw"] == [{"name": "63VWAP", "px": 975.5}]
    assert option["cfl"]["pw"] == [{"name": "21EMA", "px": 924.8}]


def test_options_expiry_and_staleness_are_evaluated_at_display_time(tmp_path, monkeypatch):
    scan = tmp_path / "scan.csv"
    scan.write_text(
        "date,ticker,expiry,call_wall,put_wall,gamma_flip,confidence\n"
        "2026-08-18,OLD,2026-08-21,110,90,100,OK\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(dashboard, "OPT_JSON", str(tmp_path / "missing.json"))
    monkeypatch.setattr(dashboard, "OPT_SCAN_CSV", str(scan))

    option = dashboard.load_options(now="2026-08-24T13:00:00+00:00")["OLD"]

    assert option["dte"] == -3
    assert option["stale"] is True
    assert option["age"] == 6


def test_options_ui_uses_atr_units_and_exposes_model_limits():
    source = Path(dashboard.__file__).read_text(encoding="utf-8")
    assert "['オプション基準',_optBasis(d.opt)" in source
    assert "['データ信頼度',_optConfidence(d.opt)" in source
    assert "['テクニカル重なり',_optConfluence(d.opt)" in source
    assert "['実績検証',_optValidation(d.opt)" in source
    assert "['スイング結論',_optSwingConclusion(d.opt)" in source
    assert "+Math.abs(a).toFixed(1)+' ATR'" in source
    assert "['Call GEX集中帯',_optcell(d.opt,'cw')" in source
    assert "['Put GEX集中帯',_optcell(d.opt,'pw')" in source
    assert "['Gamma Flip推定',_optcell(d.opt,'gf')" in source
    assert "OI更新時刻は提供元非開示" in source


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



def test_market_condition_balances_three_market_layers():
    idx = pd.DatetimeIndex([pd.Timestamp("2026-08-25")])
    cols = {}
    cols.update({ticker: [100.0] for ticker in dashboard.MC_BROAD_ETFS})
    cols.update({ticker: [0.0] for ticker in dashboard.MC_SECTOR_ETFS})
    for tickers in dashboard.MC_INDUSTRY_PARENT.values():
        cols.update({ticker: [0.0] for ticker in tickers})
    out = dashboard._mc_stratified_mean(pd.DataFrame(cols, index=idx))
    assert np.isclose(out.iloc[-1], 100.0 / 3.0)


def test_market_condition_balances_industry_parent_groups():
    idx = pd.DatetimeIndex([pd.Timestamp("2026-08-25")])
    groups = list(dashboard.MC_INDUSTRY_PARENT.values())
    assert len(groups) >= 2
    cols = {ticker: [100.0] for ticker in groups[0]}
    cols.update({ticker: [0.0] for ticker in groups[1]})
    out = dashboard._mc_stratified_mean(pd.DataFrame(cols, index=idx))
    assert np.isclose(out.iloc[-1], 50.0)


def test_market_condition_four_pillars_are_equal_weight():
    weights = [row[1] for row in dashboard.STATUS_DEF]
    assert weights == [25.0, 25.0, 25.0, 25.0]
    assert np.isclose(sum(weights), 100.0)
