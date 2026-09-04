from __future__ import annotations

import argparse, io, json, math
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd
import requests

H=(20,40); COOLDOWN=20
FRED=['DGS2','DGS10','T10Y2Y','DFII10','NFCI','WALCL','BAMLH0A0HYM2','RRPONTSYD']


def safe(v:Any)->Any:
    if isinstance(v,dict): return {str(k):safe(x) for k,x in v.items()}
    if isinstance(v,(list,tuple)): return [safe(x) for x in v]
    if isinstance(v,(np.integer,)): return int(v)
    if isinstance(v,(np.floating,float)):
        x=float(v); return x if math.isfinite(x) else None
    return v


def add_features(df:pd.DataFrame)->pd.DataFrame:
    df=df.sort_values(['sector','date']).copy()
    for h in (5,10,20):
        for c in ('internal_score','price_score','breadth21','breadth50','flow20_pct_aum'):
            df[f'{c}_delta{h}']=df.groupby('sector',sort=False)[c].diff(h)
    return df


def strict_events(df:pd.DataFrame,mask:pd.Series)->pd.DataFrame:
    z=df.assign(_s=mask.fillna(False).to_numpy(bool)); rows=[]
    for sector,g in z.groupby('sector',sort=False):
        g=g.sort_values('date').reset_index(drop=True); prev=False; last=-999999
        for i,r in g.iterrows():
            active=bool(r._s)
            if active and not prev and i-last>=COOLDOWN:
                rows.append(r.drop(labels='_s').to_dict()); last=i
            prev=active
    return pd.DataFrame(rows)


def fred_series(series:str,start:str,end:str)->pd.Series:
    url=f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}&cosd={start}&coed={end}'
    r=requests.get(url,timeout=30); r.raise_for_status(); x=pd.read_csv(io.StringIO(r.text)); x.columns=['date',series]; x['date']=pd.to_datetime(x.date,errors='coerce'); x[series]=pd.to_numeric(x[series],errors='coerce'); return x.dropna(subset=['date']).set_index('date')[series]


def macro_panel(dates:pd.DatetimeIndex,start:str,end:str)->tuple[pd.DataFrame,dict]:
    out=pd.DataFrame(index=dates); meta={}
    for s in FRED:
        try:
            x=fred_series(s,start,end); out[s]=x.reindex(dates).ffill(limit=10); meta[s]={'status':'READY','n':int(x.notna().sum())}
        except Exception as e: meta[s]={'status':'ERROR','error':str(e)}
    for s in ('DGS2','DGS10','DFII10','NFCI','BAMLH0A0HYM2'):
        if s in out: out[f'{s}_delta20']=out[s]-out[s].shift(20)
    if 'WALCL' in out: out['WALCL_pct20']=out.WALCL.pct_change(20,fill_method=None)
    if 'RRPONTSYD' in out: out['RRPONTSYD_delta20']=out.RRPONTSYD-out.RRPONTSYD.shift(20)
    try:
        import yfinance as yf
        px=yf.download(['SPY','QQQ','^VIX'],start=start,end=end,auto_adjust=True,progress=False,threads=True)
        close=px['Close'] if isinstance(px.columns,pd.MultiIndex) else px; close.index=pd.to_datetime(close.index).tz_localize(None).normalize(); close=close.reindex(dates).ffill(limit=3)
        for t in ('SPY','QQQ'):
            if t in close:
                out[f'{t}_ABOVE_200D']=close[t]>close[t].rolling(200,min_periods=150).mean(); out[f'{t}_RET20']=close[t].pct_change(20,fill_method=None)
        if '^VIX' in close: out['VIX']=close['^VIX']
        meta['YFINANCE_MARKET']={'status':'READY','columns':list(close.columns)}
    except Exception as e: meta['YFINANCE_MARKET']={'status':'ERROR','error':str(e)}
    return out,meta


def market_internal(df:pd.DataFrame,dates:pd.DatetimeIndex)->pd.DataFrame:
    g=df.groupby('date').agg(SECTOR_INTERNAL_MEAN=('internal_score','mean'),SECTOR_PRICE_MEAN=('price_score','mean'),SECTOR_BREADTH50_MEAN=('breadth50','mean')).reindex(dates)
    return g


def regime_masks(m:pd.DataFrame)->dict[str,pd.Series]:
    R={}
    def add(name,cond): R[name]=cond.fillna(False)
    if 'DGS2' in m: add('DGS2_HIGH_GE4',m.DGS2>=4); add('DGS2_LOW_LT4',m.DGS2<4)
    if 'DGS2_delta20' in m: add('DGS2_RISING_20D_GE25BP',m.DGS2_delta20>=.25); add('DGS2_FALLING_20D_LEM25BP',m.DGS2_delta20<=-.25)
    if 'DGS10' in m: add('DGS10_HIGH_GE4',m.DGS10>=4); add('DGS10_LOW_LT4',m.DGS10<4)
    if 'DGS10_delta20' in m: add('DGS10_RISING_20D_GE25BP',m.DGS10_delta20>=.25); add('DGS10_FALLING_20D_LEM25BP',m.DGS10_delta20<=-.25)
    if 'T10Y2Y' in m: add('CURVE_INVERTED',m.T10Y2Y<0); add('CURVE_POSITIVE',m.T10Y2Y>=0)
    if 'DFII10' in m: add('REAL10_HIGH_GE1P5',m.DFII10>=1.5); add('REAL10_LOW_LT1P5',m.DFII10<1.5)
    if 'NFCI' in m: add('NFCI_TIGHT_GT0',m.NFCI>0); add('NFCI_LOOSE_LE0',m.NFCI<=0)
    if 'WALCL_pct20' in m: add('FED_BALANCE_RISING_20D',m.WALCL_pct20>0); add('FED_BALANCE_FALLING_20D',m.WALCL_pct20<0)
    if 'BAMLH0A0HYM2' in m: add('HY_OAS_HIGH_GE4P5',m.BAMLH0A0HYM2>=4.5); add('HY_OAS_LOW_LT4P5',m.BAMLH0A0HYM2<4.5)
    if 'VIX' in m: add('VIX_HIGH_GE20',m.VIX>=20); add('VIX_LOW_LT20',m.VIX<20)
    for t in ('SPY','QQQ'):
        c=f'{t}_ABOVE_200D'
        if c in m: add(f'{t}_UPTREND_200D',m[c]==True); add(f'{t}_DOWNTREND_200D',m[c]==False)
    if 'SECTOR_INTERNAL_MEAN' in m: add('MARKET_INTERNAL_STRONG_GE60',m.SECTOR_INTERNAL_MEAN>=60); add('MARKET_INTERNAL_WEAK_LT50',m.SECTOR_INTERNAL_MEAN<50)
    if 'SECTOR_BREADTH50_MEAN' in m: add('MARKET_SECTOR_BREADTH_STRONG_GE60',m.SECTOR_BREADTH50_MEAN>=60); add('MARKET_SECTOR_BREADTH_WEAK_LT50',m.SECTOR_BREADTH50_MEAN<50)
    return R


def boot_ci(x:pd.Series,reps=3000,seed=1):
    a=pd.to_numeric(x,errors='coerce').dropna().to_numpy(float)
    if len(a)<8:return [None,None]
    rng=np.random.default_rng(seed); idx=rng.integers(0,len(a),size=(reps,len(a))); q=np.quantile(a[idx].mean(axis=1),[.025,.975]); return [float(q[0]),float(q[1])]


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--panel',type=Path,required=True); ap.add_argument('--output',type=Path,required=True); args=ap.parse_args(); args.output.mkdir(parents=True,exist_ok=True)
    df=add_features(pd.read_csv(args.panel,parse_dates=['date'])); dates=pd.DatetimeIndex(sorted(df.date.unique())); start=str((dates.min()-pd.Timedelta(days=400)).date()); end=str((dates.max()+pd.Timedelta(days=60)).date())
    macro,meta=macro_panel(dates,start,end); macro=macro.join(market_internal(df,dates),how='left'); masks=regime_masks(macro)
    defs={
      'DISTRIBUTION_TRAP':((df.price_score>=70)&(df.internal_score<50)&(df.flow20_pct_aum<=0),-1),
      'INTERNAL_DETERIORATION':((df.price_score>=70)&(df.internal_score_delta20<=-20)&(df.flow20_pct_aum<=0),-1),
      'PRICE_LEAD_INTERNAL_WEAK':((df.price_score>=70)&(df.internal_score<50),-1),
      'INTERNAL_ROLLOVER_10D':((df.price_score>=70)&(df.internal_score_delta10<=-20),-1),
      'BREADTH50_ROLLOVER_10D':((df.price_score>=70)&(df.breadth50_delta10<=-15),-1),
      'EARLY_ROTATION':((df.price_score<60)&(df.internal_score>=50)&(df.internal_score_delta20>=10)&(df.flow20_pct_aum>=0),+1),
      'INTERNAL_IGNITION_10D':((df.internal_score_delta10>=20)&(df.internal_score<70),+1),
    }
    report={'schema':1,'research_only':True,'note':'Pre-specified regime robustness only. Regimes are not optimized into trading gates. Historical NQSAR panel was not available in audited PIT assets.','data_sources':meta,'signals':{}}
    csv=[]
    for name,(mask,expect) in defs.items():
        ev=strict_events(df,mask); ev=ev[ev.date>=pd.Timestamp('2024-01-01')].merge(macro.reset_index(names='date'),on='date',how='left'); so={'expected_sign':expect,'overall_n':len(ev),'regimes':{}}
        for rn,rm in masks.items():
            dates_on=set(macro.index[rm]); z=ev[ev.date.isin(dates_on)]; ro={}
            for h in H:
                x=pd.to_numeric(z[f'fwd_excess_{h}d'],errors='coerce').dropna(); ro[str(h)]={'n':len(x),'mean':None if len(x)==0 else x.mean(),'median':None if len(x)==0 else x.median(),'ci95':boot_ci(x,seed=100+h) if len(x)>=8 else [None,None]}
                if len(x)>=5: csv.append({'signal':name,'regime':rn,'horizon':h,'n':len(x),'mean':x.mean(),'median':x.median()})
            so['regimes'][rn]=ro
        report['signals'][name]=so
    # paired regime families: do both sides retain expected sign?
    pairs=[('DGS2_HIGH_GE4','DGS2_LOW_LT4'),('DGS2_RISING_20D_GE25BP','DGS2_FALLING_20D_LEM25BP'),('DGS10_HIGH_GE4','DGS10_LOW_LT4'),('DGS10_RISING_20D_GE25BP','DGS10_FALLING_20D_LEM25BP'),('CURVE_INVERTED','CURVE_POSITIVE'),('REAL10_HIGH_GE1P5','REAL10_LOW_LT1P5'),('NFCI_TIGHT_GT0','NFCI_LOOSE_LE0'),('FED_BALANCE_RISING_20D','FED_BALANCE_FALLING_20D'),('HY_OAS_HIGH_GE4P5','HY_OAS_LOW_LT4P5'),('VIX_HIGH_GE20','VIX_LOW_LT20'),('SPY_UPTREND_200D','SPY_DOWNTREND_200D'),('QQQ_UPTREND_200D','QQQ_DOWNTREND_200D'),('MARKET_INTERNAL_STRONG_GE60','MARKET_INTERNAL_WEAK_LT50')]
    stability={}
    for name,so in report['signals'].items():
        sign=so['expected_sign']; fam=[]
        for a,b in pairs:
            if a not in so['regimes'] or b not in so['regimes']:continue
            for h in H:
                za=so['regimes'][a][str(h)]; zb=so['regimes'][b][str(h)]; ok=za['n']>=8 and zb['n']>=8 and za['mean'] is not None and zb['mean'] is not None and za['mean']*sign>0 and zb['mean']*sign>0
                fam.append({'pair':[a,b],'horizon':h,'both_sides_expected_sign':ok,'a_n':za['n'],'a_mean':za['mean'],'b_n':zb['n'],'b_mean':zb['mean']})
        stability[name]={'tested_pairs':len(fam),'fraction_both_sides_expected_sign':None if not fam else float(np.mean([x['both_sides_expected_sign'] for x in fam])),'details':fam}
    report['regime_stability']=stability
    pd.DataFrame(csv).to_csv(args.output/'macro_regime_rows.csv',index=False); macro.to_csv(args.output/'macro_regime_panel.csv'); (args.output/'macro_regime_report.json').write_text(json.dumps(safe(report),ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# Rotation Rates / Liquidity / Market-Regime Validation','', 'Research-only robustness check. No regime is promoted to a gate. Historical NQSAR was unavailable in the audited PIT panel; market trend/VIX/aggregate-sector internals are used instead.','', '| Signal | tested splits | both sides expected sign |','|---|---:|---:|']
    for n,s in stability.items(): lines.append(f"| {n} | {s['tested_pairs']} | {'n/a' if s['fraction_both_sides_expected_sign'] is None else f'{s[\"fraction_both_sides_expected_sign\"]:.0%}'} |")
    (args.output/'README.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('DONE macro regime validation',meta)

if __name__=='__main__':main()
