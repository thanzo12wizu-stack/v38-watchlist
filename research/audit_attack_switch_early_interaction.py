from __future__ import annotations

import argparse, json, math
from pathlib import Path
import numpy as np
import pandas as pd

from research import validate_attack_schemes_holdout as hold
from research import preimpl_early1_marginal as marginal

START=hold.START; HOLDOUT_START=hold.HOLDOUT_START; END=hold.END
POLICIES=("CORE11_EARLY1","CORE11_CASH","CORE12_NO_EARLY")
VARIANTS=("NEW_8T3I1E","SWITCH_BLUE_B70_RISING5")


def safe(x):
    if isinstance(x,dict): return {str(k):safe(v) for k,v in x.items()}
    if isinstance(x,(list,tuple)): return [safe(v) for v in x]
    if isinstance(x,np.integer): return int(x)
    if isinstance(x,(np.floating,float)):
        z=float(x); return z if math.isfinite(z) else None
    if isinstance(x,pd.Timestamp): return str(x.date())
    return x


def px(frame,d,s):
    try:
        z=float(frame.at[d,s]); return z if np.isfinite(z) and z>0 else np.nan
    except Exception: return np.nan


def simulate(idx,mx,nq,e,m,variant,policy):
    breadth=pd.to_numeric(mx['breadth'].reindex(idx),errors='coerce'); d5=breadth-breadth.shift(5)
    first=pd.Timestamp(idx[0]); state={'status':'READY','asof':str(first.date()),'cash':1.0,'positions':[],
        'pending':{'full_exits':[],'partial25':[],'entries':[]}}
    rows=[]
    for d0 in idx:
        d=pd.Timestamp(d0)
        before={str(p.get('symbol')):float(p.get('shares') or 0.0) for p in state.get('positions',[])}
        nav_open=float(state.get('cash') or 0.0)
        for s,sh in before.items():
            p=px(mx['open'],d,s)
            if np.isfinite(p): nav_open+=sh*p
        c=hold.pit.companion(d,mx,{},nq,e,True)
        new_rows=hold.hybrid.hybrid_rows(d,m,'HYBRID8T3I_E1')
        mode=str((c.get('market') or {}).get('mode') or 'STOP')
        color=str(nq.at[d,'nq_color']) if d in nq.index and pd.notna(nq.at[d,'nq_color']) else ''
        br=float(breadth.get(d,np.nan)); br5=float(d5.get(d,np.nan)); choice='8T3I1E'
        if variant=='NEW_8T3I1E':
            c=dict(c); c['candidates']=new_rows
        elif variant=='SWITCH_BLUE_B70_RISING5':
            use_current=(mode=='ATTACK' and color.title()=='Blue' and np.isfinite(br) and br>=70.0 and np.isfinite(br5) and br5>=0.0)
            if use_current: choice='CURRENT'
            else:
                c=dict(c); c['candidates']=new_rows
        else: raise ValueError(variant)
        state=hold.sleeve.advance_normal(state,c,str(d.date()),mx['open'],mx['close'])
        if policy=='CORE11_CASH': state=marginal.strip_early_and_optionally_fill_core(state,c,False)
        elif policy=='CORE12_NO_EARLY': state=marginal.strip_early_and_optionally_fill_core(state,c,True)
        elif policy!='CORE11_EARLY1': raise ValueError(policy)
        after={str(p.get('symbol')):float(p.get('shares') or 0.0) for p in state.get('positions',[])}
        turn=0.0
        for s in set(before)|set(after):
            delta=after.get(s,0.0)-before.get(s,0.0)
            if abs(delta)<=1e-14: continue
            p=px(mx['open'],d,s)
            if np.isfinite(p): turn+=abs(delta)*p/max(nav_open,1e-12)
        rows.append({'date':d,'nav':float(state['nav']),'gross_exposure':float(state.get('desired_pct') or 0.0)/100.0,
                     'turnover':float(turn),'market_mode':mode,'engine_choice':choice,'breadth':br,'breadth_d5':br5})
    out=pd.DataFrame(rows).set_index('date'); out['return']=out.nav.pct_change(fill_method=None).fillna(0.0); return out


def hm(ret): return hold.metrics(ret.loc[(ret.index>=HOLDOUT_START)&(ret.index<=END)])


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--root',default='.'); ap.add_argument('--tqqq-daily',required=True); ap.add_argument('--output',required=True); ap.add_argument('--batch-size',type=int,default=100)
    a=ap.parse_args(); root=Path(a.root); out=root/a.output; out.mkdir(parents=True,exist_ok=True)
    hold.audit.download_ohlcv=hold.resilient.resilient_download_ohlcv; hold.resilient.patch_numpy_string_concat()
    symbols,bio=hold.audit.load_universe(root/'universe.csv'); allowed=hold.earlylive._industry_symbols(root/'industry_map.json'); early_excluded=set(bio)
    if allowed: early_excluded.update(set(symbols)-set(allowed))
    warm=str((START-pd.Timedelta(days=1600)).date()); end_download=str((END+pd.Timedelta(days=1)).date())
    print('DOWNLOAD',flush=True); ohlcv,diag=hold.audit.download_ohlcv(symbols,warm,end_download,a.batch_size)
    if float(diag.get('coverage') or 0)<.85: raise RuntimeError(diag)
    print('BUILD',flush=True); m=hold.broad.build_inputs(ohlcv,bio); mx=hold.audit.build_stock_inputs(ohlcv,bio,END)
    e=hold.pit.early_inputs(ohlcv['close'],ohlcv['volume'],early_excluded)
    nq=hold.audit.market_nqsar(str((START-pd.Timedelta(days=120)).date()),end_download).reindex(mx['close'].index).ffill(limit=2)
    idx=mx['close'].index[(mx['close'].index>=START)&(mx['close'].index<=END)]
    tq=pd.read_csv(a.tqqq_daily,compression='infer'); tq['date']=pd.to_datetime(tq['date'])

    res={}; rows=[]
    for pol in POLICIES:
        for v in VARIANTS:
            print('SIM',pol,v,flush=True); s=simulate(idx,mx,nq,e,m,v,pol); res[(pol,v)]=s; s.to_csv(out/f'stock_{pol}_{v}.csv.gz',compression='gzip')
            sm=hm(s['return']); rows.append({'policy':pol,'variant':v,'scenario':'STOCK_ONLY','timing':'NA','cost_bps':0,**sm})
            for timing in ('SAME_DAY_GROSS','LAG1_GROSS'):
                for cost in (0,25):
                    _,r=hold.frozen.integrate(s,tq,None,include_reset=False,cost_bps=cost,timing=timing)
                    rows.append({'policy':pol,'variant':v,'scenario':'STOCK_PLUS_TQQQ','timing':timing,'cost_bps':cost,**hm(r)})

    # Reproduce frozen original Early1 paths exactly before interpreting controls.
    for v in VARIANTS:
        ref=hold.simulate_variant(idx,mx,nq,e,m,v)
        got=res[('CORE11_EARLY1',v)]
        ne=float((got.nav-ref.nav).abs().max()); te=float((got.turnover-ref.turnover).abs().max())
        if ne>1e-10 or te>1e-10: raise RuntimeError(f'EARLY1_REPRO_FAILED {v} nav={ne} turnover={te}')

    df=pd.DataFrame(rows); df.to_csv(out/'metrics.csv',index=False)
    deltas=[]
    for keys,g in df.groupby(['policy','scenario','timing','cost_bps'],dropna=False):
        z=g.set_index('variant')
        if set(VARIANTS).issubset(z.index):
            rec=dict(zip(['policy','scenario','timing','cost_bps'],keys))
            for k in ('cagr','mdd','sharpe','end_multiple'):
                rec[f'new_{k}']=z.at['NEW_8T3I1E',k]; rec[f'switch_{k}']=z.at['SWITCH_BLUE_B70_RISING5',k]; rec[f'delta_{k}']=rec[f'switch_{k}']-rec[f'new_{k}']
            deltas.append(rec)
    dd=pd.DataFrame(deltas); dd.to_csv(out/'switch_minus_new_by_early_policy.csv',index=False)
    primary=dd[(dd.scenario=='STOCK_PLUS_TQQQ')&(dd.timing=='SAME_DAY_GROSS')&(dd.cost_bps==25)].copy(); primary.to_csv(out/'primary_by_early_policy.csv',index=False)
    summary={'method':'Fixed Switch A vs frozen 8T3I1E under three Early policies: adopted Core11+Early1, Core11 with Early1 disabled/cash, and Core12 no-Early replacement. Switch threshold, stock exits, TQQQ, costs and holdout are unchanged.',
             'coverage':diag,'holdout':[str(HOLDOUT_START.date()),str(END.date())],'primary':primary.to_dict('records'),'production_changed':False}
    (out/'summary.json').write_text(json.dumps(safe(summary),ensure_ascii=False,indent=2),encoding='utf-8'); print('DONE',json.dumps(safe(summary),ensure_ascii=False),flush=True)

if __name__=='__main__': main()
