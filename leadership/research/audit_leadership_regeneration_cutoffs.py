from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import audit_leadership_cycle as lc
import audit_leadership_combinations as combo
import audit_ordinary_stock_market_mode_robustness as base

DISC_END = pd.Timestamp("2021-12-31")
CONF_START = pd.Timestamp("2022-01-03")


def safe(v: Any) -> Any:
    if isinstance(v, dict): return {str(k): safe(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)): return [safe(x) for x in v]
    if isinstance(v, np.integer): return int(v)
    if isinstance(v, (np.floating, float)):
        x=float(v); return x if math.isfinite(x) else None
    if isinstance(v, pd.Timestamp): return v.isoformat()
    return v


def eventize(mask: pd.Series, cooldown: int = 20) -> list[pd.Timestamp]:
    m=mask.fillna(False).astype(bool)
    cross=m & ~m.shift(1, fill_value=False)
    out=[]; last=-10**9
    for i,v in enumerate(cross.to_numpy(bool)):
        if v and i-last>=cooldown:
            out.append(pd.Timestamp(cross.index[i])); last=i
    return out


def bootstrap_pair(a: np.ndarray, b: np.ndarray, seed: int, reps: int = 20000) -> dict[str, Any]:
    ok=np.isfinite(a)&np.isfinite(b)
    d=np.asarray(a[ok]-b[ok],float)
    if len(d)<3: return {"n":int(len(d))}
    rng=np.random.default_rng(seed)
    means=d[rng.integers(0,len(d),(reps,len(d)))].mean(axis=1)
    return {"n":len(d),"mean_delta":float(d.mean()),"median_delta":float(np.median(d)),
            "ci025":float(np.quantile(means,.025)),"ci05":float(np.quantile(means,.05)),
            "ci95":float(np.quantile(means,.95)),"ci975":float(np.quantile(means,.975)),
            "prob_delta_gt0":float((means>0).mean())}


def nearest_pairs(frame: pd.DataFrame, dates: list[pd.Timestamp], mask: pd.Series, f2_cut: float) -> list[tuple[pd.Timestamp,pd.Timestamp,float]]:
    feats=["breadth50","qqq_ret20_back","f1","f2","f3","leader_temp"]
    used=set(); out=[]
    for d in dates:
        r=frame.loc[d]
        pool=frame.loc[(frame["split"]==r["split"])&(frame["mode"]==r["mode"])&(frame["nqsar"]==r["nqsar"])&(~mask.reindex(frame.index).fillna(False))&(frame["f2"]<f2_cut)].copy()
        p=frame.index.get_loc(d)
        keep=[c for c in pool.index if abs(int(frame.index.get_loc(c))-int(p))>40 and c not in used]
        pool=pool.loc[keep]
        if pool.empty: continue
        sf=frame.loc[frame["split"]==r["split"],feats]
        scale=(sf.quantile(.75)-sf.quantile(.25)).replace(0,np.nan)
        dist=(((pool[feats]-r[feats]).divide(scale))**2).sum(axis=1,skipna=False).dropna()
        if dist.empty: continue
        c=pd.Timestamp(dist.idxmin()); used.add(c); out.append((d,c,float(dist.loc[c])))
    return out


def report(frame: pd.DataFrame, mask: pd.Series, cut: float, qqq: pd.DataFrame, spy: pd.DataFrame, nq: pd.Series, cooldown: int) -> dict[str, Any]:
    dates=eventize(mask,cooldown); result={"cooldown":cooldown,"splits":{}}
    for split in ("DISCOVERY","CONFIRMATION"):
        ds=[d for d in dates if frame.at[d,"split"]==split]
        pairs=nearest_pairs(frame,ds,mask,cut)
        ed=[x[0] for x in pairs]; cd=[x[1] for x in pairs]
        eo=combo.outcome_table(ed,qqq,spy,nq).set_index("signal_date") if ed else pd.DataFrame()
        co=combo.outcome_table(cd,qqq,spy,nq).set_index("signal_date") if cd else pd.DataFrame()
        z={"n_events":len(ds),"n_pairs":len(pairs),"event_dates":[str(d.date()) for d in ds]}
        if pairs:
            for h in (20,40,60):
                for col in (f"qqq_ret_{h}",f"spy_ret_{h}",f"excess_{h}",f"qqq_mdd_{h}"):
                    a=pd.to_numeric(eo.reindex(ed).get(col),errors="coerce").to_numpy(float)
                    b=pd.to_numeric(co.reindex(cd).get(col),errors="coerce").to_numpy(float)
                    z[col]=bootstrap_pair(a,b,20260902+int(cut*1000)+h+len(col))
            er=pd.to_numeric(eo.reindex(ed).get("qqq_ret_60"),errors="coerce").dropna()
            z["event_ret60_mean"]=float(er.mean()) if len(er) else None
            z["event_ret60_win_rate"]=float((er>0).mean()) if len(er) else None
        result["splits"][split]=z
    return result


def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--root",default="."); ap.add_argument("--output",required=True)
    ap.add_argument("--analysis-start",default="2016-01-04"); ap.add_argument("--analysis-end",default="2026-08-31")
    ap.add_argument("--max-tickers",type=int,default=6000); ap.add_argument("--batch-size",type=int,default=75); a=ap.parse_args()
    root=Path(a.root); out=root/a.output; out.mkdir(parents=True,exist_ok=True)
    meta,matrices=base.build_inputs(root,a.analysis_start,a.analysis_end,a.max_tickers,a.batch_size)
    idx=pd.DatetimeIndex(meta["analysis_idx"]); breadth=meta["breadth"].reindex(idx); nq=meta["nq"].reindex(idx)["nq_color"].astype(object).ffill(limit=1)
    sig=lc.build_leadership_series(matrices).reindex(idx)
    market=lc.download_market(str((pd.Timestamp(a.analysis_start)-pd.Timedelta(days=10)).date()),str((pd.Timestamp(a.analysis_end)+pd.Timedelta(days=120)).date()))
    qqq=market["QQQ"]; spy=market["SPY"].reindex(qqq.index).ffill(limit=1)
    frame=combo.add_market_features(sig,breadth,nq,qqq); gate=frame["gate_on"]
    recent15=combo.recent_low(frame["leader_temp"],15.0,40)
    reports={}
    for cut in (0.30,0.40,0.50):
        mask=recent15 & combo.cross_below(frame["f2"],cut) & gate
        for cd in (20,40): reports[f"F2_RECOVER_{int(cut*100)}_CD{cd}"]=report(frame,mask,cut,qqq,spy,nq,cd)
    result={"status":"FROZEN_REGENERATION_CUTOFF_COMPARISON","definition":"Temperature <=15 sometime in prior 40 sessions; F2 crosses down through tested recovery line; NQSAR/Breadth gate is Selective or Attack","cutoffs":[0.30,0.40,0.50],"reports":reports,"coverage":{"selected":meta.get("selected"),"downloaded":meta.get("downloaded")},"warning":"Cutoff comparison is retrospective robustness, not prospective OOS."}
    (out/"summary_regeneration_cutoffs.json").write_text(json.dumps(safe(result),ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(safe(result),ensure_ascii=False,indent=2),flush=True)

if __name__=="__main__": main()
