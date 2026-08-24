#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

import market_conditions_compare as base
import market_conditions_compare_v2 as v2

EVAL_END = pd.Timestamp("2026-08-21")

CANDIDATES = {
    "v2_25452010": (.25,.45,.20,.10),
    "mid_15552010": (.15,.55,.20,.10),
    "mid_15502510": (.15,.50,.25,.10),
    "mid_10552510": (.10,.55,.25,.10),
}


def score_frame(px: pd.DataFrame, weights):
    f = v2.new_mc_direct(px, weights).copy()
    # Recovery telemetry deliberately excludes 5D return and 10SMA so it measures broader repair,
    # not the same short-horizon move that NQSAR is intended to catch.
    f["repair_breadth"] = f[["above20","ret21","above50","ma20_gt_50"]].mean(axis=1)
    f["repair_thrust10"] = f["repair_breadth"] - f["repair_breadth"].shift(10)
    f["medium_delta10"] = f["medium"] - f["medium"].shift(10)
    f["score_delta10"] = f["score"] - f["score"].shift(10)
    return f


def drawdown_episodes(qqq: pd.Series, trigger=-0.08, exit_dd=-0.02):
    q = qqq.dropna().copy()
    episodes=[]
    peak_price=float(q.iloc[0]); peak_date=q.index[0]
    in_ep=False; start=None; ep_peak_date=None; ep_peak_price=None
    trough_date=None; trough_price=None
    for dt, val0 in q.items():
        val=float(val0)
        if not in_ep:
            if val > peak_price:
                peak_price=val; peak_date=dt
            dd=val/peak_price-1
            if dd <= trigger:
                in_ep=True; start=dt; ep_peak_date=peak_date; ep_peak_price=peak_price
                trough_date=dt; trough_price=val
        else:
            if val < trough_price:
                trough_price=val; trough_date=dt
            dd=val/ep_peak_price-1
            if dd >= exit_dd:
                episodes.append({
                    "peak":ep_peak_date,"start":start,"trough":trough_date,"end":dt,
                    "peak_price":ep_peak_price,"trough_price":trough_price,
                    "dd":trough_price/ep_peak_price-1,
                })
                in_ep=False; peak_price=val; peak_date=dt
    if in_ep:
        episodes.append({
            "peak":ep_peak_date,"start":start,"trough":trough_date,"end":q.index[-1],
            "peak_price":ep_peak_price,"trough_price":trough_price,
            "dd":trough_price/ep_peak_price-1,
        })
    # keep meaningful episodes and de-duplicate tiny late fragments
    return [e for e in episodes if e["dd"] <= trigger]


def sess_between(index, a, b):
    z=index[(index>=a)&(index<=b)]
    return max(len(z)-1,0)


def first_after(series: pd.Series, dt, cond, limit=60):
    s=series.loc[series.index>=dt].iloc[:limit+1]
    mask=cond(s)
    if mask.any():
        return s.index[int(np.argmax(mask.to_numpy()))]
    return None


def recovery_episode_stats(frame: pd.DataFrame, qqq: pd.Series, episodes):
    out=[]
    idx=qqq.dropna().index
    for e in episodes:
        t=e["trough"]
        if t not in frame.index: continue
        pos=idx.get_indexer([t], method="nearest")[0]
        snap={}
        for h in (0,5,10,20,40):
            if pos+h < len(idx):
                d=idx[pos+h]
                snap[f"d{h}"]={
                    "date":str(d.date()),
                    "score":float(frame.loc[d,"score"]) if pd.notna(frame.loc[d,"score"]) else None,
                    "medium":float(frame.loc[d,"medium"]) if pd.notna(frame.loc[d,"medium"]) else None,
                    "repair_breadth":float(frame.loc[d,"repair_breadth"]) if pd.notna(frame.loc[d,"repair_breadth"]) else None,
                    "thrust10":float(frame.loc[d,"repair_thrust10"]) if pd.notna(frame.loc[d,"repair_thrust10"]) else None,
                    "qqq_from_trough_pct":float((qqq.loc[d]/qqq.loc[t]-1)*100),
                }
        sigs={}
        tests={
            "thrust": lambda x: x["repair_thrust10"]>=10,
            "repair45": lambda x: (x["score"]>=45)&(x["repair_breadth"]>=45)&(x["repair_thrust10"]>0),
            "repair55": lambda x: (x["score"]>=55)&(x["medium"]>=50),
            "bull65": lambda x: x["score"]>=65,
        }
        after=frame.loc[frame.index>=t].iloc[:61]
        for name,fn in tests.items():
            m=fn(after).fillna(False)
            d=after.index[int(np.argmax(m.to_numpy()))] if m.any() else None
            sigs[name]={"date":str(d.date()) if d is not None else None,
                        "sessions":sess_between(idx,t,d) if d is not None else None}
        out.append({
            "peak":str(e["peak"].date()),"trough":str(t.date()),"end":str(e["end"].date()),
            "dd_pct":float(e["dd"]*100),"snapshots":snap,"signals":sigs,
        })
    return out


def trigger_quality(frame: pd.DataFrame, qqq: pd.Series, episodes):
    # Evaluate the first recovery-thrust trigger after an episode has entered >=8% drawdown.
    # False = trigger occurs before the final trough and a materially lower low (>3%) follows within 20 sessions.
    rows=[]; idx=qqq.dropna().index
    for e in episodes:
        z=frame.loc[(frame.index>=e["start"])&(frame.index<=e["end"])].copy()
        eligible=(z["repair_thrust10"]>=10)&(z["repair_breadth"]>=35)&(z["score"]<60)
        if not eligible.any():
            rows.append({"trough":str(e["trough"].date()),"trigger":None,"false_lower_low":None}); continue
        d=z.index[int(np.argmax(eligible.to_numpy()))]
        p0=idx.get_indexer([d],method="nearest")[0]
        future=qqq.iloc[p0:min(p0+21,len(qqq))]
        lower=float(future.min()/qqq.loc[d]-1) if len(future) else np.nan
        false=bool(d<e["trough"] and lower<=-.03)
        rows.append({"trough":str(e["trough"].date()),"trigger":str(d.date()),
                     "sessions_vs_trough":int(sess_between(idx,d,e["trough"]))*(-1 if d<e["trough"] else 1),
                     "worst20_from_trigger_pct":float(lower*100),"false_lower_low":false})
    vals=[r for r in rows if r.get("false_lower_low") is not None]
    return {
        "episodes":rows,
        "triggered":len(vals),
        "false_count":sum(1 for r in vals if r["false_lower_low"]),
        "false_rate_pct":float(np.mean([r["false_lower_low"] for r in vals])*100) if vals else None,
    }


def horizon_correlations(score: pd.Series, qqq: pd.Series):
    d=pd.DataFrame({"s":score,"q":qqq}).dropna()
    out={}
    for h in (5,10,21,63,126):
        r=d["q"]/d["q"].shift(h)-1
        out[f"qqq_ret{h}_corr"]=float(d["s"].corr(r))
    return out


def gate_overlap(score: pd.Series):
    p=Path("trend_history.json")
    if not p.exists(): return {}
    raw=json.loads(p.read_text(encoding="utf-8"))
    g=pd.DataFrame(raw,columns=["date","gate"]); g["date"]=pd.to_datetime(g["date"])
    order={"Red":0,"Yellow":1,"Green":2,"Blue":3}; g["ord"]=g["gate"].map(order)
    s=pd.DataFrame({"date":score.index,"score":score.values})
    m=g.merge(s,on="date",how="inner").dropna()
    if m.empty:return {}
    by={k:{"n":int(len(x)),"mean":float(x["score"].mean())} for k,x in m.groupby("gate")}
    changes=int((m["gate"]!=m["gate"].shift()).sum()-1)
    # Score band with 5-point hysteresis, sampled on same NQSAR dates.
    hs=v2.hysteresis_changes(pd.Series(m["score"].to_numpy(),index=m["date"]),5.0)
    return {"n":int(len(m)),"by_gate":by,"gate_changes":changes,
            "score_gate_spearman":float(m["score"].corr(m["ord"],method="spearman")),
            "mc_hysteresis_changes":int(hs["changes"])}


def aggregate_recovery(epstats):
    out={}
    for sig in ("thrust","repair45","repair55","bull65"):
        a=[e["signals"][sig]["sessions"] for e in epstats if e["signals"][sig]["sessions"] is not None]
        out[f"{sig}_avg_sessions"] = float(np.mean(a)) if a else None
        out[f"{sig}_median_sessions"] = float(np.median(a)) if a else None
        out[f"{sig}_coverage"] = len(a)
    for h in (0,5,10,20,40):
        for fld in ("score","medium","repair_breadth","thrust10"):
            a=[e["snapshots"].get(f"d{h}",{}).get(fld) for e in epstats]
            a=[x for x in a if x is not None]
            out[f"d{h}_{fld}_mean"] = float(np.mean(a)) if a else None
    return out


def main():
    px,failed=base.download_prices(); qqq=px["QQQ"].loc[:EVAL_END]
    eval_start=pd.Timestamp(base.EVAL_START)
    episodes=drawdown_episodes(qqq.loc[qqq.index>=eval_start],trigger=-.08,exit_dd=-.02)
    candidates={k:score_frame(px,w) for k,w in CANDIDATES.items()}
    references={"current_mri_standardized":base.current_mri_standardized(px),
                "oratnek_like":base.oratnek_like(px)}
    result={
        "scope":{"evaluation":"2016-01-01..2026-08-21","failed_tickers":failed,
                 "episode_rule":"QQQ drawdown >=8% from running peak; episode ends when drawdown recovers to within 2% of peak",
                 "recovery_thrust":"10-session change in mean(above20, ret21>0 participation, above50, 20SMA>50SMA); excludes 5D and 10SMA"},
        "episodes":[{"peak":str(e["peak"].date()),"trough":str(e["trough"].date()),"end":str(e["end"].date()),"dd_pct":float(e["dd"]*100)} for e in episodes],
        "candidates":{},"references":{}
    }
    for name,f in candidates.items():
        s=f["score"].where((f.index>=eval_start)&(f.index<=EVAL_END))
        eps=recovery_episode_stats(f.loc[:EVAL_END],qqq,episodes)
        result["candidates"][name]={
            "weights":CANDIDATES[name],
            "horizon_corr":horizon_correlations(s,qqq),
            "gate_overlap":gate_overlap(s),
            "recovery":aggregate_recovery(eps),
            "thrust_quality":trigger_quality(f.loc[:EVAL_END],qqq,episodes),
            "episode_detail":eps,
            "noise":{"mean_abs_daily_change":float(s.diff().abs().mean()),
                     "hysteresis_changes_per_year":v2.hysteresis_changes(s.dropna(),5.0)["changes_per_year"]},
            "latest":{"date":str(s.dropna().index[-1].date()),"score":float(s.dropna().iloc[-1]),
                      "delta10":float(f.loc[s.dropna().index[-1],"score_delta10"]),
                      "repair_thrust10":float(f.loc[s.dropna().index[-1],"repair_thrust10"]),
                      "repair_breadth":float(f.loc[s.dropna().index[-1],"repair_breadth"])}
        }
    for name,f in references.items():
        s=f["score"].where((f.index>=eval_start)&(f.index<=EVAL_END))
        result["references"][name]={"horizon_corr":horizon_correlations(s,qqq),"gate_overlap":gate_overlap(s),
                                    "noise":{"mean_abs_daily_change":float(s.diff().abs().mean()),
                                             "hysteresis_changes_per_year":v2.hysteresis_changes(s.dropna(),5.0)["changes_per_year"]}}
    Path("market_conditions_recovery_validation.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    compact={"scope":result["scope"],"episodes":result["episodes"],"candidates":{},"references":result["references"]}
    for name,x in result["candidates"].items():
        compact["candidates"][name]={k:x[k] for k in ["weights","horizon_corr","gate_overlap","recovery","thrust_quality","noise","latest"]}
    Path("market_conditions_recovery_validation_compact.json").write_text(json.dumps(compact,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(compact,ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
