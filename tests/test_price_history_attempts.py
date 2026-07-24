from __future__ import annotations

import json

import pandas as pd

from intelligence_engine import ensure_prices


def _frame(start: str, periods: int = 30) -> pd.DataFrame:
    index = pd.date_range(start, periods=periods, freq="B")
    return pd.DataFrame(
        {
            "open": 1.0,
            "high": 1.1,
            "low": 0.9,
            "close": 1.0,
            "volume": 1000.0,
        },
        index=index,
    )


def test_history_attempts_are_persisted_and_recent_ipos_are_not_reselected(tmp_path, monkeypatch):
    universe = tmp_path / "universe.csv"
    universe.write_text("ticker\nIPO\n", encoding="utf-8")
    cache = tmp_path / "prices.pkl"
    attempts = tmp_path / "history-attempts.json"

    class Provider:
        name = "fake"

        def __init__(self):
            self.history_calls = 0

        def download(self, tickers, *, period="18mo"):
            if period == "3mo":
                return {"QQQ": _frame("2026-01-01")}, {"requested": len(tickers), "received": 1}
            if period == "18mo":
                return {ticker: _frame("2025-01-01") for ticker in tickers}, {"requested": len(tickers), "received": len(tickers)}
            self.history_calls += 1
            return {ticker: _frame("2025-01-01") for ticker in tickers}, {"requested": len(tickers), "received": len(tickers)}

    provider = Provider()
    monkeypatch.setattr(ensure_prices, "get_price_provider", lambda *_: provider)

    first = ensure_prices.run(
        universe,
        cache,
        history_years=10,
        max_history_tickers=10,
        history_attempts_path=attempts,
    )
    second = ensure_prices.run(
        universe,
        cache,
        history_years=10,
        max_history_tickers=10,
        history_attempts_path=attempts,
    )

    assert first["history_batch"] >= 1
    assert first["history_remaining"] == 0
    assert second["history_batch"] == 0
    assert second["history_remaining"] == 0
    assert provider.history_calls == 1
    payload = json.loads(attempts.read_text(encoding="utf-8"))
    assert "IPO" in payload["attempted"]


def test_failed_history_download_remains_retryable(tmp_path, monkeypatch):
    universe = tmp_path / "universe.csv"
    universe.write_text("ticker\nMISS\n", encoding="utf-8")
    cache = tmp_path / "prices.pkl"
    attempts = tmp_path / "history-attempts.json"

    class Provider:
        name = "fake"

        def download(self, tickers, *, period="18mo"):
            if period == "3mo":
                return {"QQQ": _frame("2026-01-01")}, {"requested": len(tickers), "received": 1}
            if period == "18mo":
                return {ticker: _frame("2025-01-01") for ticker in tickers}, {"requested": len(tickers), "received": len(tickers)}
            return {}, {"requested": len(tickers), "received": 0}

    monkeypatch.setattr(ensure_prices, "get_price_provider", lambda *_: Provider())
    result = ensure_prices.run(
        universe,
        cache,
        history_years=10,
        max_history_tickers=10,
        history_attempts_path=attempts,
    )

    assert result["history_batch"] >= 1
    assert result["history_remaining"] >= 1
    payload = json.loads(attempts.read_text(encoding="utf-8"))
    assert "MISS" not in payload["attempted"]
