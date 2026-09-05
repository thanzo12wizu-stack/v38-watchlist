from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

SECTORS = ['XLB','XLC','XLE','XLF','XLI','XLK','XLP','XLRE','XLU','XLV','XLY']
H = (5,10,20,40,63)
COOLDOWN = 20


def eventize(g: pd.DataFrame, mask: pd.Series) -> pd.DataFrame:
    x=g.sort_values('date').copy(); m=mask.reindex(x.index).fillna(False).to_numpy(bool)
    prev=np.r_[False,m[:-1]]; enter=m & ~prev; out=[]; last=-10**9
    for i,ok in enumerate(enter):
        if ok and i-last>=COOLDOWN:
            out.append(x.iloc[i]); last=i
    return pd.DataFrame(out)


def cluster_ci(df,col,cluster,reps=5000,seed=11):
    z=df[[cluster,col]].dropna(); keys=z[cluster].unique()
    if len(keys)<4:return [None,None]
    groups={k:z.loc[z[cluster]==k,col].to_numpy(float) for k in keys}; rng=np.random.default_rng(seed); vals=[]
    for _ in range(reps):
        ks=rng.choice(keys,len(keys),replace=True); vals.append(np.concatenate([groups[k] for k in ks]).mean())
    return [float(v) for v in np.quantile(vals,[.025,.975])]


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--panel',type=Path,required=True); ap.add_argument('--output',type=Path,required=True); args=ap.parse_args(); args.output.mkdir(parents=True,exist_ok=True)
    p=pd.read_csv(args.panel); p['date']=pd.to_datetime(p.date).dt.normalize(); p=p.sort_values(['sector','date'])
    if 'internal_delta20' not in p: p['internal_delta20']=p.groupby('sector').internal_score.diff(20)
    tick=SECTORS+['SPY']; raw=yf.download(tick,start='2022-03-01',end='2026-09-05',auto_adjust=True,actions=False,progress=False,group_by='ticker',threads=False)
    def fld(t,f):
        if isinstance(raw.columns,pd.MultiIndex):
            if t in raw.columns.get_level_values(0): s=raw[t][f]
            else:s=raw.xs(t,axis=1,level=1)[f]
        else:s=raw[f]
        s.index=pd.to_datetime(s.index).tz_localize(None); return pd.to_numeric(s,errors='coerce')
    op=pd.DataFrame({t:fld(t,'Open') for t in tick}); cl=pd.DataFrame({t:fld(t,'Close') for t in tick})
    defs={
      'STRONG_DETERIORATION_W10':lambda g:(g.price_score>=70)&(g.internal_delta20<=-10),
      'STRONG_DETERIORATION_W20':lambda g:(g.price_score>=70)&(g.internal_delta20<=-20),
      'STRONG_DETERIORATION_W20_FLOWOUT':lambda g:(g.price_score>=70)&(g.internal_delta20<=-20)&(g.flow20_pct_aum<=0),
      'DISTRIBUTION_TRAP':lambda g:(g.price_score>=70)&(g.internal_score<50)&(g.flow20_pct_aum<=0),
    }
    events=[]
    for sec,g in p.groupby('sector',sort=False):
        g=g.copy()
        for name,fn in defs.items():
            e=eventize(g,fn(g));
            for _,r in e.iterrows():
                d=r.date; dates=cl.index[cl.index>d]
                if len(dates)<2 or sec not in op:return_day=None
                else:return_day=dates[0]
                if return_day is None or pd.isna(op.at[return_day,sec]):continue
                entry=float(op.at[return_day,sec]); spy_entry=float(op.at[return_day,'SPY']); rec={'condition':name,'sector':sec,'signal_date':d,'entry_date':return_day,'entry_price':entry}
                loc=cl.index.get_loc(return_day)
                for h in H:
                    end=min(len(cl)-1,loc+h); ec=float(cl.iloc[end][sec]) if pd.notna(cl.iloc[end][sec]) else np.nan; sp=float(cl.iloc[end]['SPY']) if pd.notna(cl.iloc[end]['SPY']) else np.nan
                    rec[f'ret_{h}']=ec/entry-1 if np.isfinite(ec) else np.nan; rec[f'excess_{h}']=(ec/entry-1)-(sp/spy_entry-1) if np.isfinite(ec) and np.isfinite(sp) else np.nan
                    path=pd.to_numeric(cl.iloc[loc:end+1][sec],errors='coerce').dropna()
                    rec[f'max_up_{h}']=path.max()/entry-1 if len(path) else np.nan; rec[f'max_dd_{h}']=path.min()/entry-1 if len(path) else np.nan
                events.append(rec)
    ev=pd.DataFrame(events); ev['signal_date']=pd.to_datetime(ev.signal_date); ev.to_csv(args.output/'sector_etf_exit_events.csv',index=False)
    report={'status':'SECTOR_ETF_EXIT_TIMING_RESEARCH','research_only':True,'execution':'signal close -> next open','conditions':{}}
    for name,g0 in ev.groupby('condition'):
        report['conditions'][name]={}
        for label,start in [('ALL_2022_PLUS','2022-04-18'),('CONFIRM_2024_PLUS','2024-01-01'),('RECENT_2025_PLUS','2025-01-01')]:
            g=g0[g0.signal_date>=pd.Timestamp(start)].copy(); z={'n':int(len(g))}
            g['event_block20']=(g.signal_date.map(lambda d: int((d-pd.Timestamp('2022-01-03')).days//28)))
            for h in (20,40,63):
                for c in (f'ret_{h}',f'excess_{h}',f'max_up_{h}',f'max_dd_{h}'):
                    x=pd.to_numeric(g[c],errors='coerce').dropna(); z[c]={'mean':float(x.mean()) if len(x) else None,'median':float(x.median()) if len(x) else None,'sector_ci95':cluster_ci(g,c,'sector',seed=100+h),'timeblock_ci95':cluster_ci(g,c,'event_block20',seed=200+h)}
                z[f'negative_abs_rate_{h}']=float((pd.to_numeric(g[f'ret_{h}'],errors='coerce')<0).mean()) if len(g) else None
                z[f'underperform_spy_rate_{h}']=float((pd.to_numeric(g[f'excess_{h}'],errors='coerce')<0).mean()) if len(g) else None
                z[f'drawdown_ge10_rate_{h}']=float((pd.to_numeric(g[f'max_dd_{h}'],errors='coerce')<=-.10).mean()) if len(g) else None
                z[f'upside_ge10_rate_{h}']=float((pd.to_numeric(g[f'max_up_{h}'],errors='coerce')>=.10).mean()) if len(g) else None
            report['conditions'][name][label]=z
    (args.output/'summary_sector_etf_exit_timing.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
