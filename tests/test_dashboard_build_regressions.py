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




def test_market_condition_full_equal_weight_contract():
    assert len(dashboard.MC_MARKET_TICKERS) == 57
    assert [row[1] for row in dashboard.STATUS_DEF] == [
        33.333333333333336,
        33.333333333333336,
        16.666666666666668,
        16.666666666666668,
    ]
    idx = pd.DatetimeIndex([pd.Timestamp("2026-08-25")])
    cols = {ticker: [0.0] for ticker in dashboard.MC_MARKET_TICKERS}
    cols[dashboard.MC_MARKET_TICKERS[0]] = [1.0]
    out = dashboard._mc_participation(pd.DataFrame(cols, index=idx).astype(bool))
    assert np.isclose(out.iloc[-1], 100.0 / 57.0)



def test_market_condition_15y_temperature_contract():
    z = pd.Series([-2.0, -1.0, 0.0, 1.0, 2.0])
    got = dashboard._mc_z_to_temperature(z).to_numpy()
    assert np.allclose(got, [10.0, 25.0, 50.0, 75.0, 90.0])
    assert dashboard.MC_BASELINE_BARS == 252 * 15

    raw = pd.Series(np.arange(dashboard.MC_BASELINE_BARS + 2, dtype=float))
    temp, mean15, sd15, z15 = dashboard._mc_temperature_from_raw(raw)
    i = dashboard.MC_BASELINE_BARS
    expected = raw.iloc[:i]
    assert np.isclose(mean15.iloc[i], expected.mean())
    assert np.isclose(sd15.iloc[i], expected.std(ddof=0))
    assert np.isclose(z15.iloc[i], (raw.iloc[i] - expected.mean()) / expected.std(ddof=0))
    assert np.isfinite(temp.iloc[i])


def test_market_condition_fold_contains_occupancy_context():
    source = Path(dashboard.__file__).read_text(encoding="utf-8")
    assert "長期滞在比率（本番MC15履歴から毎回再計算・scoreには不算入）" in source
    assert "右端は各指標のRawへの寄与" in source
    assert 'mri_band(aux["cur"])' in source



def test_market_condition_history_is_recomputed_from_production_series():
    assert dashboard.MC_LONG_HISTORY_START <= "1993-01-01"
    assert dashboard.MC_HISTORY_DISPLAY_START == "2008-01-01"
    idx = pd.to_datetime([
        "2008-01-02", "2012-01-03", "2013-01-02", "2014-01-02", "2015-01-02"
    ])
    mri = pd.Series([60.0, 50.0, 40.0, 70.0, 30.0], index=idx)
    coverage = pd.Series([100.0, 100.0, 100.0, 90.0, 80.0], index=idx)
    occ = dashboard._mc_occupancy_stats(mri, coverage)

    assert occ["long"]["n"] == 5
    assert np.isclose(occ["long"]["bull"], 40.0)
    assert np.isclose(occ["long"]["neutral"], 20.0)
    assert np.isclose(occ["long"]["bear"], 40.0)
    assert occ["coverage50"]["n"] == 2
    assert np.isclose(occ["coverage50"]["bull"], 50.0)
    assert np.isclose(occ["coverage50"]["bear"], 50.0)

    source = Path(dashboard.__file__).read_text(encoding="utf-8")
    assert "MC_OCCUPANCY_LONG" not in source
    assert "MC_OCCUPANCY_50ETF" not in source
    assert "mri.iloc[-CHART_LB:].items()" not in source
    assert "本番MC15履歴から毎回再計算" in source
