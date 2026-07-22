import pickle

import pandas as pd

from intelligence_engine.preflight import run


def _frame(mult=1.0):
    idx = pd.date_range("2025-01-01", periods=260, freq="B")
    close = pd.Series(range(100, 360), index=idx, dtype=float) * mult
    return pd.DataFrame({
        "open": close * 0.99,
        "high": close * 1.01,
        "low": close * 0.98,
        "close": close,
        "volume": 1_000_000,
    }, index=idx)


def test_preflight_runs_without_fundamental_columns(tmp_path):
    universe = tmp_path / "universe.csv"
    universe.write_text("ticker,sector,industry\nAAA,Tech,Software\nBBB,Tech,Hardware\n", encoding="utf-8")
    prices = tmp_path / "prices.pkl"
    with prices.open("wb") as fh:
        pickle.dump({"QQQ": _frame(), "AAA": _frame(1.1), "BBB": _frame(0.9)}, fh)
    report = run(universe, prices)
    assert report["status"] == "OK"
    assert report["symbols"] == 2
