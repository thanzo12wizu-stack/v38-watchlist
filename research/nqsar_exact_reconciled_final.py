from __future__ import annotations

import argparse, json, math
from pathlib import Path
import numpy as np
import pandas as pd

from research import audit_stock_nqsar_theme30_pit as audit
from research import preimpl_core11_early1_pit as pit
from research import preimpl_core11_early1_long as lng
from research import preimpl_early1_marginal as marginal
from research import nqsar_centric_broad_scan as broad
import build_v38_sleeve_live as sleeve
import build_v38_early1_live as earlylive

START=pd.Timestamp('2016-01-04')
END=pd.Timestamp('2026-09-04')
CONF=pd.Timestamp('2022-01-03')

SPECS=[
    ('CURRENT_EARLY1','CURRENT',True),
    ('WEEK_RS63_EARLY1','WEEK_RS63',True),
    ('WEEK_RS189_NO_THRESH_EARLY1','WEEK_RS189',True),
    ('WEEK_RS63_CORE12','WEEK_RS63',False),
    ('TREND9_IGN3_CORE12','MIX9_IGN3',False),
]


def safe(x):
    if isinstance(x,dict): return {str(k):safe(v) for k,v in x.items()}
    if isinstance(x,(list,tuple)): return [safe(v) for v in x]
    if isinstance(x,np.integer): return int(x)
    if isinstance(x,(np.floating,float)):
        z=float(x); return z if math.isfinite(z) else None
    if isinstance(x,pd.Timestamp): return str(x.date())
    return x


def ranked_core_rows(d,m,kind):
    pool=m['pool'].loc[d].fillna(False); struct=m['struct'].loc[d].fillna(False); wb=m['wb'].loc[d].fillna(False)
    ddv=pd.to_numeric(m['ddv'].loc[d],errors='coerce'); q63=pd.to_numeric(m['q'][63].loc[d],errors='coerce'); q189=pd.to_numeric(m['q'][189].loc[d],errors='coerce')
    mask=pool&struct&wb
    if kind in {'WEEK_RS63','WEEK_RS189'}:
        score=q63 if kind=='WEEK_RS63' else q189
        z=score.where(mask).dropna().sort_values(ascending=False)
        return [{'ticker':str(s),'final_rank':i,'daily_dollar_volume_m':float(ddv.get(s,np.nan))/1e6 if pd.notna(ddv.get(s,np.nan)) else None,
                 'stock_rs63_pct':float(q63.get(s,np.nan)) if pd.notna(q63.get(s,np.nan)) else None,
                 'stock_rs189_pct':float(q189.get(s,np.nan)) if pd.notna(q189.get(s,np.nan)) else None}
                for i,(s,_) in enumerate(z.items(),1)]
    if kind=='MIX9_IGN3':
        trend=q63.where(mask).dropna().sort_values(ascending=False).index.tolist()
        ign=pd.to_numeric(m['early_score'].loc[d],errors='coerce').where(pool&wb&m['radar_active'].loc[d].fillna(False)).dropna().sort_values(ascending=False).index.tolist()
        lists={'T':trend,'I':ign}; ptr={'T':0,'I':0}; chosen=[]
        for src in ['T','T','T','I']*3:
            arr=lists[src]
            while ptr[src]<len(arr) and arr[ptr[src]] in chosen: ptr[src]+=1
            if ptr[src]>=len(arr): continue
            chosen.append(arr[ptr[src]]); ptr[src]+=1
        rows=[]
        for i,s in enumerate(chosen[:12],1):
            rows.append({'ticker':str(s),'final_rank':i,'daily_dollar_volume_m':float(ddv.get(s,np.nan))/1e6 if pd.notna(ddv.get(s,np.nan)) else None,
                         'source':'IGNITION' if i in {4,8,12} else 'TREND',
                         'stock_rs63_pct':float(q63.get(s,np.nan)) if pd.notna(q63.get(s,np.nan)) else None})
        return rows
    raise KeyError(kind)


def build_events(m,idx):
    c=m['close']; prior_low=c.shift(1).rolling(126,min_periods=60).min()
    future_max=c.shift(-1).iloc[::-1].rolling(126,min_periods=100).max().iloc[::-1]
    future_ret=future_max/c-1.0
    valid=pd.Series(np.arange(len(c))<=len(c)-127,index=c.index)
    big=(future_ret>=1.0)&m['pool']&valid.to_numpy()[:,None]
    starts=(big&~big.shift(1).fillna(False)).loc[idx]
    coords=np.argwhere(starts.to_numpy(bool)); events=[]
    for n,(i,j) in enumerate(coords):
        d=pd.Timestamp(starts.index[i]); s=str(starts.columns[j]); gi=c.index.get_loc(d)
        if not isinstance(gi,(int,np.integer)) or gi+126>=len(c): continue
        fut=c[s].iloc[gi+1:gi+127].dropna(); p0=c.at[d,s]
        if pd.isna(p0) or p0<=0 or len(fut)<100: continue
        events.append({'symbol':s,'start_date':d,'peak_date':pd.Timestamp(fut.idxmax()),'future_peak_return':float(fut.max()/p0-1)})
        if n and n%5000==0: print('EVENT_BUILD',n,len(coords),flush=True)
    return pd.DataFrame(events),prior_low


def simulate(idx,mx,nq,e,m,kind,use_early):
    first=pd.Timestamp(idx[0]); state={'status':'READY','asof':str(first.date()),'cash':1.0,'positions':[],
        'pending':{'full_exits':[],'partial25':[],'entries':[]}}
    eq=[]; snaps=[]; cols=list(m['close'].columns); cmap={s:i for i,s in enumerate(cols)}
    held=np.zeros((len(idx),len(cols)),dtype=np.bool_); ent_px=np.full((len(idx),len(cols)),np.nan,dtype=np.float32); ent_i=np.full((len(idx),len(cols)),-1,dtype=np.int16)
    ipos={pd.Timestamp(d):i for i,d in enumerate(idx)}
    for ii,d0 in enumerate(idx):
        d=pd.Timestamp(d0); c=pit.companion(d,mx,{},nq,e,True)
        if kind!='CURRENT':
            c=dict(c); c['candidates']=ranked_core_rows(d,m,kind)
        if not use_early:
            c=dict(c); c['early1']={'status':'READY','entry_allowed_now':False,'candidates':[]}
        state=sleeve.advance_normal(state,c,str(d.date()),mx['open'],mx['close'])
        if not use_early: state=marginal.strip_early_and_optionally_fill_core(state,c,True)
        eq.append((d,float(state['nav']))); snaps.append((d,json.dumps(state.get('pending',{}),sort_keys=True,default=str)))
        for p in state.get('positions',[]):
            s=str(p.get('symbol') or ''); j=cmap.get(s)
            if j is None: continue
            held[ii,j]=True
            try: ent_px[ii,j]=float(p.get('entry_price'))
            except Exception: pass
            ed=pd.Timestamp(p.get('entry_date')) if p.get('entry_date') is not None else d
            ent_i[ii,j]=int(ipos.get(ed,ii))
    return {'equity':pd.Series(dict(eq),dtype=float),'pending_snapshots':snaps,'held':held,'entry_px':ent_px,'entry_i':ent_i,'columns':cols}


def event_counts(res):
    out={'CORE':0,'EARLY':0}
    for _,txt in res['pending_snapshots']:
        p=json.loads(txt)
        for x in p.get('entries',[]):
            sl=str(x.get('sleeve') or 'CORE'); out[sl]=out.get(sl,0)+1
    return out


def leader_summary(events,prior_low,idx,m,res,name):
    pos={pd.Timestamp(d):i for i,d in enumerate(idx)}; cmap={s:i for i,s in enumerate(res['columns'])}; rows=[]
    for e in events.itertuples(index=False):
        i0=pos.get(pd.Timestamp(e.start_date)); ip=pos.get(pd.Timestamp(e.peak_date)); j=cmap.get(str(e.symbol))
        if i0 is None or j is None: continue
        ip=min(ip if ip is not None else i0+126,i0+126,len(idx)-1)
        seg=res['held'][i0:ip+1,j]; loc=np.flatnonzero(seg)
        captured=len(loc)>0; rec={'variant':name,'symbol':str(e.symbol),'start_date':e.start_date,'future_peak_return':e.future_peak_return,'captured':captured}
        if captured:
            h=i0+int(loc[0]); ei=int(res['entry_i'][h,j]); ep=float(res['entry_px'][h,j]); rec['delay_sessions']=h-i0
            p0=float(m['close'].at[pd.Timestamp(e.start_date),str(e.symbol)])
            rec['gain_from_event_start']=0.0 if ei<=i0 else (ep/p0-1 if p0>0 and np.isfinite(ep) else np.nan)
            if 0<=ei<len(idx):
                ed=pd.Timestamp(idx[ei]); pl=prior_low.at[ed,str(e.symbol)] if ed in prior_low.index else np.nan
                rec['gain_from_prior126_low_at_entry']=ep/float(pl)-1 if pd.notna(pl) and float(pl)>0 and np.isfinite(ep) else np.nan
        rows.append(rec)
    det=pd.DataFrame(rows); sums=[]
    for period,maskp in [('FULL',pd.Series(True,index=det.index)),('DISCOVERY',pd.to_datetime(det.start_date)<=pd.Timestamp('2021-12-31')),('CONFIRMATION',pd.to_datetime(det.start_date)>=CONF)]:
        for target in (1.0,2.0,4.0):
            g=det[maskp&(det.future_peak_return>=target)]; h=g[g.captured]
            sums.append({'variant':name,'period':period,'future_peak_threshold':target,'events':len(g),'captured':len(h),'capture_rate':len(h)/len(g) if len(g) else None,
                         'median_delay_sessions':float(h.delay_sessions.median()) if len(h) else None,
                         'median_gain_from_event_start':float(h.gain_from_event_start.median()) if len(h) else None,
                         'median_gain_from_prior126_low_at_entry':float(h.gain_from_prior126_low_at_entry.median()) if len(h) else None,
                         'captured_by_50pct_from_prior_low':float((h.gain_from_prior126_low_at_entry<=.5).mean()) if len(h) else None,
                         'captured_by_100pct_from_prior_low':float((h.gain_from_prior126_low_at_entry<=1.0).mean()) if len(h) else None})
    return det,pd.DataFrame(sums)


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--root',default='.'); ap.add_argument('--output',required=True); ap.add_argument('--batch-size',type=int,default=100)
    a=ap.parse_args(); root=Path(a.root); out=root/a.output; out.mkdir(parents=True,exist_ok=True)
    symbols,bio=audit.load_universe(root/'universe.csv'); allowed=earlylive._industry_symbols(root/'industry_map.json'); early_excluded=set(bio)
    if allowed: early_excluded.update(set(symbols)-set(allowed))
    warm=str((START-pd.Timedelta(days=1600)).date()); end='2026-09-05'
    print('DOWNLOAD',flush=True); ohlcv,diag=audit.download_ohlcv(symbols,warm,end,a.batch_size)
    if diag['coverage']<.85: raise RuntimeError(diag)
    print('BUILD NORMAL CORE FEATURES',flush=True); m=broad.build_inputs(ohlcv,bio)
    print('BUILD PRODUCTION INPUTS',flush=True); mx=audit.build_stock_inputs(ohlcv,bio,END); e=pit.early_inputs(ohlcv['close'],ohlcv['volume'],early_excluded)
    nq=audit.market_nqsar(str((START-pd.Timedelta(days=120)).date()),end).reindex(mx['close'].index).ffill(limit=2)
    idx=mx['close'].index[(mx['close'].index>=START)&(mx['close'].index<=END)]
    print('BUILD INDEPENDENT LEADER EVENTS',flush=True); events,prior_low=build_events(m,idx); print('EVENTS',len(events),flush=True)
    metrics=[]; boots=[]; leader_sums=[]; leader_dets=[]; eqs={}
    for name,kind,use_early in SPECS:
        print('SIM',name,flush=True); r=simulate(idx,mx,nq,e,m,kind,use_early); eqs[name]=r['equity']
        sl=lng.slices(r['equity']); rec={'variant':name,**event_counts(r)}
        for p,mm in sl.items():
            for k,v in mm.items(): rec[f'{p}_{k}']=v
        metrics.append(rec); r['equity'].rename('equity').to_csv(out/f'equity_{name}.csv')
        det,sm=leader_summary(events,prior_low,idx,m,r,name); leader_dets.append(det); leader_sums.append(sm)
        del r['held'],r['entry_px'],r['entry_i']
    base=eqs['CURRENT_EARLY1']; rs=eqs['WEEK_RS63_EARLY1']
    for name,eq in eqs.items():
        boots.append({'variant':name,'vs_current_full_block20':lng.blockprob(eq,base),'vs_current_conf_block20':lng.blockprob(eq,base,CONF),
                      'vs_rs63_early_full_block20':lng.blockprob(eq,rs),'vs_rs63_early_conf_block20':lng.blockprob(eq,rs,CONF)})
    pd.DataFrame(metrics).to_csv(out/'metrics.csv',index=False); pd.DataFrame(boots).to_csv(out/'bootstrap.csv',index=False)
    pd.concat(leader_sums,ignore_index=True).to_csv(out/'leader_capture_summary.csv',index=False)
    # detail is intentionally omitted from artifact to keep size reasonable; labels are evaluation-only.
    summary={'method':'reconciled exact V38 sleeve: Core NQSAR features use normal-stock universe (bio exclusion only); Early1 keeps its original industry-map restriction; direct RS63 vs RS189 no-threshold rank; Trend9/Ignition3 Core12; current Market Mode/exits; Top12 then DDV20 no-refill',
             'coverage':diag,'specs':SPECS,'leader_events':len(events),'production_changed':False,
             'important':'corrects prior exact-core confound where Early1 industry-map exclusion leaked into Core feature pool'}
    (out/'summary.json').write_text(json.dumps(safe(summary),ensure_ascii=False,indent=2)); print('DONE_RECONCILED',flush=True)

if __name__=='__main__': main()
