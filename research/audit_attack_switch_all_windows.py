from __future__ import annotations

import argparse, copy, json, math
from pathlib import Path
import numpy as np
import pandas as pd

from research import validate_attack_schemes_holdout as hold

START=hold.START; HOLDOUT_START=hold.HOLDOUT_START; END=hold.END


def safe(x):
    if isinstance(x,dict): return {str(k):safe(v) for k,v in x.items()}
    if isinstance(x,(list,tuple)): return [safe(v) for v in x]
    if isinstance(x,np.integer): return int(x)
    if isinstance(x,(np.floating,float)):
        z=float(x); return z if math.isfinite(z) else None
    if isinstance(x,pd.Timestamp): return str(x.date())
    return x


def choice_companion(d,mx,nq,e,m,policy,disabled,breadth,d5):
    c=hold.pit.companion(d,mx,{},nq,e,True)
    new_rows=hold.hybrid.hybrid_rows(d,m,'HYBRID8T3I_E1')
    market=c.get('market') or {}; mode=str(market.get('mode') or 'STOP')
    color=str(nq.at[d,'nq_color']) if d in nq.index and pd.notna(nq.at[d,'nq_color']) else ''
    br=float(breadth.get(d,np.nan)); br5=float(d5.get(d,np.nan))
    use_current=False
    if policy=='SWITCH':
        use_current=(mode=='ATTACK' and color.title()=='Blue' and np.isfinite(br) and br>=70.0 and np.isfinite(br5) and br5>=0.0)
        if disabled is not None and disabled[0] <= d <= disabled[1]: use_current=False
    elif policy!='NEW':
        raise ValueError(policy)
    choice='CURRENT' if use_current else '8T3I1E'
    if not use_current:
        c=dict(c); c['candidates']=new_rows
    return c,choice,mode,color,br,br5


def run_policy(idx,mx,nq,e,m,policy,disabled=None,initial_state=None,capture_states=False,capture_signals=False):
    breadth=pd.to_numeric(mx['breadth'].reindex(idx if initial_state is None else mx['breadth'].index),errors='coerce')
    d5=breadth-breadth.shift(5)
    if initial_state is None:
        first=pd.Timestamp(idx[0]); state={'status':'READY','asof':str(first.date()),'cash':1.0,'positions':[],
            'pending':{'full_exits':[],'partial25':[],'entries':[]}}
    else:
        state=copy.deepcopy(initial_state)
    rows=[]; signals=[]; states={}
    for d0 in idx:
        d=pd.Timestamp(d0)
        before={str(p.get('symbol') or ''):float(p.get('shares') or 0.0) for p in state.get('positions',[]) if str(p.get('symbol') or '')}
        nav_open=float(state.get('cash') or 0.0)
        for s,sh in before.items():
            p=hold.px(mx['open'],d,s)
            if np.isfinite(p): nav_open+=sh*p
        c,choice,mode,color,br,br5=choice_companion(d,mx,nq,e,m,policy,disabled,breadth,d5)
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
                     'turnover':float(turnover),'market_mode':mode,'nq_color':color,'engine_choice':choice,'breadth':br,'breadth_d5':br5})
        if capture_signals:
            pending=state.get('pending') or {}
            core=[str(x.get('symbol') or '') for x in pending.get('entries',[]) if isinstance(x,dict) and str(x.get('sleeve') or 'CORE')=='CORE']
            early=[str(x.get('symbol') or '') for x in pending.get('entries',[]) if isinstance(x,dict) and str(x.get('sleeve') or 'CORE')=='EARLY']
            promo=[str(x) for x in pending.get('promotions',[]) if str(x)]
            signals.append({'date':d,'engine_choice':choice,'market_mode':mode,'pending_core':'|'.join(core),'pending_early':'|'.join(early),
                            'promotions':'|'.join(promo),'pending_core_n':len(core),'pending_early_n':len(early),'promotion_n':len(promo)})
        if capture_states: states[d]=copy.deepcopy(state)
    frame=pd.DataFrame(rows).set_index('date'); frame['return']=frame.nav.pct_change(fill_method=None).fillna(0.0)
    # For a tail started from a prior state, first return must use prior NAV rather than zero.
    if initial_state is not None and len(frame):
        frame.iloc[0,frame.columns.get_loc('return')]=float(frame.iloc[0].nav)/max(float(initial_state.get('nav') or 1.0),1e-12)-1.0
    return frame,pd.DataFrame(signals),states


def windows_from(frame):
    h=frame.loc[frame.index>=HOLDOUT_START].copy(); cur=h.engine_choice.eq('CURRENT')
    start=cur & ~cur.shift(fill_value=False); gid=start.cumsum(); rows=[]
    for n,g in h[cur].groupby(gid[cur]):
        rows.append({'window_id':f'W{int(n):02d}','start':pd.Timestamp(g.index.min()),'end':pd.Timestamp(g.index.max()),'sessions':int(len(g))})
    return pd.DataFrame(rows)


def rec_metrics(ret):
    return hold.metrics(ret.loc[(ret.index>=HOLDOUT_START)&(ret.index<=END)])


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

    print('BASELINE_TRACE',flush=True)
    switch,sig_switch,states=run_policy(idx,mx,nq,e,m,'SWITCH',capture_states=True,capture_signals=True)
    new,sig_new,_=run_policy(idx,mx,nq,e,m,'NEW',capture_signals=True)
    ref_switch=hold.simulate_variant(idx,mx,nq,e,m,'SWITCH_BLUE_B70_RISING5'); ref_new=hold.simulate_variant(idx,mx,nq,e,m,'NEW_8T3I1E')
    errs={
      'switch_nav':float((switch.nav-ref_switch.nav).abs().max()),'switch_turnover':float((switch.turnover-ref_switch.turnover).abs().max()),
      'new_nav':float((new.nav-ref_new.nav).abs().max()),'new_turnover':float((new.turnover-ref_new.turnover).abs().max())}
    if max(errs.values())>1e-10: raise RuntimeError(f'BASE_REPRO_FAILED {errs}')

    wins=windows_from(switch); wins.to_csv(out/'current_choice_windows.csv',index=False)
    if len(wins)!=28: raise RuntimeError(f'EXPECTED_28_CURRENT_WINDOWS got={len(wins)}')
    sig_switch=sig_switch[pd.to_datetime(sig_switch.date)>=HOLDOUT_START]; sig_new=sig_new[pd.to_datetime(sig_new.date)>=HOLDOUT_START]
    sig_switch.to_csv(out/'signal_path_switch.csv',index=False); sig_new.to_csv(out/'signal_path_new.csv',index=False)
    sd=sig_switch.merge(sig_new,on='date',suffixes=('_switch','_new'))
    for k in ('pending_core','pending_early','promotions'):
        sd[f'{k}_diff']=sd[f'{k}_switch'].fillna('')!=sd[f'{k}_new'].fillna('')
    sd.to_csv(out/'signal_path_differences.csv',index=False)

    tq=pd.read_csv(args.tqqq_daily,compression='infer'); tq['date']=pd.to_datetime(tq['date'])
    reset=pd.read_csv(args.reset_daily,compression='infer'); reset['date']=pd.to_datetime(reset['date'])
    def primary(stock):
        _,r=hold.frozen.integrate(stock,tq,reset,include_reset=False,cost_bps=25,timing='SAME_DAY_GROSS')
        return rec_metrics(r)
    new_s=rec_metrics(new['return']); switch_s=rec_metrics(switch['return']); new_p=primary(new); switch_p=primary(switch)
    rows=[]
    cal=list(pd.DatetimeIndex(idx)); pos={pd.Timestamp(d):i for i,d in enumerate(cal)}
    for rec in wins.itertuples(index=False):
        a=pd.Timestamp(rec.start); b=pd.Timestamp(rec.end); ip=pos[a]
        if ip<=0: raise RuntimeError('WINDOW_AT_FIRST_SESSION')
        prev=cal[ip-1]; initial=states[pd.Timestamp(prev)]
        tail_idx=pd.DatetimeIndex(cal[ip:])
        tail,_,_=run_policy(tail_idx,mx,nq,e,m,'SWITCH',disabled=(a,b),initial_state=initial)
        combined=pd.concat([switch.loc[switch.index<a],tail]).sort_index()
        if len(combined)!=len(switch) or combined.index.duplicated().any(): raise RuntimeError(f'COMBINE_FAILED {rec.window_id}')
        sm=rec_metrics(combined['return']); pm=primary(combined)
        rows.append({'window_id':rec.window_id,'window_start':a,'window_end':b,'sessions':int(rec.sessions),
                     **{f'stock_{k}':v for k,v in sm.items()},**{f'primary_{k}':v for k,v in pm.items()}})
        print('ABLATE',rec.window_id,str(a.date()),str(b.date()),'primary_cagr',pm['cagr'],flush=True)
    df=pd.DataFrame(rows)
    for metric in ('cagr','mdd','sharpe','end_multiple'):
        for prefix in ('stock','primary'):
            col=f'{prefix}_{metric}'
            df[f'{col}_minus_full']=df[col]-float((switch_s if prefix=='stock' else switch_p)[metric])
            df[f'{col}_minus_new']=df[col]-float((new_s if prefix=='stock' else new_p)[metric])
    df.to_csv(out/'leave_one_window_metrics.csv',index=False)

    current_days=sd.engine_choice_switch.eq('CURRENT')
    path_summary={
      'holdout_current_choice_days':int(current_days.sum()),'current_windows':int(len(wins)),
      'current_days_pending_core_diff_vs_new':int((current_days & sd.pending_core_diff).sum()),
      'current_days_pending_early_diff_vs_new':int((current_days & sd.pending_early_diff).sum()),
      'current_days_promotion_diff_vs_new':int((current_days & sd.promotions_diff).sum()),
      'all_days_pending_core_diff_vs_new':int(sd.pending_core_diff.sum()),
      'all_days_pending_early_diff_vs_new':int(sd.pending_early_diff.sum()),
      'all_days_promotion_diff_vs_new':int(sd.promotions_diff.sum())}
    above=int((df.primary_cagr_minus_new>0).sum()); equal=int(np.isclose(df.primary_cagr_minus_new,0,atol=1e-12).sum()); below=int((df.primary_cagr_minus_new<0).sum())
    worst=df.sort_values('primary_cagr_minus_full').iloc[0].to_dict(); improve=df.sort_values('primary_cagr_minus_full',ascending=False).iloc[0].to_dict()
    summary={'method':'Final fixed all-contiguous-CURRENT-window leave-one-out audit of pre-registered Switch A. Windows are derived mechanically from the frozen condition; each ablation falls back to frozen 8T3I1E for that whole window only. State, exits, Early1 promotions/fills and downstream path are preserved. No threshold search.',
             'coverage':diag,'holdout':[str(HOLDOUT_START.date()),str(END.date())],'reproduction_errors':errs,
             'new_stock':new_s,'switch_stock':switch_s,'new_primary':new_p,'switch_primary':switch_p,'path_summary':path_summary,
             'leave_one_window_primary_cagr_vs_new':{'above':above,'equal':equal,'below':below,'total':int(len(df)),
                 'min_delta':float(df.primary_cagr_minus_new.min()),'median_delta':float(df.primary_cagr_minus_new.median()),'max_delta':float(df.primary_cagr_minus_new.max())},
             'most_important_window_by_primary_cagr_loss':worst,'window_whose_removal_improves_primary_cagr_most':improve,
             'production_changed':False}
    (out/'summary.json').write_text(json.dumps(safe(summary),ensure_ascii=False,indent=2),encoding='utf-8')
    print('DONE',json.dumps(safe(summary),ensure_ascii=False),flush=True)

if __name__=='__main__': main()
