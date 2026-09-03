from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

import audit_major_leader_entry_delay as delay
import audit_radar_cohort_discriminator as audit


def event_pack_strict(events: pd.DataFrame, selections: dict[pd.Timestamp, list[str]], close: pd.DataFrame, k: int) -> dict[str, Any]:
    """Count an entry as early only if the leader had never crossed the cutoff before selection.

    This prevents a leader that already ran +50%, pulled back to +20%, and was selected then
    from being mislabeled as a +20% early capture.
    """
    if events.empty:
        return {"n": 0}
    rows: list[dict[str, Any]] = []
    idx = close.index
    pos = {pd.Timestamp(d): i for i, d in enumerate(idx)}
    for ev in events.itertuples(index=False):
        sym = str(ev.symbol)
        a = pd.Timestamp(ev.anchor_date)
        e = pd.Timestamp(ev.final_date)
        ap = delay.px(close, a, sym, None)
        if ap is None or a not in pos:
            continue
        found = None
        gain = np.nan
        peak_gain = -np.inf
        peak_at_selection = np.nan
        for d0 in idx[(idx >= a) & (idx <= e)]:
            d = pd.Timestamp(d0)
            cp = delay.px(close, d, sym, None)
            if cp is None:
                continue
            g = float(cp / ap - 1.0)
            peak_gain = max(peak_gain, g)
            if sym in selections.get(d, [])[:k]:
                found = d
                gain = g
                peak_at_selection = peak_gain
                break
        rows.append({
            "captured": found is not None,
            "gain": gain,
            "peak_gain_before_selection": peak_at_selection,
        })
    x = pd.DataFrame(rows)
    g = pd.to_numeric(x["gain"], errors="coerce")
    pg = pd.to_numeric(x["peak_gain_before_selection"], errors="coerce")
    return {
        "n": int(len(x)),
        "captured_n": int(x["captured"].sum()),
        "captured_rate": float(x["captured"].mean()) if len(x) else None,
        "within_20pct_all": float((pg <= 0.20).fillna(False).mean()) if len(x) else None,
        "within_30pct_all": float((pg <= 0.30).fillna(False).mean()) if len(x) else None,
        "within_50pct_all": float((pg <= 0.50).fillna(False).mean()) if len(x) else None,
        "median_first_gain_captured": float(g[x["captured"]].median()) if x["captured"].any() else None,
        "median_peak_gain_before_selection": float(pg[x["captured"]].median()) if x["captured"].any() else None,
    }


audit.event_pack = event_pack_strict

if __name__ == "__main__":
    audit.main()
