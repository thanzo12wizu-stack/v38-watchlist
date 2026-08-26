from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
from research import tqqq_backtest_once as bt

START=pd.Timestamp('2011-01-03'); NSIM=1000; H=2520; BLOCK=120; SEED=150827; COST=.0005

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
    C=nq.Close.astype(float).to_numpy(); Hh=nq.High.astype(float).to_numpy(); L=nq.Low.astype(float).to_numpy(); S=psar(Hh,L)
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

def metrics(r):
    eq=np.cumprod(1+r); peak=np.maximum.accumulate(eq); dd=eq/peak-1
    return eq[-1]**(252/len(r))-1, dd.min(), eq[-1]

print('=== STAGE15C NUMPY JOINT-STATE MC ===',flush=True)
qqq=bt.dl_one('QQQ','2009-01-01'); tq=bt.dl_one('TQQQ','2010-01-01'); nqraw=bt.dl_one('NQ=F','2000-01-01'); vix=bt.dl_one('^VIX','1990-01-01'); mc,_=bt.compute_mc(); vs,_=bt.vix_state_series(vix); nq=nq_colors(nqraw)
c=qqq.Close.astype(float); h=qqq.High.astype(float); l=qqq.Low.astype(float); v=qqq.Volume.astype(float); pc=c.shift(1)
tr=pd.concat([(h-l),(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1); atr=tr.ewm(alpha=1/14,adjust=False,min_periods=14).mean(); e10=c.ewm(span=10,adjust=False).mean(); e21=c.ewm(span=21,adjust=False).mean(); s50=c.rolling(50).mean(); s200=c.rolling(200).mean(); tp=(h+l+c)/3; v63=(tp*v).rolling(63).sum()/v.rolling(63).sum(); v252=(tp*v).rolling(252,min_periods=200).sum()/v.rolling(252,min_periods=200).sum(); s50a=(c-s50)/atr; dd10=c/c.rolling(10,min_periods=2).max()-1
idx=qqq.index.intersection(tq.index); idx=idx[idx>=START]
F=pd.DataFrame(index=idx); F['ret']=tq.Open.pct_change().reindex(idx); F['mc']=mc.reindex(idx).ffill(); F['nq']=nq.reindex(idx).ffill(); F['panic']=vs.reindex(idx).ffill().astype(str).isin(['BOTTOM','RE-EXTREME']); F['a50']=(c>s50).reindex(idx); F['a63']=(c>v63).reindex(idx); F['a200']=(c>s200).reindex(idx); F['a252']=(c>v252).reindex(idx); F['gte10']=(c>e10).reindex(idx); F['lte21']=(c<e21).reindex(idx); F['s50a']=s50a.reindex(idx); F['dd10']=dd10.reindex(idx); F=F.dropna().reset_index(drop=True)
# NQ encode Red=0 Yellow=1 Green=2 Blue=3
mp={'Red':0,'Yellow':1,'Green':2,'Blue':3}; nqv=np.array([mp.get(str(x),1) for x in F.nq],dtype=np.int8)
A={'ret':F.ret.to_numpy(float),'mc':F.mc.to_numpy(float),'nq':nqv,'panic':F.panic.to_numpy(bool),'a50':F.a50.to_numpy(bool),'a63':F.a63.to_numpy(bool),'a200':F.a200.to_numpy(bool),'a252':F.a252.to_numpy(bool),'gte10':F.gte10.to_numpy(bool),'lte21':F.lte21.to_numpy(bool),'s50a':F.s50a.to_numpy(float),'dd10':F.dd10.to_numpy(float)}; L=len(F)
rng=np.random.default_rng(SEED); nblocks=int(np.ceil(H/BLOCK)); starts=rng.integers(0,L-BLOCK+1,size=(NSIM,nblocks)); offs=np.arange(BLOCK); paths=(starts[:,:,None]+offs).reshape(NSIM,-1)[:,:H]
CANDS={'defensive':(.35,-.065,4,.80,.90),'balanced':(.35,-.075,3,.70,1.0)}
rows=[]
for name,(baseexp,fastdd,fastrec,rg,gb) in CANDS.items():
  for sim in range(NSIM):
    ix=paths[sim]; ret=A['ret'][ix]; mcv=A['mc'][ix]; nq=A['nq'][ix]; panic=A['panic'][ix]; a50=A['a50'][ix]; a63=A['a63'][ix]; a200=A['a200'][ix]; a252=A['a252'][ix]; gte10=A['gte10'][ix]; lte21=A['lte21'][ix]; s50x=A['s50a'][ix]; dd=A['dd10'][ix]
    rawbear=(~a200)&(~a252); bear5=np.zeros(H,bool); score3=(a50.astype(int)+a63.astype(int)+(mcv>=35).astype(int)+(nq!=0).astype(int))>=3
    for i in range(4,H): bear5[i]=rawbear[i-4:i+1].all()
    rec=np.zeros(H,bool)
    for i in range(fastrec-1,H): rec[i]=gte10[i-fastrec+1:i+1].all()
    arm=np.empty(H,float)
    for i in range(H): arm[i]=np.min(s50x[max(0,i-19):i+1])
    base=np.zeros(H,float); slow=fast=mclock=False
    for i in range(H):
      if bear5[i]: slow=True
      if slow and (not rawbear[i]) and score3[i] and mcv[i]>=35: slow=False
      if mcv[i]<25: mclock=True
      if mclock and mcv[i]>=35 and score3[i] and nq[i]!=0: mclock=False
      if dd[i]<=fastdd and lte21[i]: fast=True
      if fast and rec[i]: fast=False
      x=0. if (slow or fast or mclock) else baseexp
      if x>0 and mcv[i]>=65 and nq[i]==3 and a50[i] and a63[i] and s50x[i]<=2.5: x=1.
      if panic[i] and s50x[i]<=-2: x=1.
      base[i]=x
    t=base.copy(); active=0; entry=0
    for i in range(1,H):
      transRG=nq[i-1]==0 and nq[i]==2; transGB=nq[i-1]==2 and nq[i]==3; transBG=nq[i-1]==3 and nq[i]==2; transBY=nq[i-1]==3 and nq[i]==1
      if active==0:
        if transRG and arm[i]<=-2 and mcv[i]>=35 and base[i]<=.10: active=1; entry=i+1
        elif transGB and arm[i]<=-1.5 and mcv[i]>=35 and not bear5[i]: active=2; entry=i+1
      if active:
        hold=max(0,i-(entry-1)); ex=(active==1 and ((nq[i] in (0,1)) or hold>=7)) or (active==2 and (transBG or transBY or nq[i]==0 or hold>=20))
        if ex: active=0
        else:
          total=rg if active==1 else gb
          if base[i]>=.999: total=1.
          t[i]=max(base[i],total)
    eff=np.zeros(H); eff[2:]=t[:-2]; turn=np.zeros(H); turn[2:]=np.abs(np.diff(t))[:-1]; sr=eff*ret-turn*COST; cg,md,en=metrics(sr[2:]); rows.append((name,sim,cg,md,en,float(t.mean())))
D=pd.DataFrame(rows,columns=['candidate','sim','cagr','mdd','end_multiple','avg_exp']); D.to_csv('tqqq_stage15c_mc.csv',index=False)
ss=[]
for cand,g in D.groupby('candidate'):
  cg=g.cagr.to_numpy(); md=g.mdd.to_numpy(); en=g.end_multiple.to_numpy(); q=lambda x,p:float(np.quantile(x,p)); cbin=np.floor(cg/.02)*.02; mbin=np.floor((-md)/.02)*.02
  ss.append({'candidate':cand,'n':len(g),'cagr_mode_lo':float(pd.Series(cbin).value_counts().idxmax()),'cagr_mode_hi':float(pd.Series(cbin).value_counts().idxmax()+.02),'mdd_mode_abs_lo':float(pd.Series(mbin).value_counts().idxmax()),'mdd_mode_abs_hi':float(pd.Series(mbin).value_counts().idxmax()+.02),'cagr_p05':q(cg,.05),'cagr_p25':q(cg,.25),'cagr_median':q(cg,.5),'cagr_p75':q(cg,.75),'cagr_p95':q(cg,.95),'mdd_p05':q(md,.05),'mdd_p25':q(md,.25),'mdd_median':q(md,.5),'mdd_p75':q(md,.75),'mdd_p95':q(md,.95),'end_p05':q(en,.05),'end_median':q(en,.5),'end_p95':q(en,.95),'prob_cagr25_mdd25':float(np.mean((cg>=.25)&(md>=-.25))),'prob_cagr28_mdd22':float(np.mean((cg>=.28)&(md>=-.22))),'prob_mdd30plus':float(np.mean(md<-.30)),'prob_cagr20below':float(np.mean(cg<.20))})
S=pd.DataFrame(ss); S.to_csv('tqqq_stage15c_summary.csv',index=False); print('\n=== NUMPY JOINT-STATE 1000 PATH SUMMARY ==='); print(S.to_string(index=False)); Path('tqqq_stage15c_summary.json').write_text(json.dumps({'seed':SEED,'block':BLOCK,'horizon_days':H,'nsim':NSIM,'summary':S.to_dict('records'),'note':'Joint-state 120-day moving-block bootstrap. TQQQ return + MC/NQSAR/QQQ/VIX state features sampled together. Slow bear, fast brake, MC lock, Bull boost and NQSAR RG/GB state machine rerun on each 10-year synthetic sequence. Source-block indicators are inherited; boundary history is approximate.'},ensure_ascii=False,indent=2))
