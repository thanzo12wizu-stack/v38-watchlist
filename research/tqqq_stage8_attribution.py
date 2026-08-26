from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
from research import tqqq_backtest_once as bt

# Exact Stage7 low-DD candidate attribution.
# Candidate: b200&b252 confirmed 5d -> risk-off; score3 immediate -> risk-on;
# risk-on 60%, risk-off 10%, MC57<25 => 0%, VIX BOTTOM/RE-EXTREME + SMA50 <= -2ATR => 100%.


def psar(h,l,step=.02,mx=.08):
    h=np.asarray(h,float); l=np.asarray(l,float); n=len(h); s=np.zeros(n); bull=True; af=step; ep=l[0]; s[0]=l[0]
    for i in range(1,n):
        s[i]=s[i-1]+af*(ep-s[i-1])
        if bull:
            if l[i]<s[i]: bull=False; s[i]=ep; ep=l[i]; af=step
            elif h[i]>ep: ep=h[i]; af=min(af+step,mx)
        else:
            if h[i]>s[i]: bull=True; s[i]=ep; ep=h[i]; af=step
            elif l[i]<ep: ep=l[i]; af=min(af+step,mx)
    return s


def rsi(c,n=14):
    x=pd.Series(c,dtype=float); d=x.diff(); u=d.clip(lower=0); dn=(-d).clip(lower=0)
    au=u.ewm(alpha=1/n,adjust=False,min_periods=n).mean(); ad=dn.ewm(alpha=1/n,adjust=False,min_periods=n).mean()
    rs=au/ad.replace(0,np.nan); y=100-100/(1+rs); return y.where(ad.ne(0),100.).to_numpy()


def nq_colors(nq):
    C=nq.Close.astype(float).to_numpy(); H=nq.High.astype(float).to_numpy(); L=nq.Low.astype(float).to_numpy()
    S=psar(H,L); E=pd.Series(C,index=nq.index).ewm(span=21,adjust=False).mean().to_numpy(); R=rsi(C)
    a=C>S; st='Green' if a[0] else 'Yellow'; up=dn=99; prev=None; out=[]
    for i in range(len(C)):
        up=0 if i>0 and a[i] and not a[i-1] else up+1; dn=0 if i>0 and (not a[i]) and a[i-1] else dn+1
        ri=float(R[i]) if np.isfinite(R[i]) else 50.; dr=ri-prev if prev is not None else 0.
        if a[i]:
            if st=='Blue': st='Green' if C[i]<E[i] else 'Blue'
            else: st='Blue' if ri>52 and up>=2 and dr<=3 else 'Green'
        else:
            if st=='Red': st='Yellow' if ri>50 else 'Red'
            else: st='Red' if ri<47 and dn>=2 and dr>=-3 else 'Yellow'
        prev=ri; out.append(st)
    return pd.Series(out,index=nq.index,dtype='object')


def conf(s,n):
    s=s.fillna(False).astype(bool)
    return s.rolling(n,min_periods=n).sum().eq(n)


def mdd(r):
    eq=(1+r.fillna(0)).cumprod(); dd=eq/eq.cummax()-1
    return float(dd.min())


def period_stats(r):
    r=r.dropna(); n=len(r)
    if n==0:return dict(n=0,total=np.nan,cagr=np.nan,mdd=np.nan)
    total=float((1+r).prod()-1); years=n/252
    return dict(n=n,total=total,cagr=float((1+total)**(1/years)-1) if total>-1 and years>0 else np.nan,mdd=mdd(r))

print('=== STAGE8 ATTRIBUTION ===',flush=True)
qqq=bt.dl_one('QQQ','2009-01-01'); tqqq=bt.dl_one('TQQQ','2010-01-01'); vix=bt.dl_one('^VIX','1990-01-01'); nq=bt.dl_one('NQ=F','2000-01-01')
mc,_=bt.compute_mc(); vs,_=bt.vix_state_series(vix); ind=bt.indicators(qqq); nqcol=nq_colors(nq)

c=qqq.Close.astype(float); h=qqq.High.astype(float); l=qqq.Low.astype(float); v=qqq.Volume.astype(float)
sma50=c.rolling(50).mean(); sma200=c.rolling(200).mean(); tp=(h+l+c)/3
vw63=(tp*v).rolling(63).sum()/v.rolling(63).sum(); vw252=(tp*v).rolling(252,min_periods=200).sum()/v.rolling(252,min_periods=200).sum()
idx=ind.index.intersection(tqqq.index); idx=idx[idx>=bt.START]
ind=ind.reindex(idx); tqqq=tqqq.reindex(idx); mc=mc.reindex(idx).ffill(); vs=vs.reindex(idx).ffill(); nqcol=nqcol.reindex(idx).ffill()
c=c.reindex(idx); sma50=sma50.reindex(idx); sma200=sma200.reindex(idx); vw63=vw63.reindex(idx); vw252=vw252.reindex(idx)
a50=c>sma50; a63=c>vw63; a200=c>sma200; a252=c>vw252; mc35=mc>=35; nqnr=nqcol!='Red'
off=conf((~a200)&(~a252),5)
on=((a50.astype(int)+a63.astype(int)+mc35.astype(int)+nqnr.astype(int))>=3)
panic=vs.astype(str).isin(['BOTTOM','RE-EXTREME']) & (ind.sma50_atr<=-2.0)

ron=True; target=[]; regime=[]
for d in idx:
    if ron and bool(off.loc[d]): ron=False
    elif (not ron) and bool(on.loc[d]): ron=True
    x=.60 if ron else .10
    why='RISK_ON' if ron else 'RISK_OFF'
    if ron and pd.notna(mc.loc[d]) and float(mc.loc[d])<25:
        x=0.; why='MC25_ZERO'
    if (not ron) and bool(panic.loc[d]):
        x=1.; why='PANIC_100'
    target.append(x); regime.append(why)
target=pd.Series(target,index=idx,name='target'); regime=pd.Series(regime,index=idx,name='regime')
ret=bt.strategy_returns(target,tqqq.Open).fillna(0); bh=tqqq.Open.pct_change().fillna(0)
eq=(1+ret).cumprod(); bheq=(1+bh).cumprod(); dd=eq/eq.cummax()-1; bhdd=bheq/bheq.cummax()-1

# Annual table: calendar return, within-year DD, global-from-prior-peak DD, end-of-year DD, exposure composition.
annual=[]
for y,g in pd.DataFrame({'ret':ret,'bh':bh,'eq':eq,'dd':dd,'target':target,'regime':regime}).groupby(lambda x:x.year):
    yr=(1+g.ret).cumprod(); ydd=yr/yr.cummax()-1
    bhr=(1+g.bh).cumprod(); bhydd=bhr/bhr.cummax()-1
    annual.append(dict(year=int(y),strategy_return=float((1+g.ret).prod()-1),tqqq_return=float((1+g.bh).prod()-1),year_internal_mdd=float(ydd.min()),global_dd_min=float(g.dd.min()),year_end_global_dd=float(g.dd.iloc[-1]),tqqq_year_internal_mdd=float(bhydd.min()),avg_exposure=float(g.target.mean()),riskoff_days=int((g.regime=='RISK_OFF').sum()),mc25zero_days=int((g.regime=='MC25_ZERO').sum()),panic100_days=int((g.regime=='PANIC_100').sum())))
pd.DataFrame(annual).to_csv('tqqq_stage8_annual.csv',index=False)

# Start-year -> final metrics.
starts=[]
for y in range(idx[0].year,idx[-1].year+1):
    d=idx[idx.year>=y]
    if len(d)<100: continue
    rr=ret.reindex(d); st=period_stats(rr)
    starts.append(dict(start_year=y,end=str(d[-1].date()),multiple=float((1+rr).prod()),**st))
pd.DataFrame(starts).to_csv('tqqq_stage8_start_year.csv',index=False)

# Drawdown episodes: peak -> trough -> recovery.
peaks=eq.cummax(); indd=eq<peaks
episodes=[]; i=0; dates=list(idx)
while i<len(dates):
    if not bool(indd.iloc[i]): i+=1; continue
    start=i-1 if i>0 else i; j=i
    while j+1<len(dates) and bool(indd.iloc[j+1]): j+=1
    seg=dd.iloc[i:j+1]; trough_pos=i+int(np.argmin(seg.to_numpy()))
    recovered=(j+1<len(dates) and not bool(indd.iloc[j+1])); rec_pos=j+1 if recovered else None
    episodes.append(dict(peak_date=str(dates[start].date()),trough_date=str(dates[trough_pos].date()),recovery_date=str(dates[rec_pos].date()) if rec_pos is not None else '',max_dd=float(dd.iloc[trough_pos]),underwater_days=int((rec_pos-start) if rec_pos is not None else (len(dates)-1-start)),peak_equity=float(eq.iloc[start]),trough_equity=float(eq.iloc[trough_pos]),avg_exposure_to_trough=float(target.iloc[start:trough_pos+1].mean()),riskoff_days_to_trough=int((regime.iloc[start:trough_pos+1]=='RISK_OFF').sum()),panic_days_to_trough=int((regime.iloc[start:trough_pos+1]=='PANIC_100').sum())))
    i=j+1
edf=pd.DataFrame(episodes).sort_values('max_dd').head(20); edf.to_csv('tqqq_stage8_drawdowns.csv',index=False)

# Monthly + daily output for attribution.
daily=pd.DataFrame({'qqq_close':c,'mc57':mc,'nqsar':nqcol,'vix_state':vs,'sma50_atr':ind.sma50_atr,'above50':a50,'above63vw':a63,'above200':a200,'above252vw':a252,'off_confirmed':off,'reentry_score':a50.astype(int)+a63.astype(int)+mc35.astype(int)+nqnr.astype(int),'target':target,'regime':regime,'strategy_ret':ret,'tqqq_ret':bh,'equity':eq,'drawdown':dd})
daily.to_csv('tqqq_stage8_daily.csv')
monthly=pd.DataFrame({'strategy':ret,'tqqq':bh}).groupby([ret.index.year,ret.index.month]).apply(lambda x:pd.Series({'strategy_return':(1+x.strategy).prod()-1,'tqqq_return':(1+x.tqqq).prod()-1}),include_groups=False).reset_index(names=['year','month']); monthly.to_csv('tqqq_stage8_monthly.csv',index=False)

print('\n=== ANNUAL ===')
print(pd.DataFrame(annual).to_string(index=False,formatters={k:(lambda x:f'{x*100:.1f}%') for k in ['strategy_return','tqqq_return','year_internal_mdd','global_dd_min','year_end_global_dd','tqqq_year_internal_mdd','avg_exposure']}))
print('\n=== START YEAR -> 2026 ===')
print(pd.DataFrame(starts).to_string(index=False,formatters={'multiple':lambda x:f'{x:.1f}x','cagr':lambda x:f'{x*100:.1f}%','mdd':lambda x:f'{x*100:.1f}%','total':lambda x:f'{x*100:.0f}%'}))
print('\n=== TOP DRAWDOWNS ===')
print(edf.head(12).to_string(index=False,formatters={'max_dd':lambda x:f'{x*100:.1f}%','avg_exposure_to_trough':lambda x:f'{x*100:.1f}%'}))
summary={'full':period_stats(ret),'bh':period_stats(bh),'max_dd_date':str(dd.idxmin().date()),'max_dd':float(dd.min()),'end_equity':float(eq.iloc[-1]),'avg_exposure':float(target.mean())}
Path('tqqq_stage8_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)); print('\nSUMMARY',json.dumps(summary,ensure_ascii=False,indent=2))
