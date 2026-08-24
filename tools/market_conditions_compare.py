#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

START = "2014-01-01"
END = "2026-08-23"
EVAL_START = "2016-01-01"

BROAD = ["SPY","QQQ","DIA","IWM","MDY","RSP"]
SECTORS = ["XLK","XLY","VOX","XLF","XLI","XLE","XLB","XLV","XLP","XLU","XLRE"]
INDUSTRY_PARENT = {
    "Technology": ["SOXX","IGV","CIBR","SKYY","FDN"],
    "Health Care": ["XBI","IBB","PPH"],
    "Financials": ["KRE","KBE"],
    "Consumer Discretionary": ["XRT","ITB","XHB"],
    "Industrials": ["IYT","ITA","ROBO","JETS"],
    "Materials": ["XME","COPX","GDX","SIL","LIT"],
    "Energy": ["XOP","OIH","URA"],
    "Clean Energy": ["TAN"],
}
INDUSTRIES = [t for xs in INDUSTRY_PARENT.values() for t in xs]
MC_UNIVERSE = BROAD + SECTORS + INDUSTRIES
assert len(MC_UNIVERSE) == 43

MRI_EXTRA = ["QQQE","HYG","LQD","^VIX","^VIX3M","^VVIX"]
ALL = list(dict.fromkeys(MC_UNIVERSE + MRI_EXTRA))

BANDS = [
    (-np.inf, 20, "STRONG BEAR"),
    (20, 35, "BEAR"),
    (35, 45, "WEAK BEAR"),
    (45, 55, "NEUTRAL"),
    (55, 65, "WEAK BULL"),
    (65, 80, "BULL"),
    (80, np.inf, "STRONG BULL"),
]
BAND_ORDER = [x[2] for x in BANDS]

def download_prices() -> tuple[pd.DataFrame, list[str]]:
    closes: dict[str, pd.Series] = {}
    failed: list[str] = []
    for i, ticker in enumerate(ALL, 1):
        try:
            d = yf.download(ticker, start=START, end=END, auto_adjust=True,
                            progress=False, threads=False, timeout=20)
            if d is None or d.empty:
                failed.append(ticker); continue
            if isinstance(d.columns, pd.MultiIndex):
                if ("Close", ticker) in d.columns:
                    s = d[("Close", ticker)]
                elif "Close" in d.columns.get_level_values(0):
                    s = d.xs("Close", axis=1, level=0).iloc[:, 0]
                else:
                    failed.append(ticker); continue
            else:
                if "Close" not in d:
                    failed.append(ticker); continue
                s = d["Close"]
            s = pd.to_numeric(s, errors="coerce").dropna()
            if not s.empty:
                s.name = ticker; closes[ticker] = s
            else:
                failed.append(ticker)
        except Exception as e:
            print(f"[warn] {ticker}: {e}")
            failed.append(ticker)
        print(f"[download] {i}/{len(ALL)} {ticker} {'ok' if ticker in closes else 'FAIL'}")
    if "QQQ" not in closes:
        raise RuntimeError("QQQ download failed")
    px = pd.concat(closes.values(), axis=1).sort_index()
    px.index = pd.to_datetime(px.index).tz_localize(None)
    return px, failed

def clamp01(x):
    return np.clip(x, 0.0, 1.0)

def linear_score(s, lo, hi):
    return clamp01((s - lo) / (hi - lo))

def blend(parts, min_cov=0.0):
    idx = None
    for s, _ in parts:
        idx = s.index if idx is None else idx.union(s.index)
    num = pd.Series(0.0, index=idx); den = pd.Series(0.0, index=idx)
    total = sum(w for _, w in parts)
    for s, w in parts:
        x = pd.to_numeric(s, errors="coerce").reindex(idx); ok = x.notna()
        num = num.add(x.fillna(0) * w, fill_value=0)
        den = den.add(ok.astype(float) * w, fill_value=0)
    out = num / den.replace(0, np.nan)
    if min_cov:
        out = out.where(den / total >= min_cov)
    return out

def vol_percentile_score(s):
    s = pd.to_numeric(s, errors="coerce")
    q_bear = s.rolling(252, min_periods=120).quantile(0.85)
    q_bull = s.rolling(252, min_periods=120).quantile(0.15)
    return clamp01((s - q_bear) / (q_bull - q_bear))

def comparison_breadth(px: pd.DataFrame) -> pd.DataFrame:
    c = px.reindex(columns=[x for x in MC_UNIVERSE if x in px])
    out = pd.DataFrame(index=px.index)
    ma50 = c.rolling(50).mean(); ma200 = c.rolling(200).mean()
    v50 = ma50.notna().sum(axis=1); v200 = ma200.notna().sum(axis=1)
    out["pa50"] = c.gt(ma50).sum(axis=1) / v50.replace(0,np.nan) * 100
    out["pa200"] = c.gt(ma200).sum(axis=1) / v200.replace(0,np.nan) * 100
    ret = c.pct_change(fill_method=None); den = ret.notna().sum(axis=1)
    adv = ret.gt(0).sum(axis=1) / den.replace(0,np.nan) * 100
    out["ad20"] = adv.rolling(20, min_periods=10).mean()
    return out

def current_mri_standardized(px: pd.DataFrame) -> pd.DataFrame:
    """Current V38 Market Health v2; historical stock breadth standardized to the fixed 43-ETF universe."""
    idx = px.index
    def s(t): return px[t] if t in px else pd.Series(np.nan, index=idx)
    qqq, spy, rsp, qqqe = s("QQQ"), s("SPY"), s("RSP"), s("QQQE")
    hyg, lqd, iwm = s("HYG"), s("LQD"), s("IWM")
    vix, vix3m, vvix = s("^VIX"), s("^VIX3M"), s("^VVIX")
    hyglqd = hyg/lqd; rspspy = rsp/spy; iwmspy = iwm/spy; qqqeqqq = qqqe/qqq
    b = comparison_breadth(px)
    vals = pd.DataFrame(index=idx)
    vals["qqq_50"] = qqq/qqq.rolling(50).mean()-1
    vals["qqq_200"] = qqq/qqq.rolling(200).mean()-1
    vals["spy_200"] = spy/spy.rolling(200).mean()-1
    vals["rsp_50"] = rsp/rsp.rolling(50).mean()-1
    vals["rsp_200"] = rsp/rsp.rolling(200).mean()-1
    vals["qqqe_50"] = qqqe/qqqe.rolling(50).mean()-1
    vals["rsp_spy_20"] = rspspy/rspspy.rolling(20).mean()
    vals["iwm_spy_20"] = iwmspy/iwmspy.rolling(20).mean()
    vals["qqqe_qqq_20"] = qqqeqqq/qqqeqqq.rolling(20).mean()
    vals["vix"] = vix; vals["vix_ratio"] = vix/vix3m; vals["vvix"] = vvix
    vals["hyglqd_20"] = hyglqd/hyglqd.rolling(20).mean()
    vals["hyglqd_5d"] = hyglqd/hyglqd.shift(5)-1
    vals["uni_pa50"] = b["pa50"]; vals["uni_pa200"] = b["pa200"]; vals["uni_ad20"] = b["ad20"]
    cap_trend = blend([
        (linear_score(vals["qqq_50"],-.03,.10),.40),
        (linear_score(vals["qqq_200"],-.05,.10),.35),
        (linear_score(vals["spy_200"],-.05,.10),.25)], .5)
    broad_trend = blend([
        (linear_score(vals["rsp_50"],-.03,.07),.40),
        (linear_score(vals["rsp_200"],-.05,.10),.35),
        (linear_score(vals["qqqe_50"],-.03,.09),.25)], .5)
    trend = blend([(cap_trend,.5),(broad_trend,.5)])
    uni = blend([
        (linear_score(vals["uni_pa50"],30,75),.40),
        (linear_score(vals["uni_pa200"],30,75),.40),
        (linear_score(vals["uni_ad20"],45,55),.20)], .5)
    rel = blend([
        (linear_score(vals["rsp_spy_20"],.98,1.02),1),
        (linear_score(vals["qqqe_qqq_20"],.98,1.02),1),
        (linear_score(vals["iwm_spy_20"],.98,1.02),1)])
    breadth = blend([(uni,.70),(rel,.30)])
    risk = blend([
        (vol_percentile_score(vals["vix"]),.45),
        (linear_score(vals["vix_ratio"],1.05,.95),.35),
        (vol_percentile_score(vals["vvix"]),.20)], .5)
    credit = blend([
        (linear_score(vals["hyglqd_20"],.98,1.02),.65),
        (linear_score(vals["hyglqd_5d"],-.02,.02),.35)])
    score = blend([(trend,30),(breadth,30),(risk,20),(credit,20)])*100
    return pd.DataFrame({"score":score,"trend":trend*100,"breadth":breadth*100,"risk":risk*100,"credit":credit*100})

def available(cols, frame): return [c for c in cols if c in frame.columns]

def parent_industry_ratio(mask: pd.DataFrame) -> pd.Series:
    parents=[]
    for tickers in INDUSTRY_PARENT.values():
        cols=available(tickers,mask)
        if cols: parents.append(mask[cols].mean(axis=1))
    return pd.concat(parents,axis=1).mean(axis=1) if parents else pd.Series(np.nan,index=mask.index)

def participation(mask: pd.DataFrame) -> pd.Series:
    pieces=[]
    for cols in (BROAD,SECTORS):
        a=available(cols,mask)
        if a: pieces.append(mask[a].mean(axis=1))
    pieces.append(parent_industry_ratio(mask))
    return pd.concat(pieces,axis=1).mean(axis=1)

def participation_score(ratio): return linear_score(ratio,.30,.70)*100

def parent_industry_median(frame: pd.DataFrame) -> pd.Series:
    parents=[]
    for tickers in INDUSTRY_PARENT.values():
        cols=available(tickers,frame)
        if cols: parents.append(frame[cols].median(axis=1))
    return pd.concat(parents,axis=1).mean(axis=1) if parents else pd.Series(np.nan,index=frame.index)

def stratified_median(frame: pd.DataFrame) -> pd.Series:
    pieces=[]
    for cols in (BROAD,SECTORS):
        a=available(cols,frame)
        if a: pieces.append(frame[a].median(axis=1))
    pieces.append(parent_industry_median(frame))
    return pd.concat(pieces,axis=1).mean(axis=1)

def new_mc(px: pd.DataFrame) -> pd.DataFrame:
    c=px.reindex(columns=available(MC_UNIVERSE,px))
    ma10=c.rolling(10).mean(); ma20=c.rolling(20).mean(); ma50=c.rolling(50).mean(); ma200=c.rolling(200).mean()
    parts={}
    parts["ret5"]=participation_score(participation(c/c.shift(5)-1>0))
    parts["above10"]=participation_score(participation(c>ma10))
    parts["above20"]=participation_score(participation(c>ma20))
    short=pd.concat([parts["ret5"],parts["above10"],parts["above20"]],axis=1).mean(axis=1)
    parts["ret21"]=participation_score(participation(c/c.shift(21)-1>0))
    parts["ret63"]=participation_score(participation(c/c.shift(63)-1>0))
    parts["above50"]=participation_score(participation(c>ma50))
    parts["ma20_gt_50"]=participation_score(participation(ma20>ma50))
    parts["ma50_rising"]=participation_score(participation(ma50>ma50.shift(20)))
    medium=pd.concat([parts[k] for k in ["ret21","ret63","above50","ma20_gt_50","ma50_rising"]],axis=1).mean(axis=1)
    parts["above200"]=participation_score(participation(c>ma200))
    parts["ma50_gt_200"]=participation_score(participation(ma50>ma200))
    long=pd.concat([parts["above200"],parts["ma50_gt_200"]],axis=1).mean(axis=1)
    hi252=c.rolling(252,min_periods=200).max(); dd=c/hi252-1
    med_dd=stratified_median(dd); dd_score=linear_score(med_dd,-.30,-.05)*100
    within10=participation_score(participation(dd>=-.10))
    damage=pd.concat([dd_score,within10],axis=1).mean(axis=1)
    raw=short*.20+medium*.40+long*.30+damage*.10
    score=raw.ewm(span=2,adjust=False).mean()
    out=pd.DataFrame({"score":score,"raw":raw,"short":short,"medium":medium,"long":long,"damage":damage})
    for k,v in parts.items(): out[k]=v
    out["median_dd"]=med_dd*100
    return out

def oratnek_like(px: pd.DataFrame, vix_threshold=20.0, dd_threshold=-.10) -> pd.DataFrame:
    """Public-description approximation; exact private thresholds are unknown."""
    c=px.reindex(columns=available(MC_UNIVERSE,px))
    ma10=c.rolling(10).mean(); ma20=c.rolling(20).mean(); ma50=c.rolling(50).mean(); ma200=c.rolling(200).mean()
    vix=px["^VIX"] if "^VIX" in px else pd.Series(np.nan,index=px.index)
    first=c.groupby(c.index.year).transform("first"); ytd=c/first-1
    hi252=c.rolling(252,min_periods=200).max(); dd=c/hi252-1
    votes=pd.DataFrame(index=c.index)
    votes["ytd"]=(ytd.mean(axis=1)>0).astype(float)
    votes["1w"]=((c/c.shift(5)-1).mean(axis=1)>0).astype(float)
    votes["1m"]=((c/c.shift(21)-1).mean(axis=1)>0).astype(float)
    votes["1y"]=((c/c.shift(252)-1).mean(axis=1)>0).astype(float)
    votes["above10"]=((c>ma10).mean(axis=1)>.50).astype(float)
    votes["above20"]=((c>ma20).mean(axis=1)>.50).astype(float)
    votes["above50"]=((c>ma50).mean(axis=1)>.50).astype(float)
    votes["above200"]=((c>ma200).mean(axis=1)>.50).astype(float)
    votes["20gt50"]=((ma20>ma50).mean(axis=1)>.50).astype(float)
    votes["50gt200"]=((ma50>ma200).mean(axis=1)>.50).astype(float)
    votes["drawdown"]=(dd.mean(axis=1)>dd_threshold).astype(float)
    votes["vix"]=(vix<vix_threshold).astype(float).where(vix.notna())
    raw=votes.mean(axis=1,skipna=True)*100
    score=raw.ewm(span=2,adjust=False).mean()
    return pd.concat([pd.DataFrame({"score":score,"raw":raw}),votes.add_prefix("vote_")],axis=1)

def band(score):
    if pd.isna(score): return None
    for lo,hi,name in BANDS:
        if score>=lo and score<hi: return name
    return None

def forward_stats(score: pd.Series, qqq: pd.Series):
    d=pd.DataFrame({"score":score,"qqq":qqq}).dropna(subset=["score","qqq"]).copy()
    d["fwd10"]=d["qqq"].shift(-10)/d["qqq"]-1; d["fwd20"]=d["qqq"].shift(-20)/d["qqq"]-1
    arr=d["qqq"].to_numpy(); worst=np.full(len(d),np.nan)
    for i in range(len(d)-20): worst[i]=np.min(arr[i+1:i+21]/arr[i]-1)
    d["fwd20_worst"]=worst; d["band"]=d["score"].map(band)
    rows=[]
    for b in BAND_ORDER:
        x=d[d["band"]==b]
        rows.append({"band":b,"n":int(x["fwd20"].notna().sum()),
                     "score_mean":float(x["score"].mean()) if len(x) else None,
                     "fwd10_mean_pct":float(x["fwd10"].mean()*100) if len(x) else None,
                     "fwd20_mean_pct":float(x["fwd20"].mean()*100) if len(x) else None,
                     "fwd20_win_pct":float((x["fwd20"]>0).mean()*100) if x["fwd20"].notna().any() else None,
                     "fwd20_worst_mean_pct":float(x["fwd20_worst"].mean()*100) if len(x) else None})
    bt=pd.DataFrame(rows); valid=bt[bt["n"]>=30]; vals=valid["fwd20_mean_pct"].to_numpy()
    violations=int(np.sum(np.diff(vals)<0)) if len(vals)>1 else None
    top=d[d["score"]>=65]; bot=d[d["score"]<=35]
    headline={"valid_days":int(len(d)),"score_mean":float(d["score"].mean()),"score_std":float(d["score"].std()),
              "score_p05":float(d["score"].quantile(.05)),"score_p95":float(d["score"].quantile(.95)),
              "mean_abs_daily_change":float(d["score"].diff().abs().mean()),
              "regime_changes_per_year":float((d["band"]!=d["band"].shift()).sum()/max((d.index[-1]-d.index[0]).days/365.25,1)),
              "monotonic_violations_fwd20":violations,
              "bull_fwd20_pct":float(top["fwd20"].mean()*100),"bear_fwd20_pct":float(bot["fwd20"].mean()*100),
              "bull_minus_bear_fwd20_pct":float((top["fwd20"].mean()-bot["fwd20"].mean())*100),
              "bull_fwd20_worst_pct":float(top["fwd20_worst"].mean()*100),"bear_fwd20_worst_pct":float(bot["fwd20_worst"].mean()*100)}
    return bt,headline

def crash_events(qqq: pd.Series):
    s=qqq.dropna(); running=s.cummax(); dd=s/running-1; events=[]; in_event=False; start_i=None
    for i,(dt,v) in enumerate(dd.items()):
        if not in_event and v<=-.15: in_event=True; start_i=i
        if in_event and (v>=-.05 or i==len(dd)-1):
            left=max(0,start_i-60); seg=s.iloc[left:i+1]; cross_pos=start_i-left
            peak_dt=seg.iloc[:cross_pos+1].idxmax(); post=seg.loc[peak_dt:]; trough_dt=post.idxmin()
            events.append({"peak":str(peak_dt.date()),"trough":str(trough_dt.date()),"dd_pct":float((s.loc[trough_dt]/s.loc[peak_dt]-1)*100)})
            in_event=False
    out=[]
    for e in events:
        if not out or e["peak"]!=out[-1]["peak"]: out.append(e)
    return out

def event_lags(score, qqq, events):
    idx=score.index; out=[]
    for e in events:
        peak=pd.Timestamp(e["peak"]); trough=pd.Timestamp(e["trough"])
        w=score.loc[(idx>=peak)&(idx<=trough+pd.Timedelta(days=45))].dropna(); bear=w[w<=35]; det=bear.index[0] if len(bear) else None
        r=score.loc[(idx>=trough)&(idx<=trough+pd.Timedelta(days=180))].dropna(); bull=r[r>=55]; rec=bull.index[0] if len(bull) else None
        def sessions(a,b):
            if a is None: return None
            return max(len(qqq.loc[(qqq.index>=b)&(qqq.index<=a)].dropna())-1,0)
        out.append({**e,"bear_date":str(det.date()) if det is not None else None,"bear_sessions_from_peak":sessions(det,peak),
                    "recovery_date":str(rec.date()) if rec is not None else None,"recovery_sessions_from_trough":sessions(rec,trough)})
    return out

def nq_overlap(scores):
    p=Path("daily_log.csv")
    if not p.exists(): return {}
    log=pd.read_csv(p); log["date"]=pd.to_datetime(log["date"]); out={}
    for name,s in scores.items():
        z=pd.DataFrame({"date":s.index,"score":s.values}); m=log[["date","gate"]].merge(z,on="date",how="inner").dropna(); by={}
        for g,x in m.groupby("gate"):
            by[str(g)]={"n":int(len(x)),"mean":float(x["score"].mean()),"min":float(x["score"].min()),"max":float(x["score"].max())}
        out[name]={"n":int(len(m)),"by_gate":by,
                   "yellow_red_with_score_ge65":int(((m["gate"].isin(["Yellow","Red"]))&(m["score"]>=65)).sum()),
                   "blue_green_with_score_le35":int(((m["gate"].isin(["Blue","Green"]))&(m["score"]<=35)).sum())}
    return out

def main():
    px,failed=download_prices(); mc_cov=[x for x in MC_UNIVERSE if x in px]
    if len(mc_cov)<36: raise RuntimeError(f"too few MC tickers: {len(mc_cov)}/43, failed={failed}")
    current=current_mri_standardized(px); ora=oratnek_like(px); new=new_mc(px); qqq=px["QQQ"]
    eval_mask=(px.index>=pd.Timestamp(EVAL_START))&(px.index<=pd.Timestamp("2026-08-21"))
    methods={"current_mri_standardized":current["score"].where(eval_mask),"oratnek_like":ora["score"].where(eval_mask),"new_mc_v1":new["score"].where(eval_mask)}
    events=crash_events(qqq.loc[eval_mask]); summary={}; bands={}; lags={}
    for name,s in methods.items():
        bt,head=forward_stats(s,qqq); summary[name]=head; bands[name]=bt.to_dict(orient="records"); lags[name]=event_lags(s,qqq,events)
    sensitivity={}
    for vt in [18,20,22]:
        for dd in [-.08,-.10,-.12]:
            k=f"vix{vt}_dd{int(abs(dd)*100)}"; ss=oratnek_like(px,vt,dd)["score"].where(eval_mask); _,h=forward_stats(ss,qqq)
            sensitivity[k]={"bull_minus_bear_fwd20_pct":h["bull_minus_bear_fwd20_pct"],"mean_abs_daily_change":h["mean_abs_daily_change"],"regime_changes_per_year":h["regime_changes_per_year"]}
    daily=pd.DataFrame(methods); daily["qqq"]=qqq; daily["qqq_fwd10"]=qqq.shift(-10)/qqq-1; daily["qqq_fwd20"]=qqq.shift(-20)/qqq-1
    daily=daily.loc[eval_mask]; daily.to_csv("market_conditions_compare_daily.csv",index_label="date")
    result={"scope":{"price_source":"Yahoo Finance via yfinance, adjusted daily close","download_start":START,"evaluation_start":EVAL_START,"evaluation_end":"2026-08-21",
                     "universe_count":len(MC_UNIVERSE),"covered_mc_count":len(mc_cov),"covered_mc_tickers":mc_cov,"failed_tickers":failed,
                     "current_mri_note":"Current Market Health v2 weights/formulas reproduced; point-in-time V38 stock-universe breadth is unavailable historically, so its breadth input is standardized to the same fixed 43-ETF comparison universe.",
                     "oratnek_note":"Oratnek-like uses the 12 publicly described metrics with transparent neutral thresholds: breadth/MA structure >50%, returns >0, mean 52w drawdown >-10%, VIX<20. Exact private thresholds are unknown.",
                     "new_mc_note":"43 ETFs, stratified Broad/Sector/Industry-parent; Short20/Medium40/Long30/Damage10; continuous 30%-70% participation scaling; EMA2."},
            "summary":summary,"band_stats":bands,"crash_events":events,"event_lags":lags,"nqsar_overlap_2026":nq_overlap(methods),
            "oratnek_threshold_sensitivity":sensitivity,
            "latest":{k:{"date":str(v.dropna().index[-1].date()),"score":float(v.dropna().iloc[-1]),"band":band(float(v.dropna().iloc[-1])),
                         "delta5":float(v.dropna().iloc[-1]-v.dropna().iloc[-6]) if len(v.dropna())>=6 else None} for k,v in methods.items()},
            "new_mc_latest_components":{k:float(new[k].dropna().iloc[-1]) for k in ["short","medium","long","damage","median_dd"] if new[k].notna().any()}}
    Path("market_conditions_compare_results.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(result["summary"],ensure_ascii=False,indent=2)); print("latest",json.dumps(result["latest"],ensure_ascii=False,indent=2)); print("failed",failed)

if __name__=="__main__": main()
