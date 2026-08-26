from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
from research import tqqq_backtest_once as bt

START=pd.Timestamp('2011-01-03'); NSIM=1000; SEED=150827; COST=.0005

# Same NQSAR proxy as Stage13/14.
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

def metrics(x):
    x=np.asarray(x,float); eq=np.cumprod(1+x); peak=np.maximum.accumulate(eq); dd=eq/peak-1; years=len(x)/252
    return float(eq[-1]**(1/years)-1),float(dd.min()),float(eq[-1])

print('=== STAGE15 JOINT-STATE SYNTHETIC MARKET MC ===',flush=True)
qqq=bt.dl_one('QQQ','2009-01-01'); tq=bt.dl_one('TQQQ','2010-01-01'); nqraw=bt.dl_one('NQ=F','2000-01-01'); vix=bt.dl_one('^VIX','1990-01-01'); mc,_=bt.compute_mc(); vs,_=bt.vix_state_series(vix); nq=nq_colors(nqraw)
c=qqq.Close.astype(float); h=qqq.High.astype(float); l=qqq.Low.astype(float); v=qqq.Volume.astype(float); pc=c.shift(1)
tr=pd.concat([(h-l),(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1); atr=tr.ewm(alpha=1/14,adjust=False,min_periods=14).mean(); e10=c.ewm(span=10,adjust=False).mean(); e21=c.ewm(span=21,adjust=False).mean(); s50=c.rolling(50).mean(); s200=c.rolling(200).mean(); tp=(h+l+c)/3; v63=(tp*v).rolling(63).sum()/v.rolling(63).sum(); v252=(tp*v).rolling(252,min_periods=200).sum()/v.rolling(252,min_periods=200).sum(); s50a=(c-s50)/atr; dd10=c/c.rolling(10,min_periods=2).max()-1
idx=qqq.index.intersection(tq.index); idx=idx[idx>=START]
F=pd.DataFrame(index=idx)
F['tqret']=tq.Open.pct_change().reindex(idx)
F['mc']=mc.reindex(idx).ffill(); F['nq']=nq.reindex(idx).ffill().astype(str); F['panic']=vs.reindex(idx).ffill().astype(str).isin(['BOTTOM','RE-EXTREME'])
F['a50']=(c>s50).reindex(idx); F['a63']=(c>v63).reindex(idx); F['a200']=(c>s200).reindex(idx); F['a252']=(c>v252).reindex(idx); F['gt_e10']=(c>e10).reindex(idx); F['lt_e21']=(c<e21).reindex(idx); F['s50a']=s50a.reindex(idx); F['dd10']=dd10.reindex(idx)
F=F.dropna().reset_index(drop=True)

rng=np.random.default_rng(SEED)
def sample_blocks(df,block,n):
    chunks=[]; L=len(df)
    while sum(len(z) for z in chunks)<n:
        s=int(rng.integers(0,L-block+1)); chunks.append(df.iloc[s:s+block])
    return pd.concat(chunks,ignore_index=True).iloc[:n].reset_index(drop=True)

def run_path(z,p):
    n=len(z); rawbear=(~z.a200.astype(bool)) & (~z.a252.astype(bool)); bear_on=rawbear.rolling(5,min_periods=5).sum().eq(5)
    mc35=z.mc>=35; nqnr=z.nq!='Red'; score3=(z.a50.astype(int)+z.a63.astype(int)+mc35.astype(int)+nqnr.astype(int)).ge(3); arm20=z.s50a.rolling(20,min_periods=1).min(); rec10=z.gt_e10.astype(bool).rolling(p['fast_rec'],min_periods=p['fast_rec']).sum().eq(p['fast_rec'])
    trans=z.nq.shift(1).astype(str)+'->'+z.nq.astype(str)
    base=np.zeros(n); slow=fast=mclock=False
    for i in range(n):
        if bool(bear_on.iloc[i]): slow=True
        if slow and (not bool(rawbear.iloc[i])) and bool(score3.iloc[i]) and float(z.mc.iloc[i])>=35: slow=False
        if float(z.mc.iloc[i])<25: mclock=True
        if mclock and float(z.mc.iloc[i])>=35 and bool(score3.iloc[i]) and str(z.nq.iloc[i])!='Red': mclock=False
        if float(z.dd10.iloc[i])<=p['fast_dd'] and bool(z.lt_e21.iloc[i]): fast=True
        if fast and bool(rec10.iloc[i]): fast=False
        x=0.0 if (slow or fast or mclock) else p['baseexp']
        if x>0 and float(z.mc.iloc[i])>=65 and str(z.nq.iloc[i])=='Blue' and bool(z.a50.iloc[i]) and bool(z.a63.iloc[i]) and float(z.s50a.iloc[i])<=2.5: x=1.0
        if bool(z.panic.iloc[i]) and float(z.s50a.iloc[i])<=-2: x=1.0
        base[i]=x
    t=base.copy(); active=None; entry_i=None
    for i in range(n):
        cur=str(z.nq.iloc[i]); trn=str(trans.iloc[i])
        if active is None:
            k=None
            if trn=='Red->Green' and float(arm20.iloc[i])<=-2 and float(z.mc.iloc[i])>=35: k='RG'
            elif trn=='Green->Blue' and float(arm20.iloc[i])<=-1.5 and float(z.mc.iloc[i])>=35 and not bool(bear_on.iloc[i]): k='GB'
            if k=='RG' and float(base[i])>.10: k=None
            if k is not None: active=k; entry_i=i+1
        if active is not None:
            hold=max(0,i-(entry_i-1)); ex=False
            if active=='RG' and (cur in ('Yellow','Red') or hold>=7): ex=True
            if active=='GB' and (trn in ('Blue->Green','Blue->Yellow') or cur=='Red' or hold>=20): ex=True
            if ex: active=None; entry_i=None
            else:
                total=p['rg'] if active=='RG' else p['gb']
                if base[i]>=.999: total=1.0
                t[i]=max(base[i],total)
    # Same execution convention as bt.strategy_returns: close signal -> next session open; target shift(2).
    eff=np.r_[np.nan,np.nan,t[:-2]]; turn=np.r_[0.,0.,np.abs(np.diff(t))[:-1]]
    ret=np.nan_to_num(eff,nan=0.0)*z.tqret.to_numpy(float)-turn*COST
    return metrics(ret[2:]),float(np.mean(t))

CANDS={'defensive':dict(baseexp=.35,fast_dd=-.065,fast_rec=4,rg=.80,gb=.90),'balanced':dict(baseexp=.35,fast_dd=-.075,fast_rec=3,rg=.70,gb=1.00)}
rows=[]
for cand,p in CANDS.items():
    for block in [60,120]:
        for horizon_name,horizon in [('10y',2520),('full',len(F))]:
            for s in range(NSIM):
                z=sample_blocks(F,block,horizon); (cg,md,en),av=run_path(z,p); rows.append({'candidate':cand,'block':block,'horizon':horizon_name,'sim':s,'cagr':cg,'mdd':md,'end_multiple':en,'avg_exp':av})
D=pd.DataFrame(rows); D.to_csv('tqqq_stage15_joint_state_mc.csv',index=False)
ss=[]
for (cand,block,hor),g in D.groupby(['candidate','block','horizon']):
    cg=g.cagr.to_numpy(); md=g.mdd.to_numpy(); en=g.end_multiple.to_numpy(); q=lambda x,p:float(np.quantile(x,p)); cbin=np.floor(cg/.02)*.02; mbin=np.floor((-md)/.02)*.02
    ss.append({'candidate':cand,'block':block,'horizon':hor,'n':len(g),'cagr_mode_lo':float(pd.Series(cbin).value_counts().idxmax()),'mdd_mode_abs_lo':float(pd.Series(mbin).value_counts().idxmax()),'cagr_p05':q(cg,.05),'cagr_p25':q(cg,.25),'cagr_median':q(cg,.5),'cagr_p75':q(cg,.75),'cagr_p95':q(cg,.95),'mdd_p05':q(md,.05),'mdd_p25':q(md,.25),'mdd_median':q(md,.5),'mdd_p75':q(md,.75),'mdd_p95':q(md,.95),'end_p05':q(en,.05),'end_median':q(en,.5),'end_p95':q(en,.95),'prob_cagr25_mdd25':float(np.mean((cg>=.25)&(md>=-.25))),'prob_cagr28_mdd22':float(np.mean((cg>=.28)&(md>=-.22))),'prob_mdd30plus':float(np.mean(md<-.30)),'prob_cagr20below':float(np.mean(cg<.20))})
S=pd.DataFrame(ss); S.to_csv('tqqq_stage15_summary.csv',index=False); print('\n=== JOINT STATE SUMMARY ==='); print(S.to_string(index=False))
Path('tqqq_stage15_summary.json').write_text(json.dumps({'seed':SEED,'nsim':NSIM,'summary':S.to_dict('records'),'note':'Joint-state moving-block bootstrap: TQQQ open return and contemporaneous MC/NQSAR/QQQ/VIX-derived state features are sampled together; slow/fast/MC locks and NQSAR tactical state machine are rerun on each synthetic sequence. Indicators inside each source block are inherited from historical data, so block-boundary feature history is approximate.'},ensure_ascii=False,indent=2))
