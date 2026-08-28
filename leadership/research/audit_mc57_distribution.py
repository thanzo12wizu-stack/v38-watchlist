from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

import audit_rsi30_mc_nqsar as state_audit
import validate_rsi_divergence_strong as rsi_base

BANDS = [(-np.inf, 20, 'LT20'), (20, 35, '20_35'), (35, 50, '35_50'), (50, 65, '50_65'), (65, 80, '65_80'), (80, np.inf, 'GE80')]


def safe(x):
    if isinstance(x, dict): return {str(k): safe(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)): return [safe(v) for v in x]
    if isinstance(x, np.integer): return int(x)
    if isinstance(x, (np.floating, float)):
        z = float(x); return z if np.isfinite(z) else None
    if isinstance(x, pd.Timestamp): return x.isoformat()
    return x


def download_qqq(start: str, end_exclusive: str) -> pd.DataFrame:
    x = yf.download('QQQ', start=start, end=end_exclusive, auto_adjust=False, progress=False, threads=False)
    if x.empty: raise RuntimeError('QQQ download empty')
    if isinstance(x.columns, pd.MultiIndex):
        if 'QQQ' in x.columns.get_level_values(-1): x = x.xs('QQQ', axis=1, level=-1)
        else: x.columns = x.columns.get_level_values(0)
    x.index = pd.to_datetime(x.index)
    try: x.index = x.index.tz_localize(None)
    except TypeError: x.index = x.index.tz_convert(None)
    x.index = x.index.normalize()
    return x[['High','Low','Close']].astype(float).sort_index()


def episode_rows(z: pd.DataFrame) -> pd.DataFrame:
    rows=[]
    for band in z.band.dropna().unique():
        mask=z.band.eq(band)
        grp=(mask != mask.shift(fill_value=False)).cumsum()
        for _,g in z[mask].groupby(grp[mask]):
            rows.append({'band':band,'start':g.index.min(),'end':g.index.max(),'sessions':len(g),
                         'mc_min':float(g.mc.min()),'mc_max':float(g.mc.max()),'mc_median':float(g.mc.median()),
                         'qqq_dd20_min':float(g.qqq_dd20.min()),'qqq_dd63_min':float(g.qqq_dd63.min())})
    return pd.DataFrame(rows)


def band_stats(g: pd.DataFrame, total: int) -> dict:
    q=lambda c,p: float(pd.to_numeric(g[c],errors='coerce').quantile(p))
    return {
        'sessions':int(len(g)), 'share':float(len(g)/total) if total else None,
        'mc_median':float(g.mc.median()), 'mc_up1_share':float(g.mc_up1.mean()),
        'qqq_dd20_median':q('qqq_dd20',.5), 'qqq_dd20_p25':q('qqq_dd20',.25), 'qqq_dd20_p10':q('qqq_dd20',.10),
        'qqq_dd63_median':q('qqq_dd63',.5), 'qqq_dd63_p25':q('qqq_dd63',.25), 'qqq_dd63_p10':q('qqq_dd63',.10),
        'ema21_atr_median':q('ema21_atr',.5), 'ema21_atr_p25':q('ema21_atr',.25),
        'qqq_rsi14_median':q('qqq_rsi14',.5),
        'below_ema21_share':float((g.qqq_close < g.qqq_ema21).mean()),
        'below_ema50_share':float((g.qqq_close < g.qqq_ema50).mean()),
        'within_5pct_20d_high_share':float((g.qqq_dd20 >= -0.05).mean()),
        'within_10pct_63d_high_share':float((g.qqq_dd63 >= -0.10).mean()),
    }


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--output',required=True); ap.add_argument('--asof',default='2026-08-27'); ap.add_argument('--start',default='2016-01-04'); args=ap.parse_args()
    out=Path(args.output); out.mkdir(parents=True,exist_ok=True)
    mc=state_audit.build_mc(args.asof).copy()
    mc=mc.loc[mc.index >= pd.Timestamp(args.start)]
    qqq=download_qqq(str((pd.Timestamp(args.start)-pd.Timedelta(days=120)).date()), str((pd.Timestamp(args.asof)+pd.Timedelta(days=1)).date()))
    prev=qqq.Close.shift(1); tr=(qqq.High-qqq.Low).combine((qqq.High-prev).abs(),np.maximum).combine((qqq.Low-prev).abs(),np.maximum); atr=tr.rolling(14,min_periods=14).mean()
    ema21=qqq.Close.ewm(span=21,adjust=False).mean(); ema50=qqq.Close.ewm(span=50,adjust=False).mean(); rsi=rsi_base.rsi(qqq[['Close']].rename(columns={'Close':'QQQ'}),14)['QQQ']
    z=mc[['mc','mc_up1']].join(pd.DataFrame(index=qqq.index, data={
        'qqq_close':qqq.Close,'qqq_ema21':ema21,'qqq_ema50':ema50,'qqq_rsi14':rsi,
        'qqq_dd20':qqq.Close/qqq.Close.rolling(20,min_periods=5).max()-1,
        'qqq_dd63':qqq.Close/qqq.Close.rolling(63,min_periods=20).max()-1,
        'ema21_atr':(qqq.Close-ema21)/atr,
    }),how='inner').dropna(subset=['mc','qqq_close'])
    conds=[]; labels=[]
    for lo,hi,name in BANDS:
        conds.append((z.mc>=lo)&(z.mc<hi)); labels.append(name)
    z['band']=np.select(conds,labels,default='OTHER')
    z['year']=z.index.year
    z.to_csv(out/'mc57_daily_context.csv.gz',compression='gzip')

    rows=[]; total=len(z)
    for name,g in z.groupby('band',observed=True): rows.append({'band':name,**band_stats(g,total)})
    bs=pd.DataFrame(rows); bs.to_csv(out/'mc57_band_summary.csv',index=False)

    yr=(z.groupby(['year','band'],observed=True).size().rename('sessions').reset_index())
    yr['year_total']=yr.groupby('year').sessions.transform('sum'); yr['share']=yr.sessions/yr.year_total
    yr.to_csv(out/'mc57_yearly_band_days.csv',index=False)

    ep=episode_rows(z); ep.to_csv(out/'mc57_band_episodes.csv',index=False)
    eps=[]
    for band,g in ep.groupby('band',observed=True):
        eps.append({'band':band,'episodes':len(g),'median_sessions':float(g.sessions.median()),'p90_sessions':float(g.sessions.quantile(.9)),'max_sessions':int(g.sessions.max()),'median_worst_dd63':float(g.qqq_dd63_min.median())})
    pd.DataFrame(eps).to_csv(out/'mc57_episode_summary.csv',index=False)

    special=[]
    masks={
        'MC20_35':(z.mc>=20)&(z.mc<35),
        'MC20_35_UP':(z.mc>=20)&(z.mc<35)&z.mc_up1,
        'MC35_50':(z.mc>=35)&(z.mc<50),
        'MC35_50_UP':(z.mc>=35)&(z.mc<50)&z.mc_up1,
        'MC50_65':(z.mc>=50)&(z.mc<65),
        'MC65_80':(z.mc>=65)&(z.mc<80),
        'MC_GE80':z.mc>=80,
    }
    years=max((z.index.max()-z.index.min()).days/365.2425,1)
    for name,m in masks.items():
        g=z[m]
        r={'condition':name,'sessions':len(g),'sessions_per_year':float(len(g)/years),'share':float(len(g)/len(z))}
        r.update({k:v for k,v in band_stats(g,len(z)).items() if k not in ('sessions','share')})
        special.append(r)
    pd.DataFrame(special).to_csv(out/'mc57_special_conditions.csv',index=False)

    quant={str(q):float(z.mc.quantile(q)) for q in [0,.05,.1,.2,.25,.5,.75,.8,.9,.95,1.0]}
    summary={'status':'MC57_DISTRIBUTION_AUDIT','start':str(z.index.min().date()),'end':str(z.index.max().date()),'sessions':len(z),'mc_quantiles':quant,
             'mc_mean':float(z.mc.mean()),'mc_std':float(z.mc.std()),'bands':bs.to_dict('records'),'episodes':pd.DataFrame(eps).to_dict('records'),'special':special,
             'note':'MC is production Market Conditions from current 57ETF/12-metric historical reconstruction. QQQ context uses same-day daily data; descriptive, not causal.'}
    (out/'summary.json').write_text(json.dumps(safe(summary),ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(safe(summary),ensure_ascii=False,indent=2),flush=True)

if __name__=='__main__': main()
