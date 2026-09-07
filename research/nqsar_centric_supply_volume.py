from __future__ import annotations

import argparse, json
from pathlib import Path

import numpy as np
import pandas as pd

from research import nqsar_centric_broad_scan as scan
from research import nqsar_centric_broad_scan_runner as _runner

VARIANTS = [
    'WEEK_BULL_RS63_CONTROL','WEEK_BULL_PRICE_TIGHT','WEEK_BULL_SUPPLY_DRY','WEEK_BULL_NET_ACCUM',
    'WEEK_BULL_WEEKLY_TIGHT','WEEK_BULL_ONEIL_COMPOSITE','WEEK_BULL_VOL_DRY5_IGNITE','WEEK_BULL_VOL_DRY10_IGNITE'
]


def features(m):
    c,h,l,v=m['close'],m['high'],m['low'],m['volume']; ret=c.pct_change(fill_method=None)
    tr=np.maximum.reduce([(h-l).to_numpy(float),(h-c.shift(1)).abs().to_numpy(float),(l-c.shift(1)).abs().to_numpy(float)])
    tr=pd.DataFrame(tr,index=c.index,columns=c.columns)
    tr5=tr.shift(1).rolling(5,min_periods=4).mean(); tr20=tr.shift(1).rolling(20,min_periods=12).mean(); trratio=tr5/tr20.replace(0,np.nan)
    pc=c.shift(1); cr5=pc.rolling(5,min_periods=4).max()/pc.rolling(5,min_periods=4).min().replace(0,np.nan)-1
    pv20=v.shift(1).rolling(20,min_periods=12).mean(); pv5=v.shift(1).rolling(5,min_periods=4).mean(); pv10=v.shift(1).rolling(10,min_periods=7).mean()
    down=v.where(ret<0).shift(1); cnt=(ret<0).shift(1).rolling(10,min_periods=7).sum(); downmean=down.rolling(10,min_periods=7).sum()/cnt.replace(0,np.nan); downratio=downmean/pv20.replace(0,np.nan)
    rvol=v/pv20.replace(0,np.nan); accum=((ret>=.01)&(rvol>=1.2)).shift(1).rolling(20,min_periods=12).sum(); dist=((ret<=-.01)&(rvol>=1.2)).shift(1).rolling(20,min_periods=12).sum(); net=accum-dist
    # Completed-week features released at actual final session of each week, then carried forward.
    p=c.index.to_period('W-FRI'); wc=c.groupby(p).last(); wv=v.groupby(p).sum(min_count=1); actual=pd.Series(c.index,index=p).groupby(level=0).max().reindex(wc.index); wix=pd.DatetimeIndex(actual.to_numpy()); wc.index=wix; wv.index=wix
    wcr=wc.rolling(3,min_periods=3).max()/wc.rolling(3,min_periods=3).min().replace(0,np.nan)-1; wvr=wv.rolling(3,min_periods=3).mean()/wv.rolling(10,min_periods=7).mean().replace(0,np.nan)
    wcr=wcr.reindex(c.index).ffill(); wvr=wvr.reindex(c.index).ffill()
    return {'trratio':trratio,'cr5':cr5,'downratio':downratio,'net':net,'rvol':rvol,'dry5':pv5/pv20.replace(0,np.nan),'dry10':pv10/pv20.replace(0,np.nan),'wcr':wcr,'wvr':wvr}


def make_score(orig, f):
    def score(d,m,variant):
        base=orig(d,m,'WEEK_BULL_STRUCT_RS63')
        if variant=='WEEK_BULL_RS63_CONTROL': return base
        cond={
            'WEEK_BULL_PRICE_TIGHT':(f['trratio'].loc[d]<=.75)&(f['cr5'].loc[d]<=.06),
            'WEEK_BULL_SUPPLY_DRY':f['downratio'].loc[d]<=.80,
            'WEEK_BULL_NET_ACCUM':f['net'].loc[d]>=1,
            'WEEK_BULL_WEEKLY_TIGHT':(f['wcr'].loc[d]<=.08)&(f['wvr'].loc[d]<=.85),
            'WEEK_BULL_ONEIL_COMPOSITE':(f['trratio'].loc[d]<=.75)&(f['cr5'].loc[d]<=.06)&(f['downratio'].loc[d]<=.80)&(f['net'].loc[d]>=1)&(f['wcr'].loc[d]<=.08)&(f['wvr'].loc[d]<=.85),
            'WEEK_BULL_VOL_DRY5_IGNITE':(f['dry5'].loc[d]<=.75)&(f['rvol'].loc[d]>=1.20),
            'WEEK_BULL_VOL_DRY10_IGNITE':(f['dry10'].loc[d]<=.85)&(f['rvol'].loc[d]>=1.20),
        }[variant].fillna(False)
        return [s for s in base if bool(cond.get(s,False))]
    return score


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--root',default='.'); ap.add_argument('--output',required=True); ap.add_argument('--batch-size',type=int,default=100); a=ap.parse_args(); root=Path(a.root); out=root/a.output; out.mkdir(parents=True,exist_ok=True)
    symbols,bio=scan.audit.load_universe(root/'universe.csv'); warm=str((scan.START-pd.Timedelta(days=1600)).date()); end='2026-09-05'
    ohlcv,diag=scan.audit.download_ohlcv(symbols,warm,end,a.batch_size)
    if diag['coverage']<.85: raise RuntimeError(diag)
    m=scan.build_inputs(ohlcv,bio); f=features(m); nq=scan.audit.market_nqsar(str((scan.START-pd.Timedelta(days=120)).date()),end).reindex(m['close'].index).ffill(limit=2); idx=m['close'].index[(m['close'].index>=scan.START)&(m['close'].index<=scan.END)]
    orig=scan.score_mask; scan.score_mask=make_score(orig,f); rows=[]
    try:
        for v in VARIANTS:
            print('SIM',v,flush=True); r=scan.simulate(idx,m,nq,v); sl=scan.slices(r['equity'],r['exposure']); rec={'variant':v}
            for p,mm in sl.items():
                for k,val in mm.items():rec[f'{p}_{k}']=val
            rows.append(rec)
    finally: scan.score_mask=orig
    df=pd.DataFrame(rows); df.to_csv(out/'supply_volume_metrics.csv',index=False)
    summary={'method':'old ONeil/volume-sequence operational thresholds over Stock Weekly NQSAR Bull + structural trend; common market mode/exits; Top12 then DDV20 no-refill','coverage':diag,'variants':VARIANTS}
    (out/'summary.json').write_text(json.dumps(scan.safe(summary),ensure_ascii=False,indent=2)); print('DONE_SUPPLY',flush=True)

if __name__=='__main__': main()
