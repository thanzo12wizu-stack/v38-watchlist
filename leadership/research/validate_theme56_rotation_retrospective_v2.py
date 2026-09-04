from __future__ import annotations

import pandas as pd
import validate_theme56_rotation_retrospective as base


def strict_eventize(panel: pd.DataFrame, mask: pd.Series) -> pd.DataFrame:
    z = panel.assign(_s=mask.fillna(False).to_numpy(bool))
    rows = []
    for ticker, g in z.groupby('ticker', sort=False):
        g = g.sort_values('date').reset_index(drop=True)
        prev = False
        last = -10**9
        for i, r in g.iterrows():
            active = bool(r['_s'])
            if active and not prev and i - last >= base.COOLDOWN:
                rows.append(r.drop(labels=['_s']).to_dict())
                last = i
            prev = active
    return pd.DataFrame(rows)


base.eventize = strict_eventize

if __name__ == '__main__':
    base.main()
