from __future__ import annotations
from pathlib import Path
import json, numpy as np, pandas as pd

src=Path('research/tqqq_stage26_event_driven_bull.py').read_text()
prefix=src.split("CANDS={'CURRENT'")[0]
exec(compile(prefix,'stage26-prefix','exec'),globals())
print('\n=== STAGE27 BULL EXIT DIAGNOSTICS ===',flush=True)

# Exact current baseline target/returns, before Bull Trend Event overlay.
CUR=trace_event(A,{**P0,'bte_exp':0,'bte_mc':999,'bte_exit':'yellow','sbh_exp':0,'sbh_exit':'blue'})
base_t=CUR['target'].copy(); risklock=CUR['risklock'].copy()
n=len(base_t); nq=A['nq']; mcv=A['mc']; a50=A['a50']; a63=A['a63']; a200=A['a200']; lte21=A['lte21']; gte10=A['gte10']

# TQQQ indicators computed on full history, then aligned to the exact test dates.
tqc=tq.Close.astype(float); tqe10=tqc.ewm(span=10,adjust=False).mean(); tqe21=tqc.ewm(span=21,adjust=False).mean(); tqdd10=tqc/tqc.rolling(10,min_periods=2).max()-1
idx_dates=pd.DatetimeIndex(dates)
tq_above10=(tqc>tqe10).reindex(idx_dates).ffill().fillna(False).to_numpy(bool)
tq_above21=(tqc>tqe21).reindex(idx_dates).ffill().fillna(False).to_numpy(bool)
tq_dd10=tqdd10.reindex(idx_dates).ffill().to_numpy(float)

# Consecutive-below helpers.
def below_confirm(above,days):
    out=np.zeros(len(above),bool); b=~above
    for i in range(days-1,len(above)): out[i]=b[i-days+1:i+1].all()
    return out
qqq_b10_1=~gte10; qqq_b10_2=below_confirm(gte10,2)
tq_b10_1=~tq_above10; tq_b10_2=below_confirm(tq_above10,2)
tq_b21_1=~tq_above21

# Bull Trend Event entry: fresh Green->Blue in healthy structure. 60% only.
def make_bte(exit_mode,cooldown=0):
    t=base_t.copy(); active=False; cool_until=0; entries=[]; exits=[]; holds=[]; ent=None
    for i in range(1,n):
        trGB=nq[i-1]==2 and nq[i]==3
        if not active:
            ok=trGB and i>=cool_until and (not risklock[i]) and a200[i] and a50[i] and a63[i] and (not lte21[i]) and mcv[i]>=35
            if ok: active=True; ent=i; entries.append(i)
        if active:
            common=risklock[i] or nq[i]==0 or (not a200[i]) or (not a50[i]) or (not a63[i])
            if exit_mode=='qqq21': bad=common or lte21[i]
            elif exit_mode=='qqq10_1': bad=common or qqq_b10_1[i]
            elif exit_mode=='qqq10_2': bad=common or qqq_b10_2[i]
            elif exit_mode=='tq10_1': bad=common or tq_b10_1[i]
            elif exit_mode=='tq10_2': bad=common or tq_b10_2[i]
            elif exit_mode=='tq21': bad=common or tq_b21_1[i]
            elif exit_mode=='tqdd8': bad=common or (tq_dd10[i]<=-.08)
            elif exit_mode=='tqdd10': bad=common or (tq_dd10[i]<=-.10)
            elif exit_mode=='yellow': bad=common or nq[i] in (0,1)
            else: raise ValueError(exit_mode)
            if bad:
                active=False; exits.append(i); holds.append(i-ent if ent is not None else 0); cool_until=i+cooldown; ent=None
            else:
                t[i]=max(t[i],.60)
    if active and ent is not None: holds.append(n-1-ent)
    eff=np.zeros(n); eff[2:]=t[:-2]; turn=np.zeros(n); turn[2:]=np.abs(np.diff(t))[:-1]; sr=eff*A['ret']-turn*COST
    m=metrics(sr[2:]); m['avg_exp']=float(t.mean()); m['turnover']=float(np.abs(np.diff(t)).sum()); m['entries']=len(entries); m['mean_hold']=float(np.mean(holds)) if holds else 0.; m['median_hold']=float(np.median(holds)) if holds else 0.
    y=dates.dt.year.to_numpy(); mi=msub(sr,y<=2018); mo=msub(sr,y>=2019); m.update({'is_cagr':mi['cagr'],'is_mdd':mi['mdd'],'oos_cagr':mo['cagr'],'oos_mdd':mo['mdd']})
    return {'target':t,'effective':eff,'sr':sr,'m':m,'entries':entries,'exits':exits,'holds':holds}

def maxdd(sr):
    x=np.asarray(sr,float); eq=np.cumprod(1+np.nan_to_num(x,nan=0.)); pk=np.maximum.accumulate(eq); dd=eq/pk-1; j=int(np.argmin(dd)); i=int(np.argmax(eq[:j+1])) if j>=0 else 0
    return {'peak':str(dates.iloc[i].date()),'trough':str(dates.iloc[j].date()),'mdd':float(dd[j])}

def capture(S):
    T={'strategy_ret':S['sr'],'effective':S['effective']}; R,ag=bull_capture(T); return R,ag

MODES=['qqq21','qqq10_1','qqq10_2','tq10_1','tq10_2','tq21','tqdd8','tqdd10','yellow']
rows=[]; caps=[]; details={}
# baseline
R0,ag0=bull_capture(CUR); rows.append({'candidate':'CURRENT',**CUR['metrics'],**ag0,'entries':0,'mean_hold':0,'median_hold':0,**maxdd(CUR['strategy_ret'])}); R0.insert(0,'candidate','CURRENT'); caps.append(R0)
for mode in MODES:
    for cd in (0,5):
        name=f'BTE60_{mode}_CD{cd}'; S=make_bte(mode,cd); R,ag=capture(S); rows.append({'candidate':name,**S['m'],**ag,**maxdd(S['sr'])}); R.insert(0,'candidate',name); caps.append(R)
        details[name]={'entries':[str(dates.iloc[i].date()) for i in S['entries']],'exits':[str(dates.iloc[i].date()) for i in S['exits']],'holds':S['holds']}
H=pd.DataFrame(rows); C=pd.concat(caps,ignore_index=True)
H['score']=H.cagr+.18*H.bull_capture_median-1.8*np.maximum(0,(-H.mdd)-.22)-.00005*H.turnover
H=H.sort_values(['score','cagr'],ascending=False); H.to_csv('tqqq_stage27_screen.csv',index=False); C.to_csv('tqqq_stage27_bull_capture.csv',index=False)
print('\n=== EXIT SCREEN ==='); print(H[['candidate','cagr','mdd','is_cagr','is_mdd','oos_cagr','oos_mdd','avg_exp','turnover','entries','mean_hold','bull_capture_median','bull_capture_mean','peak','trough','score']].to_string(index=False))
print('\n=== TOP 8 BULL YEARS ===')
for nm in H.head(8).candidate:
    print('\n',nm); print(C[C.candidate==nm][['year','bh','strategy','capture','avg_exp','pct_ge60','pct_ge70','pct_ge80','pct_ge90','pct_100']].to_string(index=False))
print('\n=== MAX DD / ENTRIES TOP 8 ===')
for nm in H.head(8).candidate:
    print(nm, H[H.candidate==nm][['peak','trough','mdd']].to_dict('records')[0], details.get(nm,{}))
Path('tqqq_stage27_summary.json').write_text(json.dumps({'screen':H.to_dict('records'),'details':details,'note':'Stage27 fixes Bull Trend Event at 60% and changes only its exit/cooldown. All risk-off, crisis RG, dip-GB, Strong Bull, VIX panic and 30% base rules are unchanged. TQQQ EMA/DD exits are computed from TQQQ close but execute with the same next-session target lag used by the backtest.'},ensure_ascii=False,indent=2,default=str))
