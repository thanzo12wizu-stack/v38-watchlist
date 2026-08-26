from __future__ import annotations

import importlib.util
from pathlib import Path
import pandas as pd

p = Path('.github/scripts/oneoff_mc_layer_validation_v2.py')
spec = importlib.util.spec_from_file_location('v2', p)
v2 = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(v2)


def exact_metric_frames(c: pd.DataFrame):
    c = c.apply(pd.to_numeric, errors='coerce')
    ma10=c.rolling(10).mean(); ma20=c.rolling(20).mean(); ma50=c.rolling(50).mean(); ma200=c.rolling(200).mean()
    hi252=c.rolling(252, min_periods=200).max()
    dd=c/hi252-1.0

    def bm(lhs, rhs, op):
        return (op(lhs,rhs).where(lhs.notna() & rhs.notna()).astype(float) * 100.0)
    def ret(n):
        prev=c.shift(n)
        return bm(c,prev,lambda a,b:(a/b-1.0)>0)
    return {
        'ret5':ret(5),'ret21':ret(21),'ret63':ret(63),'ret252':ret(252),
        'above10':bm(c,ma10,lambda a,b:a>b),'above20':bm(c,ma20,lambda a,b:a>b),
        'above50':bm(c,ma50,lambda a,b:a>b),'above200':bm(c,ma200,lambda a,b:a>b),
        'ma20_gt_50':bm(ma20,ma50,lambda a,b:a>b),'ma50_gt_200':bm(ma50,ma200,lambda a,b:a>b),
        'dd_score':((dd+0.30)/0.25*100.0).clip(0.0,100.0),
        'within10':bm(dd, pd.DataFrame(-0.10,index=dd.index,columns=dd.columns), lambda a,b:a>=b),
    }

v2.corrected_metric_frames = exact_metric_frames
v2.base.metric_frames = exact_metric_frames

if __name__ == '__main__':
    v2.replication_gate()
    v2.base.main()
