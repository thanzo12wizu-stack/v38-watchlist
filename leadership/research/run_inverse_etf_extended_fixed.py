from __future__ import annotations

import io

import pandas as pd
import requests

import audit_inverse_etf_extended as audit


def fixed_norm_idx(idx) -> pd.DatetimeIndex:
    x = pd.DatetimeIndex(pd.to_datetime(idx))
    if x.tz is not None:
        x = x.tz_convert(None)
    return x.normalize()


def fixed_fred_series(series: str, idx: pd.DatetimeIndex, lag_sessions: int) -> pd.Series:
    start = (pd.Timestamp(idx.min()) - pd.Timedelta(days=550)).strftime('%Y-%m-%d')
    end = (pd.Timestamp(idx.max()) + pd.Timedelta(days=15)).strftime('%Y-%m-%d')
    url = f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}&cosd={start}&coed={end}'
    r = requests.get(url, timeout=45)
    r.raise_for_status()
    z = pd.read_csv(io.StringIO(r.text))
    dcol = 'DATE' if 'DATE' in z.columns else 'observation_date'
    z[dcol] = pd.to_datetime(z[dcol])
    valcol = [c for c in z.columns if c != dcol][0]
    s = pd.Series(pd.to_numeric(z[valcol], errors='coerce').to_numpy(), index=fixed_norm_idx(z[dcol]), dtype=float)
    s = s[~s.index.duplicated(keep='last')].sort_index().reindex(idx).ffill(limit=15)
    if lag_sessions:
        s = s.shift(lag_sessions)
    return s


def fixed_make_family_flags(feat: pd.DataFrame):
    family, cap, thresholds = audit._original_make_family_flags(feat)
    family['risk_rel'] = (
        audit.flag_low(feat, 'qew_qqq_mom20', .33)
        | audit.flag_low(feat, 'iwm_qqq_mom20', .33)
        | audit.flag_low(feat, 'soxx_qqq_mom20', .33)
    )
    family['credit'] = (
        audit.flag_low(feat, 'hyg_lqd_ext_mom5', .33)
        | audit.flag_low(feat, 'hyg_lqd_ext_mom20', .33)
        | audit.flag_low(feat, 'hyg_ret20', .33)
    )
    return family.fillna(False), cap.fillna(False), thresholds


audit.norm_idx = fixed_norm_idx
audit.fred_series = fixed_fred_series
audit._original_make_family_flags = audit.make_family_flags
audit.make_family_flags = fixed_make_family_flags

if __name__ == '__main__':
    audit.main()
