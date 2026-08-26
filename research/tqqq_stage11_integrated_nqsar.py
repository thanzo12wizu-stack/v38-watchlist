from __future__ import annotations
import itertools, json
from pathlib import Path
import numpy as np
import pandas as pd
from research import tqqq_backtest_once as bt

START=pd.Timestamp('2011-01-03'); IS_END=pd.Timestamp('2018-12-31'); COST=.0005

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
    return pd.Series(out,index=nq.index,dtype='object',name='nqsar')

def conf(s,n): return s.fillna(False).astype(bool).rolling(n,min_periods=n).sum().eq(n)

def metrics(ret):
    x=pd.Series(ret).dropna(); eq=(1+x).cumprod(); years=len(x)/252; dd=eq/eq.cummax()-1
    return {'cagr':float(eq.iloc[-1]**(1/years)-1),'mdd':float(dd.min()),'calmar':float((eq.iloc[-1]**(1/years)-1)/(-dd.min())),'end':float(eq.iloc[-1])}

def addstats(target,tq):
    s=pd.Series(target,index=IDX,dtype=float); r=bt.strategy_returns(s,tq.Open).reindex(IDX).fillna(0)
    f=metrics(r); ii=metrics(r.loc[:IS_END]); oo=metrics(r.loc[IS_END+pd.Timedelta(days=1):])
    return {'full_cagr':f['cagr'],'full_mdd':f['mdd'],'full_calmar':f['calmar'],'is_cagr':ii['cagr'],'is_mdd':ii['mdd'],'oos_cagr':oo['cagr'],'oos_mdd':oo['mdd'],'avg_exp':float(s.mean()),'turnover':float(s.diff().abs().sum())}

print('=== STAGE11 INTEGRATED NQSAR ===',flush=True)
qqq=bt.dl_one('QQQ','2009-01-01'); tq=bt.dl_one('TQQQ','2010-01-01'); nqraw=bt.dl_one('NQ=F','2000-01-01'); vix=bt.dl_one('^VIX','1990-01-01'); mc,_=bt.compute_mc(); vs,_=bt.vix_state_series(vix); nq=nq_colors(nqraw)
c=qqq.Close.astype(float); h=qqq.High.astype(float); l=qqq.Low.astype(float); v=qqq.Volume.astype(float); pc=c.shift(1)
tr=pd.concat([(h-l),(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1); atr=tr.ewm(alpha=1/14,adjust=False,min_periods=14).mean(); e10=c.ewm(span=10,adjust=False).mean(); e21=c.ewm(span=21,adjust=False).mean(); s50=c.rolling(50).mean(); s200=c.rolling(200).mean(); tp=(h+l+c)/3; v63=(tp*v).rolling(63).sum()/v.rolling(63).sum(); v252=(tp*v).rolling(252,min_periods=200).sum()/v.rolling(252,min_periods=200).sum(); s50a=(c-s50)/atr; dd10=c/c.rolling(10,min_periods=2).max()-1
IDX=qqq.index.intersection(tq.index); IDX=IDX[IDX>=START]; tq=tq.reindex(IDX); nq=nq.reindex(IDX).ffill(); mc=mc.reindex(IDX).ffill(); vs=vs.reindex(IDX).ffill(); c=c.reindex(IDX); e10=e10.reindex(IDX); e21=e21.reindex(IDX); s50=s50.reindex(IDX); s200=s200.reindex(IDX); v63=v63.reindex(IDX); v252=v252.reindex(IDX); s50a=s50a.reindex(IDX); dd10=dd10.reindex(IDX)
a50=c>s50; a63=c>v63; a200=c>s200; a252=c>v252; mc35=mc>=35; nqnr=nq!='Red'; score3=(a50.astype(int)+a63.astype(int)+mc35.astype(int)+nqnr.astype(int)).ge(3); rawbear=(~a200)&(~a252); bear_on=conf(rawbear,5); arm20=s50a.rolling(20,min_periods=1).min(); prev=nq.shift(1); trans=(prev.astype(str)+'->'+nq.astype(str)).where(prev.notna()); panic=vs.astype(str).isin(['BOTTOM','RE-EXTREME'])

# Base state machine: slow bear, MC hysteresis, fast-crash brake, normal exposure, strong-bull boost, optional VIX panic buy.
def build_base(baseexp=.545,bull_mc=65,bull_s50max=2.5,fast_dd=-.075,fast_rec=4,bear_exit='score1',vix_panic=True):
    out=np.zeros(len(IDX)); slow=False; fast=False; mclock=False
    rec10=conf(c>e10,fast_rec)
    for i,d in enumerate(IDX):
        if bool(bear_on.loc[d]): slow=True
        if slow:
            if bear_exit=='raw' and not bool(rawbear.loc[d]): slow=False
            elif bear_exit=='score1' and (not bool(rawbear.loc[d])) and bool(score3.loc[d]) and float(mc.loc[d])>=35: slow=False
            elif bear_exit=='score3' and i>=2 and all((not bool(rawbear.iloc[j])) and bool(score3.iloc[j]) and float(mc.iloc[j])>=35 for j in range(i-2,i+1)): slow=False
        if float(mc.loc[d])<25: mclock=True
        if mclock and float(mc.loc[d])>=35 and bool(score3.loc[d]) and str(nq.loc[d])!='Red': mclock=False
        if float(dd10.loc[d])<=fast_dd and float(c.loc[d])<float(e21.loc[d]): fast=True
        if fast and bool(rec10.loc[d]): fast=False
        x=0.0 if (slow or fast or mclock) else baseexp
        if x>0 and float(mc.loc[d])>=bull_mc and str(nq.loc[d])=='Blue' and bool(a50.loc[d]) and bool(a63.loc[d]) and float(s50a.loc[d])<=bull_s50max: x=1.0
        if vix_panic and bool(panic.loc[d]) and float(s50a.loc[d])<=-2.0: x=1.0
        out[i]=x
    return pd.Series(out,index=IDX,dtype=float)

# First reproduce/validate the previously reported ~30.17/-21.98 base in a small plateau, without NQSAR tactical overlays.
base_rows=[]; base_cache={}
for baseexp,bmc,bmax,fdd,frec,bexit,vp in itertools.product([.52,.54,.545,.55,.56,.58,.60],[60,65,70],[2.0,2.5,3.0],[-.065,-.075,-.085],[3,4,5],['raw','score1','score3'],[False,True]):
    key=(baseexp,bmc,bmax,fdd,frec,bexit,vp); t=build_base(*key); st=addstats(t,tq); base_rows.append({'baseexp':baseexp,'bull_mc':bmc,'bull_s50max':bmax,'fast_dd':fdd,'fast_rec':frec,'bear_exit':bexit,'vix_panic':vp,**st}); base_cache[key]=t
B=pd.DataFrame(base_rows); B['dist_reported']=(B.full_cagr-.3017).abs()+0.5*(B.full_mdd+.2198).abs(); B['minio']=B[['is_cagr','oos_cagr']].min(axis=1); B.to_csv('tqqq_stage11_base_grid.csv',index=False)
repro=B.sort_values('dist_reported').iloc[0]; print('\nREPRO CLOSEST'); print(repro.to_string())
# Candidate bases: closest reproduction + IS-frontier and full low-DD frontier. This avoids relying on one exact tuning.
sel=set(B.sort_values('dist_reported').head(5).index)
for lim in [.20,.22,.24,.26,.28]:
    q=B[B.is_mdd>=-lim].sort_values(['is_cagr','is_mdd'],ascending=[False,False]).head(4); sel.update(q.index)
    q=B[B.full_mdd>=-lim].sort_values(['full_cagr','minio'],ascending=False).head(4); sel.update(q.index)
sel=sorted(sel); print('[stage11] selected bases',len(sel),flush=True)

# Integrated NQSAR tactical state. One event sleeve at a time. It changes total TQQQ exposure, so the result is one portfolio curve.
def integrated(base, combo='RG', rg=.60, gb=1.0, by=.75, ry=.25, rg_partial='none', scope='all'):
    t=base.copy(); active=None; entry_i=None; entry_open=None; partial=False; trades=[]
    kinds=set(combo.split('+')) if combo!='NONE' else set()
    for i,d in enumerate(IDX[:-2]):
        cur=str(nq.loc[d]); trn=str(trans.loc[d]) if pd.notna(trans.loc[d]) else ''
        if active is None:
            k=None
            if 'RG' in kinds and trn=='Red->Green' and float(arm20.loc[d])<=-2 and float(mc.loc[d])>=35: k='RG'
            elif 'GB' in kinds and trn=='Green->Blue' and float(arm20.loc[d])<=-1.5 and float(mc.loc[d])>=35 and not bool(bear_on.loc[d]): k='GB'
            elif 'BY' in kinds and trn=='Blue->Yellow' and float(mc.loc[d])>=35: k='BY'
            elif 'RY' in kinds and trn=='Red->Yellow' and float(arm20.loc[d])<=-2 and float(mc.loc[d])>=35: k='RY'
            if k is not None:
                if scope=='riskoff' and k in ('RG','RY') and float(base.loc[d])>.10: k=None
                if k is not None:
                    active=k; entry_i=i+1; entry_open=float(tq.iloc[entry_i].Open); partial=False; trades.append({'kind':k,'signal':d,'entry':IDX[entry_i]})
        if active is not None:
            hold=max(0,i-(entry_i-1)); ex=False
            if active=='RG':
                if cur in ('Yellow','Red') or hold>=7: ex=True
            elif active=='GB':
                if trn in ('Blue->Green','Blue->Yellow') or cur=='Red' or hold>=20: ex=True
            elif active in ('BY','RY'):
                if trn in ('Yellow->Green','Yellow->Red') or cur in ('Green','Red') or hold>=10: ex=True
            # causal partial profit: if today's high crossed +10%, reduce tactical exposure from today's close -> next open.
            if active=='RG' and rg_partial!='none' and (not partial) and i>=entry_i and float(tq.iloc[i].High)>=entry_open*1.10:
                partial=True
            if not ex:
                total={'RG':rg,'GB':gb,'BY':by,'RY':ry}[active]
                if active=='RG' and partial:
                    frac=.50 if rg_partial=='half' else .67
                    total=max(float(base.loc[d]), total*(1-frac))
                else:
                    total=max(float(base.loc[d]),total)
                # Preserve explicit VIX panic 100% from base.
                if float(base.loc[d])>=.999: total=1.0
                t.loc[d]=min(1.0,total)
            else:
                active=None; entry_i=None; entry_open=None; partial=False
    return t

rows=[]
combos=['NONE','RG','RG+GB','RG+GB+BY','RG+GB+BY+RY']
for bi in sel:
    br=B.loc[bi]; key=(float(br.baseexp),int(br.bull_mc),float(br.bull_s50max),float(br.fast_dd),int(br.fast_rec),str(br.bear_exit),bool(br.vix_panic)); base=base_cache[key]
    for combo in combos:
      for rg,gb,by,ry,part,scope in itertools.product([.50,.60,.70],[.80,1.0],[.65,.75,.85],[.20,.25],['none','half','two_thirds'],['all','riskoff']):
        if combo=='NONE' and (rg,gb,by,ry,part,scope)!=(.50,.80,.65,.20,'none','all'): continue
        tt=integrated(base,combo,rg,gb,by,ry,part,scope); st=addstats(tt,tq)
        rows.append({'base_ix':int(bi),'combo':combo,'rg':rg,'gb':gb,'by':by,'ry':ry,'rg_partial':part,'scope':scope,**{k:br[k] for k in ['baseexp','bull_mc','bull_s50max','fast_dd','fast_rec','bear_exit','vix_panic']},**st})
R=pd.DataFrame(rows); R['minio']=R[['is_cagr','oos_cagr']].min(axis=1); R['d_cagr']=R.full_cagr-R.apply(lambda x:B.loc[int(x.base_ix)].full_cagr,axis=1); R['d_mdd']=R.full_mdd-R.apply(lambda x:B.loc[int(x.base_ix)].full_mdd,axis=1); R.to_csv('tqqq_stage11_integrated_grid.csv',index=False)

print('\n=== BEST FULL BY MDD LIMIT ===')
for lim in [.18,.20,.22,.24,.26,.28,.30]:
    q=R[R.full_mdd>=-lim].sort_values(['full_cagr','minio'],ascending=False).head(1)
    if len(q): print(f'MDD<={lim:.2f}',q[['full_cagr','full_mdd','is_cagr','oos_cagr','combo','rg','gb','by','ry','rg_partial','scope','baseexp','bull_mc','fast_dd','fast_rec','bear_exit','vix_panic']].to_dict('records')[0])
print('\n=== BEST MIN(IS,OOS) BY MDD LIMIT ===')
for lim in [.18,.20,.22,.24,.26,.28,.30]:
    q=R[R.full_mdd>=-lim].sort_values(['minio','full_cagr'],ascending=False).head(1)
    if len(q): print(f'MDD<={lim:.2f}',q[['full_cagr','full_mdd','is_cagr','oos_cagr','minio','combo','rg','gb','by','ry','rg_partial','scope','baseexp','bull_mc','fast_dd','fast_rec','bear_exit','vix_panic']].to_dict('records')[0])
print('\n=== OVERLAY DELTA TOP ===')
q=R[R.combo!='NONE'].sort_values(['d_cagr','d_mdd'],ascending=[False,False]).head(20); print(q[['d_cagr','d_mdd','full_cagr','full_mdd','is_cagr','oos_cagr','combo','rg','gb','by','rg_partial','scope']].to_string(index=False))
print('\n=== PARTIAL PROFIT COMPARISON RG-CONTAINING ===')
for p in ['none','half','two_thirds']:
    q=R[(R.combo.str.contains('RG'))&(R.rg_partial==p)&(R.full_mdd>=-.25)].sort_values(['minio','full_cagr'],ascending=False).head(1)
    if len(q): print(p,q[['full_cagr','full_mdd','is_cagr','oos_cagr','minio','combo','rg','gb','by','scope']].to_dict('records')[0])
# Save a compact robust shortlist.
valid=R[(R.full_mdd>=-.25)&(R.is_cagr>0)&(R.oos_cagr>0)].copy(); valid['score']=valid.minio+0.35*valid.full_cagr+0.15*valid.full_mdd; robust=valid.sort_values('score',ascending=False).head(50); robust.to_csv('tqqq_stage11_robust.csv',index=False)
summary={'base_grid':len(B),'selected_bases':len(sel),'integrated_grid':len(R),'closest_repro':repro.to_dict(),'best_mdd25':R[R.full_mdd>=-.25].sort_values(['full_cagr','minio'],ascending=False).head(10).to_dict('records'),'robust':robust.head(10).to_dict('records')}; Path('tqqq_stage11_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,default=str))
print('\nSUMMARY',json.dumps({'base_grid':len(B),'selected_bases':len(sel),'integrated_grid':len(R)},ensure_ascii=False))
