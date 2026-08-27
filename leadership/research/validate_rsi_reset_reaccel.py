from __future__ import annotations
import argparse,json,math
from pathlib import Path
from typing import Any
import numpy as np,pandas as pd
import validate_pioneer_leader as pl
import validate_rsi_divergence_strong as rd

H=(5,10,20,40,63); TH=(30,35,40,45,50); COST=5.0
DISC_END=pd.Timestamp('2021-12-31'); CONF_START=pd.Timestamp('2022-01-03')

def safe(x:Any)->Any:
    if isinstance(x,dict): return {str(k):safe(v) for k,v in x.items()}
    if isinstance(x,(list,tuple)): return [safe(v) for v in x]
    if isinstance(x,np.integer): return int(x)
    if isinstance(x,(np.floating,float)):
        z=float(x); return z if math.isfinite(z) else None
    if isinstance(x,pd.Timestamp): return x.isoformat()
    return x

def top3(df,col,name):
    z=df.dropna(subset=[col]).sort_values(['date','theme',col,'symbol'],ascending=[1,1,0,1]).groupby(['date','theme'],observed=True).head(3).copy(); z['rank_type']=name
    return z.groupby(['date','theme'],observed=True).filter(lambda g:len(g)==3)

def ret(op,cl,s,e,end):
    if e<0 or end<e or end>=len(cl): return np.nan
    a=op.at[cl.index[e],s]; b=cl.at[cl.index[end],s]
    return np.nan if pd.isna(a) or pd.isna(b) or a<=0 else float(b/a-1-2*COST/10000)

def exc(op,hi,lo,s,e,end):
    if e<0 or end<e or end>=len(hi): return np.nan,np.nan
    a=op.at[hi.index[e],s]
    if pd.isna(a) or a<=0:return np.nan,np.nan
    ix=hi.index[e:end+1]; h=hi.loc[ix,s].dropna(); l=lo.loc[ix,s].dropna()
    return (float(h.max()/a-1) if len(h) else np.nan,float(l.min()/a-1) if len(l) else np.nan)

def methods():
    m=[]
    for t in TH:m.append((f'STATE_LE{t}','state',t,0,'none'))
    m += [('STATE_40_50','band',(40,50),0,'none'),('STATE_35_45','band',(35,45),0,'none')]
    for w in (5,10,20):
        for t in TH:m.append((f'TOUCH_LE{t}_W{w}','touch',t,w,'none'))
        m += [(f'BAND_40_50_W{w}','bandwait',(40,50),w,'none'),(f'BAND_35_45_W{w}','bandwait',(35,45),w,'none')]
    for w in (10,20):
        for t in (30,40,50):m.append((f'RISE_LE{t}_W{w}','rise',t,w,'none'))
        m += [(f'RECROSS50_W{w}','recross',50,w,'none'),(f'BANDRISE_40_50_W{w}','bandrise',(40,50),w,'none')]
    m += [('DECLINE3_REV50_W10','decline',50,10,'none'),('HIGHBREAK45_W10','highbreak',45,10,'none')]
    for t in (30,40,45):
        m += [(f'TOUCH_LE{t}_W10_P21','touch',t,10,'p21'),(f'TOUCH_LE{t}_W10_TREND','touch',t,10,'trend')]
    return m

def struct(ok,i,s,cl,e21,s50):
    if ok=='none':return True
    c,e,z=cl.at[cl.index[i],s],e21.at[e21.index[i],s],s50.at[s50.index[i],s]
    if any(pd.isna(v) for v in (c,e,z)):return False
    return c>e if ok=='p21' else c>e>z

def locate(r,c,ep,kind,arg,w):
    last=min(len(r)-2,ep+w)
    if last<ep:return None
    if kind=='state': return ep if np.isfinite(r[ep]) and r[ep]<=arg else None
    if kind=='band': return ep if np.isfinite(r[ep]) and arg[0]<=r[ep]<=arg[1] else None
    def first(mask):
        q=np.flatnonzero(mask[ep:last+1]); return int(ep+q[0]) if q.size else None
    if kind=='touch': return first(np.isfinite(r)&(r<=arg))
    if kind=='bandwait': return first(np.isfinite(r)&(r>=arg[0])&(r<=arg[1]))
    if kind in ('rise','recross','highbreak','bandrise'):
        if kind=='bandrise': touch=first(np.isfinite(r)&(r>=arg[0])&(r<=arg[1]))
        else: touch=first(np.isfinite(r)&(r<=arg))
        if touch is None:return None
        for i in range(touch+1,last+1):
            if not (np.isfinite(r[i]) and np.isfinite(r[i-1])):continue
            if kind in ('rise','bandrise') and r[i]>r[i-1]:return i
            if kind=='recross' and r[i-1]<=arg<r[i]:return i
            if kind=='highbreak' and i>=5 and np.isfinite(c[i]):
                p=c[max(ep,i-5):i]; p=p[np.isfinite(p)]
                if p.size and c[i]>p.max():return i
        return None
    if kind=='decline':
        for i in range(max(ep,3),last+1):
            q=r[i-3:i+1]
            if np.isfinite(q).all() and q[0]>q[1]>q[2] and q[3]>q[2] and q[2]<=arg:return i
    return None

def trade_stats(g,h):
    x=pd.to_numeric(g[f'entry_{h}'],errors='coerce').dropna()
    if x.empty:return {'n':0}
    mf=pd.to_numeric(g.loc[x.index,f'mfe_{h}'],errors='coerce'); ma=pd.to_numeric(g.loc[x.index,f'mae_{h}'],errors='coerce')
    pos=float(x[x>0].sum()); neg=float(-x[x<0].sum()); pf=None if neg==0 else pos/neg
    cap=(x.clip(lower=0)/mf).where(mf>0).clip(0,1)
    q=x.quantile([.1,.9,.95])
    return {'n':len(x),'mean':x.mean(),'win':(x>0).mean(),'pf':pf,'mae':ma.mean(),'mfe':mf.mean(),'cap':cap.mean(),'p10':q.loc[.1],'p90':q.loc[.9],'p95':q.loc[.95]}

def blockid(d,cal):
    p=pd.Series(np.arange(len(cal)),index=cal); z=p.reindex(pd.to_datetime(d)).to_numpy(float); return np.floor(z/20).astype('int64')

def ci(g,val,col,seed,reps=1200):
    a=g[[col,val]].dropna().groupby(col,observed=True)[val].mean().to_numpy(float)
    if len(a)<2:return [None,None]
    rng=np.random.default_rng(seed); q=np.quantile(rng.choice(a,size=(reps,len(a)),replace=True).mean(1),[.025,.975]); return [q[0],q[1]]

def agg(g,val,cal,seed):
    u=g[['date','theme',val]].dropna().copy()
    if u.empty:return {'n':0}
    u['block20']=blockid(u.date,cal)
    return {'n':len(u),'event':u[val].mean(),'dateeq':u.groupby('date',observed=True)[val].mean().mean(),'themeeq':u.groupby('theme',observed=True)[val].mean().mean(),'block_ci':ci(u,val,'block20',seed),'date_ci':ci(u,val,'date',seed+1),'theme_ci':ci(u,val,'theme',seed+2)}

def build_base(cand,op,cl,hi,lo):
    pos={pd.Timestamp(d):i for i,d in enumerate(cl.index)}; z=[]
    for r in cand.itertuples(index=False):
        ep=pos.get(pd.Timestamp(r.date),-1); s=str(r.symbol)
        if ep<0 or ep+1>=len(cl):continue
        a={'date':pd.Timestamp(r.date),'theme':str(r.theme),'symbol':s,'rank_type':str(r.rank_type)}
        for h in H:
            end=ep+h; a[f'event_{h}']=ret(op,cl,s,ep+1,end) if end<len(cl) else np.nan; a[f'entry_{h}']=a[f'event_{h}']
            a[f'mfe_{h}'],a[f'mae_{h}']=exc(op,hi,lo,s,ep+1,end) if end<len(cl) else (np.nan,np.nan)
        z.append(a)
    return pd.DataFrame(z)

def run_method(cand,op,cl,hi,lo,rsi,e21,s50,m):
    name,kind,arg,w,st=m; pos={pd.Timestamp(d):i for i,d in enumerate(cl.index)}; rr={s:rsi[s].to_numpy(float) for s in rsi}; cc={s:cl[s].to_numpy(float) for s in cl}; z=[]
    for r in cand.itertuples(index=False):
        ep=pos.get(pd.Timestamp(r.date),-1); s=str(r.symbol)
        if ep<0 or ep+1>=len(cl) or s not in rr:continue
        sp=locate(rr[s],cc[s],ep,kind,arg,w)
        if sp is not None and not struct(st,sp,s,cl,e21,s50):sp=None
        en=sp+1 if sp is not None and sp+1<len(cl) else None
        a={'date':pd.Timestamp(r.date),'theme':str(r.theme),'symbol':s,'rank_type':str(r.rank_type),'method':name,'trade':en is not None,'delay':sp-ep if sp is not None else np.nan}
        for h in H:
            terminal=ep+h
            a[f'event_{h}']=np.nan if terminal>=len(cl) else (0.0 if en is None or en>terminal else ret(op,cl,s,en,terminal))
            end=en+h-1 if en is not None else None
            a[f'entry_{h}']=ret(op,cl,s,en,end) if end is not None and end<len(cl) else np.nan
            a[f'mfe_{h}'],a[f'mae_{h}']=exc(op,hi,lo,s,en,end) if end is not None and end<len(cl) else (np.nan,np.nan)
        z.append(a)
    return pd.DataFrame(z)

def eventize(x):
    cols=[f'event_{h}' for h in H]; return x.groupby(['date','theme','rank_type'],observed=True)[cols].mean().reset_index()

def summarize(base,meth,cal,name):
    out=[]
    for rt in sorted(base.rank_type.unique()):
        b=base[base.rank_type==rt]; x=meth[meth.rank_type==rt]; be=eventize(b); xe=eventize(x)
        for pn,lo_,hi_ in [('DISCOVERY',None,DISC_END),('CONFIRM',CONF_START,None)]:
            bf=b; xf=x; bef=be; xef=xe
            if lo_ is not None: bf=bf[bf.date>=lo_]; xf=xf[xf.date>=lo_]; bef=bef[bef.date>=lo_]; xef=xef[xef.date>=lo_]
            if hi_ is not None: bf=bf[bf.date<=hi_]; xf=xf[xf.date<=hi_]; bef=bef[bef.date<=hi_]; xef=xef[xef.date<=hi_]
            mm=xef.merge(bef,on=['date','theme','rank_type'],suffixes=('','_b')); matched=xf[xf.trade].merge(bf,on=['date','theme','symbol','rank_type'],suffixes=('','_b'))
            for j,h in enumerate(H):
                mm[f'diff_{h}']=mm[f'event_{h}']-mm[f'event_{h}_b']; ds=agg(mm,f'diff_{h}',cal,1000+j+len(name)); ms=agg(mm,f'event_{h}',cal,2000+j+len(name)); bs=agg(mm,f'event_{h}_b',cal,3000+j+len(name)); ts=trade_stats(xf[xf.trade],h); bts=trade_stats(bf,h)
                md=np.nan; sd=np.nan
                if len(matched): md=(matched[f'event_{h}']-matched[f'event_{h}_b']).mean(); sd=(matched[f'entry_{h}']-matched[f'entry_{h}_b']).mean()
                out.append({'rank_type':rt,'method':name,'period':pn,'h':h,'stock_trade_rate':xf.trade.mean() if len(xf) else np.nan,'event_any_trade_rate':xf.groupby(['date','theme'],observed=True).trade.max().mean() if len(xf) else np.nan,'delay':xf.loc[xf.trade,'delay'].mean() if xf.trade.any() else np.nan,'econ_method':ms.get('event'),'econ_base':bs.get('event'),'econ_diff':ds.get('event'),'dateeq_diff':ds.get('dateeq'),'themeeq_diff':ds.get('themeeq'),'block_lo':(ds.get('block_ci') or [None,None])[0],'block_hi':(ds.get('block_ci') or [None,None])[1],'entry_mean':ts.get('mean'),'entry_pf':ts.get('pf'),'entry_win':ts.get('win'),'entry_mae':ts.get('mae'),'entry_mfe':ts.get('mfe'),'mfe_capture':ts.get('cap'),'p10':ts.get('p10'),'p90':ts.get('p90'),'p95':ts.get('p95'),'base_entry_mean':bts.get('mean'),'base_mae':bts.get('mae'),'base_mfe':bts.get('mfe'),'base_p95':bts.get('p95'),'matched_event_diff':md,'matched_same_length_diff':sd})
    return out

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--input',required=True); ap.add_argument('--output',required=True); ap.add_argument('--start',default='2014-01-01'); ap.add_argument('--end',default='2026-08-27'); a=ap.parse_args(); out=Path(a.output); out.mkdir(parents=True,exist_ok=True)
    rows=pd.read_csv(a.input,compression='gzip',parse_dates=['date']); cand=pd.concat([top3(rows,'ret63','RS63_TOP3'),top3(rows,'ret189','RS189_TOP3')],ignore_index=True); syms=sorted(cand.symbol.unique())
    px,diag=pl.download_ohlcv(syms,a.start,a.end,100); op,of=rd.download_open(syms,a.start,a.end,100); common=sorted(set(px['close'].columns)&set(op.columns)); op=op.reindex(index=px['close'].index,columns=common); px={k:v[common] for k,v in px.items()}; cand=cand[cand.symbol.isin(common)].groupby(['date','theme','rank_type'],observed=True).filter(lambda g:len(g)==3)
    rsi=rd.rsi(px['close'],14); e21=px['close'].ewm(span=21,adjust=False,min_periods=15).mean(); s50=px['close'].rolling(50,min_periods=40).mean(); base=build_base(cand,op,px['close'],px['high'],px['low']); allr=[]; ms=methods()
    for i,m in enumerate(ms,1):
        print(f'METHOD {i}/{len(ms)} {m[0]}',flush=True); x=run_method(cand,op,px['close'],px['high'],px['low'],rsi,e21,s50,m); allr.extend(summarize(base,x,px['close'].index,m[0])); del x
    df=pd.DataFrame(allr); df.to_csv(out/'compact_results.csv',index=False)
    meta={'status':'RSI_RESET_REACCEL_STRONG_STOCKS','coverage':{'theme_events':int(rows[['date','theme']].drop_duplicates().shape[0]),'candidate_rows':len(cand),'symbols':cand.symbol.nunique()},'download':diag,'open_failed_batches':of,'methods':[m[0] for m in ms],'definitions':{'entry':'condition known at close, buy next open','baseline':'Theme Momentum Day0 + RS63/RS189 Top3 next open','economic_clock':'cash until delayed entry, then mark to original Theme-event horizon','entry_clock':'5/10/20/40/63 trading days from actual entry','cost':'5 bps/side','block_ci':'fixed 20-trading-day block resampling, 1200 reps','theme_momentum':'guaranteed at Day0 only; continuation not reconstructed'},'limitations':['current-universe/current-taxonomy retrospective bias','Yahoo adjusted OHLCV may differ from TradingView','fixed confirmation rules are secondary; main hypothesis is first RSI touch without bullish confirmation']}
    (out/'summary.json').write_text(json.dumps(safe({'meta':meta,'results':allr}),ensure_ascii=False,indent=2),encoding='utf-8'); print(df[(df.period=='CONFIRM')&df.method.str.contains('TOUCH_LE')&df.h.isin([20,40])].sort_values(['rank_type','h','econ_diff'],ascending=[1,1,0]).to_csv(index=False),flush=True)
if __name__=='__main__':main()
