from pathlib import Path
import importlib
import json
import sys
import types

import pandas as pd

from tools import build_options_positioning as options


def test_data_confidence_is_data_depth_not_legacy_ok():
    assert options._data_confidence(400, 20, 200, 200)[0] == "LOW"
    assert options._data_confidence(2_000, 12, 1_200, 800)[0] == "MEDIUM"
    assert options._data_confidence(20_000, 40, 12_000, 8_000)[0] == "HIGH"


def test_wall_concentration_matches_the_directional_displayed_side():
    gex = pd.DataFrame(
        {
            "kind": ["C", "C", "C", "P", "P", "P"],
            "strike": [90.0, 105.0, 110.0, 90.0, 95.0, 110.0],
            "gex": [1_000.0, 300.0, 100.0, -200.0, -600.0, -2_000.0],
        }
    )
    call_share, _ = options._wall_concentration(gex, "C", spot=100.0)
    put_share, _ = options._wall_concentration(gex, "P", spot=100.0)

    assert call_share == 0.75  # ignores the stronger but wrong-side 90 Call
    assert put_share == 0.75  # ignores the stronger but wrong-side 110 Put


def test_options_copy_describes_proxy_and_atr_units():
    base = Path(options.__file__).read_text(encoding="utf-8")
    directional = Path("tools/build_options_positioning_directional.py").read_text(
        encoding="utf-8"
    )
    renderer = Path("tools/render_options_html.py").read_text(encoding="utf-8")

    assert "OI×推定Gamma" in base
    assert "実ディーラーGammaではない" in base
    assert "ATR。" in directional
    assert "値動き{days:.1f}日分" not in directional
    assert "Call GEX集中帯" in renderer
    assert "Put GEX集中帯" in renderer
    assert "Gamma Flip推定" in renderer


def test_fallback_keeps_recent_cache_usable_and_marks_actual_old_cache_stale(tmp_path):
    cache = tmp_path / "QQQ.json"
    cache.write_text(json.dumps({"ticker": "QQQ", "asof": "2026-08-20T22:00:00+00:00"}))

    recent = options._fallback_record(
        str(cache), "2026-08-21T04:00:00+00:00", RuntimeError("rate limited"))
    old = options._fallback_record(
        str(cache), "2026-08-25T04:00:00+00:00", RuntimeError("rate limited"))

    assert recent["refresh_failed"] is True
    assert recent["stale"] is False
    assert old["stale"] is True


def test_refresh_gate_rejects_green_workflow_on_mass_failure(monkeypatch):
    monkeypatch.setattr(options, "MIN_REFRESH_RATIO", 0.35)
    assert options._refresh_gate(28, 0) == (False, 0.0)
    ok, ratio = options._refresh_gate(30, 23)
    assert ok is True
    assert ratio == 23 / 30


def test_main_returns_failure_and_preserves_recent_fallback_on_provider_outage(
        tmp_path, monkeypatch):
    class BrokenTicker:
        def __init__(self, _ticker):
            pass

        def history(self, **_kwargs):
            raise RuntimeError("Too Many Requests")

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    for ticker in options.REFERENCE_TICKERS:
        (cache_dir / f"{ticker}.json").write_text(
            json.dumps({"ticker": ticker, "asof": options._now(), "expiries": {}}),
            encoding="utf-8",
        )

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=BrokenTicker))
    monkeypatch.setattr(options, "CACHE_DIR", str(cache_dir))
    monkeypatch.setattr(options, "OUT_JSON", str(tmp_path / "options.json"))
    monkeypatch.setattr(options, "HIST_CSV", str(tmp_path / "history.csv"))
    monkeypatch.setattr(options, "STATE_JSON", str(tmp_path / "missing-state.json"))
    monkeypatch.setattr(options, "TARGETS_JSON", str(tmp_path / "missing-targets.json"))
    monkeypatch.setattr(options, "TICKERS_ENV", "")
    monkeypatch.setattr(options, "FETCH_ATTEMPTS", 1)
    monkeypatch.setattr(options, "SCAN_ALL", False)
    monkeypatch.setattr(options.time, "sleep", lambda _seconds: None)

    assert options.main() == 2
    output = json.loads((tmp_path / "options.json").read_text(encoding="utf-8"))
    assert output["quality"]["refreshed"] == 0
    assert output["quality"]["fallback"] == len(options.REFERENCE_TICKERS)
    assert output["quality"]["gate_ok"] is False
    assert all(v["refresh_failed"] and not v["stale"]
               for v in output["tickers"].values())
    assert not (tmp_path / "history.csv").exists()


def test_scan_rotation_prioritizes_unseen_and_backs_off_no_option_names(monkeypatch):
    monkeypatch.setattr(options, "SCAN_REFRESH_DAYS", 14)
    state = {
        "A": {"checked_at": "2026-08-20", "status": "ok"},
        "B": {"checked_at": "2026-07-01", "status": "ok"},
        "C": {"checked_at": "2026-08-01", "status": "no_options"},
    }

    selected = options._scan_targets(
        ["A", "B", "C", "D", "E"], state, "2026-08-21T22:00:00+00:00", 3)

    assert selected == ["D", "E", "B"]


def test_expiry_selection_keeps_swing_window_when_weeklies_are_dense():
    expiries = [
        "2026-08-21", "2026-08-24", "2026-08-25", "2026-08-26",
        "2026-08-28", "2026-09-04", "2026-09-11",
    ]

    detailed = options._select_expiries(
        expiries, "2026-08-21T22:00:00+00:00", limit=4, include_nearest=True)
    broad = options._select_expiries(
        expiries, "2026-08-21T22:00:00+00:00", limit=1, include_nearest=False)

    assert detailed[0] == "2026-08-21"
    assert "2026-09-04" in detailed  # DTE14を直近4本の外から拾う
    assert broad == ["2026-09-04"]


def test_zero_quotes_do_not_erase_valid_open_interest():
    tools_path = str(Path("tools").resolve())
    sys.path.insert(0, tools_path)
    try:
        directional = importlib.import_module("build_options_positioning_directional")
        df = pd.DataFrame({
            "strike": [101, 102, 103, 104, 105, 106, 107, 108],
            "openInterest": [100] * 8,
            "impliedVolatility": [0.25] * 8,
            "volume": [0] * 8,
            "bid": [0] * 8,
            "ask": [0] * 8,
        })
        cleaned = directional._clean_positioning_rows(df, "C")
        assert len(cleaned) == 8
        assert int(cleaned["openInterest"].sum()) == 800
    finally:
        sys.path.remove(tools_path)


def test_options_workflow_runs_daily_liquid_scan_after_upstream_close_build():
    workflow = Path(".github/workflows/options.yml").read_text(encoding="utf-8")
    assert "  push:" not in workflow
    assert "schedule:" in workflow
    assert "workflow_dispatch:" in workflow
    assert "cron: '47 23 * * 1-5'" in workflow
    assert "V38_OPT_SCAN_ALL: '0'" in workflow
    assert "python tools/build_options_daily_liquid.py" in workflow
    assert "V38_OPT_MIN_PRICE: '5'" in workflow
    assert "V38_OPT_MIN_DVOL_M: '10'" in workflow
    assert "V38_OPT_SCAN_STATE: options_scan_state.json" in workflow
    assert "V38_OPT_MIN_REFRESH_RATIO: '0.35'" in workflow
