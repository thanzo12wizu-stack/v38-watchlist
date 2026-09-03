from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf

import audit_ordinary_stock_market_mode_robustness as base
import audit_ordinary_stock_theme_leave_one_out as loo
import audit_ordinary_stock_exit_trail as ex
import audit_ordinary_stock_rebalance_vs_trail as rt
import audit_five_year_leader_capture as lc
import audit_core_emerging_leader_mix as cem

ACTIVE_RULE = "CURRENT_MILD"
EM_RS_FLOOR = 90.0


def pct_rank(frame: pd.DataFrame, mask: pd.DataFrame | None = None) -> pd.DataFrame:
    x = frame.where(mask) if mask is not None else frame
    return x.rank(axis=1, pct=True) * 100.0


def extend_features(matrices: dict[str, pd.DataFrame], features: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    out = dict(features)
    rs63 = matrices["rs63"]
    rs189 = matrices["rs189"]
    dvol = matrices["dvol"]
    elig = matrices["new_eligible"]
    dual = ((rs63 >= 85.0) & (rs189 >= 85.0)).astype(float) * 100.0
    out["dual_persist20"] = dual.rolling(20, min_periods=10).mean()
    out["dual_persist60"] = dual.rolling(60, min_periods=30).mean()
    dvol_pct = out["dvol_pct"]
    out["dvol_med20_pct"] = dvol_pct.rolling(20, min_periods=10).median()
    out["dvol_med60_pct"] = dvol_pct.rolling(60, min_periods=30).median()
    dvol_growth60 = dvol / dvol.shift(60) - 1.0
    out["dvol_growth60_pct"] = pct_rank(dvol_growth60, elig)
    return out


def _val(frame: pd.DataFrame, d: pd.Timestamp, sym: str, default: float = 0.0) -> float:
    try:
        x = float(frame.at[d, sym])
        return x if np.isfinite(x) else default
    except Exception:
        return default


def emerging_score(d, sym, c, matrices, f, rule: str) -> float:
    base_score = float(c.get("rank_score") or c.get("stock_rs189") or 0.0)
    rs63 = _val(matrices["rs63"], d, sym)
    if rule == "CURRENT_MILD":
        return 0.70 * base_score + 0.15 * rs63 + 0.07 * _val(f["rs_acc_pct"], d, sym) + 0.04 * _val(f["ret20_pct"], d, sym) + 0.04 * _val(f["dvol_acc_pct"], d, sym)
    return 0.65 * base_score + 0.10 * rs63 + 0.10 * _val(f["dual_persist20"], d, sym) + 0.05 * _val(f["dual_persist60"], d, sym) + 0.06 * _val(f["dvol_med20_pct"], d, sym) + 0.04 * _val(f["dvol_growth60_pct"], d, sym)


def emerging_pass(d, sym, matrices, f, rule: str) -> bool:
    try:
        if not bool(matrices["new_eligible"].at[d, sym]):
            return False
        if bool(f["core_mask"].at[d, sym]):
            return False
    except Exception:
        return False
    if _val(matrices["rs189"], d, sym) < EM_RS_FLOOR or _val(matrices["rs63"], d, sym) < EM_RS_FLOOR:
        return False
    if rule in {"PERSIST_GATE", "DURABLE_GATE"}:
        if _val(f["dual_persist20"], d, sym) < 40.0 or _val(f["dvol_med20_pct"], d, sym) < 50.0:
            return False
    if rule == "DURABLE_GATE":
        if _val(f["dual_persist60"], d, sym) < 45.0 or _val(f["dvol_med60_pct"], d, sym) < 45.0 or _val(f["dvol_growth60_pct"], d, sym) < 50.0:
            return False
    return True


def refined_classified_candidates(d, matrices, peer_ctx, features, bucket, enhanced):
    cmap = cem.base_candidate_map(d, matrices, peer_ctx, bucket)
    core, emerging = [], []
    for sym, c0 in cmap.items():
        try:
            is_core = bool(features["core_mask"].at[d, sym])
        except Exception:
            is_core = False
        is_em = emerging_pass(d, sym, matrices, features, ACTIVE_RULE)
        if not (is_core or is_em):
            continue
        layer = "CORE" if is_core else "EMERGING"
        c = dict(c0)
        c["layer"] = layer
        c["layer_score"] = float(c.get("rank_score") or c.get("stock_rs189") or 0.0) if layer == "CORE" else emerging_score(d, sym, c, matrices, features, ACTIVE_RULE)
        c["dvol"] = _val(matrices["dvol"], d, sym, np.nan)
        c["dvol_pct"] = _val(features["dvol_pct"], d, sym, np.nan)
        c["rs63"] = _val(matrices["rs63"], d, sym, np.nan)
        c["dual_persist20"] = _val(features["dual_persist20"], d, sym, np.nan)
        c["dual_persist60"] = _val(features["dual_persist60"], d, sym, np.nan)
        c["dvol_med20_pct"] = _val(features["dvol_med20_pct"], d, sym, np.nan)
        c["dvol_med60_pct"] = _val(features["dvol_med60_pct"], d, sym, np.nan)
        c["dvol_growth60_pct"] = _val(features["dvol_growth60_pct"], d, sym, np.nan)
        (core if is_core else emerging).append((sym, c))
    core.sort(key=lambda x: x[1]["layer_score"], reverse=True)
    emerging.sort(key=lambda x: x[1]["layer_score"], reverse=True)
    return core, emerging


def run_variant(meta, matrices, peer_ctx, features, name, rule, core_slots=9, em_slots=3, selective_em=1, cost_bps=0.0):
    global ACTIVE_RULE
    ACTIVE_RULE = rule
    cem.classified_candidates = refined_classified_candidates
    return cem.simulate_layered(meta, matrices, peer_ctx, features, cem.Variant(name, core_slots, em_slots, True, selective_em), cost_bps=cost_bps)


def period_metrics(eq: pd.Series) -> dict[str, Any]:
    return {"2021_plus": base.metrics(eq.loc[eq.index >= "2021-01-04"]), "2022_plus": base.metrics(eq.loc[eq.index >= "2022-01-03"]), "2024_plus": base.metrics(eq.loc[eq.index >= "2024-01-02"])}


def build_durable_graduates(rolling: pd.DataFrame, matrices: dict[str, pd.DataFrame], features: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    close, dvol, dvol_pct = matrices["close"], matrices["dvol"], features["dvol_pct"]
    rows_abs, rows_rel = [], []
    for _, r0 in rolling.iterrows():
        r = dict(r0)
        sym, start, peak = str(r["symbol"]), pd.Timestamp(r["start_date"]), pd.Timestamp(r["peak_date"])
        if sym not in close.columns or start not in close.index or bool(features["core_mask"].at[start, sym]):
            continue
        dates = close.index[(close.index > start) & (close.index <= peak)]
        if len(dates) < 20:
            continue
        dv = pd.to_numeric(dvol.loc[dates, sym], errors="coerce")
        dp = pd.to_numeric(dvol_pct.loc[dates, sym], errors="coerce")
        abs_share = float((dv >= cem.MEGA_DVOL).mean()) if dv.notna().any() else 0.0
        rel_share = float((dp >= 90.0).mean()) if dp.notna().any() else 0.0
        abs_roll, rel_roll = dv.rolling(20, min_periods=15).median(), dp.rolling(20, min_periods=15).median()
        abs_dates, rel_dates = abs_roll.index[abs_roll >= cem.MEGA_DVOL], rel_roll.index[rel_roll >= 90.0]
        r["future_abs_high_liq_share"], r["future_rel_top10_liq_share"] = abs_share, rel_share
        r["abs_graduation_date"] = pd.Timestamp(abs_dates[0]) if len(abs_dates) else pd.NaT
        r["rel_graduation_date"] = pd.Timestamp(rel_dates[0]) if len(rel_dates) else pd.NaT
        if abs_share >= 0.25 and len(abs_dates): rows_abs.append(dict(r))
        if rel_share >= 0.25 and len(rel_dates): rows_rel.append(dict(r))
    return pd.DataFrame(rows_abs), pd.DataFrame(rows_rel)


def capture_before_graduation(frame: pd.DataFrame, sim: dict[str, Any], close: pd.DataFrame, date_col: str) -> pd.DataFrame:
    x = cem.simple_capture(frame, sim["intervals"], close)
    if x.empty: return x
    gd, cd = pd.to_datetime(x[date_col], errors="coerce"), pd.to_datetime(x["capture_date"], errors="coerce")
    x["captured_before_graduation"] = x["captured"].astype(bool) & gd.notna() & cd.notna() & (cd <= gd)
    return x


def summarize_durable(x: pd.DataFrame) -> dict[str, Any]:
    if x.empty: return {"n": 0}
    s = cem.summarize_capture_ext(x)
    s["captured_before_graduation_n"] = int(x["captured_before_graduation"].sum())
    s["captured_before_graduation_rate"] = float(x["captured_before_graduation"].mean())
    return s


def fetch_rate_regime(start: str, end: str, idx: pd.DatetimeIndex) -> pd.Series:
    try:
        z = yf.download("^TNX", start=start, end=str((pd.Timestamp(end) + pd.Timedelta(days=7)).date()), progress=False, auto_adjust=False, threads=False)
        if z is None or len(z) == 0: return pd.Series("UNKNOWN", index=idx)
        c = z["Close"].iloc[:, 0] if isinstance(z.columns, pd.MultiIndex) else z["Close"]
        c.index = pd.DatetimeIndex(c.index).tz_localize(None)
        c = pd.to_numeric(c, errors="coerce").reindex(idx).ffill()
        delta = c - c.shift(63)
        return pd.Series(np.where(delta > 0.25, "RATE_UP", np.where(delta < -0.25, "RATE_DOWN", "RATE_FLAT")), index=idx).where(delta.notna(), "UNKNOWN")
    except Exception:
        return pd.Series("UNKNOWN", index=idx)


def emerging_trade_by_rate(sim: dict[str, Any], rate_regime: pd.Series) -> dict[str, Any]:
    e, t = sim["entries"].copy(), sim["trades"].copy()
    if e.empty or t.empty or "entry_layer" not in e.columns: return {}
    e = e.loc[e["entry_layer"].astype(str) == "EMERGING", ["symbol", "entry_date", "signal_date"]].copy()
    e["entry_date"], e["signal_date"] = pd.to_datetime(e["entry_date"]), pd.to_datetime(e["signal_date"])
    t["entry_date"] = pd.to_datetime(t["entry_date"])
    z = t.merge(e, on=["symbol", "entry_date"], how="inner")
    z["rate_regime"] = [str(rate_regime.get(pd.Timestamp(d), "UNKNOWN")) for d in z["signal_date"]]
    out = {}
    for k, g in z.groupby("rate_regime"):
        r = pd.to_numeric(g["return"], errors="coerce").dropna()
        out[str(k)] = {"n": int(len(r)), "mean_return": float(r.mean()) if len(r) else None, "median_return": float(r.median()) if len(r) else None, "win_rate": float((r > 0).mean()) if len(r) else None}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="."); ap.add_argument("--output", required=True)
    ap.add_argument("--analysis-start", default="2020-01-02"); ap.add_argument("--analysis-end", default="2026-09-02")
    ap.add_argument("--leader-start", default="2021-01-04"); ap.add_argument("--max-tickers", type=int, default=6000); ap.add_argument("--batch-size", type=int, default=75)
    args = ap.parse_args(); root = Path(args.root); out = root / args.output; out.mkdir(parents=True, exist_ok=True)
    end, leader_start = pd.Timestamp(args.analysis_end), pd.Timestamp(args.leader_start)

    print("BUILD shared PIT inputs", flush=True)
    meta, matrices = ex.build_inputs_ext(root, args.analysis_start, args.analysis_end, args.max_tickers, args.batch_size)
    peer_ctx = loo.build_leave_one_out_scores(root, matrices); features = extend_features(matrices, cem.build_features(matrices))
    print(f"UNIVERSE downloaded={meta['downloaded']}", flush=True)

    baseline = lc.simulate_current_with_entries(meta, matrices, peer_ctx, use_theme=True)
    validation = lc.validate_simulation(meta, matrices, peer_ctx, baseline)
    configs = [("CURRENT_BEST_9_3_SEL3_1", "CURRENT_MILD", 9, 3, 1), ("PERSIST_SCORE_9_3_SEL3_1", "PERSIST_SCORE", 9, 3, 1), ("PERSIST_GATE_9_3_SEL3_1", "PERSIST_GATE", 9, 3, 1), ("DURABLE_GATE_9_3_SEL3_1", "DURABLE_GATE", 9, 3, 1), ("PERSIST_SCORE_10_2", "PERSIST_SCORE", 10, 2, 0)]
    sims = {"BASELINE_MIXED12": baseline}
    for name, rule, c, e, se in configs:
        print(f"SIM {name}", flush=True); sims[name] = run_variant(meta, matrices, peer_ctx, features, name, rule, c, e, se, 0.0)

    annual = lc.build_annual_leaders(matrices, leader_start, end); rolling = lc.build_rolling_superleaders(matrices, leader_start, end)
    core_annual = annual.loc[annual["mega_liquid"].astype(bool)].copy(); durable_abs, durable_rel = build_durable_graduates(rolling, matrices, features)
    rate_regime = fetch_rate_regime(args.analysis_start, args.analysis_end, meta["analysis_idx"])

    result: dict[str, Any] = {"status": "EMERGING_DURABILITY_REFINEMENT", "analysis_window": {"start": args.analysis_start, "end": args.analysis_end, "leader_start": args.leader_start, "downloaded": int(meta["downloaded"])}, "baseline_validation": validation, "purpose": "Third-round test. Keep 9 Core + 3 Emerging architecture and current V38 Core ranking; test whether persistence and durable liquidity improve early capture of future sustained large leaders.", "signal_rules": {"current_best": "70% current V38 rank + 15% RS63 + 7% 20d RS acceleration + 4% 20d return + 4% DDV acceleration.", "persist_score": "65% current V38 rank + 10% RS63 + 10% dual-RS 20d persistence + 5% dual-RS 60d persistence + 6% 20d median DDV percentile + 4% 60d DDV-growth percentile.", "persist_gate": "Persist score plus dual-RS20>=40% and 20d median DDV percentile>=50.", "durable_gate": "Persist gate plus dual-RS60>=45%, 60d median DDV percentile>=45, and DDV-growth60 percentile>=50."}, "durable_denominators": {"definition": "Ex-post audit label only: rolling 126-session superleader, starts outside Core, then before peak spends >=25% of sessions above $200M DDV (absolute) or top-10% DDV percentile (relative), and reaches a 20-session median graduation threshold.", "absolute_n": int(len(durable_abs)), "relative_n": int(len(durable_rel))}, "variants": {}, "bootstrap_vs_baseline": {}, "bootstrap_vs_current_best": {}, "cost10bps": {}, "rate_regime_diagnostic": {}, "caveats": ["No future information enters signals; future durable-liquidity labels are audit denominators only.", "Core size is still contemporaneous liquidity-proxy based, not historical market cap.", "Reliable point-in-time quarterly fundamentals are not available across the full 3,000+ name history, so current fundamentals are deliberately not backfilled into past signals.", "Theme taxonomy can contain classification look-ahead even though strict leave-one-out removes self-influence.", "Yahoo OHLCV/universe survivorship and delisting coverage can under-represent historical delisted names.", "Rate regime is a diagnostic only and is not used as a trading gate."]}

    durable_caps = {}
    for name, sim in sims.items():
        cap_ann = cem.simple_capture(annual, sim["intervals"], matrices["close"]); cap_core = cem.simple_capture(core_annual, sim["intervals"], matrices["close"])
        cap_abs = capture_before_graduation(durable_abs, sim, matrices["close"], "abs_graduation_date"); cap_rel = capture_before_graduation(durable_rel, sim, matrices["close"], "rel_graduation_date")
        durable_caps[name] = {"abs": cap_abs, "rel": cap_rel}; ent = sim["entries"]; mix = {}
        if not ent.empty and "entry_layer" in ent.columns: mix = {str(k): int(v) for k, v in ent["entry_layer"].value_counts().items()}
        result["variants"][name] = {"metrics": base.slice_metrics(sim["equity"]), "period_metrics": period_metrics(sim["equity"]), "trade_stats": rt.trade_stats(sim["trades"]), "entries": int(len(ent)), "entry_layer_mix": mix, "capture": {"annual": cem.summarize_capture_ext(cap_ann), "core_annual": cem.summarize_capture_ext(cap_core), "durable_abs": summarize_durable(cap_abs), "durable_rel": summarize_durable(cap_rel)}}
        result["rate_regime_diagnostic"][name] = emerging_trade_by_rate(sim, rate_regime)
        sim["equity"].rename("equity").to_csv(out / f"equity_{name}.csv"); sim["entries"].to_csv(out / f"entries_{name}.csv", index=False); sim["trades"].to_csv(out / f"trades_{name}.csv", index=False); cap_abs.to_csv(out / f"capture_durable_abs_{name}.csv", index=False); cap_rel.to_csv(out / f"capture_durable_rel_{name}.csv", index=False)

    b, cb = sims["BASELINE_MIXED12"]["equity"], sims["CURRENT_BEST_9_3_SEL3_1"]["equity"]
    for i, (name, sim) in enumerate(sims.items()):
        if name != "BASELINE_MIXED12": result["bootstrap_vs_baseline"][name] = base.bootstrap_block_win(sim["equity"], b, block=20, reps=5000, seed=52000+i)
        if name not in {"BASELINE_MIXED12", "CURRENT_BEST_9_3_SEL3_1"}: result["bootstrap_vs_current_best"][name] = base.bootstrap_block_win(sim["equity"], cb, block=20, reps=5000, seed=62000+i)

    for name, rule, c, e, se in configs:
        if name not in {"PERSIST_SCORE_9_3_SEL3_1", "PERSIST_GATE_9_3_SEL3_1", "DURABLE_GATE_9_3_SEL3_1"}: continue
        print(f"SIM_COST10 {name}", flush=True); sc = run_variant(meta, matrices, peer_ctx, features, name+"_COST10", rule, c, e, se, cem.TCOST_BPS)
        result["cost10bps"][name] = {"period_metrics": period_metrics(sc["equity"]), "full": base.metrics(sc["equity"]), "full_cagr_drag": float(base.metrics(sc["equity"])["cagr"] - base.metrics(sims[name]["equity"])["cagr"])}

    names = {"NVDA", "PLTR", "SMCI", "APP", "VRT", "VST", "CRWD", "HOOD", "MU", "MSTR", "SNDK"}; named_rows = []
    for bench, frame in [("DURABLE_ABS", durable_abs), ("DURABLE_REL", durable_rel)]:
        if frame.empty: continue
        for _, r in frame.loc[frame["symbol"].astype(str).isin(names)].iterrows():
            for vname, caps in durable_caps.items():
                cf = caps["abs" if bench == "DURABLE_ABS" else "rel"]
                m = cf.loc[(cf["symbol"].astype(str) == str(r["symbol"])) & (pd.to_datetime(cf["start_date"]) == pd.Timestamp(r["start_date"]))]
                if m.empty: continue
                x = m.iloc[0]; named_rows.append({"benchmark": bench, "variant": vname, "symbol": r["symbol"], "start_date": r["start_date"], "peak_date": r["peak_date"], "peak_return": r["peak_return"], "captured": x["captured"], "capture_date": x["capture_date"], "captured_before_graduation": x["captured_before_graduation"], "capture_progress": x["capture_progress"]})
    pd.DataFrame(named_rows).to_csv(out / "named_durable_leader_audit.csv", index=False); durable_abs.to_csv(out / "denominator_durable_abs.csv", index=False); durable_rel.to_csv(out / "denominator_durable_rel.csv", index=False)
    (out / "summary_emerging_durability_refinement.json").write_text(json.dumps(base.safe(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== EMERGING_DURABILITY_REFINEMENT_JSON ===", flush=True); print(json.dumps(base.safe(result), ensure_ascii=False, indent=2), flush=True); print("=== END_EMERGING_DURABILITY_REFINEMENT_JSON ===", flush=True)


if __name__ == "__main__": main()
