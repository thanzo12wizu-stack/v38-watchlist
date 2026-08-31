import importlib
from pathlib import Path

import numpy as np
import pandas as pd

import sitecustomize as cachemod


def _raw(symbol: str, dates, opens, closes, adjusted):
    part = pd.DataFrame(
        {"Open": opens, "Close": closes, "Adj Close": adjusted},
        index=pd.to_datetime(dates),
    )
    return pd.concat({symbol: part}, axis=1)


def test_extract_adjusted_ohlc_uses_adj_close_factor():
    raw = _raw("AAA", ["2026-08-28"], [100.0], [110.0], [55.0])
    open_, close = cachemod._extract_adjusted_ohlc(raw, ["AAA"])
    assert close.loc[pd.Timestamp("2026-08-28"), "AAA"] == 55.0
    assert open_.loc[pd.Timestamp("2026-08-28"), "AAA"] == 50.0


def test_cache_merges_batches_and_serves_yfinance_shape(tmp_path):
    old = cachemod.CACHE_PATH
    cachemod.CACHE_PATH = tmp_path / "shared.pkl"
    try:
        cachemod._merge_cache(
            _raw("AAA", ["2026-08-27", "2026-08-28"], [100, 102], [110, 112], [55, 56]),
            ["AAA"], "2026-08-27", "2026-08-29",
        )
        cachemod._merge_cache(
            _raw("BBB", ["2026-08-27", "2026-08-28"], [20, 21], [20, 21], [20, 21]),
            ["BBB"], "2026-08-27", "2026-08-29",
        )
        out = cachemod._serve_cache(
            ["AAA", "BBB"], start="2026-08-27", end="2026-08-29", group_by="ticker"
        )
        assert isinstance(out.columns, pd.MultiIndex)
        assert set(out.columns.get_level_values(0)) == {"AAA", "BBB"}
        assert out["AAA"].loc[pd.Timestamp("2026-08-28"), "Close"] == 56.0
        assert out["AAA"].loc[pd.Timestamp("2026-08-28"), "Open"] == 51.0
        assert out["BBB"].loc[pd.Timestamp("2026-08-28"), "Open"] == 21.0
    finally:
        cachemod.CACHE_PATH = old


def test_sitecustomize_is_targeted_only_to_v38_live_builders():
    assert cachemod.TARGET_STRICT == "build_v38_strict_loo_live.py"
    assert cachemod.TARGET_SLEEVE == "build_v38_sleeve_live.py"
    assert Path(__file__).name not in {cachemod.TARGET_STRICT, cachemod.TARGET_SLEEVE}
