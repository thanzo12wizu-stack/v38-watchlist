from __future__ import annotations
import itertools, json
from pathlib import Path
import numpy as np
import pandas as pd
from research import tqqq_backtest_once as bt

# Life-plan search: avoid bear markets, re-enter early enough to retain compounding.
# Close signal -> next-session open execution, 5 bps turnover cost via bt.strategy_returns.

def psar(h,l,step=.02,mx=.08):
    h=np.asarray(h,float); l=np.asarray(l,float); n=len(h); sar=np.zeros(n); bull=True; af=step; ep=l[0]; sar[0]=l[0]
    for i in range(1,n):
        sar[i]=sar[i-1]+af*(ep-sar[i-1])
        if bull:
            if l[i]<sar[i]: bull=False; sar[i]=ep; ep=l[i]; af=step
            elif h[i]>ep: ep=h[i]; af=min(af+step,mx)
        else:
            if h[i]>sar[i]: bull=True; sar[i]=ep; ep=h[i]; af=step
            elif l[i]<ep: ep=l[i]; af=min(af+step,mx)
    return sar

def rsi(c,n=14):
    s=pd.Series(c,dtype=float); d=s.diff(); up=d.clip(lower=0); dn=(-d).clip(lower=0)
    au=up.ewm(alpha=1/n,adjust=False,min_periods=n).mean(); ad=dn.ewm(alpha=1/n,adjust=False,min_periods=n).mean(); rs=au/ad.replace(0,np.nan)
    x=100-100/(1+rs); return x.where(ad.ne(0),100.).to_numpy()

def nq_colors(nq):
    C=nq.Close.astype(float).to_numpy(); H=nq.High.astype(float).to_numpy(); L=nq.Low.astype(float).to_numpy(); S=psar(H,L); E=pd.Series(C,index=nq.index).ewm(span=21,adjust=False).mean().to_numpy(); R=rsi(C)
    above=C>S; state='Green' if above[0] else 'Yellow'; bsu=bsd=99; prev=None; out=[]
    for i in range(len(C)):
        bsu=0 if i>0 and above[i] and not above[i-1] else bsu+1; bsd=0 if i>0 and (not above[i]) and above[i-1] else bsd+1
        ri=float(R[i]) if np.isfinite(R[i]) else 50.; dr=ri-prev if prev is not None else 0.
        if above[i]:
            if state=='Blue': state='Green' if C[i]<E[i] else 'Blue'
            else: state='Blue' if ri>52 and bsu>=2 and dr<=3 else 'Green'
        else:
            if state=='Red': state='Yellow' if ri>50 else 'Red'
            else: state='Red' if ri<47 and bsd>=2 and dr>=-3 else 'Yellow'
        prev=ri; out.append(state)
    return pd.Series(out,index=nq.index,dtype='object')

def conf(s,n):
    s=s.fillna(False).astype(bool); return s if n==1 else s.rolling(n,min_periods=n).sum().eq(n)

def fast_extra(ret,start=None,end=None):
    x=ret.dropna()
    if start is not None: x=x[x.index>=pd.Timestamp(start)]
    if end is not None: x=x[x.index<=pd.Timestamp(end)]
    a=x.to_numpy(float)
    if len(a)<30: return np.nan,np.nan
    eq=np.cumprod(1+a); peak=np.maximum.accumulate(eq); uw=eq/peak-1<0; cur=best=0
    for q in uw: cur=cur+1 if q else 0; best=max(best,cur)
    if len(a)>=252:
        lg=np.log1p(np.clip(a,-.999999,None)); cs=np.r_[0.,np.cumsum(lg)]; rr=np.exp(cs[252:]-cs[:-252])-1; worst=float(np.min(rr))
    else: worst=np.nan
    return worst,int(best)

print('=== TQQQ LIFE-PLAN REGIME SEARCH FAST ===',flush=True)
qqq=bt.dl_one('QQQ','2009-01-01'); tqqq=bt.dl_one('TQQQ','2010-01-01'); vix=bt.dl_one('^VIX','1990-01-01'); nq=bt.dl_one('NQ=F','2000-01-01')
mc,_=bt.compute_mc(); vstate,_=bt.vix_state_series(vix); ind=bt.indicators(qqq); nqcol=nq_colors(nq)
c=qqq.Close.astype(float); h=qqq.High.astype(float); l=qqq.Low.astype(float); vol=qqq.Volume.astype(float); tp=(h+l+c)/3
ema21=c.ewm(span=21,adjust=False,min_periods=21).mean(); sma50=c.rolling(50,min_periods=50).mean(); sma200=c.rolling(200,min_periods=200).mean(); vw63=(tp*vol).rolling(63,min_periods=63).sum()/vol.rolling(63,min_periods=63).sum(); vw252=(tp*vol).rolling(252,min_periods=200).sum()/vol.rolling(252,min_periods=200).sum(); s50up=sma50>sma50.shift(10)
idx=ind.index.intersection(tqqq.index); idx=idx[idx>=bt.START]
ind=ind.reindex(idx); tqqq=tqqq.reindex(idx); mc=mc.reindex(idx).ffill(); vstate=vstate.reindex(idx).ffill(); nqcol=nqcol.reindex(idx).ffill(); c=c.reindex(idx); ema21=ema21.reindex(idx); sma50=sma50.reindex(idx); sma200=sma200.reindex(idx); vw63=vw63.reindex(idx); vw252=vw252.reindex(idx); s50up=s50up.reindex(idx)
mc35=mc>=35; nqnr=nqcol!='Red'; a50=c>sma50; a200=c>sma200; a63=c>vw63; a252=c>vw252; b50=~a50; b200=~a200; b252=~a252
offraw={'b200':b200,'b252':b252,'b200_252':b200&b252,'b50_b200':b50&b200,'b200_s50dn':b200&(~s50up),'b252_s50dn':b252&(~s50up),'struct2':(b200.astype(int)+b252.astype(int)+(~s50up).astype(int)).ge(2),'b200_mc35':b200&(~mc35),'b252_mc35':b252&(~mc35),'b50_nqred':b50&(nqcol=='Red')}
onraw={'a200':a200,'a252':a252,'a200_252':a200&a252,'a50':a50,'a63':a63,'a50_mc35':a50&mc35,'a63_mc35':a63&mc35,'a50_nq':a50&nqnr,'a63_nq':a63&nqnr,'score3':(a50.astype(int)+a63.astype(int)+mc35.astype(int)+nqnr.astype(int)).ge(3)}
mc_a=mc.to_numpy(float); nq_a=nqcol.astype(str).to_numpy(); panic=np.isin(vstate.astype(str).to_numpy(),['BOTTOM','RE-EXTREME']); mets={k:ind[k].to_numpy(float) for k in ['ema21_atr','sma50_atr','vwap63_atr']}; N=len(idx)
# cache confirmed signals
OFF={(k,n):conf(v,n).to_numpy(bool) for k,v in offraw.items() for n in [1,3,5]}; ON={(k,n):conf(v,n).to_numpy(bool) for k,v in onraw.items() for n in [1,2,3]}

def target(p,seed=0.,anchor='none',depth=0.):
    off=OFF[(p['off'],p['oc'])]; on=ON[(p['on'],p['nc'])]; out=np.empty(N); ron=True
    for i in range(N):
        if ron and off[i]: ron=False
        elif (not ron) and on[i]: ron=True
        x=p['onexp'] if ron else p['offexp']
        if ron:
            if p['mod']=='mc25zero' and np.isfinite(mc_a[i]) and mc_a[i]<25: x=0.
            elif p['mod']=='mc35half' and np.isfinite(mc_a[i]) and mc_a[i]<35: x=min(x,.5)
            elif p['mod']=='nqred50' and nq_a[i]=='Red': x=min(x,.5)
            elif p['mod']=='mc_nq25' and np.isfinite(mc_a[i]) and mc_a[i]<35 and nq_a[i]=='Red': x=min(x,.25)
        if (not ron) and seed>0 and panic[i]:
            hit=True if anchor=='none' else (np.isfinite(mets[anchor][i]) and mets[anchor][i]<=depth)
            if hit: x=max(x,seed)
        out[i]=x
    return out

def stats(t):
    s=pd.Series(t,index=idx,dtype=float); r=bt.strategy_returns(s,tqqq.Open); return bt.add_stats({'avg_exposure':float(np.mean(t)),'turnover':float(s.diff().abs().sum())},r)

rows=[]
for off,on,oc,nc,onexp,offexp,mod in itertools.product(offraw,onraw,[1,3,5],[1,2,3],[.75,1.],[0.,.1,.25],['none','mc25zero','mc35half','nqred50','mc_nq25']):
    p={'off':off,'on':on,'oc':oc,'nc':nc,'onexp':onexp,'offexp':offexp,'mod':mod}; rows.append({**p,'panic_seed':0.,'panic_anchor':'none','panic_depth':0.,**stats(target(p))})
base=pd.DataFrame(rows); base['minio']=base[['is_cagr','oos_cagr']].min(axis=1); base.to_csv('tqqq_stage6_base.csv',index=False); print('[stage6] base',len(base),flush=True)
sel=set(base.sort_values(['is_cagr','is_calmar'],ascending=False).head(70).index); sel.update(base.sort_values(['is_calmar','is_cagr'],ascending=False).head(70).index)
for lim in [.20,.25,.30,.35,.40,.45,.50]: sel.update(base[base.is_mdd>=-lim].sort_values(['is_cagr','is_calmar'],ascending=False).head(50).index)
for k in offraw: sel.update(base[base.off==k].sort_values(['is_calmar','is_cagr'],ascending=False).head(10).index)
sel=sorted(sel); print('[stage6] selected',len(sel),flush=True)
rows2=[{'base_ix':int(i),**base.loc[i].to_dict()} for i in sel]
for bi in sel:
    b=base.loc[bi]; p={'off':str(b.off),'on':str(b['on']),'oc':int(b.oc),'nc':int(b.nc),'onexp':float(b.onexp),'offexp':float(b.offexp),'mod':str(b['mod'])}
    for seed in [.25,.5,.75,1.]:
        for anch in ['none','ema21_atr','sma50_atr','vwap63_atr']:
            deps=[0.] if anch=='none' else [-1.,-1.5,-2.]
            for dep in deps: rows2.append({'base_ix':int(bi),**p,'panic_seed':seed,'panic_anchor':anch,'panic_depth':dep,**stats(target(p,seed,anch,dep))})
d=pd.DataFrame(rows2); d['minio']=d[['is_cagr','oos_cagr']].min(axis=1); d['minio_c']=d[['is_calmar','oos_calmar']].min(axis=1); d.to_csv('tqqq_stage6_lifeplan.csv',index=False); print('[stage6] total',len(d),flush=True)

# Collect candidates first, then compute path-risk metrics only for them.
cand=set()
for lim in [.20,.25,.30,.35,.40,.45,.50,.60]:
    q=d[d.full_mdd>=-lim];
    if len(q): cand.add(int(q.sort_values(['full_cagr','minio'],ascending=False).index[0])); cand.add(int(q.sort_values(['minio','full_cagr'],ascending=False).index[0]))
z=d[(d.full_mdd>=-.40)&(d.minio>=.20)].copy(); cand.update(map(int,z.sort_values(['full_mdd','minio'],ascending=[False,False]).head(30).index)); cand.update(map(int,z.sort_values(['minio','full_cagr'],ascending=False).head(30).index))
extra={}
for j in cand:
    r=d.loc[j]; p={'off':str(r.off),'on':str(r['on']),'oc':int(r.oc),'nc':int(r.nc),'onexp':float(r.onexp),'offexp':float(r.offexp),'mod':str(r['mod'])}; t=target(p,float(r.panic_seed),str(r.panic_anchor),float(r.panic_depth)); rr=bt.strategy_returns(pd.Series(t,index=idx),tqqq.Open); w,u=fast_extra(rr,bt.START,None); extra[j]=(w,u)

def desc(r):
    w,u=extra.get(int(r.name),(np.nan,np.nan)); return f"CAGR={r.full_cagr*100:.2f}% MDD={r.full_mdd*100:.2f}% minIO={r.minio*100:.2f}% IS/OOS={r.is_cagr*100:.2f}/{r.oos_cagr*100:.2f}% C={r.full_calmar:.3f} worst1y={w*100:.1f}% uw={u} avg={r.avg_exposure*100:.1f}% :: off={r.off}/{int(r.oc)} on={r['on']}/{int(r.nc)} exp={r.onexp:.2f}/{r.offexp:.2f} mod={r['mod']} panic={r.panic_seed:.2f}:{r.panic_anchor}@{r.panic_depth}"
print('\n=== MAX CAGR BY MDD LIMIT ===')
for lim in [.20,.25,.30,.35,.40,.45,.50,.60]:
    q=d[d.full_mdd>=-lim].sort_values(['full_cagr','minio'],ascending=False).head(1)
    if len(q): print(f'MDD<={lim*100:.0f}% '+desc(q.iloc[0]))
print('\n=== ROBUST RETURN BY MDD LIMIT ===')
for lim in [.20,.25,.30,.35,.40,.45,.50]:
    q=d[d.full_mdd>=-lim].sort_values(['minio','full_cagr'],ascending=False).head(1)
    if len(q): print(f'MDD<={lim*100:.0f}% '+desc(q.iloc[0]))
print('\n=== LOW-DD PARETO CANDIDATES ===')
for _,r in d[(d.full_mdd>=-.40)&(d.minio>=.20)].sort_values(['full_mdd','minio'],ascending=[False,False]).head(25).iterrows(): print(desc(r))
print('\n=== VIX OVERLAY MEDIAN EFFECT ===')
ov=d[d.panic_seed>0].copy()
for k in ['full_cagr','full_mdd','full_calmar','oos_cagr','oos_mdd']:
    ov[k+'d']=ov.apply(lambda r:r[k]-base.loc[int(r.base_ix),k],axis=1)
for seed in [.25,.5,.75,1.]:
    q=ov[ov.panic_seed==seed]; print(f"seed={seed:.2f}: dCAGR={q.full_cagrd.median()*100:+.2f}pt dMDD={q.full_mddd.median()*100:+.2f}pt dCalmar={q.full_calmard.median():+.3f} OOSdCAGR={q.oos_cagrd.median()*100:+.2f}pt")
bench={str(w):bt.stats(bt.fixed_returns(w,tqqq.Open),bt.START,None) for w in [0,.25,.5,.75,1.]}; summary={'start':str(idx[0].date()),'end':str(idx[-1].date()),'base':len(base),'selected':len(sel),'total':len(d),'benchmarks':bench,'note':'No fixed core. Structural exit + faster reentry + optional VIX BOTTOM seed; NQSAR is archived V38 fallback proxy.'}; Path('tqqq_stage6_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,default=str)); print('\n=== SUMMARY ==='); print(json.dumps(summary,ensure_ascii=False,indent=2,default=str))
