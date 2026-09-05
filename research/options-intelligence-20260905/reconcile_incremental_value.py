#!/usr/bin/env python3
"""Research-only reconciliation of Options incremental-value results.

The prior robustness pass found a tension: Gamma Flip was strong univariately, while
OI/strike depth drove most out-of-date model improvement. This script isolates whether
that is sample selection, collinearity, or genuine incremental depth information.

No network calls. No production writes.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

HERE = Path(__file__).resolve().parent
INFILE = HERE / "event_features.csv"
RNG = np.random.default_rng(830177)

BASE = ["ret1_today", "ret20", "dist20hi", "sector_ret20", "hv20", "above_ema21", "above_vwap63", "log_spot"]
GROUPS = {
    "base": [],
    "base+oi": ["log_oi"],
    "base+strikes": ["log_strikes"],
    "base+depth": ["log_oi", "log_strikes"],
    "base+flip": ["flip_cap"],
    "base+depth+flip": ["log_oi", "log_strikes", "flip_cap"],
    "base+depth+gex": ["log_oi", "log_strikes", "signed_log_gex_per_oi"],
    "base+depth+wall_rr": ["log_oi", "log_strikes", "log_wall_rr"],
    "base+depth+flip+gex": ["log_oi", "log_strikes", "flip_cap", "signed_log_gex_per_oi"],
    "base+depth+flip+wall_rr": ["log_oi", "log_strikes", "flip_cap", "log_wall_rr"],
    "base+depth+flip+wall_dist": ["log_oi", "log_strikes", "flip_cap", "call_cap", "put_cap"],
    "base+all_rr": ["log_oi", "log_strikes", "flip_cap", "signed_log_gex_per_oi", "log_wall_rr"],
    "base+all_dist": ["log_oi", "log_strikes", "flip_cap", "signed_log_gex_per_oi", "call_cap", "put_cap"],
}


def pct(x):
    return "—" if not np.isfinite(x) else f"{100*x:.2f}%"


def nfmt(x, nd=4):
    return "—" if not np.isfinite(x) else f"{x:.{nd}f}"


def boot(values, n=5000):
    a = np.asarray([v for v in values if np.isfinite(v)], float)
    if len(a) == 0:
        return np.nan, np.nan, np.nan
    m = float(a.mean())
    if len(a) < 3:
        return m, np.nan, np.nan
    sims = np.array([RNG.choice(a, size=len(a), replace=True).mean() for _ in range(n)])
    lo, hi = np.quantile(sims, [.025, .975])
    return m, float(lo), float(hi)


def prep(d):
    d = d.copy()
    for c in ["spot", "total_oi", "n_strikes", "gex_per_oi", "wall_rr", "flip_dist_atr", "call_dist_atr", "put_dist_atr",
              "ret1_today", "ret20", "dist20hi", "sector_ret20", "hv20", "above_ema21", "above_vwap63", "r5_exqqq", "dvol_m"]:
        if c not in d: d[c] = np.nan
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d["log_spot"] = np.log(d.spot.where(d.spot > 0))
    d["log_oi"] = np.log1p(d.total_oi.clip(lower=0))
    d["log_strikes"] = np.log1p(d.n_strikes.clip(lower=0))
    gp = d.gex_per_oi.to_numpy(float)
    d["signed_log_gex_per_oi"] = np.sign(gp) * np.log1p(np.abs(gp))
    d["log_wall_rr"] = np.log(d.wall_rr.clip(lower=.05, upper=20))
    d["flip_cap"] = d.flip_dist_atr.clip(-5, 5)
    d["call_cap"] = d.call_dist_atr.clip(-5, 5)
    d["put_cap"] = d.put_dist_atr.clip(-5, 5)
    return d


def zfit(train, test, cols):
    mu = train[cols].mean()
    sd = train[cols].std(ddof=0).replace(0, 1).fillna(1)
    return (train[cols] - mu) / sd, (test[cols] - mu) / sd


def ridge(X, y, Xt, lam=5.0):
    X = np.column_stack([np.ones(len(X)), X])
    Xt = np.column_stack([np.ones(len(Xt)), Xt])
    pen = np.eye(X.shape[1]); pen[0, 0] = 0
    beta = np.linalg.solve(X.T @ X + lam * pen, X.T @ y)
    return Xt @ beta


def stats(pred, y):
    ic = spearmanr(pred, y).statistic if len(np.unique(pred)) > 1 else np.nan
    r = pd.Series(pred).rank(pct=True).to_numpy()
    top, bot = y[r >= .8], y[r <= .2]
    spread = float(top.mean() - bot.mean()) if len(top) and len(bot) else np.nan
    mse = float(np.mean((pred-y)**2))
    return ic, spread, mse


def lodo_on_sample(d, model_names, required_cols, label):
    y = "r5_exqqq"
    cols_all = list(dict.fromkeys(BASE + required_cols))
    z = d[["date", "ticker", y] + cols_all].replace([np.inf, -np.inf], np.nan).dropna().copy()
    rows = []
    for dt in sorted(z.date.unique()):
        test, train = z[z.date == dt], z[z.date != dt]
        if len(test) < 25 or len(train) < 100:
            continue
        yy = test[y].to_numpy(float)
        for model in model_names:
            cols = BASE + GROUPS[model]
            X, Xt = zfit(train, test, cols)
            pred = ridge(X.to_numpy(float), train[y].to_numpy(float), Xt.to_numpy(float))
            ic, spread, mse = stats(pred, yy)
            rows.append({"sample": label, "date": dt, "model": model, "n": len(test), "ic": ic, "spread": spread, "mse": mse})
    return pd.DataFrame(rows)


def summarize_pairwise(detail):
    rows = []
    for sample, s in detail.groupby("sample"):
        base = s[s.model == "base"].set_index("date")
        for model, g in s.groupby("model"):
            gg = g.set_index("date")
            dates = gg.index.intersection(base.index)
            if len(dates) == 0: continue
            for metric in ("ic", "spread", "mse"):
                vals = gg.loc[dates, metric].to_numpy(float)
                bv = base.loc[dates, metric].to_numpy(float)
                delta = vals - bv
                mean, lo, hi = boot(vals)
                dm, dlo, dhi = boot(delta)
                improved = delta < 0 if metric == "mse" else delta > 0
                rows.append({"sample": sample, "model": model, "metric": metric, "dates": len(dates),
                             "mean": mean, "ci_lo": lo, "ci_hi": hi, "delta_vs_base": dm,
                             "delta_ci_lo": dlo, "delta_ci_hi": dhi, "improved_date_fraction": float(improved.mean())})
    return pd.DataFrame(rows)


def pairwise_lodo(d):
    # Each model is compared against baseline on exactly the rows available for that model.
    details = []
    for model in [m for m in GROUPS if m != "base"]:
        req = GROUPS[model]
        x = lodo_on_sample(d, ["base", model], req, f"pair:{model}")
        if not x.empty: details.append(x)
    # Strict common sample compares all variants on identical observations.
    strict_cols = list(dict.fromkeys(sum([GROUPS[m] for m in GROUPS if m != "base"], [])))
    strict = lodo_on_sample(d, list(GROUPS), strict_cols, "strict_common")
    if not strict.empty: details.append(strict)
    detail = pd.concat(details, ignore_index=True) if details else pd.DataFrame()
    return summarize_pairwise(detail), detail


def daily_spread(d, feature, mask=None, sector_neutral=False):
    z = d.copy() if mask is None else d.loc[mask].copy()
    rows=[]
    group_cols = ["date", "sector"] if sector_neutral else ["date"]
    for key, g in z.groupby(group_cols):
        q = g[[feature, "r5_exqqq"]].replace([np.inf,-np.inf],np.nan).dropna()
        if len(q)<25 or q[feature].nunique()<4: continue
        r=q[feature].rank(pct=True)
        top=q.loc[r>=.8,"r5_exqqq"]; bot=q.loc[r<=.2,"r5_exqqq"]
        if len(top)<4 or len(bot)<4: continue
        dt = key[0] if isinstance(key,tuple) else key
        rows.append({"date":dt,"spread":float(top.mean()-bot.mean()),"n":len(q)})
    if not rows: return None
    x=pd.DataFrame(rows)
    daily=x.groupby("date").spread.mean()
    m,lo,hi=boot(daily)
    return {"feature":feature,"sector_neutral":sector_neutral,"dates":len(daily),"groups":len(x),"n_group_sum":int(x.n.sum()),
            "spread":m,"ci_lo":lo,"ci_hi":hi,"positive_date_fraction":float((daily>0).mean())}


def depth_diagnostics(d):
    rows=[]
    for feature in ("log_oi","log_strikes","flip_cap","log_wall_rr","signed_log_gex_per_oi"):
        for sn in (False,True):
            r=daily_spread(d,feature,sector_neutral=sn)
            if r: rows.append(r)
    # Depth effect inside price buckets to reduce simple price-level confounding.
    valid=d.log_spot.notna()
    if valid.any():
        for dt,g in d.loc[valid].groupby("date"):
            try:
                d.loc[g.index,"price_bucket"] = pd.qcut(g.log_spot.rank(method="first"),4,labels=False,duplicates="drop")
            except Exception:
                pass
        for b in sorted(pd.Series(d.get("price_bucket")).dropna().unique()):
            mask=d.get("price_bucket").eq(b)
            for feature in ("log_oi","log_strikes"):
                r=daily_spread(d,feature,mask=mask,sector_neutral=False)
                if r:
                    r["feature"] += f" | priceQ{int(b)+1}"
                    rows.append(r)
    return pd.DataFrame(rows)


def strict_univariate(d):
    required=list(dict.fromkeys(BASE + sum([GROUPS[m] for m in GROUPS if m != "base"], [])))
    z=d[["date","ticker","sector","r5_exqqq"]+required].replace([np.inf,-np.inf],np.nan).dropna().copy()
    rows=[]
    for feature in ("flip_cap","log_oi","log_strikes","log_wall_rr","signed_log_gex_per_oi"):
        r=daily_spread(z,feature)
        if r:
            r["sample"]="strict_common"; rows.append(r)
    return pd.DataFrame(rows), len(z), z.date.nunique(), z.ticker.nunique()


def missingness(d):
    cols=["dvol_m","total_oi","n_strikes","gex_per_oi","wall_rr","flip_dist_atr","call_dist_atr","put_dist_atr","sector_ret20","hv20"]
    return {c:{"non_null":int(d[c].notna().sum()),"ratio":float(d[c].notna().mean())} for c in cols}


def report(d, summary, detail, depth, strict, strict_meta, miss):
    lines=["# Options incremental-value reconciliation — 2026-09-05","",
           "Research only. No production logic or upstream artifact was changed.","",
           "Purpose: reconcile why Gamma Flip looked strong in univariate ranks while OI/strike depth explained more of the out-of-date model improvement.","",
           "## Coverage","",
           f"- Rows: {len(d):,}", f"- Tickers: {d.ticker.nunique():,}", f"- Independent dates: {d.date.nunique()}",
           f"- Strict complete-case rows/dates/tickers: {strict_meta[0]:,} / {strict_meta[1]} / {strict_meta[2]:,}",
           f"- Historical DDV availability: {miss['dvol_m']['non_null']:,}/{len(d):,} ({miss['dvol_m']['ratio']*100:.1f}%). It is not used as a historical control when missing.","",
           "## Pairwise leave-one-date-out tests","",
           "Each candidate model is compared with the same baseline on exactly the same rows. This avoids attributing a sample-composition change to the feature itself.","",
           "|Sample|Model|Metric|Dates|Mean|Delta vs baseline|95% delta CI|Improved dates|","|---|---|---|---:|---:|---:|---:|---:|"]
    s=summary[(summary.model!="base") & summary["sample"].str.startswith("pair:")]
    for _,r in s.iterrows():
        fmt=nfmt if r.metric in ("ic","mse") else pct
        lines.append(f"|{r['sample']}|{r.model}|{r.metric}|{int(r.dates)}|{fmt(r['mean'])}|{fmt(r.delta_vs_base)}|{fmt(r.delta_ci_lo)} to {fmt(r.delta_ci_hi)}|{pct(r.improved_date_fraction)}|")

    lines += ["","## Strict common-sample model comparison","",
              "All variants below use the identical complete-case rows.","",
              "|Model|Metric|Dates|Mean|Delta vs baseline|95% delta CI|Improved dates|","|---|---|---:|---:|---:|---:|---:|"]
    s=summary[(summary["sample"]=="strict_common") & (summary.model!="base")]
    for _,r in s.iterrows():
        fmt=nfmt if r.metric in ("ic","mse") else pct
        lines.append(f"|{r.model}|{r.metric}|{int(r.dates)}|{fmt(r['mean'])}|{fmt(r.delta_vs_base)}|{fmt(r.delta_ci_lo)} to {fmt(r.delta_ci_hi)}|{pct(r.improved_date_fraction)}|")

    lines += ["","## Univariate cross-sectional spreads","",
              "Top 20% minus bottom 20% 5d ex-QQQ. Sector-neutral rows first rank within sector/date and then equal-weight sectors by date.","",
              "|Feature|Sector neutral|Dates|Spread|95% date CI|Positive dates|","|---|---|---:|---:|---:|---:|"]
    for _,r in depth.iterrows():
        if "priceQ" in str(r.feature): continue
        lines.append(f"|{r.feature}|{'yes' if r.sector_neutral else 'no'}|{int(r.dates)}|{pct(r.spread)}|{pct(r.ci_lo)} to {pct(r.ci_hi)}|{pct(r.positive_date_fraction)}|")

    lines += ["","## Price-bucket check for depth", "",
              "Within each date, stocks are split into four price buckets. This does not replace market-cap/DDV controls, but checks whether depth is only a share-price proxy.","",
              "|Feature|Dates|Spread|95% date CI|Positive dates|","|---|---:|---:|---:|---:|"]
    for _,r in depth[depth.feature.astype(str).str.contains("priceQ")].iterrows():
        lines.append(f"|{r.feature}|{int(r.dates)}|{pct(r.spread)}|{pct(r.ci_lo)} to {pct(r.ci_hi)}|{pct(r.positive_date_fraction)}|")

    lines += ["","## Strict-sample univariate check","",
              "This tells us whether Flip's earlier univariate effect disappeared merely because the multivariate model required more complete fields.","",
              "|Feature|Dates|Spread|95% date CI|Positive dates|","|---|---:|---:|---:|---:|"]
    for _,r in strict.iterrows():
        lines.append(f"|{r.feature}|{int(r.dates)}|{pct(r.spread)}|{pct(r.ci_lo)} to {pct(r.ci_hi)}|{pct(r.positive_date_fraction)}|")

    # Conservative interpretation using pairwise spread deltas.
    lines += ["","## Interpretation",""]
    pair=summary[(summary.metric=="spread") & summary["sample"].str.startswith("pair:") & (summary.model!="base")].copy()
    if not pair.empty:
        pair=pair.sort_values("delta_vs_base",ascending=False)
        best=pair.iloc[0]
        lines.append(f"- Largest pairwise out-of-date spread improvement: {best.model}, {pct(best.delta_vs_base)} across {int(best.dates)} dates.")
        dep=pair[pair.model=="base+depth"]
        flip=pair[pair.model=="base+flip"]
        dfp=pair[pair.model=="base+depth+flip"]
        if not dep.empty and not flip.empty and not dfp.empty:
            depv=float(dep.iloc[0].delta_vs_base); flv=float(flip.iloc[0].delta_vs_base); dfv=float(dfp.iloc[0].delta_vs_base)
            if depv>0 and flv<=0 and dfv<=depv:
                lines.append("- The out-of-date gain is primarily associated with Options-market depth; Flip does not add to the technical baseline on the matched pairwise sample, and adding Flip to depth does not improve on depth alone. Treat the univariate Flip result as potentially conditional/collinear until more dates accumulate.")
            elif dfv>depv and dfv>flv:
                lines.append("- Depth and Flip appear complementary on matched samples: the combined model improves more than either addition alone. This is still exploratory because the independent-date count is small.")
            else:
                lines.append("- Depth and Flip contributions remain mixed across matched samples; neither should receive a new production weight yet.")
    lines.append("- OI/strike depth may represent option tradability, institutional attention, company size, or data quality rather than directional positioning. Without reliable historical DDV/market-cap controls, label it a quality/coverage feature, not a bullish signal.")
    lines.append("- Wall and GEX remain diagnostic unless they show stable incremental improvement on longer independent history.")
    lines += ["","## Evidence threshold","",
              "Freeze these diagnostics and repeat after ~40 and ~120 independent sessions. Do not optimize production weights from the present 11-session sample.",""]
    (HERE/"RECONCILIATION.md").write_text("\n".join(lines),encoding="utf-8")


def main():
    d=pd.read_csv(INFILE,parse_dates=["date"],low_memory=False)
    if "sector" not in d: d["sector"]=""
    d=prep(d)
    summary,detail=pairwise_lodo(d)
    depth=depth_diagnostics(d)
    strict,nrows,ndates,ntickers=strict_univariate(d)
    miss=missingness(d)
    summary.to_csv(HERE/"reconcile_lodo.csv",index=False)
    detail.to_csv(HERE/"reconcile_lodo_by_date.csv",index=False)
    depth.to_csv(HERE/"depth_diagnostics.csv",index=False)
    strict.to_csv(HERE/"strict_univariate.csv",index=False)
    (HERE/"reconcile_missingness.json").write_text(json.dumps(miss,ensure_ascii=False,indent=2),encoding="utf-8")
    report(d,summary,detail,depth,strict,(nrows,ndates,ntickers),miss)
    print(json.dumps({"rows":len(d),"dates":int(d.date.nunique()),"summary_rows":len(summary),"detail_rows":len(detail),
                      "strict_rows":nrows,"strict_dates":int(ndates),"ddv_non_null":miss['dvol_m']['non_null']},ensure_ascii=False))


if __name__=="__main__":
    main()
