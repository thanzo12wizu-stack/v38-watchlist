#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

import market_conditions_deterioration_validate as base
import market_conditions_deterioration_smoothing_validate as smooth

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "market_conditions_alpha_context_15y.json"
OUT_DAILY = ROOT / "market_conditions_alpha_context_15y_daily.csv"

base.START = "2009-01-01"
base.END = "2026-08-25"
EVAL_START = pd.Timestamp("2011-01-01")
EVAL_END = pd.Timestamp("2026-08-24")
ALPHAS = [0.0, 0.75, 1.0, 1.25]


def dl_ohlc(ticker: str, start: str, end: str) -> pd.DataFrame:
    d = yf.download(ticker, start=start, end=end, auto_adjust=False, progress=False, threads=False, timeout=30)
    if d is None or d.empty:
        raise RuntimeError(f"{ticker} unavailable")
    if isinstance(d.columns, pd.MultiIndex):
        out = pd.DataFrame(index=d.index)
        for c in ("Open", "High", "Low", "Close"):
            if (c, ticker) in d.columns:
                out[c] = d[(c, ticker)]
            elif c in d.columns.get_level_values(0):
                out[c] = d.xs(c, axis=1, level=0).iloc[:, 0]
        d = out
    else:
        d = d[[c for c in ("Open", "High", "Low", "Close") if c in d.columns]].copy()
    d.index = pd.to_datetime(d.index).tz_localize(None)
    return d.apply(pd.to_numeric, errors="coerce").dropna(subset=["High", "Low", "Close"])


def psar_wilder(high: pd.Series, low: pd.Series, step: float = .02, max_af: float = .08) -> pd.Series:
    h = high.to_numpy(float); l = low.to_numpy(float); n = len(h)
    out = np.full(n, np.nan)
    if n < 3: return pd.Series(out, index=high.index)
    bull = True if (h[1] + l[1]) >= (h[0] + l[0]) else False
    af = step
    ep = h[0] if bull else l[0]
    sar = l[0] if bull else h[0]
    out[0] = sar
    for i in range(1, n):
        sar = sar + af * (ep - sar)
        if bull:
            if i >= 2: sar = min(sar, l[i-1], l[i-2])
            else: sar = min(sar, l[i-1])
            if l[i] < sar:
                bull = False; sar = ep; ep = l[i]; af = step
            else:
                if h[i] > ep:
                    ep = h[i]; af = min(max_af, af + step)
        else:
            if i >= 2: sar = max(sar, h[i-1], h[i-2])
            else: sar = max(sar, h[i-1])
            if h[i] > sar:
                bull = True; sar = ep; ep = h[i]; af = step
            else:
                if l[i] < ep:
                    ep = l[i]; af = min(max_af, af + step)
        out[i] = sar
    return pd.Series(out, index=high.index)


def rsi_wilder(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff(); up = d.clip(lower=0); dn = (-d.clip(upper=0))
    au = up.ewm(alpha=1/n, adjust=False, min_periods=n).mean()
    ad = dn.ewm(alpha=1/n, adjust=False, min_periods=n).mean()
    rs = au / ad.replace(0, np.nan)
    r = 100 - 100/(1+rs)
    return r.where(ad.ne(0), 100.0)


def nqsar_proxy(nq: pd.DataFrame) -> pd.Series:
    c=nq["Close"]; sar=psar_wilder(nq["High"],nq["Low"],.02,.08); ema=c.ewm(span=21,adjust=False).mean(); rsi=rsi_wilder(c,14)
    side=(c>sar)
    out=[]; prev=None; side_prev=None; bars_side=0
    for i,dt in enumerate(c.index):
        if pd.isna(sar.iloc[i]) or pd.isna(rsi.iloc[i]): out.append(None); continue
        cur_side=bool(side.iloc[i])
        bars_side = bars_side+1 if side_prev is cur_side else 0
        dr = float(rsi.iloc[i]-rsi.iloc[i-1]) if i and pd.notna(rsi.iloc[i-1]) else 0.0
        if cur_side:
            if side_prev is not True or prev not in ("Blue","Green"):
                st="Green"
            elif prev=="Blue":
                st="Green" if c.iloc[i] < ema.iloc[i] else "Blue"
            else:
                st="Blue" if (rsi.iloc[i]>52 and bars_side>=2 and dr<=3) else "Green"
        else:
            if side_prev is not False or prev not in ("Red","Yellow"):
                st="Yellow"
            elif prev=="Red":
                st="Yellow" if rsi.iloc[i]>50 else "Red"
            else:
                st="Red" if (rsi.iloc[i]<47 and bars_side>=2 and dr>=-3) else "Yellow"
        out.append(st); prev=st; side_prev=cur_side
    return pd.Series(out,index=c.index,name="nqsar_proxy")


def proxy_match(proxy: pd.Series) -> dict:
    p=ROOT/"trend_history.json"
    if not p.exists(): return {}
    raw=json.loads(p.read_text(encoding="utf-8")); rows=[]
    for x in raw:
        if isinstance(x,(list,tuple)) and len(x)>=2: rows.append((x[0],x[1]))
    actual=pd.Series({pd.Timestamp(d):s for d,s in rows})
    d=pd.concat([actual.rename("actual"),proxy.rename("proxy")],axis=1).dropna()
    if d.empty: return {}
    return {"n":int(len(d)),"exact_match_pct":float((d.actual==d.proxy).mean()*100),
            "risk_side_match_pct":float(((d.actual.isin(["Blue","Green"]))==(d.proxy.isin(["Blue","Green"]))).mean()*100),
            "confusion":d.groupby(["actual","proxy"]).size().to_dict()}


def vix_context(vix: pd.DataFrame) -> pd.Series:
    # Post-score context only: non-optimized, conventional stress buckets.
    # EXTREME corresponds roughly to the long-history +2 sigma threshold used by the VIX Fear Cycle card.
    x=vix["Close"]
    out=pd.Series("NORMAL",index=x.index,dtype=object)
    out.loc[x>=20]="ELEVATED"
    out.loc[x>=33]="EXTREME"
    # Reversal context: after EXTREME, VIX has fallen >=20% from its rolling 10d high.
    hi=x.rolling(10,min_periods=2).max(); rev=(hi>=33)&(x<=.80*hi)
    out.loc[rev]="REVERSAL"
    return out.rename("vix_context")


def frame_for_alpha(m: pd.DataFrame, alpha: float) -> pd.DataFrame:
    if alpha==0:
        raw=.15*m["short"]+.55*m["medium_level"]+.20*m["long"]+.10*m["damage"]
        f=m.copy(); f["penalty"]=0.0; f["medium"]=m["medium_level"]; f["score"]=raw.ewm(span=2,adjust=False).mean(); return f
    return smooth.candidate(m,alpha,3)


def threshold_stats(f: pd.DataFrame, qqq: pd.Series, eps: list[dict]) -> dict:
    idx=qqq.dropna().index; out={}
    for th in (65,55,45):
        vals=[]
        for e in eps:
            d=base.first_cross(f,e["peak"],e["trough"],"score",th,"below")
            if d is not None: vals.append(base.sessions_between(idx,e["peak"],d))
        out[f"below{th}_coverage"]=len(vals); out[f"below{th}_mean_sessions"]=float(np.mean(vals)) if vals else None; out[f"below{th}_median_sessions"]=float(np.median(vals)) if vals else None
    vals=[]
    for e in eps:
        pos=idx.get_indexer([e["trough"]],method="nearest")[0]; end=idx[min(pos+80,len(idx)-1)]
        d=base.first_cross(f,e["trough"],end,"score",65,"above")
        if d is not None: vals.append(base.sessions_between(idx,e["trough"],d))
    out["recover65_coverage"]=len(vals); out["recover65_mean_sessions"]=float(np.mean(vals)) if vals else None; out["recover65_median_sessions"]=float(np.median(vals)) if vals else None
    return out


def normal_bull_false_bear(f: pd.DataFrame, qqq: pd.Series) -> dict:
    # Calendar years with QQQ > +15% and max DD milder than -8%; count days MC <=45.
    rows=[]
    for y in range(2011,2027):
        q=qqq[qqq.index.year==y].dropna(); s=f.loc[f.index.year==y,"score"].dropna()
        if len(q)<100 or s.empty: continue
        ret=float(q.iloc[-1]/q.iloc[0]-1); dd=float((q/q.cummax()-1).min())
        if ret>.15 and dd>-.08:
            rows.append({"year":y,"qqq_return_pct":ret*100,"qqq_maxdd_pct":dd*100,"mc_min":float(s.min()),"days_le45":int((s<=45).sum()),"days_lt55":int((s<55).sum())})
    return {"years":rows,"total_days_le45":sum(r["days_le45"] for r in rows),"total_days_lt55":sum(r["days_lt55"] for r in rows)}


def corr_stats(score: pd.Series, idx: pd.Series) -> dict:
    d=pd.concat([score.rename("s"),idx.rename("x")],axis=1).dropna(); out={}
    for h in (5,10,21,63,126,252): out[f"ret{h}"]=float(d.s.corr(d.x/d.x.shift(h)-1))
    return out


def context_stats(mc: pd.Series, qqq: pd.Series, nqstate: pd.Series, vxctx: pd.Series) -> dict:
    d=pd.concat([mc.rename("mc"),qqq.rename("q"),nqstate,vxctx],axis=1).dropna()
    d=d.loc[(d.index>=EVAL_START)&(d.index<=EVAL_END)].copy()
    d["mc_zone"]=pd.cut(d.mc,[-np.inf,55,65,np.inf],labels=["DEFENSIVE","WEAK","BULL"])
    d["nq_side"]=np.where(d.nqsar_proxy.isin(["Blue","Green"]),"RISK_ON","RISK_OFF")
    fwd21=d.q.shift(-21)/d.q-1
    rows=[]
    for keys,g in d.groupby(["mc_zone","nq_side","vix_context"],observed=True):
        idx=g.index; vals=fwd21.reindex(idx).dropna(); mae=[]
        for dt in idx:
            i=d.index.get_loc(dt); z=d.q.iloc[i:min(i+11,len(d))]
            if len(z)>=2: mae.append(float(z.min()/z.iloc[0]-1))
        rows.append({"mc_zone":str(keys[0]),"nq_side":keys[1],"vix_context":keys[2],"sessions":int(len(g)),
                     "fwd21_mean_pct":float(vals.mean()*100) if len(vals) else None,
                     "fwd21_positive_pct":float((vals>0).mean()*100) if len(vals) else None,
                     "next10_mae_mean_pct":float(np.mean(mae)*100) if mae else None,
                     "next10_mae_le_minus3_pct":float(np.mean(np.array(mae)<=-.03)*100) if mae else None})
    # More stable 2-way splits for interpretation.
    two=[]
    for keys,g in d.groupby(["mc_zone","nq_side"],observed=True):
        vals=fwd21.reindex(g.index).dropna(); mae=[]
        for dt in g.index:
            i=d.index.get_loc(dt); z=d.q.iloc[i:min(i+11,len(d))]
            if len(z)>=2: mae.append(float(z.min()/z.iloc[0]-1))
        two.append({"mc_zone":str(keys[0]),"nq_side":keys[1],"sessions":int(len(g)),"fwd21_mean_pct":float(vals.mean()*100) if len(vals) else None,
                    "fwd21_positive_pct":float((vals>0).mean()*100) if len(vals) else None,"next10_mae_mean_pct":float(np.mean(mae)*100) if mae else None,
                    "next10_mae_le_minus3_pct":float(np.mean(np.array(mae)<=-.03)*100) if mae else None})
    vrows=[]
    for keys,g in d.groupby(["mc_zone","vix_context"],observed=True):
        vals=fwd21.reindex(g.index).dropna()
        vrows.append({"mc_zone":str(keys[0]),"vix_context":keys[1],"sessions":int(len(g)),"fwd21_mean_pct":float(vals.mean()*100) if len(vals) else None,"fwd21_positive_pct":float((vals>0).mean()*100) if len(vals) else None})
    return {"three_way":rows,"mc_x_nqsar":two,"mc_x_vix":vrows}


def main():
    px,failed=base.download_prices(); px=px.loc[:EVAL_END]
    m=base.build_metrics(px); q=px["QQQ"].loc[(px.index>=EVAL_START)&(px.index<=EVAL_END)].dropna()
    eps=base.drawdown_episodes(q,trigger=-.08,exit_dd=-.02)
    frames={f"alpha_{a}":frame_for_alpha(m,a) for a in ALPHAS}

    nq=dl_ohlc("NQ=F","2009-01-01","2026-08-25")
    nqstate=nqsar_proxy(nq)
    vx=dl_ohlc("^VIX","2009-01-01","2026-08-25")
    vxctx=vix_context(vx)

    result={"scope":{"evaluation":"2011-01-01..2026-08-24","failed_etfs":failed,"alphas":ALPHAS,
                     "penalty":"alpha * EWM3(0.5*max(0,-breadth_delta10)+0.5*(rolling20 breadth peak-current)); applied only to Medium",
                     "nqsar":"historical proxy reconstructed from NQ=F with PSAR(.02,.08), EMA21, Wilder RSI14 and current FSM; calibrated against stored 2026 history",
                     "vix":"post-score context only: NORMAL <20, ELEVATED 20-33, EXTREME >=33, REVERSAL when 10d high >=33 and VIX falls >=20% from that high; not part of MC score"},
            "nqsar_proxy_validation":proxy_match(nqstate),"alpha_comparison":{},"context":{}}
    for a in ALPHAS:
        name=f"alpha_{a}"; f=frames[name]; s=f["score"].loc[(f.index>=EVAL_START)&(f.index<=EVAL_END)].dropna(); latest=s.index[-1]
        result["alpha_comparison"][name]={"current_score":float(s.loc[latest]),"current_band":base.band(float(s.loc[latest])),
            "current_penalty":float(f.loc[latest,"penalty"]),"drawdown_detection":threshold_stats(f,q,eps),
            "normal_bull_false_bear":normal_bull_false_bear(f,q),"qqq_corr":corr_stats(s,q),
            "noise":{"mean_abs_daily_change":float(s.diff().abs().mean()),**base.band_flip_stats(s)}}

    for a in (0.75,1.0,1.25):
        name=f"alpha_{a}"; result["context"][name]=context_stats(frames[name]["score"],q,nqstate,vxctx)

    daily=pd.DataFrame(index=m.index)
    for a in ALPHAS: daily[f"mc_alpha_{a}"]=frames[f"alpha_{a}"]["score"]
    daily["QQQ"]=px["QQQ"]; daily["nqsar_proxy"]=nqstate.reindex(daily.index); daily["vix_context"]=vxctx.reindex(daily.index)
    daily.loc[(daily.index>=EVAL_START)&(daily.index<=EVAL_END)].to_csv(OUT_DAILY,index_label="date")
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False,indent=2,default=str))

if __name__=="__main__": main()
