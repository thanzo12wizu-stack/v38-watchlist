from __future__ import annotations

import argparse
import gc
import json
from dataclasses import dataclass
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
import audit_core_emerging_hybrid_refine as hyb
import validate_early_rotation as er


@dataclass(frozen=True)
class Variant:
    name: str
    rule: str
    profile: str = "BASE"


ACTIVE_VARIANT = Variant("CURRENT_BEST", "NONE")
EXT: dict[str, pd.DataFrame] = {}

PROFILES = {
    "LOOSE": {
        "rs63": 88.0, "rs_acc_pct": 55.0, "require_turn": False,
        "high_ratio": 0.97,
        "theme_rank": 75.0, "theme_delta": 0.0,
        "dvol_acc_pct": 55.0, "dvol_ratio": 1.00,
    },
    "BASE": {
        "rs63": 90.0, "rs_acc_pct": 65.0, "require_turn": True,
        "high_ratio": 0.98,
        "theme_rank": 80.0, "theme_delta": 5.0,
        "dvol_acc_pct": 60.0, "dvol_ratio": 1.03,
    },
    "STRICT": {
        "rs63": 92.0, "rs_acc_pct": 75.0, "require_turn": True,
        "high_ratio": 1.00,
        "theme_rank": 85.0, "theme_delta": 10.0,
        "dvol_acc_pct": 70.0, "dvol_ratio": 1.08,
    },
}


def _v(frame: pd.DataFrame, d: pd.Timestamp, sym: str, default: float = np.nan) -> float:
    try:
        x = float(frame.at[d, sym])
        return x if np.isfinite(x) else default
    except Exception:
        return default


def mild_emerging_score(d, sym, c, matrices, features) -> float:
    bs = float(c.get("rank_score") or c.get("stock_rs189") or 0.0)

    def fv(frame):
        x = _v(frame, d, sym, 0.0)
        return x if np.isfinite(x) else 0.0

    return (
        0.70 * bs
        + 0.15 * fv(matrices["rs63"])
        + 0.07 * fv(features["rs_acc_pct"])
        + 0.04 * fv(features["ret20_pct"])
        + 0.04 * fv(features["dvol_acc_pct"])
    )


def build_theme_internal_rank(root: Path, matrices: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, dict[str, Any]]:
    close = matrices["close"]
    rs63 = matrices["rs63"]
    stock_cols = list(close.columns)
    stock_pos = {s: i for i, s in enumerate(stock_cols)}
    stock_set = set(stock_cols)

    snapshot = er.load_json(root / "sector_snapshot.json")
    theme_members_all, _ = er.extract_theme_members(snapshot)
    themes = {
        str(t): [s for s in members if s in stock_set]
        for t, members in theme_members_all.items()
    }
    themes = {t: members for t, members in themes.items() if len(members) >= 3}

    best = np.full((len(close.index), len(stock_cols)), np.nan, dtype=np.float32)
    memberships = 0
    for n, (theme, members) in enumerate(themes.items(), start=1):
        rank = rs63[members].rank(axis=1, pct=True, method="average").to_numpy(dtype=np.float32) * 100.0
        for j, sym in enumerate(members):
            si = stock_pos[sym]
            best[:, si] = np.fmax(best[:, si], rank[:, j])
        memberships += len(members)
        if n % 50 == 0 or n == len(themes):
            print(f"THEME_INTERNAL_RANK {n}/{len(themes)} memberships={memberships}", flush=True)

    frame = pd.DataFrame(best, index=close.index, columns=stock_cols)
    coverage = {
        "themes": int(len(themes)),
        "memberships": int(memberships),
        "stocks_with_theme": int(np.isfinite(best).any(axis=0).sum()),
    }
    return frame, coverage


def build_extended_features(root: Path, matrices: dict[str, pd.DataFrame], features: dict[str, pd.DataFrame]):
    close = matrices["close"]
    rs63 = matrices["rs63"]
    dvol = matrices["dvol"]

    print("BUILD theme-internal rank", flush=True)
    theme_rank, coverage = build_theme_internal_rank(root, matrices)
    theme_delta20 = (theme_rank - theme_rank.shift(20)).astype(np.float32)

    print("BUILD 63d high recovery and RS/turnover reacceleration", flush=True)
    prior_high63 = close.shift(1).rolling(63, min_periods=50).max()
    high_ratio = (close / prior_high63).astype(np.float32)
    del prior_high63

    rs5 = rs63 - rs63.shift(5)
    prev_rs5 = rs63.shift(5) - rs63.shift(10)
    rs_turn = ((rs5 > 0.0) & (rs5 > prev_rs5)).fillna(False)
    del rs5, prev_rs5

    dvol_ratio20 = (dvol / dvol.shift(20)).astype(np.float32)

    near98 = (high_ratio >= 0.98).fillna(False)
    cross98 = near98 & ~near98.shift(1).fillna(False)
    fresh10_near98 = cross98.rolling(10, min_periods=1).max().gt(0.0)
    del near98, cross98

    out = {
        "theme_rank": theme_rank,
        "theme_delta20": theme_delta20,
        "high_ratio": high_ratio,
        "rs_turn": rs_turn,
        "dvol_ratio20": dvol_ratio20,
        "fresh10_near98": fresh10_near98,
    }
    gc.collect()
    return out, coverage


def component_flags(d: pd.Timestamp, sym: str, matrices, features, profile: str = "BASE"):
    p = PROFILES[profile]
    rs63 = _v(matrices["rs63"], d, sym)
    rs_acc_pct = _v(features["rs_acc_pct"], d, sym)
    turn = bool(EXT["rs_turn"].at[d, sym]) if d in EXT["rs_turn"].index and sym in EXT["rs_turn"].columns else False
    high_ratio = _v(EXT["high_ratio"], d, sym)
    theme_rank = _v(EXT["theme_rank"], d, sym)
    theme_delta = _v(EXT["theme_delta20"], d, sym)
    dv_acc = _v(features["dvol_acc_pct"], d, sym)
    dv_ratio = _v(EXT["dvol_ratio20"], d, sym)

    rs_ok = (
        np.isfinite(rs63) and np.isfinite(rs_acc_pct)
        and rs63 >= p["rs63"] and rs_acc_pct >= p["rs_acc_pct"]
        and ((not p["require_turn"]) or turn)
    )
    high_ok = np.isfinite(high_ratio) and high_ratio >= p["high_ratio"]
    theme_ok = (
        np.isfinite(theme_rank) and np.isfinite(theme_delta)
        and theme_rank >= p["theme_rank"] and theme_delta >= p["theme_delta"]
    )
    dvol_ok = (
        np.isfinite(dv_acc) and np.isfinite(dv_ratio)
        and dv_acc >= p["dvol_acc_pct"] and dv_ratio >= p["dvol_ratio"]
    )
    fresh10 = bool(EXT["fresh10_near98"].at[d, sym]) if d in EXT["fresh10_near98"].index and sym in EXT["fresh10_near98"].columns else False
    return rs_ok, high_ok, theme_ok, dvol_ok, fresh10


def signal_ok(d: pd.Timestamp, sym: str, matrices, features, variant: Variant) -> bool:
    if variant.rule == "NONE":
        return False
    rs, hi, th, dv, fresh = component_flags(d, sym, matrices, features, variant.profile)
    n = int(rs) + int(hi) + int(th) + int(dv)
    if variant.rule == "RS":
        return rs
    if variant.rule == "HIGH":
        return hi
    if variant.rule == "THEME":
        return th
    if variant.rule == "DVOL":
        return dv
    if variant.rule == "RS_HIGH":
        return rs and hi
    if variant.rule == "RS_HIGH_THEME":
        return rs and hi and th
    if variant.rule == "RS_HIGH_DVOL":
        return rs and hi and dv
    if variant.rule == "ALL4":
        return rs and hi and th and dv
    if variant.rule == "THREE4":
        return n >= 3
    if variant.rule == "RS_HIGH_PLUS_ONE":
        return rs and hi and (th or dv)
    if variant.rule == "FRESH10_RS_HIGH_PLUS_ONE":
        return rs and hi and fresh and (th or dv)
    if variant.rule == "BREAK_RS_PLUS_ONE":
        br = _v(EXT["high_ratio"], d, sym)
        return rs and np.isfinite(br) and br >= 1.0 and (th or dv)
    raise ValueError(f"unknown rule {variant.rule}")


def signal_strength(d: pd.Timestamp, sym: str, matrices, features) -> float:
    rs_acc = _v(features["rs_acc_pct"], d, sym, 0.0)
    high = _v(EXT["high_ratio"], d, sym, 0.0)
    high_score = float(np.clip((high - 0.94) / 0.06 * 100.0, 0.0, 100.0))
    theme_rank = _v(EXT["theme_rank"], d, sym, 0.0)
    theme_delta = _v(EXT["theme_delta20"], d, sym, 0.0)
    theme_score = 0.75 * theme_rank + 0.25 * float(np.clip(50.0 + theme_delta, 0.0, 100.0))
    dv = _v(features["dvol_acc_pct"], d, sym, 0.0)
    return 0.30 * rs_acc + 0.25 * high_score + 0.25 * theme_score + 0.20 * dv


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
        if is_core and signal_ok(d, sym, matrices, features, ACTIVE_VARIANT):
            signal_syms.append(sym)

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
        bs = float(c.get("rank_score") or c.get("stock_rs189") or 0.0)
        score = bs if layer == "CORE" else mild_emerging_score(d, sym, c, matrices, features)
        is_sig = bool(layer == "CORE" and sym in signal_syms)
        c["relead_signal"] = is_sig
        c["relead_priority"] = bool(sym == priority)
        c["relead_strength"] = signal_strength(d, sym, matrices, features) if is_sig else np.nan
        c["layer"] = layer
        c["layer_score"] = score + (1000.0 if sym == priority else 0.0)
        c["dvol"] = _v(matrices["dvol"], d, sym)
        c["dvol_pct"] = _v(features["dvol_pct"], d, sym)
        c["rs63"] = _v(matrices["rs63"], d, sym)
        c["rs_acc_pct"] = _v(features["rs_acc_pct"], d, sym)
        c["high63_ratio"] = _v(EXT["high_ratio"], d, sym)
        c["theme_internal_rank"] = _v(EXT["theme_rank"], d, sym)
        c["theme_internal_delta20"] = _v(EXT["theme_delta20"], d, sym)
        c["dvol_acc_pct"] = _v(features["dvol_acc_pct"], d, sym)
        c["dvol_ratio20"] = _v(EXT["dvol_ratio20"], d, sym)
        (core if layer == "CORE" else emerging).append((sym, c))

    core.sort(key=lambda x: x[1]["layer_score"], reverse=True)
    emerging.sort(key=lambda x: x[1]["layer_score"], reverse=True)
    return core, emerging


def run(meta, matrices, peer_ctx, features, variant: Variant, cost_bps: float = 0.0):
    global ACTIVE_VARIANT
    ACTIVE_VARIANT = variant
    cem.classified_candidates = classifier
    return cem.simulate_layered(
        meta, matrices, peer_ctx, features,
        cem.Variant(variant.name, 9, 3, True, 1),
        cost_bps=cost_bps,
    )


def exact_metrics(eq: pd.Series):
    return {
        "2021_plus": base.metrics(eq.loc[eq.index >= "2021-01-04"]),
        "2022_plus": base.metrics(eq.loc[eq.index >= "2022-01-03"]),
        "2024_plus": base.metrics(eq.loc[eq.index >= "2024-01-02"]),
    }


def priority_forward_stats(entries: pd.DataFrame, close: pd.DataFrame) -> dict[str, Any]:
    if entries.empty or "relead_priority" not in entries:
        return {"n": 0}
    rows = []
    idx = close.index
    pos = {pd.Timestamp(d): i for i, d in enumerate(idx)}
    for _, r in entries.loc[entries["relead_priority"].fillna(False).astype(bool)].iterrows():
        d = pd.Timestamp(r["signal_date"])
        sym = str(r["symbol"])
        i = pos.get(d)
        if i is None or sym not in close.columns:
            continue
        p0 = _v(close, d, sym)
        if not np.isfinite(p0) or p0 <= 0:
            continue
        rec = {"symbol": sym, "signal_date": d}
        for h in (20, 63):
            j = min(i + h, len(idx) - 1)
            p1 = _v(close, pd.Timestamp(idx[j]), sym)
            rec[f"ret{h}"] = p1 / p0 - 1.0 if np.isfinite(p1) and p1 > 0 else np.nan
            window = close[sym].iloc[i:j + 1]
            rec[f"max{h}"] = float(window.max() / p0 - 1.0) if window.notna().any() else np.nan
        rows.append(rec)
    df = pd.DataFrame(rows)
    out: dict[str, Any] = {"n": int(len(df))}
    for col in ("ret20", "max20", "ret63", "max63"):
        x = pd.to_numeric(df.get(col, pd.Series(dtype=float)), errors="coerce").dropna()
        out[col] = {
            "mean": float(x.mean()) if len(x) else None,
            "median": float(x.median()) if len(x) else None,
            "positive_rate": float((x > 0).mean()) if len(x) else None,
        }
    return out


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

    print("BUILD shared PIT inputs", flush=True)
    meta, matrices = ex.build_inputs_ext(
        root, args.analysis_start, args.analysis_end, args.max_tickers, args.batch_size
    )
    peer_ctx = loo.build_leave_one_out_scores(root, matrices)
    features = cem.build_features(matrices)
    print(f"UNIVERSE downloaded={meta['downloaded']}", flush=True)

    print("SIM exact 9+3 reference", flush=True)
    ref = hyb.run_variant(
        meta, matrices, peer_ctx, features,
        "REF_CURRENT_BEST", 9, 3, "MILD", 1, 0.0
    )

    global EXT
    EXT, theme_coverage = build_extended_features(root, matrices, features)

    variants = [
        Variant("CURRENT_BEST", "NONE"),
        Variant("RS_ONLY_BASE", "RS"),
        Variant("HIGH_ONLY_BASE", "HIGH"),
        Variant("THEME_ONLY_BASE", "THEME"),
        Variant("DVOL_ONLY_BASE", "DVOL"),
        Variant("RS_HIGH_BASE", "RS_HIGH"),
        Variant("RS_HIGH_THEME_BASE", "RS_HIGH_THEME"),
        Variant("RS_HIGH_DVOL_BASE", "RS_HIGH_DVOL"),
        Variant("ALL4_LOOSE", "ALL4", "LOOSE"),
        Variant("ALL4_BASE", "ALL4", "BASE"),
        Variant("ALL4_STRICT", "ALL4", "STRICT"),
        Variant("THREE4_BASE", "THREE4"),
        Variant("RS_HIGH_PLUS_ONE_BASE", "RS_HIGH_PLUS_ONE"),
        Variant("FRESH10_RS_HIGH_PLUS_ONE", "FRESH10_RS_HIGH_PLUS_ONE"),
        Variant("BREAK_RS_PLUS_ONE", "BREAK_RS_PLUS_ONE"),
    ]

    sims = {}
    for v in variants:
        print(f"SIM {v.name}", flush=True)
        sims[v.name] = run(meta, matrices, peer_ctx, features, v, 0.0)

    a, b = sims["CURRENT_BEST"]["equity"].align(ref["equity"], join="inner")
    maxdiff = float(np.nanmax(np.abs(a.to_numpy(float) - b.to_numpy(float))))
    if maxdiff > 1e-10:
        raise RuntimeError(f"current-best reproduction mismatch {maxdiff}")

    print("BUILD Core leader denominators", flush=True)
    rolling = lc.build_rolling_superleaders(
        matrices, pd.Timestamp(args.leader_start), pd.Timestamp(args.analysis_end)
    )
    dvol = matrices["dvol"]
    dvol_pct = dvol.rank(axis=1, pct=True) * 100.0
    core_rows = []
    for _, rr in rolling.iterrows():
        sym = str(rr["symbol"])
        d = pd.Timestamp(rr["start_date"])
        if sym not in dvol.columns or d not in dvol.index:
            continue
        abs_ok = pd.notna(dvol.at[d, sym]) and float(dvol.at[d, sym]) >= cem.CORE_DVOL_ABS
        pct_ok = pd.notna(dvol_pct.at[d, sym]) and float(dvol_pct.at[d, sym]) >= cem.CORE_DVOL_PCT
        if abs_ok or pct_ok:
            core_rows.append(dict(rr))
    core_roll = pd.DataFrame(core_rows)

    result: dict[str, Any] = {
        "status": "CORE_RELEADERSHIP_PRIORITY_AUDIT",
        "analysis_window": {
            "start": args.analysis_start,
            "end": args.analysis_end,
            "leader_start": args.leader_start,
            "downloaded": int(meta["downloaded"]),
        },
        "current_best_validation": {
            "status": "PASS",
            "equity_max_abs_diff": maxdiff,
        },
        "design": {
            "portfolio": "9 Core + 3 Emerging; SELECTIVE 3 Core + 1 Emerging; no forced trim",
            "releadership": "No prior-leader-history condition. Signal only uses information available on signal date.",
            "priority": "At most one signaled Core stock gets first priority on a normal vacant Core fill; no holding is sold to make room.",
            "tie_breaker": "Current V38 rank among valid Re-Leadership signals, so detection is tested without rewriting Core ranking.",
            "components": {
                "RS": "RS63 strength + 20d RS-change percentile; BASE/STRICT also require 5d RS slope to be positive and faster than the prior 5d slope.",
                "PRICE": "Close relative to prior 63-session closing high; thresholds 97%/98%/100%.",
                "THEME_INTERNAL": "Best within-theme RS63 percentile across granular theme memberships and its 20-session recovery.",
                "TURNOVER": "20d average dollar-volume re-expansion by cross-sectional acceleration percentile and ratio versus 20 sessions earlier.",
            },
            "profiles": PROFILES,
            "unchanged": "Market Mode, eligibility, Core/Emerging slots, current V38 Core rank, Emerging MILD rank, exits, next-open execution.",
        },
        "theme_internal_coverage": theme_coverage,
        "variants": {},
        "bootstrap_vs_current": {},
        "cost10bps": {},
    }

    captures = {}
    for name, sim in sims.items():
        cap = cem.simple_capture(core_roll, sim["intervals"], matrices["close"])
        captures[name] = cap
        ent = sim["entries"]
        prio = int(ent.get("relead_priority", pd.Series(dtype=bool)).fillna(False).astype(bool).sum()) if not ent.empty else 0
        sig = int(ent.get("relead_signal", pd.Series(dtype=bool)).fillna(False).astype(bool).sum()) if not ent.empty else 0
        result["variants"][name] = {
            "metrics": base.slice_metrics(sim["equity"]),
            "exact_period_metrics": exact_metrics(sim["equity"]),
            "trade_stats": rt.trade_stats(sim["trades"]),
            "entries": int(len(ent)),
            "signal_entries": sig,
            "priority_entries": prio,
            "priority_forward": priority_forward_stats(ent, matrices["close"]),
            "core_rolling_capture": cem.summarize_capture_ext(cap),
        }
        sim["equity"].rename("equity").to_csv(out / f"equity_{name}.csv")
        ent.to_csv(out / f"entries_{name}.csv", index=False)
        sim["trades"].to_csv(out / f"trades_{name}.csv", index=False)
        cap.to_csv(out / f"capture_core_rolling_{name}.csv", index=False)

    current = sims["CURRENT_BEST"]["equity"]
    for i, v in enumerate(variants):
        if v.name == "CURRENT_BEST":
            continue
        result["bootstrap_vs_current"][v.name] = base.bootstrap_block_win(
            sims[v.name]["equity"], current, block=20, reps=5000, seed=81000 + i
        )

    cost_names = {
        "ALL4_BASE",
        "THREE4_BASE",
        "RS_HIGH_PLUS_ONE_BASE",
        "FRESH10_RS_HIGH_PLUS_ONE",
        "BREAK_RS_PLUS_ONE",
    }
    variant_map = {v.name: v for v in variants}
    for name in cost_names:
        print(f"SIM COST10 {name}", flush=True)
        sc = run(meta, matrices, peer_ctx, features, Variant(name + "_COST10", variant_map[name].rule, variant_map[name].profile), cem.TCOST_BPS)
        result["cost10bps"][name] = {
            "exact_period_metrics": exact_metrics(sc["equity"]),
            "full_cagr_drag": float(
                base.metrics(sc["equity"])["cagr"] - base.metrics(sims[name]["equity"])["cagr"]
            ),
        }

    named = {"NVDA", "PLTR", "SMCI", "APP", "CRWD", "HOOD", "MSTR", "MU", "VST", "VRT", "SNDK"}
    rows = []
    for variant, cf in captures.items():
        if cf.empty:
            continue
        z = cf.loc[cf["symbol"].astype(str).isin(named)]
        for _, x in z.iterrows():
            rows.append({
                "variant": variant,
                "symbol": x["symbol"],
                "start_date": x["start_date"],
                "peak_date": x["peak_date"],
                "peak_return": x["peak_return"],
                "captured": x["captured"],
                "capture_date": x["capture_date"],
                "capture_progress": x["capture_progress"],
            })
    pd.DataFrame(rows).to_csv(out / "named_core_leader_capture.csv", index=False)

    summary_path = out / "summary_core_releadership_priority.json"
    summary_path.write_text(
        json.dumps(base.safe(result), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("=== CORE_RELEADERSHIP_PRIORITY_JSON ===", flush=True)
    print(json.dumps(base.safe(result), ensure_ascii=False, indent=2), flush=True)
    print("=== END_CORE_RELEADERSHIP_PRIORITY_JSON ===", flush=True)


if __name__ == "__main__":
    main()
