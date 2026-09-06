import numpy as np
import pandas as pd

import build_v38_early1_live as e


def synthetic_frames(n_days=110, n_symbols=24):
    idx = pd.bdate_range("2026-01-02", periods=n_days)
    symbols = [f"S{i:02d}" for i in range(n_symbols)]
    close = pd.DataFrame(index=idx, columns=symbols, dtype=float)
    volume = pd.DataFrame(2_000_000.0, index=idx, columns=symbols)
    for j, sym in enumerate(symbols):
        # Ordered but smooth trends create a stable cross-section.
        base = 20.0 + j
        slope = 0.0008 + j * 0.00008
        close[sym] = base * np.exp(np.arange(n_days) * slope)
    # Make the last symbol freshly accelerate only near the end.
    sym = symbols[-1]
    close.loc[idx[-8]:, sym] *= np.linspace(1.0, 1.35, 8)
    return close, volume


def test_score_formula_and_ddv20_filter():
    close, volume = synthetic_frames()
    asof = str(close.index[-1].date())
    out = e.calculate_early1(close, volume, list(close.columns), set(), asof)
    assert out["status"] == "READY"
    assert out["strategy"] == "RS21_HIGH_ACCEL"
    assert out["max_slots"] == 1
    assert out["max_hold_sessions"] == 10
    assert all(row["daily_dollar_volume_m"] >= 20 for row in out["candidates"])
    for row in out["candidates"][:5]:
        expected = 0.50 * row["rs21"] + 0.25 * row["high63_pct"] + 0.25 * row["acc21_pct"]
        assert abs(row["score"] - expected) < 1e-9


def test_active5_is_required():
    close, volume = synthetic_frames()
    asof = str(close.index[-1].date())
    out = e.calculate_early1(close, volume, list(close.columns), set(), asof)
    assert all(row["active5"] is True for row in out["candidates"])


def test_structural_exclusion_removes_symbol():
    close, volume = synthetic_frames()
    asof = str(close.index[-1].date())
    candidate = e.calculate_early1(close, volume, list(close.columns), set(), asof)
    if not candidate["candidates"]:
        return
    top = candidate["candidates"][0]["ticker"]
    excluded = e.calculate_early1(close, volume, list(close.columns), {top}, asof)
    assert top not in [row["ticker"] for row in excluded["candidates"]]
