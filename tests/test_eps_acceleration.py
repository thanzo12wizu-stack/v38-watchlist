from pathlib import Path
import json
import sys

import pandas as pd

import build_dashboard as dashboard


def _earnings_frame(values):
    dates = pd.to_datetime(
        ["2026-07-20", "2026-04-20", "2026-01-20", "2025-10-20",
         "2025-07-20", "2025-04-20", "2025-01-20", "2024-10-20"]
    )
    return pd.DataFrame({"Reported EPS": values}, index=dates)


def test_eps_acceleration_requires_three_quarter_confirmation():
    result = dashboard._eps_acceleration_from_dates(
        _earnings_frame([2.0, 1.5, 1.2, 1.0, 1.0, 1.0, 1.0, 0.5])
    )

    assert result["status"] == "ok"
    assert result["trend"] == "ACCEL_CONFIRMED"
    assert result["latest_yoy"] == 100.0
    assert result["prior_yoy"] == 50.0
    assert result["third_yoy"] == 20.0
    assert result["accel_pp"] == 50.0
    assert result["accel_streak"] == 2
    assert result["latest_date"] == "2026-07-20"


def test_eps_acceleration_marks_four_quarter_persistence():
    result = dashboard._eps_acceleration_from_dates(
        _earnings_frame([2.0, 1.5, 1.2, 1.0, 1.0, 1.0, 1.0, 1.0])
    )

    assert result["trend"] == "ACCEL_PERSISTENT"
    assert result["accel_streak"] == 3
    assert result["fourth_yoy"] == 0.0


def test_one_quarter_acceleration_is_only_provisional():
    result = dashboard._eps_acceleration_from_dates(
        _earnings_frame([2.0, 1.5, 1.49, 1.0, 1.0, 1.0, 1.0, 0.5])
    )

    assert result["latest_yoy"] == 100.0
    assert result["prior_yoy"] == 50.0
    assert result["third_yoy"] == 49.0
    assert result["accel_streak"] == 1
    assert result["trend"] == "ACCEL_ONE_Q"


def test_tiny_prior_eps_is_flagged_even_when_streak_is_confirmed():
    result = dashboard._eps_acceleration_from_dates(
        _earnings_frame([0.20, 0.12, 0.06, 0.03, 0.04, 0.04, 0.04, 0.04])
    )

    assert result["trend"] == "ACCEL_PERSISTENT"
    assert result["low_base"] is True
    assert "主候補から除外" in result["quality_note"]


def test_eps_acceleration_does_not_score_loss_to_profit_transition():
    result = dashboard._eps_acceleration_from_dates(
        _earnings_frame([2.0, 1.5, 1.2, 1.1, -0.4, 1.0, 1.0, 1.0])
    )

    assert result["status"] == "non_comparable"
    assert result["trend"] == "TURNAROUND"
    assert "accel_pp" not in result


def test_fmp_actual_eps_payload_uses_same_acceleration_rules():
    payload = [
        {"date": "2026-07-20", "epsActual": 2.0},
        {"date": "2026-04-20", "epsActual": 1.5},
        {"date": "2026-01-20", "epsActual": 1.2},
        {"date": "2025-10-20", "epsActual": 1.1},
        {"date": "2025-07-20", "epsActual": 1.0},
        {"date": "2025-04-20", "epsActual": 1.0},
        {"date": "2025-01-20", "epsActual": 1.0},
        {"date": "2024-10-20", "epsActual": 0.5},
    ]

    result = dashboard._eps_acceleration_from_fmp(payload)

    assert result["status"] == "ok"
    assert result["accel_pp"] == 50.0
    assert result["source"] == "FMP Earnings Report actual EPS"


def test_eps_acceleration_requires_seven_reported_quarters():
    result = dashboard._eps_acceleration_from_dates(
        _earnings_frame([2.0, 1.5, 1.2, 1.1, 1.0, 1.0, 1.0, 1.0]).iloc[:6]
    )

    assert result == {
        "status": "insufficient",
        "trend": "INSUFFICIENT",
        "source": "Yahoo Finance Reported EPS",
        "quarters": 6,
    }


def test_eps_acceleration_rejects_non_quarterly_sequence():
    frame = _earnings_frame([2.0, 1.5, 1.2, 1.1, 1.0, 1.0, 1.0, 1.0])
    frame.index = pd.to_datetime(
        ["2026-07-20", "2026-06-20", "2026-01-20", "2025-10-20",
         "2025-07-20", "2025-04-20", "2025-01-20", "2024-10-20"]
    )

    result = dashboard._eps_acceleration_from_dates(frame)

    assert result["status"] == "insufficient"
    assert "不連続" in result["note"]


def test_old_earnings_cache_is_refetched_for_eps_schema():
    today = pd.Timestamp("2026-08-21")

    assert dashboard._earnings_needs_fetch(
        {"checked_at": "2026-08-21", "next_earnings": "2026-11-01"}, today
    )
    assert not dashboard._earnings_needs_fetch(
        {"checked_at": "2026-08-21", "eps_schema": dashboard.EPS_SCHEMA_VERSION}, today
    )
    assert dashboard._earnings_fetch_priority(None, today) == 0
    assert dashboard._earnings_fetch_priority(
        {"checked_at": "2026-08-21", "eps_schema": dashboard.EPS_SCHEMA_VERSION,
         "eps": {"status": "fetch_error"}}, today
    ) is None
    assert dashboard._earnings_fetch_priority(
        {"checked_at": "2026-08-14", "eps_schema": dashboard.EPS_SCHEMA_VERSION,
         "eps": {"status": "fetch_error"}}, today
    ) == 1
    assert dashboard._earnings_fetch_priority(
        {"checked_at": "2026-08-21", "eps_schema": dashboard.EPS_SCHEMA_VERSION,
         "eps": {"status": "ok"}}, today
    ) is None


def test_load_earnings_prefers_fmp_and_avoids_yahoo_when_complete(tmp_path, monkeypatch):
    cache = tmp_path / "earnings.json"
    cache.write_text("{}", encoding="utf-8")
    actual = [
        {"date": "2026-07-20", "epsActual": 2.0},
        {"date": "2026-04-20", "epsActual": 1.5},
        {"date": "2026-01-20", "epsActual": 1.2},
        {"date": "2025-10-20", "epsActual": 1.1},
        {"date": "2025-07-20", "epsActual": 1.0},
        {"date": "2025-04-20", "epsActual": 1.0},
        {"date": "2025-01-20", "epsActual": 1.0},
        {"date": "2024-10-20", "epsActual": 0.5},
        {"date": "2027-01-20", "epsActual": None, "epsEstimated": 2.3},
    ]
    monkeypatch.setenv("V38_ER_JSON", str(cache))
    monkeypatch.setenv("FMP_API_KEY", "test-key")
    monkeypatch.setenv("V38_USE_FMP_EPS", "1")
    monkeypatch.setattr(dashboard, "_net_ok", lambda: True)
    monkeypatch.setattr(dashboard, "_fmp_get", lambda *a, **k: (actual, "ok"))

    class NoYahoo:
        def Ticker(self, _ticker):
            raise AssertionError("complete FMP data should avoid Yahoo calls")

    monkeypatch.setitem(sys.modules, "yfinance", NoYahoo())
    result = dashboard.load_earnings(["NVDA"], live=True)

    assert result["NVDA"]["next_earnings"] == "2027-01-20"
    assert result["NVDA"]["eps"]["accel_pp"] == 50.0
    assert result["NVDA"]["eps_schema"] == dashboard.EPS_SCHEMA_VERSION


def test_failed_schema_migration_never_promotes_old_two_quarter_result(tmp_path, monkeypatch):
    cache = tmp_path / "earnings.json"
    cache.write_text(json.dumps({"OLD": {
        "checked_at": "2026-08-20", "eps_schema": 1,
        "eps": {"status": "ok", "trend": "ACCEL_STRONG", "accel_pp": 500.0},
    }}), encoding="utf-8")
    monkeypatch.setenv("V38_ER_JSON", str(cache))
    monkeypatch.delenv("FMP_API_KEY", raising=False)
    monkeypatch.setattr(dashboard, "_net_ok", lambda: True)

    class BrokenTicker:
        calendar = {}

        def get_earnings_dates(self, **_kwargs):
            raise RuntimeError("rate limited")

    monkeypatch.setitem(
        sys.modules, "yfinance",
        type("BrokenYahoo", (), {"Ticker": lambda _self, _ticker: BrokenTicker()})())

    result = dashboard.load_earnings(["OLD"], live=True)

    assert result["OLD"]["eps_schema"] == dashboard.EPS_SCHEMA_VERSION
    assert result["OLD"]["eps"]["status"] == "fetch_error"
    assert result["OLD"]["eps"]["trend"] == "FETCH_ERROR"
    assert result["OLD"]["eps"].get("accel_pp") is None


def test_failed_current_schema_refresh_backs_off_without_discarding_good_data():
    today = pd.Timestamp("2026-08-21")
    recent_failure = {
        "checked_at": "2026-07-01", "eps_schema": dashboard.EPS_SCHEMA_VERSION,
        "eps": {"status": "ok"}, "eps_refresh_failed": True,
        "eps_refresh_attempted_at": "2026-08-20",
    }
    old_failure = dict(recent_failure, eps_refresh_attempted_at="2026-08-14")

    assert dashboard._earnings_needs_fetch(recent_failure, today) is False
    assert dashboard._earnings_needs_fetch(old_failure, today) is True


def test_eps_ui_is_informational_and_exposes_source_and_quality_gates():
    source = Path(dashboard.__file__).read_text(encoding="utf-8")

    assert "['EPS加速',_epsSummary(d.eps)" in source
    assert "['EPS比較根拠',_epsBasis(d.eps)" in source
    assert "build_eps_acceleration_card(mkt.get(\"er\"), mkt.get(\"eps_tickers\"))" in source
    assert "Core 12の順位・売買スコアには不使用" in source
    assert "主判定は3四半期" in source
    assert "1段階だけは「単発」として主候補にしない" in source


def test_eps_card_renders_acceleration_without_becoming_a_trade_score():
    html = dashboard.build_eps_acceleration_card(
        {"NVDA": {"eps_schema": dashboard.EPS_SCHEMA_VERSION, "eps": {
            "status": "ok", "trend": "ACCEL_CONFIRMED", "latest_date": "2026-07-20",
            "latest_eps": 2.0, "latest_yago_eps": 1.0,
            "prior_yoy": 50.0, "latest_yoy": 100.0, "third_yoy": 20.0,
            "accel_pp": 50.0, "accel_streak": 2, "low_base": False,
            "yoy_series": [{"date": "2026-07-20", "yoy": 100.0},
                           {"date": "2026-04-20", "yoy": 50.0},
                           {"date": "2026-01-20", "yoy": 20.0}],
        }}},
        ["NVDA"],
    )

    assert 'data-tkone="NVDA"' in html
    assert "EPS前年比 +20.0% → +50.0% → +100.0%" in html
    assert "3Q確認" in html
    assert "直近変化 <b class=\"pos\">+50.0pt</b>" in html
    assert "Core 12の順位・売買スコアには不使用" in html
    assert "取得済み <b>1/1</b>銘柄" in html


def test_eps_card_does_not_promote_legacy_two_quarter_signal():
    html = dashboard.build_eps_acceleration_card(
        {"OLD": {"eps_schema": 1, "eps": {
            "status": "ok", "trend": "ACCEL_STRONG", "accel_pp": 500.0,
        }}},
        ["OLD"],
    )

    assert "3四半期連続で確認できるEPS加速なし" in html
    assert "旧2Q方式から3Q方式へ更新待ち 1銘柄" in html
    assert "3Q方式取得済み <b>0/1</b>銘柄" in html


def test_eps_coverage_caps_are_large_but_bounded():
    assert dashboard.EPS_PRIORITY_TARGET_CAP == 160
    assert dashboard.EPS_FETCH_BUDGET == 120
    assert dashboard.EPS_FETCH_SECONDS == 180
    assert dashboard.EPS_PRIORITY_FETCH_RESERVE == 20


def test_eps_queue_fills_missing_names_before_refreshing_existing_names():
    today = pd.Timestamp("2026-08-21")
    tickers = [f"T{i:03d}" for i in range(160)]
    fresh = {
        t: {"checked_at": "2026-08-21", "eps_schema": dashboard.EPS_SCHEMA_VERSION,
            "eps": {"status": "ok"}}
        for t in tickers[:40]
    }

    queue = dashboard._earnings_fetch_queue(tickers, fresh, today, budget=120)

    assert queue == tickers[40:]


def test_eps_queue_accumulates_full_universe_and_rotates_oldest_cache():
    today = pd.Timestamp("2026-08-21")
    tickers = [f"T{i:03d}" for i in range(400)]
    cache = {
        t: {"checked_at": "2026-08-20", "eps_schema": dashboard.EPS_SCHEMA_VERSION,
            "eps": {"status": "ok"}}
        for t in tickers[:160]
    }

    queue = dashboard._earnings_fetch_queue(
        tickers, cache, today, budget=120, priority_tickers=tickers[:160])

    assert queue == tickers[160:280]

    stale = {
        "A": {"checked_at": "2026-07-01", "eps_schema": dashboard.EPS_SCHEMA_VERSION,
              "eps": {"status": "ok"}},
        "B": {"checked_at": "2026-07-15", "eps_schema": dashboard.EPS_SCHEMA_VERSION,
              "eps": {"status": "ok"}},
        "C": {"checked_at": "2026-07-10", "eps_schema": dashboard.EPS_SCHEMA_VERSION,
              "eps": {"status": "ok"}},
    }
    assert dashboard._earnings_fetch_queue(
        ["B", "C", "A"], stale, today, budget=3, priority_reserve=0
    ) == ["A", "C", "B"]
