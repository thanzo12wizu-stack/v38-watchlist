from __future__ import annotations

import numpy as np
import pandas as pd

import audit_emerging_early_entry_grid as grid

# Keep the first pass focused on the eight non-redundant entry families.
# Rising-SMA50 variants are reserved for a second-pass robustness check if a nearby family survives.
grid.VARIANTS = {k: v for k, v in grid.VARIANTS.items() if not v.get("rise50")}


def fast_theme_score_series(peer_ctx, d, columns):
    di = peer_ctx["date_pos"].get(pd.Timestamp(d))
    if di is None:
        return pd.Series(np.nan, index=columns, dtype=float)
    arr = np.asarray(peer_ctx["best_score"][di], dtype=float)
    if len(arr) != len(columns):
        # Defensive fallback only if column order ever changes.
        out = pd.Series(np.nan, index=columns, dtype=float)
        for sym in columns:
            si = peer_ctx["stock_pos"].get(sym)
            if si is not None:
                x = float(arr[si])
                if np.isfinite(x):
                    out.at[sym] = x
        return out
    arr = arr.copy()
    arr[~np.isfinite(arr)] = np.nan
    return pd.Series(arr, index=columns, dtype=float)


grid.theme_score_series = fast_theme_score_series

if __name__ == "__main__":
    grid.main()
