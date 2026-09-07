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
import build_v38_early1_live as earlylive

START=exact.START; END=exact.END; CONF=exact.CONF

# First 11 slots define the intended Core mix. Slot 12 is a same-universe spare
# that can only be used under the canonical Top12 -> DDV20 semantics.
PATTERNS={
    'HYBRID9T2I_E1':['T','T','T','T','I','T','T','T','T','I','T','T'],
    'HYBRID8T3I_E1':['T','T','T','I','T','T','T','I','T','T','I','T'],
    'HYBRID7T4I_E1':['T','T','I','T','T','I','T','T','I','T','I','T'],
}

SPECS=[
    ('WEEK_RS63_EARLY1','WEEK_RS63',True),
    ('TREND9_IGN3_CORE12','MIX9_IGN3',False),
    ('HYBRID9T2I_E1','HYBRID9T2I_E1',True),
    ('HYBRID8T3I_E1','HYBRID8T3I_E1',True),
    ('HYBRID7T4I_E1','HYBRID7T4I_E1',True),
    ('WEEK_RS63_CORE12','WEEK_RS63',False),
]


def safe(x):
    if isinstance(x,dict): return {str(k):safe(v) for k,v in x.items()}
    if isinstance(x,(list,tuple)): return [safe(v) for v in x]
    if isinstance(x,np.integer): return int(x)
    if isinstance(x,(np.floating,float)):
        z=float(x); return z if math.isfinite(z) else None
    if isinstance(x,pd.Timestamp): return str(x.date())
    return x


def hybrid_rows(d,m,kind):
    pool=m['pool'].loc[d].fillna(False); struct=m['struct'].loc[d].fillna(False); wb=m['wb'].loc[d].fillna(False)
    q63=pd.to_numeric(m['q'][63].loc[d],errors='coerce')
    ddv=pd.to_numeric(m['ddv'].loc[d],errors='coerce')
    trend=q63.where(pool&struct&wb).dropna().sort_values(ascending=False).index.tolist()
    ign=pd.to_numeric(m['early_score'].loc[d],errors='coerce').where(pool&wb&m['radar_active'].loc[d].fillna(False)).dropna().sort_values(ascending=False).index.tolist()
    lists={'T':trend,'I':ign}; ptr={'T':0,'I':0}; chosen=[]; sources=[]
    for src in PATTERNS[kind]:
        arr=lists[src]
        while ptr[src]<len(arr) and arr[ptr[src]] in chosen: ptr[src]+=1
        if ptr[src]>=len(arr): continue
        s=arr[ptr[src]]; ptr[src]+=1; chosen.append(s); sources.append(src)
    rows=[]
    for i,(s,src) in enumerate(zip(chosen[:12],sources[:12]),1):
        rows.append({'ticker':str(s),'final_rank':i,
                     'daily_dollar_volume_m':float(ddv.get(s,np.nan))/1e6 if pd.notna(ddv.get(s,np.nan)) else None,
                     'source':'IGNITION' if src=='I' else 'TREND',
                     'stock_rs63_pct':float(q63.get(s,np.nan)) if pd.notna(q63.get(s,np.nan)) else None})
    return rows


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--root',default='.'); ap.add_argument('--output',required=True); ap.add_argument('--batch-size',type=int,default=100)
    a=ap.parse_args(); root=Path(a.root); out=root/a.output; out.mkdir(parents=True,exist_ok=True)

    symbols,bio=audit.load_universe(root/'universe.csv')
    allowed=earlylive._industry_symbols(root/'industry_map.json'); early_excluded=set(bio)
    if allowed: early_excluded.update(set(symbols)-set(allowed))
    warm=str((START-pd.Timedelta(days=1600)).date()); end='2026-09-05'

    print('DOWNLOAD',flush=True); ohlcv,diag=audit.download_ohlcv(symbols,warm,end,a.batch_size)
    if diag['coverage']<.85: raise RuntimeError(diag)
    print('BUILD NORMAL CORE FEATURES',flush=True); m=broad.build_inputs(ohlcv,bio)
    print('BUILD PRODUCTION INPUTS',flush=True); mx=audit.build_stock_inputs(ohlcv,bio,END); e=pit.early_inputs(ohlcv['close'],ohlcv['volume'],early_excluded)
    nq=audit.market_nqsar(str((START-pd.Timedelta(days=120)).date()),end).reindex(mx['close'].index).ffill(limit=2)
    idx=mx['close'].index[(mx['close'].index>=START)&(mx['close'].index<=END)]

    orig_rank=exact.ranked_core_rows
    def patched_rank(d,mm,kind):
        if kind in PATTERNS: return hybrid_rows(d,mm,kind)
        return orig_rank(d,mm,kind)
    exact.ranked_core_rows=patched_rank

    print('BUILD LEADER EVENTS',flush=True); events,prior_low=exact.build_events(m,idx); print('EVENTS',len(events),flush=True)
    results={}; metrics=[]; leader=[]
    for name,kind,use_early in SPECS:
        print('SIM',name,flush=True)
        r=exact.simulate(idx,mx,nq,e,m,kind,use_early); results[name]=r
        sl=lng.slices(r['equity']); rec={'variant':name,**exact.event_counts(r)}
        for p,mm in sl.items():
            for k,v in mm.items(): rec[f'{p}_{k}']=v
        metrics.append(rec)
        r['equity'].rename('equity').to_csv(out/f'equity_{name}.csv')
        _,sm=exact.leader_summary(events,prior_low,idx,m,r,name); leader.append(sm)
        del r['held'],r['entry_px'],r['entry_i']

    anchors={'A_RS63_EARLY1':'WEEK_RS63_EARLY1','B_TREND9_IGN3':'TREND9_IGN3_CORE12'}
    boots=[]
    for name,r in results.items():
        row={'variant':name}
        for label,base_name in anchors.items():
            row[f'vs_{label}_full_block20']=lng.blockprob(r['equity'],results[base_name]['equity'])
            row[f'vs_{label}_conf_block20']=lng.blockprob(r['equity'],results[base_name]['equity'],CONF)
        boots.append(row)

    pd.DataFrame(metrics).to_csv(out/'metrics.csv',index=False)
    pd.DataFrame(boots).to_csv(out/'bootstrap.csv',index=False)
    pd.concat(leader,ignore_index=True).to_csv(out/'leader_capture_summary.csv',index=False)
    summary={
        'method':'Exact V38 sleeve three-role sensitivity: normal Core universe; Weekly Bull RS63 Trend; Bull-local fresh RS radar Ignition; original independent Early1; current Market NQSAR+Breadth/current exits/Top12 then DDV20 no-refill.',
        'patterns':PATTERNS,'specs':SPECS,'coverage':diag,'leader_events':len(events),'production_changed':False,
        'note':'Hybrid first 11 Core slots are 9T2I, 8T3I, or 7T4I; Early1 remains the original separate 1-slot sleeve.'
    }
    (out/'summary.json').write_text(json.dumps(safe(summary),ensure_ascii=False,indent=2),encoding='utf-8')
    exact.ranked_core_rows=orig_rank
    print('DONE_HYBRID',flush=True)

if __name__=='__main__': main()
