from __future__ import annotations

import pandas as pd
import validate_rotation_analysis_gaps as base


def strict_eventize(df: pd.DataFrame, mask: pd.Series) -> pd.DataFrame:
    rows = []
    z = df.assign(_signal=mask.fillna(False).to_numpy(bool))
    for sector, g in z.groupby('sector', sort=False):
        g = g.sort_values('date').reset_index(drop=True)
        prev = False
        last = -10**9
        for i, r in g.iterrows():
            active = bool(r['_signal'])
            if active and not prev and i - last >= base.COOLDOWN:
                rows.append(r.drop(labels=['_signal']).to_dict())
                last = i
            prev = active
    return pd.DataFrame(rows)


base.eventize = strict_eventize

if __name__ == '__main__':
    base.main()
