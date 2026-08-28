from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from research.rulebook import audit_integrated_allocation as base
from research.rulebook_v2 import audit_market_stop_reentry as ms
from research.rulebook_v3 import audit_custom_market_modes_v2 as v2

COST=base.COST
N_FULL=base.N_PORT


def safe(x):
    if isinstance(x,dict): return {str(k):safe(v) for k,v in x.items()}
    if isinstance(x,(list,tuple)): return [safe(v) for v in x]
    if isinstance(x,np.integer): return int(x)
    if isinstance(x,(np.floating,float)):
        z=float(x); return z if math.isfinite(z) else None
    return x


def mode_for(color:str, pa50:float, reopened:bool, selective_n:int, allow_repair:bool):
    if color=='Red': return 'DEFENSE',0
    if not reopened: return 'WAIT',0
    if color in ('Blue','Green') and pa50>=.60: return 'ATTACK',N_FULL
    if color in ('Blue','Green') and pa50>=.50: return 'SELECTIVE',selective_n
    if allow_repair and color!='Red' and pa50>=.50: return 'REPAIR',selective_n
    return 'HOLD',None


def simulate_tiered(market,signal,frame,selective_n:int,allow_repair:bool,active_trim:bool):
    close,open_=market['close'],market['open']
    calendar=close.index[(close.index>=v2.ANALYSIS_START)&(close.index<=v2.ANALYSIS_END)]
    rebalances=base.rebalance_sessions(calendar)
    f=frame.reindex(calendar).copy()
    lots={}; cash=1.0; initialized=False; turnover=0.0; forced_exit_count=0; entry_days=0; records=[]
    seen_red=False; reopened=True; prior_mode='INIT'; prior_target=None
    for date in calendar:
        previous=close.index[close.index.get_loc(date)-1]
        row=f.loc[previous] if previous in f.index else None
        color='Red' if row is None else str(row.nq_color)
        pa50=np.nan if row is None else float(row.stock_pa50)
        if color=='Red':
            seen_red=True; reopened=False
        elif seen_red and (not reopened) and np.isfinite(pa50) and pa50>=.50:
            reopened=True
        mode,target_n=mode_for(color,pa50,reopened,selective_n,allow_repair)
        open_prices=open_.loc[date]
        for symbol in list(lots):
            px=open_prices.get(symbol,np.nan)
            if lots[symbol].get('stop_next') and pd.notna(px) and px>0:
                cash,sold=base.sell_symbol(cash,lots,symbol,float(px)); turnover+=sold
        if color=='Red':
            for symbol in list(lots):
                px=open_prices.get(symbol,np.nan)
                if pd.notna(px) and px>0:
                    cash,sold=base.sell_symbol(cash,lots,symbol,float(px)); turnover+=sold; forced_exit_count+=1
        elif target_n is not None and target_n>0:
            recovery=(prior_target in (None,0)) or (prior_mode in ('DEFENSE','WAIT','HOLD'))
            capacity_change=(prior_target is not None and target_n!=prior_target)
            do_rebalance=(date in rebalances) or recovery or (active_trim and capacity_change) or (not initialized)
            if do_rebalance:
                picks,continuation_rank=base.core_candidates(previous,market,signal)
                survivors=[s for s in lots if pd.notna(continuation_rank.get(s)) and continuation_rank.get(s)<=24]
                selected=survivors[:target_n]
                selected.extend([s for s in picks if s not in selected][:target_n-len(selected)])
                nav_open,_=base.mark_nav(cash,lots,open_prices)
                target_value=nav_open/target_n
                for symbol in list(lots):
                    if symbol not in selected:
                        px=open_prices.get(symbol,np.nan)
                        if pd.notna(px) and px>0:
                            cash,sold=base.sell_symbol(cash,lots,symbol,float(px)); turnover+=sold
                before=set(lots)
                for symbol in selected:
                    px=open_prices.get(symbol,np.nan)
                    if pd.isna(px) or px<=0: continue
                    px=float(px); current_value=lots.get(symbol,{}).get('shares',0.0)*px; delta=target_value-current_value
                    if delta>1e-12:
                        buy=min(delta,max(0.0,cash)/(1.0+COST))
                        if buy<=0: continue
                        cash-=buy*(1.0+COST); turnover+=buy
                        if symbol not in lots: lots[symbol]={'shares':buy/px,'entry_px':px,'peak':px,'stop_next':False}
                        else: lots[symbol]['shares']+=buy/px
                    elif delta<-1e-12 and symbol in lots:
                        sell=min(-delta,current_value); sh=sell/px; lots[symbol]['shares']-=sh; cash+=sell*(1.0-COST); turnover+=sell
                if set(lots)-before: entry_days+=1
                initialized=True
        close_prices=close.loc[date]
        nav_close,gross=base.mark_nav(cash,lots,close_prices)
        for symbol,lot in lots.items():
            px=close_prices.get(symbol,np.nan)
            if pd.isna(px): continue
            px=float(px); lot['peak']=max(float(lot['peak']),px); stop=max(float(lot['entry_px'])*.75,float(lot['peak'])*.70); lot['stop_next']=px<=stop
        records.append({'date':date,'nav':nav_close,'exposure':gross/nav_close if nav_close>0 else np.nan,'positions':len(lots),'mode':mode,'pa50':pa50,'nq_color':color})
        prior_mode=mode; prior_target=target_n
    daily=pd.DataFrame(records).set_index('date')
    result={'turnover':turnover,'forced_exit_count':forced_exit_count,'entry_days':entry_days}
    return result,daily


def mode_shares(daily):
    x=daily.copy(); total=len(x)
    return {m:float((x.mode==m).sum()/total) for m in ['ATTACK','SELECTIVE','REPAIR','HOLD','WAIT','DEFENSE']}


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--root',default='.'); ap.add_argument('--output',required=True); ap.add_argument('--asof',default='2026-08-28'); args=ap.parse_args()
    out=Path(args.output); out.mkdir(parents=True,exist_ok=True)
    market,signal,frame=v2.build_frame(Path(args.root),args.asof)
    policies=[]
    for n in [4,6,8]:
        policies.append((f'TIER_ENTRY_N{n}',n,True,False))
    policies.append(('TIER_TRIM_N6',6,True,True))
    policies.append(('TIER_NO_REPAIR_N6',6,False,False))
    rows=[]; shares=[]
    for name,n,repair,trim in policies:
        meta,daily=simulate_tiered(market,signal,frame,n,repair,trim)
        for period,vals in ms.period_metrics(daily).items():
            if period in ('ALL','DISCOVERY','CONFIRM','2018Q4','COVID2020','BEAR2022'):
                rows.append({'rule':name,'period':period,**vals,**meta})
        shares.append({'rule':name,**mode_shares(daily)})
    # Direct full-cap comparators from proven thresholds.
    bg=frame.nq_color.isin(['Blue','Green'])
    for name,mask in [('PA50_FULL',bg&(frame.stock_pa50>=.50)),('PA60_FULL',bg&(frame.stock_pa50>=.60))]:
        meta,daily=ms.simulate_core(market,signal,v2.v1.permission_from_mask(frame,mask),force_exit_red=True)
        for period,vals in ms.period_metrics(daily).items():
            if period in ('ALL','DISCOVERY','CONFIRM','2018Q4','COVID2020','BEAR2022'):
                rows.append({'rule':name,'period':period,**vals,**meta})
    pd.DataFrame(rows).to_csv(out/'tiered_simulations.csv',index=False)
    pd.DataFrame(shares).to_csv(out/'mode_shares.csv',index=False)
    summary={'status':'NORMAL_STOCK_TIERED_MODES_V4','scope':'normal stock only','fixed_boundaries':{'attack_pa50':.60,'selective_pa50':[.50,.60],'post_red_restart_pa50':.50,'defense':'NQSAR Red'},'selective_capacity_tests':[4,6,8],'repair':'Yellow/non-Red with breadth>=50 tested on/off','downgrade_trim':'entry-only vs immediate trim tested at N=6','note':'Thresholds frozen from V3 before this sizing test. No RSI30/TQQQ/shallow rule changes. No main/dashboard changes.'}
    (out/'summary.json').write_text(json.dumps(safe(summary),ensure_ascii=False,indent=2),encoding='utf-8')
    print('NORMAL_STOCK_TIERED_MODES_V4_DONE',flush=True)

if __name__=='__main__': main()
