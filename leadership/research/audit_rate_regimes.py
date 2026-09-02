from __future__ import annotations

import argparse
import io
import json
import math
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

SERIES = {"dgs2": "DGS2", "dgs10": "DGS10", "real10": "DFII10", "be10": "T10YIE", "dff": "DFF"}


def fetch_fred(series_id: str, start: str, end: str) -> pd.Series:
    params = urllib.parse.urlencode({"id": series_id, "cosd": start, "coed": end})
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 V38-rate-audit"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
    df = pd.read_csv(io.BytesIO(data))
    date_col = "DATE" if "DATE" in df.columns else df.columns[0]
    value_col = series_id if series_id in df.columns else df.columns[-1]
    idx = pd.to_datetime(df[date_col], errors="coerce")
    val = pd.to_numeric(df[value_col], errors="coerce")
    s = pd.Series(val.to_numpy(dtype=float), index=idx, name=series_id).dropna()
    s = s[~s.index.duplicated(keep="last")].sort_index()
    if s.empty:
        raise RuntimeError(f"FRED series empty: {series_id}")
    return s


def rolling_pct(s: pd.Series, window: int = 252, min_periods: int = 126) -> pd.Series:
    def f(x: np.ndarray) -> float:
        x = x[np.isfinite(x)]
        if len(x) == 0:
            return np.nan
        v = x[-1]
        return 100.0 * ((x < v).sum() + 0.5 * (x == v).sum()) / len(x)
    return s.rolling(window, min_periods=min_periods).apply(f, raw=True)


def prior_z(s: pd.Series, window: int = 252, min_periods: int = 126) -> pd.Series:
    mu = s.shift(1).rolling(window, min_periods=min_periods).mean()
    sd = s.shift(1).rolling(window, min_periods=min_periods).std(ddof=1)
    return (s - mu) / sd.replace(0, np.nan)


def build_rate_features(start: str, end: str) -> pd.DataFrame:
    raw = [fetch_fred(fid, start, end).rename(short) for short, fid in SERIES.items()]
    out = pd.concat(raw, axis=1).sort_index().ffill(limit=5)
    for c in ["dgs2", "dgs10", "real10", "be10", "dff"]:
        out[f"{c}_level_pct252"] = rolling_pct(out[c])
        for h in (5, 10, 20):
            chg = out[c].diff(h) * 100.0
            out[f"{c}_chg{h}_bp"] = chg
            out[f"{c}_chg{h}_z252"] = prior_z(chg)
        acc = out[c].diff(5) - out[c].diff(5).shift(5)
        out[f"{c}_acc5_bp"] = acc * 100.0
        out[f"{c}_acc5_z252"] = prior_z(out[f"{c}_acc5_bp"])
    out["curve_2s10s_bp"] = (out["dgs10"] - out["dgs2"]) * 100.0
    out["curve_level_pct252"] = rolling_pct(out["curve_2s10s_bp"])
    out["curve_chg5_bp"] = out["curve_2s10s_bp"].diff(5)
    out["curve_chg5_z252"] = prior_z(out["curve_chg5_bp"])
    out["curve_acc5_bp"] = out["curve_chg5_bp"] - out["curve_chg5_bp"].shift(5)
    out["curve_acc5_z252"] = prior_z(out["curve_acc5_bp"])
    out["rate_shock_z5"] = out[["dgs2_chg5_z252", "dgs10_chg5_z252", "real10_chg5_z252"]].mean(axis=1, skipna=True)
    out["duration_shock_z5"] = out[["dgs10_chg5_z252", "real10_chg5_z252"]].mean(axis=1, skipna=True)
    out["inflation_shock_z5"] = out["be10_chg5_z252"]
    out["rate_accel_z5"] = out[["dgs2_acc5_z252", "dgs10_acc5_z252", "real10_acc5_z252"]].mean(axis=1, skipna=True)
    out["duration_accel_z5"] = out[["dgs10_acc5_z252", "real10_acc5_z252"]].mean(axis=1, skipna=True)
    out["real_minus_be_chg5_bp"] = out["real10_chg5_bp"] - out["be10_chg5_bp"]
    out["real_share_shock"] = out["real10_chg5_z252"] - out["be10_chg5_z252"]
    out.index.name = "date"
    return out.reset_index()


def perf(r: pd.Series, periods_per_year: float = 252.0) -> dict[str, float | int | None]:
    x = pd.to_numeric(r, errors="coerce").dropna().astype(float)
    if x.empty:
        return {"n": 0}
    nav = (1.0 + x).cumprod()
    years = len(x) / periods_per_year
    cagr = float(nav.iloc[-1] ** (1.0 / years) - 1.0) if years > 0 and nav.iloc[-1] > 0 else np.nan
    vol = float(x.std(ddof=1) * math.sqrt(periods_per_year)) if len(x) > 1 else np.nan
    ann = float(x.mean() * periods_per_year)
    sharpe = ann / vol if vol and np.isfinite(vol) and vol > 0 else np.nan
    dd = nav / nav.cummax() - 1.0
    maxdd = float(dd.min())
    calmar = cagr / abs(maxdd) if np.isfinite(cagr) and maxdd < 0 else np.nan
    return {"n": int(len(x)), "mean_daily": float(x.mean()), "cagr": cagr, "ann_vol": vol,
            "sharpe": float(sharpe) if np.isfinite(sharpe) else None, "maxdd": maxdd,
            "calmar": float(calmar) if np.isfinite(calmar) else None, "win_rate": float((x > 0).mean()),
            "final_nav": float(nav.iloc[-1])}


def cluster_boot_ci(df: pd.DataFrame, value_col: str, cluster_col: str = "cluster", reps: int = 3000, seed: int = 38) -> dict[str, float | int | None]:
    x = df[[cluster_col, value_col]].dropna().copy()
    if x.empty:
        return {"n": 0}
    groups = {k: g[value_col].to_numpy(dtype=float) for k, g in x.groupby(cluster_col, observed=True)}
    keys = np.array(list(groups), dtype=object)
    obs = float(x[value_col].mean())
    if len(keys) < 5:
        return {"n": int(len(x)), "clusters": int(len(keys)), "mean": obs, "lo": None, "hi": None, "p_two": None}
    rng = np.random.default_rng(seed)
    vals = np.empty(reps, dtype=float)
    for i in range(reps):
        draw = rng.choice(keys, size=len(keys), replace=True)
        vals[i] = np.nanmean(np.concatenate([groups[k] for k in draw]))
    lo, hi = np.quantile(vals, [0.025, 0.975])
    p_two = 2.0 * min(float((vals <= 0).mean()), float((vals >= 0).mean()))
    return {"n": int(len(x)), "clusters": int(len(keys)), "mean": obs, "lo": float(lo), "hi": float(hi), "p_two": min(1.0, p_two)}


def assign_state(z: pd.Series, cut: float = 0.75) -> pd.Series:
    return pd.Series(np.where(z <= -cut, "EASING", np.where(z >= cut, "TIGHTENING", "NEUTRAL")), index=z.index)


def assign_level(pct: pd.Series) -> pd.Series:
    return pd.Series(np.where(pct < 33.333, "LOW", np.where(pct > 66.667, "HIGH", "MID")), index=pct.index)


def subperiod(date: pd.Series) -> pd.Series:
    y = pd.to_datetime(date).dt.year
    return pd.Series(np.select([y <= 2019, y <= 2021, y <= 2023, y >= 2024],
                               ["2016-2019", "2020-2021", "2022-2023", "2024-2026"], default="OTHER"), index=date.index)


def lag_merge_daily(daily: pd.DataFrame, rates: pd.DataFrame) -> pd.DataFrame:
    d = daily.copy(); d["date"] = pd.to_datetime(d["date"])
    r = rates.copy().sort_values("date"); r["date"] = pd.to_datetime(r["date"]); r = r.rename(columns={"date": "rate_date"})
    d["signal_cutoff"] = d["date"] - pd.Timedelta(days=1)
    return pd.merge_asof(d.sort_values("signal_cutoff"), r.sort_values("rate_date"), left_on="signal_cutoff", right_on="rate_date", direction="backward", tolerance=pd.Timedelta(days=7)).sort_values("date").reset_index(drop=True)


def asof_feature_dates(events: pd.DataFrame, rates: pd.DataFrame, event_col: str = "date", lag_days: int = 0) -> pd.DataFrame:
    e = events.copy(); e[event_col] = pd.to_datetime(e[event_col]); e["signal_cutoff"] = e[event_col] - pd.Timedelta(days=lag_days)
    r = rates.copy().sort_values("date").rename(columns={"date": "rate_date"})
    return pd.merge_asof(e.sort_values("signal_cutoff"), r.sort_values("rate_date"), left_on="signal_cutoff", right_on="rate_date", direction="backward", tolerance=pd.Timedelta(days=7)).sort_values(event_col).reset_index(drop=True)


def tqqq_episodes(t: pd.DataFrame, rates: pd.DataFrame, target_col: str) -> pd.DataFrame:
    x = t.copy().reset_index(drop=True); x["date"] = pd.to_datetime(x["date"])
    active = x[target_col].astype(float) > 0.3001
    starts = np.flatnonzero(active & ~active.shift(1, fill_value=False))
    rows = []
    for s in starts:
        e = s
        while e + 1 < len(x) and bool(active.iloc[e + 1]): e += 1
        g = x.iloc[s:e+1]; rr = g["tqqq_ret_usd"].astype(float)
        adopted = float(np.prod(1.0 + rr.to_numpy() * g[target_col].astype(float).to_numpy()) - 1.0)
        base = float(np.prod(1.0 + rr.to_numpy() * 0.30) - 1.0)
        hold = float(np.prod(1.0 + rr.to_numpy()) - 1.0)
        path = np.cumprod(1.0 + rr.to_numpy()) - 1.0
        rows.append({"date": x.loc[s, "date"], "end_date": x.loc[e, "date"], "duration": int(e-s+1),
                     "adopted_ret": adopted, "base30_ret": base, "incremental_ret": adopted-base,
                     "tqqq_hold_ret": hold, "tqqq_mae": float(np.min(path)) if len(path) else np.nan})
    ep = pd.DataFrame(rows)
    return asof_feature_dates(ep, rates, event_col="date", lag_days=1) if not ep.empty else ep


def simulate_tqqq_rate_policy(t: pd.DataFrame, ep: pd.DataFrame, feature: str, hi: float, lo: float | None = None, high_target: float = 0.50, easing_target: float | None = None) -> pd.Series:
    x = t.copy().reset_index(drop=True)
    target = x["target_M30_RISE30_F80_D10"].astype(float).to_numpy().copy()
    dates = pd.to_datetime(x["date"])
    for row in ep.itertuples(index=False):
        z = getattr(row, feature)
        if pd.isna(z): continue
        mask = (dates >= pd.Timestamp(row.date)) & (dates <= pd.Timestamp(row.end_date))
        if z >= hi:
            target[mask & (target > 0.3001)] = high_target
        elif lo is not None and easing_target is not None and z <= lo:
            target[mask & (target > 0.3001)] = easing_target
    return pd.Series(x["tqqq_ret_usd"].astype(float).to_numpy() * target, index=x.index)


def theme_analysis(theme_path: Path, rates: pd.DataFrame) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    if not theme_path.exists(): return [], []
    th = pd.read_csv(theme_path)
    if th.empty or "date" not in th.columns: return [], []
    base = th[th["method"].astype(str) == "DAY0_RS63_TOP3"].copy() if "method" in th.columns else th.copy()
    if base.empty: base = th.copy()
    m = asof_feature_dates(base, rates, "date", lag_days=0); m["cluster"] = pd.to_datetime(m["date"]).dt.strftime("%Y-%m-%d")
    rows, contrasts = [], []
    feature_defs = {"rate_shock_z5": assign_state(m["rate_shock_z5"]), "duration_shock_z5": assign_state(m["duration_shock_z5"]),
                    "rate_accel_z5": assign_state(m["rate_accel_z5"]), "real10_level_pct252": assign_level(m["real10_level_pct252"]),
                    "dgs10_level_pct252": assign_level(m["dgs10_level_pct252"])}
    outcomes = [c for c in ["ret_5", "ret_10", "ret_20", "vs_spy_5", "vs_spy_10", "vs_spy_20"] if c in m.columns]
    for feat, st in feature_defs.items():
        m2 = m.copy(); m2["state"] = st
        for outc in outcomes:
            for state, g in m2.groupby("state", observed=True):
                ci = cluster_boot_ci(g, outc, "cluster")
                rows.append({"feature": feat, "state": str(state), "outcome": outc, **ci,
                             "positive_rate": float((g[outc] > 0).mean()) if g[outc].notna().any() else None})
            if set(m2["state"].dropna().unique()) >= {"EASING", "TIGHTENING"}:
                am = m2[m2.state=="EASING"].groupby("cluster", observed=True)[outc].mean().dropna()
                bm = m2[m2.state=="TIGHTENING"].groupby("cluster", observed=True)[outc].mean().dropna()
                if len(am)>=5 and len(bm)>=5:
                    rng=np.random.default_rng(38); vals=np.empty(3000)
                    for i in range(3000): vals[i]=rng.choice(am.to_numpy(),len(am),replace=True).mean()-rng.choice(bm.to_numpy(),len(bm),replace=True).mean()
                    contrasts.append({"feature":feat,"outcome":outc,"contrast":"EASING-TIGHTENING","mean":float(am.mean()-bm.mean()),
                                      "lo":float(np.quantile(vals,.025)),"hi":float(np.quantile(vals,.975)),
                                      "p_two":float(min(1,2*min((vals<=0).mean(),(vals>=0).mean()))),
                                      "easing_dates":int(len(am)),"tightening_dates":int(len(bm))})
    return rows, contrasts


def main() -> None:
    ap=argparse.ArgumentParser(); ap.add_argument("--tqqq",required=True); ap.add_argument("--ordinary",required=True); ap.add_argument("--rsi",required=True)
    ap.add_argument("--theme-rows",default=""); ap.add_argument("--output",required=True); ap.add_argument("--analysis-start",default="2016-01-04"); ap.add_argument("--analysis-end",default="2026-03-20")
    args=ap.parse_args(); outdir=Path(args.output); outdir.mkdir(parents=True,exist_ok=True)
    rates=build_rate_features(str((pd.Timestamp(args.analysis_start)-pd.Timedelta(days=900)).date()),args.analysis_end)
    rates.to_csv(outdir/"rate_features.csv.gz",index=False,compression="gzip")
    t=pd.read_csv(args.tqqq); o=pd.read_csv(args.ordinary); rsi=pd.read_csv(args.rsi)
    for d in (t,o,rsi): d["date"]=pd.to_datetime(d["date"])
    start,end=pd.Timestamp(args.analysis_start),pd.Timestamp(args.analysis_end)
    t=t[(t.date>=start)&(t.date<=end)].copy().reset_index(drop=True); o=o[(o.date>=start)&(o.date<=end)].copy().reset_index(drop=True); rsi=rsi[(rsi.date>=start)&(rsi.date<=end)].copy().reset_index(drop=True)
    t["ret_tqqq_f80"]=t["tqqq_ret_usd"].astype(float)*t["target_M30_RISE30_F80_D10"].astype(float)
    t["ret_tqqq_f100"]=t["tqqq_ret_usd"].astype(float)*t["target_M30_RISE30_F100_D10"].astype(float)
    dm={"ordinary":lag_merge_daily(o.rename(columns={"return":"strategy_return"}),rates),
        "rsi_reset":lag_merge_daily(rsi.rename(columns={"return":"strategy_return"}),rates),
        "tqqq_f80":lag_merge_daily(t[["date","ret_tqqq_f80"]].rename(columns={"ret_tqqq_f80":"strategy_return"}),rates)}
    daily_rows=[]
    features={"rate_shock_z5":"shock","duration_shock_z5":"shock","rate_accel_z5":"shock","duration_accel_z5":"shock",
              "dgs10_level_pct252":"level","real10_level_pct252":"level","dgs2_level_pct252":"level","curve_chg5_z252":"shock"}
    for name,m in dm.items():
        m["subperiod"]=subperiod(m["date"])
        for feat,kind in features.items():
            m["state"]=assign_state(m[feat]) if kind=="shock" else assign_level(m[feat])
            for st,g in m.groupby("state",observed=True):
                daily_rows.append({"strategy":name,"feature":feat,"state":str(st),"subperiod":"ALL",**perf(g["strategy_return"])})
                for sp,gg in g.groupby("subperiod",observed=True):
                    if sp!="OTHER": daily_rows.append({"strategy":name,"feature":feat,"state":str(st),"subperiod":str(sp),**perf(gg["strategy_return"])})
    pd.DataFrame(daily_rows).to_csv(outdir/"daily_regime_performance.csv",index=False)
    ep=tqqq_episodes(t,rates,"target_M30_RISE30_F80_D10")
    if not ep.empty:
        ep["rate_state"]=assign_state(ep["rate_shock_z5"]); ep["duration_state"]=assign_state(ep["duration_shock_z5"]); ep["accel_state"]=assign_state(ep["rate_accel_z5"]); ep["real_level_state"]=assign_level(ep["real10_level_pct252"])
        ep.to_csv(outdir/"tqqq_panic_episodes.csv",index=False)
    policies={"BASE_F80":t["ret_tqqq_f80"],"BASE_F100":t["ret_tqqq_f100"],
              "TIGHT_Z1_CAP50":simulate_tqqq_rate_policy(t,ep,"rate_shock_z5",1.0,high_target=.50),
              "REAL_TIGHT_Z1_CAP50":simulate_tqqq_rate_policy(t,ep,"real10_chg5_z252",1.0,high_target=.50),
              "ASYM_Z1_F100_F50":simulate_tqqq_rate_policy(t,ep,"rate_shock_z5",1.0,-1.0,.50,1.00),
              "EASING_Z1_F100":simulate_tqqq_rate_policy(t,ep,"rate_shock_z5",99.0,-1.0,.80,1.00)}
    policy_rows=[]; sp=subperiod(t["date"])
    for name,rr in policies.items():
        rr=pd.Series(rr).reset_index(drop=True); policy_rows.append({"policy":name,"subperiod":"ALL",**perf(rr)})
        for period in ["2016-2019","2020-2021","2022-2023","2024-2026"]: policy_rows.append({"policy":name,"subperiod":period,**perf(rr[sp.eq(period)])})
    pd.DataFrame(policy_rows).to_csv(outdir/"tqqq_rate_policy_performance.csv",index=False)
    ep_rows=[]
    if not ep.empty:
        for feat,state_col in [("rate_shock_z5","rate_state"),("duration_shock_z5","duration_state"),("rate_accel_z5","accel_state"),("real10_level_pct252","real_level_state")]:
            for st,g in ep.groupby(state_col,observed=True):
                for outc in ["adopted_ret","incremental_ret","tqqq_hold_ret","tqqq_mae"]:
                    vals=g[outc].dropna().astype(float); ep_rows.append({"feature":feat,"state":str(st),"outcome":outc,"n":int(len(vals)),"mean":float(vals.mean()) if len(vals) else None,"median":float(vals.median()) if len(vals) else None,"positive_rate":float((vals>0).mean()) if len(vals) else None})
    pd.DataFrame(ep_rows).to_csv(outdir/"tqqq_episode_regimes.csv",index=False)
    theme_rows=[]; theme_contrasts=[]
    if args.theme_rows:
        theme_rows,theme_contrasts=theme_analysis(Path(args.theme_rows),rates); pd.DataFrame(theme_rows).to_csv(outdir/"theme_rate_regimes.csv",index=False); pd.DataFrame(theme_contrasts).to_csv(outdir/"theme_rate_contrasts.csv",index=False)
    base_all=next(x for x in policy_rows if x["policy"]=="BASE_F80" and x["subperiod"]=="ALL")
    ranked=sorted([x for x in policy_rows if x["subperiod"]=="ALL" and x["policy"]!="BASE_F80"],key=lambda x:((x.get("calmar") or -999),(x.get("cagr") or -999)),reverse=True)
    summary={"status":"RESEARCH_ONLY_NO_RULE_CHANGE","analysis_start":args.analysis_start,"analysis_end":args.analysis_end,"rate_series":SERIES,
             "feature_principles":["level via trailing-252 percentile","velocity via 5/10/20-day bp change and prior-only z-score","acceleration via change-in-5day-change and prior-only z-score","2s10s curve","real-vs-breakeven decomposition"],
             "lookahead_control":"Daily strategy returns use rate data available by prior close; theme ignition rows use same-day close for next-open entries; panic episode starts use prior-day rates.",
             "tqqq_panic_episodes":int(len(ep)),"tqqq_base_f80":base_all,"tqqq_policy_rank_all":ranked,"theme_rows_loaded":bool(theme_rows),
             "warning":"Candidate overlays are diagnostics until they pass subperiod/OOS consistency and are reproduced from exact trade/event logs. No dashboard/main logic is changed."}
    (outdir/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2,default=lambda x:None if pd.isna(x) else x),encoding="utf-8")
    print("===RATE_AUDIT_SUMMARY==="); print(json.dumps(summary,ensure_ascii=False,separators=(",",":"),default=lambda x:None if pd.isna(x) else x)); print("===END===")


if __name__=="__main__": main()
