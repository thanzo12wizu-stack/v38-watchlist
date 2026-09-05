from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

import pandas as pd
import yfinance as yf

import validate_theme56_rotation_retrospective as base
from rotation_theme56_holdings_expansion import clean_symbol


def _extract(raw: pd.DataFrame, lookup: str, field: str) -> pd.Series | None:
    if raw is None or raw.empty:
        return None
    if isinstance(raw.columns, pd.MultiIndex):
        l0 = {str(x) for x in raw.columns.get_level_values(0)}
        l1 = {str(x) for x in raw.columns.get_level_values(1)}
        part = None
        if lookup in l0:
            part = raw[lookup]
        elif lookup in l1:
            part = raw.xs(lookup, axis=1, level=1)
        if part is None or field not in part.columns:
            return None
        s = pd.to_numeric(part[field], errors='coerce')
    else:
        if field not in raw.columns:
            return None
        s = pd.to_numeric(raw[field], errors='coerce')
    s.index = pd.to_datetime(s.index).tz_localize(None)
    return s.dropna()


def _download(batch: list[tuple[str, str]], start: str, end: str) -> tuple[dict[str, pd.Series], dict[str, pd.Series]]:
    lookups = list(dict.fromkeys(y for _, y in batch))
    raw = yf.download(
        tickers=lookups,
        start=start,
        end=end,
        auto_adjust=True,
        actions=False,
        progress=False,
        group_by='ticker',
        threads=False,
        timeout=30,
    )
    closes: dict[str, pd.Series] = {}
    volumes: dict[str, pd.Series] = {}
    for canonical, lookup in batch:
        c = _extract(raw, lookup, 'Close')
        v = _extract(raw, lookup, 'Volume')
        if c is not None and len(c) >= 2:
            closes[canonical] = c
        if v is not None and len(v) >= 2:
            volumes[canonical] = v
    return closes, volumes


def _attempt(batch: list[tuple[str, str]], start: str, end: str, retries: int = 3):
    last = None
    for attempt in range(retries):
        try:
            return _download(batch, start, end)
        except Exception as exc:
            last = repr(exc)
            time.sleep(2 ** attempt)
    return {}, {}, last


def main() -> None:
    ap = argparse.ArgumentParser()
    for a in ('config', 'base', 'expansion', 'fallback', 'dram', 'output'):
        ap.add_argument('--' + a.replace('_', '-'), dest=a, type=Path, required=True)
    ap.add_argument('--start', default='2022-01-01')
    ap.add_argument('--end', default='2026-09-05')
    ap.add_argument('--shard', type=int, required=True)
    ap.add_argument('--shards', type=int, required=True)
    ap.add_argument('--batch-size', type=int, default=20)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    cfg = json.loads(args.config.read_text(encoding='utf-8'))
    themes = [str(x['ticker']).upper() for x in cfg['themes']]
    members = base.norm_members([
        (args.base, 'BASE_EXACT'),
        (args.expansion, 'EXPANSION_EXACT'),
        (args.dram, 'DRAM_SUPPLEMENT'),
        (args.fallback, 'VALIDATED_FALLBACK'),
    ])
    members = members[members.sector_etf.isin(themes)]
    requested = sorted(set(members.symbol) | set(themes) | {'SPY', *base.SECTORS})
    shard_symbols = [s for i, s in enumerate(requested) if i % args.shards == args.shard]

    pairs = []
    invalid = []
    for s in shard_symbols:
        y = clean_symbol(s)
        if y:
            pairs.append((s, y))
        else:
            invalid.append(s)

    close_cols: dict[str, pd.Series] = {}
    volume_cols: dict[str, pd.Series] = {}
    errors = []
    for pos in range(0, len(pairs), args.batch_size):
        batch = pairs[pos:pos + args.batch_size]
        result = _attempt(batch, args.start, args.end)
        if len(result) == 3:
            c, v, err = result
            errors.append({'batch_start': pos, 'symbols': [x[0] for x in batch], 'error': err})
        else:
            c, v = result
        close_cols.update(c)
        volume_cols.update(v)
        print(f'PASS1 shard={args.shard} {min(pos + args.batch_size, len(pairs))}/{len(pairs)} close={len(close_cols)}', flush=True)

    missing = [(c, y) for c, y in pairs if c not in close_cols or c not in volume_cols]
    # Salvage partial batch failures with small groups. This is intentionally bounded.
    for pos in range(0, len(missing), 5):
        batch = missing[pos:pos + 5]
        result = _attempt(batch, args.start, args.end, retries=2)
        if len(result) == 3:
            c, v, err = result
            errors.append({'salvage_start': pos, 'symbols': [x[0] for x in batch], 'error': err})
        else:
            c, v = result
        close_cols.update(c)
        volume_cols.update(v)
        if batch:
            time.sleep(0.35)

    common = sorted(set(close_cols) & set(volume_cols))
    close = pd.DataFrame({s: close_cols[s] for s in common}).sort_index()
    volume = pd.DataFrame({s: volume_cols[s] for s in common}).sort_index()
    close.to_parquet(args.output / f'close_{args.shard:02d}.parquet')
    volume.to_parquet(args.output / f'volume_{args.shard:02d}.parquet')

    missing_final = sorted(set(shard_symbols) - set(common))
    diag = {
        'schema': 1,
        'research_only': True,
        'shard': args.shard,
        'shards': args.shards,
        'requested': len(shard_symbols),
        'valid_lookup': len(pairs),
        'downloaded_common_close_volume': len(common),
        'coverage': len(common) / len(shard_symbols) if shard_symbols else None,
        'invalid_normalization': invalid,
        'missing': missing_final,
        'errors': errors,
        'rows': int(len(close)),
        'start': str(close.index.min().date()) if len(close) else None,
        'end': str(close.index.max().date()) if len(close) else None,
    }
    (args.output / f'diagnostic_{args.shard:02d}.json').write_text(json.dumps(diag, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: diag[k] for k in ('shard','requested','downloaded_common_close_volume','coverage','rows','start','end')}, indent=2))
    if not common:
        raise SystemExit('shard returned no usable close/volume data')


if __name__ == '__main__':
    main()
