from __future__ import annotations

import argparse, json, math
from pathlib import Path
import numpy as np
import pandas as pd

from research import audit_stock_nqsar_theme30_pit as audit
from research import preimpl_core11_early1_pit as pit
from research import preimpl_core11_early1_long as lng
from research import nqsar_centric_broad_scan as broad
from research import nqsar_exact_reconciled_final as exact
from research import nqsar_hybrid_three_role_exact as hybrid
import build_v38_sleeve_live as sleeve
import build_v38_early1_live as earlylive

START=exact.START; END=exact.END; CONF=exact.CONF
SPECS=[
    ('A_RS63_EARLY1','WEEK_RS63',True),
    ('B_TREND9_IGN3','MIX9_IGN3',False),
    ('HYBRID9T2I_E1','HYBRID9T2I_E1',True),
    ('HYBRID8T3I_E1','HYBRID8T3I_E1',True),
]
COST_BPS=(0,10,25,50)
BLOCKS=(5,10,20,40,63)


def safe(x):
    if isinstance(x,dict): return {str(k):safe(v) for k,v in x.items()}
    if isinstance(x,(list,tuple)): return [safe(v) for v in x]
    if isinstance(x,np.integer): return int(x)
    if isinstance(x,(np.floating,float)):
        z=float(x); return z if math.isfinite(z) else None
    if isinstance(x,pd.Timestamp): return str(x.date())
    return x


def _px(frame,d,s):
    try:
        x=float(frame.at[d,s]); return x if np.isfinite(x) and x>0 else np.nan
    except Exception: return np.nan


def simulate_turnover(idx,mx,nq,e,m,kind,use_early):
    first=pd.Timestamp(idx[0])
    state={'status':'READY','asof':str(first.date()),'cash':1.0,'positions':[],
           'pending':{'full_exits':[],'partial25':[],'entries':[]}}
    eq=[]; turns=[]; buys=[]; sells=[]
    for d0 in idx:
        d=pd.Timestamp(d0)
        before={str(p.get('symbol')):float(p.get('shares') or 0.0) for p in state.get('positions',[])}
        cash_before=float(state.get('cash') or 0.0)
        nav_open=cash_before
        for s,sh in before.items():
            px=_px(mx['open'],d,s)
            if np.isfinite(px): nav_open += sh*px

        c=pit.companion(d,mx,{},nq,e,True)
        if kind!='CURRENT':
            c=dict(c)
            if kind in hybrid.PATTERNS: c['candidates']=hybrid.hybrid_rows(d,m,kind)
            else: c['candidates']=exact.ranked_core_rows(d,m,kind)
        if not use_early:
            c=dict(c); c['early1']={'status':'READY','entry_allowed_now':False,'candidates':[]}
        state=sleeve.advance_normal(state,c,str(d.date()),mx['open'],mx['close'])
        if not use_early:
            from research import preimpl_early1_marginal as marginal
            state=marginal.strip_early_and_optionally_fill_core(state,c,True)
        after={str(p.get('symbol')):float(p.get('shares') or 0.0) for p in state.get('positions',[])}
        allsyms=set(before)|set(after); buy_not=0.0; sell_not=0.0
        for s in allsyms:
            delta=after.get(s,0.0)-before.get(s,0.0)
            if abs(delta)<=1e-14: continue
            px=_px(mx['open'],d,s)
            if not np.isfinite(px): continue
            notional=abs(delta)*px
            if delta>0: buy_not += notional
            else: sell_not += notional
        denom=max(nav_open,1e-12)
        turns.append((d,(buy_not+sell_not)/denom)); buys.append((d,buy_not/denom)); sells.append((d,sell_not/denom))
        eq.append((d,float(state['nav'])))
    return {'equity':pd.Series(dict(eq),dtype=float),
            'turnover':pd.Series(dict(turns),dtype=float),
            'buy_turnover':pd.Series(dict(buys),dtype=float),
            'sell_turnover':pd.Series(dict(sells),dtype=float)}


def cost_equity(eq,turn,bps):
    r=eq.pct_change(fill_method=None).fillna(0.0)
    c=float(bps)/10000.0
    nr=(r-c*turn.reindex(eq.index).fillna(0.0)).clip(lower=-0.999999)
    out=(1.0+nr).cumprod()
    out.iloc[0]=1.0
    return out


def met(eq):
    if len(eq)<2:return {'cagr':None,'mdd':None,'sharpe':None}
    yrs=(eq.index[-1]-eq.index[0]).days/365.25
    cagr=float((eq.iloc[-1]/eq.iloc[0])**(1/max(yrs,1e-9))-1)
    dd=eq/eq.cummax()-1
    r=eq.pct_change(fill_method=None).dropna()
    sh=float(r.mean()/r.std(ddof=1)*np.sqrt(252)) if len(r)>2 and r.std(ddof=1)>0 else None
    return {'cagr':cagr,'mdd':float(dd.min()),'sharpe':sh}


def slices(eq):
    ranges={
      'FULL':(START,None),
      'DISCOVERY_2016_2021':(START,pd.Timestamp('2021-12-31')),
      'CONF_2022_PLUS':(CONF,None),
      'REGIME_2022_2023':(CONF,pd.Timestamp('2023-12-31')),
      'REGIME_2024_PLUS':(pd.Timestamp('2024-01-01'),None),
    }
    out={}
    for name,(a,b) in ranges.items():
        z=eq.loc[eq.index>=a]
        if b is not None:z=z.loc[z.index<=b]
        out[name]=met(z)
    return out


def annual_rows(name,eq):
    rows=[]
    for y,g in eq.groupby(eq.index.year):
        if len(g)<2: continue
        rows.append({'variant':name,'year':int(y),'return':float(g.iloc[-1]/g.iloc[0]-1)})
    return rows


def rolling_rows(name,eq,win):
    vals=[]
    arr=eq.to_numpy(float); dates=eq.index
    for i in range(win,len(eq)):
        a=arr[i-win]; b=arr[i]
        if not (np.isfinite(a) and np.isfinite(b) and a>0): continue
        years=win/252.0
        vals.append({'variant':name,'window_sessions':win,'end_date':dates[i],
                     'cagr':float((b/a)**(1/years)-1)})
    return pd.DataFrame(vals)


def blockprob(a,b,block,reps=10000,seed=20260908):
    x=(a.pct_change(fill_method=None)-b.pct_change(fill_method=None)).dropna().to_numpy(float)
    n=len(x)
    if n<block:return None
    starts=np.arange(n-block+1); rng=np.random.default_rng(seed+block); wins=0
    for _ in range(reps):
        z=[]
        while len(z)<n:
            st=int(rng.choice(starts)); z.extend(x[st:st+block])
        wins += np.mean(z[:n])>0
    return wins/reps


def rolling_summary(roll,anchor_map):
    out=[]
    for win in sorted(roll.window_sessions.unique()):
        sub=roll[roll.window_sessions==win]
        piv=sub.pivot(index='end_date',columns='variant',values='cagr').dropna()
        for v in piv.columns:
            z=piv[v]
            rec={'variant':v,'window_sessions':int(win),'windows':len(z),
                 'median_cagr':float(z.median()),'p10_cagr':float(z.quantile(.10)),'min_cagr':float(z.min()),
                 'positive_rate':float((z>0).mean())}
            for label,a in anchor_map.items():
                if a in piv.columns:rec[f'outperform_{label}_rate']=float((piv[v]>piv[a]).mean())
            out.append(rec)
    return pd.DataFrame(out)


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--root',default='.'); ap.add_argument('--output',required=True); ap.add_argument('--batch-size',type=int,default=100)
    a=ap.parse_args(); root=Path(a.root); out=root/a.output; out.mkdir(parents=True,exist_ok=True)
    symbols,bio=audit.load_universe(root/'universe.csv'); allowed=earlylive._industry_symbols(root/'industry_map.json'); early_excluded=set(bio)
    if allowed: early_excluded.update(set(symbols)-set(allowed))
    warm=str((START-pd.Timedelta(days=1600)).date()); end='2026-09-05'
    print('DOWNLOAD',flush=True); ohlcv,diag=audit.download_ohlcv(symbols,warm,end,a.batch_size)
    if diag['coverage']<.85: raise RuntimeError(diag)
    print('BUILD INPUTS',flush=True); m=broad.build_inputs(ohlcv,bio); mx=audit.build_stock_inputs(ohlcv,bio,END); e=pit.early_inputs(ohlcv['close'],ohlcv['volume'],early_excluded)
    nq=audit.market_nqsar(str((START-pd.Timedelta(days=120)).date()),end).reindex(mx['close'].index).ffill(limit=2)
    idx=mx['close'].index[(mx['close'].index>=START)&(mx['close'].index<=END)]

    results={}; metrics=[]; ann=[]; rolls=[]; turnover=[]
    for name,kind,use_early in SPECS:
        print('SIM',name,flush=True); r=simulate_turnover(idx,mx,nq,e,m,kind,use_early); results[name]=r
        r['equity'].rename('equity').to_csv(out/f'equity_{name}.csv'); r['turnover'].rename('turnover').to_csv(out/f'turnover_{name}.csv')
        years=(idx[-1]-idx[0]).days/365.25
        turnover.append({'variant':name,'total_turnover':float(r['turnover'].sum()),'annualized_turnover':float(r['turnover'].sum()/years),
                         'buy_turnover':float(r['buy_turnover'].sum()),'sell_turnover':float(r['sell_turnover'].sum()),
                         'active_trade_days':int((r['turnover']>1e-12).sum())})
        for bps in COST_BPS:
            ce=cost_equity(r['equity'],r['turnover'],bps)
            sl=slices(ce); rec={'variant':name,'cost_bps_per_side':bps}
            for p,mm in sl.items():
                for k,v in mm.items():rec[f'{p}_{k}']=v
            metrics.append(rec)
            if bps in (0,25):ann.extend([{**x,'cost_bps_per_side':bps} for x in annual_rows(name,ce)])
            if bps in (0,25):
                rolls.append(rolling_rows(name,ce,504).assign(cost_bps_per_side=bps))
                rolls.append(rolling_rows(name,ce,756).assign(cost_bps_per_side=bps))
    pd.DataFrame(metrics).to_csv(out/'robustness_metrics.csv',index=False); pd.DataFrame(turnover).to_csv(out/'turnover_summary.csv',index=False)
    adf=pd.DataFrame(ann); adf.to_csv(out/'annual_returns.csv',index=False)
    rdf=pd.concat(rolls,ignore_index=True); rdf.to_csv(out/'rolling_windows.csv',index=False)
    rs=[]
    anchors={'A':'A_RS63_EARLY1','B':'B_TREND9_IGN3'}
    for bps in (0,25):
        rr={k:cost_equity(v['equity'],v['turnover'],bps) for k,v in results.items()}
        rs0=rolling_summary(rdf[rdf.cost_bps_per_side==bps],anchors); rs0['cost_bps_per_side']=bps; rs.append(rs0)
    pd.concat(rs,ignore_index=True).to_csv(out/'rolling_summary.csv',index=False)

    boots=[]
    for bps in (0,25):
        rr={k:cost_equity(v['equity'],v['turnover'],bps) for k,v in results.items()}
        for v in ('HYBRID9T2I_E1','HYBRID8T3I_E1'):
            for label,base in anchors.items():
                for block in BLOCKS:
                    full=blockprob(rr[v],rr[base],block)
                    conf=blockprob(rr[v].loc[rr[v].index>=CONF],rr[base].loc[rr[base].index>=CONF],block)
                    boots.append({'variant':v,'base':label,'cost_bps_per_side':bps,'block':block,'full_prob':full,'conf_prob':conf})
    pd.DataFrame(boots).to_csv(out/'bootstrap_block_sensitivity.csv',index=False)

    # Annual win counts against anchors, including 25bp primary stress.
    wins=[]
    for bps in (0,25):
        piv=adf[adf.cost_bps_per_side==bps].pivot(index='year',columns='variant',values='return').dropna()
        for v in ('HYBRID9T2I_E1','HYBRID8T3I_E1'):
            for label,base in anchors.items():
                wins.append({'variant':v,'base':label,'cost_bps_per_side':bps,'years':len(piv),
                             'win_years':int((piv[v]>piv[base]).sum()),'tie_years':int(np.isclose(piv[v],piv[base]).sum()),
                             'median_annual_delta':float((piv[v]-piv[base]).median()),'worst_annual_delta':float((piv[v]-piv[base]).min())})
    pd.DataFrame(wins).to_csv(out/'annual_win_summary.csv',index=False)

    summary={'method':'Final robustness only; no new signal conditions. Exact V38 sleeve; 9T2I1E and 8T3I1E vs A/B; turnover-derived per-side cost stress; annual/rolling/bootstrap sensitivity.',
             'coverage':diag,'cost_bps':COST_BPS,'bootstrap_blocks':BLOCKS,'production_changed':False,
             'cost_note':'Cost stress is applied from exact engine inferred executed share turnover at each open; it is a conservative post-execution NAV drag, not a rewrite of production execution sizing.'}
    (out/'summary.json').write_text(json.dumps(safe(summary),ensure_ascii=False,indent=2),encoding='utf-8')
    print('DONE_FINAL_ROBUSTNESS',flush=True)

if __name__=='__main__': main()
