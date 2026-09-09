from __future__ import annotations

import argparse, json, math
from pathlib import Path
import numpy as np
import pandas as pd

from research import validate_attack_schemes_holdout as hold

START=hold.START; HOLDOUT_START=hold.HOLDOUT_START; END=hold.END
EPISODES={
    'E1_2022NOV':('2022-11-14','2022-11-16','SLB,TMDX'),
    'E2_2023JAN12':('2023-01-12','2023-01-17','EDU'),
    'E3_2023JAN25':('2023-01-25','2023-01-27','CRDO'),
    'E4_2024MAR28':('2024-03-28','2024-03-28','VKTX'),
    'E5_2024OCT16':('2024-10-16','2024-10-18','UXIN/OKLO path'),
    'E6_2025MAY12':('2025-05-12','2025-05-13','DAVE,SEZL,PRCH,ASST,RGC,TDUP,QBTS,AEVA'),
    'E7_2025MAY15':('2025-05-15','2025-05-20','QUBT'),
    'E8_2025JUN03':('2025-06-03','2025-06-12','QUBT'),
    'E9_2026JAN08':('2026-01-08','2026-01-13','KRMN,BW'),
}


def safe(x):
    if isinstance(x,dict): return {str(k):safe(v) for k,v in x.items()}
    if isinstance(x,(list,tuple)): return [safe(v) for v in x]
    if isinstance(x,np.integer): return int(x)
    if isinstance(x,(np.floating,float)):
        z=float(x); return z if math.isfinite(z) else None
    if isinstance(x,pd.Timestamp): return str(x.date())
    return x


def simulate_switch(idx,mx,nq,e,m,disabled=None):
    breadth=pd.to_numeric(mx['breadth'].reindex(idx),errors='coerce'); d5=breadth-breadth.shift(5)
    first=pd.Timestamp(idx[0]); state={'status':'READY','asof':str(first.date()),'cash':1.0,'positions':[],
        'pending':{'full_exits':[],'partial25':[],'entries':[]}}
    rows=[]; a=b=None
    if disabled:
        a=pd.Timestamp(EPISODES[disabled][0]); b=pd.Timestamp(EPISODES[disabled][1])
    for d0 in idx:
        d=pd.Timestamp(d0)
        before={str(p.get('symbol') or ''):float(p.get('shares') or 0.0) for p in state.get('positions',[]) if str(p.get('symbol') or '')}
        nav_open=float(state.get('cash') or 0.0)
        for s,sh in before.items():
            p=hold.px(mx['open'],d,s)
            if np.isfinite(p): nav_open+=sh*p
        c=hold.pit.companion(d,mx,{},nq,e,True)
        new_rows=hold.hybrid.hybrid_rows(d,m,'HYBRID8T3I_E1'); market=c.get('market') or {}; mode=str(market.get('mode') or 'STOP')
        color=str(nq.at[d,'nq_color']) if d in nq.index and pd.notna(nq.at[d,'nq_color']) else ''
        br=float(breadth.get(d,np.nan)); br5=float(d5.get(d,np.nan))
        use_current=(mode=='ATTACK' and color.title()=='Blue' and np.isfinite(br) and br>=70 and np.isfinite(br5) and br5>=0)
        if disabled and a<=d<=b: use_current=False
        choice='CURRENT' if use_current else '8T3I1E'
        if not use_current:
            c=dict(c); c['candidates']=new_rows
        state=hold.sleeve.advance_normal(state,c,str(d.date()),mx['open'],mx['close'])
        after={str(p.get('symbol') or ''):float(p.get('shares') or 0.0) for p in state.get('positions',[]) if str(p.get('symbol') or '')}
        buy=sell=0.0
        for s in set(before)|set(after):
            delta=after.get(s,0.0)-before.get(s,0.0)
            if abs(delta)<=1e-14: continue
            p=hold.px(mx['open'],d,s)
            if not np.isfinite(p): continue
            notional=abs(delta)*p
            if delta>0: buy+=notional
            else: sell+=notional
        turnover=(buy+sell)/max(nav_open,1e-12)
        rows.append({'date':d,'nav':float(state['nav']),'gross_exposure':float(state.get('desired_pct') or 0)/100,
                     'turnover':float(turnover),'market_mode':mode,'engine_choice':choice,'breadth':br,'breadth_d5':br5})
    out=pd.DataFrame(rows).set_index('date'); out['return']=out.nav.pct_change(fill_method=None).fillna(0.0); return out


def rec_metrics(ret):
    z=ret.loc[(ret.index>=HOLDOUT_START)&(ret.index<=END)]
    return hold.metrics(z)


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--root',default='.'); ap.add_argument('--tqqq-daily',required=True); ap.add_argument('--reset-daily',required=True); ap.add_argument('--output',required=True); ap.add_argument('--batch-size',type=int,default=100)
    args=ap.parse_args(); root=Path(args.root); out=root/args.output; out.mkdir(parents=True,exist_ok=True)
    hold.audit.download_ohlcv=hold.resilient.resilient_download_ohlcv; hold.resilient.patch_numpy_string_concat()
    symbols,bio=hold.audit.load_universe(root/'universe.csv'); allowed=hold.earlylive._industry_symbols(root/'industry_map.json'); early_excluded=set(bio)
    if allowed: early_excluded.update(set(symbols)-set(allowed))
    warm=str((START-pd.Timedelta(days=1600)).date()); end_download=str((END+pd.Timedelta(days=1)).date())
    print('DOWNLOAD',flush=True); ohlcv,diag=hold.audit.download_ohlcv(symbols,warm,end_download,args.batch_size)
    if float(diag.get('coverage') or 0)<.85: raise RuntimeError(diag)
    print('BUILD',flush=True); m=hold.broad.build_inputs(ohlcv,bio); mx=hold.audit.build_stock_inputs(ohlcv,bio,END)
    e=hold.pit.early_inputs(ohlcv['close'],ohlcv['volume'],early_excluded)
    nq=hold.audit.market_nqsar(str((START-pd.Timedelta(days=120)).date()),end_download).reindex(mx['close'].index).ffill(limit=2)
    idx=mx['close'].index[(mx['close'].index>=START)&(mx['close'].index<=END)]

    print('BASES',flush=True); new=hold.simulate_variant(idx,mx,nq,e,m,'NEW_8T3I1E'); full=hold.simulate_variant(idx,mx,nq,e,m,'SWITCH_BLUE_B70_RISING5')
    custom=simulate_switch(idx,mx,nq,e,m,None); err=float((custom.nav-full.nav).abs().max()); terr=float((custom.turnover-full.turnover).abs().max())
    if err>1e-10 or terr>1e-10: raise RuntimeError(f'FULL_SWITCH_REPRO_FAILED nav={err} turnover={terr}')
    tq=pd.read_csv(args.tqqq_daily,compression='infer'); tq['date']=pd.to_datetime(tq['date'])
    reset=pd.read_csv(args.reset_daily,compression='infer'); reset['date']=pd.to_datetime(reset['date'])

    def primary(stock):
        _,r=hold.frozen.integrate(stock,tq,reset,include_reset=False,cost_bps=25,timing='SAME_DAY_GROSS')
        return rec_metrics(r)
    base_new_s=rec_metrics(new['return']); base_full_s=rec_metrics(full['return']); base_new_p=primary(new); base_full_p=primary(full)
    rows=[]
    rows.append({'variant':'NEW_8T3I1E','removed_episode':'NONE',**{f'stock_{k}':v for k,v in base_new_s.items()},**{f'primary_{k}':v for k,v in base_new_p.items()}})
    rows.append({'variant':'FULL_SWITCH_A','removed_episode':'NONE',**{f'stock_{k}':v for k,v in base_full_s.items()},**{f'primary_{k}':v for k,v in base_full_p.items()}})
    for name,(a,b,syms) in EPISODES.items():
        print('ABLATE',name,a,b,syms,flush=True); s=simulate_switch(idx,mx,nq,e,m,name); sm=rec_metrics(s['return']); pm=primary(s)
        rows.append({'variant':'SWITCH_A_MINUS_ONE','removed_episode':name,'episode_start':a,'episode_end':b,'episode_symbols':syms,
                     **{f'stock_{k}':v for k,v in sm.items()},**{f'primary_{k}':v for k,v in pm.items()}})
    df=pd.DataFrame(rows)
    for metric in ('cagr','mdd','sharpe','end_multiple'):
        for prefix in ('stock','primary'):
            col=f'{prefix}_{metric}'
            df[f'{col}_minus_full']=df[col]-float(df.loc[df.variant=='FULL_SWITCH_A',col].iloc[0])
            df[f'{col}_minus_new']=df[col]-float(df.loc[df.variant=='NEW_8T3I1E',col].iloc[0])
    df.to_csv(out/'episode_ablation_metrics.csv',index=False)
    abl=df[df.variant=='SWITCH_A_MINUS_ONE'].copy()
    worst=abl.sort_values('primary_cagr_minus_full').iloc[0].to_dict(); best=abl.sort_values('primary_cagr_minus_full',ascending=False).iloc[0].to_dict()
    summary={'method':'Fixed leave-one-episode-out sensitivity audit of pre-registered Switch A; no threshold or strategy search.',
             'coverage':diag,'holdout':[str(HOLDOUT_START.date()),str(END.date())],'episodes':EPISODES,
             'full_switch_repro_max_nav_error':err,'full_switch_repro_max_turnover_error':terr,
             'new_primary':base_new_p,'full_switch_primary':base_full_p,'new_stock':base_new_s,'full_switch_stock':base_full_s,
             'most_important_episode_by_primary_cagr_loss':worst,'episode_whose_removal_improves_primary_cagr_most':best,'production_changed':False}
    (out/'summary.json').write_text(json.dumps(safe(summary),ensure_ascii=False,indent=2),encoding='utf-8')
    print('DONE',json.dumps(safe(summary),ensure_ascii=False),flush=True)

if __name__=='__main__': main()
