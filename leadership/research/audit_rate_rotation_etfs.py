from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

GICS = ["XLK","XLC","XLY","XLP","XLE","XLF","XLV","XLI","XLB","XLRE","XLU"]
STYLE = ["IWM","IWF","IWD","RSP","MDY"]
FACTORS = [
    "rate_shock_z5",
    "duration_shock_z5",
    "dgs2_chg5_z252",
    "real10_chg5_z252",
    "rate_accel_z5",
    "duration_accel_z5",
]
CUT = 0.75
TRAIN_END = pd.Timestamp("2021-12-31")
HOLD_START = pd.Timestamp("2022-01-03")


def _safe(x):
    if isinstance(x, dict): return {str(k): _safe(v) for k,v in x.items()}
    if isinstance(x, list): return [_safe(v) for v in x]
    if isinstance(x, (np.integer,)): return int(x)
    if isinstance(x, (np.floating, float)):
        z=float(x); return z if np.isfinite(z) else None
    if isinstance(x, pd.Timestamp): return x.isoformat()
    return x


def download_close(tickers: list[str], start: str, end: str) -> pd.DataFrame:
    raw = yf.download(tickers, start=start, end=end, auto_adjust=True, progress=False,
                      group_by="column", threads=True, timeout=60)
    if raw.empty: raise RuntimeError("empty yfinance download")
    if isinstance(raw.columns, pd.MultiIndex):
        if "Close" in raw.columns.get_level_values(0): close = raw["Close"].copy()
        elif "Close" in raw.columns.get_level_values(1): close = raw.xs("Close", axis=1, level=1).copy()
        else: raise RuntimeError("Close not found in yfinance response")
    else:
        close = raw[["Close"]].rename(columns={"Close": tickers[0]})
    close.index = pd.to_datetime(close.index).tz_localize(None)
    close = close.sort_index()
    return close


def attach_prior_rates(ret: pd.DataFrame, rates: pd.DataFrame) -> pd.DataFrame:
    d = ret.copy(); d.index.name="date"; d=d.reset_index().sort_values("date")
    d["signal_cutoff"] = d["date"] - pd.Timedelta(days=1)
    r = rates.copy(); r["date"]=pd.to_datetime(r["date"]); r=r.sort_values("date").rename(columns={"date":"rate_date"})
    m = pd.merge_asof(d, r, left_on="signal_cutoff", right_on="rate_date",
                      direction="backward", tolerance=pd.Timedelta(days=7))
    return m.sort_values("date").reset_index(drop=True)


def block_boot_mean(x: pd.Series, block_ids: pd.Series, reps: int=5000, seed: int=38) -> dict:
    z = pd.DataFrame({"x":pd.to_numeric(x, errors="coerce"), "b":block_ids}).dropna()
    if z.empty: return {"n":0}
    block = z.groupby("b", observed=True)["x"].agg(["sum","count"])
    keys=block.index.to_numpy(); rng=np.random.default_rng(seed)
    draws=np.empty(reps)
    for i in range(reps):
        k=rng.choice(keys, size=len(keys), replace=True)
        draws[i]=block.loc[k,"sum"].sum()/block.loc[k,"count"].sum()
    obs=float(z.x.mean()); lo,hi=np.quantile(draws,[.025,.975])
    p=2*min(float((draws<=0).mean()), float((draws>=0).mean()))
    return {"n":int(len(z)),"blocks":int(len(keys)),"mean":obs,"lo":float(lo),"hi":float(hi),"p_two":float(min(1,p))}


def state_score(g: pd.DataFrame, ticker: str, factor: str) -> dict:
    ex = g[ticker] - g["SPY"]
    tight = g[factor] >= CUT
    ease = g[factor] <= -CUT
    a=ex[tight].dropna(); b=ex[ease].dropna()
    return {
        "n_tight":int(len(a)), "n_ease":int(len(b)),
        "tight_excess_bps":float(a.mean()*1e4) if len(a) else np.nan,
        "ease_excess_bps":float(b.mean()*1e4) if len(b) else np.nan,
        "tight_minus_ease_bps":float((a.mean()-b.mean())*1e4) if len(a) and len(b) else np.nan,
        "beta":float(ex.cov(g[factor])/g[factor].var()) if g[factor].var()>0 else np.nan,
    }


def universe_audit(m: pd.DataFrame, names: list[str], universe_name: str) -> tuple[list[dict],list[dict],dict]:
    train=m[m.date<=TRAIN_END].copy(); hold=m[m.date>=HOLD_START].copy()
    entity=[]; group=[]; summary={}
    for factor in FACTORS:
        trows=[]; hrows=[]
        for tk in names:
            ts=state_score(train,tk,factor); hs=state_score(hold,tk,factor)
            row={"universe":universe_name,"factor":factor,"ticker":tk,
                 **{f"train_{k}":v for k,v in ts.items()}, **{f"hold_{k}":v for k,v in hs.items()}}
            row["sign_agree"] = bool(np.sign(ts["tight_minus_ease_bps"])==np.sign(hs["tight_minus_ease_bps"])) if np.isfinite(ts["tight_minus_ease_bps"]) and np.isfinite(hs["tight_minus_ease_bps"]) else None
            entity.append(row); trows.append((tk,ts["tight_minus_ease_bps"])); hrows.append((tk,hs["tight_minus_ease_bps"]))
        td=pd.Series(dict(trows),dtype=float); hd=pd.Series(dict(hrows),dtype=float)
        common=td.dropna().index.intersection(hd.dropna().index)
        # Spearman = Pearson correlation of ranks; calculate directly to avoid scipy dependency.
        rho=float(td.loc[common].rank(method="average").corr(hd.loc[common].rank(method="average"))) if len(common)>=4 else np.nan
        sign_rate=float(np.mean(np.sign(td.loc[common])==np.sign(hd.loc[common]))) if len(common) else np.nan
        valid=td.dropna().sort_values()
        k=min(4,max(2,len(valid)//4))
        bottom=list(valid.index[:k]); top=list(valid.index[-k:])
        spread=hold[top].mean(axis=1)-hold[bottom].mean(axis=1)
        z=hold[factor]
        signal=np.where(z>=CUT,1.0,np.where(z<=-CUT,-1.0,0.0))
        rot=pd.Series(spread.to_numpy()*signal,index=hold.index)
        block_id=(np.arange(len(hold))//20)
        boot=block_boot_mean(rot,pd.Series(block_id,index=hold.index),reps=5000,seed=38)
        tight=spread[z>=CUT].dropna(); ease=(-spread[z<=-CUT]).dropna()
        active=pd.concat([tight,ease])
        group_row={"universe":universe_name,"factor":factor,"top_train":",".join(top),"bottom_train":",".join(bottom),
                   "rank_spearman_train_hold":rho,"sign_agreement":sign_rate,
                   "hold_tight_top_minus_bottom_bps":float(tight.mean()*1e4) if len(tight) else np.nan,
                   "hold_ease_bottom_minus_top_bps":float(ease.mean()*1e4) if len(ease) else np.nan,
                   "hold_active_rotation_bps":float(active.mean()*1e4) if len(active) else np.nan,
                   "hold_active_days":int(len(active)),
                   "hold_full_daily_rotation_bps":float(rot.mean()*1e4),
                   "hold_full_daily_boot_lo_bps":float(boot.get("lo",np.nan)*1e4) if boot.get("lo") is not None else np.nan,
                   "hold_full_daily_boot_hi_bps":float(boot.get("hi",np.nan)*1e4) if boot.get("hi") is not None else np.nan,
                   "hold_full_daily_boot_p":boot.get("p_two")}
        group.append(group_row)
        summary[factor]=group_row
    return entity,group,summary


def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--rates",required=True); ap.add_argument("--output",required=True)
    ap.add_argument("--start",default="2016-01-04"); ap.add_argument("--end",default="2026-03-21")
    args=ap.parse_args(); out=Path(args.output); out.mkdir(parents=True,exist_ok=True)
    tickers=["SPY"]+GICS+STYLE
    close=download_close(tickers,str(pd.Timestamp(args.start)-pd.Timedelta(days=10)).split()[0],args.end)
    missing=[t for t in tickers if t not in close.columns]
    if missing: raise RuntimeError(f"missing tickers: {missing}")
    ret=close.pct_change(fill_method=None).loc[pd.Timestamp(args.start):pd.Timestamp(args.end)].copy()
    rates=pd.read_csv(args.rates); m=attach_prior_rates(ret,rates)
    m=m[(m.date>=pd.Timestamp(args.start))&(m.date<=pd.Timestamp("2026-03-20"))].copy()
    all_entity=[]; all_group=[]; summaries={}
    for uname,names in [("GICS11",GICS),("GICS11_STYLE5",GICS+STYLE)]:
        e,g,s=universe_audit(m,names,uname); all_entity+=e; all_group+=g; summaries[uname]=s
    pd.DataFrame(all_entity).to_csv(out/"entity_rate_sensitivity.csv",index=False)
    pd.DataFrame(all_group).to_csv(out/"holdout_rotation_groups.csv",index=False)
    coverage={t:{"first":str(close[t].dropna().index.min().date()),"last":str(close[t].dropna().index.max().date()),"n":int(close[t].notna().sum())} for t in tickers}
    result={"status":"RESEARCH_ONLY_NO_RULE_CHANGE","train":"2016-01-04..2021-12-31","holdout":"2022-01-03..2026-03-20",
            "state_cut_abs_z":CUT,"universes":{"GICS11":GICS,"STYLE5":STYLE},"factors":FACTORS,
            "method":"Rank ETFs in TRAIN by SPY-relative return difference on tightening vs easing days; freeze top/bottom groups; validate rank stability and directional top-bottom spread in HOLDOUT. Rate features are prior-close only. 20-trading-day block bootstrap is applied to full-daily signed rotation spread.",
            "coverage":coverage,"summary":summaries}
    (out/"summary.json").write_text(json.dumps(_safe(result),ensure_ascii=False,indent=2),encoding="utf-8")
    print("===RATE_ROTATION_SUMMARY===")
    print(json.dumps(_safe(result),ensure_ascii=False,separators=(",",":")))
    print("===END===")

if __name__=="__main__": main()
