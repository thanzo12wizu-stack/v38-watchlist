from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from audit_rate_rotation_etfs import download_close, attach_prior_rates

TOP = ["XLF", "XLE"]
BOTTOM = ["XLRE", "XLV"]
ALL = ["SPY"] + TOP + BOTTOM
HOLD_START = pd.Timestamp("2022-01-03")
HOLD_END = pd.Timestamp("2026-03-20")


def safe(x):
    if isinstance(x, dict): return {str(k): safe(v) for k,v in x.items()}
    if isinstance(x, list): return [safe(v) for v in x]
    if isinstance(x, (np.integer,)): return int(x)
    if isinstance(x, (np.floating, float)):
        z=float(x); return z if np.isfinite(z) else None
    return x


def add_duration_horizons(r: pd.DataFrame) -> pd.DataFrame:
    x=r.copy()
    for h in (5,10,20):
        x[f"duration_shock_z{h}"] = x[[f"dgs10_chg{h}_z252", f"real10_chg{h}_z252"]].mean(axis=1, skipna=True)
    return x


def fast_block_boot_mean(x: pd.Series, block_ids: pd.Series, reps: int=5000, seed: int=38) -> dict:
    z=pd.DataFrame({"x":pd.to_numeric(x,errors="coerce"),"b":block_ids}).dropna()
    if z.empty: return {"n":0}
    block=z.groupby("b",observed=True)["x"].agg(["sum","count"]).reset_index(drop=True)
    sums=block["sum"].to_numpy(float); counts=block["count"].to_numpy(float)
    nblocks=len(block); rng=np.random.default_rng(seed)
    idx=rng.integers(0,nblocks,size=(reps,nblocks))
    draws=sums[idx].sum(axis=1)/counts[idx].sum(axis=1)
    lo,hi=np.quantile(draws,[.025,.975]); p=2*min(float((draws<=0).mean()),float((draws>=0).mean()))
    return {"n":int(len(z)),"blocks":int(nblocks),"mean":float(z.x.mean()),"lo":float(lo),"hi":float(hi),"p_two":float(min(1,p))}


def evaluate(g: pd.DataFrame, top: list[str], bottom: list[str], factor: str, cut: float, seed: int=38) -> dict:
    spread = g[top].mean(axis=1) - g[bottom].mean(axis=1)
    z = pd.to_numeric(g[factor], errors="coerce")
    signal = np.where(z>=cut,1.0,np.where(z<=-cut,-1.0,0.0))
    rot = pd.Series(spread.to_numpy()*signal, index=g.index)
    block_id = pd.Series(np.arange(len(g))//20, index=g.index)
    boot = fast_block_boot_mean(rot, block_id, reps=5000, seed=seed)
    tight = spread[z>=cut].dropna()
    easing = (-spread[z<=-cut]).dropna()
    active = pd.concat([tight,easing])
    return {
        "factor":factor,"cut":cut,"top":",".join(top),"bottom":",".join(bottom),
        "n_days":int(len(g)),"active_days":int(len(active)),
        "tight_days":int(len(tight)),"ease_days":int(len(easing)),
        "tight_top_minus_bottom_bps":float(tight.mean()*1e4) if len(tight) else None,
        "ease_bottom_minus_top_bps":float(easing.mean()*1e4) if len(easing) else None,
        "active_rotation_bps":float(active.mean()*1e4) if len(active) else None,
        "full_daily_rotation_bps":float(rot.mean()*1e4),
        "boot_lo_bps":float(boot.get("lo")*1e4) if boot.get("lo") is not None else None,
        "boot_hi_bps":float(boot.get("hi")*1e4) if boot.get("hi") is not None else None,
        "boot_p":boot.get("p_two"),
    }


def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--rates",required=True); ap.add_argument("--output",required=True)
    args=ap.parse_args(); out=Path(args.output); out.mkdir(parents=True,exist_ok=True)
    close=download_close(ALL,"2015-12-20","2026-03-21")
    ret=close.pct_change(fill_method=None).loc[pd.Timestamp("2016-01-04"):HOLD_END].copy()
    rates=add_duration_horizons(pd.read_csv(args.rates))
    m=attach_prior_rates(ret,rates)
    hold=m[(m.date>=HOLD_START)&(m.date<=HOLD_END)].copy().reset_index(drop=True)
    periods={"HOLD_ALL":hold,"2022-2023":hold[hold.date<=pd.Timestamp("2023-12-31")].copy(),"2024-2026":hold[hold.date>=pd.Timestamp("2024-01-01")].copy()}

    rows=[]
    for pname,g in periods.items():
        for cut in (0.50,0.75,1.00,1.25):
            r=evaluate(g,TOP,BOTTOM,"duration_shock_z5",cut,100+int(cut*100)); r["period"]=pname; r["test"]="CUT_SENSITIVITY"; rows.append(r)
        for h in (5,10,20):
            r=evaluate(g,TOP,BOTTOM,f"duration_shock_z{h}",0.75,200+h); r["period"]=pname; r["test"]="HORIZON_SENSITIVITY"; rows.append(r)

    variants=[
        ("PAIR_PAIR",TOP,BOTTOM),
        ("XLF_PAIR",["XLF"],BOTTOM),
        ("XLE_PAIR",["XLE"],BOTTOM),
        ("PAIR_XLRE",TOP,["XLRE"]),
        ("PAIR_XLV",TOP,["XLV"]),
        ("XLF_XLRE",["XLF"],["XLRE"]),
        ("XLF_XLV",["XLF"],["XLV"]),
        ("XLE_XLRE",["XLE"],["XLRE"]),
        ("XLE_XLV",["XLE"],["XLV"]),
    ]
    loo=[]
    for pname,g in periods.items():
        for i,(name,t,b) in enumerate(variants):
            r=evaluate(g,t,b,"duration_shock_z5",0.75,500+i); r["period"]=pname; r["variant"]=name; loo.append(r)

    df=pd.DataFrame(rows); dl=pd.DataFrame(loo)
    df.to_csv(out/"threshold_horizon_robustness.csv",index=False)
    dl.to_csv(out/"leave_one_out_robustness.csv",index=False)

    base=df[(df.period=="HOLD_ALL")&(df.test=="CUT_SENSITIVITY")&(df.cut==0.75)].iloc[0].to_dict()
    sub=df[(df.test=="CUT_SENSITIVITY")&(df.cut==0.75)].set_index("period").to_dict(orient="index")
    horizons=df[(df.period=="HOLD_ALL")&(df.test=="HORIZON_SENSITIVITY")].set_index("factor").to_dict(orient="index")
    loo_all=dl[dl.period=="HOLD_ALL"].set_index("variant").to_dict(orient="index")
    result={
        "status":"RESEARCH_ONLY_NO_RULE_CHANGE",
        "frozen_group":{"tightening_favor":TOP,"easing_favor":BOTTOM,"selection_source":"2016-2021 GICS11 duration_shock_z5 discovery ranking"},
        "holdout":"2022-01-03..2026-03-20",
        "prior_close_only":True,
        "base_cut_075":base,
        "subperiod_cut_075":sub,
        "horizon_sensitivity_hold_all":horizons,
        "leave_one_out_hold_all":loo_all,
        "decision_rule":"Do not adopt if the effect is confined to one subperiod, one threshold, one horizon, or one constituent pair.",
    }
    (out/"summary.json").write_text(json.dumps(safe(result),ensure_ascii=False,indent=2),encoding="utf-8")
    print("===RATE_ROTATION_ROBUSTNESS===")
    print(json.dumps(safe(result),ensure_ascii=False,separators=(",",":")))
    print("===END===")

if __name__=="__main__": main()
