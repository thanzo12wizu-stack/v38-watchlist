from __future__ import annotations
import json, math
from pathlib import Path
import numpy as np
import pandas as pd
from research import tqqq_backtest_once as bt

STAGE3=Path('prev3/tqqq_stage3_smart_vix.csv')
if not STAGE3.exists(): raise SystemExit('missing stage3 results')
d3=pd.read_csv(STAGE3)

# Reconstruct the historical V38 NQSAR fallback FSM from the archived implementation.
def psar(h,l,step=0.02,mx=0.08):
    h=np.asarray(h,float); l=np.asarray(l,float); n=len(h)
    sar=np.full(n,np.nan); bull=True; af=step; ep=l[0]; sar[0]=l[0]
    for i in range(1,n):
        sar[i]=sar[i-1]+af*(ep-sar[i-1])
        if bull:
            # standard two-bar clamp for stability; archived fallback used direction/AF logic.
            if i>=2: sar[i]=min(sar[i],l[i-1],l[i-2])
            elif i>=1: sar[i]=min(sar[i],l[i-1])
            if l[i] < sar[i]:
                bull=False; sar[i]=ep; ep=l[i]; af=step
            elif h[i] > ep:
                ep=h[i]; af=min(af+step,mx)
        else:
            if i>=2: sar[i]=max(sar[i],h[i-1],h[i-2])
            elif i>=1: sar[i]=max(sar[i],h[i-1])
            if h[i] > sar[i]:
                bull=True; sar[i]=ep; ep=h[i]; af=step
            elif l[i] < ep:
                ep=l[i]; af=min(af+step,mx)
    return sar

def psar_archived(h,l,step=0.02,mx=0.08):
    # Exact archived V38 fallback implementation (no two-bar clamp).
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
    s=pd.Series(c,dtype=float)
    d=s.diff(); up=d.clip(lower=0); dn=(-d).clip(lower=0)
    au=up.ewm(alpha=1/n,adjust=False,min_periods=n).mean()
    ad=dn.ewm(alpha=1/n,adjust=False,min_periods=n).mean()
    rs=au/ad.replace(0,np.nan)
    r=100-100/(1+rs)
    r= r.where(ad.ne(0),100.0)
    return r.to_numpy()

def nq_colors(nq,use_clamped=False):
    C=nq['Close'].astype(float).to_numpy(); H=nq['High'].astype(float).to_numpy(); L=nq['Low'].astype(float).to_numpy()
    sar=(psar(H,L,0.02,0.08) if use_clamped else psar_archived(H,L,0.02,0.08))
    ema=pd.Series(C,index=nq.index).ewm(span=21,adjust=False).mean().to_numpy()
    rsi=rsi_wilder(C,14)
    above=C>sar; state='Green' if above[0] else 'Yellow'; bsu=bsd=99; prev=None; out=[]
    for i in range(len(C)):
        bsu=0 if (i>0 and above[i] and not above[i-1]) else bsu+1
        bsd=0 if (i>0 and (not above[i]) and above[i-1]) else bsd+1
        ri=float(rsi[i]) if np.isfinite(rsi[i]) else 50.0
        dr=ri-prev if prev is not None else 0.0
        if above[i]:
            if state=='Blue': state='Green' if C[i]<ema[i] else 'Blue'
            else: state='Blue' if (ri>52 and bsu>=2 and dr<=3.0) else 'Green'
        else:
            if state=='Red': state='Yellow' if ri>50 else 'Red'
            else: state='Red' if (ri<47 and bsd>=2 and dr>=-3.0) else 'Yellow'
        prev=ri; out.append(state)
    return pd.Series(out,index=nq.index,dtype='object')

# Data
qqq=bt.dl_one('QQQ','2009-01-01'); tqqq=bt.dl_one('TQQQ','2010-01-01'); vix=bt.dl_one('^VIX','1990-01-01'); nq=bt.dl_one('NQ=F','2000-01-01')
mc,mc_cov=bt.compute_mc(); vstate,vsignals=bt.vix_state_series(vix); ind=bt.indicators(qqq)
colors=nq_colors(nq,use_clamped=False); colors_clamped=nq_colors(nq,use_clamped=True)

# Validate reconstructed proxy against committed authoritative recent states where available.
actual=[]
try:
    arr=json.loads(Path('trend_history.json').read_text(encoding='utf-8'))
    actual=pd.Series({pd.Timestamp(d):c for d,c in arr},dtype='object')
except Exception: actual=pd.Series(dtype='object')
def validate(proxy,name):
    if actual.empty: return {'name':name,'n':0,'acc':None}
    p=proxy.reindex(actual.index).dropna(); a=actual.reindex(p.index)
    return {'name':name,'n':int(len(p)),'acc':float((p==a).mean()) if len(p) else None,
            'pairs':pd.crosstab(a,p).to_dict() if len(p) else {}}
val_arch=validate(colors,'archived_exact_psar'); val_clamp=validate(colors_clamped,'clamped_psar')
print('=== NQSAR PROXY VALIDATION VS COMMITTED TREND_HISTORY ===')
print(json.dumps(val_arch,ensure_ascii=False,default=str)); print(json.dumps(val_clamp,ensure_ascii=False,default=str))
# Use whichever proxy matches the authoritative recent series better, with archived exact winning ties.
acc_a=-1 if val_arch['acc'] is None else val_arch['acc']; acc_c=-1 if val_clamp['acc'] is None else val_clamp['acc']
nqcol=colors if acc_a>=acc_c else colors_clamped
proxy_name='archived_exact_psar' if acc_a>=acc_c else 'clamped_psar'
print('[stage4] using proxy',proxy_name,flush=True)

common=ind.index.intersection(tqqq.index)
ind=ind.reindex(common); tqqq=tqqq.reindex(common); mc=mc.reindex(common).ffill(); mc_cov=mc_cov.reindex(common).ffill(); vstate=vstate.reindex(common).ffill(); nqcol=nqcol.reindex(common).ffill()
mask=common>=bt.START
ind=ind.loc[mask]; tqqq=tqqq.loc[mask]; mc=mc.loc[mask]; mc_cov=mc_cov.loc[mask]; vstate=vstate.loc[mask]; nqcol=nqcol.loc[mask]

# Select Stage3 configs by IS only, not OOS. Keep metric diversity and both MC35/45.
x=d3[(d3['panic_mode']=='release_bottom') & (d3['mc_gate'].isin([35.0,45.0]))].copy()
sel=[]
for metric in ['ema21_atr','sma50_atr','vwap63_atr','vwap252_atr']:
    z=x[x.metric==metric]
    sel += list(z.sort_values(['is_calmar','is_cagr'],ascending=False).head(12).index)
    sel += list(z.sort_values(['is_cagr','is_calmar'],ascending=False).head(12).index)
    for lim in (.35,.40,.45,.50):
        sel += list(z[z.is_mdd>=-lim].sort_values(['is_cagr','is_calmar'],ascending=False).head(8).index)
sel=sorted(set(sel)); bases=x.loc[sel].copy()
print('[stage4] IS-only stage3 bases',len(bases),flush=True)

MODES={
 'none':{},
 'gate_nonred':{'gate':{'Blue','Green','Yellow'}},
 'gate_bull':{'gate':{'Blue','Green'}},
 'gate_blue':{'gate':{'Blue'}},
 'red_exit':{'exit_colors':{'Red'}},
 'yellowred_exit':{'exit_colors':{'Yellow','Red'}},
 'cap_soft':{'caps':{'Blue':1.00,'Green':1.00,'Yellow':0.75,'Red':0.55}},
 'cap_strict':{'caps':{'Blue':1.00,'Green':0.75,'Yellow':0.55,'Red':0.30}},
 'gate_bull_cap_soft':{'gate':{'Blue','Green'},'caps':{'Blue':1.00,'Green':1.00,'Yellow':0.75,'Red':0.55}},
}
PANIC={'BOTTOM','RE-EXTREME'}

def target_with_nq(metric,entries,exit_level,tactical,mc_gate,mode):
    cfg=MODES[mode]; held=0; out=[]
    for d,xv in metric.items():
        state=str(nqcol.loc[d]); panic=str(vstate.loc[d]) in PANIC
        x=float(xv) if pd.notna(xv) else np.nan
        if np.isfinite(x) and held>0 and x>=exit_level: held=0
        # NQSAR forced exit variants; panic BOTTOM explicitly overrides them.
        if not panic and state in cfg.get('exit_colors',set()): held=0
        if np.isfinite(x):
            desired=bt.tier_from_value(x,entries)
            if desired>held:
                allow=(pd.notna(mc.loc[d]) and float(mc.loc[d])>=float(mc_gate))
                if not panic and 'gate' in cfg: allow=allow and state in cfg['gate']
                if panic: allow=True
                if allow: held=desired
        tgt=bt.CORE+(tactical[held-1] if held else 0.0)
        if not panic and 'caps' in cfg: tgt=min(tgt,float(cfg['caps'].get(state,1.0)))
        out.append(max(bt.CORE,min(1.0,tgt)))
    return pd.Series(out,index=metric.index,dtype=float)

rows=[]
for bix,b in bases.iterrows():
    metric=ind[str(b.metric)]; entries=tuple(float(q) for q in str(b.entries).split('/')); ex=float(b['exit']); tactical=bt.ALLOC_SHAPES[str(b['shape'])]; gate=float(b.mc_gate)
    for mode in MODES:
        target=target_with_nq(metric,entries,ex,tactical,gate,mode)
        ret=bt.strategy_returns(target,tqqq['Open'])
        row={'stage3_ix':int(bix),'metric':str(b.metric),'entries':str(b.entries),'exit':ex,'shape':str(b['shape']),'mc_gate':gate,'panic_mode':'release_bottom','nqsar_mode':mode,
             'avg_exposure':float(target.mean()),'turnover':float(target.diff().abs().sum())}
        rows.append(bt.add_stats(row,ret))
d=pd.DataFrame(rows)
# matched deltas vs same base no NQSAR
base=d[d.nqsar_mode=='none'].set_index('stage3_ix')
for p in ['full','is','oos']:
    for k in ['cagr','mdd','calmar']:
        d[f'{p}_{k}_delta']=d.apply(lambda r:r[f'{p}_{k}']-base.loc[int(r.stage3_ix)][f'{p}_{k}'],axis=1)
d.to_csv('tqqq_stage4_nqsar.csv',index=False)

print('\n=== NQSAR MODE DIAGNOSTICS MATCHED SAME BASE ===')
for mode in MODES:
    z=d[d.nqsar_mode==mode]
    print(f"{mode:20s} FULL dCAGR={z.full_cagr_delta.median()*100:+.2f}pt dMDD={z.full_mdd_delta.median()*100:+.2f}pt dCalmar={z.full_calmar_delta.median():+.3f} winC={(z.full_calmar_delta>0).mean()*100:.0f}% | OOS dCAGR={z.oos_cagr_delta.median()*100:+.2f}pt dMDD={z.oos_mdd_delta.median()*100:+.2f}pt dCalmar={z.oos_calmar_delta.median():+.3f} winC={(z.oos_calmar_delta>0).mean()*100:.0f}%")

print('\n=== MAX CAGR BY FULL MDD LIMIT ===')
for lim in (.35,.40,.45,.50,.55,.60):
    q=d[d.full_mdd>=-lim].sort_values(['full_cagr','full_calmar'],ascending=False).head(1)
    if len(q):
        r=q.iloc[0]
        print(f"MDD<={lim*100:.0f}% {r.metric} {r.entries} exit=+{r['exit']} {r['shape']} MC={int(r.mc_gate)} VIX=bottom NQ={r.nqsar_mode} CAGR={r.full_cagr*100:.2f}% MDD={r.full_mdd*100:.2f}% C={r.full_calmar:.3f} IS_C={r.is_calmar:.3f} OOS_C={r.oos_calmar:.3f} avgExp={r.avg_exposure*100:.1f}%")

print('\n=== BEST FULL CALMAR ===')
for _,r in d.sort_values(['full_calmar','full_cagr'],ascending=False).head(20).iterrows():
    print(f"{r.metric:12s} {r.entries:20s} exit=+{r['exit']:<3} {r['shape']:6s} MC={int(r.mc_gate)} NQ={r.nqsar_mode:18s} CAGR={r.full_cagr*100:6.2f}% MDD={r.full_mdd*100:7.2f}% C={r.full_calmar:.3f} IS_C={r.is_calmar:.3f} OOS_C={r.oos_calmar:.3f}")

# IS-only selected top and show untouched OOS.
print('\n=== IS-SELECTED TOP 15, THEN OOS ===')
for _,r in d.sort_values(['is_calmar','is_cagr'],ascending=False).head(15).iterrows():
    print(f"{r.metric:12s} {r.entries:20s} {r['shape']:6s} MC={int(r.mc_gate)} NQ={r.nqsar_mode:18s} IS CAGR={r.is_cagr*100:6.2f}% MDD={r.is_mdd*100:7.2f}% C={r.is_calmar:.3f} | OOS CAGR={r.oos_cagr*100:6.2f}% MDD={r.oos_mdd*100:7.2f}% C={r.oos_calmar:.3f} | FULL C={r.full_calmar:.3f}")

# robust diagnostic only
_d=d.copy(); _d['min_io_calmar']=_d[['is_calmar','oos_calmar']].min(axis=1)
print('\n=== ROBUSTNESS DIAGNOSTIC ===')
for _,r in _d.sort_values(['min_io_calmar','full_calmar'],ascending=False).head(15).iterrows():
    print(f"{r.metric:12s} {r.entries:20s} {r['shape']:6s} MC={int(r.mc_gate)} NQ={r.nqsar_mode:18s} minIO={r.min_io_calmar:.3f} FULL={r.full_calmar:.3f} CAGR={r.full_cagr*100:.2f}% MDD={r.full_mdd*100:.2f}%")

summary={'proxy_used':proxy_name,'proxy_validation_archived':val_arch,'proxy_validation_clamped':val_clamp,'bases':len(bases),'configs':len(d),
         'note':'NQSAR here is the archived V38 reconstructed fallback FSM, not the authoritative EXP_STATE_ID export. VIX BOTTOM/RE-EXTREME overrides NQSAR restrictions so panic buying remains enabled.'}
Path('tqqq_stage4_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
print('\n=== SUMMARY ==='); print(json.dumps(summary,ensure_ascii=False,indent=2,default=str))
