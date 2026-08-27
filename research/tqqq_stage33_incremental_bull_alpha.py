from __future__ import annotations
from pathlib import Path
import json, numpy as np, pandas as pd

src=Path('research/tqqq_stage24_smart_bull_continuation.py').read_text()
prefix=src.split("CANDS={'CURRENT'")[0]
exec(compile(prefix,'stage24-prefix','exec'),globals())
print('\n=== STAGE33 INCREMENTAL BULL ALPHA ATTRIBUTION ===',flush=True)
P0={'base':.30,'fast_dd':-.065,'fast_rec':4,'rg_slow':.50,'rg_fast':.80,'gb':.90,'rg_mc_slow':40,'cooldown':20,'panic':1.0,'latch_exp':0,'latch_mc':999,'latch_confirm':3,'ext_exp':0,'ext_mc':35,'ext_max':40}
CUR=trace_smart(A,P0); t=CUR['target'].copy(); risklock=CUR['risklock'].copy(); n=len(t)
MC=A['mc']; nq=A['nq']; a50=A['a50']; a63=A['a63']; a200=A['a200']; lte21=A['lte21']; s50a=A['s50a']
dates=pd.to_datetime(F.date).reset_index(drop=True)
# Point-in-time auxiliary features.
qc=qqq.Close.astype(float); qr=qc.pct_change(); rv20=qr.rolling(20).std()*np.sqrt(252); s50q=qc.rolling(50).mean(); s200q=qc.rolling(200).mean(); sl50=s50q/s50q.shift(20)-1; sl200=s200q/s200q.shift(20)-1
idx=pd.DatetimeIndex(dates); align=lambda s:s.reindex(idx).ffill().to_numpy(float)
RV=align(rv20); SL50=align(sl50); SL200=align(sl200)
DS=np.full(n,999,dtype=int); last=-999
for i in range(n):
    if risklock[i]: last=i; DS[i]=0
    else: DS[i]=i-last if last>-900 else 999
# Days eligible for any generic Bull add-on: current target exactly 30%, no risk lock, healthy long structure.
elig=(~risklock)&np.isclose(t,.30,atol=1e-9)&a200&a50&a63&(~lte21)&(MC>=35)
# A decision at close i changes effective exposure for A['ret'][i+2] under the current backtest convention.
fwd=np.full(n,np.nan); fwd[:-2]=A['ret'][2:]
D=pd.DataFrame({'date':dates,'year':dates.dt.year,'is_oos':np.where(dates.dt.year<=2018,'IS','OOS'),'eligible':elig,'nq':nq,'mc':MC,'rv20':RV,'s50_slope':SL50,'s200_slope':SL200,'days_since_lock':DS,'s50_atr':s50a,'next_tqqq':fwd})
D=D[D.eligible & D.next_tqqq.notna()].copy()
# Label bins chosen before looking at results; no numeric optimization here.
D['nq_state']=D.nq.map({0:'Red',1:'Yellow',2:'Green',3:'Blue'})
D['mc_band']=pd.cut(D.mc,[-np.inf,45,55,65,np.inf],labels=['35-45','45-55','55-65','65+'],right=False)
D['rv_band']=pd.cut(D.rv20,[-np.inf,.15,.20,.25,np.inf],labels=['<15%','15-20%','20-25%','25%+'],right=False)
D['lock_band']=pd.cut(D.days_since_lock,[-1,20,60,np.inf],labels=['<20d','20-60d','60d+'],right=False)
D['atr_band']=pd.cut(D.s50_atr,[-np.inf,0,1,2,2.5,np.inf],labels=['<0','0-1','1-2','2-2.5','2.5+'],right=False)
D['ma_slope']=np.where((D.s50_slope>0)&(D.s200_slope>0),'both_up','not_both_up')
D.to_csv('tqqq_stage33_eligible_days.csv',index=False)

def stat(name,g):
    x=g.next_tqqq.to_numpy(float); x=x[np.isfinite(x)]
    if len(x)<5:return None
    return {'group':name,'n':len(x),'mean_1d':float(x.mean()),'median_1d':float(np.median(x)),'win_1d':float(np.mean(x>0)),'worst_1d':float(x.min()),'best_1d':float(x.max()),'ann_arith':float(x.mean()*252)}
rows=[]
for split,g in D.groupby('is_oos'):
    rows.append({'split':split,**stat('ALL',g)})
    for col in ['nq_state','mc_band','rv_band','lock_band','atr_band','ma_slope']:
        for val,h in g.groupby(col,observed=True):
            s=stat(f'{col}={val}',h)
            if s: rows.append({'split':split,**s})
S=pd.DataFrame(rows); S.to_csv('tqqq_stage33_groups.csv',index=False)
# Cross-period robustness for a small, concept-driven set only.
conds={
 'Blue':D.nq_state.eq('Blue'),
 'Green':D.nq_state.eq('Green'),
 'NonRed':~D.nq_state.eq('Red'),
 'MC65+':D.mc>=65,
 'BothMAUp':(D.s50_slope>0)&(D.s200_slope>0),
 'Calm<20':D.rv20<.20,
 'FarFromLock60+':D.days_since_lock>=60,
 'Blue_BothMAUp':D.nq_state.eq('Blue')&(D.s50_slope>0)&(D.s200_slope>0),
 'Blue_Calm':D.nq_state.eq('Blue')&(D.rv20<.20),
 'Blue_Far60':D.nq_state.eq('Blue')&(D.days_since_lock>=60),
 'Blue_MC65':D.nq_state.eq('Blue')&(D.mc>=65),
 'Green_BothMAUp':D.nq_state.eq('Green')&(D.s50_slope>0)&(D.s200_slope>0),
 'BothMAUp_Calm_Far60':(D.s50_slope>0)&(D.s200_slope>0)&(D.rv20<.20)&(D.days_since_lock>=60),
}
rob=[]
for name,c in conds.items():
    for split in ['IS','OOS']:
        s=stat(name,D[c & D.is_oos.eq(split)])
        if s: rob.append({'condition':name,'split':split,**{k:v for k,v in s.items() if k!='group'}})
R=pd.DataFrame(rob); R.to_csv('tqqq_stage33_robust.csv',index=False)
# Year attribution, especially 2011/2017/2023.
Y=[]
for y,g in D.groupby('year'):
    s=stat(str(y),g)
    if s: Y.append({'year':int(y),**{k:v for k,v in s.items() if k!='group'}})
Y=pd.DataFrame(Y); Y.to_csv('tqqq_stage33_years.csv',index=False)
print('\n=== SPLIT GROUPS ==='); print(S.to_string(index=False))
print('\n=== CONCEPT CONDITIONS IS/OOS ==='); print(R.to_string(index=False))
print('\n=== YEARS ==='); print(Y.to_string(index=False))
# Estimate the exact historical incremental CAGR impact of +10pp TQQQ on each concept condition, without changing any exits.
inc=[]
base_sr=CUR['strategy_ret'].copy()
for name,c in conds.items():
    mask=np.zeros(n,bool); mask[D.index.to_numpy(int)]=c.to_numpy(bool) if len(c)==len(D) else False
    # safer map by date since D has filtered original indexes retained
    mask=np.zeros(n,bool); mask[D.loc[c].index.to_numpy(int)]=True
    add=np.zeros(n,float); add[2:]=mask[:-2].astype(float)*.10
    sr=base_sr+add*A['ret']
    # charge 5bp on changes of the extra 10pp sleeve
    at=np.zeros(n,float); at[mask]=.10; tc=np.zeros(n); tc[2:]=np.abs(np.diff(at))[:-1]*COST; sr-=tc
    m=metrics(sr[2:]); inc.append({'condition':name,'cagr':m['cagr'],'mdd':m['mdd'],'delta_cagr':m['cagr']-CUR['metrics']['cagr'],'days':int(mask.sum())})
I=pd.DataFrame(inc).sort_values('delta_cagr',ascending=False); I.to_csv('tqqq_stage33_incremental_10pp.csv',index=False)
print('\n=== +10PP TQQQ INCREMENTAL ==='); print(I.to_string(index=False))
Path('tqqq_stage33_summary.json').write_text(json.dumps({'groups':S.to_dict('records'),'robust':R.to_dict('records'),'years':Y.to_dict('records'),'incremental10pp':I.to_dict('records'),'note':'Diagnostic attribution only. Eligible days are exact current H30 target=30%, all risk locks off, QQQ above SMA200/SMA50/VWAP63/EMA21, MC>=35. next_tqqq is the return that would be affected by an exposure decision at that signal close under the same i+2 lag convention. Conditions were concept-driven, not optimized thresholds.'},ensure_ascii=False,indent=2,default=str))
