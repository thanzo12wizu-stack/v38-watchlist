import pandas as pd

import build_v38_sleeve_refresh as refresh


def _frame(symbols, date="2026-08-31"):
    idx = pd.DatetimeIndex([pd.Timestamp(date)])
    op = pd.DataFrame({s: [100.0] for s in symbols}, index=idx)
    cl = pd.DataFrame({s: [101.0] for s in symbols}, index=idx)
    return op, cl


def test_small_normal_request_recovers_missing_symbol(monkeypatch):
    def base(symbols, start, end, batch_size=150):
        op, cl = _frame(["AAA"])
        return op, cl, {"requested": 2, "downloaded": 1, "failed_batches": 0}

    def chart(symbol, start=None):
        assert symbol == "CAKE"
        idx = pd.DatetimeIndex([pd.Timestamp("2026-08-31")])
        return pd.DataFrame(
            {"Open": [65.0], "High": [67.0], "Low": [64.0], "Close": [66.0], "Volume": [1_000_000]},
            index=idx,
        )

    monkeypatch.setattr(refresh, "_BASE_DOWNLOAD", base)
    monkeypatch.setattr(refresh, "download_yahoo_chart", chart)
    op, cl, quality = refresh.download_adjusted_ohlc_resilient(
        ["AAA", "CAKE"], "2026-08-28", "2026-09-01", 100
    )

    assert cl.at[pd.Timestamp("2026-08-31"), "CAKE"] == 66.0
    assert op.at[pd.Timestamp("2026-08-31"), "CAKE"] == 65.0
    assert quality["fallback_used"] == ["CAKE"]
    assert quality["fallback_failed"] == {}


def test_large_reset_request_never_uses_per_symbol_fallback(monkeypatch):
    called = {"chart": 0}

    def base(symbols, start, end, batch_size=150):
        op, cl = _frame(["AAA"])
        return op, cl, {"requested": len(symbols), "downloaded": 1, "failed_batches": 0}

    def chart(symbol, start=None):
        called["chart"] += 1
        raise AssertionError("large Reset route must not use per-symbol fallback")

    monkeypatch.setattr(refresh, "_BASE_DOWNLOAD", base)
    monkeypatch.setattr(refresh, "download_yahoo_chart", chart)
    symbols = [f"T{i}" for i in range(51)]
    refresh.download_adjusted_ohlc_resilient(symbols, "2026-08-28", "2026-09-01", 100)
    assert called["chart"] == 0
