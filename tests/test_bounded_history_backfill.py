from pathlib import Path

import pandas as pd

from intelligence_engine import ensure_prices


def _frame(period: str) -> pd.DataFrame:
    periods = 60 if period == "3mo" else 320 if period == "18mo" else 2520
    index = pd.bdate_range(end="2026-06-30", periods=periods)
    return pd.DataFrame(
        {
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 1_000_000,
        },
        index=index,
    )


class _Provider:
    name = "test"

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], str]] = []

    def download(self, tickers, *, period):
        normalized = [str(ticker) for ticker in tickers]
        self.calls.append((normalized, period))
        return (
            {ticker: _frame(period) for ticker in normalized},
            {"requested": len(normalized), "received": len(normalized)},
        )


def test_missing_symbols_get_recent_coverage_before_bounded_ten_year_expansion(tmp_path, monkeypatch):
    universe = tmp_path / "universe.csv"
    universe.write_text("ticker\nAAA\nBBB\nCCC\n", encoding="utf-8")
    provider = _Provider()
    monkeypatch.setattr(ensure_prices, "get_price_provider", lambda _name=None: provider)

    result = ensure_prices.run(
        universe,
        tmp_path / "prices.pkl",
        min_coverage=1.0,
        history_years=10,
        max_history_tickers=2,
    )

    assert provider.calls[0] == (["QQQ"], "3mo")
    assert provider.calls[1] == (["AAA", "BBB", "CCC"], "18mo")
    ten_year_calls = [tickers for tickers, period in provider.calls if period == "10y"]
    assert ten_year_calls == [["QQQ", "AAA"]]
    assert result["history_requested"] == 4
    assert result["history_batch"] == 2
    assert result["history_received"] == 2
