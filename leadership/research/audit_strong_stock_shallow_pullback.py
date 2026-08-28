from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

import audit_market_rs189_context as ctx
import audit_rsi30_mc_nqsar as state_audit
import audit_rsi_reset_robust as market_base
import validate_rsi_divergence_strong as rsi_base
import validate_early_rotation as universe_base

DISC_END = pd.Timestamp('2021-12-31')
CONF_START = pd.Timestamp('2022-01-03')
COST = 5.0 / 10000.0
COOLDOWN = 20
TOUCH_WINDOW = 5
H = (5, 10, 20, 40)

METHODS = {
    'A10_RSI55': {'ema': 10, 'rsi': 55.0},
    'A10_RSI50': {'ema': 10, 'rsi': 50.0},
    'B21_RSI50': {'ema': 21, 'rsi': 50.0},
    'B21_RSI45': {'ema': 21, 'rsi': 45.0},
}


def safe(x):
    if isinstance(x, dict): return {str(k): safe(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)): return [safe(v) for v in x]
    if isinstance(x, np.integer): return int(x)
    if isinstance(x, (np.floating, float)):
        z = float(x); return z if math.isfinite(z) else None
    if isinstance(x, pd.Timestamp): return x.isoformat()
    return x


def pf(x: pd.Series) -> float | None:
    z = pd.to_numeric(x, errors='coerce').dropna()
    if z.empty: return None
    gp = float(z[z > 0].sum()); gl = float(-z[z < 0].sum())
    return None if gl <= 0 else gp / gl


def ci_cluster(df: pd.DataFrame, cluster: str, seed: int, reps: int = 2000):
    z = df[[cluster, 'entry_20']].dropna()
    if z.empty: return [None, None]
    a = z.groupby(cluster, observed=True).entry_20.mean().to_numpy(float)
    if len(a) < 2: return [None, None]
    rng = np.random.default_rng(seed)
    d = rng.choice(a, size=(reps, len(a)), replace=True).mean(axis=1)
    q = np.quantile(d, [0.025, 0.975])
    return [float(q[0]), float(q[1])]


def event_stats(g: pd.DataFrame, calendar: pd.DatetimeIndex, seed: int) -> dict:
    z = g.dropna(subset=['entry_20']).copy()
    if z.empty: return {'n': 0}
    r = pd.to_numeric(z.entry_20, errors='coerce')
    pos = pd.Series(np.arange(len(calendar)), index=calendar)
    p = pos.reindex(pd.to_datetime(z.signal_date)).to_numpy(float)
    good = np.isfinite(p); z = z.loc[good].copy(); p = p[good]
    z['block20'] = np.floor(p / 20.0).astype('int64')
    years = max((pd.to_datetime(z.signal_date).max() - pd.to_datetime(z.signal_date).min()).days / 365.2425, 1.0)
    return {
        'n': int(len(z)), 'signal_dates': int(z.signal_date.nunique()), 'symbols': int(z.symbol.nunique()),
        'sectors': int(z.sector.nunique()), 'signals_per_year': float(len(z) / years),
        'mean5': float(pd.to_numeric(z.entry_5, errors='coerce').mean()),
        'mean10': float(pd.to_numeric(z.entry_10, errors='coerce').mean()),
        'mean20': float(r.mean()), 'median20': float(r.median()), 'win20': float((r > 0).mean()),
        'pf20': pf(r), 'mae20': float(pd.to_numeric(z.mae_20, errors='coerce').mean()),
        'mfe20': float(pd.to_numeric(z.mfe_20, errors='coerce').mean()),
        'p10_20': float(r.quantile(0.10)), 'p90_20': float(r.quantile(0.90)),
        'date_ci95': ci_cluster(z, 'signal_date', seed),
        'block20_ci95': ci_cluster(z, 'block20', seed + 1000),
        'symbol_ci95': ci_cluster(z, 'symbol', seed + 2000),
        'sector_ci95': ci_cluster(z, 'sector', seed + 3000),
    }


def trade_outcomes(op, cl, hi, lo, sym: str, sig_i: int) -> dict:
    out = {}
    entry_i = sig_i + 1
    if entry_i >= len(cl.index): return out
    e = op.iat[entry_i, op.columns.get_loc(sym)] if sym in op.columns else np.nan
    if pd.isna(e) or e <= 0: return out
    for h in H:
        end_i = sig_i + h
        if end_i >= len(cl.index):
            out[f'entry_{h}'] = np.nan
            if h == 20:
                out['mae_20'] = np.nan; out['mfe_20'] = np.nan
            continue
        z = cl.iat[end_i, cl.columns.get_loc(sym)]
        out[f'entry_{h}'] = float(z / e - 1.0 - 2 * COST) if pd.notna(z) else np.nan
        if h == 20:
            ds = cl.index[entry_i:end_i + 1]
            hs = pd.to_numeric(hi.loc[ds, sym], errors='coerce').dropna()
            ls = pd.to_numeric(lo.loc[ds, sym], errors='coerce').dropna()
            out['mfe_20'] = float(hs.max() / e - 1.0) if len(hs) else np.nan
            out['mae_20'] = float(ls.min() / e - 1.0) if len(ls) else np.nan
    return out


def sector_map_for(close: pd.DataFrame, root: Path):
    imap = universe_base.read_industry_map(root / 'industry_map.json')
    return {s: (imap.get(s, ('UNMAPPED', 'UNMAPPED'))[0] or 'UNMAPPED') for s in close.columns}


def context_bins(z: pd.DataFrame) -> pd.DataFrame:
    x = z.copy()
    x['mc_bucket'] = np.select([
        x.mc < 20,
        (x.mc >= 20) & (x.mc < 50) & x.mc_up1.astype(bool),
        (x.mc >= 20) & (x.mc < 50),
        (x.mc >= 50) & x.mc_up1.astype(bool),
    ], ['LT20', '20_50_UP', '20_50_NOTUP', 'GE50_UP'], default='GE50_OTHER')
    x['sector_bucket'] = pd.cut(x.sector_rs63_pct, [-np.inf, 50, 60, 70, 80, np.inf],
                                labels=['LT50', '50_60', '60_70', '70_80', 'GE80'], right=False)
    x['rs189_bucket'] = pd.cut(x.rs189_signal, [-np.inf, 85, 90, 95, np.inf],
                               labels=['LT85', '85_90', '90_95', 'GE95'], right=False)
    return x


def generate_signals(market: dict, root: Path, asof: str) -> tuple[pd.DataFrame, dict]:
    cl, op, hi, lo = market['close'], market['open'], market['high'], market['low']
    cal = cl.index
    rsi = rsi_base.rsi(cl, 14)
    ema10 = cl.ewm(span=10, adjust=False).mean(); ema21 = cl.ewm(span=21, adjust=False).mean(); ema50 = cl.ewm(span=50, adjust=False).mean()
    ret63 = cl.pct_change(63, fill_method=None); ret189 = cl.pct_change(189, fill_method=None)
    rs63 = ret63.rank(axis=1, pct=True, method='average') * 100.0
    rs189 = ret189.rank(axis=1, pct=True, method='average') * 100.0
    sec_pct, _sec_breadth, sec_map = ctx.build_sector_state(cl, root)
    mc = state_audit.build_mc(asof)
    prev = cl.shift(1)
    tr = (hi - lo).combine((hi - prev).abs(), np.maximum).combine((lo - prev).abs(), np.maximum)
    atr = tr.rolling(14, min_periods=14).mean()

    rows = []
    pos = {pd.Timestamp(d): i for i, d in enumerate(cal)}
    for k, sym in enumerate(cl.columns, start=1):
        sec = sec_map.get(sym, 'UNMAPPED')
        sp = sec_pct[sec].reindex(cal) if sec in sec_pct.columns else pd.Series(np.nan, index=cal)
        c = cl[sym]; l = lo[sym]; rr = rsi[sym]; a = atr[sym]
        strong = (rs189[sym] >= 85) & (rs63[sym] >= 80) & (sp >= 50) & (c > ema21[sym]) & (ema21[sym] > ema50[sym])
        rise = rr > rr.shift(1)
        for method, cfg in METHODS.items():
            ma = ema10[sym] if cfg['ema'] == 10 else ema21[sym]
            touch = strong & (rr <= cfg['rsi']) & (l <= ma + 0.25 * a)
            signal_ok = strong & rise & (c >= ma)
            touch_idx = np.flatnonzero(touch.fillna(False).to_numpy())
            last_sig = -999
            scan_from = 0
            for ti in touch_idx:
                if ti < scan_from: continue
                end = min(ti + TOUCH_WINDOW, len(cal) - 2)
                found = None
                for j in range(ti, end + 1):
                    if bool(signal_ok.iat[j]): found = j; break
                if found is None: continue
                if found - last_sig < COOLDOWN: continue
                d = cal[found]; td = cal[ti]
                mcv = mc.mc.get(d, np.nan); mcu = mc.mc_up1.get(d, False)
                rec = {
                    'method': method, 'symbol': sym, 'sector': sec, 'touch_date': td,
                    'signal_date': d, 'entry_date': cal[found + 1], 'rsi_signal': float(rr.iat[found]),
                    'rsi_touch': float(rr.iat[ti]), 'rs63_signal': float(rs63[sym].iat[found]),
                    'rs189_signal': float(rs189[sym].iat[found]), 'sector_rs63_pct': float(sp.iat[found]),
                    'mc': float(mcv) if pd.notna(mcv) else np.nan, 'mc_up1': bool(mcu) if pd.notna(mcu) else False,
                    'ema_distance_atr': float((c.iat[found] - ma.iat[found]) / a.iat[found]) if pd.notna(a.iat[found]) and a.iat[found] > 0 else np.nan,
                }
                rec.update(trade_outcomes(op, cl, hi, lo, sym, found))
                rows.append(rec)
                last_sig = found; scan_from = found + COOLDOWN
        if k % 250 == 0 or k == len(cl.columns): print(f'SIGNAL_SCAN {k}/{len(cl.columns)}', flush=True)

    out = pd.DataFrame(rows)
    diag = {'symbols': int(len(cl.columns)), 'date_start': str(cal.min().date()), 'date_end': str(cal.max().date())}
    return out, diag


def attach_deep(deep_path: Path, market: dict, root: Path, asof: str) -> pd.DataFrame:
    z = pd.read_csv(deep_path, compression='gzip', parse_dates=['touch_date', 'signal_date', 'entry_date'])
    z = z[(z.rs_cut == 85) & (z.rsi_cut == 30)].copy()
    z['method'] = 'C_RSI30_MARKET'
    cl = market['close']; cal = cl.index
    ret63 = cl.pct_change(63, fill_method=None); ret189 = cl.pct_change(189, fill_method=None)
    rs63 = ret63.rank(axis=1, pct=True, method='average') * 100.0
    rs189 = ret189.rank(axis=1, pct=True, method='average') * 100.0
    ema21 = cl.ewm(span=21, adjust=False).mean(); ema50 = cl.ewm(span=50, adjust=False).mean()
    sec_pct, _b, sec_map = ctx.build_sector_state(cl, root)
    mc = state_audit.build_mc(asof)
    vals=[]
    for r in z.itertuples(index=False):
        d=pd.Timestamp(r.signal_date); s=str(r.symbol); sec=sec_map.get(s,'UNMAPPED')
        if d not in cal or s not in cl.columns: continue
        try: secv=float(sec_pct.at[d,sec])
        except Exception: secv=np.nan
        vals.append({
            'method':'C_RSI30_MARKET','symbol':s,'sector':sec,'touch_date':r.touch_date,'signal_date':d,'entry_date':r.entry_date,
            'rsi_signal':getattr(r,'rsi_signal',np.nan),'rsi_touch':np.nan,'rs63_signal':float(rs63.at[d,s]),
            'rs189_signal':float(rs189.at[d,s]),'sector_rs63_pct':secv,'mc':float(mc.mc.get(d,np.nan)),
            'mc_up1':bool(mc.mc_up1.get(d,False)),'ema_distance_atr':np.nan,
            'entry_5':getattr(r,'entry_5',np.nan),'entry_10':getattr(r,'entry_10',np.nan),'entry_20':getattr(r,'entry_20',np.nan),
            'entry_40':getattr(r,'entry_40',np.nan),'mae_20':getattr(r,'mae_20',np.nan),'mfe_20':getattr(r,'mfe_20',np.nan),
            'strong_signal': bool(rs63.at[d,s] >= 80 and secv >= 50 and cl.at[d,s] > ema21.at[d,s] and ema21.at[d,s] > ema50.at[d,s])
        })
    d = pd.DataFrame(vals)
    if d.empty: return d
    strong = d[d.strong_signal].copy(); strong['method']='C_RSI30_STRONG'
    return pd.concat([d.drop(columns=['strong_signal']), strong.drop(columns=['strong_signal'])], ignore_index=True)


def summarize_context(events: pd.DataFrame) -> pd.DataFrame:
    z = context_bins(events)
    rows=[]
    for period, start, end in [('DISCOVERY', pd.Timestamp('2016-01-04'), DISC_END), ('CONFIRM', CONF_START, pd.Timestamp('2026-06-30'))]:
        p=z[z.signal_date.between(start,end)]
        for method in sorted(p.method.unique()):
            q=p[p.method==method]
            for dim in ('mc_bucket','sector_bucket','rs189_bucket'):
                for val,g in q.groupby(dim, observed=True):
                    r=pd.to_numeric(g.entry_20,errors='coerce').dropna()
                    if len(r)<20: continue
                    rows.append({'period':period,'method':method,'dimension':dim,'bucket':str(val),'n':len(r),
                                 'mean20':float(r.mean()),'median20':float(r.median()),'win20':float((r>0).mean()),
                                 'pf20':pf(r),'mae20':float(pd.to_numeric(g.mae_20,errors='coerce').mean()),
                                 'p10_20':float(r.quantile(.10))})
    return pd.DataFrame(rows)


def gap_summary(events: pd.DataFrame, calendar: pd.DatetimeIndex) -> pd.DataFrame:
    pos={pd.Timestamp(d):i for i,d in enumerate(calendar)}; rows=[]
    for period,start,end in [('DISCOVERY',pd.Timestamp('2016-01-04'),DISC_END),('CONFIRM',CONF_START,pd.Timestamp('2026-06-30'))]:
        p=events[events.signal_date.between(start,end)]
        years=max((end-start).days/365.2425,1)
        for method,g in p.groupby('method',observed=True):
            gaps=[]
            for _s,sg in g.sort_values('signal_date').groupby('symbol',observed=True):
                a=[pos.get(pd.Timestamp(d)) for d in sg.signal_date if pd.Timestamp(d) in pos]
                gaps.extend([b-a for a,b in zip(a,a[1:])])
            rows.append({'period':period,'method':method,'signals':int(len(g)),'signals_per_year':float(len(g)/years),
                         'symbols':int(g.symbol.nunique()),'median_same_symbol_gap_sessions':float(np.median(gaps)) if gaps else np.nan})
    return pd.DataFrame(rows)


def runner_diagnostics(events: pd.DataFrame, market: dict, root: Path) -> tuple[pd.DataFrame,pd.DataFrame,pd.DataFrame]:
    cl,op=market['close'],market['open']; cal=cl.index
    ret63=cl.pct_change(63,fill_method=None); ret189=cl.pct_change(189,fill_method=None)
    rs63=ret63.rank(axis=1,pct=True,method='average')*100; rs189=ret189.rank(axis=1,pct=True,method='average')*100
    ema21=cl.ewm(span=21,adjust=False).mean(); ema50=cl.ewm(span=50,adjust=False).mean()
    sec_pct,_b,sec_map=ctx.build_sector_state(cl,root)
    ev_by={(m,s):g.sort_values('signal_date') for (m,s),g in events.groupby(['method','symbol'],observed=True)}
    rows=[]
    for k,s in enumerate(cl.columns,start=1):
        sec=sec_map.get(s,'UNMAPPED'); sp=sec_pct[sec].reindex(cal) if sec in sec_pct.columns else pd.Series(np.nan,index=cal)
        strong=(rs189[s]>=85)&(rs63[s]>=80)&(sp>=50)&(cl[s]>ema21[s])&(ema21[s]>ema50[s])
        starts=np.flatnonzero((strong & ~strong.shift(1,fill_value=False)).fillna(False).to_numpy())
        last=-999
        for i in starts:
            if i-last<63 or i+1>=len(cal): continue
            end=min(i+126,len(cal)-1); e=op.iat[i+1,op.columns.get_loc(s)] if s in op.columns else np.nan
            if pd.isna(e) or e<=0: continue
            mx=float(pd.to_numeric(cl[s].iloc[i+1:end+1],errors='coerce').max()/e-1)
            rec={'symbol':s,'sector':sec,'episode_start':cal[i],'forward126_max':mx,'period':'DISCOVERY' if cal[i]<=DISC_END else 'CONFIRM'}
            for method in sorted(events.method.unique()):
                g=ev_by.get((method,s))
                hit=None
                if g is not None:
                    cand=g[(g.signal_date>=cal[i])&(g.signal_date<=cal[min(i+63,len(cal)-1)])]
                    if not cand.empty: hit=pd.Timestamp(cand.iloc[0].signal_date)
                rec[f'{method}_days']=np.nan if hit is None else int(cal.get_loc(hit)-i)
            rows.append(rec); last=i
        if k%500==0 or k==len(cl.columns): print(f'RUNNER_SCAN {k}/{len(cl.columns)}',flush=True)
    epi=pd.DataFrame(rows)
    cov=[]
    if not epi.empty:
        for period in ('DISCOVERY','CONFIRM'):
            p=epi[epi.period==period]
            for thr in (.50,.80,1.00):
                q=p[p.forward126_max>=thr]
                for method in sorted(events.method.unique()):
                    col=f'{method}_days'; cov.append({'period':period,'runner_threshold':thr,'method':method,'episodes':len(q),
                        'covered_63d':int(q[col].notna().sum()) if col in q else 0,
                        'coverage_rate':float(q[col].notna().mean()) if len(q) and col in q else np.nan,
                        'median_days_to_entry':float(q[col].dropna().median()) if len(q) and col in q and q[col].notna().any() else np.nan})
    examples=pd.concat([epi[epi.period=='CONFIRM'].nlargest(25,'forward126_max'),epi[epi.symbol=='SNDK']],ignore_index=True).drop_duplicates(['symbol','episode_start']) if not epi.empty else epi
    return epi,pd.DataFrame(cov),examples


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--root',default='.'); ap.add_argument('--deep-trades',required=True); ap.add_argument('--output',required=True); ap.add_argument('--asof',default='2026-08-28'); args=ap.parse_args()
    root=Path(args.root); out=Path(args.output); out.mkdir(parents=True,exist_ok=True)
    market=market_base.rebuild_market(root,'2016-01-04','2026-06-30',6000,75,3)
    shallow,diag=generate_signals(market,root,args.asof)
    deep=attach_deep(Path(args.deep_trades),market,root,args.asof)
    events=pd.concat([shallow,deep],ignore_index=True,sort=False); events['signal_date']=pd.to_datetime(events.signal_date); events['entry_date']=pd.to_datetime(events.entry_date)
    events.to_csv(out/'event_rows.csv.gz',index=False,compression='gzip')
    rows=[]; cal=market['close'].index
    for pidx,(period,start,end) in enumerate([('DISCOVERY',pd.Timestamp('2016-01-04'),DISC_END),('CONFIRM',CONF_START,pd.Timestamp('2026-06-30'))]):
        for midx,(method,g) in enumerate(events[events.signal_date.between(start,end)].groupby('method',observed=True)):
            rows.append({'period':period,'method':method,**event_stats(g,cal,2800+pidx*100+midx)})
    summary=pd.DataFrame(rows); summary.to_csv(out/'event_summary.csv',index=False)
    context=summarize_context(events); context.to_csv(out/'context_summary.csv',index=False)
    gaps=gap_summary(events,cal); gaps.to_csv(out/'opportunity_summary.csv',index=False)
    epi,cov,examples=runner_diagnostics(events,market,root); cov.to_csv(out/'runner_coverage.csv',index=False); examples.to_csv(out/'runner_examples.csv',index=False)
    result={'status':'STRONG_STOCK_SHALLOW_PULLBACK_AUDIT','research_only':True,
            'definitions':{'strong':'daily RS189 percentile>=85, RS63 percentile>=80, sector RS63 percentile>=50, close>EMA21>EMA50',
                           'A10':'touch low<=EMA10+0.25ATR with RSI threshold; first RSI rise within 5 sessions while strong and close>=EMA10; next-open',
                           'B21':'touch low<=EMA21+0.25ATR with RSI threshold; first RSI rise within 5 sessions while strong and close>=EMA21; next-open',
                           'deep':'existing market-wide RS189>=85 + RSI30 reset/rise artifact; STRONG variant also applies signal-date strong filter',
                           'cooldown':'20 sessions per symbol per shallow method','cost':'5 bps each side','hold':'20 sessions primary'},
            'download':market.get('diag',{}),'signal_scan':diag,'methods':summary.to_dict('records'),
            'limitations':['Current-universe/current-classification survivorship bias remains.','2022+ is confirmation, not pristine untouched OOS.','Runner coverage uses future 126d max return only as retrospective diagnostic, never as an entry input.','No individual-stock tax model.']}
    (out/'summary.json').write_text(json.dumps(safe(result),ensure_ascii=False,indent=2),encoding='utf-8')
    print(summary.to_string(index=False),flush=True); print(cov.to_string(index=False),flush=True); print(json.dumps(safe(result),ensure_ascii=False,indent=2),flush=True)

if __name__=='__main__': main()
