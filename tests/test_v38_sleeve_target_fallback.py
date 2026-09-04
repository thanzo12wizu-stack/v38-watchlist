from __future__ import annotations

import pandas as pd

import run_v38_sleeve_refresh_live as live_refresh


def test_target_session_missing_open_uses_yahoo_chart(monkeypatch):
    target = pd.Timestamp("2026-09-03")
    base_open = pd.DataFrame(
        {"BFLY": [float("nan")], "SPY": [100.0]},
        index=[target],
    )
    base_close = pd.DataFrame(
        {"BFLY": [8.43], "SPY": [101.0]},
        index=[target],
    )

    def base_downloader(symbols, start, end, batch_size=150):
        return base_open.reindex(columns=symbols), base_close.reindex(columns=symbols), {"source": "BASE"}

    calls: list[str] = []

    def yahoo_chart(symbol: str, start: str):
        calls.append(symbol)
        assert symbol == "BFLY"
        return pd.DataFrame(
            {"Open": [8.20], "Close": [8.43]},
            index=[target],
        )

    monkeypatch.setattr(live_refresh, "_BASE_RESILIENT", base_downloader)
    monkeypatch.setattr(live_refresh.refresh, "download_yahoo_chart", yahoo_chart)

    op, cl, quality = live_refresh.download_adjusted_ohlc_live(
        ["BFLY", "SPY"], "2026-08-26", "2026-09-04", 100
    )

    assert calls == ["BFLY"]
    assert float(op.at[target, "BFLY"]) == 8.20
    assert float(cl.at[target, "BFLY"]) == 8.43
    assert quality["target_session"] == "2026-09-03"
    assert quality["target_fallback_used"] == ["BFLY"]
    assert quality["target_fallback_failed"] == {}


def test_large_reset_request_does_not_use_target_session_wrapper(monkeypatch):
    symbols = [f"SYM{i:03d}" for i in range(51)]
    target = pd.Timestamp("2026-09-03")
    op = pd.DataFrame({symbol: [1.0] for symbol in symbols}, index=[target])
    cl = pd.DataFrame({symbol: [1.1] for symbol in symbols}, index=[target])

    def base_downloader(requested, start, end, batch_size=150):
        return op.reindex(columns=requested), cl.reindex(columns=requested), {"source": "RESET_BASE"}

    def should_not_run(*args, **kwargs):
        raise AssertionError("Yahoo target-session fallback must not run for Reset large request")

    monkeypatch.setattr(live_refresh, "_BASE_RESILIENT", base_downloader)
    monkeypatch.setattr(live_refresh.refresh, "download_yahoo_chart", should_not_run)

    out_open, out_close, quality = live_refresh.download_adjusted_ohlc_live(
        symbols, "2026-01-01", "2026-09-04", 100
    )

    assert list(out_open.columns) == symbols
    assert list(out_close.columns) == symbols
    assert quality == {"source": "RESET_BASE"}
