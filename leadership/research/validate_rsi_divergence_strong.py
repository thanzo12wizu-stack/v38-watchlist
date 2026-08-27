from __future__ import annotations
import argparse, json, math
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd
import yfinance as yf
import validate_pioneer_leader as pl
import validate_early_rotation as er
import validate_rrg_tail_system as rt

RSI_LEN=14
H=(5,10,20,40)
COST=5.0
DISC_END=pd.Timestamp('2021-12-31')
CONF_START=pd.Timestamp('2022-01-03')
PARAMS={'TVLIKE_5':(5,5,5,60),'SENS_3':(3,3,5,60),'SENS_7':(7,7,5,60)}


def safe(v:Any)->Any:
    if isinstance(v,dict): return {str(k):safe(x) for k,x in v.items()}
    if isinstance(v,(list,tuple)): return [safe(x) for x in v]
    if isinstance(v,np.integer): return int(v)
    if isinstance(v,(np.floating,float)):
        x=float(v); return x if math.isfinite(x) else None
    if isinstance(v,pd.Timestamp): return v.isoformat()
    return v


def download_open(symbols,start,end,batch=100):
    frames=[]; failed=0
    for pos in range(0,len(symbols),batch):
        b=symbols[pos:pos+batch]; ys=[er.yahoo_symbol(s) for s in b]; rev={er.yahoo_symbol(s):s for s in b}
        try:
            raw=yf.download(ys,start=start,end=end,auto_adjust=True,actions=False,progress=False,group_by='ticker',threads=True,timeout=30)
        except Exception:
            failed+=1; continue
        cols={}
        if raw is not None and not raw.empty:
            if isinstance(raw.columns,pd.MultiIndex):
                lv=set(str(x) for x in raw.columns.get_level_values(0))
                for y in ys:
                    if y in lv and 'Open' in raw[y].columns: cols[rev[y]]=pd.to_numeric(raw[y]['Open'],errors='coerce')
            elif len(b)==1 and 'Open' in raw.columns: cols[b[0]]=pd.to_numeric(raw['Open'],errors='coerce')
        if cols: frames.append(pd.DataFrame(cols))
        print(f'OPEN {min(pos+batch,len(symbols))}/{len(symbols)}',flush=True)
    if not frames: raise RuntimeError('no open data')
    z=pd.concat(frames,axis=1); z=z.loc[:,~z.columns.duplicated()].sort_index(); z.index=pd.to_datetime(z.index).tz_localize(None)
    return z.replace([np.inf,-np.inf],np.nan),failed


def rsi(close,n=14):
    d=close.diff(); g=d.clip(lower=0); l=(-d).clip(lower=0)
    ag=g.ewm(alpha=1/n,adjust=False,min_periods=n).mean(); al=l.ewm(alpha=1/n,adjust=False,min_periods=n).mean()
    rs=ag/al.replace(0,np.nan); x=100-100/(1+rs)
    x=x.where(al!=0,100).where(ag!=0,0); x=x.where(~((ag==0)&(al==0)),50)
    return x


def signals(rsi_df,low,left,right,rlo,rhi):
    out={}; w=left+right+1
    for sym in rsi_df.columns:
        s=rsi_df[sym]; mn=s.rolling(w,center=True,min_periods=w).min(); a=s.to_numpy(float); m=mn.to_numpy(float); lo=low[sym].to_numpy(float)
        ps=np.where(np.isfinite(a)&np.isfinite(m)&(a==m))[0]; piv=[]
        for p in ps:
            if p<left or p+right>=len(a): continue
            ww=a[p-left:p+right+1]
            if np.isfinite(ww).sum()==w and np.sum(np.isclose(ww,a[p],rtol=0,atol=1e-12))==1: piv.append(int(p))
        reg=[]; hid=[]; prev=None
        for p in piv:
            if prev is not None and rlo<=p-prev<=rhi and np.isfinite(lo[p]) and np.isfinite(lo[prev]):
                c=p+right
                if c<len(a):
                    if a[p]>a[prev] and lo[p]<lo[prev]: reg.append(c)
                    if a[p]<a[prev] and lo[p]>lo[prev]: hid.append(c)
            prev=p
        out[sym]={'reg':np.asarray(reg,dtype=np.int32),'hid':np.asarray(hid,dtype=np.int32)}
    return out


def pick(a,ep,kind,mode,window):
    if kind=='reg': x=a['reg']
    elif kind=='hid': x=a['hid']
    else: x=np.asarray(sorted(set(a['reg'].tolist())|set(a['hid'].tolist())),dtype=np.int32)
    if x.size==0:return None
    if mode=='wait':
        k=int(np.searchsorted(x,ep,'left')); return int(x[k]) if k<len(x) and int(x[k])<=ep+window else None
    k=int(np.searchsorted(x,ep,'right'))-1; return int(x[k]) if k>=0 and int(x[k])>=ep-window else None


def top3(rows,col,name):
    z=rows.dropna(subset=[col]).sort_values(['date','theme',col,'symbol'],ascending=[True,True,False,True]).groupby(['date','theme'],observed=True).head(3).copy()
    z['rank_type']=name
    return z.groupby(['date','theme'],observed=True).filter(lambda g:len(g)==3)


def tret(op,cl,sym,entry,end,cost=COST):
    if entry<0 or end<entry or end>=len(cl): return np.nan
    d0,d1=cl.index[entry],cl.index[end]; e=op.at[d0,sym] if sym in op.columns else np.nan; z=cl.at[d1,sym] if sym in cl.columns else np.nan
    if pd.isna(e) or pd.isna(z) or e<=0:return np.nan
    return float(z/e-1-2*cost/10000)


def exc(op,hi,lo,sym,entry,end):
    if entry<0 or end<entry or end>=len(hi):return np.nan,np.nan
    d0=hi.index[entry]; e=op.at[d0,sym]
    if pd.isna(e) or e<=0:return np.nan,np.nan
    ds=hi.index[entry:end+1]; hs=hi.loc[ds,sym].dropna(); ls=lo.loc[ds,sym].dropna()
    return (float(hs.max()/e-1) if len(hs) else np.nan,float(ls.min()/e-1) if len(ls) else np.nan)


def evaluate(cand,op,cl,hi,lo,sig,param,methods):
    pos={pd.Timestamp(d):i for i,d in enumerate(cl.index)}; rec=[]
    for r in cand.itertuples(index=False):
        d=pd.Timestamp(r.date); ep=pos.get(d,-1); sym=str(r.symbol)
        if ep<0 or ep+1>=len(cl) or sym not in sig: continue
        base={'date':d,'theme':str(r.theme),'symbol':sym,'rank_type':str(r.rank_type),'param':param}
        b=dict(base,method='BASE',trade=True,delay=0)
        for h in H:
            b[f'event_{h}']=tret(op,cl,sym,ep+1,ep+h)
            b[f'entry_{h}']=b[f'event_{h}']; b[f'mfe_{h}'],b[f'mae_{h}']=exc(op,hi,lo,sym,ep+1,ep+h)
        rec.append(b)
        for name,kind,mode,w in methods:
            sp=pick(sig[sym],ep,kind,mode,w); epos=(ep+1 if mode=='recent' and sp is not None else (sp+1 if sp is not None else None))
            x=dict(base,method=name,trade=sp is not None,delay=(sp-ep if sp is not None and mode=='wait' else 0 if sp is not None else np.nan))
            for h in H:
                terminal=ep+h
                x[f'event_{h}']=0.0 if epos is None or epos>terminal else (tret(op,cl,sym,epos,terminal) if terminal<len(cl) else np.nan)
                end=(epos+h-1) if epos is not None else None
                x[f'entry_{h}']=tret(op,cl,sym,epos,end) if end is not None and end<len(cl) else np.nan
                x[f'mfe_{h}'],x[f'mae_{h}']=exc(op,hi,lo,sym,epos,end) if end is not None and end<len(cl) else (np.nan,np.nan)
            rec.append(x)
    return pd.DataFrame(rec)


def eventize(s):
    keys=['date','theme','rank_type','param','method']; mets=[f'event_{h}' for h in H]
    a=s.groupby(keys,observed=True)[mets].mean().reset_index(); b=s.groupby(keys,observed=True).agg(trade_rate=('trade','mean'),delay=('delay','mean')).reset_index()
    return a.merge(b,on=keys,how='left')


def summarize(ev,sleeves,calendar):
    out={}; periods={'ALL':ev,'DISCOVERY':ev[ev.date<=DISC_END],'CONFIRM':ev[ev.date>=CONF_START]}
    for rtpe in sorted(ev.rank_type.unique()):
        out[rtpe]={}
        for param in sorted(ev.param.unique()):
            out[rtpe][param]={}
            for pn,p0 in periods.items():
                p=p0[(p0.rank_type==rtpe)&(p0.param==param)]
                if p.empty:continue
                base=p[p.method=='BASE'][['date','theme']+[f'event_{h}' for h in H]]
                mm={}
                for mi,meth in enumerate(sorted(set(p.method)-{'BASE'})):
                    q=p[p.method==meth].merge(base,on=['date','theme'],suffixes=('','_b')); z={'trade_rate':float(p.loc[p.method==meth,'trade_rate'].mean()),'delay':float(p.loc[p.method==meth,'delay'].mean()),'h':{}}
                    for h in H:
                        col=f'diff_{h}'; q[col]=q[f'event_{h}']-q[f'event_{h}_b']; z['h'][str(h)]=rt.summary(q[['date','theme',col]],col,calendar,1000+mi*100+h)
                    mm[meth]=z
                out[rtpe][param][pn]=mm
    cond={}
    for (rtpe,param,meth),g in sleeves[(sleeves.method!='BASE')&sleeves.trade].groupby(['rank_type','param','method'],observed=True):
        cond.setdefault(rtpe,{}).setdefault(param,{})[meth]={str(h):{'n':int(g[f'entry_{h}'].notna().sum()),'ret':float(g[f'entry_{h}'].mean()),'win':float((g[f'entry_{h}']>0).mean()),'mfe':float(g[f'mfe_{h}'].mean()),'mae':float(g[f'mae_{h}'].mean())} for h in H}
    return {'economic_vs_day0':out,'conditional':cond}


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--input',required=True); ap.add_argument('--output',required=True); ap.add_argument('--start',default='2014-01-01'); ap.add_argument('--end',default='2026-08-27'); args=ap.parse_args()
    out=Path(args.output); out.mkdir(parents=True,exist_ok=True); rows=pd.read_csv(args.input,compression='gzip',parse_dates=['date'])
    cand=pd.concat([top3(rows,'ret63','RS63_TOP3'),top3(rows,'ret189','RS189_TOP3')],ignore_index=True); syms=sorted(cand.symbol.unique())
    px,diag=pl.download_ohlcv(syms,args.start,args.end,100); op,open_failed=download_open(syms,args.start,args.end,100)
    common=sorted(set(px['close'].columns)&set(op.columns)); op=op.reindex(index=px['close'].index,columns=common); px={k:v[common] for k,v in px.items()}; cand=cand[cand.symbol.isin(common)].groupby(['date','theme','rank_type'],observed=True).filter(lambda g:len(g)==3)
    rr=rsi(px['close']); allr=[]; counts={}
    for pname,(l,r,lo,up) in PARAMS.items():
        sg=signals(rr,px['low'],l,r,lo,up); counts[pname]={'regular':sum(len(v['reg']) for v in sg.values()),'hidden':sum(len(v['hid']) for v in sg.values())}
        methods=[]
        if pname=='TVLIKE_5':
            for kind,lab in [('reg','REG'),('hid','HID'),('any','ANY')]:
                for w in (5,10,20): methods.append((f'{lab}_WAIT{w}',kind,'wait',w))
                methods.append((f'{lab}_RECENT10',kind,'recent',10))
        else: methods=[('REG_WAIT10','reg','wait',10),('HID_WAIT10','hid','wait',10),('ANY_WAIT10','any','wait',10)]
        allr.append(evaluate(cand,op,px['close'],px['high'],px['low'],sg,pname,methods))
    sleeves=pd.concat(allr,ignore_index=True); ev=eventize(sleeves); res=summarize(ev,sleeves,px['close'].index)
    res.update({'status':'RSI_DIVERGENCE_STRONG_STOCKS','download':diag,'open_failed_batches':open_failed,'signal_counts':counts,'coverage':{'events':int(rows[['date','theme']].drop_duplicates().shape[0]),'candidate_events':int(cand[['date','theme','rank_type']].drop_duplicates().shape[0]),'symbols':int(cand.symbol.nunique())},'definition':{'regular':'price LL + RSI HL','hidden':'price HL + RSI LL','signal':'confirmed RSI pivot; signal known right bars after pivot; entry next open','primary':'RSI14, pivot 5/5, separation 5-60','baseline':'Theme Momentum + RS63/RS189 top3 next-open entry'},'limitations':['current universe/current taxonomy retrospective bias','TradingView support page documents regular divergence; hidden is a separate continuation variant','Yahoo adjusted OHLCV can differ slightly from TradingView feed']})
    sleeves.to_csv(out/'sleeves.csv.gz',index=False,compression='gzip'); ev.to_csv(out/'events.csv.gz',index=False,compression='gzip'); (out/'summary.json').write_text(json.dumps(safe(res),ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(safe({'status':res['status'],'download':diag,'counts':counts,'coverage':res['coverage'],'rs189_confirm':res['economic_vs_day0'].get('RS189_TOP3',{}).get('TVLIKE_5',{}).get('CONFIRM',{})}),ensure_ascii=False,indent=2),flush=True)
if __name__=='__main__': main()
