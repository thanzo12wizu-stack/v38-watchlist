#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
import yfinance as yf

START='2009-01-01'; END='2026-08-26'; EVAL_START=pd.Timestamp('2011-01-01'); EVAL_END=pd.Timestamp('2026-08-25')
ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/'market_conditions_simple_variants_15y.json'

BROAD=['SPY','QQQ','DIA','IWM','MDY','RSP','VTI','QQQE']
SECTORS=['XLK','XLY','VOX','XLF','XLI','XLE','XLB','XLV','XLP','XLU','XLRE']
IND_GROUPS={
 'Semiconductors':['SOXX','SMH','XSD'],
 'SoftwareCloudInternet':['IGV','SKYY','CIBR','HACK','FDN'],
 'Biotech':['XBI','IBB'],
 'PharmaMedical':['PPH','IHI','IHF'],
 'Banks':['KRE','KBE'],
 'RetailHousing':['XRT','ITB','XHB'],
 'Transport':['IYT','JETS'],
 'Defense':['ITA','XAR'],
 'Automation':['ROBO'],
 'Metals':['XME','COPX','PICK'],
 'PreciousMetals':['GDX','SIL'],
 'Lithium':['LIT'],
 'Energy':['XOP','OIH','URA'],
 'CleanEnergy':['TAN','ICLN'],
 'RealEstate':['VNQ'],
 'Agriculture':['MOO'],
 'Water':['PHO'],
 'Infrastructure':['PAVE'],
}
INDUSTRIES=[x for xs in IND_GROUPS.values() for x in xs]
UNIVERSE=list(dict.fromkeys(BROAD+SECTORS+INDUSTRIES))
METRICS=['ret5','ret21','ret63','ret252','above10','above20','above50','above200','ma20_gt50','ma50_gt200','dd_score','within10']
BANDS=[(-np.inf,20,'STRONG BEAR'),(20,35,'BEAR'),(35,45,'WEAK BEAR'),(45,55,'NEUTRAL'),(55,65,'WEAK BULL'),(65,80,'BULL'),(80,np.inf,'STRONG BULL')]

def band(x):
    for lo,hi,n in BANDS:
        if lo<=x<hi:return n
    return 'N/A'

def download():
    out={}; failed=[]
    for i,t in enumerate(UNIVERSE,1):
        ok=False
        for _ in range(2):
            try:
                d=yf.download(t,start=START,end=END,auto_adjust=True,progress=False,threads=False,timeout=25)
                if d is None or d.empty: continue
                if isinstance(d.columns,pd.MultiIndex):
                    if ('Close',t) in d.columns:s=d[('Close',t)]
                    elif 'Close' in d.columns.get_level_values(0):s=d.xs('Close',axis=1,level=0).iloc[:,0]
                    else:continue
                else:
                    if 'Close' not in d.columns:continue
                    s=d['Close']
                s=pd.to_numeric(s,errors='coerce').dropna()
                if len(s):s.name=t;out[t]=s;ok=True;break
            except Exception: pass
        if not ok: failed.append(t)
        print(f'[download] {i}/{len(UNIVERSE)} {t} {"ok" if ok else "FAIL"}')
    px=pd.concat(out.values(),axis=1).sort_index(); px.index=pd.to_datetime(px.index).tz_localize(None)
    return px,failed

def mean_cols(v,cols):
    c=[x for x in cols if x in v.columns]
    return v[c].mean(axis=1,skipna=True) if c else pd.Series(np.nan,index=v.index)

def aggregate(v):
    broad=mean_cols(v,BROAD); sector=mean_cols(v,SECTORS)
    groups=[mean_cols(v,xs) for xs in IND_GROUPS.values()]
    industry=pd.concat(groups,axis=1).mean(axis=1,skipna=True)
    return pd.concat([broad,sector,industry],axis=1).mean(axis=1,skipna=True)

def build(px):
    c=px.reindex(columns=[x for x in UNIVERSE if x in px.columns])
    ma10=c.rolling(10,min_periods=10).mean(); ma20=c.rolling(20,min_periods=20).mean(); ma50=c.rolling(50,min_periods=50).mean(); ma200=c.rolling(200,min_periods=200).mean()
    vals={}
    for n,h in [('ret5',5),('ret21',21),('ret63',63),('ret252',252)]: vals[n]=aggregate(((c/c.shift(h)-1)>0).where(c.notna()&c.shift(h).notna()).astype(float)*100)
    for n,ma in [('above10',ma10),('above20',ma20),('above50',ma50),('above200',ma200)]: vals[n]=aggregate((c>ma).where(c.notna()&ma.notna()).astype(float)*100)
    vals['ma20_gt50']=aggregate((ma20>ma50).where(ma20.notna()&ma50.notna()).astype(float)*100)
    vals['ma50_gt200']=aggregate((ma50>ma200).where(ma50.notna()&ma200.notna()).astype(float)*100)
    hi=c.rolling(252,min_periods=200).max(); dd=c/hi-1
    ddscore=((dd+0.30)/0.25*100).clip(0,100)
    vals['dd_score']=aggregate(ddscore)
    vals['within10']=aggregate((dd>=-0.10).where(dd.notna()).astype(float)*100)
    m=pd.DataFrame(vals)
    m['delta20_soft']=(50+1.25*(m.above20-m.above20.shift(10))).clip(0,100)
    m['delta50_soft']=(50+1.25*(m.above50-m.above50.shift(10))).clip(0,100)
    m['delta20_mid']=(50+2.0*(m.above20-m.above20.shift(10))).clip(0,100)
    m['delta50_mid']=(50+2.0*(m.above50-m.above50.shift(10))).clip(0,100)
    return m

def score_variants(m):
    x=m[METRICS]
    raw={}
    raw['eq12']=x.mean(axis=1)
    mom=m[['ret5','ret21','ret63','ret252']].mean(axis=1); breadth=m[['above10','above20','above50','above200']].mean(axis=1); trend=m[['ma20_gt50','ma50_gt200']].mean(axis=1); damage=m[['dd_score','within10']].mean(axis=1)
    raw['family25']=pd.concat([mom,breadth,trend,damage],axis=1).mean(axis=1)
    raw['trimmed12']=x.apply(lambda r: float(np.nanmean(np.sort(r.dropna().to_numpy())[1:-1])) if r.notna().sum()>=4 else np.nan,axis=1)
    raw['robust_mean_median']=0.5*x.mean(axis=1)+0.5*x.median(axis=1)
    raw['speed14_soft']=m[METRICS+['delta20_soft','delta50_soft']].mean(axis=1)
    raw['speed14_mid']=m[METRICS+['delta20_mid','delta50_mid']].mean(axis=1)
    raw['dedup10']=pd.concat([m[['ret5','ret21','ret63','ret252','above20','above50','above200','ma20_gt50','ma50_gt200']],damage.rename('damage')],axis=1).mean(axis=1)
    contrast=(50+1.25*(x-50)).clip(0,100)
    raw['contrast12']=contrast.mean(axis=1)
    return {k:v.ewm(span=2,adjust=False).mean() for k,v in raw.items()}

def drawdown_episodes(q,trigger=-.08,exit_dd=-.02):
    q=q.dropna(); peak=float(q.iloc[0]); peak_dt=q.index[0]; active=False; out=[]
    for dt,v0 in q.items():
        v=float(v0)
        if not active:
            if v>peak: peak=v; peak_dt=dt
            if v/peak-1<=trigger: active=True; ep_peak=peak; ep_peak_dt=peak_dt; trough=v; trough_dt=dt
        else:
            if v<trough: trough=v; trough_dt=dt
            if v/ep_peak-1>=exit_dd:
                out.append({'peak':ep_peak_dt,'trough':trough_dt,'end':dt,'dd':trough/ep_peak-1}); active=False; peak=v; peak_dt=dt
    if active: out.append({'peak':ep_peak_dt,'trough':trough_dt,'end':q.index[-1],'dd':trough/ep_peak-1})
    return out

def sessions(idx,a,b): return max(len(idx[(idx>=a)&(idx<=b)])-1,0)
def stress_mask(idx,eps):
    z=pd.Series(False,index=idx)
    for e in eps:z.loc[(idx>=e['peak'])&(idx<=e['end'])]=True
    return z

def quality(s,q,eps):
    idx=q.index; st=stress_mask(idx,eps); out={}
    for th in (65,55,45):
        delays=[]
        for e in eps:
            z=s.loc[e['peak']:e['trough']]; h=z[z<th]
            if len(h):delays.append(sessions(idx,e['peak'],h.index[0]))
        sig=(s<th); false=sig&~st
        # max false run
        arr=false.fillna(False).to_numpy(); mx=cur=runs=0; prev=False
        for b in arr:
            if b: cur+=1; mx=max(mx,cur); runs+=int(not prev)
            else: cur=0
            prev=bool(b)
        out[f'below{th}_coverage']=len(delays); out[f'below{th}_mean']=float(np.mean(delays)) if delays else None
        out[f'false{th}_days']=int(false.sum()); out[f'false{th}_pct_signal']=float(false.sum()/max(sig.sum(),1)*100); out[f'false{th}_maxrun']=mx; out[f'false{th}_runs']=runs
    return out

def year_stats(s,y):
    z=s[s.index.year==y]
    return {'min':float(z.min()),'mean':float(z.mean()),'median':float(z.median()),'lt55':int((z<55).sum()),'le45':int((z<=45).sum())}

def episode_focus(s,eps,years=(2018,2020,2022,2025,2026)):
    rows=[]; idx=s.index
    for e in eps:
        if not any(e['peak'].year<=y<=e['end'].year for y in years):continue
        r={'peak':str(e['peak'].date()),'trough':str(e['trough'].date()),'dd_pct':float(e['dd']*100)}
        for th in (65,55,45):
            z=s.loc[e['peak']:e['trough']]; h=z[z<th]
            r[f'below{th}']=sessions(idx,e['peak'],h.index[0]) if len(h) else None
        rows.append(r)
    return rows

def main():
    px,failed=download(); px=px.loc[:EVAL_END]; m=build(px); scores=score_variants(m)
    q=px.QQQ.loc[EVAL_START:EVAL_END].dropna(); spy=px.SPY.reindex(q.index); iwm=px.IWM.reindex(q.index); eps=drawdown_episodes(q)
    report={}
    for name,s0 in scores.items():
        s=s0.reindex(q.index)
        r={'target_2026_08_21':float(s.loc[pd.Timestamp('2026-08-21')]),'latest':float(s.dropna().iloc[-1]),'corr_qqq21':float(s.corr(q/q.shift(21)-1)),'corr_qqq63':float(s.corr(q/q.shift(63)-1)),'corr_qqq126':float(s.corr(q/q.shift(126)-1)),'corr_spy63':float(s.corr(spy/spy.shift(63)-1)),'corr_iwm63':float(s.corr(iwm/iwm.shift(63)-1)),'daily_abs_change':float(s.diff().abs().mean()),'benign_2013':year_stats(s,2013),'benign_2017':year_stats(s,2017),'year_2022':year_stats(s,2022)}
        r.update(quality(s,q,eps)); r['focus_episodes']=episode_focus(s,eps); report[name]=r
    coverage={str(d.date()):int(px.loc[d].notna().sum()) for d in [pd.Timestamp('2011-01-03'),pd.Timestamp('2016-01-04'),pd.Timestamp('2022-01-03'),pd.Timestamp('2026-08-21')] if d in px.index}
    out={'definition':{'universe_count':len(UNIVERSE),'broad':len(BROAD),'sectors':len(SECTORS),'industry_groups':len(IND_GROUPS),'metrics':METRICS,'aggregation':'each metric first balanced Broad/Sector/Industry; industry ETFs averaged within subgroup then subgroups equally weighted; variants differ only in metric aggregation','vix_nqsar':'not inside score'},'coverage':coverage,'failed':failed,'episodes':len(eps),'metric_snapshot_2026_08_21':{k:float(m.loc[pd.Timestamp('2026-08-21'),k]) for k in METRICS+['delta20_soft','delta50_soft']},'variants':report}
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps(out,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
