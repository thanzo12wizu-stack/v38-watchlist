#!/usr/bin/env python3
"""Final research attribution: nested deltas and cross-sectional partial coefficients.

Uses outputs/data already on the research branch. No network, no production writes.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
EVENT=HERE/"event_features.csv"
LODO=HERE/"reconcile_lodo_by_date.csv"
RNG=np.random.default_rng(2026090517)


def pct(x): return "—" if not np.isfinite(x) else f"{100*x:.2f}%"
def num(x): return "—" if not np.isfinite(x) else f"{x:.4f}"

def boot(a,n=6000):
    a=np.asarray([x for x in a if np.isfinite(x)],float)
    if len(a)==0:return np.nan,np.nan,np.nan
    m=float(a.mean())
    if len(a)<3:return m,np.nan,np.nan
    s=np.array([RNG.choice(a,size=len(a),replace=True).mean() for _ in range(n)])
    lo,hi=np.quantile(s,[.025,.975]); return m,float(lo),float(hi)


def nested_from_lodo():
    d=pd.read_csv(LODO,parse_dates=["date"])
    d=d[d["sample"]=="strict_common"].copy()
    base="base+depth"
    candidates=["base+depth+flip","base+depth+gex","base+depth+wall_rr","base+depth+flip+gex",
                "base+depth+flip+wall_rr","base+all_rr","base+all_dist"]
    rows=[]
    b=d[d.model==base].set_index("date")
    for model in candidates:
        g=d[d.model==model].set_index("date")
        dates=b.index.intersection(g.index)
        for metric in ("ic","spread","mse"):
            delta=g.loc[dates,metric].to_numpy(float)-b.loc[dates,metric].to_numpy(float)
            m,lo,hi=boot(delta)
            improved=delta<0 if metric=="mse" else delta>0
            rows.append({"comparison":f"{model} minus {base}","metric":metric,"dates":len(dates),"delta":m,
                         "ci_lo":lo,"ci_hi":hi,"improved_date_fraction":float(improved.mean())})
    return pd.DataFrame(rows)


def prep_event():
    d=pd.read_csv(EVENT,parse_dates=["date"],low_memory=False)
    for c in ["spot","total_oi","n_strikes","gex_per_oi","wall_rr","flip_dist_atr","ret1_today","ret20","dist20hi",
              "sector_ret20","hv20","above_ema21","above_vwap63","r5_exqqq","dvol_m"]:
        if c not in d:d[c]=np.nan
        d[c]=pd.to_numeric(d[c],errors="coerce")
    d["log_spot"]=np.log(d.spot.where(d.spot>0))
    d["log_oi"]=np.log1p(d.total_oi.clip(lower=0))
    d["log_strikes"]=np.log1p(d.n_strikes.clip(lower=0))
    gp=d.gex_per_oi.to_numpy(float)
    d["gex_t"]=np.sign(gp)*np.log1p(np.abs(gp))
    d["log_wall_rr"]=np.log(d.wall_rr.clip(.05,20))
    d["flip_cap"]=d.flip_dist_atr.clip(-5,5)
    d["log_dvol"]=np.log(d.dvol_m.where(d.dvol_m>0))
    return d


def cross_sectional_partial(d):
    base=["ret1_today","ret20","dist20hi","sector_ret20","hv20","above_ema21","above_vwap63","log_spot"]
    tests={
        "log_oi | base+strikes": base+["log_strikes","log_oi"],
        "log_strikes | base+oi": base+["log_oi","log_strikes"],
        "flip | base+depth": base+["log_oi","log_strikes","flip_cap"],
        "wall_rr | base+depth": base+["log_oi","log_strikes","log_wall_rr"],
        "gex | base+depth": base+["log_oi","log_strikes","gex_t"],
        "flip | base+depth+wall+gex": base+["log_oi","log_strikes","log_wall_rr","gex_t","flip_cap"],
    }
    target={k:v[-1] for k,v in tests.items()}
    detail=[]
    for name,cols in tests.items():
        z=d[["date","r5_exqqq"]+cols].replace([np.inf,-np.inf],np.nan).dropna()
        for dt,g in z.groupby("date"):
            if len(g)<max(30,3*len(cols)):continue
            X=g[cols].copy(); mu=X.mean(); sd=X.std(ddof=0).replace(0,1); X=(X-mu)/sd
            y=g.r5_exqqq.to_numpy(float)
            A=np.column_stack([np.ones(len(X)),X.to_numpy(float)])
            pen=np.eye(A.shape[1]); pen[0,0]=0
            beta=np.linalg.solve(A.T@A+3*pen,A.T@y)
            j=cols.index(target[name])+1
            detail.append({"test":name,"date":dt,"n":len(g),"coef":beta[j]})
    det=pd.DataFrame(detail)
    rows=[]
    if not det.empty:
        for name,g in det.groupby("test"):
            m,lo,hi=boot(g.coef)
            rows.append({"test":name,"dates":len(g),"n_sum":int(g.n.sum()),"mean_std_coef":m,"ci_lo":lo,"ci_hi":hi,
                         "positive_date_fraction":float((g.coef>0).mean())})
    return pd.DataFrame(rows),det


def dvol_control(d):
    """Check whether OI survives a historical-DDV control where enough dates exist."""
    base=["ret1_today","ret20","dist20hi","sector_ret20","hv20","above_ema21","above_vwap63","log_spot","log_dvol","log_strikes"]
    z=d[["date","r5_exqqq"]+base+["log_oi"]].replace([np.inf,-np.inf],np.nan).dropna()
    detail=[]
    for dt,g in z.groupby("date"):
        if len(g)<35:continue
        cols=base+["log_oi"]
        X=g[cols]; mu=X.mean(); sd=X.std(ddof=0).replace(0,1); X=(X-mu)/sd
        A=np.column_stack([np.ones(len(X)),X.to_numpy(float)]); y=g.r5_exqqq.to_numpy(float)
        pen=np.eye(A.shape[1]);pen[0,0]=0
        beta=np.linalg.solve(A.T@A+3*pen,A.T@y)
        detail.append({"date":dt,"n":len(g),"oi_coef":beta[-1]})
    x=pd.DataFrame(detail)
    if x.empty:return {"dates":0,"n_sum":0,"mean_coef":np.nan,"ci_lo":np.nan,"ci_hi":np.nan,"positive_fraction":np.nan},x
    m,lo,hi=boot(x.oi_coef)
    return {"dates":len(x),"n_sum":int(x.n.sum()),"mean_coef":m,"ci_lo":lo,"ci_hi":hi,"positive_fraction":float((x.oi_coef>0).mean())},x


def write_report(nested,partial,dvol,meta):
    lines=["# Options nested attribution — 2026-09-05","",
           "Research only. This is the final attribution pass for the current 11-session sample; no production files were changed.","",
           "## Nested out-of-date deltas versus baseline+depth","",
           "The reference model already contains technical/sector controls plus OI and strike depth. Positive spread/IC deltas are better; negative MSE deltas are better.","",
           "|Added structure|Metric|Dates|Delta|95% date CI|Improved dates|","|---|---|---:|---:|---:|---:|"]
    for _,r in nested.iterrows():
        fmt=num if r.metric in ("ic","mse") else pct
        lines.append(f"|{r.comparison}|{r.metric}|{int(r.dates)}|{fmt(r.delta)}|{fmt(r.ci_lo)} to {fmt(r.ci_hi)}|{pct(r.improved_date_fraction)}|")
    lines += ["","## Date-by-date partial coefficients", "",
              "Each date is a separate standardized cross-sectional ridge regression. These coefficients ask whether each feature has residual association after the named controls.","",
              "|Test|Dates|Mean standardized coefficient|95% date CI|Positive dates|","|---|---:|---:|---:|---:|"]
    for _,r in partial.iterrows():
        lines.append(f"|{r.test}|{int(r.dates)}|{pct(r.mean_std_coef)}|{pct(r.ci_lo)} to {pct(r.ci_hi)}|{pct(r.positive_date_fraction)}|")
    lines += ["","## Historical DDV control for OI", "",
              f"Eligible DDV-controlled independent dates: {int(dvol['dates'])}; summed cross-sectional observations: {int(dvol['n_sum'])}.",
              f"OI standardized coefficient after technical/sector/price/DDV/strike controls: {pct(dvol['mean_coef'])} ({pct(dvol['ci_lo'])} to {pct(dvol['ci_hi'])}); positive dates {pct(dvol['positive_fraction'])}.","",
              "## Consolidated interpretation",""]
    flip=nested[(nested.comparison.str.startswith("base+depth+flip minus"))&(nested.metric=="spread")]
    wall=nested[(nested.comparison.str.startswith("base+depth+wall_rr minus"))&(nested.metric=="spread")]
    gex=nested[(nested.comparison.str.startswith("base+depth+gex minus"))&(nested.metric=="spread")]
    if not flip.empty:
        r=flip.iloc[0]
        if r.delta<=0:
            lines.append(f"- After OI/strike depth is already known, adding Flip changes the out-of-date top-bottom spread by {pct(r.delta)}. Thus the strong univariate Flip ranking is not yet proven to be independent of depth/other controls.")
        else:
            lines.append(f"- After OI/strike depth is already known, adding Flip improves out-of-date spread by {pct(r.delta)}; this is the cleanest current evidence for incremental Flip value, but only across {int(r.dates)} dates.")
    if not wall.empty:
        r=wall.iloc[0]; lines.append(f"- Adding Wall RR on top of depth changes spread by {pct(r.delta)}. Do not reverse or increase its directional weight from this short sample.")
    if not gex.empty:
        r=gex.iloc[0]; lines.append(f"- Adding GEX on top of depth changes spread by {pct(r.delta)}. Dealer-side ambiguity remains unresolved.")
    lines.append("- OI depth is the most persistent quality-associated feature in the current sample, but it may proxy liquidity, company size, institutional attention, or provider coverage. It should not be called bullish positioning.")
    if dvol['dates']<4:
        lines.append("- Historical DDV coverage is too sparse for a credible liquidity-controlled conclusion. This is a key reason to keep collecting all-liquid daily snapshots before production reweighting.")
    lines += ["","## Decision for this sample","",
              "No production weight/threshold change is justified yet. The useful research hypotheses are: downside score asymmetry, Options-market depth as a quality variable, Gamma Flip as a conditional structure variable, and Wall as a path/level variable rather than a standalone directional predictor. Freeze these hypotheses and retest at ~40 and ~120 independent sessions.",""]
    (HERE/"ATTRIBUTION.md").write_text("\n".join(lines),encoding="utf-8")


def main():
    nested=nested_from_lodo()
    d=prep_event()
    partial,pdetail=cross_sectional_partial(d)
    dvol,dvdetail=dvol_control(d)
    nested.to_csv(HERE/"nested_delta.csv",index=False)
    partial.to_csv(HERE/"partial_coefficients.csv",index=False)
    pdetail.to_csv(HERE/"partial_coefficients_by_date.csv",index=False)
    dvdetail.to_csv(HERE/"dvol_control_by_date.csv",index=False)
    meta={"rows":len(d),"dates":int(d.date.nunique()),"nested_rows":len(nested),"partial_rows":len(partial),"dvol_dates":int(dvol['dates'])}
    (HERE/"attribution_summary.json").write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding="utf-8")
    write_report(nested,partial,dvol,meta)
    print(json.dumps(meta,ensure_ascii=False))

if __name__=="__main__":main()
