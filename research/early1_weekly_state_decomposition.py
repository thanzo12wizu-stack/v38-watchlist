from __future__ import annotations

import argparse, json, math
from pathlib import Path
import numpy as np
import pandas as pd

from research import audit_stock_nqsar_theme30_pit as audit
from research import preimpl_core11_early1_pit as pit
from research import preimpl_core11_early1_long as lng
from research import preimpl_early1_marginal as marginal
from research import nqsar_transition_early_marginal as focused
import build_v38_sleeve_live as sleeve
import build_v38_early1_live as earlylive

START=pd.Timestamp('2016-01-04'); END=pd.Timestamp('2026-09-04'); CONF=pd.Timestamp('2022-01-03')
POLICIES=['CORE12','EARLY1_ALL','EARLY1_WEEK_BULL','EARLY1_BLUE','EARLY1_GREEN','EARLY1_YELLOW','EARLY1_NOT_RED']


def safe(x):
    if isinstance(x,dict): return {str(k):safe(v) for k,v in x.items()}
    if isinstance(x,(list,tuple)): return [safe(v) for v in x]
    if isinstance(x,np.integer): return int(x)
    if isinstance(x,(np.floating,float)):
        z=float(x); return z if math.isfinite(z) else None
    return x


def filter_early(c,d,f,policy):
    if policy=='EARLY1_ALL': return c
    if policy=='CORE12':
        z=dict(c); z['early1']={'status':'READY','entry_allowed_now':False,'candidates':[]}; return z
    state=f['ws'].loc[d]
    def ok(s):
        try: v=int(state.get(s,-1))
        except Exception: return False
        if policy=='EARLY1_WEEK_BULL': return v>=2
        if policy=='EARLY1_BLUE': return v==3
        if policy=='EARLY1_GREEN': return v==2
        if policy=='EARLY1_YELLOW': return v==1
        if policy=='EARLY1_NOT_RED': return v>=1
        return False
    z=dict(c); e=dict(c.get('early1') or {}); e['candidates']=[r for r in (e.get('candidates') or []) if ok(str(r.get('ticker') or ''))]; z['early1']=e; return z


def simulate(idx,mx,nq,e,f,policy):
    first=pd.Timestamp(idx[0]); state={'status':'READY','asof':str(first.date()),'cash':1.0,'positions':[],'pending':{'full_exits':[],'partial25':[],'entries':[]}}
    eq=[]; entries=[]
    for d0 in idx:
        d=pd.Timestamp(d0); c=pit.companion(d,mx,{},nq,e,True); c=filter_early(c,d,f,policy)
        state=sleeve.advance_normal(state,c,str(d.date()),mx['open'],mx['close'])
        if policy=='CORE12': state=marginal.strip_early_and_optionally_fill_core(state,c,True)
        for x in state.get('pending',{}).get('entries',[]): entries.append({'date':d,'sleeve':str(x.get('sleeve') or 'CORE'),'symbol':str(x.get('symbol') or '')})
        eq.append((d,float(state['nav'])))
    return {'equity':pd.Series(dict(eq),dtype=float),'entries':pd.DataFrame(entries)}


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--root',default='.'); ap.add_argument('--output',required=True); ap.add_argument('--batch-size',type=int,default=100)
    a=ap.parse_args(); root=Path(a.root); out=root/a.output; out.mkdir(parents=True,exist_ok=True)
    symbols,bio=audit.load_universe(root/'universe.csv'); allowed=earlylive._industry_symbols(root/'industry_map.json'); ex=set(bio)
    if allowed: ex.update(set(symbols)-set(allowed))
    warm=str((START-pd.Timedelta(days=1600)).date()); end='2026-09-05'
    print('DOWNLOAD',flush=True); ohlcv,diag=audit.download_ohlcv(symbols,warm,end,a.batch_size)
    if diag['coverage']<.85: raise RuntimeError(diag)
    print('INPUTS',flush=True); mx=audit.build_stock_inputs(ohlcv,bio,END); e=pit.early_inputs(ohlcv['close'],ohlcv['volume'],ex); f=focused.build_features(ohlcv,ex,mx)
    nq=audit.market_nqsar(str((START-pd.Timedelta(days=120)).date()),end).reindex(mx['close'].index).ffill(limit=2)
    idx=mx['close'].index[(mx['close'].index>=START)&(mx['close'].index<=END)]
    res={}; rows=[]
    for p in POLICIES:
        print('SIM',p,flush=True); r=simulate(idx,mx,nq,e,f,p); res[p]=r; sl=lng.slices(r['equity']); er=r['entries']; ec=int((er.sleeve=='EARLY').sum()) if len(er) else 0
        rec={'variant':p,'early_entries':ec}
        for period,mm in sl.items():
            for k,v in mm.items(): rec[f'{period}_{k}']=v
        rows.append(rec); r['equity'].rename('equity').to_csv(out/f'equity_{p}.csv')
    pd.DataFrame(rows).to_csv(out/'metrics.csv',index=False)
    base=res['EARLY1_ALL']['equity']; core=res['CORE12']['equity']; boots=[]
    for p in POLICIES[1:]:
        boots.append({'variant':p,'vs_all_full':lng.blockprob(res[p]['equity'],base),'vs_all_conf':lng.blockprob(res[p]['equity'],base,CONF),
                      'vs_core12_full':lng.blockprob(res[p]['equity'],core),'vs_core12_conf':lng.blockprob(res[p]['equity'],core,CONF)})
    pd.DataFrame(boots).to_csv(out/'bootstrap.csv',index=False)
    summary={'method':'exact current Core11 + one existing Early1 slot, Early1 candidates filtered only by stock Weekly NQSAR state; all other rules identical','coverage':diag,'policies':POLICIES,'production_changed':False}
    (out/'summary.json').write_text(json.dumps(safe(summary),ensure_ascii=False,indent=2)); print('DONE_EARLY_STATE',flush=True)

if __name__=='__main__': main()
