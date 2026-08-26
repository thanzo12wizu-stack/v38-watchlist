from __future__ import annotations
import json, math
from pathlib import Path
import numpy as np
import pandas as pd
from research import tqqq_backtest_once as bt

START=pd.Timestamp('2011-01-03'); COST=.0005; NSIM=1000; SEED=20260827

# --- NQSAR reconstruction (same as integrated study) ---
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
    au=u.ewm(alpha=1/n,adjust=False,min_periods=n).mean(); ad=dn.ewm(alpha=1/n,adjust=False,min_periods=n).mean(); rs=au/ad.replace(0,np.nan)
    y=100-100/(1+rs); return y.where(ad.ne(0),100.).to_numpy()

def nq_colors(nq):
    C=nq.Close.astype(float).to_numpy(); H=nq.High.astype(float).to_numpy(); L=nq.Low.astype(float).to_numpy(); S=psar(H,L)
    E=pd.Series(C,index=nq.index).ewm(span=21,adjust=False).mean().to_numpy(); R=rsi(C); a=C>S
    st='Green' if a[0] else 'Yellow'; up=dn=99; prev=None; out=[]
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

def conf(s,n): return s.fillna(False).astype(bool).rolling(n,min_periods=n).sum().eq(n)

def metrics(arr):
    x=np.asarray(arr,float); eq=np.cumprod(1+x); peak=np.maximum.accumulate(eq); dd=eq/peak-1; years=len(x)/252
    cagr=eq[-1]**(1/years)-1
    return cagr,float(dd.min()),float(eq[-1])

print('=== STAGE14 MONTE CARLO SEQUENCE ROBUSTNESS ===',flush=True)
qqq=bt.dl_one('QQQ','2009-01-01'); tq=bt.dl_one('TQQQ','2010-01-01'); nqraw=bt.dl_one('NQ=F','2000-01-01'); vix=bt.dl_one('^VIX','1990-01-01'); mc,_=bt.compute_mc(); vs,_=bt.vix_state_series(vix); nq=nq_colors(nqraw)
c=qqq.Close.astype(float); h=qqq.High.astype(float); l=qqq.Low.astype(float); v=qqq.Volume.astype(float); pc=c.shift(1)
tr=pd.concat([(h-l),(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1); atr=tr.ewm(alpha=1/14,adjust=False,min_periods=14).mean(); e10=c.ewm(span=10,adjust=False).mean(); e21=c.ewm(span=21,adjust=False).mean(); s50=c.rolling(50).mean(); s200=c.rolling(200).mean(); tp=(h+l+c)/3; v63=(tp*v).rolling(63).sum()/v.rolling(63).sum(); v252=(tp*v).rolling(252,min_periods=200).sum()/v.rolling(252,min_periods=200).sum(); s50a=(c-s50)/atr; dd10=c/c.rolling(10,min_periods=2).max()-1
IDX=qqq.index.intersection(tq.index); IDX=IDX[IDX>=START]; tq=tq.reindex(IDX); nq=nq.reindex(IDX).ffill(); mc=mc.reindex(IDX).ffill(); vs=vs.reindex(IDX).ffill(); c=c.reindex(IDX); e10=e10.reindex(IDX); e21=e21.reindex(IDX); s50=s50.reindex(IDX); s200=s200.reindex(IDX); v63=v63.reindex(IDX); v252=v252.reindex(IDX); s50a=s50a.reindex(IDX); dd10=dd10.reindex(IDX)
a50=c>s50; a63=c>v63; a200=c>s200; a252=c>v252; mc35=mc>=35; nqnr=nq!='Red'; score3=(a50.astype(int)+a63.astype(int)+mc35.astype(int)+nqnr.astype(int)).ge(3); rawbear=(~a200)&(~a252); bear_on=conf(rawbear,5); arm20=s50a.rolling(20,min_periods=1).min(); prev=nq.shift(1); trans=(prev.astype(str)+'->'+nq.astype(str)).where(prev.notna()); panic=vs.astype(str).isin(['BOTTOM','RE-EXTREME'])

def build_base(baseexp,bull_mc,fast_dd,fast_rec):
    out=np.zeros(len(IDX)); slow=False; fast=False; mclock=False; rec10=conf(c>e10,fast_rec)
    for i,d in enumerate(IDX):
        if bool(bear_on.loc[d]): slow=True
        if slow and (not bool(rawbear.loc[d])) and bool(score3.loc[d]) and float(mc.loc[d])>=35: slow=False
        if float(mc.loc[d])<25: mclock=True
        if mclock and float(mc.loc[d])>=35 and bool(score3.loc[d]) and str(nq.loc[d])!='Red': mclock=False
        if float(dd10.loc[d])<=fast_dd and float(c.loc[d])<float(e21.loc[d]): fast=True
        if fast and bool(rec10.loc[d]): fast=False
        x=0.0 if (slow or fast or mclock) else baseexp
        if x>0 and float(mc.loc[d])>=bull_mc and str(nq.loc[d])=='Blue' and bool(a50.loc[d]) and bool(a63.loc[d]) and float(s50a.loc[d])<=2.5: x=1.0
        if bool(panic.loc[d]) and float(s50a.loc[d])<=-2.0: x=1.0
        out[i]=x
    return pd.Series(out,index=IDX,dtype=float)

def integrated(base,rg,gb):
    t=base.copy(); active=None; entry_i=None
    for i,d in enumerate(IDX[:-2]):
        cur=str(nq.loc[d]); trn=str(trans.loc[d]) if pd.notna(trans.loc[d]) else ''
        if active is None:
            k=None
            if trn=='Red->Green' and float(arm20.loc[d])<=-2 and float(mc.loc[d])>=35: k='RG'
            elif trn=='Green->Blue' and float(arm20.loc[d])<=-1.5 and float(mc.loc[d])>=35 and not bool(bear_on.loc[d]): k='GB'
            if k=='RG' and float(base.loc[d])>.10: k=None
            if k is not None: active=k; entry_i=i+1
        if active is not None:
            hold=max(0,i-(entry_i-1)); ex=False
            if active=='RG' and (cur in ('Yellow','Red') or hold>=7): ex=True
            if active=='GB' and (trn in ('Blue->Green','Blue->Yellow') or cur=='Red' or hold>=20): ex=True
            if ex: active=None; entry_i=None
            else:
                total=rg if active=='RG' else gb
                if float(base.loc[d])>=.999: total=1.0
                t.loc[d]=max(float(base.loc[d]),total)
    return t

def strat_returns(target): return bt.strategy_returns(target,tq.Open).reindex(IDX).fillna(0.0)

CANDS={
 'defensive': dict(baseexp=.35,bull_mc=65,fast_dd=-.065,fast_rec=4,rg=.80,gb=.90),
 'balanced': dict(baseexp=.35,bull_mc=65,fast_dd=-.075,fast_rec=3,rg=.70,gb=1.00),
}
real={}
for name,p in CANDS.items():
    b=build_base(p['baseexp'],p['bull_mc'],p['fast_dd'],p['fast_rec']); t=integrated(b,p['rg'],p['gb']); r=strat_returns(t)
    cg,md,en=metrics(r.values); real[name]={'cagr':cg,'mdd':md,'end':en,'avg_exp':float(t.mean()),'turnover':float(t.diff().abs().sum())}; r.to_csv(f'tqqq_stage14_{name}_daily_returns.csv',header=['ret'])
    print(name,real[name],flush=True)

rng=np.random.default_rng(SEED)
def moving_block(x,block,n):
    out=[]; L=len(x)
    while len(out)<n:
        s=int(rng.integers(0,max(1,L-block+1))); out.extend(x[s:s+block])
    return np.asarray(out[:n],float)

def sim_one(x,block,horizon):
    z=moving_block(x,block,horizon); return metrics(z)

rows=[]
for name in CANDS:
    x=pd.read_csv(f'tqqq_stage14_{name}_daily_returns.csv',index_col=0).iloc[:,0].to_numpy(float)
    for block in [20,60]:
        for horizon_name,horizon in [('full',len(x)),('10y',2520)]:
            for s in range(NSIM):
                cg,md,en=sim_one(x,block,horizon); rows.append({'candidate':name,'method':f'block{block}','horizon':horizon_name,'sim':s,'cagr':cg,'mdd':md,'end_multiple':en})
D=pd.DataFrame(rows); D.to_csv('tqqq_stage14_monte_carlo.csv',index=False)

# Summary + modal bins (2%-pt CAGR, 2%-pt MDD bins)
sums=[]
for (cand,method,hor),g in D.groupby(['candidate','method','horizon']):
    cg=g.cagr.to_numpy(); md=g.mdd.to_numpy(); en=g.end_multiple.to_numpy()
    cbin=np.floor(cg/.02)*.02; mbin=np.floor((-md)/.02)*.02
    c_mode=float(pd.Series(cbin).value_counts().idxmax()); m_mode=float(pd.Series(mbin).value_counts().idxmax())
    q=lambda a,p: float(np.quantile(a,p))
    sums.append({'candidate':cand,'method':method,'horizon':hor,'n':len(g),
      'cagr_mode_bin_lo':c_mode,'cagr_mode_bin_hi':c_mode+.02,'mdd_mode_abs_bin_lo':m_mode,'mdd_mode_abs_bin_hi':m_mode+.02,
      'cagr_p05':q(cg,.05),'cagr_p25':q(cg,.25),'cagr_median':q(cg,.5),'cagr_p75':q(cg,.75),'cagr_p95':q(cg,.95),
      'mdd_p05':q(md,.05),'mdd_p25':q(md,.25),'mdd_median':q(md,.5),'mdd_p75':q(md,.75),'mdd_p95':q(md,.95),
      'end_p05':q(en,.05),'end_median':q(en,.5),'end_p95':q(en,.95),
      'prob_cagr25_mdd25':float(np.mean((cg>=.25)&(md>=-.25))),
      'prob_cagr28_mdd22':float(np.mean((cg>=.28)&(md>=-.22))),
      'prob_mdd30plus':float(np.mean(md<-.30)),
      'prob_cagr20below':float(np.mean(cg<.20))})
S=pd.DataFrame(sums); S.to_csv('tqqq_stage14_summary.csv',index=False)
print('\n=== SUMMARY ===')
print(S.to_string(index=False))
Path('tqqq_stage14_summary.json').write_text(json.dumps({'seed':SEED,'nsim':NSIM,'real':real,'summary':S.to_dict('records'),'note':'Moving-block bootstrap of realized integrated strategy daily returns. Preserves local return clustering inside blocks; does not rerun signals on synthetic joint market states.'},ensure_ascii=False,indent=2))
