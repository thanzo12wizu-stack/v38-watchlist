from __future__ import annotations
from pathlib import Path
import json, numpy as np, pandas as pd

src=Path('research/tqqq_stage24_smart_bull_continuation.py').read_text(); prefix=src.split("CANDS={'CURRENT'")[0]; exec(compile(prefix,'stage24-prefix','exec'),globals())
print('\n=== STAGE31 VOL-TARGETED BULL ALLOCATION ===',flush=True)
P0={'base':.30,'fast_dd':-.065,'fast_rec':4,'rg_slow':.50,'rg_fast':.80,'gb':.90,'rg_mc_slow':40,'cooldown':20,'panic':1.0,'latch_exp':0,'latch_mc':999,'latch_confirm':3,'ext_exp':0,'ext_mc':35,'ext_max':40}
CUR=trace_smart(A,P0); base_t=CUR['target'].copy(); risklock=CUR['risklock'].copy(); n=len(base_t)
MC=A['mc']; nq=A['nq']; a50=A['a50']; a63=A['a63']; a200=A['a200']; lte21=A['lte21']
# QQQ 20d realized vol, annualized, aligned point-in-time.
qc=qqq.Close.astype(float); rv20=qc.pct_change().rolling(20).std()*np.sqrt(252); RV=rv20.reindex(pd.DatetimeIndex(dates)).ffill().to_numpy(float)
healthy=(~risklock)&a200&a50&a63&(~lte21)&(nq!=0)&(MC>=35)&np.isfinite(RV)&(RV>0)

def run_vt(tv,cap,step=.05):
    t=base_t.copy(); vt=np.zeros(n,float)
    for i in range(n):
        if not healthy[i] or base_t[i]>.300001: continue
        # 3x beta approximation: target portfolio vol / (3 * QQQ realized vol).
        x=float(np.clip(tv/(3.0*RV[i]),.30,cap)); x=round(x/step)*step; x=float(np.clip(x,.30,cap)); vt[i]=x; t[i]=max(t[i],x)
    eff=np.zeros(n); eff[2:]=t[:-2]; turn=np.zeros(n); turn[2:]=np.abs(np.diff(t))[:-1]; sr=eff*A['ret']-turn*COST
    m=metrics(sr[2:]); m['avg_exp']=float(t.mean()); m['turnover']=float(np.abs(np.diff(t)).sum()); m['vt_days']=int(np.sum(vt>.300001)); m['vt_avg_when_on']=float(vt[vt>0].mean()) if np.any(vt>0) else 0.
    y=dates.dt.year.to_numpy(); mi=metrics_window(sr,y<=2018); mo=metrics_window(sr,y>=2019); m.update({'is_cagr':mi['cagr'],'is_mdd':mi['mdd'],'oos_cagr':mo['cagr'],'oos_mdd':mo['mdd']})
    eq=np.cumprod(1+np.nan_to_num(sr,nan=0.)); pk=np.maximum.accumulate(eq); dd=eq/pk-1; j=int(np.argmin(dd)); ii=int(np.argmax(eq[:j+1])); m['dd_peak']=str(dates.iloc[ii].date()); m['dd_trough']=str(dates.iloc[j].date())
    return {'target':t,'effective':eff,'strategy_ret':sr,'metrics':m,'vt':vt}

CANDS=[('CURRENT',None,None)]
for tv in (.18,.20,.22,.24):
    for cap in (.50,.60): CANDS.append((f'VT{int(tv*100)}_C{int(cap*100)}',tv,cap))
rows=[]; caps=[]
R0,ag0=bull_capture(CUR); rows.append({'candidate':'CURRENT',**CUR['metrics'],**ag0,'vt_days':0,'vt_avg_when_on':0,'dd_peak':'','dd_trough':''}); R0.insert(0,'candidate','CURRENT'); caps.append(R0)
for name,tv,cp in CANDS[1:]:
    T=run_vt(tv,cp); R,ag=bull_capture(T); rows.append({'candidate':name,**T['metrics'],**ag}); R.insert(0,'candidate',name); caps.append(R)
H=pd.DataFrame(rows); C=pd.concat(caps,ignore_index=True); H['acceptable']=(H.mdd>=-.23)&(H.cagr>=.276)&(H.bull_capture_median>=.38); H['score']=H.cagr+.20*H.bull_capture_median-1.8*np.maximum(0,(-H.mdd)-.22)-.00005*H.turnover; H=H.sort_values(['acceptable','score','cagr'],ascending=False)
H.to_csv('tqqq_stage31_screen.csv',index=False); C.to_csv('tqqq_stage31_bull_capture.csv',index=False)
print('\n=== VOL TARGET SCREEN ==='); print(H[['candidate','cagr','mdd','is_cagr','is_mdd','oos_cagr','oos_mdd','avg_exp','turnover','bull_capture_median','bull_capture_mean','bull_avg_exp_median','vt_days','vt_avg_when_on','dd_peak','dd_trough','acceptable','score']].to_string(index=False))
print('\n=== BULL YEARS ===')
for nm in H.candidate:
    print('\n',nm); print(C[C.candidate==nm][['year','bh','strategy','capture','avg_exp','pct_ge50','pct_ge60','pct_ge70','pct_ge90']].to_string(index=False))
Path('tqqq_stage31_summary.json').write_text(json.dumps({'screen':H.to_dict('records'),'note':'Stage31 overlays a volatility-targeted intermediate allocation only when all risk locks are off, QQQ is above SMA200/SMA50/VWAP63/EMA21, MC>=35, NQSAR non-Red, and the exact current target is otherwise 30%. Desired TQQQ exposure = target portfolio vol /(3*QQQ RV20), clipped to 30-50/60% and rounded to 5pp. Existing H30 risk rules, RG/GB, Strong Bull100 and VIX panic are unchanged.'},ensure_ascii=False,indent=2,default=str))
