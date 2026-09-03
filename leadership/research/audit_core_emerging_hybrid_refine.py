from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import audit_ordinary_stock_market_mode_robustness as base
import audit_ordinary_stock_theme_leave_one_out as loo
import audit_ordinary_stock_exit_trail as ex
import audit_ordinary_stock_rebalance_vs_trail as rt
import audit_five_year_leader_capture as lc
import audit_core_emerging_leader_mix as cem

MODE = "MILD"


def hybrid_layer_score(d, sym, c, layer, matrices, features, enhanced):
    base_score = float(c.get("rank_score") or c.get("stock_rs189") or 0.0)
    if layer == "CORE":
        return base_score
    rs63 = float(matrices["rs63"].at[d, sym]) if pd.notna(matrices["rs63"].at[d, sym]) else 0.0
    acc = float(features["rs_acc_pct"].at[d, sym]) if pd.notna(features["rs_acc_pct"].at[d, sym]) else 0.0
    ret20 = float(features["ret20_pct"].at[d, sym]) if pd.notna(features["ret20_pct"].at[d, sym]) else 0.0
    dvacc = float(features["dvol_acc_pct"].at[d, sym]) if pd.notna(features["dvol_acc_pct"].at[d, sym]) else 0.0
    if MODE == "MILD":
        return 0.70 * base_score + 0.15 * rs63 + 0.07 * acc + 0.04 * ret20 + 0.04 * dvacc
    return 0.50 * base_score + 0.20 * rs63 + 0.15 * acc + 0.10 * ret20 + 0.05 * dvacc


def run_variant(meta, matrices, peer_ctx, features, name, core_slots, em_slots, mode, selective_em=0, cost_bps=0.0):
    global MODE
    MODE = mode
    cem.layer_score = hybrid_layer_score
    v = cem.Variant(name, core_slots, em_slots, True, selective_em)
    return cem.simulate_layered(meta, matrices, peer_ctx, features, v, cost_bps=cost_bps)


def capture_set(sim, frames, close):
    return {k: cem.simple_capture(v, sim["intervals"], close) for k, v in frames.items()}


def main():
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
    end = pd.Timestamp(args.analysis_end)
    leader_start = pd.Timestamp(args.leader_start)

    print("BUILD shared PIT inputs", flush=True)
    meta, matrices = ex.build_inputs_ext(root, args.analysis_start, args.analysis_end, args.max_tickers, args.batch_size)
    peer_ctx = loo.build_leave_one_out_scores(root, matrices)
    features = cem.build_features(matrices)
    print(f"UNIVERSE downloaded={meta['downloaded']}", flush=True)

    print("SIM exact baseline", flush=True)
    baseline = lc.simulate_current_with_entries(meta, matrices, peer_ctx, use_theme=True)
    validation = lc.validate_simulation(meta, matrices, peer_ctx, baseline)
    plain = cem.simulate_layered(meta, matrices, peer_ctx, features, cem.Variant("CE_PLAIN_10_2", 10, 2, False, 0), 0.0)
    sims = {"BASELINE_MIXED12": baseline, "CE_PLAIN_10_2": plain}

    configs = [
        ("HYB_MILD_10_2", 10, 2, "MILD", 0),
        ("HYB_MILD_9_3", 9, 3, "MILD", 0),
        ("HYB_MILD_8_4", 8, 4, "MILD", 0),
        ("HYB_MILD_9_3_SEL3_1", 9, 3, "MILD", 1),
        ("HYB_STRONG_10_2", 10, 2, "STRONG", 0),
        ("HYB_STRONG_9_3", 9, 3, "STRONG", 0),
    ]
    for name, c, e, mode, se in configs:
        print(f"SIM {name}", flush=True)
        sims[name] = run_variant(meta, matrices, peer_ctx, features, name, c, e, mode, se, 0.0)

    print("BUILD leader denominators", flush=True)
    annual = lc.build_annual_leaders(matrices, leader_start, end)
    rolling = lc.build_rolling_superleaders(matrices, leader_start, end)
    core_annual = annual.loc[annual["mega_liquid"].astype(bool)].copy()
    core_rolling = rolling.loc[pd.to_numeric(rolling["early_dvol"], errors="coerce") >= cem.MEGA_DVOL].copy()
    em_abs, em_rel = cem.build_emerging_graduates(rolling, matrices, features)
    frames = {
        "annual": annual, "core_annual": core_annual, "rolling": rolling, "core_rolling": core_rolling,
        "emerging_abs": em_abs, "emerging_rel": em_rel,
    }
    captures = {name: capture_set(sim, frames, matrices["close"]) for name, sim in sims.items()}

    result: dict[str, Any] = {
        "status": "CORE_EMERGING_HYBRID_REFINE",
        "analysis_window": {"start": args.analysis_start, "end": args.analysis_end, "leader_start": args.leader_start, "downloaded": int(meta["downloaded"])},
        "baseline_validation": validation,
        "purpose": "Second-round isolation test: keep current V38 ranking for Core; apply acceleration only inside Emerging so Core capture improvements do not come at the cost of rewriting established-leader ranking.",
        "mild_emerging_score": "70% current V38 rank + 15% RS63 + 7% RS63 20d acceleration percentile + 4% 20d return percentile + 4% DDV acceleration percentile",
        "strong_emerging_score": "50% current V38 rank + 20% RS63 + 15% RS63 acceleration percentile + 10% 20d return percentile + 5% DDV acceleration percentile",
        "variants": {}, "bootstrap_vs_baseline": {}, "bootstrap_vs_plain10_2": {}, "cost10bps": {},
    }

    for name, sim in sims.items():
        ent = sim["entries"]
        mix = {}
        if not ent.empty and "entry_layer" in ent.columns:
            mix = {str(k): int(v) for k, v in ent["entry_layer"].value_counts().items()}
        result["variants"][name] = {
            "metrics": base.slice_metrics(sim["equity"]), "trade_stats": rt.trade_stats(sim["trades"]),
            "entries": int(len(ent)), "entry_layer_mix": mix,
            "capture": {k: cem.summarize_capture_ext(v) for k, v in captures[name].items()},
        }
        sim["equity"].rename("equity").to_csv(out / f"equity_{name}.csv")
        sim["entries"].to_csv(out / f"entries_{name}.csv", index=False)
        sim["trades"].to_csv(out / f"trades_{name}.csv", index=False)
        for k, f in captures[name].items():
            f.to_csv(out / f"capture_{k}_{name}.csv", index=False)

    b = sims["BASELINE_MIXED12"]["equity"]
    p = sims["CE_PLAIN_10_2"]["equity"]
    for name, sim in sims.items():
        if name != "BASELINE_MIXED12":
            result["bootstrap_vs_baseline"][name] = base.bootstrap_block_win(sim["equity"], b, block=20, reps=4000, seed=31000 + list(sims).index(name))
        if name not in {"BASELINE_MIXED12", "CE_PLAIN_10_2"}:
            result["bootstrap_vs_plain10_2"][name] = base.bootstrap_block_win(sim["equity"], p, block=20, reps=4000, seed=41000 + list(sims).index(name))

    for name, c, e, mode, se in configs:
        if name not in {"HYB_MILD_10_2", "HYB_MILD_9_3", "HYB_MILD_8_4"}:
            continue
        print(f"SIM_COST10 {name}", flush=True)
        simc = run_variant(meta, matrices, peer_ctx, features, name + "_COST10", c, e, mode, se, cem.TCOST_BPS)
        result["cost10bps"][name] = {
            "metrics": base.slice_metrics(simc["equity"]),
            "cagr_drag": float(base.metrics(simc["equity"])["cagr"] - base.metrics(sims[name]["equity"])["cagr"]),
        }

    named_frames = {name: caps["rolling"] for name, caps in captures.items()}
    cem.named_audit(named_frames, {k: v["entries"] for k, v in sims.items()}).to_csv(out / "named_leader_audit.csv", index=False)
    (out / "summary_core_emerging_hybrid_refine.json").write_text(json.dumps(base.safe(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== CORE_EMERGING_HYBRID_REFINE_JSON ===", flush=True)
    print(json.dumps(base.safe(result), ensure_ascii=False, indent=2), flush=True)
    print("=== END_CORE_EMERGING_HYBRID_REFINE_JSON ===", flush=True)


if __name__ == "__main__":
    main()
