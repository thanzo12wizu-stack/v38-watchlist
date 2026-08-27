from __future__ import annotations
from pathlib import Path
import json, numpy as np, pandas as pd

src=Path('research/tqqq_stage27_bull_exit_diagnostics.py').read_text()
prefix=src.split("MODES=['qqq21'")[0]
exec(compile(prefix,'stage27-prefix','exec'),globals())
print('\n=== STAGE29 PROVE-IT BULL ACCELERATOR ===',flush=True)

# Exact current H30 baseline; Bull accelerator only overlays this target.
CUR=trace_event(A,{**P0,'bte_exp':0,'bte_mc':999,'bte_exit':'yellow','sbh_exp':0,'sbh_exit':'blue'})
base_t=CUR['target'].copy(); risklock=CUR['risklock'].copy(); n=len(base_t)
MC=A['mc']; nq=A['nq']; a50=A['a50']; a63=A['a63']; a200=A['a200']; lte21=A['lte21']

# TQQQ close / EMA10 aligned to signal dates. All proof and exit decisions are based on information known at that close.
tqc=tq.Close.astype(float); tqe10=tqc.ewm(span=10,adjust=False).mean(); idx_dates=pd.DatetimeIndex(dates)
tq_close=tqc.reindex(idx_dates).ffill().to_numpy(float); tq_above10=(tqc>tqe10).reindex(idx_dates).ffill().fillna(False).to_numpy(bool)

def apply_booster(p):
    t=base_t.copy(); active=False; stage=0; sig_i=-1; sig_px=np.nan; entries=[]; exits=[]; upgrades=[]; stage_days={1:0,2:0,3:0}
    for i in range(1,n):
        trGB=nq[i-1]==2 and nq[i]==3
        if not active:
            # Same broad healthy event definition as Stage28. No ex-post quality filter.
            entry_ok=trGB and (not risklock[i]) and a200[i] and a50[i] and a63[i] and (not lte21[i]) and MC[i]>=35
            if entry_ok:
                active=True; stage=1; sig_i=i; sig_px=float(tq_close[i]); entries.append(i)
        if active:
            # Booster is subordinate to existing risk hierarchy and leaves immediately when short trend fails.
            bad=risklock[i] or nq[i]==0 or (not a200[i]) or (not a50[i]) or (not a63[i]) or (not tq_above10[i])
            if bad:
                active=False; exits.append(i); stage=0; sig_i=-1; sig_px=np.nan
            else:
                age=i-sig_i; gain=(float(tq_close[i])/sig_px-1.0) if np.isfinite(sig_px) and sig_px>0 else -1.0
                if stage==1:
                    mode=p['proof']
                    if mode=='5d_pos': proven=(age>=5 and gain>0)
                    elif mode=='gain5': proven=(gain>=.05)
                    elif mode=='5d_gain5': proven=(age>=5 and gain>=.05)
                    else: proven=False
                    if proven:
                        stage=2; upgrades.append({'i':i,'stage':2,'gain':gain,'age':age})
                if stage>=2 and p.get('second',0)>0 and gain>=p.get('second_gain',.10):
                    if stage<3:
                        stage=3; upgrades.append({'i':i,'stage':3,'gain':gain,'age':age})
                exp=p['starter'] if stage==1 else (p.get('second',0) if stage==3 else p['upgrade'])
                t[i]=max(t[i],exp); stage_days[stage]+=1
    eff=np.zeros(n); eff[2:]=t[:-2]; turn=np.zeros(n); turn[2:]=np.abs(np.diff(t))[:-1]; sr=eff*A['ret']-turn*COST
    m=metrics(sr[2:]); m['avg_exp']=float(t.mean()); m['turnover']=float(np.abs(np.diff(t)).sum()); m['entries']=len(entries); m['upgrades']=len([u for u in upgrades if u['stage']==2]); m['second_upgrades']=len([u for u in upgrades if u['stage']==3]); m['starter_days']=stage_days[1]; m['upgrade_days']=stage_days[2]; m['second_days']=stage_days[3]
    y=dates.dt.year.to_numpy(); mi=msub(sr,y<=2018); mo=msub(sr,y>=2019); m.update({'is_cagr':mi['cagr'],'is_mdd':mi['mdd'],'oos_cagr':mo['cagr'],'oos_mdd':mo['mdd']})
    # Max DD episode
    eq=np.cumprod(1+np.nan_to_num(sr,nan=0.)); pk=np.maximum.accumulate(eq); dd=eq/pk-1; j=int(np.argmin(dd)); ii=int(np.argmax(eq[:j+1])); m['dd_peak']=str(dates.iloc[ii].date()); m['dd_trough']=str(dates.iloc[j].date())
    return {'target':t,'effective':eff,'sr':sr,'m':m,'entries':entries,'exits':exits,'upgrades':upgrades}

def prodret(x):
    x=np.asarray(x,float); x=x[np.isfinite(x)]; return float(np.prod(1+x)-1) if len(x) else np.nan

def cap_from(S):
    T={'strategy_ret':S['sr'],'effective':S['effective']}; return bull_capture(T)

CANDS={
 'CURRENT':None,
 'S40_ONLY':{'starter':.40,'upgrade':.40,'proof':'5d_pos','second':0},
 'S40_U60_5DPOS':{'starter':.40,'upgrade':.60,'proof':'5d_pos','second':0},
 'S40_U70_5DPOS':{'starter':.40,'upgrade':.70,'proof':'5d_pos','second':0},
 'S50_U70_5DPOS':{'starter':.50,'upgrade':.70,'proof':'5d_pos','second':0},
 'S40_U60_G5':{'starter':.40,'upgrade':.60,'proof':'gain5','second':0},
 'S40_U70_G5':{'starter':.40,'upgrade':.70,'proof':'gain5','second':0},
 'S50_U70_G5':{'starter':.50,'upgrade':.70,'proof':'gain5','second':0},
 'S40_U60_5DG5':{'starter':.40,'upgrade':.60,'proof':'5d_gain5','second':0},
 'S40_U70_5DG5':{'starter':.40,'upgrade':.70,'proof':'5d_gain5','second':0},
 'S40_U60_U80':{'starter':.40,'upgrade':.60,'proof':'gain5','second':.80,'second_gain':.10},
 'S40_U70_U80':{'starter':.40,'upgrade':.70,'proof':'gain5','second':.80,'second_gain':.10},
}
rows=[]; caps=[]; details={}
# Current baseline
R0,ag0=bull_capture(CUR); rows.append({'candidate':'CURRENT',**CUR['metrics'],**ag0,'entries':0,'upgrades':0,'second_upgrades':0,'starter_days':0,'upgrade_days':0,'second_days':0,'dd_peak':'','dd_trough':''}); R0.insert(0,'candidate','CURRENT'); caps.append(R0)
for name,p in CANDS.items():
    if name=='CURRENT': continue
    S=apply_booster(p); R,ag=cap_from(S); rows.append({'candidate':name,**S['m'],**ag}); R.insert(0,'candidate',name); caps.append(R)
    details[name]={'entries':[str(dates.iloc[i].date()) for i in S['entries']],'exits':[str(dates.iloc[i].date()) for i in S['exits']],'upgrades':[{'date':str(dates.iloc[u['i']].date()),'stage':u['stage'],'gain':u['gain'],'age':u['age']} for u in S['upgrades']]}
H=pd.DataFrame(rows); C=pd.concat(caps,ignore_index=True)
# Selection target: materially improve Bull capture/CAGR without giving back the hard-won risk control.
H['acceptable']=((H.mdd>=-.23)&(H.cagr>=.275)&(H.bull_capture_median>=.37))
H['score']=H.cagr+.20*H.bull_capture_median-2.0*np.maximum(0,(-H.mdd)-.22)-.00005*H.turnover
H=H.sort_values(['acceptable','score','cagr'],ascending=False); H.to_csv('tqqq_stage29_screen.csv',index=False); C.to_csv('tqqq_stage29_bull_capture.csv',index=False)
print('\n=== PROVE-IT SCREEN ==='); print(H[['candidate','cagr','mdd','is_cagr','is_mdd','oos_cagr','oos_mdd','avg_exp','turnover','bull_capture_median','bull_capture_mean','bull_avg_exp_median','entries','upgrades','second_upgrades','starter_days','upgrade_days','second_days','dd_peak','dd_trough','acceptable','score']].to_string(index=False))
print('\n=== ACCEPTABLE / TOP BULL YEARS ===')
for nm in H.head(8).candidate:
    print('\n',nm); print(C[C.candidate==nm][['year','bh','strategy','capture','avg_exp','pct_ge60','pct_ge70','pct_ge80','pct_ge90','pct_100']].to_string(index=False))
Path('tqqq_stage29_summary.json').write_text(json.dumps({'candidates':CANDS,'screen':H.to_dict('records'),'details':details,'note':'Stage29 is a prove-it accelerator. Fresh healthy Green->Blue starts at only 40-50% total exposure. It can scale to 60-70% only after the market proves the move via 5-day positive progress or +5% TQQQ, optionally to 80% after +10%. Extra exposure exits on TQQQ EMA10 failure, Red, risk lock, or major QQQ structure failure. Existing H30 risk side, crisis RG, dip-GB90, Strong Bull100 and VIX panic buy are unchanged.'},ensure_ascii=False,indent=2,default=str))
