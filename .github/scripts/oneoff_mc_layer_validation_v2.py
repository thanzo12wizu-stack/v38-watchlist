from __future__ import annotations

import inspect
import numpy as np
import pandas as pd

import build_dashboard as d
import importlib.util
from pathlib import Path

base_path = Path('.github/scripts/oneoff_mc_layer_validation.py')
spec = importlib.util.spec_from_file_location('mc_layer_base', base_path)
base = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(base)


def bool_metric(lhs: pd.DataFrame, rhs: pd.DataFrame, op) -> pd.DataFrame:
    valid = lhs.notna() & rhs.notna()
    out = op(lhs, rhs).astype(float) * 100.0
    return out.where(valid)


def corrected_metric_frames(c: pd.DataFrame) -> dict[str, pd.DataFrame]:
    c = c.apply(pd.to_numeric, errors='coerce')
    ma10 = c.rolling(10, min_periods=10).mean()
    ma20 = c.rolling(20, min_periods=20).mean()
    ma50 = c.rolling(50, min_periods=50).mean()
    ma200 = c.rolling(200, min_periods=200).mean()
    hi252 = c.rolling(252, min_periods=252).max()
    dd = c / hi252 - 1.0

    def ret(n: int) -> pd.DataFrame:
        prev = c.shift(n)
        return bool_metric(c, prev, lambda a, b: (a / b - 1.0) > 0)

    return {
        'ret5': ret(5),
        'ret21': ret(21),
        'ret63': ret(63),
        'ret252': ret(252),
        'above10': bool_metric(c, ma10, lambda a,b: a > b),
        'above20': bool_metric(c, ma20, lambda a,b: a > b),
        'above50': bool_metric(c, ma50, lambda a,b: a > b),
        'above200': bool_metric(c, ma200, lambda a,b: a > b),
        'ma20_gt_50': bool_metric(ma20, ma50, lambda a,b: a > b),
        'ma50_gt_200': bool_metric(ma50, ma200, lambda a,b: a > b),
        'dd_score': ((dd + 0.30) / 0.25 * 100.0).clip(0.0, 100.0),
        'within10': bool_metric(c, hi252 * 0.90, lambda a,b: a >= b),
    }


base.metric_frames = corrected_metric_frames

# Fingerprint the production metric construction if replication still fails.
def replication_gate() -> None:
    import json
    state = json.loads(Path('state.json').read_text(encoding='utf-8'))
    hist = d._fetch_mc_long_history(asof=state.get('date'))
    c = d._mc_frame_from_macro(hist)
    metrics = corrected_metric_frames(c)
    prod = d.mri_frame(hist)
    v0 = prod[0] if isinstance(prod, tuple) else prod
    raw = base.raw_from_concepts(metrics, {t:[t] for t in d.MC_MARKET_TICKERS})
    re, _, _, _ = d._mc_temperature_from_raw(raw)
    common = pd.concat([pd.to_numeric(v0,errors='coerce').rename('prod'), pd.to_numeric(re,errors='coerce').rename('re')],axis=1).dropna()
    latest = abs(float(common.iloc[-1,0]-common.iloc[-1,1]))
    mae = float((common['prod']-common['re']).abs().mean())
    maxe = float((common['prod']-common['re']).abs().max())
    print(f'REPLICATION_GATE latest_abs={latest:.6f} mae={mae:.6f} max={maxe:.6f} n={len(common)}')
    if latest > 0.05 or mae > 0.05 or maxe > 0.25:
        src = inspect.getsource(d.mri_frame).splitlines()
        print('PRODUCTION_MC_SOURCE_FINGERPRINT')
        for i,line in enumerate(src):
            if any(tok in line for tok in ('p[', 'pct_change', 'rolling(', 'hi252', 'dd_score', 'within10', 'score_keys', '_mc_participation', 'raw =')):
                lo=max(0,i-1); hi=min(len(src),i+2)
                for j in range(lo,hi): print(f'{j+1:03d}: {src[j]}')
        raise SystemExit('V0 replication gate failed; V1/V2 remain invalid')


if __name__ == '__main__':
    replication_gate()
    base.main()
