from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import audit_ordinary_stock_market_mode_robustness as base
import audit_ordinary_stock_exit_trail as ex
import audit_ordinary_stock_theme_leave_one_out as loo
import audit_core_emerging_leader_mix as cem
import audit_core_emerging_hybrid_refine as hyb
import audit_core_releadership_priority as rel
import audit_core_releadership_volume_decomposition as vd
import audit_annual_leader_releadership_capture as alc
import audit_five_year_leader_capture as lc
import audit_leader_factor_horizon_discovery as disc

ACTIVE_NAME = "CURRENT_V38"
FACTOR_MATS: dict[str, pd.DataFrame] = {}
FEATURES: dict[str, pd.DataFrame] = {}
MATRICES: dict[str, pd.DataFrame] = {}
PEER_CTX: dict[str, Any] = {}


def safe(v: Any) -> Any:
    return base.safe(v)


def _v(frame: pd.DataFrame, d: pd.Timestamp, sym: str, default=np.nan) -> float:
    try:
        x = float(frame.at[d, sym])
        return x if np.isfinite(x) else default
    except Exception:
        return default


def core_factor_score(d: pd.Timestamp, sym: str, c: dict[str, Any]) -> float:
    if ACTIVE_NAME == "CURRENT_V38":
        return float(c.get("rank_score") or c.get("stock_rs189") or 0.0)
    f = FACTOR_MATS[ACTIVE_NAME]
    return _v(f, d, sym, -1e9)


def classifier(d, matrices, peer_ctx, features, bucket, enhanced):
    cmap = cem.base_candidate_map(d, matrices, peer_ctx, bucket)
    core, emerging = [], []
    signal_syms = []
    for sym, c0 in cmap.items():
        try:
            is_core = bool(features["core_mask"].at[d, sym])
            is_em = bool(features["emerging_mask"].at[d, sym])
        except Exception:
            continue
        if not (is_core or is_em):
            continue
        if is_core and rel.signal_ok(d, sym, matrices, features, rel.Variant("THREE4", "THREE4", "BASE")):
            signal_syms.append(sym)

    # Preserve the validated P1 behavior: ONE Re-Leadership priority selected by CURRENT V38 rank,
    # even when the ordinary Core ranking under study changes.
    priority = None
    if signal_syms:
        priority = max(
            signal_syms,
            key=lambda s: float(cmap[s].get("rank_score") or cmap[s].get("stock_rs189") or 0.0),
        )

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
        if layer == "CORE":
            raw = core_factor_score(d, sym, c)
            score = raw
        else:
            raw = np.nan
            score = rel.mild_emerging_score(d, sym, c, matrices, features)
        is_sig = bool(layer == "CORE" and sym in signal_syms)
        c.update({
            "layer": layer,
            "leader_rank_factor": ACTIVE_NAME,
            "leader_rank_raw": raw,
            "relead_signal": is_sig,
            "relead_priority": bool(sym == priority),
            "layer_score": score + (1000.0 if sym == priority else 0.0),
            "dvol": _v(matrices["dvol"], d, sym),
            "dvol_pct": _v(features["dvol_pct"], d, sym),
            "rs63": _v(matrices["rs63"], d, sym),
            "rs_acc_pct": _v(features["rs_acc_pct"], d, sym),
            "high63_ratio": _v(rel.EXT["high_ratio"], d, sym),
            "theme_internal_rank": _v(rel.EXT["theme_rank"], d, sym),
            "theme_internal_delta20": _v(rel.EXT["theme_delta20"], d, sym),
            "dvol_acc_pct": _v(features["dvol_acc_pct"], d, sym),
            "dvol_ratio20": _v(rel.EXT["dvol_ratio20"], d, sym),
        })
        (core if layer == "CORE" else emerging).append((sym, c))

    core.sort(key=lambda x: x[1]["layer_score"], reverse=True)
    emerging.sort(key=lambda x: x[1]["layer_score"], reverse=True)
    return core, emerging


def run_variant(meta, matrices, peer_ctx, features, name: str, cost_bps: float = 0.0):
    global ACTIVE_NAME
    ACTIVE_NAME = name
    cem.classified_candidates = classifier
    return cem.simulate_layered(
        meta, matrices, peer_ctx, features,
        cem.Variant(name, 9, 3, True, 1),
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
        "dev_2021_2023": m("2021-01-04", "2023-12-29"),
        "oos_2024_plus": m("2024-01-02"),
        "2025_plus": m("2025-01-02"),
    }


def capture_summary(df: pd.DataFrame) -> dict[str, Any]:
    if df.empty:
        return {"n": 0}
    z = df.copy()
    cap = z["captured"].astype(bool)
    prog = pd.to_numeric(z.loc[cap, "capture_progress"], errors="coerce")
    early20 = cap & (pd.to_numeric(z["capture_progress"], errors="coerce") <= 0.20)
    early33 = cap & (pd.to_numeric(z["capture_progress"], errors="coerce") <= 1/3)
    return {
        "n": int(len(z)),
        "captured_n": int(cap.sum()),
        "capture_rate": float(cap.mean()),
        "early20_n": int(early20.sum()),
        "early20_rate_all": float(early20.mean()),
        "early20_share_hits": float(early20.sum() / max(1, cap.sum())),
        "early33_n": int(early33.sum()),
        "early33_rate_all": float(early33.mean()),
        "median_capture_progress": float(prog.median()) if prog.notna().any() else None,
    }


def by_year_top10(df: pd.DataFrame) -> dict[str, Any]:
    z = df.loc[pd.to_numeric(df["rank"], errors="coerce") <= 10].copy()
    return {str(p): capture_summary(g) for p, g in z.groupby("period", sort=True)}


def main():
    global FACTOR_MATS, FEATURES, MATRICES, PEER_CTX
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--output", required=True)
    ap.add_argument("--analysis-start", default="2020-01-02")
    ap.add_argument("--analysis-end", default="2026-09-02")
    ap.add_argument("--leader-start", default="2021-01-04")
    ap.add_argument("--max-tickers", type=int, default=6000)
    ap.add_argument("--batch-size", type=int, default=75)
    args = ap.parse_args()
    root = Path(args.root); out = root / args.output; out.mkdir(parents=True, exist_ok=True)

    print("BUILD PIT inputs", flush=True)
    meta, matrices = ex.build_inputs_ext(root, args.analysis_start, args.analysis_end, args.max_tickers, args.batch_size)
    peer_ctx = loo.build_leave_one_out_scores(root, matrices)
    features = cem.build_features(matrices)
    MATRICES, PEER_CTX, FEATURES = matrices, peer_ctx, features
    print(f"UNIVERSE downloaded={meta['downloaded']}", flush=True)

    print("FREEZE independent leader labels", flush=True)
    annual = lc.build_annual_leaders(matrices, pd.Timestamp(args.leader_start), pd.Timestamp(args.analysis_end))
    rolling = lc.build_rolling_superleaders(matrices, pd.Timestamp(args.leader_start), pd.Timestamp(args.analysis_end))
    freeze = alc.freeze_labels(out, annual, rolling)
    annual.to_csv(out / "annual_leaders_frozen.csv", index=False)
    rolling.to_csv(out / "rolling_126_leaders_frozen.csv", index=False)

    print("BUILD Re-Leadership and factor matrices", flush=True)
    rel.EXT, theme_coverage = rel.build_extended_features(root, matrices, features)
    rel.signal_ok = vd.signal_ok
    vd.PRICE_ACC_PCT = features["ret20_pct"].astype(np.float32)
    vd.PRICE_RATIO20 = (matrices["close"] / matrices["close"].shift(20)).astype(np.float32)
    vd.SHARE_ACC_PCT, vd.SHARE_RATIO20 = __import__("audit_core_releadership_falsification").build_share_volume_features(matrices, features)
    vd.BANNED_SYMBOLS = set()

    common = disc.build_common(root, matrices)
    rs = disc.build_rs(matrices["close"], common["BASE_POOL"])
    theme = disc.theme_frame(peer_ctx, matrices["close"])
    comp = disc.build_factor_components(matrices["close"], common, rs, theme)
    specs = disc.factor_specs(rs, comp)

    # Pre-declared discovery factors + two transparent composites. Eligibility is held at CURRENT V38 for isolation.
    FACTOR_MATS = {
        "RS21": specs["RS21"],
        "RS42": specs["RS42"],
        "RS63": specs["RS63"],
        "RS126": specs["RS126"],
        "RS189": specs["RS189"],
        "RS63_HIGH": specs["RS63_HIGH"],
        "RS63_ACCEL": specs["RS63_ACCEL"],
        "RS63_P20_THEME": specs["RS63_P20_THEME"],
        "RS63_HIGH_ACCEL": (0.50 * rs[63] + 0.25 * comp["HIGH63"] + 0.25 * comp["ACC63"]).astype(np.float32),
        "RS63_HIGH_ACCEL_THEME": (0.40 * rs[63] + 0.20 * comp["HIGH63"] + 0.20 * comp["ACC63"] + 0.20 * comp["THEME"].fillna(50.0)).astype(np.float32),
    }

    # Existing research-top reference for exact reproduction.
    ref = rel.run(meta, matrices, peer_ctx, features, rel.Variant("REF_THREE4", "THREE4", "BASE"), 0.0)
    sims: dict[str, Any] = {}
    for name in ["CURRENT_V38"] + list(FACTOR_MATS):
        print(f"SIM {name}", flush=True)
        sims[name] = run_variant(meta, matrices, peer_ctx, features, name, 0.0)

    a, b = sims["CURRENT_V38"]["equity"].align(ref["equity"], join="inner")
    maxdiff = float(np.nanmax(np.abs(a.to_numpy(float) - b.to_numpy(float)))) if len(a) else 0.0
    if len(a) != len(ref["equity"]) or maxdiff > 1e-10:
        raise RuntimeError(f"CURRENT_V38 THREE4 reproduction mismatch maxdiff={maxdiff}")

    result: dict[str, Any] = {
        "status": "CORE_RANK_HORIZON_PORTFOLIO_AUDIT",
        "analysis_window": {"start": args.analysis_start, "end": args.analysis_end, "leader_start": args.leader_start, "downloaded": int(meta["downloaded"])},
        "freeze": freeze,
        "validation": {"current_three4_reproduction": "PASS", "equity_max_abs_diff": maxdiff},
        "design": {
            "unchanged": "Current V38 eligibility (including RS63>=85 & RS189>=85), 9 Core + 3 Emerging, SELECTIVE 3+1, Emerging MILD rank, exits, Market Mode, next-open execution.",
            "isolated_change": "Core ordinary ranking only. THREE4 P1 remains active and its single priority winner is ALWAYS chosen by current V38 rank, not the candidate ranking under test.",
            "purpose": "Determine whether RS189 is the best Core ranking horizon after holding current eligibility constant.",
            "exploratory": ["RS63_HIGH_ACCEL", "RS63_HIGH_ACCEL_THEME"],
        },
        "theme_coverage": theme_coverage,
        "variants": {},
    }

    annual10 = annual.loc[pd.to_numeric(annual["rank"], errors="coerce") <= 10].copy()
    for name, sim in sims.items():
        print(f"CAPTURE {name}", flush=True)
        ac = alc.annotate(annual, sim, matrices, meta, peer_ctx, features, rel.Variant(name, "THREE4", "BASE"))
        rc = alc.annotate(rolling, sim, matrices, meta, peer_ctx, features, rel.Variant(name, "THREE4", "BASE"))
        ac.to_csv(out / f"annual_capture_{name}.csv", index=False)
        rc.to_csv(out / f"rolling126_capture_{name}.csv", index=False)
        top10 = ac.loc[pd.to_numeric(ac["rank"], errors="coerce") <= 10]
        years = pd.to_numeric(top10["period"].astype(str).str[:4], errors="coerce")
        result["variants"][name] = {
            "metrics": period_metrics(sim["equity"]),
            "annual_top10_all": capture_summary(top10),
            "annual_top10_dev_2021_2023": capture_summary(top10.loc[years.between(2021, 2023)]),
            "annual_top10_oos_2024_2026": capture_summary(top10.loc[years.between(2024, 2026)]),
            "annual_top10_by_year": by_year_top10(ac),
            "rolling126_all": capture_summary(rc),
            "trade_stats": __import__("audit_ordinary_stock_rebalance_vs_trail").trade_stats(sim["trades"]),
        }
        sim["equity"].rename("equity").to_csv(out / f"equity_{name}.csv")
        sim["entries"].to_csv(out / f"entries_{name}.csv", index=False)
        sim["trades"].to_csv(out / f"trades_{name}.csv", index=False)

    path = out / "summary_core_rank_horizon_portfolio.json"
    path.write_text(json.dumps(safe(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== CORE_RANK_HORIZON_PORTFOLIO_JSON ===", flush=True)
    print(json.dumps(safe(result), ensure_ascii=False, indent=2), flush=True)
    print("=== END_CORE_RANK_HORIZON_PORTFOLIO_JSON ===", flush=True)


if __name__ == "__main__":
    main()
