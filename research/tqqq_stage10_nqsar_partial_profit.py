from __future__ import annotations
import json
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
    au=u.ewm(alpha=1/n,adjust=False,min_periods=n).mean(); ad=dn.ewm(alpha=1/n,adjust=False,min_periods=n).mean()
    rs=au/ad.replace(0,np.nan); y=100-100/(1+rs)
    return y.where(ad.ne(0),100.).to_numpy()


def nq_colors(nq):
    C=nq.Close.astype(float).to_numpy(); H=nq.High.astype(float).to_numpy(); L=nq.Low.astype(float).to_numpy(); S=psar(H,L)
    E=pd.Series(C,index=nq.index).ewm(span=21,adjust=False).mean().to_numpy(); R=rsi(C)
    a=C>S; st='Green' if a[0] else 'Yellow'; up=dn=99; prev=None; out=[]
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


def summarize(x):
    x=pd.Series(x,dtype=float).dropna()
    if len(x)==0: return dict(n=0,mean=np.nan,median=np.nan,win=np.nan,worst=np.nan,best=np.nan)
    return dict(n=int(len(x)),mean=float(x.mean()),median=float(x.median()),win=float((x>0).mean()),worst=float(x.min()),best=float(x.max()))


def trade_exit(sig, e, idx, nq, tq):
    # Signal at close sig, entry at next session open e. Exit signal known at close, then next open.
    kind=sig['kind']; maxhold={'RG':7,'GB':20,'BY':10,'RY':10}[kind]
    start_i=idx.get_loc(e)
    for j in range(start_i, min(start_i+maxhold, len(idx)-1)):
        d=idx[j]; cur=str(nq.loc[d]); prev=str(nq.shift(1).loc[d]) if j>0 else ''
        tr=f'{prev}->{cur}'
        ex=False
        if kind=='RG' and cur in ('Yellow','Red'): ex=True
        elif kind=='GB' and (tr in ('Blue->Green','Blue->Yellow') or cur=='Red'): ex=True
        elif kind in ('BY','RY') and (tr in ('Yellow->Green','Yellow->Red') or cur in ('Green','Red')): ex=True
        if ex:
            return idx[j+1], 'NQSAR'
    q=min(start_i+maxhold, len(idx)-1)
    return idx[q], 'TIME'


def build_signals(idx,nq,mc,bear,s50a):
    prev=nq.shift(1); tr=(prev.astype(str)+'->'+nq.astype(str)).where(prev.notna())
    arm20=s50a.rolling(20,min_periods=1).min()
    rows=[]
    for i,d in enumerate(idx[:-2]):
        t=str(tr.loc[d]) if pd.notna(tr.loc[d]) else ''
        mv=float(mc.loc[d]) if pd.notna(mc.loc[d]) else np.nan
        a=float(arm20.loc[d]) if pd.notna(arm20.loc[d]) else np.nan
        kind=None
        if t=='Red->Green' and a<=-2.0 and mv>=35: kind='RG'
        elif t=='Green->Blue' and a<=-1.5 and mv>=35 and not bool(bear.loc[d]): kind='GB'
        elif t=='Blue->Yellow' and mv>=35: kind='BY'
        elif t=='Red->Yellow' and a<=-2.0 and mv>=35: kind='RY'
        if kind:
            rows.append({'signal_date':d,'entry_date':idx[i+1],'kind':kind,'period':'IS' if d<=IS_END else 'OOS','mc57':mv,'arm20':a,'bear5':bool(bear.loc[d])})
    return pd.DataFrame(rows)


def simulate_trade(row, idx, nq, tq, partial_target=None, partial_frac=0.0):
    e=pd.Timestamp(row.entry_date); xp,why=trade_exit(row,e,idx,nq,tq)
    ep=float(tq.loc[e,'Open']); exitp=float(tq.loc[xp,'Open']); e_i=idx.get_loc(e); x_i=idx.get_loc(xp)
    window=tq.iloc[e_i:x_i+1]
    base_ret=exitp/ep-1-2*COST
    mfe=float(window.High.max()/ep-1); mae=float(window.Low.min()/ep-1)
    hit=False; hit_date=pd.NaT; ret=base_ret
    if partial_target is not None and partial_frac>0:
        tgt=ep*(1+partial_target)
        hits=window.index[window.High>=tgt]
        if len(hits):
            hit=True; hit_date=hits[0]
            # partial leg pays one sell cost; runner exits later with one sell cost; entry cost once on full notional.
            gross=partial_frac*partial_target+(1-partial_frac)*(exitp/ep-1)
            ret=gross-COST-partial_frac*COST-(1-partial_frac)*COST
    return {'kind':row.kind,'signal_date':row.signal_date,'entry_date':e,'exit_date':xp,'period':row.period,'exit_why':why,
            'partial_target':partial_target if partial_target is not None else 0.0,'partial_frac':partial_frac,'partial_hit':hit,'partial_hit_date':hit_date,
            'ret':ret,'base_ret':base_ret,'mfe':mfe,'mae':mae,'hold_days':x_i-e_i}


def combined_portfolio(signals, idx, nq, tq, target, frac, sizes):
    # One tactical NQSAR swing at a time; no overlap. Cash otherwise. This isolates the swing sleeve.
    ret=pd.Series(0.0,index=idx); active_until=None; trades=[]
    for _,row in signals.sort_values('signal_date').iterrows():
        e=pd.Timestamp(row.entry_date)
        if active_until is not None and e<=active_until: continue
        z=simulate_trade(row,idx,nq,tq,target,frac); trades.append(z); active_until=pd.Timestamp(z['exit_date'])
        ei=idx.get_loc(z['entry_date']); xi=idx.get_loc(z['exit_date']); size=float(sizes.get(z['kind'],0.0)); ep=float(tq.iloc[ei].Open)
        partial_done=False
        for k in range(ei+1,xi+1):
            # open-to-open daily return under current remaining exposure; partial can occur during prior session and reduces next open interval exposure.
            prevd=idx[k-1]; curd=idx[k]; exposure=size*(1-frac if partial_done else 1.0)
            ret.iloc[k]+=exposure*(float(tq.iloc[k].Open)/float(tq.iloc[k-1].Open)-1)
            if (not partial_done) and target is not None and float(tq.iloc[k-1].High)>=ep*(1+target):
                partial_done=True
        # approximate costs on entry, partial if hit, and final exit.
        ret.iloc[min(ei+1,len(ret)-1)]-=size*COST
        if z['partial_hit']:
            hi=idx.get_loc(pd.Timestamp(z['partial_hit_date'])); ret.iloc[min(hi+1,len(ret)-1)]-=size*frac*COST
        ret.iloc[min(xi,len(ret)-1)]-=size*(1-frac if z['partial_hit'] else 1.0)*COST
    eq=(1+ret).cumprod(); dd=eq/eq.cummax()-1; years=len(ret)/252
    return {'cagr':float(eq.iloc[-1]**(1/years)-1),'mdd':float(dd.min()),'end':float(eq.iloc[-1]),'trades':len(trades)},pd.DataFrame(trades)

print('=== STAGE10 NQSAR PARTIAL PROFIT ===',flush=True)
qqq=bt.dl_one('QQQ','2009-01-01'); tq=bt.dl_one('TQQQ','2010-01-01'); nqraw=bt.dl_one('NQ=F','2000-01-01'); mc,_=bt.compute_mc(); nq=nq_colors(nqraw)
c=qqq.Close.astype(float); hi=qqq.High.astype(float); lo=qqq.Low.astype(float); vol=qqq.Volume.astype(float); pc=c.shift(1)
trr=pd.concat([(hi-lo),(hi-pc).abs(),(lo-pc).abs()],axis=1).max(axis=1); atr=trr.ewm(alpha=1/14,adjust=False,min_periods=14).mean(); s50=c.rolling(50).mean(); s200=c.rolling(200).mean(); tp=(hi+lo+c)/3; v252=(tp*vol).rolling(252,min_periods=200).sum()/vol.rolling(252,min_periods=200).sum(); s50a=(c-s50)/atr
idx=qqq.index.intersection(tq.index); idx=idx[idx>=START]; tq=tq.reindex(idx); nq=nq.reindex(idx).ffill(); mc=mc.reindex(idx).ffill(); c=c.reindex(idx); s50=s50.reindex(idx); s200=s200.reindex(idx); v252=v252.reindex(idx); s50a=s50a.reindex(idx); bear=conf((c<s200)&(c<v252),5)
sigs=build_signals(idx,nq,mc,bear,s50a); sigs.to_csv('tqqq_stage10_signals.csv',index=False)

# Baseline and one-stage partial profit grid.
allrows=[]; tradefiles=[]
for target in [None,.05,.075,.10,.125,.15,.20]:
  for frac in ([0.0] if target is None else [.25,1/3,.50,.67]):
    td=pd.DataFrame([simulate_trade(r,idx,nq,tq,target,frac) for _,r in sigs.iterrows()])
    for kind in ['ALL','RG','GB','BY','RY']:
        g=td if kind=='ALL' else td[td.kind==kind]
        st=summarize(g.ret); bs=summarize(g.base_ret); isst=summarize(g.loc[g.period=='IS','ret']); osst=summarize(g.loc[g.period=='OOS','ret'])
        allrows.append({'kind':kind,'partial_target':0 if target is None else target,'partial_frac':frac,'n':st['n'],'mean':st['mean'],'median':st['median'],'win':st['win'],'worst':st['worst'],'best':st['best'],
                        'baseline_mean':bs['mean'],'delta_mean':st['mean']-bs['mean'] if st['n'] else np.nan,'is_mean':isst['mean'],'oos_mean':osst['mean'],'is_win':isst['win'],'oos_win':osst['win'],
                        'hit_rate':float(g.partial_hit.mean()) if len(g) and target is not None else 0.0,'median_mfe':float(g.mfe.median()) if len(g) else np.nan,'median_mae':float(g.mae.median()) if len(g) else np.nan})
res=pd.DataFrame(allrows); res.to_csv('tqqq_stage10_partial_grid.csv',index=False)

# Combined standalone swing sleeve using the signal-specific sizes already motivated by Stage9 risk.
sizes={'RG':.60,'GB':.50,'BY':.20,'RY':.25}
ports=[]
for target in [None,.05,.075,.10,.125,.15,.20]:
  for frac in ([0.0] if target is None else [.25,1/3,.50,.67]):
    ps,td=combined_portfolio(sigs,idx,nq,tq,target,frac,sizes); ii=td[td.period=='IS']; oo=td[td.period=='OOS']
    ports.append({'partial_target':0 if target is None else target,'partial_frac':frac,**ps,'trade_mean':float(td.ret.mean()) if len(td) else np.nan,'trade_worst':float(td.ret.min()) if len(td) else np.nan,
                  'is_trade_mean':float(ii.ret.mean()) if len(ii) else np.nan,'oos_trade_mean':float(oo.ret.mean()) if len(oo) else np.nan,'hit_rate':float(td.partial_hit.mean()) if len(td) and target is not None else 0.0})
pd.DataFrame(ports).to_csv('tqqq_stage10_portfolio_grid.csv',index=False)

# Robust ranking: require both IS and OOS expectation >0; prioritize MDD then CAGR for sleeve.
pg=pd.DataFrame(ports); valid=pg[(pg.is_trade_mean>0)&(pg.oos_trade_mean>0)].copy(); valid['calmar']=valid.cagr/(-valid.mdd); valid=valid.sort_values(['calmar','cagr'],ascending=False); valid.to_csv('tqqq_stage10_robust.csv',index=False)
print('\nSIGNALS',sigs.kind.value_counts().to_string())
print('\nBEST TRADE-LEVEL BY KIND')
for kind in ['RG','GB','BY','RY','ALL']:
    z=res[res.kind==kind].sort_values(['delta_mean','worst'],ascending=[False,False]).head(8)
    print('\n',kind); print(z[['partial_target','partial_frac','n','mean','delta_mean','win','worst','is_mean','oos_mean','hit_rate']].to_string(index=False))
print('\nPORTFOLIO TOP')
print(valid.head(15).to_string(index=False))
summary={'signals':sigs.kind.value_counts().to_dict(),'best_portfolio':valid.head(10).to_dict('records'),'baseline':pg[(pg.partial_target==0)&(pg.partial_frac==0)].to_dict('records')}
Path('tqqq_stage10_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,default=str))
