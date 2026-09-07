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

START = pd.Timestamp('2016-01-04')
END = pd.Timestamp('2026-09-04')
CONF = pd.Timestamp('2022-01-03')
DDV_POOL = 10_000_000.0

CORE_VARIANTS = ['CURRENT','WEEK_BULL_RS63','WEEK_BLUE_FIRST_RS63','WEEK_BULL_DAILY_NOT_RED_RS63']


def safe(x):
    if isinstance(x, dict): return {str(k): safe(v) for k,v in x.items()}
    if isinstance(x, (list,tuple)): return [safe(v) for v in x]
    if isinstance(x, np.integer): return int(x)
    if isinstance(x, (np.floating,float)):
        z=float(x); return z if math.isfinite(z) else None
    if isinstance(x,pd.Timestamp): return str(x.date())
    return x


def core_rows(d, f, mx, variant, struct):
    if variant == 'CURRENT':
        return None
    pool = f['pool'].loc[d].fillna(False)
    wb = f['ws'].loc[d] >= 2
    q63 = pd.to_numeric(f['q63'].loc[d], errors='coerce')
    ddv = pd.to_numeric(f['ddv'].loc[d], errors='coerce')
    mask = pool & struct.loc[d].fillna(False) & wb & q63.notna()
    if variant == 'WEEK_BULL_DAILY_NOT_RED_RS63':
        mask &= ~mx['day_red'].loc[d].fillna(False)
    z = pd.DataFrame({'q63': q63, 'ddv': ddv, 'state': f['ws'].loc[d]}).loc[mask]
    if variant == 'WEEK_BLUE_FIRST_RS63':
        z = z.assign(blue=(z['state']==3).astype(int)).sort_values(['blue','q63'], ascending=[False,False])
    else:
        z = z.sort_values('q63', ascending=False)
    rows=[]
    for i,(s,r) in enumerate(z.iterrows(),1):
        rows.append({'ticker':str(s),'final_rank':i,'daily_dollar_volume_m':float(r['ddv'])/1_000_000.0,
                     'stock_rs63_pct':float(r['q63']),'weekly_nqsar_state':int(r['state'])})
    return rows


def simulate(idx, mx, nq, e_existing, f, core_variant, use_early, struct):
    first=pd.Timestamp(idx[0])
    state={'status':'READY','asof':str(first.date()),'cash':1.0,'positions':[],
           'pending':{'full_exits':[],'partial25':[],'entries':[]}}
    eq=[]; snaps=[]
    for d0 in idx:
        d=pd.Timestamp(d0)
        c=pit.companion(d,mx,{},nq,e_existing,True)
        rows=core_rows(d,f,mx,core_variant,struct)
        if rows is not None:
            c=dict(c); c['candidates']=rows
        if not use_early:
            c=dict(c); c['early1']={'status':'READY','entry_allowed_now':False,'candidates':[]}
        state=sleeve.advance_normal(state,c,str(d.date()),mx['open'],mx['close'])
        if not use_early:
            state=marginal.strip_early_and_optionally_fill_core(state,c,True)
        eq.append((d,float(state['nav'])))
        snaps.append((d,json.dumps(state.get('pending',{}),sort_keys=True,default=str)))
    return {'equity':pd.Series(dict(eq),dtype=float),'pending_snapshots':snaps}


def event_counts(res):
    out={'CORE':0,'EARLY':0}
    for _,txt in res['pending_snapshots']:
        p=json.loads(txt)
        for x in p.get('entries',[]):
            sl=str(x.get('sleeve') or 'CORE'); out[sl]=out.get(sl,0)+1
    return out


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--root',default='.'); ap.add_argument('--output',required=True); ap.add_argument('--batch-size',type=int,default=100)
    a=ap.parse_args(); root=Path(a.root); out=root/a.output; out.mkdir(parents=True,exist_ok=True)
    symbols,bio=audit.load_universe(root/'universe.csv')
    allowed=earlylive._industry_symbols(root/'industry_map.json'); early_excluded=set(bio)
    if allowed: early_excluded.update(set(symbols)-set(allowed))
    warm=str((START-pd.Timedelta(days=1600)).date()); end='2026-09-05'
    print('DOWNLOAD',flush=True); ohlcv,diag=audit.download_ohlcv(symbols,warm,end,a.batch_size)
    if diag['coverage']<.85: raise RuntimeError(diag)
    print('BUILD CORE INPUTS',flush=True); mx=audit.build_stock_inputs(ohlcv,bio,END)
    e=pit.early_inputs(ohlcv['close'],ohlcv['volume'],early_excluded)
    print('BUILD NQSAR FEATURES',flush=True); f=focused.build_features(ohlcv,early_excluded,mx)
    c=f['close']; sma50=c.rolling(50,min_periods=50).mean(); sma200=c.rolling(200,min_periods=200).mean()
    struct=f['pool']&(sma50>sma200)&(c>sma200)
    nq=audit.market_nqsar(str((START-pd.Timedelta(days=120)).date()),end).reindex(mx['close'].index).ffill(limit=2)
    idx=mx['close'].index[(mx['close'].index>=START)&(mx['close'].index<=END)]
    results={}; rows=[]
    for cv in CORE_VARIANTS:
        for use_early in (False,True):
            name=f'{cv}__'+('CORE11_EARLY1' if use_early else 'CORE12')
            print('SIM',name,flush=True); r=simulate(idx,mx,nq,e,f,cv,use_early,struct); results[name]=r
            sl=lng.slices(r['equity']); counts=event_counts(r)
            rec={'variant':name,'core_variant':cv,'use_early1':use_early,**counts}
            for p,mm in sl.items():
                for k,v in mm.items(): rec[f'{p}_{k}']=v
            rows.append(rec); r['equity'].rename('equity').to_csv(out/f'equity_{name}.csv')
    met=pd.DataFrame(rows); met.to_csv(out/'metrics.csv',index=False)
    base=results['CURRENT__CORE11_EARLY1']['equity']; boots=[]
    for name,r in results.items():
        if name=='CURRENT__CORE11_EARLY1': continue
        boots.append({'variant':name,'vs_current_full_block20':lng.blockprob(r['equity'],base),
                      'vs_current_conf_block20':lng.blockprob(r['equity'],base,CONF)})
    # Within each Core definition, test whether Early1 still adds value.
    for cv in CORE_VARIANTS:
        aeq=results[f'{cv}__CORE11_EARLY1']['equity']; beq=results[f'{cv}__CORE12']['equity']
        boots.append({'variant':f'{cv}__EARLY1_MARGINAL','vs_current_full_block20':lng.blockprob(aeq,beq),
                      'vs_current_conf_block20':lng.blockprob(aeq,beq,CONF)})
    pd.DataFrame(boots).to_csv(out/'bootstrap.csv',index=False)
    summary={'method':'exact V38 sleeve engine: identical market mode, exits, D10 Early1 expiry, direct promotion, Top12 then DDV20 no-refill; only Core universe/ranking changed',
             'coverage':diag,'core_variants':CORE_VARIANTS,'theme_note':'long history has no hindsight Theme30; comparison isolates Stock NQSAR x RS role','production_changed':False}
    (out/'summary.json').write_text(json.dumps(safe(summary),ensure_ascii=False,indent=2)); print('DONE_EXACT_CORE',flush=True)

if __name__=='__main__': main()
