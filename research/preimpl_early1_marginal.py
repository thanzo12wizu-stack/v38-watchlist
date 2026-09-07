from __future__ import annotations
import argparse, json
from pathlib import Path
import numpy as np, pandas as pd
from research import audit_stock_nqsar_theme30_pit as audit
from research import preimpl_core11_early1_pit as pit
from research import preimpl_core11_early1_long as lng
import build_v38_sleeve_live as sleeve
import build_v38_early1_live as earlylive

START=pd.Timestamp('2016-01-04'); END=pd.Timestamp('2026-09-04'); CONF=pd.Timestamp('2022-01-03')


def strip_early_and_optionally_fill_core(state, companion, fill_core12: bool):
    p=dict(state.get('pending') or {})
    entries=[dict(e) for e in p.get('entries',[]) if str((e if isinstance(e,dict) else {}).get('sleeve') or 'CORE')!='EARLY']
    p['entries']=entries
    if not fill_core12:
        state['pending']=p
        return state
    mode=str((companion.get('market') or {}).get('mode') or 'STOP')
    target=12 if mode=='ATTACK' else 4 if mode=='SELECTIVE' else 0
    if target<=0:
        state['pending']=p
        return state
    exiting={str(x.get('symbol')) for x in p.get('full_exits',[]) if isinstance(x,dict)}
    survivors={str(x.get('symbol')) for x in state.get('positions',[]) if str(x.get('symbol')) not in exiting}
    planned={str(x.get('symbol')) for x in entries if isinstance(x,dict)}
    expected=len(survivors|planned)
    ranked=[dict(r) for r in companion.get('candidates',[]) if r.get('final_rank') is not None]
    ranked.sort(key=lambda r:int(r['final_rank']))
    top12=ranked[:12]
    liquid=[r for r in top12 if pit.finite(r.get('daily_dollar_volume_m')) and float(r['daily_dollar_volume_m'])>=20.0]
    for r in liquid:
        if expected>=target: break
        sym=str(r.get('ticker') or '')
        if not sym or sym in survivors or sym in planned: continue
        entries.append({'symbol':sym,'sleeve':'CORE','signal_date':companion.get('asof')})
        planned.add(sym); expected+=1
    p['entries']=entries
    p['entry_cap']=target
    p['core_cap']=target
    p['early_cap']=0
    p['early_policy']='DISABLED_CORE12_REPLACEMENT'
    state['pending']=p
    return state


def simulate(idx,mx,theme,nq,e,weekly,policy):
    first=pd.Timestamp(idx[0]); state={'status':'READY','asof':str(first.date()),'cash':1.0,'positions':[],'pending':{'full_exits':[],'partial25':[],'entries':[]}}
    eq=[]; snaps=[]
    for d0 in idx:
        d=pd.Timestamp(d0); c=pit.companion(d,mx,theme,nq,e,weekly)
        state=sleeve.advance_normal(state,c,str(d.date()),mx['open'],mx['close'])
        if policy=='CORE11_CASH':
            state=strip_early_and_optionally_fill_core(state,c,False)
        elif policy=='CORE12_NO_EARLY':
            state=strip_early_and_optionally_fill_core(state,c,True)
        elif policy!='CORE11_EARLY1':
            raise ValueError(policy)
        eq.append((d,float(state['nav']))); snaps.append((d,json.dumps(state.get('pending',{}),sort_keys=True,default=str)))
    return {'equity':pd.Series(dict(eq),dtype=float),'pending_snapshots':snaps}


def event_counts(res):
    out={'CORE':0,'EARLY':0}
    for _,txt in res['pending_snapshots']:
        p=json.loads(txt)
        for x in p.get('entries',[]):
            sl=str(x.get('sleeve') or 'CORE'); out[sl]=out.get(sl,0)+1
    return out


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--root',default='.'); ap.add_argument('--output',required=True); ap.add_argument('--batch-size',type=int,default=100); a=ap.parse_args(); root=Path(a.root); out=root/a.output; out.mkdir(parents=True,exist_ok=True)
    symbols,bio=audit.load_universe(root/'universe.csv'); allowed=earlylive._industry_symbols(root/'industry_map.json'); early_excluded=set(bio)
    if allowed: early_excluded.update(set(symbols)-set(allowed))
    warm=str((START-pd.Timedelta(days=1600)).date()); end='2026-09-05'
    print('DOWNLOAD',flush=True); ohlcv,diag=audit.download_ohlcv(symbols,warm,end,a.batch_size)
    if diag['coverage']<.85: raise RuntimeError(diag)
    mx=audit.build_stock_inputs(ohlcv,bio,END); e=pit.early_inputs(ohlcv['close'],ohlcv['volume'],early_excluded)
    nq=audit.market_nqsar(str((START-pd.Timedelta(days=90)).date()),end).reindex(mx['close'].index).ffill(limit=2)
    idx=mx['close'].index[(mx['close'].index>=START)&(mx['close'].index<=END)]; theme={}
    specs=[]
    for weekly in (False,True):
        pref='WEEK' if weekly else 'CURRENT'
        for pol in ('CORE11_EARLY1','CORE11_CASH','CORE12_NO_EARLY'):
            specs.append((f'{pref}_{pol}',weekly,pol))
    results={}
    for name,w,p in specs:
        print('SIM',name,flush=True); results[name]=simulate(idx,mx,theme,nq,e,w,p)
    rows=[]
    for name,res in results.items():
        sl=lng.slices(res['equity']); rows.append({'variant':name,**{f'full_{k}':v for k,v in sl['full'].items()},**{f'conf_{k}':v for k,v in sl['confirmation_2022_plus'].items()},**event_counts(res)})
        res['equity'].rename('equity').to_csv(out/f'equity_{name}.csv')
    pd.DataFrame(rows).to_csv(out/'metrics.csv',index=False)
    # Validate production parity for A against prior production-path result by re-running pit.simulate.
    prod_cur=pit.simulate(idx,mx,theme,nq,e,False); prod_wk=pit.simulate(idx,mx,theme,nq,e,True)
    parity={'current_max_abs':float((results['CURRENT_CORE11_EARLY1']['equity']-prod_cur['equity']).abs().max()),'week_max_abs':float((results['WEEK_CORE11_EARLY1']['equity']-prod_wk['equity']).abs().max())}
    summary={'method':'same engine Early1 marginal isolation; A production Core11+Early1, B Core11+cash, C Core12 no Early; Weekly applied only to Core','universe':diag,'metrics':rows,'production_parity':parity,
             'weekly_early_vs_cash_bootstrap_block20':lng.blockprob(results['WEEK_CORE11_EARLY1']['equity'],results['WEEK_CORE11_CASH']['equity']),
             'weekly_early_vs_core12_bootstrap_block20':lng.blockprob(results['WEEK_CORE11_EARLY1']['equity'],results['WEEK_CORE12_NO_EARLY']['equity']),
             'weekly_early_vs_cash_conf_bootstrap_block20':lng.blockprob(results['WEEK_CORE11_EARLY1']['equity'],results['WEEK_CORE11_CASH']['equity'],CONF),
             'weekly_early_vs_core12_conf_bootstrap_block20':lng.blockprob(results['WEEK_CORE11_EARLY1']['equity'],results['WEEK_CORE12_NO_EARLY']['equity'],CONF)}
    if max(parity.values())>1e-12: raise RuntimeError(f'production parity failed {parity}')
    (out/'summary.json').write_text(json.dumps(pit.safe(summary),ensure_ascii=False,indent=2)); print('DONE',json.dumps(pit.safe(summary),ensure_ascii=False),flush=True)
if __name__=='__main__':main()
