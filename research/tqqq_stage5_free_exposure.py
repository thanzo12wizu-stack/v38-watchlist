from __future__ import annotations

import itertools
import json
from pathlib import Path

import numpy as np
import pandas as pd

from research import tqqq_backtest_once as bt

# Search TQQQ exposure freely from 0..100%. No mandatory core holding.
# Signals are formed at close and executed at the next session open using bt.strategy_returns.


def psar_archived(h, l, step=0.02, mx=0.08):
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


print('=== TQQQ FREE-EXPOSURE RETURN SEARCH ===', flush=True)
qqq=bt.dl_one('QQQ','2009-01-01'); tqqq=bt.dl_one('TQQQ','2010-01-01'); vix=bt.dl_one('^VIX','1990-01-01'); nq=bt.dl_one('NQ=F','2000-01-01')
mc,mc_cov=bt.compute_mc(); vstate,vsignals=bt.vix_state_series(vix); ind=bt.indicators(qqq); nqcol=nq_colors(nq)

# Extra trend lines on QQQ.
c=qqq['Close'].astype(float); h=qqq['High'].astype(float); l=qqq['Low'].astype(float); v=qqq['Volume'].astype(float)
ema21=c.ewm(span=21,adjust=False,min_periods=21).mean(); sma50=c.rolling(50,min_periods=50).mean(); sma200=c.rolling(200,min_periods=200).mean()
tp=(h+l+c)/3.0
vwap63=(tp*v).rolling(63,min_periods=63).sum()/v.rolling(63,min_periods=63).sum()
vwap252=(tp*v).rolling(252,min_periods=200).sum()/v.rolling(252,min_periods=200).sum()
trend=pd.DataFrame(index=qqq.index)
trend['ema21']=c>ema21; trend['sma50']=c>sma50; trend['sma200']=c>sma200; trend['vwap63']=c>vwap63; trend['vwap252']=c>vwap252
trend['ema21_sma50']=trend['ema21']&trend['sma50']; trend['sma50_sma200']=trend['sma50']&trend['sma200']; trend['all3']=trend['ema21']&trend['sma50']&trend['sma200']

common=ind.index.intersection(tqqq.index)
ind=ind.reindex(common); tqqq=tqqq.reindex(common); mc=mc.reindex(common).ffill(); mc_cov=mc_cov.reindex(common).ffill(); vstate=vstate.reindex(common).ffill(); nqcol=nqcol.reindex(common).ffill(); trend=trend.reindex(common).ffill()
mask=common>=bt.START
ind=ind.loc[mask]; tqqq=tqqq.loc[mask]; mc=mc.loc[mask]; mc_cov=mc_cov.loc[mask]; vstate=vstate.loc[mask]; nqcol=nqcol.loc[mask]; trend=trend.loc[mask]

# numpy arrays for speed
open_px=tqqq['Open']
ret_open=open_px.pct_change().to_numpy(float)
idx=ind.index; n=len(idx)
mc_a=mc.to_numpy(float)
vs=vstate.astype(str).to_numpy(); nq_a=nqcol.astype(str).to_numpy()
panic=np.isin(vs,['BOTTOM','RE-EXTREME'])

trend_names=['ema21','sma50','sma200','vwap63','vwap252','ema21_sma50','sma50_sma200','all3']
anchors=['ema21_atr','sma50_atr','vwap63_atr','vwap252_atr']

# Coarse but broad parameter space. All exposures are fractions of portfolio in TQQQ.
bull_exps=[0.75,1.00]
bear_exps=[0.00,0.10,0.25,0.50]
mc_modes=['none','35','45','graded']
nq_modes=['none','red25','red0_yellow50','soft']
hard200_caps=[1.00,0.50,0.25,0.00]

# Dip ladders: (thresholds, target exposures). 'none' means no dip overlay.
dip_defs={
    'none':((),()),
    'shallow':((-0.5,-1.0,-1.5),(0.75,0.90,1.00)),
    'medium':((-1.0,-1.5,-2.0),(0.75,0.90,1.00)),
    'deep':((-1.5,-2.0,-2.5),(0.75,0.90,1.00)),
}
# Normal dip gate. Panic BOTTOM/RE-EXTREME bypasses this gate.
dip_mc_gates=[25.0,35.0,45.0]
# Overextension trims: threshold in ATR, cap. none leaves bull exposure intact.
ext_defs={'none':(999.0,1.0),'x15_75':(1.5,0.75),'x20_75':(2.0,0.75),'x20_50':(2.0,0.50)}


def apply_stats(target: np.ndarray):
    # close t target -> next-session open execution; same convention as prior stages
    s=pd.Series(target,index=idx,dtype=float)
    r=bt.strategy_returns(s,open_px)
    return bt.add_stats({'avg_exposure':float(np.nanmean(target)),'turnover':float(s.diff().abs().sum())},r)


def make_target(tr_name,bull_exp,bear_exp,mc_mode,nq_mode,hard200_cap,anchor,dip_name,dip_gate,ext_name):
    tr=trend[tr_name].fillna(False).to_numpy(bool)
    t=np.where(tr,bull_exp,bear_exp).astype(float)

    # MC as regime modifier, not a fixed core.
    if mc_mode=='35': t=np.where(mc_a>=35.0,t,np.minimum(t,bear_exp))
    elif mc_mode=='45': t=np.where(mc_a>=45.0,t,np.minimum(t,bear_exp))
    elif mc_mode=='graded':
        caps=np.where(mc_a<25,0.0,np.where(mc_a<35,0.25,np.where(mc_a<45,0.50,1.0)))
        t=np.minimum(t,caps)

    # NQSAR tested as caps only; panic can later override via dip ladder.
    if nq_mode=='red25': t=np.where(nq_a=='Red',np.minimum(t,0.25),t)
    elif nq_mode=='red0_yellow50':
        t=np.where(nq_a=='Red',0.0,t); t=np.where(nq_a=='Yellow',np.minimum(t,0.50),t)
    elif nq_mode=='soft':
        caps=np.select([nq_a=='Blue',nq_a=='Green',nq_a=='Yellow',nq_a=='Red'],[1.0,0.85,0.65,0.35],default=1.0)
        t=np.minimum(t,caps)

    # Structural 200DMA cap searched independently from the trend trigger.
    if hard200_cap<1.0:
        below200=~trend['sma200'].fillna(False).to_numpy(bool)
        t=np.where(below200,np.minimum(t,hard200_cap),t)

    metric=ind[anchor].to_numpy(float)
    ths,levels=dip_defs[dip_name]
    if ths:
        allow=(mc_a>=dip_gate)|panic
        for th,lev in zip(ths,levels):
            hit=np.isfinite(metric)&(metric<=th)&allow
            t=np.where(hit,np.maximum(t,lev),t)

    ex_th,ex_cap=ext_defs[ext_name]
    if ex_th<900:
        hit=np.isfinite(metric)&(metric>=ex_th)&(~panic)
        t=np.where(hit,np.minimum(t,ex_cap),t)

    return np.clip(t,0.0,1.0)

# Stage A: broad search without dip overlay first, then retain winners by IS CAGR/Calmar and metric diversity.
rows=[]
base_params=[]
for tr_name,bull_exp,bear_exp,mc_mode,nq_mode,hardcap in itertools.product(trend_names,bull_exps,bear_exps,mc_modes,nq_modes,hard200_caps):
    # anchor does not matter with no overlays; use sma50 placeholder.
    tgt=make_target(tr_name,bull_exp,bear_exp,mc_mode,nq_mode,hardcap,'sma50_atr','none',35.0,'none')
    st=apply_stats(tgt)
    row={'trend':tr_name,'bull_exp':bull_exp,'bear_exp':bear_exp,'mc_mode':mc_mode,'nq_mode':nq_mode,'hard200_cap':hardcap,'anchor':'none','dip':'none','dip_mc':None,'ext':'none',**st}
    rows.append(row)
dA=pd.DataFrame(rows)
dA.to_csv('tqqq_stage5_base_grid.csv',index=False)
print('[stage5] base configs',len(dA),flush=True)

# Select bases by IS only for overlay search; retain high-return and high-Calmar candidates.
sel=set(dA.sort_values(['is_cagr','is_calmar'],ascending=False).head(60).index)
sel.update(dA.sort_values(['is_calmar','is_cagr'],ascending=False).head(60).index)
for lim in (.30,.35,.40,.45,.50,.60):
    sel.update(dA[dA.is_mdd>=-lim].sort_values(['is_cagr','is_calmar'],ascending=False).head(30).index)
# preserve each trend family's best
for tn in trend_names:
    z=dA[dA.trend==tn]
    sel.update(z.sort_values(['is_cagr','is_calmar'],ascending=False).head(15).index)
base_ix=sorted(sel)
print('[stage5] IS-selected bases for overlays',len(base_ix),flush=True)

rows2=[]
for bix in base_ix:
    b=dA.loc[bix]
    # include no-overlay row for matched comparison
    rows2.append({'base_ix':int(bix),**b.to_dict()})
    for anchor,dip_name,dip_gate,ext_name in itertools.product(anchors,['shallow','medium','deep'],dip_mc_gates,ext_defs.keys()):
        tgt=make_target(str(b.trend),float(b.bull_exp),float(b.bear_exp),str(b.mc_mode),str(b.nq_mode),float(b.hard200_cap),anchor,dip_name,float(dip_gate),ext_name)
        st=apply_stats(tgt)
        rows2.append({'base_ix':int(bix),'trend':str(b.trend),'bull_exp':float(b.bull_exp),'bear_exp':float(b.bear_exp),'mc_mode':str(b.mc_mode),'nq_mode':str(b.nq_mode),'hard200_cap':float(b.hard200_cap),'anchor':anchor,'dip':dip_name,'dip_mc':float(dip_gate),'ext':ext_name,**st})
d=pd.DataFrame(rows2)
d.to_csv('tqqq_stage5_free_exposure.csv',index=False)
print('[stage5] total configs',len(d),flush=True)

# Benchmarks
bench={}
for w in (0.0,0.25,0.50,0.75,1.0):
    bench[str(w)]=bt.stats(bt.fixed_returns(w,open_px),bt.START,None)

print('\n=== ABSOLUTE MAX CAGR (diagnostic; full-sample selected) ===')
for _,r in d.sort_values(['full_cagr','full_calmar'],ascending=False).head(20).iterrows():
    print(f"{r.trend:12s} bull={r.bull_exp:.2f} bear={r.bear_exp:.2f} MC={r.mc_mode:6s} NQ={r.nq_mode:15s} 200cap={r.hard200_cap:.2f} anchor={r.anchor:11s} dip={r.dip:7s}/{str(r.dip_mc):4s} ext={r.ext:7s} CAGR={r.full_cagr*100:6.2f}% MDD={r.full_mdd*100:7.2f}% C={r.full_calmar:.3f} avg={r.avg_exposure*100:5.1f}%")

print('\n=== MAX CAGR BY FULL MDD LIMIT ===')
for lim in (.25,.30,.35,.40,.45,.50,.60,.70,.80):
    q=d[d.full_mdd>=-lim].sort_values(['full_cagr','full_calmar'],ascending=False).head(1)
    if len(q):
        r=q.iloc[0]
        print(f"MDD<={lim*100:.0f}% CAGR={r.full_cagr*100:.2f}% MDD={r.full_mdd*100:.2f}% C={r.full_calmar:.3f} trend={r.trend} bull={r.bull_exp:.2f} bear={r.bear_exp:.2f} MC={r.mc_mode} NQ={r.nq_mode} 200cap={r.hard200_cap:.2f} {r.anchor}/{r.dip}/MC{r.dip_mc}/{r.ext}")

print('\n=== IS CAGR TOP 20 -> UNTOUCHED OOS ===')
topis=d.sort_values(['is_cagr','is_calmar'],ascending=False).head(20)
for _,r in topis.iterrows():
    print(f"IS {r.is_cagr*100:6.2f}%/{r.is_mdd*100:7.2f}% C={r.is_calmar:.3f} | OOS {r.oos_cagr*100:6.2f}%/{r.oos_mdd*100:7.2f}% C={r.oos_calmar:.3f} | FULL {r.full_cagr*100:6.2f}%/{r.full_mdd*100:7.2f}% :: {r.trend} b{r.bull_exp:.2f}/{r.bear_exp:.2f} MC={r.mc_mode} NQ={r.nq_mode} cap={r.hard200_cap:.2f} {r.anchor}/{r.dip}/{r.dip_mc}/{r.ext}")

# Robust high-return ranking: maximize the weaker of IS/OOS CAGR, then full CAGR.
d['min_io_cagr']=d[['is_cagr','oos_cagr']].min(axis=1)
d['min_io_calmar']=d[['is_calmar','oos_calmar']].min(axis=1)
print('\n=== ROBUST RETURN: MAX min(IS,OOS CAGR) ===')
for _,r in d.sort_values(['min_io_cagr','full_cagr','min_io_calmar'],ascending=False).head(20).iterrows():
    print(f"minIO={r.min_io_cagr*100:5.2f}% FULL={r.full_cagr*100:6.2f}% MDD={r.full_mdd*100:7.2f}% IS={r.is_cagr*100:5.2f}% OOS={r.oos_cagr*100:5.2f}% C={r.full_calmar:.3f} :: {r.trend} b{r.bull_exp:.2f}/{r.bear_exp:.2f} MC={r.mc_mode} NQ={r.nq_mode} cap={r.hard200_cap:.2f} {r.anchor}/{r.dip}/{r.dip_mc}/{r.ext}")

summary={
    'start':str(idx[0].date()),'end':str(idx[-1].date()),'sessions':int(n),'base_configs':int(len(dA)),'total_configs':int(len(d)),
    'benchmarks':bench,
    'best_full_cagr':d.sort_values(['full_cagr','full_calmar'],ascending=False).iloc[0].to_dict(),
    'best_robust_return':d.sort_values(['min_io_cagr','full_cagr','min_io_calmar'],ascending=False).iloc[0].to_dict(),
    'note':'No mandatory TQQQ core. Exposure is freely searched from 0 to 100%. Full-sample best is diagnostic; robust ranking maximizes min(IS,OOS CAGR). NQSAR uses archived V38 fallback proxy.'
}
Path('tqqq_stage5_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
print('\n=== SUMMARY ==='); print(json.dumps(summary,ensure_ascii=False,indent=2,default=str))
