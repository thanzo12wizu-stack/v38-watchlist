#!/usr/bin/env python3
"""Second-stage research: isolate incremental predictive value of Options features.

Uses event_features.csv produced by the first research run. No network and no production
writes. The key question is whether Flip/Wall/GEX add information beyond underlying
trend, sector momentum, and broad-market context.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

HERE = Path(__file__).resolve().parent
IN = HERE / "event_features.csv"
HORIZONS = (1,3,5,10)
SEED=9173
rng=np.random.default_rng(SEED)


def finite(x):
    return np.isfinite(x)


def boot_ci(values, n=5000):
    a=np.asarray([x for x in values if np.isfinite(x)],float)
    if len(a)<2: return (float(np.nanmean(a)) if len(a) else np.nan,np.nan,np.nan)
    means=np.empty(n)
    for i in range(n): means[i]=rng.choice(a,size=len(a),replace=True).mean()
    return float(a.mean()),float(np.quantile(means,.025)),float(np.quantile(means,.975))


def score_components(d):
    d=d.copy()
    tech=np.full(len(d),50.0)
    tech += np.where(d.above_ema21.eq(1),8,np.where(d.above_ema21.eq(0),-8,0))
    tech += np.where(d.above_vwap63.eq(1),5,np.where(d.above_vwap63.eq(0),-5,0))
    tech += np.where(d.ret1_today>=.02,5,np.where(d.ret1_today<=-.02,-5,0))
    opt=np.full(len(d),50.0)
    opt += np.where(d.flip_dist_atr>.35,10,np.where(d.flip_dist_atr<-.35,-10,0))
    rr=d.wall_rr.to_numpy(float)
    opt += np.where(rr>=1.4,10,np.where(rr<=.7,-10,np.where(rr>=1.15,4,np.where(rr<=.87,-4,0))))
    d["tech_score"]=tech
    d["options_score"]=opt
    d["combined_score_rebuilt"]=np.clip(tech+opt-50,0,100)
    d["log_wall_rr"]=np.log(d.wall_rr.clip(lower=.05,upper=20))
    gp=d.gex_per_oi.to_numpy(float)
    d["signed_log_gex_per_oi"]=np.sign(gp)*np.log1p(np.abs(gp))
    d["log_oi"]=np.log1p(d.total_oi.clip(lower=0))
    d["quality_gate"]=(d.total_oi>=5000)&(d.n_strikes>=20)&(d.cp_balance>=.05)
    return d


def daily_quintile_spreads(d, value, outcome, subset=None):
    z=d.copy()
    if subset is not None: z=z[subset(z)]
    rows=[]
    for dt,g in z.groupby("date"):
        g=g[[value,outcome,"ticker"]].replace([np.inf,-np.inf],np.nan).dropna()
        if len(g)<25 or g[value].nunique()<4: continue
        r=g[value].rank(method="average",pct=True)
        top=g[r>=.8]; bot=g[r<=.2]
        if len(top)<4 or len(bot)<4: continue
        rows.append({"date":dt,"n":len(g),"top_n":len(top),"bottom_n":len(bot),
                     "top":top[outcome].mean(),"bottom":bot[outcome].mean(),
                     "spread":top[outcome].mean()-bot[outcome].mean()})
    return pd.DataFrame(rows)


def quintile_summary(d):
    specs=[
        ("tech_score",None,"higher=bullish"),
        ("options_score",None,"higher=bullish"),
        ("combined_score_rebuilt",None,"higher=bullish"),
        ("flip_dist_atr",None,"higher=bullish"),
        ("log_wall_rr",None,"higher=bullish"),
        ("signed_log_gex_per_oi",None,"higher test only; dealer side unknown"),
        ("options_score",lambda x:x.quality_gate,"quality-gated"),
    ]
    details=[]; sums=[]
    for h in HORIZONS:
        out=f"r{h}_exqqq"
        for val,subset,note in specs:
            x=daily_quintile_spreads(d,val,out,subset)
            if x.empty: continue
            x["feature"]=val; x["horizon"]=h; x["note"]=note; details.append(x)
            mean,lo,hi=boot_ci(x.spread)
            sums.append({"feature":val,"horizon":h,"note":note,"dates":len(x),"n_total":int(x.n.sum()),
                         "spread_mean":mean,"ci_lo":lo,"ci_hi":hi,"spread_median":x.spread.median(),
                         "positive_date_fraction":float((x.spread>0).mean())})
    return pd.DataFrame(sums),pd.concat(details,ignore_index=True) if details else pd.DataFrame()


def zfit(train, test, cols):
    mu=train[cols].mean(); sd=train[cols].std(ddof=0).replace(0,1)
    return (train[cols]-mu)/sd,(test[cols]-mu)/sd


def ridge_predict(X,y,Xt,lam=5.0):
    X=np.column_stack([np.ones(len(X)),X])
    Xt=np.column_stack([np.ones(len(Xt)),Xt])
    pen=np.eye(X.shape[1]); pen[0,0]=0
    beta=np.linalg.solve(X.T@X+lam*pen,X.T@y)
    return Xt@beta


def cv_incremental(d,h=5):
    y=f"r{h}_exqqq"
    base=["ret1_today","ret20","dist20hi","sector_ret20","hv20","above_ema21","above_vwap63"]
    opts=["flip_dist_atr","log_wall_rr","signed_log_gex_per_oi","log_oi","n_strikes","cp_balance"]
    cols=base+opts
    z=d[["date","ticker",y]+cols].replace([np.inf,-np.inf],np.nan).dropna().copy()
    rows=[]
    dates=sorted(z.date.unique())
    for dt in dates:
        test=z[z.date==dt]; train=z[z.date!=dt]
        if len(test)<25 or len(train)<100: continue
        xb,xbt=zfit(train,test,base)
        xe,xet=zfit(train,test,cols)
        pb=ridge_predict(xb.to_numpy(float),train[y].to_numpy(float),xbt.to_numpy(float))
        pe=ridge_predict(xe.to_numpy(float),train[y].to_numpy(float),xet.to_numpy(float))
        yy=test[y].to_numpy(float)
        def stats(pred):
            ic=spearmanr(pred,yy).statistic if len(np.unique(pred))>1 else np.nan
            rank=pd.Series(pred).rank(pct=True).to_numpy()
            top=yy[rank>=.8]; bot=yy[rank<=.2]
            spread=float(np.mean(top)-np.mean(bot)) if len(top) and len(bot) else np.nan
            mse=float(np.mean((pred-yy)**2))
            return ic,spread,mse
        ib,sb,mb=stats(pb); ie,se,me=stats(pe)
        rows.append({"date":dt,"n":len(test),"base_ic":ib,"enhanced_ic":ie,"delta_ic":ie-ib,
                     "base_spread":sb,"enhanced_spread":se,"delta_spread":se-sb,
                     "base_mse":mb,"enhanced_mse":me,"delta_mse":me-mb})
    return pd.DataFrame(rows)


def fama_macbeth(d,h=5):
    y=f"r{h}_exqqq"
    cols=["ret1_today","ret20","dist20hi","sector_ret20","hv20","above_ema21","above_vwap63",
          "flip_dist_atr","log_wall_rr","signed_log_gex_per_oi","log_oi","n_strikes","cp_balance"]
    z=d[["date",y]+cols].replace([np.inf,-np.inf],np.nan).dropna().copy()
    coefs=[]
    for dt,g in z.groupby("date"):
        if len(g)<max(60,len(cols)*5): continue
        X=g[cols].copy(); mu=X.mean(); sd=X.std(ddof=0).replace(0,1); X=(X-mu)/sd
        X=np.column_stack([np.ones(len(X)),X.to_numpy(float)])
        yy=g[y].to_numpy(float)
        # Mild ridge stabilisation; intercept unpenalized.
        pen=np.eye(X.shape[1]); pen[0,0]=0
        beta=np.linalg.solve(X.T@X+3*pen,X.T@yy)
        row={"date":dt,"n":len(g)}
        for c,v in zip(cols,beta[1:]): row[c]=v
        coefs.append(row)
    detail=pd.DataFrame(coefs)
    sums=[]
    if not detail.empty:
        for c in cols:
            a=detail[c].dropna().to_numpy(float)
            if not len(a): continue
            mean=float(a.mean()); se=float(a.std(ddof=1)/math.sqrt(len(a))) if len(a)>1 else np.nan
            sums.append({"feature":c,"dates":len(a),"mean_coef":mean,"t_across_dates":mean/se if se and np.isfinite(se) and se>0 else np.nan,
                         "positive_fraction":float((a>0).mean())})
    return pd.DataFrame(sums),detail


def p(x):
    return "—" if not np.isfinite(x) else f"{x*100:.2f}%"


def main():
    d=pd.read_csv(IN,parse_dates=["date"],low_memory=False)
    d=score_components(d)
    qs,qd=quintile_summary(d)
    cv=cv_incremental(d,5)
    fm,fmd=fama_macbeth(d,5)
    qs.to_csv(HERE/"incremental_quintile_summary.csv",index=False)
    qd.to_csv(HERE/"incremental_quintile_by_date.csv",index=False)
    cv.to_csv(HERE/"incremental_lodo_cv.csv",index=False)
    fm.to_csv(HERE/"incremental_fama_macbeth.csv",index=False)
    fmd.to_csv(HERE/"incremental_fama_macbeth_by_date.csv",index=False)

    lines=["# Incremental Options value addendum","",
           "Question: after controlling for ordinary underlying trend / sector / market context, do Flip / Wall / GEX add useful cross-sectional information?","",
           "All results remain research-only; the option snapshot history contains only 11 independent sessions.","",
           "## Within-date quintile spreads","",
           "Top 20% minus bottom 20% future return, measured relative to QQQ. Ranking is recalculated independently inside each observation date, which removes most day-level market selection effects.",""]
    t=qs[qs.horizon==5].copy()
    lines += ["|Feature|Dates|Top-bottom 5d ex-QQQ|95% date-bootstrap CI|Positive dates|Note|","|---|---:|---:|---:|---:|---|"]
    for _,r in t.iterrows():
        lines.append(f"|{r.feature}|{int(r.dates)}|{p(r.spread_mean)}|{p(r.ci_lo)} to {p(r.ci_hi)}|{p(r.positive_date_fraction)}|{r.note}|")
    lines += ["","## Leave-one-date-out prediction, 5-day ex-QQQ","",
              "Baseline = underlying 1d/20d momentum, distance from 20d high, sector 20d momentum, HV20, EMA21 and 63d VWAP state. Enhanced = baseline + Flip distance, Wall asymmetry, GEX-per-OI transform, OI depth, strike count and C/P OI balance.",""]
    if cv.empty:
        lines.append("Insufficient complete-case folds.")
    else:
        for c in ["base_ic","enhanced_ic","delta_ic","base_spread","enhanced_spread","delta_spread","base_mse","enhanced_mse","delta_mse"]:
            mean,lo,hi=boot_ci(cv[c])
            if "mse" in c:
                lines.append(f"- {c}: {mean:.6f} ({lo:.6f} to {hi:.6f}) across {len(cv)} left-out dates")
            else:
                lines.append(f"- {c}: {mean:.4f} ({lo:.4f} to {hi:.4f}) across {len(cv)} left-out dates")
    lines += ["","## Date-by-date multivariate coefficients (Fama-MacBeth style, 5-day ex-QQQ)","",
              "Each date is regressed cross-sectionally after z-scoring features. The table averages coefficients across dates; t-stat is across independent dates, not across tickers.","",
              "|Feature|Dates|Mean standardized coefficient|t across dates|Positive dates|","|---|---:|---:|---:|---:|"]
    for _,r in fm.sort_values("t_across_dates",key=lambda s:s.abs(),ascending=False).iterrows():
        lines.append(f"|{r.feature}|{int(r.dates)}|{p(r.mean_coef)}|{r.t_across_dates:.2f}|{p(r.positive_fraction)}|")

    lines += ["","## Interpretation guardrail",""]
    if not cv.empty:
        di=float(cv.delta_ic.mean()); ds=float(cv.delta_spread.mean()); dm=float(cv.delta_mse.mean())
        if di>0 and ds>0 and dm<0:
            lines.append("- In this short sample, adding Options features improves all three out-of-date metrics (rank IC, top-bottom spread, and MSE). That is evidence of incremental information, but not enough independent dates for production adoption.")
        elif di<=0 and ds<=0 and dm>=0:
            lines.append("- In this short sample, Options features do not improve out-of-date prediction over the underlying/sector baseline. Direction Bias should not receive more Options weight from this evidence.")
        else:
            lines.append("- Incremental results are mixed across metrics. Do not increase Options weights yet; keep collecting daily snapshots and re-run on 40+ independent sessions.")
    lines.append("- GEX sign remains a statistical proxy only. It cannot be interpreted as dealer bullish/bearish positioning because trade side is unobserved.")
    lines.append("- Expected Move still cannot be validated historically: the new Expected Move fields exist mainly on the latest all-liquid snapshot, which has no completed forward expiry yet.")
    (HERE/"ADDENDUM.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print(json.dumps({"rows":len(d),"quintile_rows":len(qs),"cv_dates":len(cv),"fm_dates":int(fmd.date.nunique()) if not fmd.empty else 0},ensure_ascii=False))


if __name__=="__main__":
    main()
