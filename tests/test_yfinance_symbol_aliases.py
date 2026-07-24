from __future__ import annotations

import pandas as pd

from intelligence_engine import providers


def _frame() -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=3, freq="B")
    return pd.DataFrame(
        {
            "open": [1.0, 1.0, 1.0],
            "high": [1.1, 1.1, 1.1],
            "low": [0.9, 0.9, 0.9],
            "close": [1.0, 1.0, 1.0],
            "volume": [1000.0, 1000.0, 1000.0],
        },
        index=index,
    )


def test_yfinance_maps_share_class_symbols_and_restores_original_keys(monkeypatch):
    requested = []

    def fake_download(tickers, *, period):
        requested.extend(tickers)
        return {
            "BRK-B": _frame(),
            "BF-B": _frame(),
            "QQQ": _frame(),
        }, {
            "source": "yfinance",
            "requested": 3,
            "received": 3,
            "coverage": 1.0,
            "qqq_received": True,
            "failed_batches": [],
        }

    monkeypatch.setattr(providers, "download_price_map", fake_download)

    prices, diagnostics = providers.YFinancePriceProvider().download(
        ["BRK.B", "BF.B", "QQQ"], period="10y"
    )

    assert requested == ["BF-B", "BRK-B", "QQQ"]
    assert set(prices) == {"BF.B", "BRK.B", "QQQ"}
    assert diagnostics["requested"] == 3
    assert diagnostics["received"] == 3
    assert diagnostics["coverage"] == 1.0
    assert diagnostics["symbol_aliases_used"] == 2
    assert diagnostics["missing"] == []


def test_yfinance_reports_missing_symbols_using_original_notation(monkeypatch):
    def fake_download(tickers, *, period):
        return {}, {
            "source": "yfinance",
            "requested": len(tickers),
            "received": 0,
            "coverage": 0.0,
            "qqq_received": False,
            "failed_batches": [],
        }

    monkeypatch.setattr(providers, "download_price_map", fake_download)

    prices, diagnostics = providers.YFinancePriceProvider().download(
        ["BRK.B"], period="18mo"
    )

    assert prices == {}
    assert diagnostics["missing"] == ["BRK.B"]
    assert diagnostics["coverage"] == 0.0
