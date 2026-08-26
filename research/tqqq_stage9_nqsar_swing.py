from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
from research import tqqq_backtest_once as bt

START=pd.Timestamp('2011-01-03'); IS_END=pd.Timestamp('2018-12-31'); COST=.0005; H=[5,10,15,20]

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
    au=u.ewm(alpha=1/n,adjust=False,min_periods=n).mean(); ad=dn.ewm(alpha=1/n,adjust=False,min_periods=n).mean(); rs=au/ad.replace(0,np.nan); y=100-100/(1+rs)
    return y.where(ad.ne(0),100.).to_numpy()

def nq_colors(nq):
    C=nq.Close.astype(float).to_numpy(); H=nq.High.astype(float).to_numpy(); L=nq.Low.astype(float).to_numpy(); S=psar(H,L); E=pd.Series(C,index=nq.index).ewm(span=21,adjust=False).mean().to_numpy(); R=rsi(C)
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

def sret(r):
    r=pd.Series(r).dropna()
    if len(r)==0:return {'n':0,'mean':np.nan,'median':np.nan,'win':np.nan,'worst':np.nan,'best':np.nan}
    return {'n':int(len(r)),'mean':float(r.mean()),'median':float(r.median()),'win':float((r>0).mean()),'worst':float(r.min()),'best':float(r.max())}

def pst(r):
    r=pd.Series(r).fillna(0); eq=(1+r).cumprod(); dd=eq/eq.cummax()-1; years=len(r)/252
    return {'cagr':float(eq.iloc[-1]**(1/years)-1),'mdd':float(dd.min()),'end':float(eq.iloc[-1])}

def year_ci(df,col,nboot=1200,seed=7):
    if len(df)<8:return np.nan,np.nan
    z=df[['year',col]].dropna(); ys=np.array(sorted(z.year.unique()))
    if len(ys)<4:return np.nan,np.nan
    rng=np.random.default_rng(seed); g={y:z.loc[z.year==y,col].to_numpy(float) for y in ys}; vals=[]
    for _ in range(nboot):
        yy=rng.choice(ys,size=len(ys),replace=True); a=np.concatenate([g[y] for y in yy if len(g[y])]); vals.append(float(a.mean()))
    return tuple(np.quantile(vals,[.025,.975]))

def events(idx,nq,tq,mc,vs,s50,bear,a50,a63,a200,a252):
    rows=[]; prev=nq.shift(1); pos={d:i for i,d in enumerate(idx)}; vb=vs.astype(str).isin(['BOTTOM','RE-EXTREME']); vb5=vb.rolling(5,min_periods=1).max().astype(bool); arm20=s50.rolling(20,min_periods=1).min()<=-2
    for d in idx:
        p=prev.loc[d]; c=nq.loc[d]
        if pd.isna(p) or p==c:continue
        i=pos[d]; e=i+1
        if e>=len(idx):continue
        ep=float(tq.Open.iloc[e]); mv=float(mc.loc[d]) if pd.notna(mc.loc[d]) else np.nan; x=float(s50.loc[d]) if pd.notna(s50.loc[d]) else np.nan
        r={'date':d,'year':d.year,'period':'IS' if d<=IS_END else 'OOS','transition':f'{p}->{c}','mc57':mv,'bear5':bool(bear.loc[d]),'sma50_atr':x,'armed20':bool(arm20.loc[d]),'vix_bottom5':bool(vb5.loc[d]),'above50':bool(a50.loc[d]),'above63':bool(a63.loc[d]),'above200':bool(a200.loc[d]),'above252':bool(a252.loc[d])}
        r['mc_band']='<25' if mv<25 else '25-35' if mv<35 else '35-50' if mv<50 else '50-65' if mv<65 else '65+'
        r['price_band']='<=-2' if x<=-2 else '-2:-1' if x<=-1 else '-1:0' if x<=0 else '0:2' if x<=2 else '>2'
        for h in H:
            q=e+h
            if q>=len(idx):r[f'r{h}']=r[f'mae{h}']=r[f'mfe{h}']=np.nan;continue
            w=tq.iloc[e:q+1]; r[f'r{h}']=float(tq.Open.iloc[q]/ep-1); r[f'mae{h}']=float(w.Low.min()/ep-1); r[f'mfe{h}']=float(w.High.max()/ep-1)
        rows.append(r)
    return pd.DataFrame(rows)

def aggregate(ev):
    out=[]; cuts=[('FULL',pd.Series(True,index=ev.index)),('IS',ev.period.eq('IS')),('OOS',ev.period.eq('OOS')),('BEAR5',ev.bear5),('NON_BEAR5',~ev.bear5),('BEAR_ARMED20',ev.bear5&ev.armed20),('BEAR_VIXBOTTOM5',ev.bear5&ev.vix_bottom5),('BEAR_MC35+',ev.bear5&(ev.mc57>=35))]
    for tr in sorted(ev.transition.unique()):
        for name,m in cuts:
            g=ev[m.reindex(ev.index).fillna(False)&ev.transition.eq(tr)]
            for h in H:
                st=sret(g[f'r{h}']); lo,hi=year_ci(g,f'r{h}')
                out.append({'transition':tr,'cut':name,'horizon':h,**st,'median_mae':float(g[f'mae{h}'].median()) if len(g) else np.nan,'median_mfe':float(g[f'mfe{h}'].median()) if len(g) else np.nan,'ci_lo':lo,'ci_hi':hi})
    bear=ev[ev.bear5]
    for dim in ['mc_band','price_band','vix_bottom5','armed20']:
        for (tr,val),g in bear.groupby(['transition',dim],dropna=False):
            for h in H:
                st=sret(g[f'r{h}']); out.append({'transition':tr,'cut':f'BEAR_{dim}={val}','horizon':h,**st,'median_mae':float(g[f'mae{h}'].median()),'median_mfe':float(g[f'mfe{h}'].median()),'ci_lo':np.nan,'ci_hi':np.nan})
    return pd.DataFrame(out)

def grid(idx,nq,tq,mc,vs,s50,bear):
    trans=(nq.shift(1).astype(str)+'->'+nq.astype(str)).where(nq.shift(1).notna()); arm={a:s50.rolling(20,min_periods=1).min().le(a) for a in [-1,-1.5,-2,-2.5]}; vb5=vs.astype(str).isin(['BOTTOM','RE-EXTREME']).rolling(5,min_periods=1).max().astype(bool)
    sets={'RY':{'Red->Yellow'},'YG':{'Yellow->Green'},'GB':{'Green->Blue'},'RECOVERY':{'Red->Yellow','Yellow->Green','Green->Blue','Red->Green','Red->Blue','Yellow->Blue'}}
    base=pd.Series(np.where(bear,0,.545),index=idx,dtype=float); base=base.mask((~bear)&nq.eq('Blue')&(mc>=65)&(s50<=2.5),1.0); ro=tq.Open.pct_change().reindex(idx).fillna(0); br=base.shift(2)*ro-base.diff().abs().shift(2).fillna(0)*COST; bfull=pst(br); bis=pst(br.loc[:IS_END]); boos=pst(br.loc[IS_END+pd.Timedelta(days=1):]); out=[]
    for en,es in sets.items():
      for a in arm:
       for mm in [0,25,35]:
        for vr in [False,True]:
         for xr in ['RED','YELLOW','BG','ATR3_RED','ATR45_RED']:
          for mh in [10,15,20]:
            target=base.copy(); trades=[]; active=False; si=ei=None; ep=ed=None
            for i,d in enumerate(idx[:-1]):
                tr=str(trans.loc[d]) if pd.notna(trans.loc[d]) else ''
                if not active:
                    ok=bool(bear.loc[d]) and tr in es and bool(arm[a].loc[d]) and (mm==0 or (pd.notna(mc.loc[d]) and float(mc.loc[d])>=mm)) and ((not vr) or bool(vb5.loc[d]))
                    if ok:active=True;si=i;ei=i+1;ep=float(tq.Open.iloc[ei]);ed=idx[ei]
                else:
                    cur=str(nq.loc[d]); hold=i-si; ex=False; why=''
                    if not bool(bear.loc[d]):ex=True;why='BEAR_END'
                    elif xr=='RED' and cur=='Red':ex=True;why='RED'
                    elif xr=='YELLOW' and cur in ('Yellow','Red'):ex=True;why=cur
                    elif xr=='BG' and (tr=='Blue->Green' or cur=='Red'):ex=True;why='BG/RED'
                    elif xr=='ATR3_RED' and ((pd.notna(s50.loc[d]) and s50.loc[d]>=3) or cur=='Red'):ex=True;why='ATR3/RED'
                    elif xr=='ATR45_RED' and ((pd.notna(s50.loc[d]) and s50.loc[d]>=4.5) or cur=='Red'):ex=True;why='ATR45/RED'
                    if hold>=mh:ex=True;why=why or 'TIME'
                    if ex:
                        q=i+1; xp=float(tq.Open.iloc[q]); w=tq.iloc[ei:q+1]; trades.append({'ret':xp/ep-1-2*COST,'mae':float(w.Low.min()/ep-1),'mfe':float(w.High.max()/ep-1),'period':'IS' if ed<=IS_END else 'OOS'}); target.iloc[si:i+1]=.60;active=False
            r=target.shift(2)*ro-target.diff().abs().shift(2).fillna(0)*COST; f=pst(r); ii=pst(r.loc[:IS_END]); oo=pst(r.loc[IS_END+pd.Timedelta(days=1):]); td=pd.DataFrame(trades); st=sret(td.ret if len(td) else []); ist=sret(td.loc[td.period=='IS','ret'] if len(td) else []); ost=sret(td.loc[td.period=='OOS','ret'] if len(td) else [])
            out.append({'entry':en,'arm':a,'mcmin':mm,'vix_bottom5_req':vr,'exit_rule':xr,'maxhold':mh,'trades':st['n'],'trade_mean':st['mean'],'trade_median':st['median'],'trade_win':st['win'],'trade_worst':st['worst'],'trade_mae_med':float(td.mae.median()) if len(td) else np.nan,'trade_mfe_med':float(td.mfe.median()) if len(td) else np.nan,'is_trades':ist['n'],'is_trade_mean':ist['mean'],'is_trade_win':ist['win'],'oos_trades':ost['n'],'oos_trade_mean':ost['mean'],'oos_trade_win':ost['win'],'cagr':f['cagr'],'mdd':f['mdd'],'is_cagr':ii['cagr'],'is_mdd':ii['mdd'],'oos_cagr':oo['cagr'],'oos_mdd':oo['mdd'],'dcagr_vs_base':f['cagr']-bfull['cagr'],'dmdd_vs_base':f['mdd']-bfull['mdd'],'base_cagr':bfull['cagr'],'base_mdd':bfull['mdd']})
    return pd.DataFrame(out),{'full':bfull,'is':bis,'oos':boos}

print('=== STAGE9 NQSAR SWING STUDY ===',flush=True)
qqq=bt.dl_one('QQQ','2009-01-01'); tq=bt.dl_one('TQQQ','2010-01-01'); vix=bt.dl_one('^VIX','1990-01-01'); nq=bt.dl_one('NQ=F','2000-01-01'); mc,_=bt.compute_mc(); vs,_=bt.vix_state_series(vix); nq=nq_colors(nq)
c=qqq.Close.astype(float); hi=qqq.High.astype(float); lo=qqq.Low.astype(float); vol=qqq.Volume.astype(float); pc=c.shift(1); tr=pd.concat([(hi-lo),(hi-pc).abs(),(lo-pc).abs()],axis=1).max(axis=1); atr=tr.ewm(alpha=1/14,adjust=False,min_periods=14).mean(); s50=c.rolling(50).mean(); s200=c.rolling(200).mean(); tp=(hi+lo+c)/3; v63=(tp*vol).rolling(63).sum()/vol.rolling(63).sum(); v252=(tp*vol).rolling(252,min_periods=200).sum()/vol.rolling(252,min_periods=200).sum(); s50a=(c-s50)/atr
idx=qqq.index.intersection(tq.index); idx=idx[idx>=START]; tq=tq.reindex(idx); nq=nq.reindex(idx).ffill(); mc=mc.reindex(idx).ffill(); vs=vs.reindex(idx).ffill(); c=c.reindex(idx); s50=s50.reindex(idx); s200=s200.reindex(idx); v63=v63.reindex(idx); v252=v252.reindex(idx); s50a=s50a.reindex(idx); a50=c>s50; a63=c>v63; a200=c>s200; a252=c>v252; bear=conf((~a200)&(~a252),5)
ev=events(idx,nq,tq,mc,vs,s50a,bear,a50,a63,a200,a252); ev.to_csv('tqqq_stage9_nqsar_events.csv',index=False); st=aggregate(ev); st.to_csv('tqqq_stage9_nqsar_stats.csv',index=False); gd,base=grid(idx,nq,tq,mc,vs,s50a,bear); gd.to_csv('tqqq_stage9_nqsar_trade_grid.csv',index=False)
valid=gd[(gd.trades>=10)&(gd.is_trades>=3)&(gd.oos_trades>=3)].copy(); valid['min_split_cagr']=valid[['is_cagr','oos_cagr']].min(axis=1); valid['min_split_trade_mean']=valid[['is_trade_mean','oos_trade_mean']].min(axis=1); valid['calmar']=valid.cagr/(-valid.mdd); robust=valid.sort_values(['min_split_cagr','mdd','cagr'],ascending=[False,False,False]).head(30); robust.to_csv('tqqq_stage9_nqsar_robust.csv',index=False)
print('\nBASE',json.dumps(base,indent=2)); print('\nTRANSITIONS'); print(ev.transition.value_counts().to_string()); print('\nFULL 10D'); print(st[(st.cut=='FULL')&(st.horizon==10)].sort_values('mean',ascending=False)[['transition','n','mean','median','win','median_mae','median_mfe','ci_lo','ci_hi']].to_string(index=False,float_format=lambda x:f'{x:.4f}')); print('\nBEAR+ARMED20 10D'); print(st[(st.cut=='BEAR_ARMED20')&(st.horizon==10)].sort_values('mean',ascending=False)[['transition','n','mean','median','win','median_mae','median_mfe']].to_string(index=False,float_format=lambda x:f'{x:.4f}')); print('\nROBUST GRID'); cols=['entry','arm','mcmin','vix_bottom5_req','exit_rule','maxhold','trades','trade_mean','trade_win','is_trade_mean','oos_trade_mean','cagr','mdd','is_cagr','oos_cagr','dcagr_vs_base','dmdd_vs_base']; print(robust[cols].head(20).to_string(index=False,float_format=lambda x:f'{x:.4f}'))
summary={'sessions':len(idx),'start':str(idx[0].date()),'end':str(idx[-1].date()),'events':len(ev),'base':base,'best_cagr':valid.sort_values('cagr',ascending=False).head(1).to_dict('records'),'best_mdd_under_base_cagr':valid[valid.cagr>=base['full']['cagr']].sort_values('mdd',ascending=False).head(1).to_dict('records'),'best_robust':robust.head(10).to_dict('records')}; Path('tqqq_stage9_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,default=str))
