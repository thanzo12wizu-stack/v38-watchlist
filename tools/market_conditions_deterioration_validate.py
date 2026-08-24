#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

START = "2014-01-01"
END = "2026-08-25"  # yfinance end is exclusive; includes 2026-08-24
EVAL_START = pd.Timestamp("2016-01-01")
EVAL_END = pd.Timestamp("2026-08-24")
ROOT = Path(__file__).resolve().parents[1]

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
INDUSTRIES = [x for xs in INDUSTRY_PARENT.values() for x in xs]
UNIVERSE = BROAD + SECTORS + INDUSTRIES
assert len(UNIVERSE) == 43

BANDS = [
    (-np.inf,20,"STRONG BEAR"),(20,35,"BEAR"),(35,45,"WEAK BEAR"),
    (45,55,"NEUTRAL"),(55,65,"WEAK BULL"),(65,80,"BULL"),(80,np.inf,"STRONG BULL")
]

CANDIDATES = {
    # medium_level_weight, deterioration_weight, deterioration source
    "baseline_15552010": (1.00, 0.00, "none"),
    "det20_20pct":       (0.80, 0.20, "d20"),
    "det20_30pct":       (0.70, 0.30, "d20"),
    "det20_40pct":       (0.60, 0.40, "d20"),
    "det1020_30pct":     (0.70, 0.30, "multi"),
}


def band(x: float) -> str:
    for lo,hi,name in BANDS:
        if lo <= x < hi:
            return name
    return "N/A"


def download_prices() -> tuple[pd.DataFrame,list[str]]:
    out={}; failed=[]
    for i,t in enumerate(UNIVERSE,1):
        ok=False
        for attempt in range(2):
            try:
                d=yf.download(t,start=START,end=END,auto_adjust=True,progress=False,threads=False,timeout=25)
                if d is None or d.empty:
                    continue
                if isinstance(d.columns,pd.MultiIndex):
                    if ("Close",t) in d.columns:
                        s=d[("Close",t)]
                    elif "Close" in d.columns.get_level_values(0):
                        s=d.xs("Close",axis=1,level=0).iloc[:,0]
                    else:
                        continue
                else:
                    if "Close" not in d.columns:
                        continue
                    s=d["Close"]
                s=pd.to_numeric(s,errors="coerce").dropna()
                if not s.empty:
                    s.name=t; out[t]=s; ok=True; break
            except Exception as e:
                print(f"[warn] {t} attempt={attempt+1}: {e}")
        if not ok: failed.append(t)
        print(f"[download] {i}/{len(UNIVERSE)} {t} {'ok' if ok else 'FAIL'}")
    if "QQQ" not in out:
        raise RuntimeError("QQQ unavailable")
    px=pd.concat(out.values(),axis=1).sort_index()
    px.index=pd.to_datetime(px.index).tz_localize(None)
    return px,failed


def family_ratio(truth: pd.DataFrame, valid: pd.DataFrame, cols: list[str]) -> pd.Series:
    cols=[c for c in cols if c in truth.columns]
    if not cols:
        return pd.Series(np.nan,index=truth.index)
    num=truth[cols].where(valid[cols]).sum(axis=1,min_count=1)
    den=valid[cols].sum(axis=1).replace(0,np.nan)
    return num/den


def participation(truth: pd.DataFrame, valid: pd.DataFrame) -> pd.Series:
    pieces=[family_ratio(truth,valid,BROAD),family_ratio(truth,valid,SECTORS)]
    parents=[]
    for cols in INDUSTRY_PARENT.values():
        parents.append(family_ratio(truth,valid,cols))
    industry=pd.concat(parents,axis=1).mean(axis=1,skipna=True)
    pieces.append(industry)
    return pd.concat(pieces,axis=1).mean(axis=1,skipna=True)*100.0


def metric_gt(a: pd.DataFrame,b: pd.DataFrame) -> pd.Series:
    valid=a.notna()&b.notna(); truth=a.gt(b)
    return participation(truth,valid)


def metric_ret_positive(c: pd.DataFrame,h: int) -> pd.Series:
    p=c.shift(h); valid=c.notna()&p.notna(); truth=(c/p-1).gt(0)
    return participation(truth,valid)


def stratified_median(frame: pd.DataFrame) -> pd.Series:
    def med(cols):
        z=frame[[c for c in cols if c in frame.columns]]
        return z.median(axis=1,skipna=True) if len(z.columns) else pd.Series(np.nan,index=frame.index)
    broad=med(BROAD); sector=med(SECTORS)
    parents=[med(cols) for cols in INDUSTRY_PARENT.values()]
    industry=pd.concat(parents,axis=1).mean(axis=1,skipna=True)
    return pd.concat([broad,sector,industry],axis=1).mean(axis=1,skipna=True)


def linear_score(s: pd.Series,lo: float,hi: float) -> pd.Series:
    return ((s-lo)/(hi-lo)).clip(0,1)*100.0


def build_metrics(px: pd.DataFrame) -> pd.DataFrame:
    c=px.reindex(columns=[x for x in UNIVERSE if x in px.columns])
    ma10=c.rolling(10,min_periods=10).mean(); ma20=c.rolling(20,min_periods=20).mean()
    ma50=c.rolling(50,min_periods=50).mean(); ma200=c.rolling(200,min_periods=200).mean()
    m=pd.DataFrame(index=c.index)
    m["ret5"]=metric_ret_positive(c,5)
    m["above10"]=metric_gt(c,ma10)
    m["above20"]=metric_gt(c,ma20)
    m["ret21"]=metric_ret_positive(c,21)
    m["ret63"]=metric_ret_positive(c,63)
    m["above50"]=metric_gt(c,ma50)
    m["ma20_gt_50"]=metric_gt(ma20,ma50)
    m["ma50_rising"]=metric_gt(ma50,ma50.shift(20))
    m["above200"]=metric_gt(c,ma200)
    m["ma50_gt_200"]=metric_gt(ma50,ma200)
    hi252=c.rolling(252,min_periods=200).max(); dd=c/hi252-1
    med_dd=stratified_median(dd)
    m["median_dd_pct"]=med_dd*100
    m["dd_score"]=linear_score(med_dd,-.30,-.05)
    valid=dd.notna(); m["within10"]=participation(dd.ge(-.10),valid)
    m["short"]=m[["ret5","above10","above20"]].mean(axis=1)
    m["medium_level"]=m[["ret21","ret63","above50","ma20_gt_50","ma50_rising"]].mean(axis=1)
    m["long"]=m[["above200","ma50_gt_200"]].mean(axis=1)
    m["damage"]=m[["dd_score","within10"]].mean(axis=1)
    # Broad repair level: deliberately excludes 5D return and 10SMA.
    m["breadth_core"]=m[["above20","ret21","above50","ma20_gt_50"]].mean(axis=1)
    m["breadth_delta10"]=m["breadth_core"]-m["breadth_core"].shift(10)
    m["breadth_delta20"]=m["breadth_core"]-m["breadth_core"].shift(20)
    # Neutral slope=50. +/-20 percentage-point change maps to 0/100.
    m["det20_score"]=(50.0+2.5*m["breadth_delta20"]).clip(0,100)
    multi_delta=.35*m["breadth_delta10"]+.65*m["breadth_delta20"]
    m["det1020_score"]=(50.0+2.5*multi_delta).clip(0,100)
    return m


def score_candidates(m: pd.DataFrame) -> dict[str,pd.DataFrame]:
    out={}
    for name,(level_w,det_w,source) in CANDIDATES.items():
        if source=="none": det=m["medium_level"]
        elif source=="d20": det=m["det20_score"]
        else: det=m["det1020_score"]
        medium=level_w*m["medium_level"]+det_w*det
        raw=.15*m["short"]+.55*medium+.20*m["long"]+.10*m["damage"]
        score=raw.ewm(span=2,adjust=False).mean()
        f=m.copy(); f["medium"]=medium; f["raw"]=raw; f["score"]=score
        out[name]=f
    return out


def trailing_corr(score: pd.Series,qqq: pd.Series) -> dict:
    d=pd.DataFrame({"s":score,"q":qqq}).dropna()
    ans={}
    for h in (5,10,21,63,126):
        r=d["q"]/d["q"].shift(h)-1
        ans[f"ret{h}"]=float(d["s"].corr(r))
    return ans


def band_flip_stats(score: pd.Series) -> dict:
    s=score.dropna(); labels=pd.Series([band(float(x)) for x in s],index=s.index)
    flips=int((labels!=labels.shift()).sum()-1)
    years=max((s.index[-1]-s.index[0]).days/365.25,1)
    # compress runs; A->B->A within <=10 sessions counts as a whipsaw
    runs=[]; start=0; vals=labels.to_numpy(); idx=labels.index
    for i in range(1,len(vals)+1):
        if i==len(vals) or vals[i]!=vals[start]:
            runs.append((vals[start],start,i-1)); start=i
    whips=0
    for i in range(1,len(runs)-1):
        a,b,c=runs[i-1],runs[i],runs[i+1]
        if a[0]==c[0] and (b[2]-b[1]+1)<=10:
            whips+=1
    occ=labels.value_counts(normalize=True).mul(100).to_dict()
    return {"flips_per_year":flips/years,"whipsaws_per_year":whips/years,"flips":flips,"whipsaws":whips,"occupancy_pct":{k:float(v) for k,v in occ.items()}}


def drawdown_episodes(qqq: pd.Series,trigger=-.08,exit_dd=-.02):
    q=qqq.dropna(); peak=float(q.iloc[0]); peak_date=q.index[0]; in_ep=False; out=[]
    for dt,val0 in q.items():
        val=float(val0)
        if not in_ep:
            if val>peak: peak=val; peak_date=dt
            if val/peak-1<=trigger:
                in_ep=True; ep_peak=peak; ep_peak_date=peak_date; start=dt; trough=val; trough_date=dt
        else:
            if val<trough: trough=val; trough_date=dt
            if val/ep_peak-1>=exit_dd:
                out.append({"peak":ep_peak_date,"start":start,"trough":trough_date,"end":dt,"dd":trough/ep_peak-1})
                in_ep=False; peak=val; peak_date=dt
    if in_ep:
        out.append({"peak":ep_peak_date,"start":start,"trough":trough_date,"end":q.index[-1],"dd":trough/ep_peak-1})
    return out


def sessions_between(index: pd.DatetimeIndex,a: pd.Timestamp,b: pd.Timestamp) -> int:
    z=index[(index>=min(a,b))&(index<=max(a,b))]
    return max(len(z)-1,0)


def first_cross(frame: pd.DataFrame,start: pd.Timestamp,end: pd.Timestamp,col: str,threshold: float,direction: str):
    z=frame.loc[(frame.index>=start)&(frame.index<=end),col].dropna()
    if direction=="below": hit=z[z<threshold]
    else: hit=z[z>=threshold]
    return hit.index[0] if len(hit) else None


def episode_stats(frame: pd.DataFrame,qqq: pd.Series,episodes: list[dict]) -> list[dict]:
    idx=qqq.dropna().index; rows=[]
    for e in episodes:
        peak=e["peak"]; trough=e["trough"]; end=e["end"]
        recover_end=idx[min(idx.get_indexer([trough],method="nearest")[0]+60,len(idx)-1)]
        row={"peak":str(peak.date()),"trough":str(trough.date()),"end":str(end.date()),"dd_pct":float(e["dd"]*100)}
        for th in (65,55,45):
            d=first_cross(frame,peak,trough,"score",th,"below")
            row[f"below{th}_date"]=str(d.date()) if d is not None else None
            row[f"below{th}_sessions_from_peak"]=sessions_between(idx,peak,d) if d is not None else None
        for th in (45,55,65):
            d=first_cross(frame,trough,recover_end,"score",th,"above")
            row[f"recover{th}_date"]=str(d.date()) if d is not None else None
            row[f"recover{th}_sessions_from_trough"]=sessions_between(idx,trough,d) if d is not None else None
        rows.append(row)
    return rows


def avg_episode(rows: list[dict]) -> dict:
    ans={}
    for key in ["below65_sessions_from_peak","below55_sessions_from_peak","below45_sessions_from_peak","recover45_sessions_from_trough","recover55_sessions_from_trough","recover65_sessions_from_trough"]:
        a=[r[key] for r in rows if r.get(key) is not None]
        ans[key.replace("sessions_", "avg_sessions_")]=float(np.mean(a)) if a else None
        ans[key.replace("sessions_", "median_sessions_")]=float(np.median(a)) if a else None
        ans[key+"_coverage"]=len(a)
    return ans


def gate_overlap(score: pd.Series) -> dict:
    p=ROOT/"trend_history.json"
    if not p.exists(): return {}
    raw=json.loads(p.read_text(encoding="utf-8"))
    rows=[]
    for x in raw:
        if isinstance(x,(list,tuple)) and len(x)>=2: rows.append((x[0],x[1]))
        elif isinstance(x,dict): rows.append((x.get("date"),x.get("gate")))
    g=pd.DataFrame(rows,columns=["date","gate"]); g["date"]=pd.to_datetime(g["date"],errors="coerce")
    order={"Red":0,"Yellow":1,"Green":2,"Blue":3}; g["ord"]=g["gate"].map(order)
    s=pd.DataFrame({"date":score.index,"score":score.values})
    z=g.merge(s,on="date",how="inner").dropna()
    if z.empty:return {}
    by={k:{"n":int(len(v)),"mean":float(v["score"].mean())} for k,v in z.groupby("gate")}
    return {"n":int(len(z)),"spearman":float(z["score"].corr(z["ord"],method="spearman")),"by_gate":by}


def main():
    px,failed=download_prices(); px=px.loc[:EVAL_END]
    m=build_metrics(px); candidates=score_candidates(m); qqq=px["QQQ"]
    episodes=drawdown_episodes(qqq.loc[qqq.index>=EVAL_START])
    result={
        "scope":{
            "evaluation":"2016-01-01..2026-08-24","universe_n":43,"failed_tickers":failed,
            "core_weights":"Short15 / Medium55 / Long20 / Damage10; EMA2",
            "deterioration_definition":"breadth_core = mean(above20, positive21D, above50, 20SMA>50SMA); delta20 in percentage points; det score = clip(50 + 2.5*delta20,0,100)",
            "purpose":"descriptive medium-term market health; deterioration metric is tested for earlier internal weakening without turning Market Conditions into NQSAR"
        },
        "episodes":[{"peak":str(e["peak"].date()),"trough":str(e["trough"].date()),"end":str(e["end"].date()),"dd_pct":float(e["dd"]*100)} for e in episodes],
        "candidates":{}
    }
    eval_mask=(m.index>=EVAL_START)&(m.index<=EVAL_END)
    latest_date=m.loc[eval_mask].dropna(subset=["breadth_core"]).index[-1]
    for name,f in candidates.items():
        s=f["score"].where(eval_mask).dropna(); eps=episode_stats(f,qqq,episodes)
        selected=[r for r in eps if pd.Timestamp(r["trough"]).year in (2022,2025,2026)]
        result["candidates"][name]={
            "current":{
                "date":str(latest_date.date()),"score":float(f.loc[latest_date,"score"]),"band":band(float(f.loc[latest_date,"score"])),
                "short":float(f.loc[latest_date,"short"]),"medium_level":float(f.loc[latest_date,"medium_level"]),"medium_used":float(f.loc[latest_date,"medium"]),
                "long":float(f.loc[latest_date,"long"]),"damage":float(f.loc[latest_date,"damage"]),
                "breadth_core":float(f.loc[latest_date,"breadth_core"]),"breadth_delta10":float(f.loc[latest_date,"breadth_delta10"]),"breadth_delta20":float(f.loc[latest_date,"breadth_delta20"]),
                "det20_score":float(f.loc[latest_date,"det20_score"]),"det1020_score":float(f.loc[latest_date,"det1020_score"]),
            },
            "timescale_corr":trailing_corr(s,qqq),
            "noise":{
                "mean_abs_daily_change":float(s.diff().abs().mean()),
                **band_flip_stats(s)
            },
            "nqsar_overlap":gate_overlap(s),
            "all_drawdowns":avg_episode(eps),
            "case_2022_2025_2026":selected,
        }
    Path("market_conditions_deterioration_validation.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    compact={"scope":result["scope"],"episodes":result["episodes"],"candidates":{}}
    for name,x in result["candidates"].items():
        compact["candidates"][name]={k:x[k] for k in ["current","timescale_corr","noise","nqsar_overlap","all_drawdowns","case_2022_2025_2026"]}
    Path("market_conditions_deterioration_validation_compact.json").write_text(json.dumps(compact,ensure_ascii=False,indent=2),encoding="utf-8")
    # Persist recent daily comparison for visual/manual inspection without touching production artifacts.
    daily=pd.DataFrame(index=m.index)
    daily["qqq"]=qqq
    daily["breadth_core"]=m["breadth_core"]; daily["breadth_delta20"]=m["breadth_delta20"]
    for name,f in candidates.items(): daily[name]=f["score"]
    daily.loc[daily.index>=pd.Timestamp("2026-01-01")].to_csv("market_conditions_deterioration_daily_2026.csv",index_label="date")
    print(json.dumps(compact,ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
