from __future__ import annotations

import argparse, json, math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import build_dashboard as bd
from research import audit_stock_nqsar_theme30_pit as audit

START = pd.Timestamp('2016-01-04')
END = pd.Timestamp('2026-09-04')
DISC_END = pd.Timestamp('2021-12-31')
CONF_START = pd.Timestamp('2022-01-03')
NPORT = 12
DDV_POOL = 10_000_000.0
DDV_ENTRY = 20_000_000.0
STATE = {'Red':0, 'Yellow':1, 'Green':2, 'Blue':3}

VARIANTS = [
    'BASE_STRICT_RS189',
    'CURRENT_WEEK_PRIORITY',
    'WEEK_BULL_STRUCT_RS189',
    'WEEK_BULL_POOL_RS189',
    'WEEK_BULL_STRUCT_RS63',
    'WEEK_BULL_STRUCT_RS21',
    'WEEK_BULL_BLEND_SHORT',
    'WEEK_BULL_BLEND_MID',
    'WEEK_BULL_BLEND_RECENT',
    'WEEK_BULL_ACCEL',
    'WEEK_BULL_EARLY1_SCORE',
    'WEEK_BLUE_FIRST_RS63',
    'WEEK_GREEN_ONLY_RS63',
    'WEEK_FRESH_BULL_ACCEL',
    'WEEK_YOUNG_BULL_ACCEL',
    'WEEK_FRESH_BLUE_ACCEL',
    'WEEK_BULL_DAILY_BULL_RS63',
    'WEEK_BULL_DAILY_FRESH_ACCEL',
    'WEEK_BULL_DAILY_NOT_RED_RS63',
    'WEEK_BULL_MONTH_NOT_RED_RS63',
    'WEEK_BULL_BREAKOUT20_RS63',
    'WEEK_BULL_NEARHIGH20_RS63',
    'WEEK_BULL_SHALLOW_EMA21_RS63',
    'WEEK_BULL_TIGHT_DRYUP_RS63',
    'WEEK_BULL_RSI30_RESET_RS63',
    'RSI30_RESET_STRICT_RS189',
    'EARLY1_ANALOG',
    'EARLY1_WEEK_NOT_RED',
    'EARLY1_WEEK_BULL',
    'PIONEER_MARKET_ANALOG',
    'PIONEER_WEEK_BULL',
    'NQSAR_PREWEEK_ACCEL',
    'NQSAR_PREWEEK_NEARHIGH',
    'NQSAR_YELLOW_DAILY_BULL',
    'NQSAR_PURE_STATE',
]


def safe(x: Any) -> Any:
    if isinstance(x, dict): return {str(k): safe(v) for k,v in x.items()}
    if isinstance(x, (list,tuple)): return [safe(v) for v in x]
    if isinstance(x, np.integer): return int(x)
    if isinstance(x, (np.floating,float)):
        z=float(x); return z if math.isfinite(z) else None
    if isinstance(x, pd.Timestamp): return str(x.date())
    return x


def pct(values: pd.DataFrame, mask: pd.DataFrame) -> pd.DataFrame:
    return values.where(mask & values.notna()).rank(axis=1, pct=True, method='average') * 100.0


def rsi14(close: pd.DataFrame) -> pd.DataFrame:
    d=close.diff(); up=d.clip(lower=0); dn=-d.clip(upper=0)
    ru=up.ewm(alpha=1/14, adjust=False).mean(); rd=dn.ewm(alpha=1/14, adjust=False).mean()
    return 100.0 - 100.0/(1.0 + ru/rd.replace(0,np.nan))


def exact_states(high: pd.DataFrame, low: pd.DataFrame, close: pd.DataFrame, min_rows: int) -> pd.DataFrame:
    out=pd.DataFrame(np.int8(-1), index=close.index, columns=close.columns)
    good=0
    for j,s in enumerate(close.columns,1):
        z=pd.DataFrame({'h':high[s],'l':low[s],'c':close[s]}).dropna()
        if len(z)<min_rows: continue
        h=z.h.to_numpy(float); l=z.l.to_numpy(float); c=z.c.to_numpy(float)
        sar=bd._psar(h,l,c,step=.02,mx=.08)
        ema=z.c.ewm(span=21,adjust=False).mean().to_numpy(float)
        d=z.c.diff(); up=d.clip(lower=0); dn=-d.clip(upper=0)
        ru=up.ewm(alpha=1/14,adjust=False).mean(); rd=dn.ewm(alpha=1/14,adjust=False).mean()
        rsi=(100.0-100.0/(1.0+ru/rd.replace(0,np.nan))).to_numpy(float)
        bd._onimine_state(c,sar,ema,rsi)
        colors=list(bd._LAST_ONIMINE_SERIES or [])
        if len(colors)!=len(z): continue
        out.loc[z.index,s]=np.array([STATE.get(str(v),-1) for v in colors],dtype=np.int8)
        good+=1
        if j%500==0 or j==len(close.columns): print(f'NQSAR {j}/{len(close.columns)} good={good}',flush=True)
    return out


def period_ohlc(h: pd.DataFrame,l: pd.DataFrame,c: pd.DataFrame,freq: str):
    p=c.index.to_period(freq)
    hh=h.groupby(p).max(); ll=l.groupby(p).min(); cc=c.groupby(p).last()
    actual=pd.Series(c.index,index=p).groupby(level=0).max().reindex(cc.index)
    idx=pd.DatetimeIndex(actual.to_numpy())
    hh.index=idx; ll.index=idx; cc.index=idx
    return hh,ll,cc


def to_daily(frame: pd.DataFrame, idx: pd.DatetimeIndex, fill=-1):
    return frame.reindex(idx).ffill().fillna(fill)


def bull_age(states: pd.DataFrame) -> pd.DataFrame:
    a=np.zeros(states.shape,dtype=np.int16)
    x=states.to_numpy()
    for j in range(x.shape[1]):
        age=0
        for i in range(x.shape[0]):
            if x[i,j]>=2: age+=1
            else: age=0
            a[i,j]=age
    return pd.DataFrame(a,index=states.index,columns=states.columns)


def first_rsi30_rebound(rsi: pd.DataFrame) -> pd.DataFrame:
    arr=np.zeros(rsi.shape,dtype=bool); x=rsi.to_numpy(float)
    for j in range(x.shape[1]):
        armed=False; touch=-10_000
        for i in range(x.shape[0]):
            v=x[i,j]
            if not np.isfinite(v): continue
            if v<=30:
                if not armed: touch=i
                armed=True
                continue
            if armed and i-touch<=20 and i>0 and np.isfinite(x[i-1,j]) and v>x[i-1,j]:
                arr[i,j]=True; armed=False
            elif armed and i-touch>20:
                armed=False
    return pd.DataFrame(arr,index=rsi.index,columns=rsi.columns)


def build_inputs(ohlcv: dict[str,pd.DataFrame], bio: set[str]):
    o,h,l,c,v=(ohlcv[k] for k in ('open','high','low','close','volume'))
    vol20=v.rolling(20,min_periods=20).mean(); ddv=c*vol20
    pool=(c>=5)&(ddv>=DDV_POOL)
    ex=[s for s in bio if s in pool.columns]
    if ex: pool.loc[:,ex]=False
    sma50=c.rolling(50,min_periods=50).mean(); sma200=c.rolling(200,min_periods=200).mean()
    struct=pool&(sma50>sma200)&(c>sma200)
    periods=(21,42,63,126,189,252)
    q={p:pct(c/c.shift(p)-1,pool) for p in periods}
    strict=struct&(q[63]>=85)&(q[189]>=85)
    acc21=pct(q[21]-q[21].shift(20),pool)
    prior63=c.shift(1).rolling(63,min_periods=40).max(); high63_raw=c/prior63
    high63_pct=pct(high63_raw,pool)
    prior20=h.shift(1).rolling(20,min_periods=15).max(); dist_high20=c/prior20-1
    breakout20=c>prior20; nearhigh20=dist_high20>=-.05
    rv=v/v.shift(1).rolling(20,min_periods=12).mean().replace(0,np.nan); rv_pct=pct(rv,pool)
    # breakout recency, expressed as a cross-sectional percentile as in prior Pioneer research, but market-wide rather than frozen-theme.
    n=len(c); pos=np.arange(n,dtype=float)[:,None]
    last=pd.DataFrame(np.where(breakout20.to_numpy(bool),pos,np.nan),index=c.index,columns=c.columns).ffill()
    age=pd.DataFrame(pos-last.to_numpy(float),index=c.index,columns=c.columns)
    br_raw=(21-age).where((age>=0)&(age<=20),0.0); br_pct=pct(br_raw,pool)
    ema21=c.ewm(span=21,adjust=False).mean(); dist_ema=c/ema21-1
    tr=pd.DataFrame(np.nanmax(np.stack([(h-l).to_numpy(float),(h-c.shift(1)).abs().to_numpy(float),(l-c.shift(1)).abs().to_numpy(float)]),axis=0),index=c.index,columns=c.columns)
    compression=tr.shift(1).rolling(5,min_periods=4).mean()/tr.shift(1).rolling(20,min_periods=12).mean().replace(0,np.nan)
    rsi=rsi14(c); rsi_reset=first_rsi30_rebound(rsi)
    print('NQSAR DAILY',flush=True); ds=exact_states(h,l,c,60)
    print('NQSAR WEEKLY',flush=True); wh,wl,wc=period_ohlc(h,l,c,'W-FRI'); ws0=exact_states(wh,wl,wc,30)
    wa0=bull_age(ws0); wf0=(ws0>=2)&~(ws0.shift(1)>=2); wbluef0=(ws0==3)&~(ws0.shift(1)==3)
    ws=to_daily(ws0,c.index).astype(np.int8); wa=to_daily(wa0,c.index,0).astype(np.int16)
    wf=to_daily(wf0.astype(float),c.index,0).astype(bool); wbluef=to_daily(wbluef0.astype(float),c.index,0).astype(bool)
    print('NQSAR MONTHLY',flush=True); mh,ml,mc=period_ohlc(h,l,c,'M'); ms0=exact_states(mh,ml,mc,24); ms=to_daily(ms0,c.index).astype(np.int8)
    db=ds>=2; dr=ds==0; dfresh=db&~(db.shift(1).fillna(False))
    wb=ws>=2; wr=ws==0; wnred=ws>0; mnred=ms>0
    radar=(pool&((q[21]>=85)|(q[42]>=85)|(q[63]>=85))).fillna(False)
    radar_fresh=radar&~radar.shift(1).fillna(False); radar_active=radar_fresh.astype(int).rolling(5,min_periods=1).max().astype(bool)
    early_score=.50*q[21]+.25*high63_pct+.25*acc21
    pioneer_score=.25*q[63]+.25*acc21+.25*br_pct+.25*rv_pct
    blend_short=(q[21]+q[42]+q[63])/3
    blend_mid=(q[63]+q[126]+q[189])/3
    blend_recent=.4*q[63]+.2*q[126]+.2*q[189]+.2*q[252]
    accel_score=.4*q[63]+.3*acc21+.3*high63_pct
    nobs=c.notna().sum(axis=1); valid=sma50.notna().sum(axis=1); floor=max(5,min(30,int(max(1,c.shape[1])*.20)))
    breadth=(c>sma50).sum(axis=1)/valid.replace(0,np.nan)*100; breadth=breadth.where(valid>=np.maximum(floor,nobs*.45))
    return dict(open=o,high=h,low=l,close=c,volume=v,ddv=ddv,pool=pool,struct=struct,strict=strict,q=q,acc21=acc21,
                high63_raw=high63_raw,high63_pct=high63_pct,dist_high20=dist_high20,breakout20=breakout20,nearhigh20=nearhigh20,
                rv=rv,rv_pct=rv_pct,br_pct=br_pct,ema21=ema21,dist_ema=dist_ema,compression=compression,rsi=rsi,rsi_reset=rsi_reset,
                ds=ds,ws=ws,ms=ms,db=db,dr=dr,dfresh=dfresh,wb=wb,wr=wr,wnred=wnred,mnred=mnred,wage=wa,wfresh=wf,wbluefresh=wbluef,
                radar_active=radar_active,early_score=early_score,pioneer_score=pioneer_score,blend_short=blend_short,blend_mid=blend_mid,
                blend_recent=blend_recent,accel_score=accel_score,breadth=breadth)


def score_mask(d: pd.Timestamp, m: dict, variant: str):
    pool=m['pool'].loc[d].fillna(False); struct=m['struct'].loc[d].fillna(False); strict=m['strict'].loc[d].fillna(False)
    wb=m['wb'].loc[d].fillna(False); wr=m['wr'].loc[d].fillna(False); wn=m['wnred'].loc[d].fillna(False)
    db=m['db'].loc[d].fillna(False); dr=m['dr'].loc[d].fillna(False); df=m['dfresh'].loc[d].fillna(False)
    mn=m['mnred'].loc[d].fillna(False); wf=m['wfresh'].loc[d].fillna(False); wbf=m['wbluefresh'].loc[d].fillna(False)
    ws=m['ws'].loc[d]; age=m['wage'].loc[d]; q=m['q']; q21=q[21].loc[d]; q63=q[63].loc[d]; q189=q[189].loc[d]
    acc=m['acc21'].loc[d]; early=m['early_score'].loc[d]; pioneer=m['pioneer_score'].loc[d]
    ddv=m['ddv'].loc[d]; ddvok=ddv>=DDV_ENTRY
    mask=pool & ddvok
    score=q189.copy()
    if variant=='BASE_STRICT_RS189': mask &= strict
    elif variant=='CURRENT_WEEK_PRIORITY':
        mask &= strict; score=q189 + wb.astype(float)*1000
    elif variant=='WEEK_BULL_STRUCT_RS189': mask &= struct&wb; score=q189
    elif variant=='WEEK_BULL_POOL_RS189': mask &= wb; score=q189
    elif variant=='WEEK_BULL_STRUCT_RS63': mask &= struct&wb; score=q63
    elif variant=='WEEK_BULL_STRUCT_RS21': mask &= struct&wb; score=q21
    elif variant=='WEEK_BULL_BLEND_SHORT': mask &= struct&wb; score=m['blend_short'].loc[d]
    elif variant=='WEEK_BULL_BLEND_MID': mask &= struct&wb; score=m['blend_mid'].loc[d]
    elif variant=='WEEK_BULL_BLEND_RECENT': mask &= struct&wb; score=m['blend_recent'].loc[d]
    elif variant=='WEEK_BULL_ACCEL': mask &= struct&wb; score=m['accel_score'].loc[d]
    elif variant=='WEEK_BULL_EARLY1_SCORE': mask &= struct&wb; score=early
    elif variant=='WEEK_BLUE_FIRST_RS63': mask &= struct&wb; score=q63+(ws==3).astype(float)*1000
    elif variant=='WEEK_GREEN_ONLY_RS63': mask &= struct&(ws==2); score=q63
    elif variant=='WEEK_FRESH_BULL_ACCEL': mask &= struct&wf; score=m['accel_score'].loc[d]
    elif variant=='WEEK_YOUNG_BULL_ACCEL': mask &= struct&wb&(age>=1)&(age<=4); score=m['accel_score'].loc[d]
    elif variant=='WEEK_FRESH_BLUE_ACCEL': mask &= struct&wbf; score=m['accel_score'].loc[d]
    elif variant=='WEEK_BULL_DAILY_BULL_RS63': mask &= struct&wb&db; score=q63
    elif variant=='WEEK_BULL_DAILY_FRESH_ACCEL': mask &= struct&wb&df; score=m['accel_score'].loc[d]
    elif variant=='WEEK_BULL_DAILY_NOT_RED_RS63': mask &= struct&wb&~dr; score=q63
    elif variant=='WEEK_BULL_MONTH_NOT_RED_RS63': mask &= struct&wb&mn; score=q63
    elif variant=='WEEK_BULL_BREAKOUT20_RS63': mask &= struct&wb&m['breakout20'].loc[d].fillna(False); score=q63
    elif variant=='WEEK_BULL_NEARHIGH20_RS63': mask &= struct&wb&m['nearhigh20'].loc[d].fillna(False); score=q63
    elif variant=='WEEK_BULL_SHALLOW_EMA21_RS63': mask &= struct&wb&~dr&m['dist_ema'].loc[d].between(-.03,.03); score=q63
    elif variant=='WEEK_BULL_TIGHT_DRYUP_RS63': mask &= struct&wb&m['nearhigh20'].loc[d].fillna(False)&(m['compression'].loc[d]<=.75)&(m['rv'].loc[d]<=1.0); score=q63
    elif variant=='WEEK_BULL_RSI30_RESET_RS63': mask &= struct&wb&m['rsi_reset'].loc[d].fillna(False); score=q63
    elif variant=='RSI30_RESET_STRICT_RS189': mask &= strict&m['rsi_reset'].loc[d].fillna(False); score=q189
    elif variant=='EARLY1_ANALOG': mask &= m['radar_active'].loc[d].fillna(False); score=early
    elif variant=='EARLY1_WEEK_NOT_RED': mask &= m['radar_active'].loc[d].fillna(False)&wn; score=early
    elif variant=='EARLY1_WEEK_BULL': mask &= m['radar_active'].loc[d].fillna(False)&wb; score=early
    elif variant=='PIONEER_MARKET_ANALOG': mask &= (q21>=60); score=pioneer
    elif variant=='PIONEER_WEEK_BULL': mask &= wb&(q21>=60); score=pioneer
    elif variant=='NQSAR_PREWEEK_ACCEL': mask &= (~wb)&wn&db&(q21>=85)&(acc>=80); score=early
    elif variant=='NQSAR_PREWEEK_NEARHIGH': mask &= (~wb)&wn&db&(q21>=85)&(acc>=80)&m['nearhigh20'].loc[d].fillna(False); score=early
    elif variant=='NQSAR_YELLOW_DAILY_BULL': mask &= (ws==1)&db&(q21>=80); score=early
    elif variant=='NQSAR_PURE_STATE':
        mask &= wb
        # NQSAR hierarchy first: Blue, fresh Bull, young Bull, daily Bull, Monthly not-Red; RS63 only breaks ties.
        score=(ws==3).astype(float)*10000 + wf.astype(float)*3000 + ((age>=1)&(age<=4)).astype(float)*1000 + db.astype(float)*300 + mn.astype(float)*100 + q63
    else: raise KeyError(variant)
    score=pd.to_numeric(score,errors='coerce').where(mask)
    return score.dropna().nlargest(NPORT).index.tolist()


def metrics(eq: pd.Series, exposure: pd.Series|None=None):
    e=pd.to_numeric(eq,errors='coerce').dropna(); r=e.pct_change(fill_method=None).dropna(); dd=e/e.cummax()-1
    years=max(len(r)/252,1/252); sd=float(r.std(ddof=1)) if len(r)>2 else np.nan
    out={'n':len(e),'total_return':float(e.iloc[-1]/e.iloc[0]-1),'cagr':float((e.iloc[-1]/e.iloc[0])**(1/years)-1),'mdd':float(dd.min()),
         'sharpe':float(r.mean()/sd*np.sqrt(252)) if np.isfinite(sd) and sd>0 else None}
    if exposure is not None: out['avg_exposure']=float(exposure.reindex(e.index).mean())
    return out


def slices(eq,exp):
    return {'full':metrics(eq,exp),'discovery_2016_2021':metrics(eq.loc[eq.index<=DISC_END],exp),'confirmation_2022_plus':metrics(eq.loc[eq.index>=CONF_START],exp),
            '2016_2019':metrics(eq.loc[eq.index<'2020-01-01'],exp),'2020_2021':metrics(eq.loc[(eq.index>='2020-01-01')&(eq.index<'2022-01-01')],exp),
            '2022_2023':metrics(eq.loc[(eq.index>='2022-01-01')&(eq.index<'2024-01-01')],exp),'2024_plus':metrics(eq.loc[eq.index>='2024-01-01'],exp)}


def simulate(idx, m, nq, variant, cost_bps=0.0, exit_policy='CURRENT'):
    cost=max(0.,float(cost_bps))/10000.; cash=1.; pos={}; eq=[]; exps=[]; trades=[]; datepos={pd.Timestamp(d):i for i,d in enumerate(idx)}
    def px(frame,d,s,fallback=None):
        try:
            z=float(frame.at[d,s]); return z if np.isfinite(z) and z>0 else fallback
        except Exception:return fallback
    def finish(s,d,pprice,reason):
        nonlocal cash
        p=pos.pop(s); proceeds=p['shares']*pprice*(1-cost); cash+=proceeds; realized=p['realized']+proceeds
        trades.append({'symbol':s,'entry_date':p['entry_date'],'exit_date':d,'return':realized/p['cost_basis']-1,'reason':reason,'hold':datepos.get(d,0)-datepos.get(p['entry_date'],0)})
    for i,d0 in enumerate(idx):
        d=pd.Timestamp(d0); prev=pd.Timestamp(idx[i-1]) if i else None
        if prev is not None:
            color=str(nq.at[prev,'nq_color']) if prev in nq.index and pd.notna(nq.at[prev,'nq_color']) else ''
            mode=audit.mode(color,m['breadth'].get(prev,np.nan))
            for s in list(pos):
                p=pos.get(s); pc=px(m['close'],prev,s,p['entry_price']); op=px(m['open'],d,s,pc)
                if pc is None or op is None: continue
                stock_exit=False; reason=''
                if color.title()=='Red': stock_exit=True; reason='MARKET_RED'
                elif exit_policy=='DAILY_RED' and int(m['ds'].at[prev,s])==0: stock_exit=True; reason='STOCK_DAILY_RED'
                elif exit_policy=='WEEK_RED' and int(m['ws'].at[prev,s])==0: stock_exit=True; reason='STOCK_WEEK_RED'
                elif exit_policy=='WEEK_NONBULL' and int(m['ws'].at[prev,s])<2: stock_exit=True; reason='STOCK_WEEK_NONBULL'
                if stock_exit: finish(s,d,op,reason); continue
                stop=max(p['entry_price']*.92,p['peak']*.70)
                if pc<=stop: finish(s,d,op,'INITIAL_STOP' if p['entry_price']*.92>=p['peak']*.70 else 'PEAK30_STOP'); continue
                if (not p['partial']) and pc>=p['entry_price']*1.24:
                    sell=min(p['initial_shares']*.25,p['shares']); proceeds=sell*op*(1-cost); p['shares']-=sell; p['realized']+=proceeds; p['partial']=True; cash+=proceeds
            cap=12 if mode=='ATTACK' else 4 if mode=='SELECTIVE' else 0
            if cap>len(pos):
                cands=score_mask(prev,m,variant); nav_open=cash
                for s,p in pos.items(): nav_open+=p['shares']*px(m['open'],d,s,px(m['close'],prev,s,p['entry_price']))
                slot=nav_open/NPORT
                for s in cands:
                    if len(pos)>=cap or cash<=1e-12: break
                    if s in pos: continue
                    op=px(m['open'],d,s,px(m['close'],prev,s,None))
                    if op is None: continue
                    alloc=min(slot,cash)
                    if alloc<=1e-12: break
                    sh=alloc/(op*(1+cost)); cash-=alloc
                    pos[s]={'shares':sh,'initial_shares':sh,'cost_basis':alloc,'realized':0.,'entry_price':op,'entry_date':d,'peak':op,'partial':False}
        nav=cash; invested=0.
        for s,p in pos.items():
            cp=px(m['close'],d,s,px(m['open'],d,s,p['entry_price'])); cp=cp if cp is not None else p['entry_price']; p['peak']=max(p['peak'],cp); val=p['shares']*cp; nav+=val; invested+=val
        eq.append((d,nav)); exps.append((d,invested/nav if nav>0 else 0.))
    return {'equity':pd.Series(dict(eq),dtype=float),'exposure':pd.Series(dict(exps),dtype=float),'trades':pd.DataFrame(trades)}


def transition_expectancy(m, idx):
    c=m['close'].loc[idx]; periods={'DISCOVERY':idx[idx<=DISC_END],'CONFIRMATION':idx[idx>=CONF_START]}; defs={
        'WEEK_BULL_ALL':m['wb'], 'WEEK_FRESH_BULL':m['wfresh'], 'WEEK_YOUNG_BULL':m['wb']&(m['wage']<=4)&(m['wage']>=1),
        'WEEK_BLUE':m['ws']==3, 'WEEK_GREEN':m['ws']==2, 'WEEK_BULL_DAILY_BULL':m['wb']&m['db'],
        'WEEK_BULL_DAILY_FRESH':m['wb']&m['dfresh'], 'WEEK_YELLOW_DAILY_BULL':(m['ws']==1)&m['db'],
        'PREWEEK_DAILY_BULL':(~m['wb'])&m['wnred']&m['db'], 'WEEK_BULL_RSI30_RESET':m['wb']&m['rsi_reset'],
        'WEEK_BULL_BREAKOUT20':m['wb']&m['breakout20'], 'WEEK_BULL_SHALLOW_EMA21':m['wb']&~m['dr']&m['dist_ema'].between(-.03,.03),
    }; rows=[]
    for name,mask in defs.items():
        mask=mask&m['pool']
        for period,pidx in periods.items():
            for h in (5,10,20,63):
                fwd=c.shift(-h)/c-1; z=fwd.loc[pidx].where(mask.loc[pidx]).stack(future_stack=True).replace([np.inf,-np.inf],np.nan).dropna()
                rows.append({'signal':name,'period':period,'horizon':h,'n':len(z),'mean':float(z.mean()) if len(z) else None,'median':float(z.median()) if len(z) else None,'win':float((z>0).mean()) if len(z) else None})
    return pd.DataFrame(rows)


def leader_retention(m,idx,variants):
    c=m['close']; future=c.shift(-1).iloc[::-1].rolling(126,min_periods=20).max().iloc[::-1]/c-1
    base_leaders=0; counts={v:0 for v in variants}; totals={v:0 for v in variants}
    for k,d in enumerate(idx):
        if k%250==0: print(f'LEADERS {k}/{len(idx)}',flush=True)
        base=score_mask(d,m,'BASE_STRICT_RS189'); leaders=[s for s in base if pd.notna(future.at[d,s]) and float(future.at[d,s])>=1.0]; base_leaders+=len(leaders)
        if not leaders: continue
        for v in variants:
            cand=set(score_mask(d,m,v)); counts[v]+=sum(s in cand for s in leaders); totals[v]+=len(cand)
    return pd.DataFrame([{'variant':v,'baseline_big_leaders':base_leaders,'retained':counts[v],'retention':counts[v]/base_leaders if base_leaders else None,'candidate_slots_counted':totals[v]} for v in variants])


def blockprob(a,b,start=None,block=20,reps=3000,seed=20260907):
    if start is not None: a=a.loc[a.index>=start]; b=b.loc[b.index>=start]
    x=(a.pct_change(fill_method=None)-b.pct_change(fill_method=None)).dropna().to_numpy(float)
    if len(x)<20:return None
    rng=np.random.default_rng(seed+block+(100 if start is not None else 0)); starts=np.arange(max(1,len(x)-block+1)); win=0
    for _ in range(reps):
        z=[]
        while len(z)<len(x):
            st=int(rng.choice(starts)); z.extend(x[st:st+block])
        win+=np.mean(z[:len(x)])>0
    return win/reps


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--root',default='.'); ap.add_argument('--output',required=True); ap.add_argument('--batch-size',type=int,default=100); a=ap.parse_args()
    root=Path(a.root); out=root/a.output; out.mkdir(parents=True,exist_ok=True)
    symbols,bio=audit.load_universe(root/'universe.csv'); warm=str((START-pd.Timedelta(days=1600)).date()); end='2026-09-05'
    print('DOWNLOAD',flush=True); ohlcv,diag=audit.download_ohlcv(symbols,warm,end,a.batch_size)
    if diag['coverage']<.85: raise RuntimeError(diag)
    print('INPUTS',flush=True); m=build_inputs(ohlcv,bio)
    nq=audit.market_nqsar(str((START-pd.Timedelta(days=120)).date()),end).reindex(m['close'].index).ffill(limit=2)
    idx=m['close'].index[(m['close'].index>=START)&(m['close'].index<=END)]
    cov=float(nq.loc[idx,'nq_color'].notna().mean());
    if cov<.95: raise RuntimeError(f'Market NQSAR coverage {cov}')
    allres={}; metric_rows=[]; trade_rows=[]
    for i,v in enumerate(VARIANTS,1):
        print(f'SIM {i}/{len(VARIANTS)} {v}',flush=True); r=simulate(idx,m,nq,v); allres[v]=r; sl=slices(r['equity'],r['exposure'])
        row={'variant':v}
        for p,mm in sl.items():
            for k,val in mm.items(): row[f'{p}_{k}']=val
        metric_rows.append(row)
        t=r['trades']; trade_rows.append({'variant':v,'n_trades':len(t),'mean_trade':float(t['return'].mean()) if len(t) else None,'median_trade':float(t['return'].median()) if len(t) else None,'win_rate':float((t['return']>0).mean()) if len(t) else None,'avg_hold':float(t['hold'].mean()) if len(t) else None})
    vm=pd.DataFrame(metric_rows); vm.to_csv(out/'variant_metrics.csv',index=False); pd.DataFrame(trade_rows).to_csv(out/'trade_stats.csv',index=False)
    # Discovery-only selection. Confirmation is untouched by finalist selection.
    eligible_final=vm[(vm.discovery_2016_2021_avg_exposure>=.20)&(~vm.variant.isin(['BASE_STRICT_RS189','CURRENT_WEEK_PRIORITY']))].copy()
    finalists=eligible_final.sort_values('discovery_2016_2021_cagr',ascending=False).head(6).variant.tolist()
    finalists=['BASE_STRICT_RS189','CURRENT_WEEK_PRIORITY']+finalists
    print('FINALISTS',finalists,flush=True)
    transition_expectancy(m,idx).to_csv(out/'transition_expectancy.csv',index=False)
    leader_retention(m,idx,finalists).to_csv(out/'leader_retention.csv',index=False)
    cost_rows=[]; boot_rows=[]
    base=allres['CURRENT_WEEK_PRIORITY']['equity']
    for v in finalists:
        for bps in (10,25):
            rr=simulate(idx,m,nq,v,cost_bps=bps); mm=slices(rr['equity'],rr['exposure']); cost_rows.append({'variant':v,'cost_bps_per_side':bps,'full_cagr':mm['full']['cagr'],'full_mdd':mm['full']['mdd'],'confirm_cagr':mm['confirmation_2022_plus']['cagr'],'confirm_mdd':mm['confirmation_2022_plus']['mdd']})
        boot_rows.append({'variant':v,'vs_current_week_full_block20':blockprob(allres[v]['equity'],base),'vs_current_week_confirm_block20':blockprob(allres[v]['equity'],base,CONF_START)})
    pd.DataFrame(cost_rows).to_csv(out/'cost_stress.csv',index=False); pd.DataFrame(boot_rows).to_csv(out/'bootstrap.csv',index=False)
    # Exit overlays only on discovery winner and current weekly control.
    discwin=finalists[2] if len(finalists)>2 else 'CURRENT_WEEK_PRIORITY'; exrows=[]
    for v in ['CURRENT_WEEK_PRIORITY',discwin]:
        for ep in ('CURRENT','DAILY_RED','WEEK_RED','WEEK_NONBULL'):
            rr=simulate(idx,m,nq,v,exit_policy=ep); mm=slices(rr['equity'],rr['exposure']); exrows.append({'variant':v,'exit_policy':ep,'full_cagr':mm['full']['cagr'],'full_mdd':mm['full']['mdd'],'confirm_cagr':mm['confirmation_2022_plus']['cagr'],'confirm_mdd':mm['confirmation_2022_plus']['mdd']})
    pd.DataFrame(exrows).to_csv(out/'exit_overlay.csv',index=False)
    for v in finalists: allres[v]['equity'].rename('equity').to_csv(out/f'equity_{v}.csv')
    summary={'method':'NQSAR-centric broad scan; neutral Top12/Selective4; current market mode and current -8/+24%partial/peak-30 exits; no rank exits; signals at close -> next open',
             'coverage':diag,'market_nqsar_coverage':cov,'analysis_start':str(START.date()),'analysis_end':str(END.date()),
             'limitations':['current-universe survivorship/current structural classification bias','no historical Theme30 in long scan because verified PIT taxonomy starts 2026-06-22','Pioneer analog is market-wide, not historical within-theme, to avoid taxonomy hindsight'],
             'variant_count':len(VARIANTS),'discovery_selected_finalists':finalists,'discovery_winner_for_exit_overlay':discwin}
    (out/'summary.json').write_text(json.dumps(safe(summary),ensure_ascii=False,indent=2)); print('DONE',json.dumps(safe(summary),ensure_ascii=False),flush=True)

if __name__=='__main__': main()
