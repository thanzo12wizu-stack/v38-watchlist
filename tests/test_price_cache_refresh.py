from __future__ import annotations

from pathlib import Path

import pandas as pd

from intelligence_engine import ensure_prices
from intelligence_engine.prices import load_price_map, save_price_map


def _frame(dates: list[str], start: float) -> pd.DataFrame:
    index = pd.to_datetime(dates)
    close = pd.Series([start + offset for offset in range(len(index))], index=index)
    return pd.DataFrame(
        {
            "open": close - .2,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": 1_000_000,
        },
        index=index,
    )


class FakeProvider:
    name = "fake"

    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], str]] = []

    def download(self, tickers, *, period="18mo"):
        normalized = tuple(sorted(tickers))
        self.calls.append((normalized, period))
        output = {}
        if normalized == ("QQQ",):
            output["QQQ"] = _frame(["2026-07-22"], 500)
        if normalized == ("AAA",):
            output["AAA"] = _frame(["2026-07-21", "2026-07-22"], 100)
        return output, {
            "provider": self.name,
            "requested": len(normalized),
            "received": len(output),
            "coverage": len(output) / len(normalized) if normalized else 0,
        }


def test_run_refreshes_only_stale_tickers_against_fresh_qqq(tmp_path: Path, monkeypatch) -> None:
    universe = tmp_path / "universe.csv"
    pd.DataFrame([{"ticker": "AAA", "sector": "Tech", "industry": "Software"}]).to_csv(universe, index=False)
    cache = tmp_path / "prices.pkl"
    save_price_map(
        cache,
        {
            "QQQ": _frame(["2026-07-20", "2026-07-21"], 490),
            "AAA": _frame(["2026-07-20"], 95),
        },
    )
    provider = FakeProvider()
    monkeypatch.setattr(ensure_prices, "get_price_provider", lambda name=None: provider)
    result = ensure_prices.run(universe, cache, min_coverage=1.0)
    assert result["qqq_latest_date"] == "2026-07-22"
    assert result["stale_requested"] == 1
    assert (("QQQ",), "3mo") in provider.calls
    assert (("AAA",), "3mo") in provider.calls
    restored = load_price_map(cache)
    assert restored["AAA"].index.min() == pd.Timestamp("2026-07-20")
    assert restored["AAA"].index.max() == pd.Timestamp("2026-07-22")
