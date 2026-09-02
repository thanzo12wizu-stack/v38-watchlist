from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests
import yfinance as yf

import audit_inverse_etf_regime_scan as base

TRAIN_END = pd.Timestamp('2021-12-31')
HOLDOUT_START = pd.Timestamp('2022-01-03')
PRODUCTS = ['PSQ','QID','SQQQ']
HORIZONS = [3,5,10]
PERIODS = {
    'TRAIN_2016_2021': ('2016-01-04','2021-12-31'),
    'HOLDOUT_2022_2026': ('2022-01-03','2026-03-20'),
    '2016_2019': ('2016-01-04','2019-12-31'),
    '2020_2021': ('2020-01-01','2021-12-31'),
    '2022_2023': ('2022-01-03','2023-12-29'),
    '2024_2026': ('2024-01-02','2026-03-20'),
}

def safe(x: Any) -> Any:
    if isinstance(x, dict): return {str(k): safe(v) for k,v in x.items()}
    if isinstance(x, (list,tuple)): return [safe(v) for v in x]
    if isinstance(x, (np.integer,)): return int(x)
    if isinstance(x, (np.floating,float)):
        v=float(x); return v if np.isfinite(v) else None
    if isinstance(x, pd.Timestamp): return x.isoformat()
    return x

def fred_series(series_id: str, idx: pd.DatetimeIndex) -> pd.Series:
    url=f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}'
    r=requests.get(url, timeout=30)
    r.raise_for_status()
    from io import StringIO
    z=pd.read_csv(StringIO(r.text))
    z.columns=['date',series_id]
    z['date']=pd.to_datetime(z['date'], errors='coerce')
    z[series_id]=pd.to_numeric(z[series_id].replace('.',np.nan), errors='coerce')
    s=z.dropna(subset=['date']).set_index('date')[series_id].sort_index()
    s.index=base.norm_idx(s.index)
    return s.reindex(idx).ffill(limit=10)

def extra_market(idx: pd.DatetimeIndex, start: str, end: str) -> pd.DataFrame:
    warm=str((pd.Timestamp(start)-pd.Timedelta(days=500)).date())
    dl_end=str((pd.Timestamp(end)+pd.Timedelta(days=15)).date())
    symbols=['^VVIX','^SKEW','JNK','SHY','TIP','QQEW','XLK','XLU','KRE','XLF']
    raw=yf.download(symbols, start=warm, end=dl_end, auto_adjust=True, actions=False,
                    progress=False, threads=False, group_by='column')
    out=pd.DataFrame(index=idx)
    if raw.empty: return out
    if isinstance(raw.columns,pd.MultiIndex) and 'Close' in set(raw.columns.get_level_values(0)):
        c=raw['Close'].copy(); c.index=base.norm_idx(c.index); c=c.reindex(idx).ffill(limit=2)
    else:
        return out
    def add(name,sym):
        if sym in c.columns: out[name]=pd.to_numeric(c[sym], errors='coerce')
    add('vvix','^VVIX'); add('skew','^SKEW')
    for sym in ['JNK','SHY','TIP','QQEW','XLK','XLU','KRE','XLF']: add(sym.lower(),sym)
    if 'vvix' in out:
        out['vvix_chg5']=out.vvix.pct_change(5); out['vvix_pct252']=out.vvix.rolling(252,min_periods=126).rank(pct=True)
    if 'skew' in out:
        out['skew_chg5']=out.skew.pct_change(5); out['skew_pct252']=out.skew.rolling(252,min_periods=126).rank(pct=True)
    if {'jnk','shy'} <= set(out.columns): out['jnk_shy_mom20']=(out.jnk/out.shy).pct_change(20)
    if {'tip','shy'} <= set(out.columns): out['tip_shy_mom20']=(out.tip/out.shy).pct_change(20)
    if 'qqew' in out: out['qqew_ret20']=out.qqew.pct_change(20)
    if {'xlk','xlu'} <= set(out.columns): out['xlk_xlu_mom20']=(out.xlk/out.xlu).pct_change(20)
    if {'kre','xlf'} <= set(out.columns): out['kre_xlf_mom20']=(out.kre/out.xlf).pct_change(20)
    return out

def add_macro(feat: pd.DataFrame) -> tuple[pd.DataFrame,dict[str,str]]:
    idx=feat.index; status={}
    for sid in ['WALCL','WTREGEN','RRPONTSYD','NFCI','BAMLH0A0HYM2']:
        try:
            feat[sid.lower()]=fred_series(sid,idx); status[sid]='ok'
        except Exception as e:
            status[sid]=f'error:{type(e).__name__}'
    if {'walcl','wtregen','rrpontsyd'} <= set(feat.columns):
        feat['netliq_proxy']=feat.walcl-feat.wtregen-feat.rrpontsyd*1000.0
        d20=feat.netliq_proxy.diff(20)
        feat['netliq_chg20_z252']=(d20-d20.rolling(252,min_periods=126).mean())/d20.rolling(252,min_periods=126).std()
        feat['netliq_chg60']=feat.netliq_proxy.diff(60)
    if 'nfci' in feat: feat['nfci_chg4w']=feat.nfci-feat.nfci.shift(20)
    if 'bamlh0a0hym2' in feat:
        feat['hy_oas_chg5']=feat.bamlh0a0hym2.diff(5); feat['hy_oas_chg20']=feat.bamlh0a0hym2.diff(20)
        feat['hy_oas_pct252']=feat.bamlh0a0hym2.rolling(252,min_periods=126).rank(pct=True)
    return feat,status

def train_quantile(s: pd.Series,q: float) -> float:
    x=pd.to_numeric(s.loc[s.index<=TRAIN_END],errors='coerce').dropna()
    return float(x.quantile(q)) if len(x)>=100 else np.nan

def build_hypotheses(feat: pd.DataFrame) -> tuple[dict[str,pd.Series],dict[str,float]]:
    q={}
    for c in ['qqq_atr_dist50','qqq_rsi14','vvix_chg5','vvix_pct252','skew_pct252','hy_oas_chg20','netliq_chg20_z252']:
        if c in feat:
            q[c+'_q20']=train_quantile(feat[c],.20); q[c+'_q80']=train_quantile(feat[c],.80)
    below50=feat.qqq_dist_sma50<0; below200=feat.qqq_dist_sma200<0; slope50=feat.sma50_slope10<0
    momweak=(feat.qqq_ret5<0)&(feat.qqq_ret20<0); breadthweak=(feat.breadth50<50)&(feat.breadth_chg10<0)
    breadthflush=(feat.breadth50<40)&(feat.breadth_chg10<-5); creditweak=feat.hyg_lqd_mom20<0; nqsred=feat.nq_color.eq('Red')
    mcfall=feat.mc_chg5<-3; rateshock=feat.real10_chg5_z252>=.75; vixrise=feat.vix_chg5>.15; vixcontango=feat.vix_term_ratio<1.0
    fresh50=below50 & ~(feat.qqq_dist_sma50.shift(1)<0); fresh200=below200 & ~(feat.qqq_dist_sma200.shift(1)<0)
    failed_rally=below50 & (feat.qqq_ret5>0) & (feat.qqq_ret1<0) & feat.qqq_dist_ema21.between(-.015,.01)
    not_deep=(feat.qqq_rsi14>34)&(feat.qqq_atr_dist50>-2.0)&(feat.qqq_dd20>-.10)
    panic=(feat.panic_episode>0)|(feat.vix_term_ratio>1.05)|(feat.qqq_rsi14<=30)|(feat.qqq_atr_dist50<=-2.5)
    h={
      'FRESH50_BREADTH': fresh50 & breadthweak,
      'FRESH50_CREDIT': fresh50 & creditweak,
      'FRESH50_NQSAR': fresh50 & nqsred,
      'FRESH200_BREADTH': fresh200 & breadthweak,
      'TREND_MOM_BREADTH': below50 & slope50 & momweak & breadthweak,
      'TREND_MOM_CREDIT': below50 & slope50 & momweak & creditweak,
      'TREND_NQSAR': below50 & slope50 & nqsred,
      'TREND_NQSAR_CREDIT': below50 & slope50 & nqsred & creditweak,
      'TREND_MC_BREADTH': below50 & slope50 & mcfall & breadthweak,
      'TREND_RATE_SHOCK': below50 & slope50 & rateshock,
      'TREND_VIX_CONT': below50 & slope50 & vixrise & vixcontango,
      'FAILED_RALLY': failed_rally & slope50,
      'FAILED_RALLY_NQSAR': failed_rally & slope50 & nqsred,
      'BELOW200_NOTDEEP': below200 & slope50 & not_deep,
      'NQSAR_RED_ENTRY_NOTDEEP': feat.nq_red_entry.eq(1) & not_deep,
      'BREADTH_FLUSH_NOTPANIC': breadthflush & below50 & ~panic,
      'MC_BREADTH_NOTPANIC': mcfall & breadthweak & below50 & ~panic,
    }
    if 'netliq_chg20_z252' in feat:
        h['TREND_LIQ_CONTRACT']=below50 & slope50 & (feat.netliq_chg20_z252<=-.5)
        h['TREND_LIQ_NQSAR']=below50 & slope50 & nqsred & (feat.netliq_chg20_z252<=-.5)
    if 'nfci_chg4w' in feat: h['TREND_FCI_TIGHTEN']=below50 & slope50 & (feat.nfci_chg4w>0)
    if 'hy_oas_chg20' in feat:
        h['TREND_HYOAS_RISE']=below50 & slope50 & (feat.hy_oas_chg20>.20)
        h['FRESH50_HYOAS_RISE']=fresh50 & (feat.hy_oas_chg20>.20)
    if 'vvix_chg5' in feat:
        th=q.get('vvix_chg5_q80',np.nan)
        if np.isfinite(th): h['TREND_VVIX_IMPULSE']=below50 & slope50 & (feat.vvix_chg5>=th) & ~panic
    if 'qqew_ret20' in feat: h['TREND_EQUALWEIGHT_WEAK']=below50 & slope50 & (feat.qqew_ret20<feat.qqq_ret20)
    if 'jnk_shy_mom20' in feat: h['TREND_JUNK_WEAK']=below50 & slope50 & (feat.jnk_shy_mom20<0)
    if 'kre_xlf_mom20' in feat: h['TREND_REGIONAL_BANK_WEAK']=below50 & slope50 & (feat.kre_xlf_mom20<0)
    atr80=q.get('qqq_atr_dist50_q80',np.nan)
    if np.isfinite(atr80):
        h['EXTENDED_TOP_BREADTH_FADE']=(feat.qqq_atr_dist50>=atr80)&(feat.qqq_rsi14>=65)&(feat.breadth_chg10<0)
        h['EXTENDED_TOP_RATE']=(feat.qqq_atr_dist50>=atr80)&(feat.qqq_rsi14>=65)&rateshock
    return h,q

def masks(idx):
    return {k:pd.Series((idx>=pd.Timestamp(a))&(idx<=pd.Timestamp(b)),index=idx) for k,(a,b) in PERIODS.items()}

def event_screen(hyp: dict[str,pd.Series], outcomes: dict[str,pd.DataFrame], idx: pd.DatetimeIndex) -> pd.DataFrame:
    pm=masks(idx); rows=[]; seed=500000
    for name,cond in hyp.items():
        for prod in PRODUCTS:
            for horizon in HORIZONS:
                row={'hypothesis':name,'product':prod,'horizon':horizon}
                for period in PERIODS:
                    st=base.event_stats(cond,outcomes[prod][f'fwd{horizon}'],pm[period],idx,seed); seed+=1
                    for fld in ['n','mean','median','win','lo','hi','p_two','worst','best']: row[f'{period}_{fld}']=st.get(fld)
                rows.append(row)
    df=pd.DataFrame(rows)
    for period in ['TRAIN_2016_2021','HOLDOUT_2022_2026']: df[f'{period}_q']=base.bh_qvalues(df[f'{period}_p_two'])
    df['stable_sign']=(df.TRAIN_2016_2021_n>=12)&(df.HOLDOUT_2022_2026_n>=8)&(df.TRAIN_2016_2021_mean>0)&(df.HOLDOUT_2022_2026_mean>0)
    subcols=['2016_2019_mean','2020_2021_mean','2022_2023_mean','2024_2026_mean']
    df['positive_subperiods']=df[subcols].gt(0).sum(axis=1)
    df['min_train_hold']=df[['TRAIN_2016_2021_mean','HOLDOUT_2022_2026_mean']].min(axis=1)
    return df

def fixed_hold_returns(event: pd.Series, oo: pd.Series, hold: int, weight: float, cost_bp: float, guard: pd.Series | None=None) -> pd.Series:
    idx=oo.index; pos=np.zeros(len(idx),dtype=float); e=base.event_mask(event).to_numpy(bool)
    g=np.zeros(len(idx),dtype=bool) if guard is None else guard.fillna(False).to_numpy(bool); i=0
    while i<len(idx)-1:
        if e[i] and not g[i]:
            start=i+1; end=min(len(idx),start+hold); pos[start:end]=weight; i=end
        else: i+=1
    ps=pd.Series(pos,index=idx); r=ps*pd.to_numeric(oo,errors='coerce').fillna(0)
    entries=(ps>0)&~(ps.shift(1,fill_value=0)>0); r.loc[entries]-=weight*2*cost_bp/10000.0
    return r

def perf(r: pd.Series, mask: pd.Series) -> dict[str,float]:
    x=pd.to_numeric(r.loc[mask],errors='coerce').fillna(0)
    if len(x)==0:return {}
    nav=(1+x).cumprod(); yrs=len(x)/252; cagr=float(nav.iloc[-1]**(1/yrs)-1) if yrs>0 and nav.iloc[-1]>0 else np.nan
    dd=nav/nav.cummax()-1; vol=float(x.std()*np.sqrt(252)); sh=float(x.mean()/x.std()*np.sqrt(252)) if x.std()>0 else np.nan
    return {'cagr':cagr,'maxdd':float(dd.min()),'sharpe':sh,'final_nav':float(nav.iloc[-1]),'active_days':int((x!=0).sum())}

def strategy_screen(hyp, feat, outcomes, idx):
    pm=masks(idx); rows=[]; panic=(feat.panic_episode>0)|(feat.vix_term_ratio>1.05)|(feat.qqq_rsi14<=30)|(feat.qqq_atr_dist50<=-2.5)
    for name,event in hyp.items():
      for prod in PRODUCTS:
        oo=outcomes[prod]['oo_ret']
        for hold in [3,5,10]:
          for weight in [.15,.30]:
            if prod=='SQQQ' and weight>.15: continue
            for cost in [5,10]:
              for gname,guard in [('NONE',None),('PANIC',panic)]:
                r=fixed_hold_returns(event,oo,hold,weight,cost,guard)
                row={'hypothesis':name,'product':prod,'hold':hold,'weight':weight,'cost_bp_side':cost,'guard':gname}
                for period,mask in pm.items():
                    st=perf(r,mask)
                    for k,v in st.items(): row[f'{period}_{k}']=v
                rows.append(row)
    df=pd.DataFrame(rows)
    df['stable_positive']=(df.TRAIN_2016_2021_cagr>0)&(df.HOLDOUT_2022_2026_cagr>0)
    df['positive_subperiods']=df[['2016_2019_cagr','2020_2021_cagr','2022_2023_cagr','2024_2026_cagr']].gt(0).sum(axis=1)
    df['min_train_hold']=df[['TRAIN_2016_2021_cagr','HOLDOUT_2022_2026_cagr']].min(axis=1)
    return df

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--root',default='.'); ap.add_argument('--rates',required=True); ap.add_argument('--panic',required=True)
    ap.add_argument('--output',required=True); ap.add_argument('--start',default='2016-01-04'); ap.add_argument('--end',default='2026-03-20')
    ap.add_argument('--max-tickers',type=int,default=0); ap.add_argument('--batch-size',type=int,default=200); args=ap.parse_args()
    out=Path(args.output); out.mkdir(parents=True,exist_ok=True)
    feat,outcomes,diag=base.build_features(Path(args.root),Path(args.rates),Path(args.panic),args.start,args.end,args.max_tickers,args.batch_size)
    extra=extra_market(feat.index,args.start,args.end)
    for c in extra.columns: feat[c]=extra[c]
    feat,macro_status=add_macro(feat); hyp,thresholds=build_hypotheses(feat)
    ev=event_screen(hyp,outcomes,feat.index); st=strategy_screen(hyp,feat,outcomes,feat.index)
    ev.to_csv(out/'event_screen.csv',index=False); st.to_csv(out/'strategy_screen.csv',index=False); feat.to_csv(out/'feature_state_v2.csv.gz',compression='gzip')
    best_ev=ev[(ev.stable_sign)&(ev.positive_subperiods>=3)].sort_values(['min_train_hold','HOLDOUT_2022_2026_mean'],ascending=False).head(30)
    best_st=st[(st.stable_positive)&(st.positive_subperiods>=3)].sort_values(['min_train_hold','HOLDOUT_2022_2026_cagr'],ascending=False).head(30)
    summary={'status':'RESEARCH_ONLY_NO_PRODUCTION_CHANGE','diagnostics':diag,'macro_status':macro_status,'train_thresholds':thresholds,
      'hypotheses':list(hyp.keys()),'event_rows':len(ev),'strategy_rows':len(st),'stable_event_rows':int(ev.stable_sign.sum()),
      'robust_event_rows_3of4':int(((ev.stable_sign)&(ev.positive_subperiods>=3)).sum()),'stable_strategy_rows':int(st.stable_positive.sum()),
      'robust_strategy_rows_3of4':int(((st.stable_positive)&(st.positive_subperiods>=3)).sum()),'best_events':best_ev.to_dict('records'),'best_strategies':best_st.to_dict('records'),
      'mechanics':{'signal_timing':'signal-day close, entry next session open','thresholds':'all empirical quantiles frozen on 2016-2021 only',
      'products':'actual PSQ/QID/SQQQ daily-reset returns from adjusted opens','costs':'5/10 bp per side modeled as round-trip cost at each fixed-hold entry',
      'guards':'optional panic/deep-oversold skip on signal day','validation':'train/holdout plus four subperiod sign consistency; block-bootstrap/FDR on event study'}}
    (out/'summary_v2.json').write_text(json.dumps(safe(summary),ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(safe({k:v for k,v in summary.items() if k not in ['best_events','best_strategies']}),ensure_ascii=False,indent=2))
    print('BEST EVENTS'); print(best_ev.head(15).to_string(index=False)); print('BEST STRATEGIES'); print(best_st.head(15).to_string(index=False))

if __name__=='__main__': main()
