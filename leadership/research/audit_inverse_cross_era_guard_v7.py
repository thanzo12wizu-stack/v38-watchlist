from __future__ import annotations
import argparse, json
from pathlib import Path
import numpy as np, pandas as pd, yfinance as yf


def norm(x):
    z = pd.DatetimeIndex(pd.to_datetime(x))
    if z.tz is not None:
        z = z.tz_convert('America/New_York').tz_localize(None)
    return z.normalize()


def cooldown(cond: pd.Series, c: int = 10) -> pd.Series:
    x = cond.fillna(False).astype(bool)
    raw = x & ~x.shift(1, fill_value=False)
    out = np.zeros(len(x), bool); last = -10**9
    for i, z in enumerate(raw.to_numpy(bool)):
        if z and i - last > c:
            out[i] = True; last = i
    return pd.Series(out, index=x.index)


def wilder_rsi(close: pd.Series, n: int = 14) -> pd.Series:
    a = pd.to_numeric(close, errors='coerce').to_numpy(float)
    d = np.diff(a, prepend=np.nan)
    up = np.where(d > 0, d, 0.0); dn = np.where(d < 0, -d, 0.0)
    au = np.full(len(a), np.nan); ad = np.full(len(a), np.nan)
    if len(a) > n:
        au[n] = np.nanmean(up[1:n+1]); ad[n] = np.nanmean(dn[1:n+1])
        for i in range(n+1, len(a)):
            au[i] = (au[i-1]*(n-1)+up[i])/n
            ad[i] = (ad[i-1]*(n-1)+dn[i])/n
    rs = au/ad
    r = 100 - 100/(1+rs)
    r[(ad == 0) & np.isfinite(au)] = 100.0
    r[(au == 0) & (ad == 0)] = 50.0
    return pd.Series(r, index=close.index)


def market_technicals(start: str, end: str) -> pd.DataFrame:
    q = yf.download('QQQ', start=start, end=end, auto_adjust=True, actions=False, progress=False, threads=False)
    if isinstance(q.columns, pd.MultiIndex): q.columns = q.columns.get_level_values(0)
    q.index = norm(q.index); q = q[~q.index.duplicated(keep='last')].sort_index()
    c = pd.to_numeric(q.Close, errors='coerce'); h = pd.to_numeric(q.High, errors='coerce'); l = pd.to_numeric(q.Low, errors='coerce')
    sma50 = c.rolling(50, min_periods=50).mean()
    pc = c.shift(1); tr = pd.concat([(h-l).abs(), (h-pc).abs(), (l-pc).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    out = pd.DataFrame(index=q.index)
    out['qqq_rsi14_calc'] = wilder_rsi(c, 14)
    out['qqq_atr_dist50_calc'] = (c - sma50) / atr.replace(0, np.nan)
    out['qqq_dd20_calc'] = c / c.rolling(20, min_periods=20).max() - 1
    return out


def inverse_returns(idx: pd.DatetimeIndex) -> pd.DataFrame:
    products = ['PSQ','QID','SQQQ']
    x = yf.download(products, start='2010-01-01', end='2026-04-01', auto_adjust=True, actions=False, progress=False, threads=False)
    op = x['Open'].copy(); op.index = norm(op.index); op = op[~op.index.duplicated(keep='last')].sort_index()
    out = pd.DataFrame(index=idx)
    for p in products:
        s = pd.to_numeric(op[p], errors='coerce').reindex(idx)
        out[p] = s.shift(-1) / s - 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--legacy-state', required=True)
    ap.add_argument('--v2-features', required=True)
    ap.add_argument('--output', required=True)
    a = ap.parse_args(); out = Path(a.output); out.mkdir(parents=True, exist_ok=True)

    d = pd.read_csv(a.legacy_state, compression='gzip', parse_dates=['date']).set_index('date').sort_index()
    d.index = norm(d.index)
    tech = market_technicals('2010-01-01','2026-04-01').reindex(d.index)
    d = d.join(tech)
    inv = inverse_returns(d.index)

    core = d['core_mc'].fillna(False).astype(bool)
    guard = d['guard'].fillna(False).astype(bool)
    rsi = pd.to_numeric(d.qqq_rsi14_calc, errors='coerce')
    atrd = pd.to_numeric(d.qqq_atr_dist50_calc, errors='coerce')
    dd20 = pd.to_numeric(d.qqq_dd20_calc, errors='coerce')
    mc = pd.to_numeric(d.mc57, errors='coerce')
    notdeep = (rsi > 34) & (atrd > -2.0) & (dd20 > -.10)
    defs = {
        'CORE_MC': core,
        'CORE_MC_MCFLOOR20': core & (mc >= 20),
        'CORE_MC_MCFLOOR25': core & (mc >= 25),
        'CORE_MC_RSI30': core & (rsi > 30),
        'CORE_MC_RSI34': core & (rsi > 34),
        'CORE_MC_ATR2': core & (atrd > -2.0),
        'CORE_MC_DD10': core & (dd20 > -.10),
        'CORE_MC_NOTDEEP': core & notdeep,
        'CORE_MC_MCFLOOR20_NOTDEEP': core & (mc >= 20) & notdeep,
    }

    rows=[]; ledger=[]
    periods={'PRE_2011_2015':('2011-01-03','2015-12-31'),'OVERLAP_2016_2026':('2016-01-04','2026-03-20')}
    for name, cond in defs.items():
        ev = cooldown(cond,10) & ~guard
        for period,(aa,bb) in periods.items():
            maskperiod = (d.index >= aa) & (d.index <= bb)
            eidx = np.flatnonzero((ev & maskperiod).to_numpy(bool))
            for hold in [2,3,4]:
                for p in ['PSQ','QID','SQQQ']:
                    vals=[]
                    for i in eidx:
                        z=inv[p].iloc[i+1:min(len(inv),i+1+hold)]
                        if len(z)==hold and z.notna().all(): vals.append(float(np.prod(1+z)-1))
                    arr=np.asarray(vals,float)
                    rows.append({'signal':name,'period':period,'product':p,'hold':hold,'n':len(arr),'mean':float(arr.mean()) if len(arr) else None,'median':float(np.median(arr)) if len(arr) else None,'win':float((arr>0).mean()) if len(arr) else None,'worst':float(arr.min()) if len(arr) else None,'best':float(arr.max()) if len(arr) else None})
            for i in eidx:
                z=inv['QID'].iloc[i+1:min(len(inv),i+3)]
                q2=float(np.prod(1+z)-1) if len(z)==2 and z.notna().all() else None
                ledger.append({'signal':name,'period':period,'signal_date':d.index[i],'q2':q2,'mc57':mc.iloc[i],'mc_chg5':d.mc_chg5.iloc[i],'rsi14':rsi.iloc[i],'atr_dist50':atrd.iloc[i],'dd20':dd20.iloc[i],'panic':bool(d.panic.iloc[i]),'stage56':bool(d.stage56.iloc[i])})
    result=pd.DataFrame(rows); result.to_csv(out/'cross_era_guard_grid.csv',index=False)
    pd.DataFrame(ledger).to_csv(out/'cross_era_event_ledger.csv',index=False)

    v2=pd.read_csv(a.v2_features,compression='gzip',parse_dates=['date']).set_index('date').sort_index(); v2.index=norm(v2.index)
    cols=['qqq_rsi14','qqq_atr_dist50','qqq_dd20']
    ov=d[['qqq_rsi14_calc','qqq_atr_dist50_calc','qqq_dd20_calc']].join(v2[cols],how='inner')
    comp={}
    for a1,b1,label in [('qqq_rsi14_calc','qqq_rsi14','rsi14'),('qqq_atr_dist50_calc','qqq_atr_dist50','atr_dist50'),('qqq_dd20_calc','qqq_dd20','dd20')]:
        z=ov[[a1,b1]].dropna(); comp[label]={'n':len(z),'corr':float(z.corr().iloc[0,1]),'median_abs_diff':float((z[a1]-z[b1]).abs().median()),'p99_abs_diff':float((z[a1]-z[b1]).abs().quantile(.99))}

    q=result[(result['product']=='QID') & (result['hold']==2)].copy()
    pivot=q.pivot(index='signal',columns='period',values=['n','mean','median','win','worst'])
    summary={'status':'RESEARCH_ONLY_NO_PRODUCTION_CHANGE','technical_overlap':comp,'qid_h2':q.to_dict('records'),'note':'Guard variants use only pre-existing V38/V4 panic-depth concepts. Cross-era result is diagnostic; no parameter is adopted solely because it fixes 2011-2015.'}
    (out/'summary_v7.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(pivot.to_string())
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
