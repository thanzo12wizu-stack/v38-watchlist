from __future__ import annotations

import sys

import numpy as np
import pandas as pd

import audit_rotation_exit_overlays as core


def post_exit_diagnostics_fixed(tdf: pd.DataFrame, closes: pd.DataFrame, idx: pd.DatetimeIndex) -> pd.DataFrame:
    if tdf.empty:
        return tdf
    analysis_close = closes.reindex(idx)
    pos = {pd.Timestamp(d): i for i, d in enumerate(idx)}
    out = []
    for _, r0 in tdf.iterrows():
        r = r0.to_dict()
        d = pd.Timestamp(r["exit_date"])
        sym = str(r["symbol"])
        i = pos.get(d)
        ep = float(r["exit_price"])
        for h in (20, 40, 63):
            val = np.nan
            if i is not None and sym in analysis_close.columns and ep > 0:
                future = pd.to_numeric(
                    analysis_close.iloc[i + 1:min(len(analysis_close), i + 1 + h)][sym],
                    errors="coerce",
                ).dropna()
                if len(future):
                    val = float(future.max() / ep - 1.0)
            r[f"post_exit_max_{h}d"] = val
        out.append(r)
    return pd.DataFrame(out)


core.post_exit_diagnostics = post_exit_diagnostics_fixed

if __name__ == "__main__":
    core.main()
