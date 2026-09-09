from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from research import audit_stock_nqsar_theme30_pit as audit
from research import preimpl_core11_early1_pit as pit
from research import nqsar_centric_broad_scan as broad
from research import nqsar_hybrid_three_role_exact as hybrid
from research import run_backtest_8t3i1e_tqqq_resilient as resilient
import build_v38_sleeve_live as sleeve
import build_v38_early1_live as earlylive

START = pd.Timestamp("2016-01-04")
HOLDOUT_START = pd.Timestamp("2022-01-03")
END = pd.Timestamp("2026-03-20")
VARIANTS = ("NEW_8T3I1E", "SWITCH_BLUE_B70_RISING5")


def safe(x):
    if isinstance(x, dict): return {str(k): safe(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)): return [safe(v) for v in x]
    if isinstance(x, np.integer): return int(x)
    if isinstance(x, (np.floating, float)):
        z = float(x); return z if math.isfinite(z) else None
    if isinstance(x, pd.Timestamp): return str(x.date())
    return x


def px(frame: pd.DataFrame, d: pd.Timestamp, s: str, fallback=np.nan) -> float:
    try:
        z = float(frame.at[d, s])
        return z if np.isfinite(z) and z > 0 else fallback
    except Exception:
        return fallback


def position_map(state):
    return {str(p.get("symbol")): dict(p) for p in state.get("positions", []) if str(p.get("symbol") or "")}


def simulate_trace(idx, mx, nq, e, m, variant: str):
    breadth = pd.to_numeric(mx["breadth"].reindex(idx), errors="coerce")
    breadth_d5 = breadth - breadth.shift(5)
    first = pd.Timestamp(idx[0])
    state = {"status":"READY","asof":str(first.date()),"cash":1.0,"positions":[],
             "pending":{"full_exits":[],"partial25":[],"entries":[]}}
    origins = {}
    nav_rows = []
    entry_rows = []
    contrib_rows = []
    prev_d = None

    for d0 in idx:
        d = pd.Timestamp(d0)
        before_pos = position_map(state)
        prev_nav = float(state.get("nav") or 1.0)
        before_sh = {s: float(p.get("shares") or 0.0) for s,p in before_pos.items()}

        c = pit.companion(d, mx, {}, nq, e, True)
        new_rows = hybrid.hybrid_rows(d, m, "HYBRID8T3I_E1")
        market = c.get("market") or {}
        mode = str(market.get("mode") or "STOP")
        color = str(nq.at[d,"nq_color"]) if d in nq.index and pd.notna(nq.at[d,"nq_color"]) else ""
        b = float(breadth.get(d, np.nan)); b5 = float(breadth_d5.get(d, np.nan))
        choice = "8T3I1E"
        if variant == "NEW_8T3I1E":
            c = dict(c); c["candidates"] = new_rows
        elif variant == "SWITCH_BLUE_B70_RISING5":
            use_current = mode == "ATTACK" and color.title() == "Blue" and np.isfinite(b) and b >= 70.0 and np.isfinite(b5) and b5 >= 0.0
            if use_current:
                choice = "CURRENT"
            else:
                c = dict(c); c["candidates"] = new_rows
        else:
            raise ValueError(variant)

        core_map = {str(r.get("ticker") or ""): dict(r) for r in (c.get("candidates") or [])}
        early_map = {str(r.get("ticker") or ""): dict(r) for r in ((c.get("early1") or {}).get("candidates") or [])}
        state = sleeve.advance_normal(state, c, str(d.date()), mx["open"], mx["close"])
        after_pos = position_map(state)
        after_sh = {s: float(p.get("shares") or 0.0) for s,p in after_pos.items()}

        for s in set(before_sh) | set(after_sh):
            delta = after_sh.get(s,0.0) - before_sh.get(s,0.0)
            if delta > 1e-14:
                rec = core_map.get(s)
                entry_type = "CORE" if rec is not None else "EARLY1" if s in early_map else "OTHER"
                if rec is None: rec = early_map.get(s,{})
                if before_sh.get(s,0.0) <= 1e-14:
                    origins[s] = {"origin_engine": choice if entry_type == "CORE" else entry_type,
                                  "origin_type": entry_type, "origin_date": str(d.date()),
                                  "origin_rank": rec.get("final_rank", rec.get("rank")),
                                  "origin_source": rec.get("source", rec.get("mix_source"))}
                op = px(mx["open"], d, s)
                entry_rows.append({"variant":variant,"date":d,"symbol":s,"shares_added":delta,
                                   "buy_notional":delta*op if np.isfinite(op) else None,
                                   "engine_choice":choice,"entry_type":entry_type,
                                   "market_mode":mode,"nq_color":color,"breadth":b,"breadth_d5":b5,
                                   "rank":rec.get("final_rank", rec.get("rank")),"source":rec.get("source", rec.get("mix_source")),
                                   **origins.get(s,{})})

        if prev_d is not None:
            day_sum = 0.0
            for s in set(before_sh) | set(after_sh):
                pc = px(mx["close"], prev_d, s)
                op = px(mx["open"], d, s, pc)
                cp = px(mx["close"], d, s, op)
                if not (np.isfinite(pc) and np.isfinite(op) and np.isfinite(cp)):
                    continue
                pnl = before_sh.get(s,0.0)*(op-pc) + after_sh.get(s,0.0)*(cp-op)
                cr = pnl / max(prev_nav,1e-12)
                day_sum += cr
                origin = origins.get(s,{})
                contrib_rows.append({"variant":variant,"date":d,"symbol":s,"contribution_return":cr,
                                     "pnl":pnl,"before_shares":before_sh.get(s,0.0),"after_shares":after_sh.get(s,0.0),
                                     "engine_choice":choice,"market_mode":mode,"nq_color":color,"breadth":b,"breadth_d5":b5,
                                     **origin})
            nav_ret = float(state["nav"]) / max(prev_nav,1e-12) - 1.0
            if abs(day_sum-nav_ret) > 2e-8:
                raise RuntimeError(f"ATTRIBUTION_RECONCILE_FAILED {variant} {d.date()} sum={day_sum} navret={nav_ret}")

        for s in list(origins):
            if after_sh.get(s,0.0) <= 1e-14:
                origins.pop(s,None)

        nav_rows.append({"variant":variant,"date":d,"nav":float(state["nav"]),"market_mode":mode,
                         "engine_choice":choice,"breadth":b,"breadth_d5":b5})
        prev_d = d

    return pd.DataFrame(nav_rows), pd.DataFrame(entry_rows), pd.DataFrame(contrib_rows)


def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--root",default="."); ap.add_argument("--output",required=True); ap.add_argument("--batch-size",type=int,default=100)
    args=ap.parse_args(); root=Path(args.root); out=root/args.output; out.mkdir(parents=True,exist_ok=True)
    audit.download_ohlcv = resilient.resilient_download_ohlcv
    symbols,bio=audit.load_universe(root/"universe.csv")
    allowed=earlylive._industry_symbols(root/"industry_map.json"); early_excluded=set(bio)
    if allowed: early_excluded.update(set(symbols)-set(allowed))
    warm=str((START-pd.Timedelta(days=1600)).date()); end_download=str((END+pd.Timedelta(days=1)).date())
    print("DOWNLOAD",flush=True); ohlcv,diag=audit.download_ohlcv(symbols,warm,end_download,args.batch_size)
    if float(diag.get("coverage") or 0)<.85: raise RuntimeError(diag)
    print("BUILD",flush=True); m=broad.build_inputs(ohlcv,bio); mx=audit.build_stock_inputs(ohlcv,bio,END)
    e=pit.early_inputs(ohlcv["close"],ohlcv["volume"],early_excluded)
    nq=audit.market_nqsar(str((START-pd.Timedelta(days=120)).date()),end_download).reindex(mx["close"].index).ffill(limit=2)
    idx=mx["close"].index[(mx["close"].index>=START)&(mx["close"].index<=END)]

    navs=[]; entries=[]; contrib=[]
    for v in VARIANTS:
        print("TRACE",v,flush=True); n,e0,c0=simulate_trace(idx,mx,nq,e,m,v); navs.append(n); entries.append(e0); contrib.append(c0)
    nav=pd.concat(navs,ignore_index=True); ent=pd.concat(entries,ignore_index=True); con=pd.concat(contrib,ignore_index=True)
    nav=nav[pd.to_datetime(nav.date)>=HOLDOUT_START]; ent=ent[pd.to_datetime(ent.date)>=HOLDOUT_START]; con=con[pd.to_datetime(con.date)>=HOLDOUT_START]
    nav.to_csv(out/"nav_trace.csv",index=False); ent.to_csv(out/"entries_trace.csv",index=False); con.to_csv(out/"symbol_daily_contribution.csv.gz",index=False,compression="gzip")

    p=con.pivot_table(index=["date","symbol"],columns="variant",values="contribution_return",aggfunc="sum",fill_value=0).reset_index()
    for v in VARIANTS:
        if v not in p.columns: p[v]=0.0
    p["delta_switch_minus_new"] = p["SWITCH_BLUE_B70_RISING5"] - p["NEW_8T3I1E"]
    sym=p.groupby("symbol",as_index=False)["delta_switch_minus_new"].sum().sort_values("delta_switch_minus_new",ascending=False)
    sym.to_csv(out/"symbol_delta_switch_minus_new.csv",index=False)

    daily=p.groupby("date",as_index=False)["delta_switch_minus_new"].sum(); daily["date"]=pd.to_datetime(daily.date)
    meta=nav[nav.variant=="SWITCH_BLUE_B70_RISING5"][["date","market_mode","engine_choice","breadth","breadth_d5"]].copy(); meta["date"]=pd.to_datetime(meta.date)
    daily=daily.merge(meta,on="date",how="left"); daily.to_csv(out/"daily_delta_switch_minus_new.csv",index=False)
    mode=daily.groupby("market_mode",as_index=False).agg(days=("date","count"),delta_sum=("delta_switch_minus_new","sum"),delta_mean=("delta_switch_minus_new","mean"))
    mode.to_csv(out/"mode_delta_switch_minus_new.csv",index=False)

    current_entries=ent[(ent.variant=="SWITCH_BLUE_B70_RISING5")&(ent.engine_choice=="CURRENT")&(ent.entry_type=="CORE")].copy()
    current_entries.to_csv(out/"switch_current_core_entries.csv",index=False)
    cur_syms=set(current_entries.symbol.astype(str))
    ccur=con[(con.variant=="SWITCH_BLUE_B70_RISING5") & (con.origin_engine=="CURRENT")].copy()
    bysym=ccur.groupby("symbol",as_index=False).agg(contribution_sum=("contribution_return","sum"),days=("date","nunique")) if len(ccur) else pd.DataFrame(columns=["symbol","contribution_sum","days"])
    bysym.sort_values("contribution_sum",ascending=False).to_csv(out/"current_origin_symbol_contribution.csv",index=False)
    bymode=ccur.groupby("market_mode",as_index=False).agg(contribution_sum=("contribution_return","sum"),days=("date","nunique")) if len(ccur) else pd.DataFrame(columns=["market_mode","contribution_sum","days"])
    bymode.to_csv(out/"current_origin_mode_contribution.csv",index=False)

    total=float(daily.delta_switch_minus_new.sum()); top=daily.sort_values("delta_switch_minus_new",ascending=False)
    summary={"method":"Fixed pre-registered Switch A vs frozen 8T3I1E position attribution; no strategy parameter changes.",
             "coverage":diag,"holdout":[str(HOLDOUT_START.date()),str(END.date())],
             "switch_current_core_entries":int(len(current_entries)),"switch_current_unique_symbols":int(current_entries.symbol.nunique()) if len(current_entries) else 0,
             "daily_return_delta_sum":total,
             "top_positive_day_share_of_net":{str(k):float(top.head(k).delta_switch_minus_new.sum()/total) if abs(total)>1e-15 else None for k in (1,5,10,20)},
             "production_changed":False}
    (out/"summary.json").write_text(json.dumps(safe(summary),ensure_ascii=False,indent=2),encoding="utf-8")
    print("DONE",json.dumps(safe(summary),ensure_ascii=False),flush=True)

if __name__=="__main__": main()
