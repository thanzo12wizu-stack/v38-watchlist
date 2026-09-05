from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

import validate_theme56_rotation_retrospective_v3 as v3

base = v3.base


def _read_cache(cache_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    cfiles = sorted(cache_dir.rglob('close_*.parquet'))
    vfiles = sorted(cache_dir.rglob('volume_*.parquet'))
    if not cfiles or not vfiles:
        raise RuntimeError(f'price shard parquet files missing under {cache_dir}')
    close = pd.concat([pd.read_parquet(p) for p in cfiles], axis=1)
    volume = pd.concat([pd.read_parquet(p) for p in vfiles], axis=1)
    close = close.loc[:, ~close.columns.duplicated()].sort_index()
    volume = volume.loc[:, ~volume.columns.duplicated()].sort_index()
    common = sorted(set(close.columns) & set(volume.columns))
    close = close.reindex(columns=common)
    volume = volume.reindex(columns=common)
    diagnostics = []
    for p in sorted(cache_dir.rglob('diagnostic_*.json')):
        try:
            diagnostics.append(json.loads(p.read_text(encoding='utf-8')))
        except Exception:
            pass
    return close, volume, {'shards': diagnostics, 'cached_common': len(common)}


def safe_parent_map(etf_close: pd.DataFrame) -> pd.DataFrame:
    themes = [c for c in etf_close.columns if c not in {'SPY', *base.SECTORS}]
    sectors = [c for c in base.SECTORS if c in etf_close.columns]
    rets = etf_close.pct_change(fill_method=None)
    ret20 = etf_close.pct_change(20, fill_method=None)
    rows = []
    for t in themes:
        if t not in rets.columns or not sectors:
            continue
        corr = pd.DataFrame({s: rets[t].rolling(126, min_periods=90).corr(rets[s]) for s in sectors})
        valid = corr.notna().any(axis=1)
        parent = pd.Series(index=corr.index, dtype=object)
        best = pd.Series(index=corr.index, dtype=float)
        if valid.any():
            parent.loc[valid] = corr.loc[valid].idxmax(axis=1)
            best.loc[valid] = corr.loc[valid].max(axis=1)
        for dt in corr.index[valid]:
            p = parent.at[dt]
            gap = np.nan
            if isinstance(p, str) and p in ret20.columns and pd.notna(ret20.at[dt, t]) and pd.notna(ret20.at[dt, p]):
                gap = ret20.at[dt, t] - ret20.at[dt, p]
            rows.append({'date': dt, 'ticker': t, 'parent': p, 'parent_corr126': best.at[dt], 'theme_parent_ret20_gap': gap})
    return pd.DataFrame(rows, columns=['date','ticker','parent','parent_corr126','theme_parent_ret20_gap'])


def main() -> None:
    mini = argparse.ArgumentParser(add_help=False)
    mini.add_argument('--cache-dir', type=Path, required=True)
    known, rest = mini.parse_known_args()
    close, volume, cache_diag = _read_cache(known.cache_dir)

    def cached_download(symbols: list[str], start: str, end: str, batch_size: int):
        requested = list(dict.fromkeys(symbols))
        c = close.reindex(columns=[s for s in requested if s in close.columns])
        v = volume.reindex(columns=[s for s in requested if s in volume.columns])
        common = sorted(set(c.columns) & set(v.columns))
        c = c.reindex(columns=common)
        v = v.reindex(columns=common)
        lo = pd.Timestamp(start)
        hi = pd.Timestamp(end)
        c = c[(c.index >= lo) & (c.index < hi)]
        v = v[(v.index >= lo) & (v.index < hi)]
        diag = {
            'source': 'SHARDED_RESEARCH_PRICE_CACHE',
            'requested': len(requested),
            'downloaded_common_ohlcv': len(common),
            'coverage': len(common) / len(requested) if requested else None,
            'missing': sorted(set(requested) - set(common)),
            'rows': int(len(c)),
            'start': str(c.index.min().date()) if len(c) else None,
            'end': str(c.index.max().date()) if len(c) else None,
            'shard_summary': cache_diag,
        }
        return {'close': c, 'volume': v}, diag

    base.pl.download_ohlcv = cached_download
    base.parent_map = safe_parent_map
    sys.argv = [sys.argv[0], *rest]
    base.main()


if __name__ == '__main__':
    main()
