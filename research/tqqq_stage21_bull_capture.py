from __future__ import annotations
from pathlib import Path
import json, numpy as np, pandas as pd

# Reuse the exact Stage17 source-data construction and hierarchy rules.
src=Path('research/tqqq_stage17_hierarchy_crisis_fix.py').read_text()
prefix=src.split('NEW={')[0]
exec(compile(prefix,'stage17-prefix','exec'),globals())

print('\n=== STAGE21 BULL CAPTURE VALIDATION ===', flush=True)

P={'base':.30,'fast_dd':-.065,'fast_rec':4,'rg_slow':.50,'rg_fast':.80,'gb':.90,'rg_mc_slow':40,'cooldown':20,'panic':1.0}
YEARS=[2013,2017,2020,2021,2023,2024]

# Exact copy of run_hierarchy state machine, but return path diagnostics as well.
def trace_hierarchy(A,p):
    ret=A['ret']; mcv=A['mc']; nq=A['nq']; panic=A['panic']; a50=A['a50']; a63=A['a63']; a200=A['a200']; a252=A['a252']; gte10=A['gte10']; lte21=A['lte21']; s50x=A['s50a']; dd=A['dd10']
    n=len(ret); rawbear=(~a200)&(~a252)
    bear5=np.zeros(n,bool)
    for i in range(4,n): bear5[i]=rawbear[i-4:i+1].all()
    score3=(a50.astype(int)+a63.astype(int)+(mcv>=35).astype(int)+(nq!=0).astype(int))>=3
    fr=int(p['fast_rec']); rec=np.zeros(n,bool)
    for i in range(fr-1,n): rec[i]=gte10[i-fr+1:i+1].all()
    arm=np.empty(n,float)
    for i in range(n): arm[i]=np.min(s50x[max(0,i-19):i+1])

    base=np.zeros(n,float); slowA=np.zeros(n,bool); fastA=np.zeros(n,bool); mcA=np.zeros(n,bool); strong=np.zeros(n,bool); panicA=np.zeros(n,bool)
    slow=fast=mclock=False
    for i in range(n):
        if bear5[i]: slow=True
        if slow and (not rawbear[i]) and score3[i] and mcv[i]>=35: slow=False
        if mcv[i]<25: mclock=True
        if mclock and mcv[i]>=35 and score3[i] and nq[i]!=0: mclock=False
        if dd[i]<=p['fast_dd'] and lte21[i]: fast=True
        if fast and rec[i]: fast=False
        slowA[i]=slow; fastA[i]=fast; mcA[i]=mclock
        x=0. if (slow or fast or mclock) else p['base']
        if x>0 and mcv[i]>=65 and nq[i]==3 and a50[i] and a63[i] and s50x[i]<=2.5:
            x=1.0; strong[i]=True
        if panic[i] and s50x[i]<=-2:
            x=max(x,p.get('panic',1.0)); panicA[i]=True
        base[i]=min(1.,x)

    risklock=slowA|fastA|mcA
    t=base.copy(); active=0; entry=0; seen_blue=False; cool_until=0
    sleeve=np.zeros(n,np.int8)  # 0 none, 1 RG, 2 GB
    for i in range(1,n):
        trRG=nq[i-1]==0 and nq[i]==2; trGB=nq[i-1]==2 and nq[i]==3; trBG=nq[i-1]==3 and nq[i]==2; trBY=nq[i-1]==3 and nq[i]==1
        if active==0:
            rgmc=p['rg_mc_slow'] if slowA[i] else 35
            if trRG and arm[i]<=-2 and mcv[i]>=rgmc and risklock[i] and i>=cool_until:
                active=1; entry=i+1; seen_blue=False
            elif trGB and arm[i]<=-1.5 and mcv[i]>=35 and (not risklock[i]):
                active=2; entry=i+1; seen_blue=True
        if active==1:
            if nq[i]==3: seen_blue=True
            hold=max(0,i-(entry-1)); ex=((nq[i] in (0,1)) or hold>=7)
            if ex:
                if (not seen_blue) and slowA[i] and p['cooldown']>0: cool_until=i+p['cooldown']
                active=0
            else:
                if (not risklock[i]) and nq[i]==3:
                    active=2; entry=i+1; total=p['gb']
                else:
                    total=p['rg_slow'] if slowA[i] else p['rg_fast']
                if base[i]>=.999: total=1.
                t[i]=max(base[i],total); sleeve[i]=active
        elif active==2:
            hold=max(0,i-(entry-1)); ex=risklock[i] or trBG or trBY or nq[i]==0 or hold>=20
            if ex: active=0
            else:
                total=p['gb']
                if base[i]>=.999: total=1.
                t[i]=max(base[i],total); sleeve[i]=2

    eff=np.zeros(n); eff[2:]=t[:-2]
    turn=np.zeros(n); turn[2:]=np.abs(np.diff(t))[:-1]
    sr=eff*ret-turn*COST
    return {'target':t,'effective':eff,'strategy_ret':sr,'turnover_cost':turn*COST,'slow':slowA,'fast':fastA,'mclock':mcA,'risklock':risklock,'strong':strong,'panic':panicA,'sleeve':sleeve}

T=trace_hierarchy(A,P)
dates=pd.to_datetime(F.date).reset_index(drop=True)
qqq_close=qqq.Close.reindex(pd.DatetimeIndex(dates)).to_numpy(float)
tqqq_open=tq.Open.reindex(pd.DatetimeIndex(dates)).to_numpy(float)

# Diagnostics frame for audit.
D=pd.DataFrame({
    'date':dates,
    'qqq_close':qqq_close,
    'tqqq_open':tqqq_open,
    'tqqq_open_ret':A['ret'],
    'mc57':A['mc'],
    'nqsar':A['nq'],
    'target':T['target'],
    'effective_exposure':T['effective'],
    'strategy_ret':T['strategy_ret'],
    'slow_bear':T['slow'],
    'fast_crash':T['fast'],
    'mc_lock':T['mclock'],
    'risk_lock':T['risklock'],
    'strong_bull':T['strong'],
    'panic_buy':T['panic'],
    'sleeve':T['sleeve'],
})
D.to_csv('tqqq_stage21_daily.csv',index=False)

# Use tradable return interval after a signal-date start: start close -> subsequent opens.
def prodret(x):
    x=np.asarray(x,float); x=x[np.isfinite(x)]
    return float(np.prod(1+x)-1) if len(x) else np.nan

def first_days_ge(eff, i0, i1, threshold):
    # Effective exposure, trading days after start date. 0 means already true on start.
    z=np.flatnonzero(eff[i0:i1+1] >= threshold)
    return int(z[0]) if len(z) else None

def period_stats(label, kind, i0, i1):
    # Returns begin the session after i0; same interval for strategy and B&H.
    a=min(i0+1,len(D)-1); b=min(i1,len(D)-1)
    sl=slice(a,b+1)
    bh=prodret(A['ret'][sl]); st=prodret(T['strategy_ret'][sl])
    cap=st/bh if np.isfinite(bh) and bh>0 else np.nan
    eff=T['effective'][i0:i1+1]
    days=len(eff)
    out={
        'label':label,'kind':kind,'start':str(dates.iloc[i0].date()),'end':str(dates.iloc[i1].date()),'days':days,
        'tqqq_bh_return':bh,'strategy_return':st,'capture_ratio':cap,
        'avg_effective_exposure':float(np.mean(eff)),
        'pct_days_ge80':float(np.mean(eff>=.80)),'pct_days_ge90':float(np.mean(eff>=.90)),'pct_days_100':float(np.mean(eff>=.999)),
        'pct_days_strong_bull':float(np.mean(T['strong'][i0:i1+1])),
        'pct_days_risk_lock':float(np.mean(T['risklock'][i0:i1+1])),
        'days_to_80':first_days_ge(T['effective'],i0,i1,.80),
        'days_to_90':first_days_ge(T['effective'],i0,i1,.90),
        'days_to_100':first_days_ge(T['effective'],i0,i1,.999),
    }
    for h in (10,20,30):
        j=min(i0+h,i1)
        sh=slice(min(i0+1,len(D)-1),j+1)
        bhh=prodret(A['ret'][sh]); sth=prodret(T['strategy_ret'][sh])
        out[f'bh_{h}d']=bhh; out[f'strategy_{h}d']=sth; out[f'capture_{h}d']=sth/bhh if np.isfinite(bhh) and bhh>0 else np.nan
    return out

rows=[]
for y in YEARS:
    ids=np.flatnonzero(dates.dt.year.to_numpy()==y)
    if not len(ids): continue
    # Full calendar year.
    rows.append(period_stats(str(y),'calendar',int(ids[0]),int(ids[-1])))
    # Main bull leg in that year: lowest QQQ close, then highest close after that trough.
    q=qqq_close[ids]; k0=int(np.nanargmin(q)); i0=int(ids[k0]); tail=qqq_close[i0:int(ids[-1])+1]; k1=int(np.nanargmax(tail)); i1=i0+k1
    # If the max is same day (pathological), use calendar end.
    if i1<=i0: i1=int(ids[-1])
    rows.append(period_stats(str(y),'trough_to_peak',i0,i1))

R=pd.DataFrame(rows)
R.to_csv('tqqq_stage21_bull_capture.csv',index=False)

# Aggregate only positive trough-to-peak legs.
B=R[R.kind=='trough_to_peak'].copy()
agg={
    'median_capture_ratio':float(B.capture_ratio.median()),
    'mean_capture_ratio':float(B.capture_ratio.mean()),
    'median_avg_exposure':float(B.avg_effective_exposure.median()),
    'median_pct_days_ge90':float(B.pct_days_ge90.median()),
    'median_pct_days_100':float(B.pct_days_100.median()),
    'median_days_to_80':float(B.days_to_80.dropna().median()) if B.days_to_80.notna().any() else None,
    'median_days_to_90':float(B.days_to_90.dropna().median()) if B.days_to_90.notna().any() else None,
    'median_days_to_100':float(B.days_to_100.dropna().median()) if B.days_to_100.notna().any() else None,
}
print('\n=== BULL CAPTURE: TROUGH TO PEAK ===')
cols=['label','start','end','tqqq_bh_return','strategy_return','capture_ratio','avg_effective_exposure','pct_days_ge90','pct_days_100','days_to_80','days_to_90','days_to_100','bh_10d','strategy_10d','bh_20d','strategy_20d','bh_30d','strategy_30d']
print(B[cols].to_string(index=False))
print('\n=== AGGREGATE ===')
print(json.dumps(agg,indent=2))

# Also identify strongest missed-up days: TQQQ > +5% while effective exposure < 50%.
miss=D[(D.tqqq_open_ret>=.05)&(D.effective_exposure<.50)].copy()
miss['missed_return_points']=D.loc[miss.index,'tqqq_open_ret']*(1-D.loc[miss.index,'effective_exposure'])
miss=miss.sort_values('missed_return_points',ascending=False)
miss.head(50).to_csv('tqqq_stage21_missed_up_days.csv',index=False)
print('\n=== TOP MISSED +5% TQQQ DAYS (effective exposure <50%) ===')
print(miss[['date','tqqq_open_ret','effective_exposure','mc57','nqsar','slow_bear','fast_crash','mc_lock','strong_bull']].head(20).to_string(index=False))

summary={'params':P,'years':YEARS,'aggregate':agg,'periods':R.to_dict('records'),'note':'Rules are unchanged from Stage20 H30. Bull leg = lowest QQQ close within each selected calendar year to the highest subsequent QQQ close in that year. Strategy and B&H period returns use the same subsequent open-to-open TQQQ return interval. Effective exposure includes the existing execution lag.'}
Path('tqqq_stage21_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,default=str))
