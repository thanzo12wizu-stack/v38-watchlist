from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
from research import tqqq_backtest_once as bt

START=pd.Timestamp('2011-01-03')
NSIM=1000
H=2520
BLOCK=120
SEED=160827
COST=.0005

# ---------- NQSAR reconstruction ----------
def psar(h,l,step=.02,mx=.08):
    h=np.asarray(h,float); l=np.asarray(l,float); n=len(h)
    s=np.zeros(n); bull=True; af=step; ep=l[0]; s[0]=l[0]
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
    au=u.ewm(alpha=1/n,adjust=False,min_periods=n).mean()
    ad=dn.ewm(alpha=1/n,adjust=False,min_periods=n).mean()
    rs=au/ad.replace(0,np.nan)
    y=100-100/(1+rs)
    return y.where(ad.ne(0),100.).to_numpy()

def nq_colors(nq):
    C=nq.Close.astype(float).to_numpy(); Hh=nq.High.astype(float).to_numpy(); L=nq.Low.astype(float).to_numpy()
    S=psar(Hh,L); E=pd.Series(C,index=nq.index).ewm(span=21,adjust=False).mean().to_numpy(); R=rsi(C); a=C>S
    st='Green' if a[0] else 'Yellow'; up=dn=99; prev=None; out=[]
    for i in range(len(C)):
        up=0 if i>0 and a[i] and not a[i-1] else up+1
        dn=0 if i>0 and (not a[i]) and a[i-1] else dn+1
        ri=float(R[i]) if np.isfinite(R[i]) else 50.; dr=ri-prev if prev is not None else 0.
        if a[i]:
            if st=='Blue': st='Green' if C[i]<E[i] else 'Blue'
            else: st='Blue' if ri>52 and up>=2 and dr<=3 else 'Green'
        else:
            if st=='Red': st='Yellow' if ri>50 else 'Red'
            else: st='Red' if ri<47 and dn>=2 and dr>=-3 else 'Yellow'
        prev=ri; out.append(st)
    return pd.Series(out,index=nq.index,dtype='object')

# ---------- metrics / strategy ----------
def metrics(r):
    r=np.asarray(r,float)
    eq=np.cumprod(1+r); peak=np.maximum.accumulate(eq); dd=eq/peak-1
    return {'cagr':float(eq[-1]**(252/len(r))-1),'mdd':float(dd.min()),'end':float(eq[-1])}

def run_strategy(A,p):
    ret=A['ret']; mcv=A['mc']; nq=A['nq']; panic=A['panic']; a50=A['a50']; a63=A['a63']; a200=A['a200']; a252=A['a252']; gte10=A['gte10']; lte21=A['lte21']; s50x=A['s50a']; dd=A['dd10']
    n=len(ret)
    rawbear=(~a200)&(~a252)
    bear5=np.zeros(n,bool)
    for i in range(4,n): bear5[i]=rawbear[i-4:i+1].all()
    score3=(a50.astype(int)+a63.astype(int)+(mcv>=35).astype(int)+(nq!=0).astype(int))>=3
    rec=np.zeros(n,bool)
    fr=int(p['fast_rec'])
    for i in range(fr-1,n): rec[i]=gte10[i-fr+1:i+1].all()
    arm=np.empty(n,float)
    for i in range(n): arm[i]=np.min(s50x[max(0,i-19):i+1])

    base=np.zeros(n,float); slow=fast=mclock=False
    for i in range(n):
        if bear5[i]: slow=True
        if slow and (not rawbear[i]) and score3[i] and mcv[i]>=35: slow=False
        if mcv[i]<25: mclock=True
        if mclock and mcv[i]>=35 and score3[i] and nq[i]!=0: mclock=False
        if dd[i]<=p['fast_dd'] and lte21[i]: fast=True
        if fast and rec[i]: fast=False
        x=0. if (slow or fast or mclock) else p['base']
        if x>0 and mcv[i]>=p['bull_mc'] and nq[i]==3 and a50[i] and a63[i] and s50x[i]<=2.5:
            x=p['bull_exp']
        if panic[i] and s50x[i]<=-2:
            x=max(x,p['panic_exp'])
        base[i]=min(1.,x)

    t=base.copy(); active=0; entry=0
    for i in range(1,n):
        transRG=nq[i-1]==0 and nq[i]==2
        transGB=nq[i-1]==2 and nq[i]==3
        transBG=nq[i-1]==3 and nq[i]==2
        transBY=nq[i-1]==3 and nq[i]==1
        if active==0:
            if transRG and arm[i]<=-2 and mcv[i]>=35 and base[i]<=.10:
                active=1; entry=i+1
            elif transGB and arm[i]<=-1.5 and mcv[i]>=35 and not bear5[i]:
                active=2; entry=i+1
        if active:
            hold=max(0,i-(entry-1))
            ex=(active==1 and ((nq[i] in (0,1)) or hold>=7)) or (active==2 and (transBG or transBY or nq[i]==0 or hold>=20))
            if ex: active=0
            else:
                total=p['rg'] if active==1 else p['gb']
                if base[i]>=.999: total=1.
                t[i]=max(base[i],total)

    eff=np.zeros(n); eff[2:]=t[:-2]
    turn=np.zeros(n); turn[2:]=np.abs(np.diff(t))[:-1]
    sr=eff*ret-turn*COST
    m=metrics(sr[2:]); m['avg_exp']=float(t.mean()); m['turnover']=float(np.abs(np.diff(t)).sum())
    return m

# ---------- source data ----------
print('=== STAGE16 ADVERSARIAL BEAR STRESS ===',flush=True)
qqq=bt.dl_one('QQQ','2009-01-01'); tq=bt.dl_one('TQQQ','2010-01-01'); nqraw=bt.dl_one('NQ=F','2000-01-01'); vix=bt.dl_one('^VIX','1990-01-01'); mc,_=bt.compute_mc(); vs,_=bt.vix_state_series(vix); nq=nq_colors(nqraw)
c=qqq.Close.astype(float); h=qqq.High.astype(float); l=qqq.Low.astype(float); v=qqq.Volume.astype(float); pc=c.shift(1)
tr=pd.concat([(h-l),(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1); atr=tr.ewm(alpha=1/14,adjust=False,min_periods=14).mean(); e10=c.ewm(span=10,adjust=False).mean(); e21=c.ewm(span=21,adjust=False).mean(); s50=c.rolling(50).mean(); s200=c.rolling(200).mean(); tp=(h+l+c)/3; v63=(tp*v).rolling(63).sum()/v.rolling(63).sum(); v252=(tp*v).rolling(252,min_periods=200).sum()/v.rolling(252,min_periods=200).sum(); s50a=(c-s50)/atr; dd10=c/c.rolling(10,min_periods=2).max()-1
idx=qqq.index.intersection(tq.index); idx=idx[idx>=START]
F=pd.DataFrame(index=idx); F['date']=idx; F['ret']=tq.Open.pct_change().reindex(idx); F['mc']=mc.reindex(idx).ffill(); F['nq']=nq.reindex(idx).ffill(); F['panic']=vs.reindex(idx).ffill().astype(str).isin(['BOTTOM','RE-EXTREME']); F['a50']=(c>s50).reindex(idx); F['a63']=(c>v63).reindex(idx); F['a200']=(c>s200).reindex(idx); F['a252']=(c>v252).reindex(idx); F['gte10']=(c>e10).reindex(idx); F['lte21']=(c<e21).reindex(idx); F['s50a']=s50a.reindex(idx); F['dd10']=dd10.reindex(idx); F=F.dropna().reset_index(drop=True)
mp={'Red':0,'Yellow':1,'Green':2,'Blue':3}; F['nq_i']=np.array([mp.get(str(x),1) for x in F.nq],dtype=np.int8)
KEYS=['ret','mc','nq','panic','a50','a63','a200','a252','gte10','lte21','s50a','dd10']
A={'ret':F.ret.to_numpy(float),'mc':F.mc.to_numpy(float),'nq':F.nq_i.to_numpy(np.int8),'panic':F.panic.to_numpy(bool),'a50':F.a50.to_numpy(bool),'a63':F.a63.to_numpy(bool),'a200':F.a200.to_numpy(bool),'a252':F.a252.to_numpy(bool),'gte10':F.gte10.to_numpy(bool),'lte21':F.lte21.to_numpy(bool),'s50a':F.s50a.to_numpy(float),'dd10':F.dd10.to_numpy(float)}
L=len(F)

CANDS={
 'D35_current': {'base':.35,'fast_dd':-.065,'fast_rec':4,'rg':.80,'gb':.90,'bull_mc':65,'bull_exp':1.0,'panic_exp':1.0},
 'D30': {'base':.30,'fast_dd':-.065,'fast_rec':4,'rg':.80,'gb':.90,'bull_mc':65,'bull_exp':1.0,'panic_exp':1.0},
 'D30_fast55': {'base':.30,'fast_dd':-.055,'fast_rec':4,'rg':.80,'gb':.90,'bull_mc':65,'bull_exp':1.0,'panic_exp':1.0},
 'D30_fast55_rg70': {'base':.30,'fast_dd':-.055,'fast_rec':4,'rg':.70,'gb':.90,'bull_mc':65,'bull_exp':1.0,'panic_exp':1.0},
 'D30_fast55_rg70_rec5': {'base':.30,'fast_dd':-.055,'fast_rec':5,'rg':.70,'gb':.90,'bull_mc':65,'bull_exp':1.0,'panic_exp':1.0},
 'D30_fast55_rg70_rec5_p80': {'base':.30,'fast_dd':-.055,'fast_rec':5,'rg':.70,'gb':.90,'bull_mc':65,'bull_exp':1.0,'panic_exp':.80},
 'D25_fast55_rg70_rec5': {'base':.25,'fast_dd':-.055,'fast_rec':5,'rg':.70,'gb':.90,'bull_mc':65,'bull_exp':1.0,'panic_exp':1.0},
 'Balanced_ref': {'base':.35,'fast_dd':-.075,'fast_rec':3,'rg':.70,'gb':1.0,'bull_mc':65,'bull_exp':1.0,'panic_exp':1.0},
}

# Actual-history metrics for context.
hist=[]
for name,p in CANDS.items():
    m=run_strategy(A,p); hist.append({'candidate':name,**m})
HIST=pd.DataFrame(hist); HIST.to_csv('tqqq_stage16_historical_candidates.csv',index=False)
print('\n=== HISTORICAL CANDIDATES ==='); print(HIST[['candidate','cagr','mdd','avg_exp','turnover']].to_string(index=False))

# ---------- stress episode library ----------
def source_window(start,end):
    mask=(F.date>=pd.Timestamp(start))&(F.date<=pd.Timestamp(end))
    ids=np.flatnonzero(mask.to_numpy())
    return {k:A[k][ids].copy() for k in KEYS}

SRC={
 '2011':source_window('2011-07-01','2012-01-31'),
 '2015':source_window('2015-07-01','2016-04-30'),
 '2018':source_window('2018-09-01','2019-04-30'),
 '2020':source_window('2020-02-01','2020-08-31'),
 '2022':source_window('2022-01-01','2023-01-31'),
}

def cat_eps(*eps):
    return {k:np.concatenate([e[k] for e in eps]) for k in KEYS}

def transform_returns(ep,neg_scale=1.0,pos_scale=1.0):
    r=ep['ret'].copy(); r=np.where(r<0,r*neg_scale,r*pos_scale); ep['ret']=np.clip(r,-.85,.50); return ep

def inject_false_rg_gb(ep,rng,nfake):
    n=len(ep['ret']); rawbear=(~ep['a200'])&(~ep['a252'])
    # Prefer deep/weak positions so the fake signal can actually open the tactical sleeve.
    eligible=[]
    for i in range(8,n-4):
        deep=np.min(ep['s50a'][max(0,i-19):i+1])<=-1.5
        weak=rawbear[i] or ep['mc'][i]<35 or ep['dd10'][i]<=-.04
        if deep and weak: eligible.append(i)
    if not eligible: return ep
    take=rng.choice(np.array(eligible),size=min(nfake,len(eligible)),replace=False)
    for i in np.sort(take):
        # Artificially optimistic NQSAR turn inside a still-fragile bear.
        ep['nq'][i-1]=0; ep['nq'][i]=2; ep['nq'][min(i+1,n-1)]=3
        ep['mc'][i]=max(ep['mc'][i],35.0); ep['mc'][min(i+1,n-1)]=max(ep['mc'][min(i+1,n-1)],35.0)
        # Ensure a recent deep print exists without altering the full trend structure.
        ep['s50a'][max(0,i-2)]=min(ep['s50a'][max(0,i-2)],-2.2)
    return ep

def make_episode(family,rng):
    if family=='dotcom_like':
        # Long, grinding bear: concatenate two slow/choppy post-2011 bear templates.
        ep=cat_eps({k:v.copy() for k,v in SRC['2015'].items()},{k:v.copy() for k,v in SRC['2022'].items()})
        ep=transform_returns(ep,1.25,.90); ep=inject_false_rg_gb(ep,rng,6)
    elif family=='gfc_like':
        # Deeper persistent deleveraging with repeated false recoveries.
        ep=cat_eps({k:v.copy() for k,v in SRC['2011'].items()},{k:v.copy() for k,v in SRC['2022'].items()})
        ep=transform_returns(ep,1.55,.85); ep=inject_false_rg_gb(ep,rng,5)
    elif family=='covid_like':
        # Faster crash/recovery: time-compress the 2020 state sequence ~2x and worsen down days.
        base={k:v.copy()[::2] for k,v in SRC['2020'].items()}
        ep=transform_returns(base,1.40,1.00); ep=inject_false_rg_gb(ep,rng,1)
    elif family=='2022_like':
        # Repeated rallies inside a grinding bear; this is deliberately hostile to RG/GB timing.
        ep={k:v.copy() for k,v in SRC['2022'].items()}
        ep=transform_returns(ep,1.30,.92); ep=inject_false_rg_gb(ep,rng,6)
    else: raise ValueError(family)
    return ep

# ---------- 1000 adversarial 10-year paths ----------
rng=np.random.default_rng(SEED)
nblocks=int(np.ceil(H/BLOCK)); starts=rng.integers(0,L-BLOCK+1,size=(NSIM,nblocks)); offs=np.arange(BLOCK); paths=(starts[:,:,None]+offs).reshape(NSIM,-1)[:,:H]
families=np.array((['dotcom_like']*250)+(['gfc_like']*250)+(['covid_like']*250)+(['2022_like']*250),dtype=object); rng.shuffle(families)
rows=[]
for sim in range(NSIM):
    ix=paths[sim]
    B={k:A[k][ix].copy() for k in KEYS}
    fam=str(families[sim]); ep=make_episode(fam,rng); le=len(ep['ret'])
    if le>=H-504:
        # trim only if a concatenated episode is unexpectedly too long
        cut=(le-(H-504))//2; ep={k:v[cut:cut+(H-504)] for k,v in ep.items()}; le=len(ep['ret'])
    pos=int(rng.integers(252,max(253,H-le-252)))
    for k in KEYS: B[k][pos:pos+le]=ep[k]
    for name,p in CANDS.items():
        m=run_strategy(B,p)
        rows.append({'sim':sim,'family':fam,'candidate':name,'stress_len':le,**m})
    if (sim+1)%100==0: print('[stress]',sim+1,'/',NSIM,flush=True)

D=pd.DataFrame(rows); D.to_csv('tqqq_stage16_adversarial_mc.csv',index=False)

def summarize(g):
    cg=g.cagr.to_numpy(); md=g.mdd.to_numpy(); en=g.end.to_numpy(); q=lambda x,p:float(np.quantile(x,p))
    return {
      'n':len(g),'cagr_p05':q(cg,.05),'cagr_p25':q(cg,.25),'cagr_median':q(cg,.5),'cagr_p75':q(cg,.75),'cagr_p95':q(cg,.95),
      'mdd_p05':q(md,.05),'mdd_p25':q(md,.25),'mdd_median':q(md,.5),'mdd_p75':q(md,.75),'mdd_p95':q(md,.95),
      'end_p05':q(en,.05),'end_median':q(en,.5),'end_p95':q(en,.95),
      'prob_mdd30plus':float(np.mean(md<-.30)),'prob_mdd35plus':float(np.mean(md<-.35)),'prob_mdd40plus':float(np.mean(md<-.40)),
      'prob_cagr20below':float(np.mean(cg<.20)),'prob_cagr15below':float(np.mean(cg<.15)),
      'prob_cagr25_mdd25':float(np.mean((cg>=.25)&(md>=-.25))),
    }

S=[]
for cand,g in D.groupby('candidate'):
    S.append({'candidate':cand,'family':'ALL',**summarize(g)})
    for fam,hg in g.groupby('family'): S.append({'candidate':cand,'family':fam,**summarize(hg)})
S=pd.DataFrame(S); S.to_csv('tqqq_stage16_summary.csv',index=False)
ALL=S[S.family=='ALL'].copy(); ALL['hist_cagr']=ALL.candidate.map(HIST.set_index('candidate').cagr); ALL['hist_mdd']=ALL.candidate.map(HIST.set_index('candidate').mdd)
# Practical robust rank: first penalize >30% DD probability, then reward median CAGR and 5% tail CAGR.
ALL['robust_score']=ALL.cagr_median + .35*ALL.cagr_p05 - .30*ALL.prob_mdd30plus - .20*ALL.prob_mdd35plus
ALL=ALL.sort_values('robust_score',ascending=False)
ALL.to_csv('tqqq_stage16_ranked.csv',index=False)
print('\n=== ADVERSARIAL ALL-SCENARIO SUMMARY ==='); print(ALL[['candidate','hist_cagr','hist_mdd','cagr_p05','cagr_median','mdd_median','mdd_p05','prob_mdd30plus','prob_mdd35plus','prob_cagr20below','prob_cagr25_mdd25','robust_score']].to_string(index=False))
print('\n=== FAMILY MDD30+ ==='); print(S.pivot(index='candidate',columns='family',values='prob_mdd30plus').to_string())

out={'seed':SEED,'nsim':NSIM,'horizon_days':H,'block':BLOCK,'families':{x:int(np.sum(families==x)) for x in sorted(set(families))},'historical':HIST.to_dict('records'),'all_summary':ALL.to_dict('records'),'family_summary':S[S.family!='ALL'].to_dict('records'),'method_note':'Adversarial 10-year joint-state moving-block bootstrap. Each path receives one synthetic bear episode built from post-2011 state templates. TQQQ down-day returns are amplified, some positive days damped, COVID-like sequence is time-compressed, and false NQSAR RG/GB transitions are injected in weak/deep conditions. This intentionally breaks exact state/return consistency to stress model risk; it is not a forecast distribution.'}
Path('tqqq_stage16_summary.json').write_text(json.dumps(out,ensure_ascii=False,indent=2))
