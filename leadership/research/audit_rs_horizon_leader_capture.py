from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
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

HORIZONS = (21, 42, 63, 126, 189, 252)
SELECTIVE_TOTAL = 4

@dataclass(frozen=True)
class PVariant:
    name: str
    eligibility: str
    score: str
    theme_weight: float = 0.30

VARIANTS = (
    PVariant("CURRENT_RS189", "CURRENT_DUAL", "RS189", 0.30),
    PVariant("DUAL_RANK_RS63", "CURRENT_DUAL", "RS63", 0.30),
    PVariant("DUAL_RANK_RS126", "CURRENT_DUAL", "RS126", 0.30),
    PVariant("DUAL_EQ63_126", "CURRENT_DUAL", "EQ63_126", 0.30),
    PVariant("DUAL_EQ63_126_189", "CURRENT_DUAL", "EQ63_126_189", 0.30),
    PVariant("DUAL_EQ42_63_126_189", "CURRENT_DUAL", "EQ42_63_126_189", 0.30),
    PVariant("GATE126_RANK126", "RS126_85", "RS126", 0.30),
    PVariant("GATE63_126_EQ", "RS63_126_85", "EQ63_126", 0.30),
    PVariant("GATE126_189_EQ", "RS126_189_85", "EQ126_189", 0.30),
    PVariant("STRUCT_EQ63_126_189", "STRUCT_ONLY", "EQ63_126_189", 0.30),
    PVariant("STRUCT_ACCEL63_126", "STRUCT_ONLY", "ACCEL63_126", 0.30),
    PVariant("STRUCT_EQ63_126_189_NOTHEME", "STRUCT_ONLY", "EQ63_126_189", 0.0),
)

ACTIVE: PVariant | None = None
RS: dict[int, pd.DataFrame] = {}
SCORES: dict[str, pd.DataFrame] = {}
STRUCT: pd.DataFrame | None = None
CORE_LIQ: pd.DataFrame | None = None
FEATURES: dict[str, pd.DataFrame] = {}
PEER_CTX: dict[str, Any] = {}


def safe(v: Any) -> Any:
    return base.safe(v)


def _v(frame: pd.DataFrame, d: pd.Timestamp, sym: str, default: float = np.nan) -> float:
    try:
        x = float(frame.at[d, sym])
        return x if np.isfinite(x) else default
    except Exception:
        return default


def build_rs(matrices: dict[str, pd.DataFrame]) -> tuple[dict[int, pd.DataFrame], pd.DataFrame, pd.DataFrame]:
    close = matrices["close"]
    dvol = matrices["dvol"]
    base_pool = (close >= 5.0) & (dvol >= base.DVOL_FLOOR)
    # structural biotech exclusion already affected current new_eligible; infer excluded columns as names never in base pool is unsafe.
    # use current data universe and price/liquidity/trend only here; no future information.
    struct = base_pool & (matrices["sma50"] > matrices["sma200"]) & (close > matrices["sma200"])
    out: dict[int, pd.DataFrame] = {}
    for h in HORIZONS:
        ret = close / close.shift(h) - 1.0
        out[h] = (ret.where(base_pool).rank(axis=1, pct=True, method="average") * 100.0).astype(np.float32)
    dvol_pct = dvol.rank(axis=1, pct=True, method="average") * 100.0
    core_liq = (dvol >= cem.CORE_DVOL_ABS) | (dvol_pct >= cem.CORE_DVOL_PCT)
    return out, struct.fillna(False), core_liq.fillna(False)


def build_scores(rs: dict[int, pd.DataFrame], struct: pd.DataFrame, matrices: dict[str, pd.DataFrame], peer_ctx: dict[str, Any]) -> dict[str, pd.DataFrame]:
    scores: dict[str, pd.DataFrame] = {f"RS{h}": rs[h].astype(np.float32) for h in HORIZONS}
    scores["EQ63_126"] = ((rs[63] + rs[126]) / 2.0).astype(np.float32)
    scores["EQ126_189"] = ((rs[126] + rs[189]) / 2.0).astype(np.float32)
    scores["EQ63_126_189"] = ((rs[63] + rs[126] + rs[189]) / 3.0).astype(np.float32)
    scores["EQ42_63_126_189"] = ((rs[42] + rs[63] + rs[126] + rs[189]) / 4.0).astype(np.float32)
    scores["EQ_ALL"] = (sum(rs[h] for h in HORIZONS) / float(len(HORIZONS))).astype(np.float32)
    acc63 = rs[63] - rs[63].shift(20)
    acc63pct = acc63.where(struct).rank(axis=1, pct=True, method="average") * 100.0
    scores["ACCEL63_126"] = (0.40 * rs[63] + 0.35 * rs[126] + 0.25 * acc63pct).astype(np.float32)
    high = matrices["close"] / matrices["close"].shift(1).rolling(63, min_periods=50).max()
    scores["HIGH63"] = (high.where(struct).rank(axis=1, pct=True, method="average") * 100.0).astype(np.float32)
    # peer theme score is already point-in-time leave-one-out and strategy-safe.
    peer = pd.DataFrame(peer_ctx["best_score"], index=matrices["close"].index, columns=matrices["close"].columns, dtype=np.float32)
    scores["THEME"] = peer
    scores["RS126_THEME"] = (0.70 * rs[126] + 0.30 * peer.fillna(50.0)).astype(np.float32)
    scores["EQ63_126_189_THEME"] = (0.70 * scores["EQ63_126_189"] + 0.30 * peer.fillna(50.0)).astype(np.float32)
    return scores


def eligible_mask(v: PVariant, d: pd.Timestamp) -> pd.Series:
    assert STRUCT is not None
    s = STRUCT.loc[d].copy()
    if v.eligibility == "CURRENT_DUAL":
        return s & (RS[63].loc[d] >= 85.0) & (RS[189].loc[d] >= 85.0)
    if v.eligibility == "RS126_85":
        return s & (RS[126].loc[d] >= 85.0)
    if v.eligibility == "RS63_126_85":
        return s & (RS[63].loc[d] >= 85.0) & (RS[126].loc[d] >= 85.0)
    if v.eligibility == "RS126_189_85":
        return s & (RS[126].loc[d] >= 85.0) & (RS[189].loc[d] >= 85.0)
    if v.eligibility == "STRUCT_ONLY":
        return s
    raise ValueError(v.eligibility)


def peer_score(d: pd.Timestamp, sym: str) -> float:
    di = PEER_CTX["date_pos"].get(pd.Timestamp(d))
    si = PEER_CTX["stock_pos"].get(str(sym))
    if di is None or si is None:
        return 50.0
    x = float(PEER_CTX["best_score"][di, si])
    return x if np.isfinite(x) else 50.0


def mild_emerging_score(d: pd.Timestamp, sym: str, stock_rs189: float, theme: float, matrices) -> float:
    base_score = 0.70 * stock_rs189 + 0.30 * theme
    rs63 = _v(matrices["rs63"], d, sym, 0.0)
    acc = _v(FEATURES["rs_acc_pct"], d, sym, 0.0)
    ret20 = _v(FEATURES["ret20_pct"], d, sym, 0.0)
    dvacc = _v(FEATURES["dvol_acc_pct"], d, sym, 0.0)
    return 0.70 * base_score + 0.15 * rs63 + 0.07 * acc + 0.04 * ret20 + 0.04 * dvacc


def custom_classifier(d, matrices, peer_ctx, features, bucket, enhanced):
    assert ACTIVE is not None and CORE_LIQ is not None
    elig = eligible_mask(ACTIVE, d)
    raw = SCORES[ACTIVE.score].loc[d].where(elig & CORE_LIQ.loc[d]).dropna()
    core = []
    for sym, stock0 in raw.nlargest(300).items():
        stock = float(stock0)
        th = peer_score(d, str(sym))
        rank_score = stock if (bucket == 1 or ACTIVE.theme_weight <= 0) else (1.0 - ACTIVE.theme_weight) * stock + ACTIVE.theme_weight * th
        c = {
            "stock_rs189": _v(RS[189], d, str(sym)),
            "peer_theme_score": th,
            "rank_score": float(rank_score),
            "layer": "CORE",
            "layer_score": float(rank_score),
            "research_stock_score": stock,
            "research_eligibility": ACTIVE.eligibility,
            "research_score": ACTIVE.score,
        }
        core.append((str(sym), c))
    core.sort(key=lambda x: (x[1]["layer_score"], x[1]["stock_rs189"]), reverse=True)

    # Emerging sleeve stays exactly on the current V38 definition and MILD ranking.
    em_mask = FEATURES["emerging_mask"].loc[d]
    em_names = list(em_mask.index[em_mask.fillna(False)])
    emerging = []
    for sym in em_names:
        rs189 = _v(matrices["rs189"], d, str(sym))
        if not np.isfinite(rs189):
            continue
        th = peer_score(d, str(sym))
        score = mild_emerging_score(d, str(sym), rs189, th, matrices)
        emerging.append((str(sym), {
            "stock_rs189": rs189,
            "peer_theme_score": th,
            "rank_score": 0.70 * rs189 + 0.30 * th,
            "layer": "EMERGING",
            "layer_score": float(score),
        }))
    emerging.sort(key=lambda x: x[1]["layer_score"], reverse=True)
    return core, emerging


def custom_current_layer(d, sym, features):
    assert ACTIVE is not None and CORE_LIQ is not None
    try:
        if bool(CORE_LIQ.at[d, sym]) and bool(eligible_mask(ACTIVE, d).at[sym]):
            return "CORE"
    except Exception:
        pass
    return "EMERGING"


def run_variant(meta, matrices, peer_ctx, features, v: PVariant):
    global ACTIVE
    ACTIVE = v
    cem.classified_candidates = custom_classifier
    cem.current_layer = custom_current_layer
    return cem.simulate_layered(meta, matrices, peer_ctx, features, cem.Variant(v.name, 9, 3, True, 1), cost_bps=0.0)


def freeze_labels(out: Path, annual: pd.DataFrame, rolling: pd.DataFrame) -> str:
    a = annual.copy(); a["evaluation_set"] = "ANNUAL"
    r = rolling.copy(); r["evaluation_set"] = "ROLLING126"
    cols = sorted(set(a.columns) | set(r.columns))
    z = pd.concat([a.reindex(columns=cols), r.reindex(columns=cols)], ignore_index=True)
    z = z.sort_values([c for c in ["evaluation_set", "period", "rank", "symbol", "start_date"] if c in z.columns], na_position="last")
    p = out / "leader_labels_frozen.csv"; z.to_csv(p, index=False)
    digest = hashlib.sha256(p.read_bytes()).hexdigest(); (out / "leader_labels_sha256.txt").write_text(digest + "\n")
    return digest


def detection_table(leaders: pd.DataFrame, score: pd.DataFrame, struct: pd.DataFrame, close: pd.DataFrame, topn: int) -> pd.DataFrame:
    ranks = score.where(struct).rank(axis=1, ascending=False, method="min")
    rows = []
    for _, r0 in leaders.iterrows():
        r = dict(r0); sym = str(r["symbol"]); start = pd.Timestamp(r["start_date"]); peak = pd.Timestamp(r["peak_date"])
        r.update({"identified": False, "identify_date": pd.NaT, "identify_progress": np.nan})
        if sym not in ranks.columns:
            rows.append(r); continue
        dates = ranks.index[(ranks.index >= start) & (ranks.index <= peak)]
        hit = ranks.loc[dates, sym].le(topn).fillna(False)
        if hit.any():
            d = pd.Timestamp(hit.index[np.argmax(hit.to_numpy(bool))]); r["identified"] = True; r["identify_date"] = d
            sp = _v(close, start, sym); pp = _v(close, peak, sym); ep = _v(close, d, sym)
            total = pp / sp - 1.0 if np.isfinite(sp) and sp > 0 and np.isfinite(pp) else np.nan
            if np.isfinite(total) and total > 0 and np.isfinite(ep): r["identify_progress"] = (ep / sp - 1.0) / total
        rows.append(r)
    return pd.DataFrame(rows)


def det_summary(df: pd.DataFrame) -> dict[str, Any]:
    if df.empty: return {"n":0}
    hit = df["identified"].astype(bool); p = pd.to_numeric(df.loc[hit, "identify_progress"], errors="coerce")
    return {"n": int(len(df)), "hit_n": int(hit.sum()), "hit_rate": float(hit.mean()), "early20_all_rate": float((hit & (pd.to_numeric(df["identify_progress"], errors="coerce") <= 0.20)).mean()), "early20_of_hits": float((p <= 0.20).mean()) if p.notna().any() else None, "median_progress": float(p.median()) if p.notna().any() else None}


def capture_summary(df: pd.DataFrame) -> dict[str, Any]:
    if df.empty: return {"n":0}
    cap = df["captured"].astype(bool); p = pd.to_numeric(df.loc[cap, "capture_progress"], errors="coerce")
    return {"n": int(len(df)), "captured_n": int(cap.sum()), "hit_rate": float(cap.mean()), "early20_all_rate": float((cap & (pd.to_numeric(df["capture_progress"], errors="coerce") <= 0.20)).mean()), "early20_of_hits": float((p <= 0.20).mean()) if p.notna().any() else None, "median_progress": float(p.median()) if p.notna().any() else None}


def by_year(df: pd.DataFrame, top10=False) -> dict[str, Any]:
    z = df.copy()
    if top10 and "rank" in z: z = z.loc[pd.to_numeric(z["rank"], errors="coerce") <= 10]
    return {str(k): capture_summary(g) for k,g in z.groupby("period", sort=True)}


def period_metrics(eq: pd.Series) -> dict[str, Any]:
    def m(a,b=None):
        x=eq.loc[eq.index>=pd.Timestamp(a)]; x=x if b is None else x.loc[x.index<=pd.Timestamp(b)]; return base.metrics(x)
    return {"2021_2023":m("2021-01-04","2023-12-29"),"2024_plus":m("2024-01-02"),"2021_plus":m("2021-01-04")}


def main():
    global RS, SCORES, STRUCT, CORE_LIQ, FEATURES, PEER_CTX
    ap=argparse.ArgumentParser(); ap.add_argument("--root",default="."); ap.add_argument("--output",required=True)
    ap.add_argument("--analysis-start",default="2020-01-02"); ap.add_argument("--analysis-end",default="2026-09-02"); ap.add_argument("--leader-start",default="2021-01-04")
    ap.add_argument("--max-tickers",type=int,default=6000); ap.add_argument("--batch-size",type=int,default=75)
    args=ap.parse_args(); root=Path(args.root); out=root/args.output; out.mkdir(parents=True,exist_ok=True)

    print("BUILD shared PIT inputs",flush=True)
    meta,matrices=ex.build_inputs_ext(root,args.analysis_start,args.analysis_end,args.max_tickers,args.batch_size)
    PEER_CTX=loo.build_leave_one_out_scores(root,matrices); FEATURES=cem.build_features(matrices)
    RS,STRUCT,CORE_LIQ=build_rs(matrices); SCORES=build_scores(RS,STRUCT,matrices,PEER_CTX)
    print(f"UNIVERSE downloaded={meta['downloaded']}",flush=True)

    annual=lc.build_annual_leaders(matrices,pd.Timestamp(args.leader_start),pd.Timestamp(args.analysis_end))
    rolling=lc.build_rolling_superleaders(matrices,pd.Timestamp(args.leader_start),pd.Timestamp(args.analysis_end))
    digest=freeze_labels(out,annual,rolling); print(f"LABEL_SHA256 {digest}",flush=True)

    # Stage 1: strategy-independent early leader identification from the structural pool.
    screen_names=["RS21","RS42","RS63","RS126","RS189","RS252","EQ63_126","EQ63_126_189","EQ42_63_126_189","EQ_ALL","ACCEL63_126","HIGH63","THEME","RS126_THEME","EQ63_126_189_THEME"]
    screen={}
    annual10=annual.loc[pd.to_numeric(annual["rank"],errors="coerce")<=10].copy()
    for name in screen_names:
        print(f"SCREEN {name}",flush=True)
        a12=detection_table(annual10,SCORES[name],STRUCT,matrices["close"],12)
        a20=detection_table(annual10,SCORES[name],STRUCT,matrices["close"],20)
        r20=detection_table(rolling,SCORES[name],STRUCT,matrices["close"],20)
        a20.to_csv(out/f"screen_annual_top10_top20_{name}.csv",index=False)
        screen[name]={"annual_top10_top12":det_summary(a12),"annual_top10_top20":det_summary(a20),"rolling126_top20":det_summary(r20)}

    print("SIM official current 9+3 reference",flush=True)
    current=hyb.run_variant(meta,matrices,PEER_CTX,FEATURES,"CURRENT_BEST",9,3,"MILD",1,0.0)
    sims={"CURRENT_BEST":current}
    for v in VARIANTS[1:]:
        print(f"SIM {v.name}",flush=True); sims[v.name]=run_variant(meta,matrices,PEER_CTX,FEATURES,v)

    result={"status":"RS_HORIZON_LEADER_CAPTURE_AUDIT","analysis_window":{"start":args.analysis_start,"end":args.analysis_end,"downloaded":int(meta['downloaded'])},
            "design":{"question":"Is RS189 actually the best stock-strength horizon for early leader capture, separating eligibility from ranking?","leader_kpi":"Primary = fixed annual Top10 and rolling126 superleaders; target concept = >=80% capture and entry by <=20% of the leader move.","stage1":"No RS eligibility gate: common price/liquidity/trend structural pool; compare early top12/top20 identification across horizons and non-RS neighbors.","stage2":"9 Core + 3 Emerging, SELECTIVE 3+1, current Emerging MILD sleeve and exits unchanged; only Core eligibility/ranking varies.","important":"Leader labels are hindsight evaluation-only, frozen before simulations, never used by a signal."},
            "label_sha256":digest,"screen":screen,"variants":{}}

    for name,sim in sims.items():
        ac=cem.simple_capture(annual,sim["intervals"],matrices["close"]); rc=cem.simple_capture(rolling,sim["intervals"],matrices["close"])
        ac.to_csv(out/f"annual_capture_{name}.csv",index=False); rc.to_csv(out/f"rolling126_capture_{name}.csv",index=False)
        a10=ac.loc[pd.to_numeric(ac["rank"],errors="coerce")<=10]
        result["variants"][name]={"metrics":period_metrics(sim["equity"]),"mdd_full":base.metrics(sim["equity"])["max_drawdown"],"trade_stats":rt.trade_stats(sim["trades"]),"annual_top10":capture_summary(a10),"annual_top10_by_year":by_year(ac,True),"rolling126":capture_summary(rc)}
        sim["equity"].rename("equity").to_csv(out/f"equity_{name}.csv"); sim["entries"].to_csv(out/f"entries_{name}.csv",index=False); sim["trades"].to_csv(out/f"trades_{name}.csv",index=False)

    (out/"summary_rs_horizon_leader_capture.json").write_text(json.dumps(safe(result),ensure_ascii=False,indent=2),encoding="utf-8")
    print("=== RS_HORIZON_LEADER_CAPTURE_JSON ===",flush=True); print(json.dumps(safe(result),ensure_ascii=False,indent=2),flush=True); print("=== END_RS_HORIZON_LEADER_CAPTURE_JSON ===",flush=True)

if __name__=="__main__": main()
