from __future__ import annotations

import argparse, json, math
from pathlib import Path
import numpy as np
import pandas as pd

from research import audit_stock_nqsar_theme30_pit as audit
from research import run_stock_nqsar_theme30_pit_fast as fast  # patches exact PIT Theme30 engine
from research import nqsar_centric_broad_scan as broad

VARIANTS = [
    'CURRENT',
    'WEEK_RS63',
    'WEEK_RS63_THEME30',
    'BLUEFIRST_RS63',
    'BLUEFIRST_RS63_THEME30',
    'WEEK_DAILY_NOT_RED_RS63',
]


def finite(x):
    try: return math.isfinite(float(x))
    except Exception: return False


def safe(x):
    if isinstance(x, dict): return {str(k): safe(v) for k,v in x.items()}
    if isinstance(x, (list,tuple)): return [safe(v) for v in x]
    if isinstance(x, np.integer): return int(x)
    if isinstance(x, (np.floating,float)):
        z=float(x); return z if math.isfinite(z) else None
    if isinstance(x,pd.Timestamp): return str(x.date())
    return x


def augment_nqsar_centric(mx, ohlcv, bio_excluded):
    close=ohlcv['close']; ddv=mx['ddv']
    sma50=close.rolling(50,min_periods=50).mean(); sma200=close.rolling(200,min_periods=200).mean()
    pool=(close>=5.0)&(ddv>=audit.DDV_POOL)
    ex=[s for s in bio_excluded if s in pool.columns]
    if ex: pool.loc[:,ex]=False
    struct=pool&(sma50>sma200)&(close>sma200)
    # RS63 already uses the DDV10 base pool in audit.build_stock_inputs.
    wh,wl,wc=audit.period_ohlc_completed(ohlcv['high'],ohlcv['low'],close,'W-FRI',audit.ANALYSIS_END)
    ws0=broad.exact_states(wh,wl,wc,30)
    ws=broad.to_daily(ws0,close.index).astype(np.int8)
    mx['nq_struct']=struct
    mx['week_state']=ws
    return mx


def custom_ranked(date, variant, mx, theme_scores, market_mode):
    if variant=='CURRENT':
        return _ORIG_RANKED(date,'CURRENT',mx,theme_scores,market_mode)
    struct=mx['nq_struct'].loc[date].fillna(False)
    wb=mx['week_bull'].loc[date].fillna(False)
    dr=mx['day_red'].loc[date].fillna(False)
    rs63=pd.to_numeric(mx['rs63'].loc[date],errors='coerce')
    ddv=pd.to_numeric(mx['ddv'].loc[date],errors='coerce')
    ws=mx['week_state'].loc[date]
    mask=struct&wb&rs63.notna()
    if variant=='WEEK_DAILY_NOT_RED_RS63': mask &= ~dr
    ts=theme_scores.get(date,{})
    rows=[]
    use_theme=variant in {'WEEK_RS63_THEME30','BLUEFIRST_RS63_THEME30'}
    bluefirst=variant in {'BLUEFIRST_RS63','BLUEFIRST_RS63_THEME30'}
    for s in rs63.index[mask]:
        r=float(rs63[s]); th=float(ts.get(str(s),50.0))
        score=.70*r+.30*th if (use_theme and market_mode=='ATTACK') else r
        rows.append({'symbol':str(s),'score':score,'rs63':r,'rs189':float(mx['rs189'].at[date,s]) if finite(mx['rs189'].at[date,s]) else None,
                     'theme30':th,'week_bull':True,'week_blue':bool(int(ws[s])==3),'day_not_red':not bool(dr[s]),
                     'ddv':float(ddv[s]) if finite(ddv[s]) else None})
    if bluefirst:
        rows.sort(key=lambda x:(x['week_blue'],x['score'],x['rs63']),reverse=True)
    else:
        rows.sort(key=lambda x:(x['score'],x['rs63']),reverse=True)
    top12=rows[:audit.N_PORT]
    liquid=[r for r in top12 if r['ddv'] is not None and r['ddv']>=audit.DDV_ENTRY]
    return liquid,top12


def blockprob(a,b,block=3,reps=20000,seed=20260907):
    x=(a.pct_change(fill_method=None)-b.pct_change(fill_method=None)).dropna().to_numpy(float)
    n=len(x)
    if n<5:return None
    block=max(1,min(block,n)); starts=np.arange(n-block+1); rng=np.random.default_rng(seed+block); wins=0
    for _ in range(reps):
        z=[]
        while len(z)<n:
            st=int(rng.choice(starts)); z.extend(x[st:st+block])
        wins += np.mean(z[:n])>0
    return wins/reps


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--root',default='.'); ap.add_argument('--output',required=True); ap.add_argument('--batch-size',type=int,default=100); args=ap.parse_args()
    root=Path(args.root); out=root/args.output; out.mkdir(parents=True,exist_ok=True)
    hist=json.loads((root/'v38-strict-loo-history.json').read_text(encoding='utf-8'))
    snaps=hist.get('taxonomy_snapshots',[])
    if len(snaps)!=1 or str(snaps[0].get('effective_asof'))!=str(audit.PIT_EFFECTIVE.date()): raise RuntimeError('unexpected PIT taxonomy')
    s2t=snaps[0]['s2t']; symbols,bio=audit.load_universe(root/'universe.csv'); end_excl='2026-09-05'
    print('DOWNLOAD STOCK',flush=True); ohlcv,stock_diag=audit.download_ohlcv(symbols,'2024-01-01',end_excl,args.batch_size)
    if stock_diag['coverage']<.85: raise RuntimeError(stock_diag)
    print('BUILD STOCK INPUTS',flush=True); mx=audit.build_stock_inputs(ohlcv,bio,audit.ANALYSIS_END); mx=augment_nqsar_centric(mx,ohlcv,bio)
    print('DOWNLOAD THEME',flush=True); theme_close,theme_diag=audit.loo.download_adjusted_close(sorted(s2t),'2026-01-01',end_excl,args.batch_size)
    if float(theme_diag.get('coverage') or 0)<.85: raise RuntimeError(theme_diag)
    print('BUILD THEME PIT',flush=True); theme_scores,pit_diag=audit.theme_scores_by_date(theme_close,s2t,audit.ANALYSIS_END,list(ohlcv['close'].columns))
    nq=audit.market_nqsar('2026-03-01',end_excl).reindex(mx['close'].index).ffill(limit=2)
    first=max(min(theme_scores),audit.PIT_EFFECTIVE)
    idx=mx['close'].index[(mx['close'].index>=first)&(mx['close'].index<=audit.ANALYSIS_END)]
    global _ORIG_RANKED
    _ORIG_RANKED=audit.ranked
    audit.ranked=custom_ranked
    results={}; metrics=[]; costrows=[]
    for v in VARIANTS:
        print('SIM',v,flush=True); r=audit.simulate(v,idx,mx,theme_scores,nq,0); results[v]=r; metrics.append({'variant':v,**r['metrics']})
        r['equity'].rename('equity').to_csv(out/f'equity_{v}.csv')
        if len(r['entries']): r['entries'].to_csv(out/f'entries_{v}.csv',index=False)
        if len(r['trades']): r['trades'].to_csv(out/f'trades_{v}.csv',index=False)
        for bps in (10,25):
            rr=audit.simulate(v,idx,mx,theme_scores,nq,bps); costrows.append({'variant':v,'cost_bps_per_side':bps,**rr['metrics']})
    _,sels=audit.forward_selection_stats(idx,mx,theme_scores,nq,VARIANTS); sels.to_csv(out/'selection_forward_summary.csv',index=False)
    boots=[]; base=results['CURRENT']['equity']
    for v in VARIANTS:
        row={'variant':v}
        for b in (1,3,5): row[f'vs_current_block{b}']=blockprob(results[v]['equity'],base,b)
        boots.append(row)
    # Direct Theme30 marginal comparisons and Blue-first marginal comparison.
    for a,b,label in [('WEEK_RS63_THEME30','WEEK_RS63','theme_on_week'),('BLUEFIRST_RS63_THEME30','BLUEFIRST_RS63','theme_on_blue'),('BLUEFIRST_RS63','WEEK_RS63','blue_vs_plain')]:
        row={'variant':label}
        for bl in (1,3,5): row[f'vs_current_block{bl}']=blockprob(results[a]['equity'],results[b]['equity'],bl)
        boots.append(row)
    pd.DataFrame(metrics).to_csv(out/'pit_metrics.csv',index=False); pd.DataFrame(costrows).to_csv(out/'pit_cost_stress.csv',index=False); pd.DataFrame(boots).to_csv(out/'pit_bootstrap.csv',index=False)
    summary={'method':'True-PIT Theme30 finalist audit; same 34-session PIT window; current Market Mode/current exits; Top12 on DDV10 then DDV20 no-refill','stock_coverage':stock_diag,'theme_coverage':theme_diag,'pit':pit_diag,'variants':VARIANTS,'note':'NQSAR-centric variants use structural trend + completed-week Bull and do not require RS63/RS189 >=85 unless implied by rank; CURRENT preserves production strict eligibility.'}
    (out/'summary.json').write_text(json.dumps(safe(summary),ensure_ascii=False,indent=2),encoding='utf-8')
    audit.ranked=_ORIG_RANKED

if __name__=='__main__': main()
