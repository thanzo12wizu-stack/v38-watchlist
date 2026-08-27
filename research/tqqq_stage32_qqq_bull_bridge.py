from __future__ import annotations
from pathlib import Path
import json, numpy as np, pandas as pd

src=Path('research/tqqq_stage24_smart_bull_continuation.py').read_text(); prefix=src.split("CANDS={'CURRENT'")[0]; exec(compile(prefix,'stage24-prefix','exec'),globals())
print('\n=== STAGE32 QQQ BULL BRIDGE ===',flush=True)
P0={'base':.30,'fast_dd':-.065,'fast_rec':4,'rg_slow':.50,'rg_fast':.80,'gb':.90,'rg_mc_slow':40,'cooldown':20,'panic':1.0,'latch_exp':0,'latch_mc':999,'latch_confirm':3,'ext_exp':0,'ext_mc':35,'ext_max':40}
CUR=trace_smart(A,P0); tq_t=CUR['target'].copy(); risklock=CUR['risklock'].copy(); n=len(tq_t)
MC=A['mc']; nq=A['nq']; a50=A['a50']; a63=A['a63']; a200=A['a200']; lte21=A['lte21']
# QQQ open-to-open return aligned to the exact test dates.
qret=qqq.Open.astype(float).pct_change().reindex(pd.DatetimeIndex(dates)).to_numpy(float); qret=np.nan_to_num(qret,nan=0.0)
base_only=np.isclose(tq_t,.30,atol=1e-9)
healthy_base=(~risklock)&base_only&a200&a50&a63&(~lte21)&(MC>=35)

def run_bridge(qexp,nqmode):
    qt=np.zeros(n,float)
    nqok=(nq!=0) if nqmode=='nonred' else (nq>=2)
    on=healthy_base&nqok
    qt[on]=np.minimum(qexp,1.0-tq_t[on])
    te=np.zeros(n); qe=np.zeros(n); te[2:]=tq_t[:-2]; qe[2:]=qt[:-2]
    tt=np.zeros(n); qtturn=np.zeros(n); tt[2:]=np.abs(np.diff(tq_t))[:-1]; qtturn[2:]=np.abs(np.diff(qt))[:-1]
    sr=te*A['ret']+qe*qret-COST*(tt+qtturn)
    m=metrics(sr[2:]); m['avg_tqqq']=float(tq_t.mean()); m['avg_qqq']=float(qt.mean()); m['avg_capital']=float((tq_t+qt).mean()); m['avg_beta_proxy']=float((3*tq_t+qt).mean()); m['turnover_tqqq']=float(np.abs(np.diff(tq_t)).sum()); m['turnover_qqq']=float(np.abs(np.diff(qt)).sum()); m['bridge_days']=int(on.sum())
    y=dates.dt.year.to_numpy(); mi=metrics_window(sr,y<=2018); mo=metrics_window(sr,y>=2019); m.update({'is_cagr':mi['cagr'],'is_mdd':mi['mdd'],'oos_cagr':mo['cagr'],'oos_mdd':mo['mdd']})
    eq=np.cumprod(1+np.nan_to_num(sr,nan=0.)); pk=np.maximum.accumulate(eq); dd=eq/pk-1; j=int(np.argmin(dd)); ii=int(np.argmax(eq[:j+1])); m['dd_peak']=str(dates.iloc[ii].date()); m['dd_trough']=str(dates.iloc[j].date())
    return {'strategy_ret':sr,'effective':te+qe/3.0,'tq_eff':te,'q_eff':qe,'metrics':m,'q_target':qt}

def bull_capture_bridge(T):
    # Reuse same trough-to-peak dates and capture math; effective is beta-equivalent for display only.
    return bull_capture(T)

CANDS=[('CURRENT',0,'none')]
for q in (.20,.30,.40,.50):
    for mode in ('green','nonred'): CANDS.append((f'Q{int(q*100)}_{"G" if mode=="green" else "NR"}',q,mode))
rows=[]; caps=[]
R0,ag0=bull_capture(CUR); rows.append({'candidate':'CURRENT',**CUR['metrics'],**ag0,'avg_tqqq':float(tq_t.mean()),'avg_qqq':0.,'avg_capital':float(tq_t.mean()),'avg_beta_proxy':float((3*tq_t).mean()),'turnover_tqqq':float(np.abs(np.diff(tq_t)).sum()),'turnover_qqq':0.,'bridge_days':0,'dd_peak':'','dd_trough':''}); R0.insert(0,'candidate','CURRENT'); caps.append(R0)
for name,q,mode in CANDS[1:]:
    T=run_bridge(q,mode); R,ag=bull_capture_bridge(T); rows.append({'candidate':name,**T['metrics'],**ag}); R.insert(0,'candidate',name); caps.append(R)
H=pd.DataFrame(rows); C=pd.concat(caps,ignore_index=True); H['acceptable']=(H.mdd>=-.23)&(H.cagr>=.28)&(H.bull_capture_median>=.39); H['score']=H.cagr+.20*H.bull_capture_median-1.8*np.maximum(0,(-H.mdd)-.22)-.00005*(H.turnover_tqqq+H.turnover_qqq); H=H.sort_values(['acceptable','score','cagr'],ascending=False)
H.to_csv('tqqq_stage32_screen.csv',index=False); C.to_csv('tqqq_stage32_bull_capture.csv',index=False)
print('\n=== QQQ BRIDGE SCREEN ==='); print(H[['candidate','cagr','mdd','is_cagr','is_mdd','oos_cagr','oos_mdd','avg_tqqq','avg_qqq','avg_capital','avg_beta_proxy','turnover_qqq','bridge_days','bull_capture_median','bull_capture_mean','bull_avg_exp_median','dd_peak','dd_trough','acceptable','score']].to_string(index=False))
print('\n=== BULL YEARS ===')
for nm in H.candidate:
    print('\n',nm); print(C[C.candidate==nm][['year','bh','strategy','capture','avg_exp','pct_ge50','pct_ge60','pct_ge70','pct_ge90']].to_string(index=False))
Path('tqqq_stage32_summary.json').write_text(json.dumps({'screen':H.to_dict('records'),'note':'Stage32 does not increase TQQQ above the exact H30 target. Only when the current TQQQ target is exactly 30%, all Slow/Fast/MC locks are off, QQQ is above SMA200/SMA50/VWAP63/EMA21 and MC>=35, it invests part of otherwise-idle cash in unlevered QQQ. Green mode requires NQSAR Green/Blue; nonred mode also allows Yellow. QQQ is zero whenever TQQQ rises above 30% or a risk lock activates. 5bp one-way turnover cost is charged separately on both TQQQ and QQQ.'},ensure_ascii=False,indent=2,default=str))
