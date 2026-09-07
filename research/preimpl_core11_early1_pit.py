from __future__ import annotations
import argparse, json, math
from pathlib import Path
from typing import Any
import numpy as np, pandas as pd
from research import audit_stock_nqsar_theme30_pit as audit
from research import run_stock_nqsar_theme30_pit_fast as fast  # patches vectorized PIT LOO
import build_v38_sleeve_live as sleeve

END=audit.ANALYSIS_END; DDV20=audit.DDV_ENTRY

def finite(x):
    try: return math.isfinite(float(x))
    except Exception: return False

def safe(x):
    if isinstance(x,dict): return {str(k):safe(v) for k,v in x.items()}
    if isinstance(x,(list,tuple)): return [safe(v) for v in x]
    if isinstance(x,(np.integer,)): return int(x)
    if isinstance(x,(np.floating,float)):
        z=float(x); return z if math.isfinite(z) else None
    if isinstance(x,pd.Timestamp): return str(x.date())
    return x

def pct(v,p): return v.where(p&v.notna()).rank(axis=1,pct=True,method='average')*100

def early_inputs(close,volume,bio):
    ddv=close*volume.rolling(20,min_periods=20).mean(); pool=(close>=5)&(ddv>=audit.DDV_POOL)
    ex=[s for s in bio if s in pool.columns]
    if ex: pool.loc[:,ex]=False
    r21=close/close.shift(21)-1; r42=close/close.shift(42)-1; r63=close/close.shift(63)-1
    q21,q42,q63=pct(r21,pool),pct(r42,pool),pct(r63,pool)
    high=pct(close/close.shift(1).rolling(63,min_periods=40).max(),pool)
    acc=pct(q21-q21.shift(20),pool); score=.5*q21+.25*high+.25*acc
    radar=(pool&((q21>=85)|(q42>=85)|(q63>=85))).fillna(False)
    fresh=(radar&~radar.shift(1).fillna(False)).fillna(False); active=fresh.astype(int).rolling(5,min_periods=1).max().astype(bool)
    return {'ddv':ddv,'score':score,'active':active}

def early_rows(d,e):
    z=pd.to_numeric(e['score'].loc[d].where(e['active'].loc[d]),errors='coerce').dropna().sort_values(ascending=False)
    out=[]
    for s,v in z.items():
        dv=e['ddv'].at[d,s]
        if finite(dv) and float(dv)>=DDV20:
            out.append({'ticker':str(s),'score':float(v),'rank':len(out)+1})
        if len(out)>=40: break
    return out

def core_rows(d,mx,theme,mode,weekly):
    elig=mx['eligible'].loc[d].fillna(False); rs=pd.to_numeric(mx['rs189'].loc[d],errors='coerce'); ddv=pd.to_numeric(mx['ddv'].loc[d],errors='coerce'); wb=mx['week_bull'].loc[d].fillna(False)
    ts=theme.get(d,{}); rows=[]
    for s in rs.index[elig&rs.notna()]:
        r=float(rs[s]); th=float(ts.get(str(s),50)); sc=.7*r+.3*th if mode=='ATTACK' else r
        rows.append({'ticker':str(s),'attack_watch_score':sc,'rs189':r,'daily_dollar_volume_m':float(ddv[s])/1e6 if finite(ddv[s]) else None,'week_bull':bool(wb[s]),'theme30':th})
    key=(lambda x:(x['week_bull'],x['attack_watch_score'],x['rs189'])) if weekly else (lambda x:(x['attack_watch_score'],x['rs189']))
    rows.sort(key=key,reverse=True)
    for i,r in enumerate(rows,1): r['final_rank']=i
    return rows

def companion(d,mx,theme,nq,e,weekly):
    color=str(nq.at[d,'nq_color']) if d in nq.index and pd.notna(nq.at[d,'nq_color']) else ''
    mode=audit.mode(color,mx['breadth'].get(d,np.nan))
    return {'asof':str(d.date()),'market':{'mode':mode},'candidates':core_rows(d,mx,theme,mode,weekly),
            'early1':{'status':'READY','entry_allowed_now':mode in {'ATTACK','SELECTIVE'},'candidates':early_rows(d,e)}}

def simulate(idx,mx,theme,nq,e,weekly):
    first=pd.Timestamp(idx[0]); state={'status':'READY','asof':str(first.date()),'cash':1.0,'positions':[],'pending':{'full_exits':[],'partial25':[],'entries':[]}}
    eq=[]; snapshots=[]
    for d0 in idx:
        d=pd.Timestamp(d0); c=companion(d,mx,theme,nq,e,weekly)
        state=sleeve.advance_normal(state,c,str(d.date()),mx['open'],mx['close'])
        eq.append((d,float(state['nav']))); snapshots.append((d,json.dumps(state.get('pending',{}),sort_keys=True,default=str)))
    s=pd.Series(dict(eq),dtype=float); r=s.pct_change(fill_method=None).dropna(); dd=s/s.cummax()-1
    pos=pd.DataFrame(state.get('positions',[])); pending=state.get('pending',{})
    return {'equity':s,'metrics':{'days':len(s),'total_return':float(s.iloc[-1]/s.iloc[0]-1),'mdd':float(dd.min()),'sharpe':float(r.mean()/r.std(ddof=1)*np.sqrt(252)) if len(r)>2 and r.std(ddof=1)>0 else None,
           'positions_end':len(pos),'pending_entries_end':len(pending.get('entries',[]))},'state_end':state,'pending_snapshots':snapshots}

def blockprob(a,b,block,reps=5000):
    x=(a.pct_change(fill_method=None)-b.pct_change(fill_method=None)).dropna().to_numpy(float)
    if len(x)<10:return None
    rng=np.random.default_rng(20260907+block); starts=np.arange(max(1,len(x)-block+1)); win=0
    for _ in range(reps):
        z=[]
        while len(z)<len(x):
            st=int(rng.choice(starts)); z.extend(x[st:st+block])
        win+=np.mean(z[:len(x)])>0
    return win/reps

def readiness(ohlcv,mx,idx):
    h,l,c=ohlcv['high'],ohlcv['low'],ohlcv['close']; wh,wl,wc=audit.period_ohlc_completed(h,l,c,'W-FRI',END)
    ok=((wh.notna()&wl.notna()&wc.notna()).sum()>=30); latest=pd.Timestamp(idx.max()); elig=mx['eligible'].loc[latest].fillna(False); syms=list(elig.index[elig])
    before=audit.period_ohlc_completed(h,l,c,'W-FRI',END-pd.Timedelta(days=1))[2]
    mask=c.index<=pd.Timestamp('2026-04-02'); hol=audit.period_ohlc_completed(h.loc[mask],l.loc[mask],c.loc[mask],'W-FRI',pd.Timestamp('2026-04-03'))[2]
    return {'eligible_now':len(syms),'eligible_30w_hlc_ready':sum(bool(ok.get(s,False)) for s in syms),'eligible_30w_hlc_coverage':sum(bool(ok.get(s,False)) for s in syms)/max(1,len(syms)),
            'normal_friday_release':bool(len(wc) and wc.index.max()==END and (not len(before) or before.index.max()<END)),
            'good_friday_release_with_ny_build_date':bool(len(hol) and hol.index.max()==pd.Timestamp('2026-04-02')),
            'live_requirement':'use adjusted High/Low/Close; release W-FRI by America/New_York build date, not stock asof; missing state => DATA REQUIRED'}
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--root',default='.'); ap.add_argument('--output',required=True); ap.add_argument('--batch-size',type=int,default=100); a=ap.parse_args(); root=Path(a.root); out=root/a.output; out.mkdir(parents=True,exist_ok=True)
    hist=json.loads((root/'v38-strict-loo-history.json').read_text()); snaps=hist.get('taxonomy_snapshots',[])
    if len(snaps)!=1 or str(snaps[0].get('effective_asof'))!=str(audit.PIT_EFFECTIVE.date()): raise RuntimeError('verified PIT taxonomy required')
    s2t=snaps[0]['s2t']; symbols,bio=audit.load_universe(root/'universe.csv'); end='2026-09-05'
    print('DOWNLOAD STOCK',flush=True); ohlcv,sd=audit.download_ohlcv(symbols,'2024-01-01',end,a.batch_size)
    if sd['coverage']<.85: raise RuntimeError(sd)
    print('DOWNLOAD THEME',flush=True); tc,td=audit.loo.download_adjusted_close(sorted(s2t),'2026-01-01',end,a.batch_size)
    if float(td.get('coverage') or 0)<.85: raise RuntimeError(td)
    print('BUILD INPUTS',flush=True); mx=audit.build_stock_inputs(ohlcv,bio,END); e=early_inputs(ohlcv['close'],ohlcv['volume'],bio)
    theme,pdgn=audit.theme_scores_by_date(tc,s2t,END,list(ohlcv['close'].columns)); nq=audit.market_nqsar('2026-03-01',end).reindex(mx['close'].index).ffill(limit=2)
    first=max(min(theme),audit.PIT_EFFECTIVE); idx=mx['close'].index[(mx['close'].index>=first)&(mx['close'].index<=END)]
    cur=simulate(idx,mx,theme,nq,e,False); wk=simulate(idx,mx,theme,nq,e,True)
    for name,res in [('CURRENT',cur),('WEEK_PRIORITY',wk)]: res['equity'].rename('equity').to_csv(out/f'equity_{name}.csv')
    metrics=[{'variant':'CURRENT',**cur['metrics']},{'variant':'WEEK_PRIORITY',**wk['metrics']}]; pd.DataFrame(metrics).to_csv(out/'metrics.csv',index=False)
    boot={f'block{b}':blockprob(wk['equity'],cur['equity'],b) for b in (1,3,5)}; ready=readiness(ohlcv,mx,idx)
    summary={'method':'production advance_normal; exact Core11+Early1/Selective3+Early1; Weekly Priority touches Core ranking only','stock':sd,'theme':td,'pit':pdgn,'metrics':metrics,'bootstrap_prob_weekly_outperform':boot,'readiness':ready,
             'production_invariants':['Early1 formula/rank untouched','Early D10 expiry/direct promotion untouched','Top12 then DDV20 no refill','existing exits untouched','no weekly exit']}
    (out/'summary.json').write_text(json.dumps(safe(summary),ensure_ascii=False,indent=2)); print('DONE',json.dumps(safe(summary),ensure_ascii=False),flush=True)
if __name__=='__main__': main()
