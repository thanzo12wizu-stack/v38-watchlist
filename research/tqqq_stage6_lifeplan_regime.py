from __future__ import annotations

import itertools
import json
from pathlib import Path

import numpy as np
import pandas as pd

from research import tqqq_backtest_once as bt

# Stage 6: life-plan oriented TQQQ regime search.
# Priority: avoid prolonged / deep drawdowns, then maximize robust CAGR.
# Signal at close, execution at next-session open through bt.strategy_returns.


def psar_archived(h,l,step=0.02,mx=0.08):
    h=np.asarray(h,float); l=np.asarray(l,float); n=len(h)
    sar=np.zeros(n); bull=True; af=step; ep=l[0]; sar[0]=l[0]
    for i in range(1,n):
        sar[i]=sar[i-1]+af*(ep-sar[i-1])
        if bull:
            if l[i] < sar[i]:
                bull=False; sar[i]=ep; ep=l[i]; af=step
            elif h[i] > ep:
                ep=h[i]; af=min(af+step,mx)
        else:
            if h[i] > sar[i]:
                bull=True; sar[i]=ep; ep=h[i]; af=step
            elif l[i] < ep:
                ep=l[i]; af=min(af+step,mx)
    return sar


def rsi_wilder(c,n=14):
    s=pd.Series(c,dtype=float); d=s.diff(); up=d.clip(lower=0); dn=(-d).clip(lower=0)
    au=up.ewm(alpha=1/n,adjust=False,min_periods=n).mean(); ad=dn.ewm(alpha=1/n,adjust=False,min_periods=n).mean()
    rs=au/ad.replace(0,np.nan); r=100-100/(1+rs); r=r.where(ad.ne(0),100.0)
    return r.to_numpy()


def nq_colors(nq):
    C=nq['Close'].astype(float).to_numpy(); H=nq['High'].astype(float).to_numpy(); L=nq['Low'].astype(float).to_numpy()
    sar=psar_archived(H,L,0.02,0.08)
    ema=pd.Series(C,index=nq.index).ewm(span=21,adjust=False).mean().to_numpy(); rsi=rsi_wilder(C,14)
    above=C>sar; state='Green' if above[0] else 'Yellow'; bsu=bsd=99; prev=None; out=[]
    for i in range(len(C)):
        bsu=0 if (i>0 and above[i] and not above[i-1]) else bsu+1
        bsd=0 if (i>0 and (not above[i]) and above[i-1]) else bsd+1
        ri=float(rsi[i]) if np.isfinite(rsi[i]) else 50.0; dr=ri-prev if prev is not None else 0.0
        if above[i]:
            if state=='Blue': state='Green' if C[i]<ema[i] else 'Blue'
            else: state='Blue' if (ri>52 and bsu>=2 and dr<=3.0) else 'Green'
        else:
            if state=='Red': state='Yellow' if ri>50 else 'Red'
            else: state='Red' if (ri<47 and bsd>=2 and dr>=-3.0) else 'Yellow'
        prev=ri; out.append(state)
    return pd.Series(out,index=nq.index,dtype='object')


def confirmed(a: pd.Series, n: int) -> pd.Series:
    x=a.fillna(False).astype(bool)
    if n <= 1: return x
    return x.rolling(n,min_periods=n).sum().eq(n)


def extra_risk_stats(ret: pd.Series, start=None, end=None):
    x=ret.dropna().copy()
    if start is not None: x=x[x.index>=pd.Timestamp(start)]
    if end is not None: x=x[x.index<=pd.Timestamp(end)]
    if len(x)<30: return {'worst252':np.nan,'uw_sessions':np.nan}
    eq=(1+x).cumprod(); dd=eq/eq.cummax()-1
    roll=(1+x).rolling(252,min_periods=200).apply(np.prod,raw=True)-1
    # longest consecutive underwater run in sessions
    underwater=(dd<0).to_numpy(bool); best=cur=0
    for q in underwater:
        cur=cur+1 if q else 0; best=max(best,cur)
    return {'worst252':float(roll.min()) if roll.notna().any() else np.nan,'uw_sessions':int(best)}


print('=== TQQQ LIFE-PLAN REGIME SEARCH ===',flush=True)
qqq=bt.dl_one('QQQ','2009-01-01'); tqqq=bt.dl_one('TQQQ','2010-01-01'); vix=bt.dl_one('^VIX','1990-01-01'); nq=bt.dl_one('NQ=F','2000-01-01')
mc,mc_cov=bt.compute_mc(); vstate,vsignals=bt.vix_state_series(vix); ind=bt.indicators(qqq); nqcol=nq_colors(nq)

c=qqq['Close'].astype(float); h=qqq['High'].astype(float); l=qqq['Low'].astype(float); vol=qqq['Volume'].astype(float)
ema21=c.ewm(span=21,adjust=False,min_periods=21).mean(); sma50=c.rolling(50,min_periods=50).mean(); sma200=c.rolling(200,min_periods=200).mean()
tp=(h+l+c)/3
vwap63=(tp*vol).rolling(63,min_periods=63).sum()/vol.rolling(63,min_periods=63).sum()
vwap252=(tp*vol).rolling(252,min_periods=200).sum()/vol.rolling(252,min_periods=200).sum()
s50up=sma50>sma50.shift(10); s200up=sma200>sma200.shift(20)

common=ind.index.intersection(tqqq.index)
idx=common[common>=bt.START]
ind=ind.reindex(idx); tqqq=tqqq.reindex(idx); mc=mc.reindex(idx).ffill(); mc_cov=mc_cov.reindex(idx).ffill(); vstate=vstate.reindex(idx).ffill(); nqcol=nqcol.reindex(idx).ffill()
c=c.reindex(idx); ema21=ema21.reindex(idx); sma50=sma50.reindex(idx); sma200=sma200.reindex(idx); vwap63=vwap63.reindex(idx); vwap252=vwap252.reindex(idx); s50up=s50up.reindex(idx); s200up=s200up.reindex(idx)

mc35=mc>=35; mc45=mc>=45; nq_nonred=nqcol!='Red'; nq_bull=nqcol.isin(['Blue','Green'])
above21=c>ema21; above50=c>sma50; above200=c>sma200; above63=c>vwap63; above252=c>vwap252
below50=~above50; below200=~above200; below252=~above252

# Exit raw signals: structural deterioration, optionally requiring slope / MC / NQSAR confirmation.
off_raw={
 'b200': below200,
 'b252': below252,
 'b200_252': below200 & below252,
 'b50_b200': below50 & below200,
 'b200_s50dn': below200 & (~s50up),
 'b252_s50dn': below252 & (~s50up),
 'struct2': (below200.astype(int)+below252.astype(int)+(~s50up).astype(int)).ge(2),
 'b200_mc35': below200 & (~mc35),
 'b252_mc35': below252 & (~mc35),
 'b50_nqred': below50 & (nqcol=='Red'),
}
# Re-entry signals are intentionally faster than many exit signals to catch recoveries.
on_raw={
 'a200': above200,
 'a252': above252,
 'a200_252': above200 & above252,
 'a50': above50,
 'a63': above63,
 'a50_mc35': above50 & mc35,
 'a63_mc35': above63 & mc35,
 'a50_nq': above50 & nq_nonred,
 'a63_nq': above63 & nq_nonred,
 'score3': (above50.astype(int)+above63.astype(int)+mc35.astype(int)+nq_nonred.astype(int)).ge(3),
}

off_conf=[1,3,5]; on_conf=[1,2,3]
risk_on_exps=[0.75,1.0]; risk_off_exps=[0.0,0.10,0.25]
mod_modes=['none','mc25zero','mc35half','nqred50','mc_nq25']

panic_states=np.isin(vstate.astype(str).to_numpy(),['BOTTOM','RE-EXTREME'])
metric_arrays={k:ind[k].to_numpy(float) for k in ['ema21_atr','sma50_atr','vwap63_atr','vwap252_atr']}
mc_a=mc.to_numpy(float); nq_a=nqcol.astype(str).to_numpy(); n=len(idx)


def target_for(off_name,on_name,oc,nc,on_exp,off_exp,mod_mode,panic_seed=0.0,panic_anchor='none',panic_depth=0.0):
    off=confirmed(off_raw[off_name],oc).to_numpy(bool); on=confirmed(on_raw[on_name],nc).to_numpy(bool)
    t=np.zeros(n,float); risk_on=True
    for i in range(n):
        if risk_on:
            if off[i]: risk_on=False
        else:
            if on[i]: risk_on=True
        x=on_exp if risk_on else off_exp
        if risk_on:
            if mod_mode=='mc25zero' and np.isfinite(mc_a[i]) and mc_a[i]<25: x=0.0
            elif mod_mode=='mc35half' and np.isfinite(mc_a[i]) and mc_a[i]<35: x=min(x,0.50)
            elif mod_mode=='nqred50' and nq_a[i]=='Red': x=min(x,0.50)
            elif mod_mode=='mc_nq25' and np.isfinite(mc_a[i]) and mc_a[i]<35 and nq_a[i]=='Red': x=min(x,0.25)
        if (not risk_on) and panic_seed>0 and panic_states[i]:
            hit=True
            if panic_anchor!='none':
                z=metric_arrays[panic_anchor][i]
                hit=np.isfinite(z) and z<=panic_depth
            if hit: x=max(x,panic_seed)
        t[i]=x
    return np.clip(t,0,1)


def row_stats(tgt):
    s=pd.Series(tgt,index=idx,dtype=float)
    ret=bt.strategy_returns(s,tqqq['Open'])
    z={'avg_exposure':float(np.mean(tgt)),'turnover':float(s.diff().abs().sum())}
    z=bt.add_stats(z,ret)
    for pre,a,b in [('full',bt.START,None),('is',bt.START,bt.IS_END),('oos',bt.OOS_START,None)]:
        e=extra_risk_stats(ret,a,b); z[f'{pre}_worst252']=e['worst252']; z[f'{pre}_uw_sessions']=e['uw_sessions']
    return z

# Stage A: broad exit/re-entry grid without panic overlay.
rows=[]
params=itertools.product(off_raw.keys(),on_raw.keys(),off_conf,on_conf,risk_on_exps,risk_off_exps,mod_modes)
for offn,onn,oc,nc,onexp,offexp,mod in params:
    tgt=target_for(offn,onn,oc,nc,onexp,offexp,mod)
    rows.append({'off':offn,'on':onn,'off_conf':oc,'on_conf':nc,'on_exp':onexp,'off_exp':offexp,'mod':mod,
                 'panic_seed':0.0,'panic_anchor':'none','panic_depth':0.0,**row_stats(tgt)})
dA=pd.DataFrame(rows)
dA['min_io_cagr']=dA[['is_cagr','oos_cagr']].min(axis=1); dA['min_io_calmar']=dA[['is_calmar','oos_calmar']].min(axis=1)
dA.to_csv('tqqq_stage6_base.csv',index=False)
print('[stage6] base configs',len(dA),flush=True)

# Select by IS only plus MDD bands; no OOS is used for selection of overlay bases.
sel=set(dA.sort_values(['is_cagr','is_calmar'],ascending=False).head(80).index)
sel.update(dA.sort_values(['is_calmar','is_cagr'],ascending=False).head(80).index)
for lim in (.20,.25,.30,.35,.40,.45,.50):
    sel.update(dA[dA.is_mdd>=-lim].sort_values(['is_cagr','is_calmar'],ascending=False).head(60).index)
for offn in off_raw:
    z=dA[dA.off==offn]; sel.update(z.sort_values(['is_calmar','is_cagr'],ascending=False).head(12).index)
base_ix=sorted(sel)
print('[stage6] selected bases',len(base_ix),flush=True)

# Stage B: VIX BOTTOM/RE-EXTREME seed while Risk-OFF. It never forces a sale.
panic_seeds=[0.25,0.50,0.75,1.00]
panic_anchors=['none','ema21_atr','sma50_atr','vwap63_atr']
panic_depths={'none':[0.0],'ema21_atr':[-1.0,-1.5,-2.0],'sma50_atr':[-1.0,-1.5,-2.0],'vwap63_atr':[-1.0,-1.5,-2.0]}
rows2=[{'base_ix':int(i),**dA.loc[i].to_dict()} for i in base_ix]
for bix in base_ix:
    b=dA.loc[bix]
    for seed,anch in itertools.product(panic_seeds,panic_anchors):
        for depth in panic_depths[anch]:
            tgt=target_for(str(b.off),str(b.on),int(b.off_conf),int(b.on_conf),float(b.on_exp),float(b.off_exp),str(b.mod),seed,anch,float(depth))
            rows2.append({'base_ix':int(bix),'off':str(b.off),'on':str(b.on),'off_conf':int(b.off_conf),'on_conf':int(b.on_conf),'on_exp':float(b.on_exp),'off_exp':float(b.off_exp),'mod':str(b.mod),
                          'panic_seed':seed,'panic_anchor':anch,'panic_depth':float(depth),**row_stats(tgt)})
d=pd.DataFrame(rows2)
d['min_io_cagr']=d[['is_cagr','oos_cagr']].min(axis=1); d['min_io_calmar']=d[['is_calmar','oos_calmar']].min(axis=1)
d.to_csv('tqqq_stage6_lifeplan.csv',index=False)
print('[stage6] total configs',len(d),flush=True)

print('\n=== MAX CAGR BY FULL MDD LIMIT ===')
for lim in (.20,.25,.30,.35,.40,.45,.50,.60):
    q=d[d.full_mdd>=-lim].sort_values(['full_cagr','min_io_cagr','full_calmar'],ascending=False).head(1)
    if len(q):
        r=q.iloc[0]
        print(f"MDD<={lim*100:.0f}% CAGR={r.full_cagr*100:.2f}% MDD={r.full_mdd*100:.2f}% Calmar={r.full_calmar:.3f} minIO={r.min_io_cagr*100:.2f}% worst1y={r.full_worst252*100:.1f}% uw={int(r.full_uw_sessions)} off={r.off}/{int(r.off_conf)} on={r.on}/{int(r.on_conf)} exp={r.on_exp:.2f}/{r.off_exp:.2f} mod={r.mod} panic={r.panic_seed:.2f}:{r.panic_anchor}@{r.panic_depth}")

print('\n=== ROBUST: MAX min(IS,OOS CAGR) BY MDD LIMIT ===')
for lim in (.20,.25,.30,.35,.40,.45,.50):
    q=d[d.full_mdd>=-lim].sort_values(['min_io_cagr','full_cagr','min_io_calmar'],ascending=False).head(1)
    if len(q):
        r=q.iloc[0]
        print(f"MDD<={lim*100:.0f}% minIO={r.min_io_cagr*100:.2f}% FULL={r.full_cagr*100:.2f}% MDD={r.full_mdd*100:.2f}% IS={r.is_cagr*100:.2f}% OOS={r.oos_cagr*100:.2f}% C={r.full_calmar:.3f} worst1y={r.full_worst252*100:.1f}% uw={int(r.full_uw_sessions)} :: off={r.off}/{int(r.off_conf)} on={r.on}/{int(r.on_conf)} exp={r.on_exp:.2f}/{r.off_exp:.2f} mod={r.mod} panic={r.panic_seed:.2f}:{r.panic_anchor}@{r.panic_depth}")

print('\n=== PARETO-LIKE LIFE PLAN CANDIDATES (MDD<=40, minIO CAGR>=25) ===')
z=d[(d.full_mdd>=-.40)&(d.min_io_cagr>=.25)].copy()
# prioritize smaller drawdown in 2.5pt buckets, then return
z['dd_bucket']=(np.ceil(abs(z.full_mdd)*40)/40)
for _,r in z.sort_values(['dd_bucket','min_io_cagr','full_cagr'],ascending=[True,False,False]).head(30).iterrows():
    print(f"FULL {r.full_cagr*100:5.2f}% MDD={r.full_mdd*100:6.2f}% minIO={r.min_io_cagr*100:5.2f}% IS/OOS={r.is_cagr*100:5.2f}/{r.oos_cagr*100:5.2f}% worst1y={r.full_worst252*100:6.1f}% uw={int(r.full_uw_sessions):4d} avg={r.avg_exposure*100:4.1f}% :: {r.off}/{int(r.off_conf)} -> {r.on}/{int(r.on_conf)} exp {r.on_exp:.2f}/{r.off_exp:.2f} {r.mod} panic {r.panic_seed:.2f}:{r.panic_anchor}@{r.panic_depth}")

print('\n=== VIX PANIC OVERLAY MATCHED DELTAS ===')
# compare each overlay to its exact base_ix no-panic row
base=dA
ov=d[d.panic_seed>0].copy()
for k in ['full_cagr','full_mdd','full_calmar','oos_cagr','oos_mdd','oos_calmar']:
    ov[k+'_delta']=ov.apply(lambda r:r[k]-base.loc[int(r.base_ix),k],axis=1)
for seed in panic_seeds:
    q=ov[ov.panic_seed==seed]
    print(f"seed={seed:.2f} median FULL dCAGR={q.full_cagr_delta.median()*100:+.2f}pt dMDD={q.full_mdd_delta.median()*100:+.2f}pt dCalmar={q.full_calmar_delta.median():+.3f}; OOS dCAGR={q.oos_cagr_delta.median()*100:+.2f}pt dMDD={q.oos_mdd_delta.median()*100:+.2f}pt")

bench={str(w):bt.stats(bt.fixed_returns(w,tqqq['Open']),bt.START,None) for w in (0,.25,.50,.75,1.0)}
summary={'start':str(idx[0].date()),'end':str(idx[-1].date()),'base_configs':len(dA),'selected_bases':len(base_ix),'total_configs':len(d),'benchmarks':bench,
         'note':'Life-plan search: structural Risk-OFF + faster re-entry + optional VIX BOTTOM/RE-EXTREME seed. Drawdown and OOS robustness are explicit outputs; NQSAR is archived V38 fallback proxy.'}
Path('tqqq_stage6_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
print('\n=== SUMMARY ==='); print(json.dumps(summary,ensure_ascii=False,indent=2,default=str),flush=True)
