from __future__ import annotations
from pathlib import Path
import json, numpy as np, pandas as pd

# Reuse Stage23 exact risk hierarchy / tactical logic, but test only Blue-specific floors.
src=Path('research/tqqq_stage23_bull_floor_screen.py').read_text()
prefix=src.split("CANDS={'CURRENT'")[0]
exec(compile(prefix,'stage23-prefix','exec'),globals())
print('\n=== STAGE25 NQSAR BLUE FLOOR ===',flush=True)

CANDS={'CURRENT':{**BASEP,'floor_exp':0.0,'floor_mc':999,'floor_nq':'blue','floor_confirm':1}}
for exp in (.50,.60,.70,.80):
    for mc in (35,45,55):
        for cf in (1,3):
            CANDS[f"B{int(exp*100)}_MC{mc}_C{cf}"]={**BASEP,'floor_exp':exp,'floor_mc':mc,'floor_nq':'blue','floor_confirm':cf}

def winmetrics(sr):
    y=dates.dt.year.to_numpy(); out={}
    for lab,mask in [('is',y<=2018),('oos',y>=2019)]:
        x=np.asarray(sr)[mask]; x=x[np.isfinite(x)]; m=metrics(x); out[f'{lab}_cagr']=m['cagr']; out[f'{lab}_mdd']=m['mdd']
    return out

hist=[]; caps=[]
for name,p in CANDS.items():
    T=trace_variant(A,p); bc,ag=bull_capture(T)
    hist.append({'candidate':name,**T['metrics'],**winmetrics(T['strategy_ret']),**ag,'blue_floor_days':int(T['floor_ready'].sum()),'strong_days':int(T['strong'].sum())})
    bc.insert(0,'candidate',name); caps.append(bc)
H=pd.DataFrame(hist); C=pd.concat(caps,ignore_index=True)
# Require real Bull improvement but heavily penalize DD beyond 23%.
H['score']=H.cagr + .15*H.bull_capture_median - 1.3*np.maximum(0,(-H.mdd)-.23) - .00005*H.turnover
H=H.sort_values(['score','cagr'],ascending=False); H.to_csv('tqqq_stage25_screen.csv',index=False); C.to_csv('tqqq_stage25_bull_capture.csv',index=False)
print('\n=== BLUE FLOOR SCREEN ===')
print(H[['candidate','cagr','mdd','is_cagr','is_mdd','oos_cagr','oos_mdd','avg_exp','turnover','bull_capture_median','bull_capture_mean','bull_avg_exp_median','bull_pct_ge60_median','bull_pct_ge90_median','bull_pct_100_median','blue_floor_days','score']].to_string(index=False))
print('\n=== TOP 10 BULL YEARS ===')
for n in H.head(10).candidate:
    print('\n',n); print(C[C.candidate==n][['year','bh','strategy','capture','avg_exp','pct_ge60','pct_ge70','pct_ge90','pct_100']].to_string(index=False))
Path('tqqq_stage25_summary.json').write_text(json.dumps({'candidates':CANDS,'screen':H.to_dict('records'),'note':'Only added an intermediate floor when all risk locks are clear, QQQ is above SMA50 and VWAP63, MC is above threshold, and NQSAR is Blue. Strong Bull 100%, crisis RG, GB90%, and all risk-off rules remain unchanged. No +2.5ATR cap is applied to the Blue floor; that cap remains only on 100% Strong Bull.'},ensure_ascii=False,indent=2,default=str))
