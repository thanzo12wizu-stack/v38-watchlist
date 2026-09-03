from __future__ import annotations

import argparse
import hashlib
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
import audit_core_releadership_falsification as fal
import audit_core_releadership_volume_decomposition as vd
import audit_five_year_leader_capture as lc


def safe(v: Any) -> Any:
    return base.safe(v)


def _px(frame: pd.DataFrame, d: pd.Timestamp, sym: str, default=np.nan) -> float:
    try:
        x = float(frame.at[d, sym])
        return x if np.isfinite(x) else default
    except Exception:
        return default


def freeze_labels(out: Path, annual: pd.DataFrame, rolling: pd.DataFrame) -> dict[str, Any]:
    a = annual.copy()
    r = rolling.copy()
    a["evaluation_set"] = "ANNUAL_LIQUID"
    r["evaluation_set"] = "ROLLING_126_SUPERLEADER"
    cols = sorted(set(a.columns) | set(r.columns))
    frozen = pd.concat([a.reindex(columns=cols), r.reindex(columns=cols)], ignore_index=True)
    sort_cols = [c for c in ["evaluation_set", "period", "rank", "symbol", "start_date"] if c in frozen.columns]
    frozen = frozen.sort_values(sort_cols, na_position="last").reset_index(drop=True)
    path = out / "leader_labels_frozen.csv"
    frozen.to_csv(path, index=False)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    (out / "leader_labels_sha256.txt").write_text(digest + "\n", encoding="utf-8")
    return {"rows": int(len(frozen)), "sha256": digest}


def find_overlap(intervals: pd.DataFrame, sym: str, start: pd.Timestamp, peak: pd.Timestamp) -> pd.DataFrame:
    if intervals.empty:
        return intervals
    z = intervals.loc[intervals["symbol"].astype(str) == str(sym)].copy()
    if z.empty:
        return z
    z["entry_date"] = pd.to_datetime(z["entry_date"])
    z["exit_date"] = pd.to_datetime(z["exit_date"], errors="coerce")
    return z.loc[(z["entry_date"] <= peak) & (z["exit_date"].isna() | (z["exit_date"] > start))].sort_values("entry_date")


def generic_diagnosis(symbol: str, start: pd.Timestamp, peak: pd.Timestamp, meta, matrices, peer_ctx, features, variant: rel.Variant | None) -> dict[str, Any]:
    dates = [pd.Timestamp(d) for d in meta["analysis_idx"] if start <= pd.Timestamp(d) <= peak]
    counts = {k: 0 for k in ["tradable", "layer", "candidate", "signal", "priority"]}
    first = {k: None for k in counts}
    for d in dates:
        color = str(meta["nq"].at[d, "nq_color"]) if d in meta["nq"].index and pd.notna(meta["nq"].at[d, "nq_color"]) else ""
        br = float(meta["breadth"].loc[d]) if d in meta["breadth"].index and pd.notna(meta["breadth"].loc[d]) else np.nan
        bucket = base.breadth_bucket(br)
        tradable = color in ("Blue", "Green") and bucket > 0
        if tradable:
            counts["tradable"] += 1
            first["tradable"] = first["tradable"] or str(d.date())
        try:
            layer = bool(features["core_mask"].at[d, symbol]) or bool(features["emerging_mask"].at[d, symbol])
        except Exception:
            layer = False
        if layer:
            counts["layer"] += 1
            first["layer"] = first["layer"] or str(d.date())
        if not tradable:
            continue
        cmap = cem.base_candidate_map(d, matrices, peer_ctx, bucket)
        cand = symbol in cmap
        if cand:
            counts["candidate"] += 1
            first["candidate"] = first["candidate"] or str(d.date())
        if variant is None or not cand:
            continue
        try:
            core = bool(features["core_mask"].at[d, symbol])
        except Exception:
            core = False
        if not core or not vd.signal_ok(d, symbol, matrices, features, variant):
            continue
        counts["signal"] += 1
        first["signal"] = first["signal"] or str(d.date())
        sigs = []
        for s in cmap:
            try:
                if not bool(features["core_mask"].at[d, s]):
                    continue
            except Exception:
                continue
            if vd.signal_ok(d, s, matrices, features, variant):
                sigs.append(s)
        if sigs:
            winner = max(sigs, key=lambda s: float(cmap[s].get("rank_score") or cmap[s].get("stock_rs189") or 0.0))
            if winner == symbol:
                counts["priority"] += 1
                first["priority"] = first["priority"] or str(d.date())
    if counts["tradable"] == 0:
        reason = "MARKET_GATE"
    elif counts["layer"] == 0:
        reason = "NOT_CORE_OR_EMERGING"
    elif counts["candidate"] == 0:
        reason = "NOT_BASE_CANDIDATE"
    elif variant is not None and counts["signal"] == 0:
        reason = "NO_RELEAD_SIGNAL_OR_NORMAL_RANK_LOSS"
    elif variant is not None and counts["priority"] == 0:
        reason = "SIGNAL_LOST_V38_TIEBREAK"
    else:
        reason = "PORTFOLIO_SLOT_OR_TIMING"
    return {"miss_reason": reason, **{f"{k}_days": int(v) for k, v in counts.items()}, **{f"first_{k}": v for k, v in first.items()}}


def annotate(leaders: pd.DataFrame, sim, matrices, meta, peer_ctx, features, variant: rel.Variant | None) -> pd.DataFrame:
    rows = []
    close = matrices["close"]
    for _, rr in leaders.iterrows():
        z = dict(rr)
        sym = str(z["symbol"]); start = pd.Timestamp(z["start_date"]); peak = pd.Timestamp(z["peak_date"])
        ov = find_overlap(sim["intervals"], sym, start, peak)
        hit = not ov.empty
        z.update({"captured": bool(hit), "capture_date": pd.NaT, "capture_mode": "MISSED", "capture_progress": np.nan, "remaining_upside": np.nan, "miss_reason": None})
        if hit:
            ent = pd.Timestamp(ov.iloc[0]["entry_date"])
            if ent <= start:
                z["capture_date"] = start; z["capture_mode"] = "PREPOSITIONED"; z["capture_progress"] = 0.0; z["remaining_upside"] = float(z["peak_return"])
            else:
                ep = _px(close, ent, sym); sp = float(z["start_price"]); pp = float(z["peak_price"]); total = pp / sp - 1.0
                z["capture_date"] = ent; z["capture_mode"] = "ENTERED_DURING_RUN"
                if np.isfinite(ep) and ep > 0 and total > 0:
                    z["capture_progress"] = float((ep / sp - 1.0) / total)
                    z["remaining_upside"] = float(pp / ep - 1.0)
        else:
            z.update(generic_diagnosis(sym, start, peak, meta, matrices, peer_ctx, features, variant))
        rows.append(z)
    return pd.DataFrame(rows)


def summary(df: pd.DataFrame) -> dict[str, Any]:
    if df.empty:
        return {"n": 0}
    cap = df["captured"].astype(bool)
    prog = pd.to_numeric(df.loc[cap, "capture_progress"], errors="coerce")
    return {
        "n": int(len(df)),
        "captured_n": int(cap.sum()),
        "hit_rate": float(cap.mean()),
        "prepositioned_n": int((df["capture_mode"] == "PREPOSITIONED").sum()),
        "early_hit_le_33pct": float((prog <= 1/3).mean()) if prog.notna().any() else None,
        "median_capture_progress": float(prog.median()) if prog.notna().any() else None,
        "median_remaining_upside": float(pd.to_numeric(df.loc[cap, "remaining_upside"], errors="coerce").median()) if cap.any() else None,
        "miss_reasons": {str(k): int(v) for k, v in df.loc[~cap, "miss_reason"].value_counts(dropna=False).items()},
    }


def by_period(df: pd.DataFrame, top_n: int | None = None) -> dict[str, Any]:
    z = df.copy()
    if top_n is not None and "rank" in z:
        z = z.loc[pd.to_numeric(z["rank"], errors="coerce") <= top_n]
    return {str(p): summary(g) for p, g in z.groupby("period", sort=True)}


def annual_list(annual: pd.DataFrame) -> dict[str, Any]:
    out = {}
    for p, g in annual.groupby("period", sort=True):
        g = g.sort_values("rank")
        out[str(p)] = [{"rank": int(r["rank"]), "symbol": str(r["symbol"]), "period_return": float(r["period_return"]), "peak_return": float(r["peak_return"]), "mega_liquid": bool(r["mega_liquid"])} for _, r in g.head(20).iterrows()]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="."); ap.add_argument("--output", required=True)
    ap.add_argument("--analysis-start", default="2020-01-02"); ap.add_argument("--analysis-end", default="2026-09-02")
    ap.add_argument("--leader-start", default="2021-01-04"); ap.add_argument("--max-tickers", type=int, default=6000); ap.add_argument("--batch-size", type=int, default=75)
    args = ap.parse_args(); root = Path(args.root); out = root / args.output; out.mkdir(parents=True, exist_ok=True)

    print("BUILD PIT inputs", flush=True)
    meta, matrices = ex.build_inputs_ext(root, args.analysis_start, args.analysis_end, args.max_tickers, args.batch_size)
    peer_ctx = loo.build_leave_one_out_scores(root, matrices); features = cem.build_features(matrices)
    print(f"UNIVERSE downloaded={meta['downloaded']}", flush=True)

    print("FREEZE strategy-independent leader labels before simulations", flush=True)
    annual = lc.build_annual_leaders(matrices, pd.Timestamp(args.leader_start), pd.Timestamp(args.analysis_end))
    rolling = lc.build_rolling_superleaders(matrices, pd.Timestamp(args.leader_start), pd.Timestamp(args.analysis_end))
    freeze = freeze_labels(out, annual, rolling)
    annual.to_csv(out / "annual_leaders_frozen.csv", index=False); rolling.to_csv(out / "rolling_126_leaders_frozen.csv", index=False)
    print(f"LABEL_SHA256 {freeze['sha256']}", flush=True)

    print("BUILD strategy features and simulations", flush=True)
    current = hyb.run_variant(meta, matrices, peer_ctx, features, "CURRENT_BEST", 9, 3, "MILD", 1, 0.0)
    rel.EXT, _ = rel.build_extended_features(root, matrices, features); rel.signal_ok = vd.signal_ok
    vd.PRICE_ACC_PCT = features["ret20_pct"].astype(np.float32)
    vd.PRICE_RATIO20 = (matrices["close"] / matrices["close"].shift(20)).astype(np.float32)
    vd.SHARE_ACC_PCT, vd.SHARE_RATIO20 = fal.build_share_volume_features(matrices, features)
    vd.BANNED_SYMBOLS = set()
    sims = {
        "CURRENT_BEST": (current, None),
        "THREE4_BASE": (vd.run_variant(meta, matrices, peer_ctx, features, "THREE4_BASE", "THREE4", "BASE"), rel.Variant("THREE4_BASE", "THREE4", "BASE")),
        "HT_R_OR_P_BASE": (vd.run_variant(meta, matrices, peer_ctx, features, "HT_R_OR_P_BASE", "HT_R_OR_P", "BASE"), rel.Variant("HT_R_OR_P_BASE", "HT_R_OR_P", "BASE")),
    }

    result = {
        "status": "ANNUAL_LEADER_RELEADERSHIP_CAPTURE_AUDIT",
        "analysis_window": {"start": args.analysis_start, "end": args.analysis_end, "leader_start": args.leader_start, "downloaded": int(meta["downloaded"])},
        "leader_definition": {
            "annual": "Strategy-independent hindsight evaluation label: >=$50M median dollar-volume in first 20 sessions, price >=$5, >=80% session coverage, period return >=40%, top 20 by calendar/YTD return.",
            "primary": "Annual Top10 is primary; Top20 and mega-liquid are supporting views.",
            "rolling": "Independent 126-session superleader label: start liquidity >=$50M, forward MFE >=80%, cross-sectional forward-MFE percentile >=98%, 126-session cooldown.",
            "important": "Leader labels are frozen and hashed before strategy simulations; labels are evaluation-only and never enter a signal or ranking.",
        },
        "freeze": freeze,
        "annual_leader_list": annual_list(annual),
        "strategies": {},
    }

    for name, (sim, variant) in sims.items():
        print(f"ANNOTATE {name}", flush=True)
        ac = annotate(annual, sim, matrices, meta, peer_ctx, features, variant)
        rc = annotate(rolling, sim, matrices, meta, peer_ctx, features, variant)
        ac.to_csv(out / f"annual_capture_{name}.csv", index=False); rc.to_csv(out / f"rolling126_capture_{name}.csv", index=False)
        mega = ac.loc[ac["mega_liquid"].astype(bool)] if not ac.empty else ac
        result["strategies"][name] = {
            "annual_top10_by_year": by_period(ac, 10),
            "annual_top20_by_year": by_period(ac, 20),
            "annual_top10_all": summary(ac.loc[pd.to_numeric(ac["rank"], errors="coerce") <= 10]),
            "annual_top20_all": summary(ac),
            "annual_mega_liquid": summary(mega),
            "rolling126_by_start_year": by_period(rc, None),
            "rolling126_all": summary(rc),
        }

    path = out / "summary_annual_leader_capture.json"
    path.write_text(json.dumps(safe(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== ANNUAL_LEADER_CAPTURE_JSON ===", flush=True)
    print(json.dumps(safe(result), ensure_ascii=False, indent=2), flush=True)
    print("=== END_ANNUAL_LEADER_CAPTURE_JSON ===", flush=True)


if __name__ == "__main__":
    main()
