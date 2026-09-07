from __future__ import annotations
import argparse,json
from pathlib import Path
import numpy as np,pandas as pd
from research import audit_stock_nqsar_theme30_pit as audit
from research import preimpl_core11_early1_pit as pit

START=pd.Timestamp('2016-01-04'); END=pd.Timestamp('2026-09-04'); CONF=pd.Timestamp('2022-01-03')

def metrics(eq):
    e=pd.to_numeric(eq,errors='coerce').dropna(); r=e.pct_change(fill_method=None).dropna(); dd=e/e.cummax()-1; years=max(len(r)/252,1/252)
    return {'n':len(e),'total_return':float(e.iloc[-1]/e.iloc[0]-1),'cagr':float((e.iloc[-1]/e.iloc[0])**(1/years)-1),'mdd':float(dd.min()),'sharpe':float(r.mean()/r.std(ddof=1)*np.sqrt(252)) if len(r)>2 and r.std(ddof=1)>0 else None}
def slices(eq):
    return {'full':metrics(eq),'discovery_2016_2021':metrics(eq.loc[eq.index<'2022-01-01']),'confirmation_2022_plus':metrics(eq.loc[eq.index>=CONF]),
            '2016_2019':metrics(eq.loc[eq.index<'2020-01-01']),'2020_2021':metrics(eq.loc[(eq.index>='2020-01-01')&(eq.index<'2022-01-01')]),
            '2022_2023':metrics(eq.loc[(eq.index>='2022-01-01')&(eq.index<'2024-01-01')]),'2024_plus':metrics(eq.loc[eq.index>='2024-01-01'])}
def blockprob(a,b,start=None,block=20,reps=5000):
    if start is not None: a,b=a.loc[a.index>=start],b.loc[b.index>=start]
    x=(a.pct_change(fill_method=None)-b.pct_change(fill_method=None)).dropna().to_numpy(float)
    rng=np.random.default_rng(20260907+block+(0 if start is None else 100)); starts=np.arange(max(1,len(x)-block+1)); win=0
    for _ in range(reps):
        z=[]
        while len(z)<len(x):
            st=int(rng.choice(starts)); z.extend(x[st:st+block])
        win+=np.mean(z[:len(x)])>0
    return win/reps
def pending_counts(res):
    out={'CORE':0,'EARLY':0,'promotions':0}
    for _,text in res['pending_snapshots']:
        p=json.loads(text)
        for e in p.get('entries',[]): out[str(e.get('sleeve') or 'CORE')]=out.get(str(e.get('sleeve') or 'CORE'),0)+1
        out['promotions']+=len(p.get('promotions',[]))
    return out
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--root',default='.'); ap.add_argument('--output',required=True); ap.add_argument('--batch-size',type=int,default=100); a=ap.parse_args(); root=Path(a.root); out=root/a.output; out.mkdir(parents=True,exist_ok=True)
    symbols,bio=audit.load_universe(root/'universe.csv'); warm=str((START-pd.Timedelta(days=1600)).date()); end='2026-09-05'
    print('LONG DOWNLOAD',flush=True); ohlcv,diag=audit.download_ohlcv(symbols,warm,end,a.batch_size)
    if diag['coverage']<.85: raise RuntimeError(diag)
    print('LONG INPUTS',flush=True); mx=audit.build_stock_inputs(ohlcv,bio,END); early=pit.early_inputs(ohlcv['close'],ohlcv['volume'],bio)
    nq=audit.market_nqsar(str((START-pd.Timedelta(days=90)).date()),end).reindex(mx['close'].index).ffill(limit=2)
    idx=mx['close'].index[(mx['close'].index>=START)&(mx['close'].index<=END)]; cov=float(nq.loc[idx,'nq_color'].notna().mean())
    if cov<.95: raise RuntimeError(f'NQ coverage {cov}')
    # No historical PIT Theme taxonomy exists. Empty Theme means neutral 50, preserving RS189 order and isolating Core Weekly x Early1 interaction.
    theme={}
    cur=pit.simulate(idx,mx,theme,nq,early,False); wk=pit.simulate(idx,mx,theme,nq,early,True)
    cur['equity'].rename('equity').to_csv(out/'equity_CURRENT.csv'); wk['equity'].rename('equity').to_csv(out/'equity_WEEK_PRIORITY.csv')
    summary={'method':'long-history controlled interaction test: production Core11+Early1 slots/exits via advance_normal; Core ranking RS189-only; Weekly Priority touches Core only; current-universe survivorship applies',
             'universe':diag,'market_nqsar_coverage':cov,'CURRENT':slices(cur['equity']),'WEEK_PRIORITY':slices(wk['equity']),
             'bootstrap_prob_weekly_outperform':{'full_block20':blockprob(wk['equity'],cur['equity']),'confirmation_2022_plus_block20':blockprob(wk['equity'],cur['equity'],CONF)},
             'pending_event_counts':{'CURRENT':pending_counts(cur),'WEEK_PRIORITY':pending_counts(wk)},
             'invariants':['Early1 unchanged','Core11/3 plus Early1 one slot','direct promotion and D10 expiry use production code','Top12 then DDV20 no refill','no weekly exit']}
    (out/'summary.json').write_text(json.dumps(pit.safe(summary),ensure_ascii=False,indent=2)); print('DONE_LONG',json.dumps(pit.safe(summary),ensure_ascii=False),flush=True)
if __name__=='__main__':main()
