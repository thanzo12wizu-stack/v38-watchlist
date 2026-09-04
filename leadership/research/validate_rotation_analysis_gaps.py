from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.multitest import multipletests

HORIZONS=(5,10,20,40)
PERIODS={
    'DISCOVERY_2022_2023':('2022-01-01','2023-12-31'),
    'CONFIRMATION_2024_PLUS':('2024-01-01','2099-12-31'),
    'RECENT_2025_PLUS':('2025-01-01','2099-12-31'),
}
COOLDOWN=20


def safe(v:Any)->Any:
    if isinstance(v,dict): return {str(k):safe(x) for k,x in v.items()}
    if isinstance(v,(list,tuple)): return [safe(x) for x in v]
    if isinstance(v,(np.integer,)): return int(v)
    if isinstance(v,(np.floating,float)):
        x=float(v); return x if math.isfinite(x) else None
    if isinstance(v,pd.Timestamp): return v.isoformat()
    return v


def add_features(df:pd.DataFrame)->pd.DataFrame:
    df=df.sort_values(['sector','date']).copy()
    for h in (5,10,20):
        for c in ('internal_score','price_score','breadth21','breadth50','ad20_score','obv_positive20','updown_volume20','flow20_pct_aum'):
            if c in df.columns:
                df[f'{c}_delta{h}']=df.groupby('sector',sort=False)[c].diff(h)
    df['price_internal_gap']=df['price_score']-df['internal_score']
    return df


def eventize(df:pd.DataFrame,mask:pd.Series)->pd.DataFrame:
    rows=[]
    z=df.assign(_signal=mask.fillna(False).to_numpy())
    for sector,g in z.groupby('sector',sort=False):
        g=g.sort_values('date').reset_index(drop=True)
        last=-10**9
        for i,r in g.iterrows():
            if bool(r['_signal']) and i-last>=COOLDOWN:
                rows.append(r.drop(labels=['_signal']).to_dict()); last=i
    return pd.DataFrame(rows)


def matched_contrast(df:pd.DataFrame,events:pd.DataFrame,base_mask:pd.Series)->pd.DataFrame:
    if events.empty: return events.copy()
    b=df.assign(_base=base_mask.fillna(False).to_numpy())
    out=[]
    for _,r in events.iterrows():
        same=b[(b.date==r.date)&b._base&(b.sector!=r.sector)]
        rec=r.to_dict(); rec['matched_control_n']=int(len(same))
        for h in HORIZONS:
            c=f'fwd_excess_{h}d'; x=pd.to_numeric(same[c],errors='coerce').dropna()
            rec[f'matched_contrast_{h}d']=float(r[c]-x.mean()) if len(x)>=2 and pd.notna(r[c]) else np.nan
        out.append(rec)
    return pd.DataFrame(out)


def boot_mean_ci(x:pd.Series,reps:int=3000,seed:int=1)->list[float|None]:
    a=pd.to_numeric(x,errors='coerce').dropna().to_numpy(float)
    if len(a)<8:return [None,None]
    rng=np.random.default_rng(seed); vals=np.empty(reps)
    for i in range(reps): vals[i]=rng.choice(a,size=len(a),replace=True).mean()
    q=np.quantile(vals,[.025,.975]); return [float(q[0]),float(q[1])]


def sector_cluster_ci(events:pd.DataFrame,col:str,reps:int=3000,seed:int=2)->list[float|None]:
    e=events[['sector',col]].dropna(); sectors=e.sector.unique()
    if len(sectors)<3:return [None,None]
    rng=np.random.default_rng(seed); vals=[]
    for _ in range(reps):
        ss=rng.choice(sectors,size=len(sectors),replace=True); parts=[]
        for s in ss: parts.extend(e.loc[e.sector==s,col].tolist())
        vals.append(float(np.mean(parts)))
    q=np.quantile(vals,[.025,.975]); return [float(q[0]),float(q[1])]


def load_fred(path:Path,dates:pd.DatetimeIndex)->pd.DataFrame:
    if not path.exists(): return pd.DataFrame(index=dates)
    raw=json.loads(path.read_text())
    wanted=['DGS2','DGS10','T10Y2Y','DFII10','NFCI','WALCL','BAMLH0A0HYM2','RRPONTSYD']
    out=pd.DataFrame(index=dates)
    for key in wanted:
        obj=raw.get(key)
        vals=obj.get('vals') if isinstance(obj,dict) else None
        if not vals: continue
        s=pd.Series({pd.Timestamp(d):float(v) for d,v in vals if v is not None}).sort_index()
        out[key]=s.reindex(dates).ffill(limit=10)
    if 'DGS2' in out:
        out['DGS2_delta20']=out.DGS2-out.DGS2.shift(20)
    if 'DGS10' in out:
        out['DGS10_delta20']=out.DGS10-out.DGS10.shift(20)
    if 'WALCL' in out:
        out['WALCL_pct20']=out.WALCL.pct_change(20,fill_method=None)
    return out


def market_regimes(dates:pd.DatetimeIndex)->pd.DataFrame:
    out=pd.DataFrame(index=dates)
    try:
        import yfinance as yf
        px=yf.download(['SPY','QQQ','^VIX'],start=str((dates.min()-pd.Timedelta(days=400)).date()),end=str((dates.max()+pd.Timedelta(days=10)).date()),auto_adjust=True,progress=False,threads=True)
        close=px['Close'] if isinstance(px.columns,pd.MultiIndex) else px
        close.index=pd.to_datetime(close.index).tz_localize(None).normalize()
        close=close.reindex(dates).ffill(limit=3)
        for t in ('SPY','QQQ'):
            if t in close:
                out[f'{t}_uptrend']=close[t]>close[t].rolling(200,min_periods=150).mean()
                out[f'{t}_ret20']=close[t].pct_change(20,fill_method=None)
        if '^VIX' in close: out['VIX']=close['^VIX']
    except Exception as e:
        out.attrs['download_error']=str(e)
    return out


def signal_defs(df:pd.DataFrame):
    f=df.flow20_pct_aum; p=df.price_score; i=df.internal_score
    d5=df.internal_score_delta5; d10=df.internal_score_delta10; d20=df.internal_score_delta20
    b21d5=df.breadth21_delta5; b50d10=df.breadth50_delta10
    true=pd.Series(True,index=df.index)
    return {
      'DISTRIBUTION_TRAP':((p>=70)&(i<50)&(f<=0),p>=70,-1),
      'INTERNAL_DETERIORATION':((p>=70)&(d20<=-20)&(f<=0),p>=70,-1),
      'EARLY_ROTATION':((p<60)&(i>=50)&(d20>=10)&(f>=0),p<60,+1),
      'CONFIRMED_STRENGTH':((p>=70)&(i>=60)&(f>=0),p>=70,+1),
      'INTERNAL_LEAD':((p<60)&(i>=60),p<60,+1),
      'PRICE_LEAD_INTERNAL_WEAK':((p>=70)&(i<50),p>=70,-1),
      'INTERNAL_IGNITION_5D':((d5>=20)&(i<70),i<70,+1),
      'INTERNAL_IGNITION_10D':((d10>=20)&(i<70),i<70,+1),
      'INTERNAL_ROLLOVER_5D':((p>=70)&(d5<=-20),p>=70,-1),
      'INTERNAL_ROLLOVER_10D':((p>=70)&(d10<=-20),p>=70,-1),
      'BREADTH21_IGNITION_5D':(b21d5>=20,true,+1),
      'BREADTH21_ROLLOVER_5D':((p>=70)&(b21d5<=-20),p>=70,-1),
      'BREADTH50_IGNITION_10D':(b50d10>=15,true,+1),
      'BREADTH50_ROLLOVER_10D':((p>=70)&(b50d10<=-15),p>=70,-1),
    }


def period_slice(x:pd.DataFrame,name:str)->pd.DataFrame:
    lo,hi=PERIODS[name]; return x[(x.date>=pd.Timestamp(lo))&(x.date<=pd.Timestamp(hi))]


def summarize_events(events:pd.DataFrame)->dict[str,Any]:
    out={}
    for per in PERIODS:
        e=period_slice(events,per); perout={}
        for h in HORIZONS:
            for prefix in ('fwd_excess_','matched_contrast_'):
                col=f'{prefix}{h}d'; x=pd.to_numeric(e.get(col),errors='coerce').dropna() if col in e else pd.Series(dtype=float)
                perout[f'{prefix}{h}d']={'n':int(len(x)),'mean':None if x.empty else float(x.mean()),'median':None if x.empty else float(x.median()),'negative_rate':None if x.empty else float((x<0).mean())}
        out[per]=perout
    return out


def ic_table(df:pd.DataFrame)->pd.DataFrame:
    features=['price_score','internal_score','flow20_pct_aum','price_internal_gap']+[f'internal_score_delta{x}' for x in (5,10,20)]+[f'breadth21_delta{x}' for x in (5,10,20)]+[f'breadth50_delta{x}' for x in (5,10,20)]+[f'flow20_pct_aum_delta{x}' for x in (5,10,20)]
    rows=[]
    d=period_slice(df,'CONFIRMATION_2024_PLUS')
    for feat in features:
        if feat not in d: continue
        for h in HORIZONS:
            vals=[]
            for _,g in d.groupby('date'):
                z=g[[feat,f'fwd_excess_{h}d']].dropna()
                if len(z)>=6 and z[feat].nunique()>=3:
                    vals.append(stats.spearmanr(z[feat],z[f'fwd_excess_{h}d']).statistic)
            a=np.asarray([x for x in vals if np.isfinite(x)],float)
            if len(a)<20: continue
            t,p=stats.ttest_1samp(a,0.0,nan_policy='omit')
            rows.append({'feature':feat,'horizon':h,'n_dates':len(a),'mean_daily_spearman_ic':float(a.mean()),'t_stat':float(t),'p_value':float(p)})
    out=pd.DataFrame(rows)
    if not out.empty: out['fdr_q']=multipletests(out.p_value.to_numpy(),method='fdr_bh')[1]
    return out


def regime_masks(macro:pd.DataFrame)->dict[str,pd.Series]:
    m={}
    if 'DGS2' in macro:
        m['DGS2_HIGH_4PCT']=macro.DGS2>=4; m['DGS2_LOW_4PCT']=macro.DGS2<4
    if 'DGS2_delta20' in macro:
        m['DGS2_RISING_25BP_20D']=macro.DGS2_delta20>=.25; m['DGS2_FALLING_25BP_20D']=macro.DGS2_delta20<=-.25
    if 'T10Y2Y' in macro: m['CURVE_INVERTED']=macro.T10Y2Y<0
    if 'DFII10' in macro: m['REAL10_HIGH_1P5']=macro.DFII10>=1.5
    if 'NFCI' in macro: m['NFCI_TIGHT']=macro.NFCI>0
    if 'WALCL_pct20' in macro: m['FED_BALANCE_RISING_20D']=macro.WALCL_pct20>0
    if 'BAMLH0A0HYM2' in macro: m['HY_OAS_HIGH_4P5']=macro.BAMLH0A0HYM2>=4.5
    if 'SPY_uptrend' in macro: m['SPY_UPTREND']=macro.SPY_uptrend.fillna(False); m['SPY_DOWNTREND']=~macro.SPY_uptrend.fillna(True)
    if 'QQQ_uptrend' in macro: m['QQQ_UPTREND']=macro.QQQ_uptrend.fillna(False); m['QQQ_DOWNTREND']=~macro.QQQ_uptrend.fillna(True)
    if 'VIX' in macro: m['VIX_HIGH_20']=macro.VIX>=20; m['VIX_LOW_20']=macro.VIX<20
    return m


def regime_summary(events:pd.DataFrame,macro:pd.DataFrame)->pd.DataFrame:
    if events.empty:return pd.DataFrame()
    e=events.merge(macro.reset_index(names='date'),on='date',how='left')
    masks=regime_masks(macro)
    rows=[]
    for name,mask0 in masks.items():
        true_dates=set(macro.index[mask0.fillna(False)])
        z=e[e.date.isin(true_dates)&(e.date>=pd.Timestamp('2024-01-01'))]
        for h in (20,40):
            x=pd.to_numeric(z[f'fwd_excess_{h}d'],errors='coerce').dropna()
            if len(x)>=8: rows.append({'regime':name,'horizon':h,'n':len(x),'mean_excess':x.mean(),'median_excess':x.median(),'negative_rate':(x<0).mean()})
    return pd.DataFrame(rows)


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--panel60',type=Path,required=True); ap.add_argument('--panel80',type=Path,required=True); ap.add_argument('--panel90',type=Path,required=True); ap.add_argument('--fred-cache',type=Path,default=Path('fred_cache.json')); ap.add_argument('--output',type=Path,required=True); args=ap.parse_args(); args.output.mkdir(parents=True,exist_ok=True)
    panels={}
    for cov,path in [('60',args.panel60),('80',args.panel80),('90',args.panel90)]:
        x=pd.read_csv(path); x['date']=pd.to_datetime(x.date).dt.normalize(); panels[cov]=add_features(x)
    dates=pd.DatetimeIndex(sorted(panels['80'].date.unique()))
    macro=load_fred(args.fred_cache,dates).join(market_regimes(dates),how='outer')
    report={'schema':1,'research_only':True,'method':{'cooldown_sessions':20,'periods':PERIODS,'coverage_levels':[.6,.8,.9],'matched_control':'same date, same base state, excluding event sector','continuous_validation':'daily cross-sectional Spearman IC with Benjamini-Hochberg FDR','regimes':'rates/liquidity + SPY/QQQ trend + VIX where available'},'signals':{},'macro_columns':list(macro.columns)}
    all_event_rows=[]
    for cov,df in panels.items():
        for name,(mask,base,expected) in signal_defs(df).items():
            ev=eventize(df,mask); ev=matched_contrast(df,ev,base); ev['coverage']=cov; ev['signal']=name; all_event_rows.append(ev)
            report['signals'].setdefault(name,{'expected_sign':expected,'coverage':{}})['coverage'][cov]=summarize_events(ev)
            if cov=='80':
                c=period_slice(ev,'CONFIRMATION_2024_PLUS')
                boots={}
                for h in (20,40):
                    for col in (f'fwd_excess_{h}d',f'matched_contrast_{h}d'):
                        if col in c:
                            boots[col]={'iid_ci95':boot_mean_ci(c[col],seed=100+h),'sector_cluster_ci95':sector_cluster_ci(c,col,seed=200+h)}
                report['signals'][name]['confirmation_bootstrap_cov80']=boots
                rs=regime_summary(ev,macro); report['signals'][name]['regime_rows']=rs.to_dict('records')
    events=pd.concat(all_event_rows,ignore_index=True) if all_event_rows else pd.DataFrame(); events.to_csv(args.output/'rotation_gap_events.csv',index=False)
    ic=ic_table(panels['80']); ic.to_csv(args.output/'rotation_gap_ic.csv',index=False); report['continuous_ic']=ic.to_dict('records')

    decisions={}
    for name,s in report['signals'].items():
        sign=s['expected_sign']; checks=[]
        for cov in ('60','80','90'):
            for per in ('CONFIRMATION_2024_PLUS','RECENT_2025_PLUS'):
                for h in (20,40):
                    z=s['coverage'][cov][per][f'fwd_excess_{h}d']; m=z['mean']; n=z['n']; checks.append(bool(n>=10 and m is not None and m*sign>0))
        b=s.get('confirmation_bootstrap_cov80',{})
        ci_ok=[]
        for h in (20,40):
            ci=b.get(f'fwd_excess_{h}d',{}).get('sector_cluster_ci95',[None,None]);
            if ci[0] is None: ci_ok.append(False)
            elif sign>0: ci_ok.append(ci[0]>0)
            else: ci_ok.append(ci[1]<0)
        matched=[]
        for h in (20,40):
            z=s['coverage']['80']['CONFIRMATION_2024_PLUS'][f'matched_contrast_{h}d']; matched.append({'horizon':h,'n':z['n'],'mean':z['mean']})
        decisions[name]={'direction_stable_all_coverage_periods':all(checks),'sector_cluster_ci_support_20_40':all(ci_ok),'matched_control_confirmation_cov80':matched,'classification':'ROBUST_ABSOLUTE' if all(checks) and all(ci_ok) else ('DIRECTION_ONLY' if all(checks) else 'REJECT_AS_PREDICTIVE')}
    report['decisions']=decisions
    (args.output/'rotation_gap_report.json').write_text(json.dumps(safe(report),ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# Rotation Analysis Gap Validation','', 'Strict PIT 11-sector validation. No production changes.','', '| Signal | 2024+ 20D | 2024+ 40D | 2025+ 20D | 2025+ 40D | Matched 20D | Matched 40D | Class |','|---|---:|---:|---:|---:|---:|---:|---|']
    for name,s in report['signals'].items():
        c=s['coverage']['80']; d=decisions[name]
        def cell(per,h,prefix='fwd_excess_'):
            z=c[per][f'{prefix}{h}d']; return 'n/a' if z['mean'] is None else f"{100*z['mean']:+.2f}% n={z['n']}"
        lines.append(f"| {name} | {cell('CONFIRMATION_2024_PLUS',20)} | {cell('CONFIRMATION_2024_PLUS',40)} | {cell('RECENT_2025_PLUS',20)} | {cell('RECENT_2025_PLUS',40)} | {cell('CONFIRMATION_2024_PLUS',20,'matched_contrast_')} | {cell('CONFIRMATION_2024_PLUS',40,'matched_contrast_')} | {d['classification']} |")
    lines+=['','## Continuous IC after FDR','']
    sig=ic[ic.fdr_q<=.10] if not ic.empty else ic
    if sig.empty: lines.append('No feature/horizon passed FDR q<=0.10.')
    else:
        lines+=['| Feature | Horizon | Mean IC | q |','|---|---:|---:|---:|']
        for _,r in sig.sort_values('fdr_q').iterrows(): lines.append(f"| {r.feature} | {int(r.horizon)} | {r.mean_daily_spearman_ic:+.3f} | {r.fdr_q:.4f} |")
    lines+=['','## Guardrail','', 'Theme56 historical membership is not available here. These PIT conclusions are validated only for the 11 broad sectors; Theme56 use requires separate non-PIT retrospective confirmation and must remain labeled as extrapolation.']
    (args.output/'README.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('DONE rotation gap validation')

if __name__=='__main__': main()
