from __future__ import annotations

import pandas as pd
import yfinance as yf

import audit_inverse_etf_regime_scan as base
import audit_inverse_event_engine_v2 as v2


def fixed_extra_market(idx: pd.DatetimeIndex, start: str, end: str) -> pd.DataFrame:
    warm = str((pd.Timestamp(start) - pd.Timedelta(days=500)).date())
    dl_end = str((pd.Timestamp(end) + pd.Timedelta(days=15)).date())
    symbols = ['^VVIX','^SKEW','JNK','SHY','TIP','QQEW','XLK','XLU','KRE','XLF']
    raw = yf.download(symbols, start=warm, end=dl_end, auto_adjust=True, actions=False,
                      progress=False, threads=False, group_by='column')
    out = pd.DataFrame(index=idx)
    if raw.empty:
        return out
    if isinstance(raw.columns, pd.MultiIndex) and 'Close' in set(raw.columns.get_level_values(0)):
        c = raw['Close'].copy()
        c.index = base.norm_idx(c.index)
        c = c.reindex(idx).ffill(limit=2)
    else:
        return out

    def add(name: str, sym: str) -> None:
        if sym in c.columns:
            out[name] = pd.to_numeric(c[sym], errors='coerce')

    add('vvix','^VVIX'); add('skew','^SKEW')
    for sym in ['JNK','SHY','TIP','QQEW','XLK','XLU','KRE','XLF']:
        add(sym.lower(), sym)

    if 'vvix' in out:
        out['vvix_chg5'] = out['vvix'].pct_change(5)
        out['vvix_pct252'] = out['vvix'].rolling(252, min_periods=126).rank(pct=True)
    if 'skew' in out:
        out['skew_chg5'] = out['skew'].pct_change(5)
        out['skew_pct252'] = out['skew'].rolling(252, min_periods=126).rank(pct=True)
    if {'jnk','shy'} <= set(out.columns):
        out['jnk_shy_mom20'] = (out['jnk']/out['shy']).pct_change(20)
    if {'tip','shy'} <= set(out.columns):
        out['tip_shy_mom20'] = (out['tip']/out['shy']).pct_change(20)
    if 'qqew' in out:
        out['qqew_ret20'] = out['qqew'].pct_change(20)
    if {'xlk','xlu'} <= set(out.columns):
        out['xlk_xlu_mom20'] = (out['xlk']/out['xlu']).pct_change(20)
    if {'kre','xlf'} <= set(out.columns):
        out['kre_xlf_mom20'] = (out['kre']/out['xlf']).pct_change(20)
    return out


v2.extra_market = fixed_extra_market

if __name__ == '__main__':
    v2.main()
