from __future__ import annotations

import argparse
import gc
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import audit_ordinary_stock_market_mode_robustness as base
import audit_ordinary_stock_exit_trail as ex
import audit_ordinary_stock_theme_leave_one_out as loo
import audit_ordinary_stock_rebalance_vs_trail as rt
import audit_five_year_leader_capture as lc
import audit_core_emerging_leader_mix as cem
import audit_core_emerging_hybrid_refine as hyb
import audit_core_releadership_priority as rel
import validate_early_rotation as er


BANNED_SYMBOLS: set[str] = set()


def safe(v: Any) -> Any:
    return base.safe(v)


def _v(frame: pd.DataFrame, d: pd.Timestamp, sym: str, default: float = np.nan) -> float:
    try:
        x = float(frame.at[d, sym])
        return x if np.isfinite(x) else default
    except Exception:
        return default


def signal_ok(d: pd.Timestamp, sym: str, matrices, features, variant: rel.Variant) -> bool:
    if sym in BANNED_SYMBOLS:
        return False
    if variant.rule == "NONE":
        return False
    rs, hi, th, dv, fresh = rel.component_flags(d, sym, matrices, features, variant.profile)
    n = int(rs) + int(hi) + int(th) + int(dv)
    if variant.rule == "RS": return rs
    if variant.rule == "HIGH": return hi
    if variant.rule == "THEME": return th
    if variant.rule == "DVOL": return dv
    if variant.rule == "RS_HIGH": return rs and hi
    if variant.rule == "RS_HIGH_THEME": return rs and hi and th
    if variant.rule == "RS_HIGH_DVOL": return rs and hi and dv
    if variant.rule == "RS_THEME_DVOL": return rs and th and dv
    if variant.rule == "HIGH_THEME_DVOL": return hi and th and dv
    if variant.rule == "ALL4": return rs and hi and th and dv
    if variant.rule == "THREE4": return n >= 3
    if variant.rule == "RS_HIGH_PLUS_ONE": return rs and hi and (th or dv)
    if variant.rule == "FRESH10_RS_HIGH_PLUS_ONE": return rs and hi and fresh and (th or dv)
    if variant.rule == "BREAK_RS_PLUS_ONE":
        br = _v(rel.EXT["high_ratio"], d, sym)
        return rs and np.isfinite(br) and br >= 1.0 and (th or dv)
    raise ValueError(f"unknown rule {variant.rule}")


def set_context(theme_rank: pd.DataFrame, dvol_ratio20: pd.DataFrame) -> None:
    rel.EXT["theme_rank"] = theme_rank
    rel.EXT["theme_delta20"] = (theme_rank - theme_rank.shift(20)).astype(np.float32)
    rel.EXT["dvol_ratio20"] = dvol_ratio20


def build_theme_rank(root: Path, matrices: dict[str, pd.DataFrame], min_members: int, agg: str):
    close, rs63 = matrices["close"], matrices["rs63"]
    cols = list(close.columns); pos = {s:i for i,s in enumerate(cols)}; stock_set = set(cols)
    snapshot = er.load_json(root / "sector_snapshot.json")
    theme_members_all, _ = er.extract_theme_members(snapshot)
    themes = {str(t): [s for s in members if s in stock_set] for t,members in theme_members_all.items()}
    themes = {t:m for t,m in themes.items() if len(m) >= min_members}
    count = np.zeros(len(cols), dtype=np.int16)
    arr = np.full((len(close.index), len(cols)), np.nan, dtype=np.float32)
    store = [[] for _ in cols] if agg == "median" else None
    memberships = 0
    for n, members in enumerate(themes.values(), start=1):
        rank = rs63[members].rank(axis=1, pct=True, method="average").to_numpy(dtype=np.float32) * 100.0
        for j, sym in enumerate(members):
            si = pos[sym]; count[si] += 1
            if agg == "best": arr[:,si] = np.fmax(arr[:,si], rank[:,j])
            elif agg == "median": store[si].append(rank[:,j].copy())
            else: raise ValueError(agg)
        memberships += len(members)
        if n % 75 == 0 or n == len(themes): print(f"THEME_{agg.upper()}_MIN{min_members} {n}/{len(themes)}", flush=True)
    if agg == "median":
        for si, xs in enumerate(store):
            if xs: arr[:,si] = np.nanmedian(np.column_stack(xs), axis=1).astype(np.float32)
        del store; gc.collect()
    frame = pd.DataFrame(arr, index=close.index, columns=cols)
    counts = pd.Series(count, index=cols, name=f"theme_memberships_min{min_members}")
    cov = {"min_members":min_members,"agg":agg,"themes":len(themes),"memberships":memberships,
           "stocks_with_theme":int((count>0).sum()),
           "membership_count":{"mean":float(count[count>0].mean()) if (count>0).any() else None,
                               "median":float(np.median(count[count>0])) if (count>0).any() else None,
                               "max":int(count.max()) if len(count) else 0}}
    return frame, counts, cov


def build_share_volume_features(matrices, features):
    close = matrices["close"].replace(0.0, np.nan)
    share20 = (matrices["dvol"] / close).astype(np.float32)
    ratio = (share20 / share20.shift(20)).astype(np.float32)
    acc = share20 / share20.shift(20) - 1.0
    acc_pct = (acc.where(matrices["new_eligible"]).rank(axis=1, pct=True) * 100.0).astype(np.float32)
    return acc_pct, ratio


def calendar_returns(eq: pd.Series, start="2021-01-04"):
    x = eq.loc[eq.index >= pd.Timestamp(start)].pct_change().fillna(0.0)
    return {str(int(y)):float((1.0+g).prod()-1.0) for y,g in x.groupby(x.index.year)}


def priority_trade_frame(sim):
    ent, tr = sim["entries"].copy(), sim["trades"].copy()
    if ent.empty or tr.empty or "relead_priority" not in ent: return pd.DataFrame()
    p = ent.loc[ent["relead_priority"].fillna(False).astype(bool), ["symbol","entry_date","signal_date"]].copy()
    if p.empty: return pd.DataFrame()
    p["entry_date"] = pd.to_datetime(p["entry_date"]); tr["entry_date"] = pd.to_datetime(tr["entry_date"])
    return p.merge(tr, on=["symbol","entry_date"], how="left", suffixes=("_entry","_trade"))


def trimmed_trade_stats(df):
    if df.empty or "return" not in df: return {"n":0}
    x = pd.to_numeric(df["return"], errors="coerce").dropna().sort_values(ascending=False).reset_index(drop=True)
    out = {"n":len(x),"mean":float(x.mean()) if len(x) else None,"median":float(x.median()) if len(x) else None,
           "win_rate":float((x>0).mean()) if len(x) else None}
    for k in (1,3,5):
        y = x.iloc[min(k,len(x)):]
        out[f"drop_top{k}"] = {"n":len(y),"mean":float(y.mean()) if len(y) else None,
                               "median":float(y.median()) if len(y) else None,"win_rate":float((y>0).mean()) if len(y) else None}
    if len(x) >= 10:
        lo,hi = x.quantile([0.10,0.90]); out["winsor10_mean"] = float(x.clip(lo,hi).mean())
    return out


def priority_pattern_stats(sim, matrices, features):
    ent, close = sim["entries"], matrices["close"]
    if ent.empty or "relead_priority" not in ent: return {}
    idx = close.index; ipos = {pd.Timestamp(d):i for i,d in enumerate(idx)}; rows=[]
    for _,r in ent.loc[ent["relead_priority"].fillna(False).astype(bool)].iterrows():
        d=pd.Timestamp(r["signal_date"]); sym=str(r["symbol"]); i=ipos.get(d); p0=_v(close,d,sym)
        if i is None or not np.isfinite(p0) or p0<=0: continue
        rs,hi,th,dv,_=rel.component_flags(d,sym,matrices,features,"BASE")
        rec={"pattern":f"R{int(rs)}H{int(hi)}T{int(th)}V{int(dv)}"}
        for h in (20,63):
            j=min(i+h,len(idx)-1); p1=_v(close,pd.Timestamp(idx[j]),sym); rec[f"ret{h}"]=p1/p0-1 if np.isfinite(p1) and p1>0 else np.nan
        rows.append(rec)
    df=pd.DataFrame(rows); out={}
    if df.empty:return out
    for pat,g in df.groupby("pattern"):
        out[str(pat)]={"n":len(g),"ret20_mean":float(g.ret20.mean()),"ret20_median":float(g.ret20.median()),"ret20_positive":float((g.ret20>0).mean()),
                       "ret63_mean":float(g.ret63.mean()),"ret63_median":float(g.ret63.median()),"ret63_positive":float((g.ret63>0).mean())}
    return out


def membership_bias_stats(sim, counts, matrices):
    ent=sim["entries"]
    if ent.empty or "relead_priority" not in ent:return {}
    e=ent.loc[ent["relead_priority"].fillna(False).astype(bool)].copy()
    if e.empty:return {}
    e["memberships"]=e["symbol"].map(counts).fillna(0).astype(int)
    e["bucket"]=pd.cut(e["memberships"],[-1,1,2,10**6],labels=["0-1","2","3+"])
    close=matrices["close"]; idx=close.index; ipos={pd.Timestamp(d):i for i,d in enumerate(idx)}; vals=[]
    for _,r in e.iterrows():
        d=pd.Timestamp(r["signal_date"]);sym=str(r["symbol"]);i=ipos.get(d);p0=_v(close,d,sym)
        if i is None or not np.isfinite(p0) or p0<=0: vals.append(np.nan);continue
        j=min(i+20,len(idx)-1);p1=_v(close,pd.Timestamp(idx[j]),sym);vals.append(p1/p0-1 if np.isfinite(p1) and p1>0 else np.nan)
    e["ret20"]=vals;out={}
    for b,g in e.groupby("bucket",observed=True):
        out[str(b)]={"n":len(g),"membership_mean":float(g.memberships.mean()),"ret20_mean":float(g.ret20.mean()),"ret20_median":float(g.ret20.median()),"ret20_positive":float((g.ret20>0).mean())}
    return out


def fixed_block_indices(n,block,rng):
    starts=rng.integers(0,n,size=int(np.ceil(n/block)));return np.concatenate([(s+np.arange(block))%n for s in starts])[:n]


def reality_check(sims,current_name,names,start="2021-01-04",block=20,reps=5000,seed=94117):
    cur=sims[current_name]["equity"].loc[lambda x:x.index>=pd.Timestamp(start)].pct_change().fillna(0.0)
    diffs=[];valid=[]
    for name in names:
        if name==current_name or name not in sims:continue
        r=sims[name]["equity"].reindex(cur.index).pct_change().fillna(0.0);diffs.append((r-cur).to_numpy(float));valid.append(name)
    if not diffs:return {}
    mat=np.column_stack(diffs);obs=np.nanmean(mat,axis=0);centered=mat-obs;rng=np.random.default_rng(seed);maxboot=np.empty(reps);indiv=np.empty((reps,len(valid)))
    for b in range(reps):
        ix=fixed_block_indices(len(mat),block,rng);bm=np.nanmean(centered[ix,:],axis=0);indiv[b,:]=bm;maxboot[b]=np.nanmax(bm)
    bi=int(np.nanargmax(obs));pv={}
    for j,name in enumerate(valid):
        pv[name]={"mean_daily_excess":float(obs[j]),"annualized_arith_excess":float(obs[j]*252),
                  "unadjusted_p_one_sided":float((indiv[:,j]>=obs[j]).mean()),"max_stat_adjusted_p":float((maxboot>=obs[j]).mean())}
    return {"method":"Centered fixed-20-session block bootstrap max-stat (White Reality Check style approximation)","start":start,"block":block,"reps":reps,
            "candidate_count":len(valid),"best":valid[bi],"best_mean_daily_excess":float(obs[bi]),"best_max_stat_adjusted_p":float((maxboot>=obs[bi]).mean()),"variants":pv}


def build_core_roll(matrices,leader_start,analysis_end):
    rolling=lc.build_rolling_superleaders(matrices,pd.Timestamp(leader_start),pd.Timestamp(analysis_end));dvol=matrices["dvol"];dp=dvol.rank(axis=1,pct=True)*100;rows=[]
    for _,rr in rolling.iterrows():
        sym=str(rr["symbol"]);d=pd.Timestamp(rr["start_date"])
        if sym not in dvol.columns or d not in dvol.index:continue
        if (pd.notna(dvol.at[d,sym]) and float(dvol.at[d,sym])>=cem.CORE_DVOL_ABS) or (pd.notna(dp.at[d,sym]) and float(dp.at[d,sym])>=cem.CORE_DVOL_PCT):rows.append(dict(rr))
    return pd.DataFrame(rows)


def diagnose_episode(symbol,start,peak,meta,matrices,peer_ctx,features,sim):
    dates=[pd.Timestamp(d) for d in meta["analysis_idx"] if start<=pd.Timestamp(d)<=peak];rows=[]
    for d in dates:
        color=str(meta["nq"].at[d,"nq_color"]) if d in meta["nq"].index and pd.notna(meta["nq"].at[d,"nq_color"]) else ""
        b=float(meta["breadth"].loc[d]) if d in meta["breadth"].index and pd.notna(meta["breadth"].loc[d]) else np.nan;bucket=base.breadth_bucket(b);trad=color in ("Blue","Green") and bucket>0
        cmap=cem.base_candidate_map(d,matrices,peer_ctx,bucket) if trad else {};cand=symbol in cmap
        core=bool(features["core_mask"].at[d,symbol]) if symbol in features["core_mask"].columns and d in features["core_mask"].index else False
        rs,hi,th,dv,_=rel.component_flags(d,symbol,matrices,features,"BASE");sig=bool(cand and core and int(rs)+int(hi)+int(th)+int(dv)>=3);prio=False
        if sig:
            ss=[]
            for s in cmap:
                try:
                    if not bool(features["core_mask"].at[d,s]):continue
                except Exception:continue
                a,bh,c,vd,_=rel.component_flags(d,s,matrices,features,"BASE")
                if int(a)+int(bh)+int(c)+int(vd)>=3:ss.append(s)
            if ss:prio=max(ss,key=lambda s:float(cmap[s].get("rank_score") or cmap[s].get("stock_rs189") or 0.0))==symbol
        rows.append({"date":d,"tradable_mode":trad,"candidate":cand,"core":core,"rs":rs,"high":hi,"theme":th,"volume":dv,"signal":sig,"priority":prio})
    df=pd.DataFrame(rows);ent=sim["entries"];actual=pd.DataFrame()
    if not ent.empty:actual=ent.loc[(ent.symbol.astype(str)==symbol)&(pd.to_datetime(ent.signal_date)>=start)&(pd.to_datetime(ent.signal_date)<=peak)]
    out={"symbol":symbol,"start":str(start.date()),"peak":str(peak.date()),"days":len(df),"actual_entry_in_window":not actual.empty,
         "actual_entry_date":str(pd.Timestamp(actual.iloc[0].entry_date).date()) if not actual.empty else None}
    if df.empty:out["diagnosis"]="NO_DATA";return out
    for col in ("tradable_mode","candidate","core","rs","high","theme","volume","signal","priority"):
        out[f"{col}_days"]=int(df[col].astype(bool).sum());hit=df.loc[df[col].astype(bool),"date"];out[f"first_{col}"]=str(hit.iloc[0].date()) if len(hit) else None
    if not actual.empty:out["diagnosis"]="CAPTURED"
    elif out["tradable_mode_days"]==0:out["diagnosis"]="MARKET_MODE_GATE"
    elif out["candidate_days"]==0 or out["core_days"]==0:out["diagnosis"]="NOT_CORE_OR_NOT_TOP_CANDIDATE"
    elif out["signal_days"]==0:
        out["diagnosis"]="FAILED_3_OF_4";counts={k:out[f"{k}_days"] for k in ("rs","high","theme","volume")};out["weakest_component"]=min(counts,key=counts.get)
    elif out["priority_days"]==0:out["diagnosis"]="SIGNAL_LOST_V38_TIEBREAK"
    else:out["diagnosis"]="NO_VACANCY_OR_ALREADY_HELD"
    return out


def choose_named_episodes(core_roll):
    fixed=[("NVDA",pd.Timestamp("2023-12-22"),pd.Timestamp("2024-06-18")),("PLTR",pd.Timestamp("2024-05-09"),pd.Timestamp("2024-11-07")),("SMCI",pd.Timestamp("2024-11-11"),pd.Timestamp("2025-02-19"))]
    for sym in ("CRWD","SNDK"):
        z=core_roll.loc[core_roll.symbol.astype(str)==sym].sort_values("peak_return",ascending=False)
        if not z.empty:fixed.append((sym,pd.Timestamp(z.iloc[0].start_date),pd.Timestamp(z.iloc[0].peak_date)))
    return fixed


def run_variant(meta,matrices,peer_ctx,features,name,rule,profile="BASE",cost_bps=0.0):
    return rel.run(meta,matrices,peer_ctx,features,rel.Variant(name,rule,profile),cost_bps)


def main():
    global BANNED_SYMBOLS
    ap=argparse.ArgumentParser();ap.add_argument("--root",default=".");ap.add_argument("--output",required=True);ap.add_argument("--analysis-start",default="2020-01-02");ap.add_argument("--analysis-end",default="2026-09-02");ap.add_argument("--leader-start",default="2021-01-04");ap.add_argument("--max-tickers",type=int,default=6000);ap.add_argument("--batch-size",type=int,default=75);args=ap.parse_args()
    root=Path(args.root);out=root/args.output;out.mkdir(parents=True,exist_ok=True)
    print("BUILD shared PIT inputs",flush=True);meta,matrices=ex.build_inputs_ext(root,args.analysis_start,args.analysis_end,args.max_tickers,args.batch_size);peer_ctx=loo.build_leave_one_out_scores(root,matrices);features=cem.build_features(matrices);print(f"UNIVERSE downloaded={meta['downloaded']}",flush=True)
    print("VALIDATE exact 9+3 reference",flush=True);ref=hyb.run_variant(meta,matrices,peer_ctx,features,"REF_CURRENT_BEST",9,3,"MILD",1,0.0)
    print("BUILD base Re-Leadership features",flush=True);rel.EXT,base_cov=rel.build_extended_features(root,matrices,features);rel.signal_ok=signal_ok;default_theme=rel.EXT["theme_rank"].copy();default_ratio=rel.EXT["dvol_ratio20"].copy()
    print("BUILD theme falsification variants",flush=True);theme5,counts5,cov5=build_theme_rank(root,matrices,5,"best");theme10,counts10,cov10=build_theme_rank(root,matrices,10,"best");thememed,counts3,covmed=build_theme_rank(root,matrices,3,"median")
    print("BUILD share-volume falsification features",flush=True);share_acc,share_ratio=build_share_volume_features(matrices,features)
    specs=[("CURRENT_BEST","NONE","BASE"),("RS_ONLY_BASE","RS","BASE"),("HIGH_ONLY_BASE","HIGH","BASE"),("THEME_ONLY_BASE","THEME","BASE"),("DVOL_ONLY_BASE","DVOL","BASE"),("RS_HIGH_BASE","RS_HIGH","BASE"),("RS_HIGH_THEME_BASE","RS_HIGH_THEME","BASE"),("RS_HIGH_DVOL_BASE","RS_HIGH_DVOL","BASE"),("ALL4_LOOSE","ALL4","LOOSE"),("ALL4_BASE","ALL4","BASE"),("ALL4_STRICT","ALL4","STRICT"),("THREE4_LOOSE","THREE4","LOOSE"),("THREE4_BASE","THREE4","BASE"),("THREE4_STRICT","THREE4","STRICT"),("RS_HIGH_PLUS_ONE_BASE","RS_HIGH_PLUS_ONE","BASE"),("FRESH10_RS_HIGH_PLUS_ONE","FRESH10_RS_HIGH_PLUS_ONE","BASE"),("BREAK_RS_PLUS_ONE","BREAK_RS_PLUS_ONE","BASE"),("RS_THEME_DVOL_BASE","RS_THEME_DVOL","BASE"),("HIGH_THEME_DVOL_BASE","HIGH_THEME_DVOL","BASE")]
    sims={};set_context(default_theme,default_ratio)
    for name,rule,profile in specs:print(f"SIM {name}",flush=True);BANNED_SYMBOLS=set();sims[name]=run_variant(meta,matrices,peer_ctx,features,name,rule,profile)
    a,b=sims["CURRENT_BEST"]["equity"].align(ref["equity"],join="inner");maxdiff=float(np.nanmax(np.abs(a.to_numpy(float)-b.to_numpy(float))));
    if maxdiff>1e-10:raise RuntimeError(f"current-best reproduction mismatch {maxdiff}")
    for name,tf in {"THREE4_THEME_BEST_MIN5":theme5,"THREE4_THEME_BEST_MIN10":theme10,"THREE4_THEME_MEDIAN_MIN3":thememed}.items():print(f"SIM {name}",flush=True);set_context(tf,default_ratio);BANNED_SYMBOLS=set();sims[name]=run_variant(meta,matrices,peer_ctx,features,name,"THREE4")
    print("SIM THREE4_SHARE_VOLUME",flush=True);set_context(default_theme,share_ratio);fshare=dict(features);fshare["dvol_acc_pct"]=share_acc;BANNED_SYMBOLS=set();sims["THREE4_SHARE_VOLUME"]=run_variant(meta,matrices,peer_ctx,fshare,"THREE4_SHARE_VOLUME","THREE4");set_context(default_theme,default_ratio)
    core_roll=build_core_roll(matrices,args.leader_start,args.analysis_end)
    result={"status":"CORE_RELEADERSHIP_FALSIFICATION_AUDIT","analysis_window":{"start":args.analysis_start,"end":args.analysis_end,"leader_start":args.leader_start,"downloaded":int(meta["downloaded"])},"current_best_validation":{"status":"PASS","equity_max_abs_diff":maxdiff},
            "tests":{"three_of_four_decomposition":"Four triple branches plus exact component patterns","threshold_sensitivity":"THREE4 Loose/Base/Strict","theme_bias":"Min theme size 5/10 and median across memberships","volume_bias":"Share-volume replaces dollar-volume expansion","outlier_stress":"Drop top priority winners and ban top 1/3/5 priority-profit symbols","multiple_testing":"Centered 20-session block bootstrap max-stat","miss_diagnostics":"NVDA/PLTR/SMCI plus largest CRWD/SNDK episodes"},
            "theme_coverage":{"base_best_min3":base_cov,"best_min5":cov5,"best_min10":cov10,"median_min3":covmed},"variants":{},"three4_patterns":{},"membership_bias":{},"outlier_stress":{},"reality_check":{},"named_episode_diagnostics":[]}
    for name,sim in sims.items():
        cap=cem.simple_capture(core_roll,sim["intervals"],matrices["close"]);result["variants"][name]={"metrics":base.slice_metrics(sim["equity"]),"exact_period_metrics":rel.exact_metrics(sim["equity"]),"calendar_returns":calendar_returns(sim["equity"]),"trade_stats":rt.trade_stats(sim["trades"]),"core_capture":cem.summarize_capture_ext(cap),"priority_forward":rel.priority_forward_stats(sim["entries"],matrices["close"])}
        sim["equity"].rename("equity").to_csv(out/f"equity_{name}.csv");sim["entries"].to_csv(out/f"entries_{name}.csv",index=False);sim["trades"].to_csv(out/f"trades_{name}.csv",index=False)
    result["three4_patterns"]=priority_pattern_stats(sims["THREE4_BASE"],matrices,features);result["membership_bias"]=membership_bias_stats(sims["THREE4_BASE"],counts3,matrices)
    ptdf=priority_trade_frame(sims["THREE4_BASE"]);result["outlier_stress"]["priority_trade_returns"]=trimmed_trade_stats(ptdf);top=[]
    if not ptdf.empty and "return" in ptdf:top=[str(s) for s in ptdf.groupby("symbol")["return"].sum().sort_values(ascending=False).index[:5]]
    result["outlier_stress"]["top_priority_profit_symbols"]=top
    for k in (1,3,5):
        banned=set(top[:k]);
        if not banned:continue
        name=f"THREE4_BAN_TOP{k}_SYMBOLS";print(f"SIM {name} banned={sorted(banned)}",flush=True);BANNED_SYMBOLS=banned;set_context(default_theme,default_ratio);sim=run_variant(meta,matrices,peer_ctx,features,name,"THREE4");sims[name]=sim;result["outlier_stress"][name]={"banned":sorted(banned),"exact_period_metrics":rel.exact_metrics(sim["equity"]),"calendar_returns":calendar_returns(sim["equity"]),"trade_stats":rt.trade_stats(sim["trades"])};sim["equity"].rename("equity").to_csv(out/f"equity_{name}.csv")
    BANNED_SYMBOLS=set();rc_names=[n for n in sims if not n.startswith("THREE4_BAN_TOP")];result["reality_check"]=reality_check(sims,"CURRENT_BEST",rc_names)
    set_context(default_theme,default_ratio)
    for sym,st,pk in choose_named_episodes(core_roll):print(f"DIAG {sym} {st.date()}->{pk.date()}",flush=True);result["named_episode_diagnostics"].append(diagnose_episode(sym,st,pk,meta,matrices,peer_ctx,features,sims["THREE4_BASE"]))
    cy=result["variants"]["CURRENT_BEST"]["calendar_returns"];ty=result["variants"]["THREE4_BASE"]["calendar_returns"];result["three4_calendar_excess"]={y:float(ty[y]-cy[y]) for y in sorted(set(cy)&set(ty))}
    (out/"summary_core_releadership_falsification.json").write_text(json.dumps(safe(result),ensure_ascii=False,indent=2),encoding="utf-8")
    print("=== CORE_RELEADERSHIP_FALSIFICATION_JSON ===",flush=True);print(json.dumps(safe(result),ensure_ascii=False,indent=2),flush=True);print("=== END_CORE_RELEADERSHIP_FALSIFICATION_JSON ===",flush=True)


if __name__ == "__main__": main()
