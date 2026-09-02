from __future__ import annotations

import pandas as pd
import audit_inverse_etf_extended as audit


def fixed_norm_idx(idx) -> pd.DatetimeIndex:
    x = pd.DatetimeIndex(pd.to_datetime(idx))
    if x.tz is not None:
        x = x.tz_convert(None)
    return x.normalize()


audit.norm_idx = fixed_norm_idx

if __name__ == '__main__':
    audit.main()
