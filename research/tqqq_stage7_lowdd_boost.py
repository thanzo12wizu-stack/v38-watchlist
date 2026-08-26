from __future__ import annotations
import itertools, json
from pathlib import Path
import numpy as np
import pandas as pd
from research import tqqq_backtest_once as bt

# Stage7: low-DD first. Risk-ON baseline can be 50-75%, boosted only in strong regimes.
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
    x=pd.Series(c,dtype=float); d=x.diff(); u=d.clip(lower=0); dn=(-d).clip(lower=0); au=u.ewm(alpha=1/n,adjust=False,min_periods=n).mean(); ad=dn.ewm(alpha=1/n,adjust=False,min_periods=n).mean(); rs=au/ad.replace(0,np.nan); y=100-100/(1+rs); return y.where(ad.ne(0),100.).to_numpy()

def nq_colors(nq):
    C=nq.Close.astype(float).to_numpy(); H=nq.High.astype(float).to_numpy(); L=nq.Low.astype(float).to_numpy(); S=psar(H,L); E=pd.Series(C,index=nq.index).ewm(span=21,adjust=False).mean().to_numpy(); R=rsi(C); a=C>S; st='Green' if a[0] else 'Yellow'; up=dn=99; prev=None; out=[]
    for i in range(len(C)):
        up=0 if i>0 and a[i] and not a[i-1] else up+1; dn=0 if i>0 and (not a[i]) and a[i-1] else dn+1; ri=float(R[i]) if np.isfinite(R[i]) else 50.; dr=ri-prev if prev is not None else 0.
        if a[i]:
            if st=='Blue': st='Green' if C[i]<E[i] else 'Blue'
            else: st='Blue' if ri>52 and up>=2 and dr<=3 else 'Green'
        else:
            if st=='Red': st='Yellow' if ri>50 else 'Red'
            else: st='Red' if ri<47 and dn>=2 and dr>=-3 else 'Yellow'
        prev=ri; out.append(st)
    return pd.Series(out,index=nq.index,dtype='object')

def conf(s,n):
    s=s.fillna(False).astype(bool); return s if n==1 else s.rolling(n,min_periods=n).sum().eq(n)

def extra(ret):
    a=ret.dropna().to_numpy(float); eq=np.cumprod(1+a); peak=np.maximum.accumulate(eq); uw=eq/peak-1<0; cur=best=0
    for q in uw: cur=cur+1 if q else 0; best=max(best,cur)
    lg=np.log1p(np.clip(a,-.999999,None)); cs=np.r_[0.,np.cumsum(lg)]; rr=np.exp(cs[252:]-cs[:-252])-1 if len(a)>=252 else np.array([np.nan]); return float(np.nanmin(rr)),int(best)

print('=== TQQQ STAGE7 LOW-DD BOOST SEARCH ===',flush=True)
qqq=bt.dl_one('QQQ','2009-01-01'); tqqq=bt.dl_one('TQQQ','2010-01-01'); vix=bt.dl_one('^VIX','1990-01-01'); nq=bt.dl_one('NQ=F','2000-01-01'); mc,_=bt.compute_mc(); vs,_=bt.vix_state_series(vix); ind=bt.indicators(qqq); nqcol=nq_colors(nq)
c=qqq.Close.astype(float); h=qqq.High.astype(float); l=qqq.Low.astype(float); v=qqq.Volume.astype(float); tp=(h+l+c)/3; sma50=c.rolling(50).mean(); sma200=c.rolling(200).mean(); vw63=(tp*v).rolling(63).sum()/v.rolling(63).sum(); vw252=(tp*v).rolling(252,min_periods=200).sum()/v.rolling(252,min_periods=200).sum(); s50up=sma50>sma50.shift(10)
idx=ind.index.intersection(tqqq.index); idx=idx[idx>=bt.START]; ind=ind.reindex(idx); tqqq=tqqq.reindex(idx); mc=mc.reindex(idx).ffill(); vs=vs.reindex(idx).ffill(); nqcol=nqcol.reindex(idx).ffill(); c=c.reindex(idx); sma50=sma50.reindex(idx); sma200=sma200.reindex(idx); vw63=vw63.reindex(idx); vw252=vw252.reindex(idx); s50up=s50up.reindex(idx)
mc35=mc>=35; mc45=mc>=45; nqnr=nqcol!='Red'; nqb=nqcol.isin(['Blue','Green']); a50=c>sma50; a200=c>sma200; a63=c>vw63; a252=c>vw252; b50=~a50; b200=~a200; b252=~a252
offraw={'b200_252':b200&b252,'struct2':(b200.astype(int)+b252.astype(int)+(~s50up).astype(int)).ge(2),'b200_s50dn':b200&(~s50up),'b252_s50dn':b252&(~s50up),'b200_mc35':b200&(~mc35),'b252_mc35':b252&(~mc35),'b50_nqred':b50&(nqcol=='Red')}
onraw={'a50_mc35':a50&mc35,'a63_mc35':a63&mc35,'score3':(a50.astype(int)+a63.astype(int)+mc35.astype(int)+nqnr.astype(int)).ge(3),'a50_nq':a50&nqnr,'a63_nq':a63&nqnr,'a200_252':a200&a252}
OFF={(k,n):conf(v,n).to_numpy(bool) for k,v in offraw.items() for n in [3,5]}; ON={(k,n):conf(v,n).to_numpy(bool) for k,v in onraw.items() for n in [1,2,3]}
mc_a=mc.to_numpy(float); nq_a=nqcol.astype(str).to_numpy(); A50=a50.to_numpy(bool); A63=a63.to_numpy(bool); A252=a252.to_numpy(bool); MC35=mc35.to_numpy(bool); MC45=mc45.to_numpy(bool); NQNR=nqnr.to_numpy(bool); NQB=nqb.to_numpy(bool); PAN=np.isin(vs.astype(str).to_numpy(),['BOTTOM','RE-EXTREME']); MET={k:ind[k].to_numpy(float) for k in ['sma50_atr','vwap63_atr']}; N=len(idx)

def boosted(i,mode):
    if mode=='none': return False
    if mode=='mc45': return MC45[i]
    if mode=='mc35_nq': return MC35[i] and NQNR[i]
    if mode=='strong': return A50[i] and A63[i] and MC35[i] and NQNR[i]
    if mode=='nqbull_mc35': return NQB[i] and MC35[i]
    if mode=='v252_mc35': return A252[i] and MC35[i]
    return False

def target(p,seed=0.,anch='none',dep=0.):
    off=OFF[(p['off'],p['oc'])]; on=ON[(p['on'],p['nc'])]; out=np.empty(N); ron=True
    for i in range(N):
        if ron and off[i]: ron=False
        elif (not ron) and on[i]: ron=True
        x=p['baseexp'] if ron else p['offexp']
        if ron and boosted(i,p['boost']): x=max(x,p['boostexp'])
        if ron:
            if p['mod']=='mc25zero' and np.isfinite(mc_a[i]) and mc_a[i]<25: x=0.
            elif p['mod']=='mc35half' and np.isfinite(mc_a[i]) and mc_a[i]<35: x=min(x,.5)
            elif p['mod']=='mc_nq25' and np.isfinite(mc_a[i]) and mc_a[i]<35 and nq_a[i]=='Red': x=min(x,.25)
        if (not ron) and seed>0 and PAN[i]:
            hit=True if anch=='none' else (np.isfinite(MET[anch][i]) and MET[anch][i]<=dep)
            if hit: x=max(x,seed)
        out[i]=x
    return np.clip(out,0,1)

def stats(t):
    s=pd.Series(t,index=idx); r=bt.strategy_returns(s,tqqq.Open); return bt.add_stats({'avg_exposure':float(np.mean(t)),'turnover':float(s.diff().abs().sum())},r)

rows=[]
mods=['none','mc25zero','mc35half','mc_nq25']; boosts=['none','mc45','mc35_nq','strong','nqbull_mc35','v252_mc35']
for off,on,oc,nc,baseexp,offexp,boost,boostexp,mod in itertools.product(offraw,onraw,[3,5],[1,2,3],[.50,.60,.75],[0.,.10],boosts,[.85,1.],mods):
    p={'off':off,'on':on,'oc':oc,'nc':nc,'baseexp':baseexp,'offexp':offexp,'boost':boost,'boostexp':boostexp,'mod':mod}; rows.append({**p,'panic_seed':0.,'panic_anchor':'none','panic_depth':0.,**stats(target(p))})
base=pd.DataFrame(rows); base['minio']=base[['is_cagr','oos_cagr']].min(axis=1); base['minioc']=base[['is_calmar','oos_calmar']].min(axis=1); base.to_csv('tqqq_stage7_base.csv',index=False); print('[stage7] base',len(base),flush=True)
# IS-only selection, deliberately overweight low-DD bands
sel=set()
for lim in [.20,.25,.30,.35,.40,.45]: sel.update(base[base.is_mdd>=-lim].sort_values(['is_cagr','is_calmar'],ascending=False).head(80).index)
sel.update(base.sort_values(['is_calmar','is_cagr'],ascending=False).head(100).index); sel.update(base.sort_values(['is_cagr','is_calmar'],ascending=False).head(60).index); sel=sorted(sel); print('[stage7] selected',len(sel),flush=True)
rows2=[{'base_ix':int(i),**base.loc[i].to_dict()} for i in sel]
for bi in sel:
    b=base.loc[bi]; p={k:(str(b[k]) if k in ['off','on','boost','mod'] else int(b[k]) if k in ['oc','nc'] else float(b[k])) for k in ['off','on','oc','nc','baseexp','offexp','boost','boostexp','mod']}
    for seed in [.25,.5,.75,1.]:
        for anch in ['none','sma50_atr','vwap63_atr']:
            for dep in ([0.] if anch=='none' else [-1.,-1.5,-2.]): rows2.append({'base_ix':int(bi),**p,'panic_seed':seed,'panic_anchor':anch,'panic_depth':dep,**stats(target(p,seed,anch,dep))})
d=pd.DataFrame(rows2); d['minio']=d[['is_cagr','oos_cagr']].min(axis=1); d['minioc']=d[['is_calmar','oos_calmar']].min(axis=1); d.to_csv('tqqq_stage7_lowdd.csv',index=False); print('[stage7] total',len(d),flush=True)

# Candidate reports
cand=set()
for lim in [.20,.25,.30,.325,.35,.375,.40,.45]:
    q=d[d.full_mdd>=-lim]
    if len(q): cand.add(int(q.sort_values(['full_cagr','minio'],ascending=False).index[0])); cand.add(int(q.sort_values(['minio','full_cagr'],ascending=False).index[0]))
for j in d[d.full_mdd>=-.40].sort_values(['full_mdd','minio'],ascending=[False,False]).head(30).index: cand.add(int(j))
EX={}
for j in cand:
    r=d.loc[j]; p={k:(str(r[k]) if k in ['off','on','boost','mod'] else int(r[k]) if k in ['oc','nc'] else float(r[k])) for k in ['off','on','oc','nc','baseexp','offexp','boost','boostexp','mod']}; t=target(p,float(r.panic_seed),str(r.panic_anchor),float(r.panic_depth)); rr=bt.strategy_returns(pd.Series(t,index=idx),tqqq.Open); EX[j]=extra(rr)
def desc(r):
    w,u=EX.get(int(r.name),(np.nan,np.nan)); return f"CAGR={r.full_cagr*100:.2f}% MDD={r.full_mdd*100:.2f}% minIO={r.minio*100:.2f}% IS/OOS={r.is_cagr*100:.2f}/{r.oos_cagr*100:.2f}% C={r.full_calmar:.3f} worst1y={w*100:.1f}% uw={u} avg={r.avg_exposure*100:.1f}% :: {r.off}/{int(r.oc)} -> {r['on']}/{int(r.nc)} base/off={r.baseexp:.2f}/{r.offexp:.2f} boost={r.boost}:{r.boostexp:.2f} mod={r['mod']} panic={r.panic_seed:.2f}:{r.panic_anchor}@{r.panic_depth}"
print('\n=== MAX CAGR BY MDD LIMIT ===')
for lim in [.20,.25,.30,.325,.35,.375,.40,.45]:
    q=d[d.full_mdd>=-lim].sort_values(['full_cagr','minio'],ascending=False).head(1)
    if len(q): print(f'MDD<={lim*100:.1f}% '+desc(q.iloc[0]))
print('\n=== ROBUST RETURN BY MDD LIMIT ===')
for lim in [.20,.25,.30,.325,.35,.375,.40,.45]:
    q=d[d.full_mdd>=-lim].sort_values(['minio','full_cagr'],ascending=False).head(1)
    if len(q): print(f'MDD<={lim*100:.1f}% '+desc(q.iloc[0]))
print('\n=== LOWEST-DD WITH minIO>=25% ===')
q=d[d.minio>=.25].sort_values(['full_mdd','minio'],ascending=[False,False]).head(20)
for _,r in q.iterrows(): print(desc(r))
print('\n=== VIX MEDIAN ===')
ov=d[d.panic_seed>0].copy()
for k in ['full_cagr','full_mdd','full_calmar','oos_cagr']: ov[k+'d']=ov.apply(lambda r:r[k]-base.loc[int(r.base_ix),k],axis=1)
for seed in [.25,.5,.75,1.]:
    q=ov[ov.panic_seed==seed]; print(f"seed {seed:.2f}: dCAGR={q.full_cagrd.median()*100:+.2f} dMDD={q.full_mddd.median()*100:+.2f} dCalmar={q.full_calmard.median():+.3f} OOSd={q.oos_cagrd.median()*100:+.2f}")
summary={'base':len(base),'selected':len(sel),'total':len(d),'start':str(idx[0].date()),'end':str(idx[-1].date()),'note':'Low-DD first: 50-75% risk-on baseline, 0-10% risk-off, boost to 85-100% only in strong regimes; optional VIX BOTTOM seed.'}; Path('tqqq_stage7_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)); print(json.dumps(summary,ensure_ascii=False,indent=2))
