from __future__ import annotations
from pathlib import Path
import json, numpy as np, pandas as pd

src=Path('research/tqqq_stage27_bull_exit_diagnostics.py').read_text()
prefix=src.split("MODES=['qqq21'")[0]
exec(compile(prefix,'stage27-prefix','exec'),globals())
print('\n=== STAGE28 BULL EVENT QUALITY ===',flush=True)

# QQQ features from full history, point-in-time at signal close.
qc=qqq.Close.astype(float); qh=qqq.High.astype(float); ql=qqq.Low.astype(float); qpc=qc.shift(1)
qtr=pd.concat([(qh-ql),(qh-qpc).abs(),(ql-qpc).abs()],axis=1).max(axis=1)
qatr=qtr.ewm(alpha=1/14,adjust=False,min_periods=14).mean(); atrp=(qatr/qc)
qret=qc.pct_change(); rv20=qret.rolling(20).std()*np.sqrt(252)
s50q=qc.rolling(50).mean(); s200q=qc.rolling(200).mean(); sl50=s50q/s50q.shift(20)-1; sl200=s200q/s200q.shift(20)-1
dd20=qc/qc.rolling(20,min_periods=2).max()-1; dd60=qc/qc.rolling(60,min_periods=2).max()-1
align=lambda s:s.reindex(pd.DatetimeIndex(dates)).ffill().to_numpy(float)
ATR=align(atrp); RV=align(rv20); S50SL=align(sl50); S200SL=align(sl200); DD20=align(dd20); DD60=align(dd60); S50=align(s50q); S200=align(s200q)
MC=A['mc']; MC10=np.r_[np.full(10,np.nan),MC[10:]-MC[:-10]]
# days since most recent risk lock
DS=np.full(n,999,dtype=int); last=-999
for i in range(n):
    if risklock[i]: last=i; DS[i]=0
    else: DS[i]=i-last if last>-900 else 999

# Candidate fresh Green->Blue events, same healthy entry as Stage27.
events=[]
for i in range(1,n-45):
    trGB=nq[i-1]==2 and nq[i]==3
    if not (trGB and (not risklock[i]) and a200[i] and a50[i] and a63[i] and (not lte21[i]) and MC[i]>=35): continue
    row={'i':i,'date':str(dates.iloc[i].date()),'year':int(dates.iloc[i].year),'mc':float(MC[i]),'mc_d10':float(MC10[i]) if np.isfinite(MC10[i]) else np.nan,'atrp':float(ATR[i]),'rv20':float(RV[i]),'s50_slope20':float(S50SL[i]),'s200_slope20':float(S200SL[i]),'s50_gt_s200':bool(S50[i]>S200[i]),'dd20':float(DD20[i]),'dd60':float(DD60[i]),'days_since_lock':int(DS[i]),'s50_atr':float(A['s50a'][i])}
    # Signal i -> same convention as strategy target: effective from i+2 return.
    start=i+2
    for h in (10,20,40):
        rr=np.asarray(A['ret'][start:start+h],float); path=np.cumprod(1+np.nan_to_num(rr,nan=0.))-1
        row[f'r{h}']=float(path[-1]) if len(path) else np.nan; row[f'mae{h}']=float(path.min()) if len(path) else np.nan; row[f'mfe{h}']=float(path.max()) if len(path) else np.nan
    events.append(row)
E=pd.DataFrame(events); E.to_csv('tqqq_stage28_events.csv',index=False)
print('events',len(E),flush=True)

def stat(name,g):
    if len(g)==0:return None
    return {'group':name,'n':len(g),'r20_mean':float(g.r20.mean()),'r20_med':float(g.r20.median()),'r20_win':float((g.r20>0).mean()),'r20_worst':float(g.r20.min()),'mae20_med':float(g.mae20.median()),'mae20_worst':float(g.mae20.min()),'r40_mean':float(g.r40.mean()),'r40_med':float(g.r40.median()),'r40_win':float((g.r40>0).mean()),'r40_worst':float(g.r40.min()),'mae40_med':float(g.mae40.median()),'mae40_worst':float(g.mae40.min()),'n2011':int((g.year==2011).sum()),'n2017':int((g.year==2017).sum()),'n2023':int((g.year==2023).sum())}
S=[]; S.append(stat('ALL',E))
# Absolute, economically interpretable splits.
conds={
 'RV20<20%':E.rv20<.20,'RV20<25%':E.rv20<.25,'RV20<30%':E.rv20<.30,'ATR%<1.25':E.atrp<.0125,'ATR%<1.5':E.atrp<.015,'ATR%<2.0':E.atrp<.020,
 'S50slope>0':E.s50_slope20>0,'S50slope>1%':E.s50_slope20>.01,'S200slope>0':E.s200_slope20>0,'S200slope>0.5%':E.s200_slope20>.005,'S50>S200':E.s50_gt_s200,
 'MCd10>=0':E.mc_d10>=0,'MC>=45':E.mc>=45,'MC>=55':E.mc>=55,'MC>=65':E.mc>=65,'DSlock>=10':E.days_since_lock>=10,'DSlock>=20':E.days_since_lock>=20,'DSlock>=40':E.days_since_lock>=40,
 'DD20>-3%':E.dd20>-.03,'DD60>-5%':E.dd60>-.05,'S50ATR<2.5':E.s50_atr<2.5,
}
for k,c in conds.items(): S.append(stat(k,E[c]))
# Combinations chosen from concepts, not optimized numeric grids.
comb={
 'LOWVOL_TREND':(E.rv20<.25)&(E.s50_slope20>0)&(E.s200_slope20>0),
 'LOWVOL_TREND_MCUP':(E.rv20<.25)&(E.s50_slope20>0)&(E.s200_slope20>0)&(E.mc_d10>=0),
 'LOWVOL_TREND_FRESHSAFE':(E.rv20<.25)&(E.s50_slope20>0)&(E.s200_slope20>0)&(E.days_since_lock>=20),
 'CALM_STRONG':(E.atrp<.015)&(E.s50_slope20>.01)&(E.s200_slope20>0)&(E.mc>=45),
 'CALM_STRONG_MCUP':(E.atrp<.015)&(E.s50_slope20>.01)&(E.s200_slope20>0)&(E.mc>=45)&(E.mc_d10>=0),
 'CLEAN_TREND':(E.s50_gt_s200)&(E.s50_slope20>0)&(E.s200_slope20>0)&(E.dd20>-.03)&(E.days_since_lock>=20),
}
for k,c in comb.items(): S.append(stat(k,E[c]))
S=pd.DataFrame([x for x in S if x is not None]); S.to_csv('tqqq_stage28_groups.csv',index=False)
print('\n=== EVENT GROUPS ==='); print(S.sort_values(['r20_mean','n'],ascending=[False,False]).to_string(index=False))
print('\n=== YEAR FEATURE MEDIANS ===')
Y=E.groupby('year').agg(n=('date','size'),r20=('r20','mean'),r40=('r40','mean'),rv20=('rv20','median'),atrp=('atrp','median'),s50s=('s50_slope20','median'),s200s=('s200_slope20','median'),mc=('mc','median'),mcd=('mc_d10','median'),dsl=('days_since_lock','median'),dd20=('dd20','median'),dd60=('dd60','median')).reset_index()
print(Y[Y.year.isin([2011,2013,2017,2020,2021,2023,2024])].to_string(index=False)); Y.to_csv('tqqq_stage28_years.csv',index=False)
print('\n=== 2011 EVENTS ==='); print(E[E.year==2011][['date','mc','mc_d10','rv20','atrp','s50_slope20','s200_slope20','days_since_lock','dd20','dd60','r20','mae20','r40','mae40']].to_string(index=False))
print('\n=== 2017/2023 EVENTS ==='); print(E[E.year.isin([2017,2023])][['date','year','mc','mc_d10','rv20','atrp','s50_slope20','s200_slope20','days_since_lock','dd20','dd60','r20','mae20','r40','mae40']].to_string(index=False))
Path('tqqq_stage28_summary.json').write_text(json.dumps({'groups':S.to_dict('records'),'years':Y.to_dict('records'),'note':'Event study only. Fresh Green->Blue events use the same healthy-structure gate as Stage27. Outcomes start at i+2 to match the existing signal-close/next-session strategy lag convention. Filters are descriptive and concept-driven; no live rule is changed.'},ensure_ascii=False,indent=2,default=str))
