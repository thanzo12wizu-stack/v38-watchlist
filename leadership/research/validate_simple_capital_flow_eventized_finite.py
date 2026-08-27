from __future__ import annotations

import numpy as np
import pandas as pd

import validate_simple_capital_flow_eventized as base


_orig_summarize = base.summarize
_orig_summarize_diff = base.summarize_diff


def _finite_frame(df: pd.DataFrame, value_col: str) -> pd.DataFrame:
    x = pd.to_numeric(df[value_col], errors="coerce")
    return df[np.isfinite(x.to_numpy(float))].copy()


def summarize(df, value_col, trading_dates, seed, extra_clusters=()):
    return _orig_summarize(_finite_frame(df, value_col), value_col, trading_dates, seed, extra_clusters)


def summarize_diff(df, value_col, group_col, hi, lo, trading_dates, seed, extra_clusters=()):
    return _orig_summarize_diff(_finite_frame(df, value_col), value_col, group_col, hi, lo, trading_dates, seed, extra_clusters)


base.summarize = summarize
base.summarize_diff = summarize_diff


if __name__ == "__main__":
    base.main()
