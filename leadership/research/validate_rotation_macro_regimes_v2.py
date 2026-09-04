from __future__ import annotations
import argparse, io, json, math
from pathlib import Path
import numpy as np
import pandas as pd
import requests

H=(20,40); COOLDOWN=20
FRED=('DGS2','DGS10','T10Y2Y','DFII10','NFCI','WALCL','BAMLH0A0HYM2','RRPONTSYD')

def safe(v):
    if isinstance(v,dict): return {str(k):safe(x) for k,x in v.items()}
    if isinstance(v,(list,tuple)): return [safe(x) for x in v]
    if isinstance(v,np.integer): return int(v)
    if isinstance(v,(np.floating,float)):
        x=float(v); return x if math.isfinite(x) else None
    return v

def add_features(df):
    df=df.sort_values(['sector','date']).copy()
    for h in (5,10,20):
        for c in ('internal_score','price_score','breadth21','breadth50','flow20_pct_aum'):
            df[f'{c}_delta{h}']=df.groupby('sector',sort=False)[c].diff(h)
    return df

def strict_events(df,mask):
    z=df.assign(_s=mask.fillna(False).to_numpy(bool)); rows=[]
    for _,g in z.groupby('sector',sort=False):
        g=g.sort_values('date').reset_index(drop=True); prev=False; last=-999999
        for i,r in g.iterrows():
            active=bool(r._s)
            if active and not prev and i-last>=COOLDOWN:
                rows.append(r.drop(labels='_s').to_dict()); last=i
            prev=active
    return pd.DataFrame(rows)

def fred_series(s,start,end):
    url=f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={s}&cosd={start}&coed={end}'
    r=requests.get(url,timeout=30); r.raise_for_status(); x=pd.read_csv(io.StringIO(r.text))
    x.columns=['date',s]; x['date']=pd.to_datetime(x.date,errors='coerce'); x[s]=pd.to_numeric(x[s],errors='coerce')
    return x.dropna(subset=['date']).set_index('date')[s]

def build_macro(dates,start,end,df):
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
        close=px['Close'] if isinstance(px.columns,pd.MultiIndex) else px
        close.index=pd.to_datetime(close.index).tz_localize(None).normalize(); close=close.reindex(dates).ffill(limit=3)
        for t in ('SPY','QQQ'):
            if t in close: out[f'{t}_ABOVE_200D']=close[t]>close[t].rolling(200,min_periods=150).mean()
        if '^VIX' in close: out['VIX']=close['^VIX']
        meta['YFINANCE_MARKET']={'status':'READY'}
    except Exception as e: meta['YFINANCE_MARKET']={'status':'ERROR','error':str(e)}
    agg=df.groupby('date').agg(SECTOR_INTERNAL_MEAN=('internal_score','mean'),SECTOR_BREADTH50_MEAN=('breadth50','mean')).reindex(dates)
    return out.join(agg),meta

def masks(m):
    out={}
    def add(k,x): out[k]=x.fillna(False)
    if 'DGS2' in m: add('DGS2_HIGH_GE4',m.DGS2>=4); add('DGS2_LOW_LT4',m.DGS2<4)
    if 'DGS2_delta20' in m: add('DGS2_RISING_25BP',m.DGS2_delta20>=.25); add('DGS2_FALLING_25BP',m.DGS2_delta20<=-.25)
    if 'DGS10' in m: add('DGS10_HIGH_GE4',m.DGS10>=4); add('DGS10_LOW_LT4',m.DGS10<4)
    if 'DGS10_delta20' in m: add('DGS10_RISING_25BP',m.DGS10_delta20>=.25); add('DGS10_FALLING_25BP',m.DGS10_delta20<=-.25)
    if 'T10Y2Y' in m: add('CURVE_INVERTED',m.T10Y2Y<0); add('CURVE_POSITIVE',m.T10Y2Y>=0)
    if 'DFII10' in m: add('REAL10_HIGH_GE1P5',m.DFII10>=1.5); add('REAL10_LOW_LT1P5',m.DFII10<1.5)
    if 'NFCI' in m: add('NFCI_TIGHT',m.NFCI>0); add('NFCI_LOOSE',m.NFCI<=0)
    if 'WALCL_pct20' in m: add('FED_BALANCE_RISING',m.WALCL_pct20>0); add('FED_BALANCE_FALLING',m.WALCL_pct20<0)
    if 'BAMLH0A0HYM2' in m: add('HY_OAS_HIGH_GE4P5',m.BAMLH0A0HYM2>=4.5); add('HY_OAS_LOW_LT4P5',m.BAMLH0A0HYM2<4.5)
    if 'VIX' in m: add('VIX_HIGH_GE20',m.VIX>=20); add('VIX_LOW_LT20',m.VIX<20)
    for t in ('SPY','QQQ'):
        c=f'{t}_ABOVE_200D'
        if c in m: add(f'{t}_UPTREND',m[c]==True); add(f'{t}_DOWNTREND',m[c]==False)
    if 'SECTOR_INTERNAL_MEAN' in m: add('MARKET_INTERNAL_STRONG',m.SECTOR_INTERNAL_MEAN>=60); add('MARKET_INTERNAL_WEAK',m.SECTOR_INTERNAL_MEAN<50)
    if 'SECTOR_BREADTH50_MEAN' in m: add('MARKET_BREADTH_STRONG',m.SECTOR_BREADTH50_MEAN>=60); add('MARKET_BREADTH_WEAK',m.SECTOR_BREADTH50_MEAN<50)
    return out

def boot_ci(x,reps=2000,seed=1):
    a=pd.to_numeric(x,errors='coerce').dropna().to_numpy(float)
    if len(a)<8:return [None,None]
    rng=np.random.default_rng(seed); idx=rng.integers(0,len(a),size=(reps,len(a))); q=np.quantile(a[idx].mean(axis=1),[.025,.975]); return [float(q[0]),float(q[1])]

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--panel',type=Path,required=True); ap.add_argument('--output',type=Path,required=True); args=ap.parse_args(); args.output.mkdir(parents=True,exist_ok=True)
    df=add_features(pd.read_csv(args.panel,parse_dates=['date'])); dates=pd.DatetimeIndex(sorted(df.date.unique())); start=str((dates.min()-pd.Timedelta(days=400)).date()); end=str((dates.max()+pd.Timedelta(days=60)).date())
    macro,meta=build_macro(dates,start,end,df); rm=masks(macro)
    defs={
      'DISTRIBUTION_TRAP':((df.price_score>=70)&(df.internal_score<50)&(df.flow20_pct_aum<=0),-1),
      'INTERNAL_DETERIORATION':((df.price_score>=70)&(df.internal_score_delta20<=-20)&(df.flow20_pct_aum<=0),-1),
      'PRICE_LEAD_INTERNAL_WEAK':((df.price_score>=70)&(df.internal_score<50),-1),
      'INTERNAL_ROLLOVER_10D':((df.price_score>=70)&(df.internal_score_delta10<=-20),-1),
      'BREADTH50_ROLLOVER_10D':((df.price_score>=70)&(df.breadth50_delta10<=-15),-1),
      'EARLY_ROTATION':((df.price_score<60)&(df.internal_score>=50)&(df.internal_score_delta20>=10)&(df.flow20_pct_aum>=0),+1),
      'INTERNAL_IGNITION_10D':((df.internal_score_delta10>=20)&(df.internal_score<70),+1),
    }
    report={'schema':2,'research_only':True,'note':'Pre-specified robustness splits only. No regime becomes a trading gate. Historical NQSAR panel was unavailable in the audited PIT asset.','sources':meta,'signals':{}}
    rows=[]
    for name,(sig,expect) in defs.items():
        ev=strict_events(df,sig); ev=ev[ev.date>=pd.Timestamp('2024-01-01')].merge(macro.reset_index(names='date'),on='date',how='left'); sr={'expected_sign':expect,'overall_n':len(ev),'regimes':{}}
        for rn,mask in rm.items():
            z=ev[ev.date.isin(set(macro.index[mask]))]; rr={}
            for h in H:
                x=pd.to_numeric(z[f'fwd_excess_{h}d'],errors='coerce').dropna(); rr[str(h)]={'n':len(x),'mean':None if x.empty else float(x.mean()),'median':None if x.empty else float(x.median()),'ci95':boot_ci(x,seed=100+h)}
                if len(x)>=5: rows.append({'signal':name,'regime':rn,'horizon':h,'n':len(x),'mean':x.mean(),'median':x.median()})
            sr['regimes'][rn]=rr
        report['signals'][name]=sr
    pair_names=[('DGS2_HIGH_GE4','DGS2_LOW_LT4'),('DGS2_RISING_25BP','DGS2_FALLING_25BP'),('DGS10_HIGH_GE4','DGS10_LOW_LT4'),('DGS10_RISING_25BP','DGS10_FALLING_25BP'),('CURVE_INVERTED','CURVE_POSITIVE'),('REAL10_HIGH_GE1P5','REAL10_LOW_LT1P5'),('NFCI_TIGHT','NFCI_LOOSE'),('FED_BALANCE_RISING','FED_BALANCE_FALLING'),('HY_OAS_HIGH_GE4P5','HY_OAS_LOW_LT4P5'),('VIX_HIGH_GE20','VIX_LOW_LT20'),('SPY_UPTREND','SPY_DOWNTREND'),('QQQ_UPTREND','QQQ_DOWNTREND'),('MARKET_INTERNAL_STRONG','MARKET_INTERNAL_WEAK'),('MARKET_BREADTH_STRONG','MARKET_BREADTH_WEAK')]
    stability={}
    for name,sr in report['signals'].items():
        sign=sr['expected_sign']; details=[]
        for a,b in pair_names:
            if a not in sr['regimes'] or b not in sr['regimes']:continue
            for h in H:
                x=sr['regimes'][a][str(h)]; y=sr['regimes'][b][str(h)]; ok=x['n']>=8 and y['n']>=8 and x['mean'] is not None and y['mean'] is not None and x['mean']*sign>0 and y['mean']*sign>0
                details.append({'pair':[a,b],'horizon':h,'both_expected_sign':ok,'a_n':x['n'],'a_mean':x['mean'],'b_n':y['n'],'b_mean':y['mean']})
        stability[name]={'tested_pairs':len(details),'fraction_both_expected_sign':None if not details else float(np.mean([x['both_expected_sign'] for x in details])),'details':details}
    report['regime_stability']=stability
    pd.DataFrame(rows).to_csv(args.output/'macro_regime_rows.csv',index=False); macro.to_csv(args.output/'macro_regime_panel.csv'); (args.output/'macro_regime_report.json').write_text(json.dumps(safe(report),ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# Rotation Macro Regime Validation','', 'Research-only. Pre-specified rates/liquidity/market splits; no optimized gates.','', '| Signal | tested | stable fraction |','|---|---:|---:|']
    for n,s in stability.items():
        frac=s['fraction_both_expected_sign']; txt='n/a' if frac is None else f'{frac:.0%}'
        lines.append(f"| {n} | {s['tested_pairs']} | {txt} |")
    (args.output/'README.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('DONE macro regime validation',json.dumps(meta,default=str))
if __name__=='__main__': main()
