from __future__ import annotations
from pathlib import Path
import json, numpy as np, pandas as pd
import yfinance as yf
from research import tqqq_backtest_once as bt

print('\n=== STAGE54 IMPLEMENTATION READINESS AUDIT ===',flush=True)

# 1) MC57 coverage/PIT audit. compute_mc returns the exact research score plus number of available ETFs.
mc,count=bt.compute_mc()
count=pd.Series(count).dropna().astype(float); count.index=pd.to_datetime(count.index)
rows=[]
for y,g in count.groupby(count.index.year):
    rows.append({'year':int(y),'n_days':int(len(g)),'count_min':float(g.min()),'count_median':float(g.median()),'count_max':float(g.max()),'coverage_median_pct':float(g.median()/57*100)})
COV=pd.DataFrame(rows); COV.to_csv('tqqq_stage54_mc57_coverage.csv',index=False)
first50=count[count>=50].index.min() if (count>=50).any() else pd.NaT
first57=count[count>=57].index.min() if (count>=57).any() else pd.NaT
MC_AUDIT={'universe_definition':'current fixed list of 57 non-levered ETFs; each date averages only ETFs available on that date',
          'pit_indicator_math':True,'historical_universe_membership_pit':False,'delisted_etfs_included':False,
          'survivorship_selection_risk':'present: current 57-name universe is projected backward and delisted/historical alternatives are not reconstructed',
          'first_date_50plus':None if pd.isna(first50) else str(first50.date()),'first_date_57':None if pd.isna(first57) else str(first57.date()),
          '2011_median_count':float(COV.loc[COV.year==2011,'count_median'].iloc[0]) if (COV.year==2011).any() else None,
          '2026_median_count':float(COV.loc[COV.year==2026,'count_median'].iloc[0]) if (COV.year==2026).any() else None,
          'verdict':'LIMITED_PIT: calculations are backward-looking, but the ETF universe itself is not point-in-time/survivorship-clean.'}

# 2) NQSAR audit: production truth is sar_state.txt (TradingView/Pipedream), while research history is reconstructed proxy.
prod=Path('sar_state.txt').read_text().strip() if Path('sar_state.txt').exists() else ''
prod_color=None; prod_asof=None
try:
    j=json.loads(prod); prod_color=j.get('color'); prod_asof=j.get('asof')
except Exception:
    if ',' in prod:
        prod_asof,prod_color=[x.strip() for x in prod.split(',',1)]
# reproduce the research proxy current state for a one-date sanity check; this does NOT validate history.
def psar(h,l,step=.02,mx=.08):
    h=np.asarray(h,float); l=np.asarray(l,float); n=len(h); s=np.zeros(n); bull=True; af=step; ep=l[0]; s[0]=l[0]
    for i in range(1,n):
        s[i]=s[i-1]+af*(ep-s[i-1])
        if bull:
            if l[i]<s[i]: bull=False; s[i]=ep; ep=l[i]; af=step
            elif h[i]>ep: ep=h[i]; af=min(af+step,mx)
        else:
            if h[i]>s[i]: bull=True; s[i]=ep; ep=h[i]; af=step
            elif l[i]<ep: ep=l[i]; af=min(af+step,mx)
    return s
def rsi(c,n=14):
    x=pd.Series(c,dtype=float); d=x.diff(); u=d.clip(lower=0); dn=(-d).clip(lower=0); au=u.ewm(alpha=1/n,adjust=False,min_periods=n).mean(); ad=dn.ewm(alpha=1/n,adjust=False,min_periods=n).mean(); rs=au/ad.replace(0,np.nan); y=100-100/(1+rs); return y.where(ad.ne(0),100.).to_numpy()
def proxy_colors(nq):
    C=nq.Close.astype(float).to_numpy(); H=nq.High.astype(float).to_numpy(); L=nq.Low.astype(float).to_numpy(); S=psar(H,L); E=pd.Series(C).ewm(span=21,adjust=False).mean().to_numpy(); R=rsi(C); a=C>S
    st='Green' if a[0] else 'Yellow'; up=dn=99; prev=None; out=[]
    for i in range(len(C)):
        up=0 if i>0 and a[i] and not a[i-1] else up+1; dn=0 if i>0 and (not a[i]) and a[i-1] else dn+1; ri=float(R[i]) if np.isfinite(R[i]) else 50.; dr=ri-prev if prev is not None else 0.
        if a[i]: st=('Green' if C[i]<E[i] else 'Blue') if st=='Blue' else ('Blue' if ri>52 and up>=2 and dr<=3 else 'Green')
        else: st=('Yellow' if ri>50 else 'Red') if st=='Red' else ('Red' if ri<47 and dn>=2 and dr>=-3 else 'Yellow')
        prev=ri; out.append(st)
    return out
proxy_now=None
try:
    nq=bt.dl_one('NQ=F','2024-01-01'); proxy_now=proxy_colors(nq)[-1]
except Exception: pass
NQ_AUDIT={'production_authority':'sar_state.txt from TradingView->Pipedream; local TradingView export is fallback',
          'production_asof':prod_asof,'production_color':prod_color,'research_history':'PSAR(0.02/0.08)+EMA21+Wilder RSI14 reconstructed proxy on Yahoo NQ=F',
          'research_proxy_latest':proxy_now,'latest_match':None if prod_color is None or proxy_now is None else bool(str(prod_color).lower()==str(proxy_now).lower()),
          'historical_exact_match_rate':None,'reason_no_historical_match_rate':'No committed historical TradingView NQ color export is present on this research branch; sar_state.txt is only a current snapshot.',
          'verdict':'PROXY_NOT_PRODUCTION_TRUTH: keep NQSAR as a proxy caveat in historical backtests until authoritative color history is archived.'}

# 3) 4H data route/freshness. Static 5m source + recent Yahoo 1h bridge.
HIST_URL='https://raw.githubusercontent.com/lvrusu/QQQ_price_data/main/QQQ5m_Ext_J_23_to_Mar_20a_2026.csv'
static_end=None; static_status='unavailable'
try:
    xs=pd.read_csv(HIST_URL,usecols=['ds']); ds=pd.to_datetime(xs.ds,errors='coerce').dropna(); static_end=str(ds.max()); static_status='ok'
except Exception as exc: static_status=type(exc).__name__
LIVE={'status':'unavailable'}
try:
    z=yf.download('QQQ',period='729d',interval='1h',auto_adjust=True,prepost=False,progress=False,threads=False)
    if len(z):
        ix=pd.DatetimeIndex(z.index); LIVE={'status':'ok','first':str(ix.min()),'last':str(ix.max()),'n_bars':int(len(z))}
except Exception as exc: LIVE={'status':type(exc).__name__}
bridge=False
if static_end and LIVE.get('status')=='ok':
    try:
        a=pd.Timestamp(static_end); b=pd.Timestamp(LIVE['first']);
        if a.tzinfo is not None: a=a.tz_convert(None)
        if b.tzinfo is not None: b=b.tz_convert(None)
        bridge=bool(b<=a+pd.Timedelta(days=7))
    except Exception: pass
DATA_AUDIT={'static_qqq_5m_status':static_status,'static_qqq_5m_end':static_end,'yahoo_qqq_1h':LIVE,'bridge_overlap_or_near':bridge,
            'live_4h_feasible':bool(LIVE.get('status')=='ok'),
            'route':'Use archived 5m history for Stage51 comparability; use Yahoo 1h (09:30/10:30/11:30/12:30 => first 4H, 13:30/14:30/15:30 => partial second) for current updates; archive appended bars periodically.',
            'verdict':'READY_FOR_LIVE_SIGNAL' if bridge else 'GAP_OR_SOURCE_FAILURE_REQUIRES_FIX'}

summary={'mc57':MC_AUDIT,'nqsar':NQ_AUDIT,'intraday':DATA_AUDIT,
         'production_readiness':{'qqq_4h_rsi':'PASS' if DATA_AUDIT['verdict']=='READY_FOR_LIVE_SIGNAL' else 'FAIL',
                                 'mc57':'CAVEAT','nqsar':'CAVEAT',
                                 'overall':'CONDITIONAL: QQQ RSI execution route is operational; MC57 universe and historical NQSAR remain research-validity caveats, not silent assumptions.'}}
Path('tqqq_stage54_audit_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,default=str));
print('\nMC57',json.dumps(MC_AUDIT,ensure_ascii=False,default=str)); print('\nNQSAR',json.dumps(NQ_AUDIT,ensure_ascii=False,default=str)); print('\nINTRADAY',json.dumps(DATA_AUDIT,ensure_ascii=False,default=str)); print('\nSUMMARY',json.dumps(summary,ensure_ascii=False,default=str))
