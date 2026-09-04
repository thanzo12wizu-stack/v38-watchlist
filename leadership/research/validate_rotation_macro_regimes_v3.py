from __future__ import annotations
import json
import pandas as pd
import validate_rotation_macro_regimes_v2 as base

_original=base.build_macro

def build_macro_v3(dates,start,end,df):
    out,meta=_original(dates,start,end,df)
    try:
        x=base.fred_series('VIXCLS',start,end)
        out['VIX']=x.reindex(dates).ffill(limit=5)
        meta['VIXCLS']={'status':'READY','n':int(x.notna().sum())}
    except Exception as e:
        meta['VIXCLS']={'status':'ERROR','error':str(e)}
    return out,meta

base.build_macro=build_macro_v3

if __name__=='__main__':
    base.main()
