#!/usr/bin/env python3
"""Research-only validation of Options positioning vs subsequent underlying returns.

This script is deliberately isolated from production. It reads existing Options history
and universe metadata, downloads historical OHLCV only for research, and writes reports
under research/options-intelligence-20260905/. It never writes V38/Dashboard/Rotation
artifacts and does not alter production ranking logic.

Important limitation: historical option chains cannot be reconstructed from yfinance.
Therefore all Options features are strictly those snapshots already accumulated in this
repository. Price history may extend before/after those snapshots only to compute
technical context and forward returns.
"""
from __future__ import annotations

import csv
import json
import math
import os
import random
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[2]
OUTDIR = Path(__file__).resolve().parent
SCAN = ROOT / "options_scan_history.csv"
DETAIL = ROOT / "options_history.csv"
UNIVERSE = ROOT / "universe.csv"

SEED = 381947
random.seed(SEED)
np.random.seed(SEED)
HORIZONS = (1, 3, 5, 10)


def f(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return np.nan
    return x if math.isfinite(x) else np.nan


def b(v):
    if isinstance(v, bool):
        return v
    return str(v or "").strip().lower() in {"1", "true", "yes", "y"}


def read_csv(path: Path, source: str) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    d = pd.read_csv(path, low_memory=False)
    if d.empty:
        return d
    d["source"] = source
    if "date" in d:
        d["date"] = pd.to_datetime(d["date"], errors="coerce").dt.normalize()
    if "ticker" in d:
        d["ticker"] = d["ticker"].astype(str).str.strip().str.upper()
    return d


def load_events() -> pd.DataFrame:
    scan = read_csv(SCAN, "SCAN")
    detail = read_csv(DETAIL, "DETAIL")
    cols = sorted(set(scan.columns) | set(detail.columns))
    for d in (scan, detail):
        for c in cols:
            if c not in d:
                d[c] = np.nan
    d = pd.concat([scan[cols], detail[cols]], ignore_index=True)
    d = d[d["date"].notna() & d["ticker"].notna()].copy()
    # Prefer same-session SCAN for broad history; then DETAIL. Keep only one row per
    # ticker/session to avoid treating multiple expiries as independent observations.
    d["source_pri"] = d["source"].map({"SCAN": 0, "DETAIL": 1}).fillna(9)
    d["dte_num"] = pd.to_numeric(d.get("dte"), errors="coerce")
    d["quality_pri"] = d.get("confidence", "").astype(str).str.upper().map(
        {"HIGH": 0, "MEDIUM": 1, "OK": 1, "LOW": 2}
    ).fillna(3)
    d = d.sort_values(["ticker", "date", "source_pri", "quality_pri", "dte_num"])
    d = d.drop_duplicates(["ticker", "date"], keep="first")
    return d.reset_index(drop=True)


def load_universe():
    u = pd.read_csv(UNIVERSE, low_memory=False)
    tcol = "シンボル" if "シンボル" in u else "ticker"
    scol = "セクター" if "セクター" in u else "sector"
    icol = "業種" if "業種" in u else "industry"
    u[tcol] = u[tcol].astype(str).str.strip().str.upper()
    meta = {}
    for _, r in u.iterrows():
        meta[r[tcol]] = {
            "sector": str(r.get(scol, "") or ""),
            "industry": str(r.get(icol, "") or ""),
        }
    return meta


def yf_batch(tickers, start, end, batch=80):
    """Download research OHLCV with conservative batching and retries."""
    out = {}
    pending = list(dict.fromkeys(tickers))
    for attempt in range(1, 4):
        if not pending:
            break
        next_pending = []
        for i in range(0, len(pending), batch):
            names = pending[i:i+batch]
            try:
                z = yf.download(
                    tickers=" ".join(names), start=start, end=end,
                    auto_adjust=False, actions=False, group_by="ticker",
                    threads=True, progress=False, timeout=30,
                )
            except Exception:
                z = pd.DataFrame()
            if len(names) == 1:
                tk = names[0]
                if isinstance(z, pd.DataFrame) and not z.empty:
                    x = z.copy()
                    x.columns = [str(c) for c in x.columns]
                    out[tk] = x
                else:
                    next_pending.append(tk)
            else:
                for tk in names:
                    try:
                        x = z[tk].dropna(how="all").copy()
                    except Exception:
                        x = pd.DataFrame()
                    if not x.empty:
                        out[tk] = x
                    else:
                        next_pending.append(tk)
            time.sleep(0.35)
        pending = next_pending
        if pending:
            time.sleep(5 * attempt)
    return out, pending


def normalize_price(tk, x):
    if x is None or x.empty:
        return None
    x = x.copy()
    x.index = pd.to_datetime(x.index).tz_localize(None).normalize()
    # Some yfinance versions can still return nested columns.
    if isinstance(x.columns, pd.MultiIndex):
        x.columns = [c[-1] if c[-1] in {"Open","High","Low","Close","Adj Close","Volume"} else c[0] for c in x.columns]
    need = ["Open", "High", "Low", "Close", "Volume"]
    if not set(need).issubset(x.columns):
        return None
    x = x[need].apply(pd.to_numeric, errors="coerce").dropna(subset=["Close"])
    if x.empty:
        return None
    close = x["Close"]
    x["ret1"] = close.pct_change()
    x["logret"] = np.log(close / close.shift(1))
    x["ema21"] = close.ewm(span=21, adjust=False, min_periods=15).mean()
    vv = x["Volume"].replace(0, np.nan)
    x["vwap63"] = (close * vv).rolling(63, min_periods=25).sum() / vv.rolling(63, min_periods=25).sum()
    x["hv20"] = x["logret"].rolling(20, min_periods=15).std() * math.sqrt(252)
    x["ret20"] = close.pct_change(20)
    x["high20"] = x["High"].rolling(20, min_periods=15).max()
    x["dist20hi"] = close / x["high20"] - 1
    x["gap"] = x["Open"] / close.shift(1) - 1
    return x


def get_forward(x, date, h):
    if x is None or date not in x.index:
        return (np.nan,) * 4
    loc = x.index.get_loc(date)
    if isinstance(loc, slice) or not isinstance(loc, (int, np.integer)):
        return (np.nan,) * 4
    if loc + h >= len(x):
        return (np.nan,) * 4
    base = f(x.iloc[loc]["Close"])
    fut = x.iloc[loc+1:loc+h+1]
    if not np.isfinite(base) or base <= 0 or len(fut) < h:
        return (np.nan,) * 4
    ret = f(x.iloc[loc+h]["Close"]) / base - 1
    mfe = f(fut["High"].max()) / base - 1
    mae = f(fut["Low"].min()) / base - 1
    end = x.index[loc+h]
    return ret, mfe, mae, end


def expiry_return(x, date, expiry):
    try:
        exp = pd.Timestamp(expiry).normalize()
    except Exception:
        return np.nan
    if x is None or date not in x.index or exp <= date:
        return np.nan
    future = x[(x.index > date) & (x.index <= exp)]
    if future.empty:
        return np.nan
    base = f(x.loc[date, "Close"])
    last = f(future.iloc[-1]["Close"])
    return last / base - 1 if np.isfinite(base) and base > 0 and np.isfinite(last) else np.nan


def wall_path(x, date, level, side, h=5):
    if x is None or date not in x.index or not np.isfinite(level):
        return np.nan, np.nan
    loc = x.index.get_loc(date)
    if not isinstance(loc, (int, np.integer)):
        return np.nan, np.nan
    fut = x.iloc[loc+1:min(loc+h+1, len(x))]
    if fut.empty:
        return np.nan, np.nan
    if side == "call":
        touch = bool((fut["High"] >= level).any())
        brk = bool((fut["Close"] >= level * 1.002).any())
    else:
        touch = bool((fut["Low"] <= level).any())
        brk = bool((fut["Close"] <= level * 0.998).any())
    return float(touch), float(brk)


def cluster_boot_ci(df, value_col, nboot=1500, block_len=2):
    z = df[["date", value_col]].dropna()
    if z.empty:
        return np.nan, np.nan, np.nan
    dates = sorted(z["date"].unique())
    mean = float(z[value_col].mean())
    if len(dates) < 3:
        return mean, np.nan, np.nan
    groups = {d: z[z["date"] == d][value_col].to_numpy(float) for d in dates}
    vals = []
    n = len(dates)
    for _ in range(nboot):
        picked = []
        while len(picked) < n:
            s = random.randrange(n)
            for k in range(block_len):
                picked.append(dates[(s+k) % n])
                if len(picked) >= n:
                    break
        arr = np.concatenate([groups[d] for d in picked if len(groups[d])])
        vals.append(float(np.mean(arr)))
    lo, hi = np.quantile(vals, [0.025, 0.975])
    return mean, float(lo), float(hi)


def sign_pvalue_boot(df, value_col, nboot=1200):
    z = df[["date", value_col]].dropna()
    if len(z) < 5:
        return np.nan
    dates = sorted(z["date"].unique())
    if len(dates) < 3:
        return np.nan
    observed = abs(float(z[value_col].mean()))
    centered = z.copy()
    centered[value_col] = centered[value_col] - centered[value_col].mean()
    groups = {d: centered[centered["date"] == d][value_col].to_numpy(float) for d in dates}
    vals=[]
    for _ in range(nboot):
        pick = np.random.choice(dates, size=len(dates), replace=True)
        arr=np.concatenate([groups[d] for d in pick])
        vals.append(abs(float(arr.mean())))
    return float((np.sum(np.array(vals) >= observed)+1)/(len(vals)+1))


def bh_qvalues(pvals):
    p = np.asarray(pvals, float)
    q = np.full(len(p), np.nan)
    ok = np.isfinite(p)
    ix = np.where(ok)[0]
    if not len(ix):
        return q
    order = ix[np.argsort(p[ix])]
    m = len(order)
    running = 1.0
    for rank_rev, idx in enumerate(order[::-1], start=1):
        rank = m-rank_rev+1
        running = min(running, p[idx]*m/rank)
        q[idx] = running
    return q


def build_event_frame(events, prices, meta):
    # Sector momentum is the cross-sectional median 20d return of all fetched names in that sector.
    sector_by_date = defaultdict(lambda: defaultdict(list))
    for tk, x in prices.items():
        sec = meta.get(tk, {}).get("sector", "")
        if not sec or x is None:
            continue
        for dt, val in x["ret20"].dropna().items():
            sector_by_date[dt][sec].append(float(val))
    sector_median = {dt: {s: float(np.median(v)) for s,v in dd.items() if len(v)>=3} for dt,dd in sector_by_date.items()}

    qqq = prices.get("QQQ")
    spy = prices.get("SPY")
    rows=[]
    numeric = [
        "spot","atr14","call_wall","put_wall","gamma_flip","net_gex","total_oi","n_strikes","dte",
        "call_oi","put_oi","expected_move","expected_move_pct","dvol_m",
    ]
    for _, r in events.iterrows():
        tk = r["ticker"]
        dt = pd.Timestamp(r["date"]).normalize()
        x = prices.get(tk)
        if x is None or dt not in x.index:
            continue
        o = {k:f(r.get(k)) for k in numeric}
        spot = o["spot"] if np.isfinite(o["spot"]) else f(x.loc[dt,"Close"])
        close = f(x.loc[dt,"Close"])
        # Require price anchor to be reasonably consistent with the event snapshot.
        if np.isfinite(spot) and np.isfinite(close) and abs(spot/close-1) > 0.02:
            continue
        atr = o["atr14"]
        z={
            "date":dt,"ticker":tk,"source":r.get("source"),"expiry":r.get("expiry"),
            "confidence":str(r.get("confidence") or "").upper(),"regime":str(r.get("regime") or "UNKNOWN").upper(),
            "session_consistent": b(r.get("session_consistent")) if pd.notna(r.get("session_consistent")) else np.nan,
            "sector":meta.get(tk,{}).get("sector",""),"industry":meta.get(tk,{}).get("industry",""),
            **o,
            "close":close,"ret1_today":f(x.loc[dt,"ret1"]),"gap":f(x.loc[dt,"gap"]),
            "ema21":f(x.loc[dt,"ema21"]),"vwap63":f(x.loc[dt,"vwap63"]),"hv20":f(x.loc[dt,"hv20"]),
            "ret20":f(x.loc[dt,"ret20"]),"dist20hi":f(x.loc[dt,"dist20hi"]),
        }
        z["above_ema21"] = float(close > z["ema21"]) if np.isfinite(z["ema21"]) else np.nan
        z["above_vwap63"] = float(close > z["vwap63"]) if np.isfinite(z["vwap63"]) else np.nan
        z["call_dist_atr"] = (o["call_wall"]-spot)/atr if np.isfinite(o["call_wall"]) and np.isfinite(atr) and atr>0 else np.nan
        z["put_dist_atr"] = (spot-o["put_wall"])/atr if np.isfinite(o["put_wall"]) and np.isfinite(atr) and atr>0 else np.nan
        z["flip_dist_atr"] = (spot-o["gamma_flip"])/atr if np.isfinite(o["gamma_flip"]) and np.isfinite(atr) and atr>0 else np.nan
        z["wall_rr"] = z["call_dist_atr"]/z["put_dist_atr"] if z["call_dist_atr"]>0 and z["put_dist_atr"]>0 else np.nan
        z["cp_balance"] = min(o["call_oi"],o["put_oi"])/max(o["call_oi"],o["put_oi"]) if np.isfinite(o["call_oi"]) and np.isfinite(o["put_oi"]) and max(o["call_oi"],o["put_oi"])>0 else np.nan
        z["gex_per_oi"] = o["net_gex"]/o["total_oi"] if np.isfinite(o["net_gex"]) and np.isfinite(o["total_oi"]) and o["total_oi"]>0 else np.nan
        if np.isfinite(o["expected_move_pct"]) and np.isfinite(z["hv20"]) and z["hv20"]>0 and np.isfinite(o["dte"]) and o["dte"]>0:
            z["implied_vs_realized"] = o["expected_move_pct"]/(z["hv20"]*math.sqrt(o["dte"]/252))
        else:
            z["implied_vs_realized"] = np.nan
        z["sector_ret20"] = sector_median.get(dt,{}).get(z["sector"],np.nan)
        for bench,bx in (("qqq",qqq),("spy",spy)):
            if bx is not None and dt in bx.index:
                z[f"{bench}_ret20"] = f(bx.loc[dt,"ret20"])
                z[f"{bench}_above_ema21"] = float(f(bx.loc[dt,"Close"]) > f(bx.loc[dt,"ema21"])) if np.isfinite(f(bx.loc[dt,"ema21"])) else np.nan
            else:
                z[f"{bench}_ret20"] = z[f"{bench}_above_ema21"] = np.nan
        for h in HORIZONS:
            ret,mfe,mae,end = get_forward(x,dt,h)
            z[f"r{h}"]=ret; z[f"mfe{h}"]=mfe; z[f"mae{h}"]=mae
            if qqq is not None and np.isfinite(ret):
                qr,_,_,_ = get_forward(qqq,dt,h)
                z[f"r{h}_exqqq"] = ret-qr if np.isfinite(qr) else np.nan
            else:
                z[f"r{h}_exqqq"] = np.nan
        z["call_touch5"],z["call_break5"] = wall_path(x,dt,o["call_wall"],"call",5)
        z["put_touch5"],z["put_break5"] = wall_path(x,dt,o["put_wall"],"put",5)
        er = expiry_return(x,dt,r.get("expiry"))
        z["expiry_return"] = er
        z["expiry_inside_expected"] = float(abs(er) <= o["expected_move_pct"]) if np.isfinite(er) and np.isfinite(o["expected_move_pct"]) else np.nan
        z["expiry_move_ratio"] = abs(er)/o["expected_move_pct"] if np.isfinite(er) and np.isfinite(o["expected_move_pct"]) and o["expected_move_pct"]>0 else np.nan

        # Reconstruct broad single-expiry portion of current Direction Bias. No historical
        # Leadership/multi-expiry look-ahead is used.
        score=50
        if np.isfinite(z["flip_dist_atr"]):
            if z["flip_dist_atr"]>.35: score += 10
            elif z["flip_dist_atr"]<-.35: score -= 10
        if np.isfinite(z["above_ema21"]): score += 8 if z["above_ema21"] else -8
        if np.isfinite(z["above_vwap63"]): score += 5 if z["above_vwap63"] else -5
        if np.isfinite(z["ret1_today"]):
            if z["ret1_today"]>=.02: score += 5
            elif z["ret1_today"]<=-.02: score -= 5
        if np.isfinite(z["wall_rr"]):
            if z["wall_rr"]>=1.4: score += 10
            elif z["wall_rr"]<=.7: score -= 10
            elif z["wall_rr"]>=1.15: score += 4
            elif z["wall_rr"]<=.87: score -= 4
        z["broad_direction_score"] = max(0,min(100,score))
        rows.append(z)
    return pd.DataFrame(rows)


def conditions(df):
    def finite(c): return df[c].notna()
    return {
        "Flip > +0.35ATR": finite("flip_dist_atr") & (df.flip_dist_atr>.35),
        "Flip < -0.35ATR": finite("flip_dist_atr") & (df.flip_dist_atr<-.35),
        "Flip near ±0.35ATR": finite("flip_dist_atr") & (df.flip_dist_atr.abs()<=.35),
        "Call Wall 0-0.5ATR": finite("call_dist_atr") & df.call_dist_atr.between(0,.5),
        "Call Wall 0.5-1ATR": finite("call_dist_atr") & df.call_dist_atr.between(.5,1, inclusive="left"),
        "Call Wall 1-2ATR": finite("call_dist_atr") & df.call_dist_atr.between(1,2, inclusive="left"),
        "Put Wall 0-0.5ATR": finite("put_dist_atr") & df.put_dist_atr.between(0,.5),
        "Put Wall 0.5-1ATR": finite("put_dist_atr") & df.put_dist_atr.between(.5,1, inclusive="left"),
        "Put Wall 1-2ATR": finite("put_dist_atr") & df.put_dist_atr.between(1,2, inclusive="left"),
        "Wall RR >=1.4": finite("wall_rr") & (df.wall_rr>=1.4),
        "Wall RR <=0.7": finite("wall_rr") & (df.wall_rr<=.7),
        "Net GEX >0": finite("net_gex") & (df.net_gex>0),
        "Net GEX <0": finite("net_gex") & (df.net_gex<0),
        "Positive gamma regime": df.regime.eq("POSITIVE_GAMMA"),
        "Negative gamma regime": df.regime.eq("NEGATIVE_GAMMA"),
        "Near flip regime": df.regime.eq("NEAR_FLIP"),
        "OI >=5k": finite("total_oi") & (df.total_oi>=5000),
        "OI >=20k": finite("total_oi") & (df.total_oi>=20000),
        "Strikes >=20": finite("n_strikes") & (df.n_strikes>=20),
        "C/P OI balance >=5%": finite("cp_balance") & (df.cp_balance>=.05),
        "Implied/realized >=1.2": finite("implied_vs_realized") & (df.implied_vs_realized>=1.2),
        "Implied/realized <=0.8": finite("implied_vs_realized") & (df.implied_vs_realized<=.8),
        "Price > EMA21": df.above_ema21.eq(1),
        "Price < EMA21": df.above_ema21.eq(0),
        "Price > 63d VWAP": df.above_vwap63.eq(1),
        "Price < 63d VWAP": df.above_vwap63.eq(0),
        "20d return >10%": finite("ret20") & (df.ret20>.10),
        "20d return <0": finite("ret20") & (df.ret20<0),
        "QQQ > EMA21": df.qqq_above_ema21.eq(1),
        "QQQ < EMA21": df.qqq_above_ema21.eq(0),
        "Sector 20d momentum >0": finite("sector_ret20") & (df.sector_ret20>0),
        "Sector 20d momentum <0": finite("sector_ret20") & (df.sector_ret20<0),
        "Large move day |r|>=5%": finite("ret1_today") & (df.ret1_today.abs()>=.05),
        "Normal move day |r|<5%": finite("ret1_today") & (df.ret1_today.abs()<.05),
        "Broad Direction score >=68": finite("broad_direction_score") & (df.broad_direction_score>=68),
        "Broad Direction score <=32": finite("broad_direction_score") & (df.broad_direction_score<=32),
        "Bull combo Flip+/EMA/VWAP/RR": finite("flip_dist_atr") & (df.flip_dist_atr>.35) & df.above_ema21.eq(1) & df.above_vwap63.eq(1) & finite("wall_rr") & (df.wall_rr>=1.15),
        "Bear combo Flip-/EMA/VWAP/RR": finite("flip_dist_atr") & (df.flip_dist_atr<-.35) & df.above_ema21.eq(0) & df.above_vwap63.eq(0) & finite("wall_rr") & (df.wall_rr<=.87),
        "GEX+ & Flip above": finite("net_gex") & (df.net_gex>0) & finite("flip_dist_atr") & (df.flip_dist_atr>.35),
        "GEX- & Flip below": finite("net_gex") & (df.net_gex<0) & finite("flip_dist_atr") & (df.flip_dist_atr<-.35),
    }


def run_event_study(df):
    rows=[]
    conds=conditions(df)
    for name,mask in conds.items():
        z=df[mask].copy()
        for h in HORIZONS:
            col=f"r{h}_exqqq"
            q=z[col].dropna()
            if len(q)<8:
                continue
            mean,lo,hi=cluster_boot_ci(z,col)
            rows.append({
                "condition":name,"horizon":h,"n":int(len(q)),"dates":int(z.loc[q.index,"date"].nunique()),
                "tickers":int(z.loc[q.index,"ticker"].nunique()),"mean_exqqq":mean,"ci_lo":lo,"ci_hi":hi,
                "raw_mean":float(z.loc[q.index,f"r{h}"].mean()),"median_exqqq":float(q.median()),
                "win_exqqq":float((q>0).mean()),"p_boot":sign_pvalue_boot(z,col),
            })
    out=pd.DataFrame(rows)
    if not out.empty:
        out["q_bh"] = bh_qvalues(out.p_boot.to_numpy())
        out=out.sort_values(["horizon","q_bh","mean_exqqq"],ascending=[True,True,False])
    return out


def wall_stats(df):
    rows=[]
    for side,dist,touch,brk in [
        ("Call","call_dist_atr","call_touch5","call_break5"),
        ("Put","put_dist_atr","put_touch5","put_break5"),
    ]:
        for label,lo,hi in [("0-0.5ATR",0,.5),("0.5-1ATR",.5,1),("1-2ATR",1,2),("2ATR+",2,999)]:
            z=df[df[dist].between(lo,hi,inclusive="left")].copy()
            if len(z)<5: continue
            rows.append({
                "side":side,"distance":label,"n":len(z),"dates":z.date.nunique(),
                "touch5":z[touch].mean(),"break5":z[brk].mean(),
                "hold_given_touch":1-z.loc[z[touch].eq(1),brk].mean() if z[touch].eq(1).any() else np.nan,
                "mean_r5":z.r5.mean(),"mean_r5_exqqq":z.r5_exqqq.mean(),
            })
    return pd.DataFrame(rows)


def expected_move_stats(df):
    z=df[df.expiry_inside_expected.notna()].copy()
    if z.empty: return pd.DataFrame()
    z["iv_bucket"] = pd.cut(z.implied_vs_realized,[-np.inf,.8,1.2,np.inf],labels=["<=0.8","0.8-1.2",">=1.2"])
    rows=[]
    for name,g in [("ALL",z),*[(str(k),v) for k,v in z.groupby("iv_bucket",observed=True)]]:
        if len(g)<4: continue
        rows.append({"bucket":name,"n":len(g),"dates":g.date.nunique(),"inside_expected":g.expiry_inside_expected.mean(),
                     "median_realized_over_expected":g.expiry_move_ratio.median(),"mean_realized_over_expected":g.expiry_move_ratio.mean()})
    return pd.DataFrame(rows)


def direction_stats(df):
    rows=[]
    for label,mask,sign in [
        ("UP >=68",df.broad_direction_score>=68,1),
        ("DOWN <=32",df.broad_direction_score<=32,-1),
        ("MID 33-67",df.broad_direction_score.between(33,67),0),
    ]:
        z=df[mask]
        for h in HORIZONS:
            q=z[f"r{h}_exqqq"].dropna()
            if len(q)<5: continue
            mean,lo,hi=cluster_boot_ci(z,f"r{h}_exqqq")
            directional = q*sign if sign else q.abs()*0
            rows.append({"bucket":label,"horizon":h,"n":len(q),"dates":z.loc[q.index,"date"].nunique(),
                         "mean_exqqq":mean,"ci_lo":lo,"ci_hi":hi,"win_exqqq":float((q>0).mean()),
                         "directional_hit":float((directional>0).mean()) if sign else np.nan})
    return pd.DataFrame(rows)


def fmt_pct(x):
    return "—" if not np.isfinite(x) else f"{x*100:.2f}%"


def write_report(events, df, tests, walls, em, dirs, missing):
    OUTDIR.mkdir(parents=True,exist_ok=True)
    df.to_csv(OUTDIR/"event_features.csv",index=False)
    tests.to_csv(OUTDIR/"event_study.csv",index=False)
    walls.to_csv(OUTDIR/"wall_behavior.csv",index=False)
    em.to_csv(OUTDIR/"expected_move_calibration.csv",index=False)
    dirs.to_csv(OUTDIR/"direction_score_validation.csv",index=False)

    dates=sorted(df.date.dropna().unique())
    earliest=str(pd.Timestamp(dates[0]).date()) if dates else "—"
    latest=str(pd.Timestamp(dates[-1]).date()) if dates else "—"
    lines=[
        "# Options Intelligence structure backtest — 2026-09-05",
        "",
        "## Scope / guardrails",
        "",
        "Research only. No production V38 / Dashboard / Rotation / Options ranking code was changed.",
        "Historical option-chain snapshots are not reconstructed: only snapshots already stored in `options_scan_history.csv` / `options_history.csv` are used. Historical OHLCV is fetched only to calculate contemporaneous technical context and subsequent underlying returns.",
        "",
        "## Data audit",
        "",
        f"- Raw option event rows after same ticker/day collapse: {len(events):,}",
        f"- Events matched to underlying daily OHLCV: {len(df):,}",
        f"- Unique tickers: {df.ticker.nunique():,}",
        f"- Option snapshot dates: {earliest} to {latest} ({df.date.nunique()} sessions)",
        f"- Price-download failures after retries: {len(missing)}",
        f"- Forward-return availability: " + ", ".join(f"{h}d={df[f'r{h}'].notna().sum():,}" for h in HORIZONS),
        "",
        "> Limitation: the snapshot history is short. Cross-sectional N can be large, but independent time clusters are few. Therefore the results below are exploratory and are **not sufficient by themselves for production rule adoption**. Confidence intervals use moving-block resampling by observation date; multiple tests use Benjamini-Hochberg q-values.",
        "",
        "## Current broad Direction score",
        "",
    ]
    if dirs.empty:
        lines.append("No sufficient forward samples.")
    else:
        lines.append("|Bucket|Horizon|N|Dates|Mean ex-QQQ|95% block CI|Directional hit|")
        lines.append("|---|---:|---:|---:|---:|---:|---:|")
        for _,r in dirs.iterrows():
            lines.append(f"|{r.bucket}|{int(r.horizon)}d|{int(r.n)}|{int(r.dates)}|{fmt_pct(r.mean_exqqq)}|{fmt_pct(r.ci_lo)} to {fmt_pct(r.ci_hi)}|{fmt_pct(r.directional_hit)}|")
    lines += ["","## Strongest exploratory effects (5-day ex-QQQ)",""]
    t5=tests[(tests.horizon==5)&(tests.n>=15)].copy() if not tests.empty else pd.DataFrame()
    if t5.empty:
        lines.append("No sufficient 5-day samples.")
    else:
        t5=t5.sort_values("q_bh").head(15)
        lines.append("|Condition|N|Dates|Mean ex-QQQ|95% block CI|Win|q(BH)|")
        lines.append("|---|---:|---:|---:|---:|---:|---:|")
        for _,r in t5.iterrows():
            q="—" if not np.isfinite(r.q_bh) else f"{r.q_bh:.3f}"
            lines.append(f"|{r.condition}|{int(r.n)}|{int(r.dates)}|{fmt_pct(r.mean_exqqq)}|{fmt_pct(r.ci_lo)} to {fmt_pct(r.ci_hi)}|{fmt_pct(r.win_exqqq)}|{q}|")
    lines += ["","## Wall behavior within next 5 sessions","","|Side|Distance|N|Touch|Close-break|Hold given touch|Mean 5d ex-QQQ|","|---|---:|---:|---:|---:|---:|---:|"]
    for _,r in walls.iterrows():
        lines.append(f"|{r.side}|{r.distance}|{int(r.n)}|{fmt_pct(r.touch5)}|{fmt_pct(r.break5)}|{fmt_pct(r.hold_given_touch)}|{fmt_pct(r.mean_r5_exqqq)}|")
    lines += ["","## Expected Move calibration to expiry","","|Implied/HV bucket|N|Inside expected range|Median realized / expected|","|---|---:|---:|---:|"]
    for _,r in em.iterrows():
        ratio="—" if not np.isfinite(r.median_realized_over_expected) else f"{r.median_realized_over_expected:.2f}x"
        lines.append(f"|{r.bucket}|{int(r.n)}|{fmt_pct(r.inside_expected)}|{ratio}|")

    # Programmatic conclusions with conservative criteria.
    lines += ["", "## Research conclusions", ""]
    conclusions=[]
    if not tests.empty:
        robust=tests[(tests.n>=20)&(tests.dates>=4)&(tests.q_bh<=.10)&((tests.ci_lo>0)|(tests.ci_hi<0))]
        if robust.empty:
            conclusions.append("- No tested condition clears the pre-set exploratory robustness bar (N>=20, >=4 dates, BH q<=0.10, block CI excluding zero). Do not add a new production weight from this sample.")
        else:
            for _,r in robust.sort_values("q_bh").head(8).iterrows():
                conclusions.append(f"- {r.condition}, {int(r.horizon)}d: ex-QQQ {fmt_pct(r.mean_exqqq)} (N={int(r.n)}, dates={int(r.dates)}, q={r.q_bh:.3f}). Candidate for a longer validation, not automatic adoption.")
    if not dirs.empty:
        up5=dirs[(dirs.bucket=="UP >=68")&(dirs.horizon==5)]
        dn5=dirs[(dirs.bucket=="DOWN <=32")&(dirs.horizon==5)]
        if not up5.empty:
            r=up5.iloc[0]; conclusions.append(f"- Current broad UP score 5d mean ex-QQQ: {fmt_pct(r.mean_exqqq)} (N={int(r.n)}, dates={int(r.dates)}).")
        if not dn5.empty:
            r=dn5.iloc[0]; conclusions.append(f"- Current broad DOWN score 5d mean ex-QQQ: {fmt_pct(r.mean_exqqq)}; directional hit {fmt_pct(r.directional_hit)} (N={int(r.n)}, dates={int(r.dates)}).")
    if not em.empty:
        r=em[em.bucket=="ALL"]
        if not r.empty:
            q=r.iloc[0]; conclusions.append(f"- Expected Move calibration: {fmt_pct(q.inside_expected)} of completed expiries finished inside the implied range; median realized/expected={q.median_realized_over_expected:.2f}x (N={int(q.n)}).")
    conclusions.append("- Net GEX sign is evaluated as an empirical feature only. Because free OI does not identify dealer long/short side, even a statistical association would not justify interpreting positive Net GEX as inherently bullish.")
    conclusions.append("- Historical earnings calendars are not reliably recoverable from the free provider in this run. A |daily return|>=5% event-proxy is tested instead; this must not be relabeled as an earnings test.")
    lines += conclusions
    lines += ["","## Next evidence threshold","","Accumulate daily all-liquid snapshots. Re-run after at least ~40 independent market sessions, and again after ~120 sessions. Production changes should require effect-sign stability across time splits plus date-clustered confidence intervals, not only a large cross-sectional ticker count.",""]
    (OUTDIR/"REPORT.md").write_text("\n".join(lines),encoding="utf-8")
    summary={
        "raw_events":len(events),"matched_events":len(df),"tickers":int(df.ticker.nunique()) if len(df) else 0,
        "dates":int(df.date.nunique()) if len(df) else 0,"earliest":earliest,"latest":latest,
        "missing_prices":missing,"forward_counts":{str(h):int(df[f"r{h}"].notna().sum()) for h in HORIZONS},
    }
    (OUTDIR/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")


def main():
    OUTDIR.mkdir(parents=True,exist_ok=True)
    events=load_events()
    meta=load_universe()
    if events.empty:
        raise SystemExit("No Options history rows")
    start=(events.date.min()-pd.Timedelta(days=100)).date().isoformat()
    # Current UTC date plus a few days so yf end is inclusive enough for last completed session.
    end=(pd.Timestamp.utcnow().tz_localize(None).normalize()+pd.Timedelta(days=3)).date().isoformat()
    tickers=sorted(set(events.ticker) | {"QQQ","SPY"})
    raw,missing=yf_batch(tickers,start,end)
    prices={tk:normalize_price(tk,x) for tk,x in raw.items()}
    prices={tk:x for tk,x in prices.items() if x is not None}
    frame=build_event_frame(events,prices,meta)
    if frame.empty:
        raise SystemExit("No matched event/price rows")
    tests=run_event_study(frame)
    walls=wall_stats(frame)
    em=expected_move_stats(frame)
    dirs=direction_stats(frame)
    write_report(events,frame,tests,walls,em,dirs,missing)
    print(json.dumps({
        "events":len(events),"matched":len(frame),"dates":frame.date.nunique(),"tickers":frame.ticker.nunique(),
        "forward":{h:int(frame[f"r{h}"].notna().sum()) for h in HORIZONS},"price_failures":len(missing),
    },ensure_ascii=False))


if __name__ == "__main__":
    main()
