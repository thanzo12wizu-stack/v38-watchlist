from __future__ import annotations

import argparse
import io
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests
import yfinance as yf

TRAIN_END = pd.Timestamp('2021-12-31')
HOLDOUT_START = pd.Timestamp('2022-01-03')
PRODUCTS = ['PSQ', 'QID', 'SQQQ']
PERIODS = {
    'TRAIN_2016_2021': ('2016-01-04', '2021-12-31'),
    'HOLDOUT_2022_2026': ('2022-01-03', '2026-03-20'),
    '2022': ('2022-01-03', '2022-12-30'),
    '2023': ('2023-01-03', '2023-12-29'),
    '2024': ('2024-01-02', '2024-12-31'),
    '2025_2026': ('2025-01-02', '2026-03-20'),
}

FRED = {
    'WALCL': ('fed_assets', 2),
    'WTREGEN': ('tga', 1),
    'RRPONTSYD': ('rrp', 1),
    'WRESBAL': ('reserve_balances', 2),
    'NFCI': ('nfci', 3),
    'BAMLH0A0HYM2': ('hy_oas', 1),
    'BAMLC0A0CM': ('ig_oas', 1),
}
VOL_SYMBOLS = ['^VXN', '^VVIX', '^SKEW', '^VIX9D']
ETF_SYMBOLS = ['QQQ', 'PSQ', 'QID', 'SQQQ', 'QEW', 'HYG', 'LQD']


def norm_idx(idx) -> pd.DatetimeIndex:
    x = pd.to_datetime(idx)
    try:
        x = x.tz_localize(None)
    except TypeError:
        x = x.tz_convert(None)
    return pd.DatetimeIndex(x).normalize()


def safe(x: Any) -> Any:
    if isinstance(x, dict):
        return {str(k): safe(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [safe(v) for v in x]
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating, float)):
        v = float(x)
        return v if np.isfinite(v) else None
    if isinstance(x, pd.Timestamp):
        return x.isoformat()
    return x


def dl_one(symbol: str, start: str, end: str) -> pd.DataFrame:
    try:
        z = yf.download(symbol, start=start, end=end, auto_adjust=True, actions=False,
                        progress=False, threads=False)
    except Exception:
        return pd.DataFrame()
    if z is None or z.empty:
        return pd.DataFrame()
    if isinstance(z.columns, pd.MultiIndex):
        z.columns = z.columns.get_level_values(0)
    z = z.rename(columns={c: c.lower() for c in z.columns})
    z.index = norm_idx(z.index)
    return z.sort_index()


def fred_series(series: str, idx: pd.DatetimeIndex, lag_sessions: int) -> pd.Series:
    url = f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}'
    r = requests.get(url, timeout=45)
    r.raise_for_status()
    z = pd.read_csv(io.StringIO(r.text))
    dcol = 'DATE' if 'DATE' in z.columns else 'observation_date'
    z[dcol] = pd.to_datetime(z[dcol])
    valcol = [c for c in z.columns if c != dcol][0]
    s = pd.to_numeric(z[valcol], errors='coerce')
    s.index = norm_idx(z[dcol])
    s = s.sort_index().reindex(idx).ffill(limit=15)
    if lag_sessions:
        s = s.shift(lag_sessions)
    return s


def rolling_z(s: pd.Series, n: int = 252, minp: int = 126) -> pd.Series:
    mu = s.rolling(n, min_periods=minp).mean()
    sd = s.rolling(n, min_periods=minp).std()
    return (s - mu) / sd.replace(0, np.nan)


def pct_rank(s: pd.Series, n: int = 252, minp: int = 126) -> pd.Series:
    return s.rolling(n, min_periods=minp).rank(pct=True)


def build_extended(base_path: Path, start: str, end: str) -> tuple[pd.DataFrame, dict[str, pd.Series], dict[str, Any]]:
    base = pd.read_csv(base_path, compression='infer', parse_dates=['date']).set_index('date').sort_index()
    base.index = norm_idx(base.index)
    a0 = pd.Timestamp(start); a1 = pd.Timestamp(end)
    idx = base.index[(base.index >= a0) & (base.index <= a1)]
    base = base.reindex(idx).copy()
    warm = str((a0 - pd.Timedelta(days=500)).date())
    dl_end = str((a1 + pd.Timedelta(days=15)).date())
    market: dict[str, pd.DataFrame] = {}
    for sym in ETF_SYMBOLS + VOL_SYMBOLS:
        market[sym] = dl_one(sym, warm, dl_end)

    q = market['QQQ'].reindex(idx)
    qclose=q['close']; qopen=q['open']; qhigh=q['high']; qlow=q['low']; qvol=q['volume']
    ret=qclose.pct_change(); overnight=qopen/qclose.shift(1)-1.0; intraday=qclose/qopen-1.0
    tr_pct=(qhigh-qlow)/qclose; dollar_vol=(qclose*qvol).replace(0,np.nan)
    amihud=ret.abs()/dollar_vol*1e9; neg=ret.where(ret<0,0.0); pos=ret.where(ret>0,0.0)
    ext=pd.DataFrame(index=idx)
    ext['qqq_overnight5']=overnight.rolling(5).sum(); ext['qqq_intraday5']=intraday.rolling(5).sum()
    ext['qqq_overnight20']=overnight.rolling(20).sum(); ext['qqq_intraday20']=intraday.rolling(20).sum()
    ext['qqq_downside_rv10']=neg.rolling(10).std()*np.sqrt(252); ext['qqq_upside_rv10']=pos.rolling(10).std()*np.sqrt(252)
    ext['qqq_down_up_vol_ratio10']=ext.qqq_downside_rv10/ext.qqq_upside_rv10.replace(0,np.nan)
    ext['qqq_skew20']=ret.rolling(20).skew(); ext['qqq_range20']=tr_pct.rolling(20).mean(); ext['qqq_amihud20']=amihud.rolling(20).mean()
    ext['qqq_volume_z20']=(qvol-qvol.rolling(20).mean())/qvol.rolling(20).std()
    ext['qqq_downvol_share20']=qvol.where(ret<0,0.0).rolling(20).sum()/qvol.rolling(20).sum()
    ext['qqq_lower_close_share10']=((qclose-qlow)/(qhigh-qlow).replace(0,np.nan)).rolling(10).mean()
    ext['qqq_down_days10']=(ret<0).rolling(10).sum(); ext['qqq_bigdown_days20']=(ret<=-0.02).rolling(20).sum()
    ext['qqq_gapdown_vol20']=qvol.where(overnight<=-0.01,0.0).rolling(20).sum()/qvol.rolling(20).sum()

    for sym in ['QEW','HYG','LQD']:
        z=market.get(sym,pd.DataFrame())
        if not z.empty and 'close' in z.columns: market[sym]=z.reindex(idx)
    if not market['QEW'].empty:
        rr=market['QEW']['close']/qclose; ext['qew_qqq_mom5']=rr.pct_change(5); ext['qew_qqq_mom20']=rr.pct_change(20)
    if not market['HYG'].empty and not market['LQD'].empty:
        rr=market['HYG']['close']/market['LQD']['close']; ext['hyg_lqd_ext_mom5']=rr.pct_change(5); ext['hyg_lqd_ext_mom20']=rr.pct_change(20)

    diag_symbols={}
    for sym,prefix in [('^VXN','vxn'),('^VVIX','vvix'),('^SKEW','skew'),('^VIX9D','vix9d')]:
        z=market.get(sym,pd.DataFrame()); diag_symbols[sym]=bool(not z.empty and 'close' in z.columns)
        if z.empty or 'close' not in z.columns: continue
        s=z['close'].reindex(idx).ffill(limit=2); ext[prefix]=s; ext[f'{prefix}_chg5']=s.pct_change(5); ext[f'{prefix}_chg10']=s.pct_change(10); ext[f'{prefix}_pct252']=pct_rank(s)
    if 'vxn' in ext and 'vix' in base: ext['vxn_vix_ratio']=ext.vxn/pd.to_numeric(base.vix,errors='coerce')
    if 'vix9d' in ext and 'vix' in base: ext['vix9d_vix_ratio']=ext.vix9d/pd.to_numeric(base.vix,errors='coerce')

    fred_diag={}
    for series,(name,lag) in FRED.items():
        try:
            s=fred_series(series,idx,lag); fred_diag[series]=int(s.notna().sum()); ext[name]=s
            ext[f'{name}_chg5']=s.diff(5); ext[f'{name}_chg20']=s.diff(20)
            ext[f'{name}_chg5_z252']=rolling_z(ext[f'{name}_chg5']); ext[f'{name}_chg20_z252']=rolling_z(ext[f'{name}_chg20']); ext[f'{name}_pct252']=pct_rank(s)
        except Exception as e: fred_diag[series]=f'ERR:{type(e).__name__}'
    if 'hy_oas' in ext and 'ig_oas' in ext:
        ext['hy_ig_oas_spread']=ext.hy_oas-ext.ig_oas; ext['hy_ig_oas_spread_chg5']=ext.hy_ig_oas_spread.diff(5); ext['hy_ig_oas_spread_pct252']=pct_rank(ext.hy_ig_oas_spread)
    if all(c in ext for c in ['fed_assets','tga','rrp']):
        ext['net_liquidity_proxy']=ext.fed_assets-ext.tga-ext.rrp*1000.0
        ext['net_liquidity_chg20']=ext.net_liquidity_proxy.diff(20); ext['net_liquidity_chg20_z252']=rolling_z(ext.net_liquidity_chg20)

    feat=pd.concat([base,ext],axis=1)
    opens={p:market[p].reindex(idx)['open'].ffill(limit=1) for p in PRODUCTS}
    diag={'sessions':len(idx),'analysis_start':str(idx.min().date()),'analysis_end':str(idx.max().date()),'vol_symbols':diag_symbols,'fred_nonnull':fred_diag,'feature_count':int(feat.shape[1]),'extended_feature_count':int(ext.shape[1])}
    return feat,opens,diag


def train_quantile(s: pd.Series,q:float)->float:
    z=pd.to_numeric(s.loc[s.index<=TRAIN_END],errors='coerce').dropna(); return float(z.quantile(q)) if len(z) else float('nan')
def flag_low(feat,col,q):
    if col not in feat:return pd.Series(False,index=feat.index)
    return pd.to_numeric(feat[col],errors='coerce')<=train_quantile(feat[col],q)
def flag_high(feat,col,q):
    if col not in feat:return pd.Series(False,index=feat.index)
    return pd.to_numeric(feat[col],errors='coerce')>=train_quantile(feat[col],q)
def event_mask(cond):
    c=cond.fillna(False).astype(bool); return c&~c.shift(1,fill_value=False)
def fwd_open_return(opn,horizon): return opn.shift(-(horizon+1))/opn.shift(-1)-1.0

def simple_stats(vals):
    z=pd.to_numeric(vals,errors='coerce').dropna()
    if len(z)==0:return {'n':0,'mean':None,'median':None,'win':None,'worst':None,'best':None}
    return {'n':int(len(z)),'mean':float(z.mean()),'median':float(z.median()),'win':float((z>0).mean()),'worst':float(z.min()),'best':float(z.max())}


def make_family_flags(feat):
    f=pd.DataFrame(index=feat.index); thresholds={}
    def low(c,q=.33):
        thresholds[f'{c}_q{q}']=train_quantile(feat[c],q) if c in feat else np.nan; return flag_low(feat,c,q)
    def high(c,q=.67):
        thresholds[f'{c}_q{q}']=train_quantile(feat[c],q) if c in feat else np.nan; return flag_high(feat,c,q)
    f['trend']=(pd.to_numeric(feat.get('qqq_dist_sma200'),errors='coerce')<0)|low('sma50_slope10',.33)
    f['breadth']=(pd.to_numeric(feat.get('breadth50'),errors='coerce')<50)|low('breadth_chg10',.33)
    f['risk_rel']=low('qew_qqq_mom20',.33)|low('hyg_lqd_mom20',.33)
    f['credit']=high('hy_oas_pct252',.67)|high('hy_oas_chg5_z252',.67)|high('hy_ig_oas_spread_pct252',.67)
    f['vol']=high('vxn_chg5',.67)|high('vvix_chg5',.67)|(pd.to_numeric(feat.get('vix_term_ratio'),errors='coerce')>1.0)
    f['micro']=high('qqq_down_up_vol_ratio10',.67)|high('qqq_downvol_share20',.67)|high('qqq_bigdown_days20',.67)
    f['liquidity']=low('net_liquidity_chg20_z252',.33)|high('nfci_chg20_z252',.67)|high('tga_chg20_z252',.67)
    f['rates']=high('real10_chg5_z252',.67)|high('duration_shock_z5',.67)
    f['nqsar']=pd.to_numeric(feat.get('nq_red'),errors='coerce').fillna(0).astype(bool)
    c=pd.DataFrame(index=feat.index)
    c['deep_dd']=low('qqq_dd63',.20); c['oversold']=low('qqq_rsi14',.20)
    c['vol_extreme']=high('vix_pct252',.80)|high('vxn_pct252',.80)|high('vvix_pct252',.80)
    c['term_panic']=high('vix_term_ratio',.80)|high('vix9d_vix_ratio',.80)
    c['realized_extreme']=high('qqq_atr14_pct',.80)|high('qqq_downside_rv10',.80)
    c['panic_episode']=pd.to_numeric(feat.get('panic_episode'),errors='coerce').fillna(0).astype(bool)
    return f.fillna(False),c.fillna(False),thresholds


def screen_flags(flags,opens,horizons=(3,5,10,20)):
    rows=[]; train=flags.index<=TRAIN_END; hold=flags.index>=HOLDOUT_START
    for name in flags.columns:
        ev=event_mask(flags[name])
        for p,opn in opens.items():
            for h in horizons:
                out=fwd_open_return(opn,h); tr=simple_stats(out.loc[ev&train]); ho=simple_stats(out.loc[ev&hold])
                rows.append({'flag':name,'product':p,'horizon':h,**{f'train_{k}':v for k,v in tr.items()},**{f'hold_{k}':v for k,v in ho.items()}})
    return pd.DataFrame(rows)


def make_position(cont_score,cap_score,enter,exit_,cap_guard,max_weight):
    state=0.0; out=[]
    for d in cont_score.index:
        cs=float(cont_score.loc[d]) if pd.notna(cont_score.loc[d]) else 0.0; cp=float(cap_score.loc[d]) if pd.notna(cap_score.loc[d]) else 0.0
        guarded=cap_guard is not None and cp>=cap_guard
        if state<=0:
            if cs>=enter and not guarded:state=max_weight
        elif cs<=exit_ or guarded:state=0.0
        out.append(state)
    return pd.Series(out,index=cont_score.index,dtype=float)

def perf_stats(r):
    z=pd.to_numeric(r,errors='coerce').fillna(0.0); n=len(z)
    if n==0:return {'n':0}
    nav=(1+z).cumprod(); years=n/252.0; cagr=float(nav.iloc[-1]**(1/years)-1) if years>0 and nav.iloc[-1]>0 else np.nan
    dd=nav/nav.cummax()-1; vol=float(z.std()*np.sqrt(252)); sharpe=float(z.mean()/z.std()*np.sqrt(252)) if z.std()>0 else np.nan
    return {'n':n,'cagr':cagr,'maxdd':float(dd.min()),'ann_vol':vol,'sharpe':sharpe,'final_nav':float(nav.iloc[-1]),'worst_day':float(z.min()),'best_day':float(z.max())}


def strategy_grid(family,cap,opens):
    cont_base=family[['trend','breadth','risk_rel','credit','vol','micro','liquidity','rates']].sum(axis=1); cont_nq=cont_base+family['nqsar'].astype(int); cap_score=cap.sum(axis=1)
    rows=[]; periods=[]
    for score_name,score in [('broad8',cont_base),('broad8_plus_nqsar',cont_nq)]:
        for p in PRODUCTS:
            opn=opens[p]; oo=opn.shift(-1)/opn-1.0
            for w in [0.15,0.30,0.50]:
                for enter,exit_ in [(3,1),(4,2),(5,3),(6,3)]:
                    for guard in [None,4,3,2]:
                        pos=make_position(score,cap_score,enter,exit_,guard,w); eff=pos.shift(1).fillna(0.0); turnover=pos.diff().abs().shift(1).fillna(0.0)
                        for cost in [0,5,10]:
                            ret=eff*oo-turnover*(cost/10000.0); g='NONE' if guard is None else f'CAP{guard}'; name=f'{p}_{score_name}_W{int(w*100)}_E{enter}X{exit_}_{g}_C{cost}'
                            train_perf=None; hold_perf=None
                            for period,(a,b) in PERIODS.items():
                                pm=(ret.index>=pd.Timestamp(a))&(ret.index<=pd.Timestamp(b)); ps=perf_stats(ret.loc[pm])
                                rec={'strategy':name,'product':p,'score':score_name,'weight':w,'enter':enter,'exit':exit_,'cap_guard':guard,'cost_bp_side':cost,'period':period,'holding_days':int((eff.loc[pm]>0).sum()),'entries':int(((eff.loc[pm]>0)&~(eff.shift(1).loc[pm]>0)).sum()),**ps}; periods.append(rec)
                                if period=='TRAIN_2016_2021':train_perf=rec
                                if period=='HOLDOUT_2022_2026':hold_perf=rec
                            if train_perf and hold_perf: rows.append({**hold_perf,'train_cagr':train_perf['cagr'],'train_maxdd':train_perf['maxdd'],'train_sharpe':train_perf['sharpe'],'min_cagr':min(train_perf['cagr'],hold_perf['cagr']),'stable_positive':bool(train_perf['cagr']>0 and hold_perf['cagr']>0)})
    return pd.DataFrame(rows),pd.DataFrame(periods)


def ablation_grid(family,cap,opens):
    families=['trend','breadth','risk_rel','credit','vol','micro','liquidity','rates']; rows=[]; cap_score=cap.sum(axis=1)
    for removed in ['NONE']+families:
        use=[x for x in families if x!=removed]; score=family[use].sum(axis=1); enter=max(2,round(4*len(use)/8)); exit_=max(1,enter-2)
        for p in PRODUCTS:
            opn=opens[p]; oo=opn.shift(-1)/opn-1; pos=make_position(score,cap_score,enter,exit_,3,.30); r=pos.shift(1).fillna(0)*oo-pos.diff().abs().shift(1).fillna(0)*.0005
            for per,(a,b) in {'TRAIN':('2016-01-04','2021-12-31'),'HOLDOUT':('2022-01-03','2026-03-20')}.items():
                pm=(r.index>=pd.Timestamp(a))&(r.index<=pd.Timestamp(b)); rows.append({'removed':removed,'product':p,'period':per,'enter':enter,'exit':exit_,**perf_stats(r.loc[pm])})
    return pd.DataFrame(rows)


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--base',required=True); ap.add_argument('--output',required=True); ap.add_argument('--start',default='2016-01-04'); ap.add_argument('--end',default='2026-03-20'); args=ap.parse_args()
    out=Path(args.output); out.mkdir(parents=True,exist_ok=True)
    feat,opens,diag=build_extended(Path(args.base),args.start,args.end); family,cap,thresholds=make_family_flags(feat)
    flags=pd.concat([family.add_prefix('CONT_'),cap.add_prefix('CAP_')],axis=1); screen=screen_flags(flags,opens); strategies,periods=strategy_grid(family,cap,opens); ablation=ablation_grid(family,cap,opens)
    feat.reset_index(names='date').to_csv(out/'extended_feature_state.csv.gz',index=False,compression='gzip'); flags.reset_index(names='date').to_csv(out/'family_flags.csv',index=False); screen.to_csv(out/'family_event_screen.csv',index=False); strategies.to_csv(out/'extended_strategy_performance.csv',index=False); periods.to_csv(out/'extended_strategy_periods.csv',index=False); ablation.to_csv(out/'extended_ablation.csv',index=False)
    stable=strategies[strategies.stable_positive].sort_values(['min_cagr','sharpe'],ascending=False); best_hold=strategies.sort_values(['cagr','min_cagr'],ascending=False).head(30)
    best_events=screen[(screen.train_n>=12)&(screen.hold_n>=8)].copy(); best_events['robust_mean']=best_events[['train_mean','hold_mean']].min(axis=1); best_events=best_events.sort_values('robust_mean',ascending=False).head(30)
    summary={'status':'RESEARCH_ONLY_NO_PRODUCTION_CHANGE','mechanics':{'base':'Uses prior broad-scan feature artifact; adds microstructure, volatility surface, equal-weight, credit-spread, and lagged FRED liquidity features.','lookahead':'Signal at close; inverse position starts next open. FRED series use conservative 1-3 session lags.','split':'2016-2021 train; 2022-2026-03-20 holdout.','design':'Eight conceptual continuation families plus independent capitulation guard; OR within family prevents correlated double counting.','costs':'0/5/10 bp per side; actual PSQ/QID/SQQQ open prices preserve daily reset path.'},'diagnostics':diag,'thresholds':thresholds,'stable_strategy_count':int(len(stable)),'best_stable_strategies':stable.head(20).to_dict('records'),'best_holdout_strategies':best_hold.to_dict('records'),'best_family_events':best_events.to_dict('records')}
    with open(out/'summary.json','w') as f:json.dump(safe(summary),f,ensure_ascii=False,indent=2)
    print('===EXTENDED_INVERSE_SUMMARY==='); print(json.dumps(safe(summary),ensure_ascii=False,separators=(',',':'))); print('===END===')

if __name__=='__main__':main()
