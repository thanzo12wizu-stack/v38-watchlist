from pathlib import Path
import json
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import build_options_daily_liquid as daily


def _write_inputs(tmp_path):
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"date": "2026-09-04"}), encoding="utf-8")

    html = tmp_path / "command-center.html"
    details = {
        "GOOD": {"px": 25.0, "dvol": 12.5, "rs189": 1, "rs": 1},
        "LOWVOL": {"px": 25.0, "dvol": 9.99, "rs189": 99, "rs": 99},
        "LOWPX": {"px": 4.99, "dvol": 50.0},
        "ADR": {"px": 30.0, "dvol": 50.0},
        "ETF": {"px": 100.0, "dvol": 500.0},
    }
    html.write_text(
        "window.CALC=" + json.dumps({"asof": "2026-09-04"}) + ";</script>\n"
        "window.DET=" + json.dumps(details) + ";</script>\n",
        encoding="utf-8",
    )

    universe = tmp_path / "universe.csv"
    universe.write_text(
        "シンボル,名称,取引所,証券種別,証券サブタイプ\n"
        "GOOD,Good,NASDAQ,stock,common\n"
        "LOWVOL,LowVol,NASDAQ,stock,common\n"
        "LOWPX,LowPx,NASDAQ,stock,common\n"
        "ADR,Adr,NASDAQ,stock,dr\n"
        "ETF,Etf,NASDAQ,fund,etf\n",
        encoding="utf-8",
    )
    return state, html, universe


def test_daily_universe_is_liquidity_only_not_rs_theme(tmp_path, monkeypatch):
    state, html, universe = _write_inputs(tmp_path)
    monkeypatch.setattr(daily, "STATE_JSON", state)
    monkeypatch.setattr(daily, "DASHBOARD_HTML", html)
    monkeypatch.setattr(daily, "UNIVERSE_CSV", universe)
    monkeypatch.setattr(daily, "MIN_PRICE", 5.0)
    monkeypatch.setattr(daily, "MIN_DVOL_M", 10.0)

    tickers, rows, quality = daily.load_liquid_universe()

    assert tickers == ["GOOD"]
    assert rows["GOOD"]["dvol_m"] == 12.5
    # Deliberately weak RS still qualifies: this broad Options universe is liquidity-only.
    assert quality["rs_or_theme_filter_used"] is False
    assert quality["liquid_eligible"] == 1
    assert quality["session_date"] == "2026-09-04"


def test_liquidity_asof_mismatch_fails_closed(tmp_path, monkeypatch):
    state, html, universe = _write_inputs(tmp_path)
    state.write_text(json.dumps({"date": "2026-09-03"}), encoding="utf-8")
    monkeypatch.setattr(daily, "STATE_JSON", state)
    monkeypatch.setattr(daily, "DASHBOARD_HTML", html)
    monkeypatch.setattr(daily, "UNIVERSE_CSV", universe)

    with pytest.raises(RuntimeError, match="LIQUIDITY_ASOF_MISMATCH"):
        daily.load_liquid_universe()


def test_swing_expiry_uses_completed_session_date():
    expiries = ["2026-09-05", "2026-09-11", "2026-09-18", "2026-09-25", "2026-10-16"]
    assert daily._swing_expiry(expiries, "2026-09-04") == "2026-09-18"
    assert daily._swing_expiry(["2026-09-05", "2026-09-25"], "2026-09-04") is None


def test_scan_history_upsert_does_not_duplicate_same_session(tmp_path, monkeypatch):
    path = tmp_path / "scan.csv"
    path.write_text(
        "date,ticker,expiry,spot\n2026-09-04,GOOD,2026-09-18,20\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(daily, "SCAN_HIST", path)

    daily._upsert_history([
        {
            "date": "2026-09-04",
            "ticker": "GOOD",
            "expiry": "2026-09-18",
            "spot": 25,
            "dvol_m": 12.5,
        }
    ])

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert "dvol_m" in lines[0]
    assert ",25," in lines[1]
