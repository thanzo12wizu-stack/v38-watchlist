from __future__ import annotations

import argparse
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
import audit_core_releadership_priority as rel
import audit_core_releadership_falsification as fal


@dataclass(frozen=True)
class Variant:
    name: str
    high_w: float = 0.35
    theme_w: float = 0.35
    rs_w: float = 0.15
    turn_w: float = 0.15
    gate_high: float = 0.95
    gate_theme: float = 70.0
    gate_delta: float = 0.0
    theme_mode: str = "BEST3"
    tie_break: str = "SCORE"
    fresh20: bool = False


ACTIVE = Variant("V2_BAL_BASE_SCORE")
V2EXT: dict[str, Any] = {}
BANNED_SYMBOLS: set[str] = set()


def _v(frame: pd.DataFrame, d: pd.Timestamp, sym: str, default: float = np.nan) -> float:
    try:
        x = float(frame.at[d, sym])
        return x if np.isfinite(x) else default
    except Exception:
        return default


def _theme_frames(variant: Variant):
    return V2EXT["theme"][variant.theme_mode]


def component_scores(d: pd.Timestamp, sym: str, matrices, features, variant: Variant) -> dict[str, float | bool]:
    high_ratio = _v(V2EXT["high_ratio"], d, sym)
    theme_rank_f, theme_delta_f = _theme_frames(variant)
    theme_rank = _v(theme_rank_f, d, sym)
    theme_delta = _v(theme_delta_f, d, sym)
    rs63 = _v(matrices["rs63"], d, sym)
    rs_acc = _v(features["rs_acc_pct"], d, sym)
    rs_turn = bool(V2EXT["rs_turn"].at[d, sym]) if d in V2EXT["rs_turn"].index and sym in V2EXT["rs_turn"].columns else False
    sh_acc = _v(V2EXT["share_acc_pct"], d, sym)
    sh_ratio = _v(V2EXT["share_ratio20"], d, sym)

    high_score = float(np.clip((high_ratio - 0.94) / 0.08 * 100.0, 0.0, 100.0)) if np.isfinite(high_ratio) else 0.0
    theme_recovery = float(np.clip(50.0 + 2.0 * theme_delta, 0.0, 100.0)) if np.isfinite(theme_delta) else 0.0
    theme_score = 0.75 * (theme_rank if np.isfinite(theme_rank) else 0.0) + 0.25 * theme_recovery
    rs_score = (
        0.45 * (rs63 if np.isfinite(rs63) else 0.0)
        + 0.45 * (rs_acc if np.isfinite(rs_acc) else 0.0)
        + 0.10 * (100.0 if rs_turn else 0.0)
    )
    ratio_score = float(np.clip(50.0 + 250.0 * (sh_ratio - 1.0), 0.0, 100.0)) if np.isfinite(sh_ratio) else 0.0
    turn_score = 0.70 * (sh_acc if np.isfinite(sh_acc) else 0.0) + 0.30 * ratio_score

    gate = (
        np.isfinite(high_ratio) and high_ratio >= variant.gate_high
        and np.isfinite(theme_rank) and theme_rank >= variant.gate_theme
        and np.isfinite(theme_delta) and theme_delta >= variant.gate_delta
    )
    if variant.fresh20:
        fresh = bool(V2EXT["fresh20_high95"].at[d, sym]) if d in V2EXT["fresh20_high95"].index and sym in V2EXT["fresh20_high95"].columns else False
        gate = gate and fresh

    total = (
        variant.high_w * high_score
        + variant.theme_w * theme_score
        + variant.rs_w * rs_score
        + variant.turn_w * turn_score
    )
    return {
        "gate": bool(gate),
        "score": float(total),
        "high_score": float(high_score),
        "theme_score": float(theme_score),
        "rs_score": float(rs_score),
        "turn_score": float(turn_score),
        "high_ratio": float(high_ratio) if np.isfinite(high_ratio) else np.nan,
        "theme_rank": float(theme_rank) if np.isfinite(theme_rank) else np.nan,
        "theme_delta": float(theme_delta) if np.isfinite(theme_delta) else np.nan,
        "rs63": float(rs63) if np.isfinite(rs63) else np.nan,
        "rs_acc": float(rs_acc) if np.isfinite(rs_acc) else np.nan,
        "share_acc_pct": float(sh_acc) if np.isfinite(sh_acc) else np.nan,
        "share_ratio20": float(sh_ratio) if np.isfinite(sh_ratio) else np.nan,
    }


def classifier_v2(d, matrices, peer_ctx, features, bucket, enhanced):
    cmap = cem.base_candidate_map(d, matrices, peer_ctx, bucket)
    core, emerging = [], []
    signal: dict[str, dict[str, float | bool]] = {}
    for sym in cmap:
        try:
            is_core = bool(features["core_mask"].at[d, sym])
        except Exception:
            continue
        if not is_core or sym in BANNED_SYMBOLS:
            continue
        comp = component_scores(d, sym, matrices, features, ACTIVE)
        if bool(comp["gate"]):
            signal[sym] = comp

    priority = None
    if signal:
        if ACTIVE.tie_break == "V38":
            priority = max(signal, key=lambda s: float(cmap[s].get("rank_score") or cmap[s].get("stock_rs189") or 0.0))
        else:
            priority = max(signal, key=lambda s: (float(signal[s]["score"]), float(cmap[s].get("rank_score") or cmap[s].get("stock_rs189") or 0.0)))

    for sym, c0 in cmap.items():
        try:
            is_core = bool(features["core_mask"].at[d, sym])
            is_em = bool(features["emerging_mask"].at[d, sym])
        except Exception:
            continue
        if not (is_core or is_em):
            continue
        layer = "CORE" if is_core else "EMERGING"
        c = dict(c0)
        bs = float(c.get("rank_score") or c.get("stock_rs189") or 0.0)
        score = bs if layer == "CORE" else rel.mild_emerging_score(d, sym, c, matrices, features)
        comp = signal.get(sym)
        is_sig = comp is not None
        c["relead_signal"] = bool(is_sig)
        c["relead_priority"] = bool(sym == priority)
        c["relead_strength"] = float(comp["score"]) if comp else np.nan
        if comp:
            c["relead_high_score"] = comp["high_score"]
            c["relead_theme_score"] = comp["theme_score"]
            c["relead_rs_score"] = comp["rs_score"]
            c["relead_turn_score"] = comp["turn_score"]
            c["high63_ratio"] = comp["high_ratio"]
            c["theme_internal_rank"] = comp["theme_rank"]
            c["theme_internal_delta20"] = comp["theme_delta"]
            c["rs63"] = comp["rs63"]
            c["rs_acc_pct"] = comp["rs_acc"]
            c["sharevol_acc_pct"] = comp["share_acc_pct"]
            c["sharevol_ratio20"] = comp["share_ratio20"]
        c["layer"] = layer
        c["layer_score"] = score + (1000.0 if sym == priority else 0.0)
        (core if layer == "CORE" else emerging).append((sym, c))

    core.sort(key=lambda x: x[1]["layer_score"], reverse=True)
    emerging.sort(key=lambda x: x[1]["layer_score"], reverse=True)
    return core, emerging


def run_v2(meta, matrices, peer_ctx, features, variant: Variant, cost_bps: float = 0.0):
    global ACTIVE
    ACTIVE = variant
    cem.classified_candidates = classifier_v2
    return cem.simulate_layered(
        meta, matrices, peer_ctx, features,
        cem.Variant(variant.name, 9, 3, True, 1),
        cost_bps=cost_bps,
    )


def period_metrics(eq: pd.Series) -> dict[str, Any]:
    def m(start: str, end: str | None = None):
        x = eq.loc[eq.index >= pd.Timestamp(start)]
        if end is not None:
            x = x.loc[x.index <= pd.Timestamp(end)]
        return base.metrics(x)
    return {
        "2021_plus": m("2021-01-04"),
        "2022_plus": m("2022-01-03"),
        "2022_2023": m("2022-01-03", "2023-12-29"),
        "2024_plus": m("2024-01-02"),
    }


def build_core_roll(matrices, leader_start: str, analysis_end: str):
    return fal.build_core_roll(matrices, leader_start, analysis_end)


def variant_summary(sim, core_roll, matrices):
    cap = cem.simple_capture(core_roll, sim["intervals"], matrices["close"])
    return {
        "metrics": base.slice_metrics(sim["equity"]),
        "period_metrics": period_metrics(sim["equity"]),
        "calendar_returns": fal.calendar_returns(sim["equity"]),
        "trade_stats": rt.trade_stats(sim["trades"]),
        "core_capture": cem.summarize_capture_ext(cap),
        "priority_forward": rel.priority_forward_stats(sim["entries"], matrices["close"]),
    }


def diagnose_episode_v2(symbol: str, start: pd.Timestamp, peak: pd.Timestamp, meta, matrices, peer_ctx, features, variant: Variant, sim):
    dates = [pd.Timestamp(d) for d in meta["analysis_idx"] if start <= pd.Timestamp(d) <= peak]
    rows = []
    for d in dates:
        color = str(meta["nq"].at[d, "nq_color"]) if d in meta["nq"].index and pd.notna(meta["nq"].at[d, "nq_color"]) else ""
        breadth = float(meta["breadth"].loc[d]) if d in meta["breadth"].index and pd.notna(meta["breadth"].loc[d]) else np.nan
        bucket = base.breadth_bucket(breadth)
        tradable = color in ("Blue", "Green") and bucket > 0
        cmap = cem.base_candidate_map(d, matrices, peer_ctx, bucket) if tradable else {}
        candidate = symbol in cmap
        core = bool(features["core_mask"].at[d, symbol]) if symbol in features["core_mask"].columns and d in features["core_mask"].index else False
        comp = component_scores(d, symbol, matrices, features, variant) if candidate and core else {"gate": False, "score": np.nan}
        priority = False
        if bool(comp["gate"]):
            sig = []
            for s in cmap:
                try:
                    if not bool(features["core_mask"].at[d, s]):
                        continue
                except Exception:
                    continue
                cc = component_scores(d, s, matrices, features, variant)
                if bool(cc["gate"]):
                    sig.append((s, cc))
            if sig:
                if variant.tie_break == "V38":
                    chosen = max(sig, key=lambda z: float(cmap[z[0]].get("rank_score") or cmap[z[0]].get("stock_rs189") or 0.0))[0]
                else:
                    chosen = max(sig, key=lambda z: (float(z[1]["score"]), float(cmap[z[0]].get("rank_score") or cmap[z[0]].get("stock_rs189") or 0.0)))[0]
                priority = chosen == symbol
        rows.append({"date": d, "tradable": tradable, "candidate": candidate, "core": core, "signal": bool(comp["gate"]), "priority": priority})
    df = pd.DataFrame(rows)
    ent = sim["entries"]
    actual = pd.DataFrame()
    if not ent.empty:
        actual = ent.loc[(ent.symbol.astype(str) == symbol) & (pd.to_datetime(ent.signal_date) >= start) & (pd.to_datetime(ent.signal_date) <= peak)]
    out = {
        "symbol": symbol,
        "start": str(start.date()),
        "peak": str(peak.date()),
        "actual_entry_in_window": not actual.empty,
        "actual_entry_date": str(pd.Timestamp(actual.iloc[0].entry_date).date()) if not actual.empty else None,
    }
    for col in ("tradable", "candidate", "core", "signal", "priority"):
        out[f"{col}_days"] = int(df[col].astype(bool).sum()) if not df.empty else 0
        hit = df.loc[df[col].astype(bool), "date"] if not df.empty else pd.Series(dtype="datetime64[ns]")
        out[f"first_{col}"] = str(pd.Timestamp(hit.iloc[0]).date()) if len(hit) else None
    if not actual.empty:
        out["diagnosis"] = "CAPTURED"
    elif out["tradable_days"] == 0:
        out["diagnosis"] = "MARKET_MODE_GATE"
    elif out["candidate_days"] == 0 or out["core_days"] == 0:
        out["diagnosis"] = "NOT_CORE_OR_NOT_TOP_CANDIDATE"
    elif out["signal_days"] == 0:
        out["diagnosis"] = "FAILED_HIGH_THEME_GATE"
    elif out["priority_days"] == 0:
        out["diagnosis"] = "LOST_RELEADERSHIP_SCORE_TIEBREAK"
    else:
        out["diagnosis"] = "NO_VACANCY_OR_ALREADY_HELD"
    return out


def main():
    global V2EXT, BANNED_SYMBOLS
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--output", required=True)
    ap.add_argument("--analysis-start", default="2020-01-02")
    ap.add_argument("--analysis-end", default="2026-09-02")
    ap.add_argument("--leader-start", default="2021-01-04")
    ap.add_argument("--max-tickers", type=int, default=6000)
    ap.add_argument("--batch-size", type=int, default=75)
    args = ap.parse_args()

    root = Path(args.root)
    out = root / args.output
    out.mkdir(parents=True, exist_ok=True)

    print("BUILD shared PIT inputs", flush=True)
    meta, matrices = ex.build_inputs_ext(root, args.analysis_start, args.analysis_end, args.max_tickers, args.batch_size)
    peer_ctx = loo.build_leave_one_out_scores(root, matrices)
    features = cem.build_features(matrices)
    print(f"UNIVERSE downloaded={meta['downloaded']}", flush=True)

    print("SIM exact current 9+3 reference", flush=True)
    current = hyb.run_variant(meta, matrices, peer_ctx, features, "CURRENT_BEST", 9, 3, "MILD", 1, 0.0)

    print("BUILD Re-Leadership base features", flush=True)
    rel.EXT, base_theme_cov = rel.build_extended_features(root, matrices, features)
    print("SIM previous THREE4_BASE", flush=True)
    three4 = rel.run(meta, matrices, peer_ctx, features, rel.Variant("THREE4_BASE", "THREE4", "BASE"), 0.0)

    print("BUILD residual share-turnover and theme robustness features", flush=True)
    share_acc, share_ratio = fal.build_share_volume_features(matrices, features)
    theme_med3, _, theme_med3_cov = fal.build_theme_rank(root, matrices, 3, "median")
    theme_best5, _, theme_best5_cov = fal.build_theme_rank(root, matrices, 5, "best")
    high_ratio = rel.EXT["high_ratio"]
    above95 = (high_ratio >= 0.95).fillna(False)
    cross95 = above95 & ~above95.shift(1).fillna(False)
    fresh20 = cross95.rolling(20, min_periods=1).max().gt(0.0)

    V2EXT = {
        "high_ratio": high_ratio,
        "rs_turn": rel.EXT["rs_turn"],
        "share_acc_pct": share_acc,
        "share_ratio20": share_ratio,
        "fresh20_high95": fresh20,
        "theme": {
            "BEST3": (rel.EXT["theme_rank"], rel.EXT["theme_delta20"]),
            "MED3": (theme_med3, (theme_med3 - theme_med3.shift(20)).astype(np.float32)),
            "BEST5": (theme_best5, (theme_best5 - theme_best5.shift(20)).astype(np.float32)),
        },
    }

    specs = [
        Variant("V2_BAL_BASE_SCORE"),
        Variant("V2_BAL_BASE_V38", tie_break="V38"),
        Variant("V2_BAL_LOOSE_SCORE", gate_high=0.94, gate_theme=65.0, gate_delta=-5.0),
        Variant("V2_BAL_STRICT_SCORE", gate_high=0.97, gate_theme=75.0, gate_delta=5.0),
        Variant("V2_PRICE_THEME_SCORE", high_w=0.40, theme_w=0.40, rs_w=0.10, turn_w=0.10),
        Variant("V2_RS_SUPPORT_SCORE", high_w=0.30, theme_w=0.30, rs_w=0.25, turn_w=0.15),
        Variant("V2_TURN_SUPPORT_SCORE", high_w=0.30, theme_w=0.30, rs_w=0.15, turn_w=0.25),
        Variant("V2_NO_RS_SCORE", high_w=0.40, theme_w=0.40, rs_w=0.00, turn_w=0.20),
        Variant("V2_NO_TURN_SCORE", high_w=0.40, theme_w=0.40, rs_w=0.20, turn_w=0.00),
        Variant("V2_MEDIAN_THEME_SCORE", theme_mode="MED3"),
        Variant("V2_MIN5_THEME_SCORE", theme_mode="BEST5"),
        Variant("V2_FRESH20_SCORE", fresh20=True),
    ]

    sims: dict[str, Any] = {"CURRENT_BEST": current, "THREE4_BASE": three4}
    BANNED_SYMBOLS = set()
    for v in specs:
        print(f"SIM {v.name}", flush=True)
        sims[v.name] = run_v2(meta, matrices, peer_ctx, features, v, 0.0)

    core_roll = build_core_roll(matrices, args.leader_start, args.analysis_end)
    result: dict[str, Any] = {
        "status": "CORE_RELEADERSHIP_V2_AUDIT",
        "analysis_window": {"start": args.analysis_start, "end": args.analysis_end, "leader_start": args.leader_start, "downloaded": int(meta["downloaded"])},
        "design": {
            "portfolio": "Unchanged 9 Core + 3 Emerging; SELECTIVE 3+1; no forced trim; one priority only on normal vacant Core fill.",
            "bone": "Broad High+Theme recovery gate. RS and residual share-turnover are continuous support scores, not binary mandatory triggers.",
            "turnover": "Residual share-turnover uses 20-session average shares = dollar-volume / close, removing the mechanical price component from dollar-volume expansion.",
            "tie_break_test": "Same V2 signal pool is compared with V2 continuous-score tie-break versus existing V38-rank tie-break.",
            "predeclared_primary": "V2_BAL_BASE_SCORE",
        },
        "theme_coverage": {"best_min3": base_theme_cov, "median_min3": theme_med3_cov, "best_min5": theme_best5_cov},
        "variants": {},
        "reality_check": {},
        "primary_outlier_stress": {},
        "cost10bps": {},
        "named_episode_diagnostics": [],
    }

    for name, sim in sims.items():
        result["variants"][name] = variant_summary(sim, core_roll, matrices)
        sim["equity"].rename("equity").to_csv(out / f"equity_{name}.csv")
        sim["entries"].to_csv(out / f"entries_{name}.csv", index=False)
        sim["trades"].to_csv(out / f"trades_{name}.csv", index=False)

    test_names = ["THREE4_BASE"] + [v.name for v in specs]
    result["reality_check"] = fal.reality_check(sims, "CURRENT_BEST", ["CURRENT_BEST"] + test_names, start="2021-01-04", block=20, reps=5000, seed=95231)

    primary = next(v for v in specs if v.name == "V2_BAL_BASE_SCORE")
    ptdf = fal.priority_trade_frame(sims[primary.name])
    result["primary_outlier_stress"]["priority_trade_returns"] = fal.trimmed_trade_stats(ptdf)
    top = []
    if not ptdf.empty and "return" in ptdf:
        top = [str(s) for s in ptdf.groupby("symbol")["return"].sum().sort_values(ascending=False).index[:5]]
    result["primary_outlier_stress"]["top_priority_profit_symbols"] = top
    for k in (1, 3, 5):
        banned = set(top[:k])
        if not banned:
            continue
        BANNED_SYMBOLS = banned
        name = f"V2_BAL_BAN_TOP{k}_SYMBOLS"
        print(f"SIM {name} banned={sorted(banned)}", flush=True)
        vv = Variant(name)
        sim = run_v2(meta, matrices, peer_ctx, features, vv, 0.0)
        result["primary_outlier_stress"][name] = variant_summary(sim, core_roll, matrices)
        sim["equity"].rename("equity").to_csv(out / f"equity_{name}.csv")
    BANNED_SYMBOLS = set()

    for name, vv in [
        ("V2_BAL_BASE_SCORE", primary),
        ("V2_PRICE_THEME_SCORE", next(v for v in specs if v.name == "V2_PRICE_THEME_SCORE")),
    ]:
        print(f"SIM COST10 {name}", flush=True)
        simc = run_v2(meta, matrices, peer_ctx, features, Variant(name + "_COST10", vv.high_w, vv.theme_w, vv.rs_w, vv.turn_w, vv.gate_high, vv.gate_theme, vv.gate_delta, vv.theme_mode, vv.tie_break, vv.fresh20), cem.TCOST_BPS)
        result["cost10bps"][name] = {
            "period_metrics": period_metrics(simc["equity"]),
            "full_cagr_drag": float(base.metrics(simc["equity"])["cagr"] - base.metrics(sims[name]["equity"])["cagr"]),
        }

    episodes = fal.choose_named_episodes(core_roll)
    for sym, start, peak in episodes:
        result["named_episode_diagnostics"].append(diagnose_episode_v2(sym, start, peak, meta, matrices, peer_ctx, features, primary, sims[primary.name]))

    summary_path = out / "summary_core_releadership_v2.json"
    summary_path.write_text(json.dumps(base.safe(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== CORE_RELEADERSHIP_V2_JSON ===", flush=True)
    print(json.dumps(base.safe(result), ensure_ascii=False, indent=2), flush=True)
    print("=== END_CORE_RELEADERSHIP_V2_JSON ===", flush=True)


if __name__ == "__main__":
    main()
