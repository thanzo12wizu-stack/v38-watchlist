from __future__ import annotations

import argparse
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

CORE_DVOL_ABS = 100_000_000.0
CORE_DVOL_PCT = 85.0
MEGA_DVOL = 200_000_000.0
SELECTIVE_TOTAL = 4
EMERGING_RS_FLOOR = 90.0
TCOST_BPS = 10.0


@dataclass(frozen=True)
class Variant:
    name: str
    core_slots: int
    emerging_slots: int
    enhanced_scores: bool
    selective_emerging_slots: int


VARIANTS = (
    Variant("CE_PLAIN_10_2", 10, 2, False, 0),
    Variant("CE_PLAIN_9_3", 9, 3, False, 0),
    Variant("CE_ACCEL_10_2", 10, 2, True, 0),
    Variant("CE_ACCEL_9_3", 9, 3, True, 0),
    Variant("CE_ACCEL_8_4", 8, 4, True, 0),
    Variant("CE_ACCEL_9_3_SEL3_1", 9, 3, True, 1),
)


def safe(v: Any) -> Any:
    return base.safe(v)


def px(frame: pd.DataFrame, date: pd.Timestamp, sym: str, fallback: float | None = None) -> float | None:
    try:
        x = float(frame.at[date, sym])
        if np.isfinite(x) and x > 0:
            return x
    except Exception:
        pass
    return fallback


def build_features(matrices: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    close = matrices["close"]
    dvol = matrices["dvol"]
    elig = matrices["new_eligible"]
    rs63 = matrices["rs63"]
    rs189 = matrices["rs189"]

    dvol_pct = dvol.where(dvol.notna()).rank(axis=1, pct=True) * 100.0
    rs_acc20 = rs63 - rs63.shift(20)
    rs_acc_pct = rs_acc20.where(elig).rank(axis=1, pct=True) * 100.0
    ret20 = close / close.shift(20) - 1.0
    ret20_pct = ret20.where(elig).rank(axis=1, pct=True) * 100.0
    dvol_acc20 = dvol / dvol.shift(20) - 1.0
    dvol_acc_pct = dvol_acc20.where(elig).rank(axis=1, pct=True) * 100.0

    core_mask = elig & ((dvol >= CORE_DVOL_ABS) | (dvol_pct >= CORE_DVOL_PCT))
    emerging_mask = elig & ~core_mask & (rs189 >= EMERGING_RS_FLOOR) & (rs63 >= EMERGING_RS_FLOOR)
    return {
        "dvol_pct": dvol_pct,
        "rs_acc20": rs_acc20,
        "rs_acc_pct": rs_acc_pct,
        "ret20_pct": ret20_pct,
        "dvol_acc_pct": dvol_acc_pct,
        "core_mask": core_mask,
        "emerging_mask": emerging_mask,
    }


def base_candidate_map(d, matrices, peer_ctx, bucket):
    n = min(300, matrices["close"].shape[1])
    if bucket == 1:
        elig = matrices["new_eligible"].loc[d]
        rs = matrices["rs189"].loc[d].where(elig).dropna().nlargest(n)
        return {str(sym): {"stock_rs189": float(v), "peer_theme_score": None, "rank_score": float(v)} for sym, v in rs.items()}
    return {str(sym): dict(c) for sym, c in loo.peer_ranked_candidates(d, matrices, peer_ctx, n)}


def layer_score(d, sym, c, layer, matrices, features, enhanced):
    base_score = float(c.get("rank_score") or c.get("stock_rs189") or 0.0)
    if not enhanced:
        return base_score
    rs63 = float(matrices["rs63"].at[d, sym]) if pd.notna(matrices["rs63"].at[d, sym]) else 0.0
    if layer == "CORE":
        dvol_pct = float(features["dvol_pct"].at[d, sym]) if pd.notna(features["dvol_pct"].at[d, sym]) else 0.0
        return 0.60 * base_score + 0.25 * rs63 + 0.15 * dvol_pct
    acc = float(features["rs_acc_pct"].at[d, sym]) if pd.notna(features["rs_acc_pct"].at[d, sym]) else 0.0
    ret20 = float(features["ret20_pct"].at[d, sym]) if pd.notna(features["ret20_pct"].at[d, sym]) else 0.0
    dvacc = float(features["dvol_acc_pct"].at[d, sym]) if pd.notna(features["dvol_acc_pct"].at[d, sym]) else 0.0
    return 0.50 * base_score + 0.20 * rs63 + 0.15 * acc + 0.10 * ret20 + 0.05 * dvacc


def classified_candidates(d, matrices, peer_ctx, features, bucket, enhanced):
    cmap = base_candidate_map(d, matrices, peer_ctx, bucket)
    core, emerging = [], []
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
        c["layer"] = layer
        c["layer_score"] = layer_score(d, sym, c, layer, matrices, features, enhanced)
        c["dvol"] = float(matrices["dvol"].at[d, sym]) if pd.notna(matrices["dvol"].at[d, sym]) else np.nan
        c["dvol_pct"] = float(features["dvol_pct"].at[d, sym]) if pd.notna(features["dvol_pct"].at[d, sym]) else np.nan
        c["rs63"] = float(matrices["rs63"].at[d, sym]) if pd.notna(matrices["rs63"].at[d, sym]) else np.nan
        c["rs_acc20"] = float(features["rs_acc20"].at[d, sym]) if pd.notna(features["rs_acc20"].at[d, sym]) else np.nan
        (core if is_core else emerging).append((sym, c))
    core.sort(key=lambda x: x[1]["layer_score"], reverse=True)
    emerging.sort(key=lambda x: x[1]["layer_score"], reverse=True)
    return core, emerging


def current_layer(d, sym, features):
    try:
        if bool(features["core_mask"].at[d, sym]):
            return "CORE"
    except Exception:
        pass
    return "EMERGING"


def simulate_layered(meta, matrices, peer_ctx, features, variant: Variant, cost_bps: float = 0.0):
    idx = meta["analysis_idx"]
    opens, closes = matrices["open"], matrices["close"]
    breadth, nq = meta["breadth"], meta["nq"]
    cost = float(cost_bps) / 10000.0
    cash = 1.0
    pos = {}
    equities, trades, entries, intervals = [], [], [], []
    red_run = 0

    def close_position(sym, date, price, reason):
        nonlocal cash
        p = pos.pop(sym)
        cash += p["shares"] * price * (1.0 - cost)
        rec = {
            "variant": variant.name, "symbol": sym, "entry_date": p["entry_date"], "exit_date": date,
            "entry_price": p["entry_price"], "exit_price": price, "return": price / p["entry_price"] - 1.0,
            "exit_reason": reason, "entry_bucket": p["entry_bucket"], "entry_layer": p.get("entry_layer"),
            "entry_layer_score": p.get("entry_layer_score"), "stock_rs189": p.get("stock_rs189"),
            "peer_theme_score": p.get("peer_theme_score"), "partial_done": p.get("partial_done", False),
        }
        trades.append(rec)
        intervals.append(dict(rec))

    for i, d0 in enumerate(idx):
        d = pd.Timestamp(d0)
        prev = None if i == 0 else pd.Timestamp(idx[i - 1])
        if prev is not None:
            color = str(nq.at[prev, "nq_color"]) if prev in nq.index and pd.notna(nq.at[prev, "nq_color"]) else ""
            red_run = red_run + 1 if color == "Red" else 0
            red_force = color == "Red" and red_run >= 1

            if red_force:
                for sym in list(pos):
                    opx = px(opens, d, sym, px(closes, prev, sym, pos[sym]["entry_price"]))
                    if opx is not None:
                        close_position(sym, d, opx, "RED")
            else:
                for sym in list(pos):
                    p = pos[sym]
                    pc = px(closes, prev, sym, p["entry_price"])
                    if pc is None:
                        continue
                    p["sessions"] += 1
                    if (not p["partial_done"]) and pc >= p["entry_price"] * 1.24:
                        opx = px(opens, d, sym, pc)
                        if opx is not None:
                            sold = p["shares"] * 0.25
                            cash += sold * opx * (1.0 - cost)
                            p["shares"] -= sold
                            p["partial_done"] = True
                    stop, reason = p["entry_price"] * 0.92, "HARD8"
                    peak_stop = p["peak_close"] * 0.70
                    if peak_stop > stop:
                        stop, reason = peak_stop, "PEAK30"
                    if pc <= stop:
                        opx = px(opens, d, sym, pc)
                        if opx is not None:
                            close_position(sym, d, opx, reason)

            b = float(breadth.loc[prev]) if prev in breadth.index and pd.notna(breadth.loc[prev]) else np.nan
            bucket = base.breadth_bucket(b)
            bull = color in ("Blue", "Green")
            total_cap = base.N_PORT if bull and bucket == 2 else SELECTIVE_TOTAL if bull and bucket == 1 else 0

            if (not red_force) and total_cap > 0 and len(pos) < total_cap:
                if bucket == 2:
                    core_cap, em_cap = variant.core_slots, variant.emerging_slots
                else:
                    em_cap = min(variant.selective_emerging_slots, SELECTIVE_TOTAL)
                    core_cap = SELECTIVE_TOTAL - em_cap
                core_cands, em_cands = classified_candidates(prev, matrices, peer_ctx, features, bucket, variant.enhanced_scores)

                nav_open = cash
                for sym, p in pos.items():
                    opx = px(opens, d, sym, px(closes, prev, sym, p["entry_price"]))
                    if opx is not None:
                        nav_open += p["shares"] * opx
                slot_cash = nav_open / base.N_PORT

                def counts():
                    c = sum(1 for s in pos if current_layer(prev, s, features) == "CORE")
                    return c, len(pos) - c

                def add_from(cands, layer, target):
                    nonlocal cash
                    for sym, c in cands:
                        if len(pos) >= total_cap or cash <= 1e-12:
                            break
                        core_n, em_n = counts()
                        layer_n = core_n if layer == "CORE" else em_n
                        if layer_n >= target:
                            break
                        if sym in pos:
                            continue
                        opx = px(opens, d, sym, px(closes, prev, sym, None))
                        if opx is None:
                            continue
                        alloc = min(slot_cash, cash)
                        if alloc <= 1e-10:
                            break
                        cash -= alloc
                        investable = alloc * (1.0 - cost)
                        pos[sym] = {
                            "shares": investable / opx, "entry_price": opx, "entry_date": d, "peak_close": opx,
                            "entry_bucket": bucket, "sessions": 0, "partial_done": False, "entry_layer": layer,
                            "entry_layer_score": c["layer_score"], **c,
                        }
                        entries.append({
                            "variant": variant.name, "symbol": sym, "signal_date": prev, "entry_date": d,
                            "entry_price": opx, "entry_bucket": bucket, "entry_layer": layer, **c,
                        })

                add_from(core_cands, "CORE", core_cap)
                add_from(em_cands, "EMERGING", em_cap)

                if len(pos) < total_cap:
                    combined = sorted(core_cands + em_cands, key=lambda x: x[1]["layer_score"], reverse=True)
                    for sym, c in combined:
                        if len(pos) >= total_cap or cash <= 1e-12:
                            break
                        if sym in pos:
                            continue
                        opx = px(opens, d, sym, px(closes, prev, sym, None))
                        if opx is None:
                            continue
                        alloc = min(slot_cash, cash)
                        if alloc <= 1e-10:
                            break
                        cash -= alloc
                        investable = alloc * (1.0 - cost)
                        layer = str(c["layer"])
                        pos[sym] = {
                            "shares": investable / opx, "entry_price": opx, "entry_date": d, "peak_close": opx,
                            "entry_bucket": bucket, "sessions": 0, "partial_done": False, "entry_layer": layer,
                            "entry_layer_score": c["layer_score"], **c,
                        }
                        entries.append({
                            "variant": variant.name, "symbol": sym, "signal_date": prev, "entry_date": d,
                            "entry_price": opx, "entry_bucket": bucket, "entry_layer": layer, **c,
                        })

        nav = cash
        for sym, p in pos.items():
            cp = px(closes, d, sym, px(opens, d, sym, p["entry_price"]))
            if cp is None:
                cp = p["entry_price"]
            p["peak_close"] = max(p["peak_close"], cp)
            nav += p["shares"] * cp
        equities.append((d, nav))

    for sym, p in pos.items():
        intervals.append({
            "variant": variant.name, "symbol": sym, "entry_date": p["entry_date"], "exit_date": pd.NaT,
            "entry_price": p["entry_price"], "exit_price": np.nan, "return": np.nan, "exit_reason": "OPEN",
            "entry_bucket": p["entry_bucket"], "entry_layer": p.get("entry_layer"),
            "entry_layer_score": p.get("entry_layer_score"), "stock_rs189": p.get("stock_rs189"),
            "peer_theme_score": p.get("peer_theme_score"), "partial_done": p.get("partial_done", False),
        })

    eq = pd.Series(dict(equities), dtype=float).sort_index()
    tdf, edf = pd.DataFrame(trades), pd.DataFrame(entries)
    return {
        "equity": eq, "metrics": base.slice_metrics(eq), "rolling_252": base.rolling_252_stats(eq),
        "trades": tdf, "entries": edf, "intervals": pd.DataFrame(intervals), "trade_stats": rt.trade_stats(tdf),
    }


def simple_capture(leaders, intervals, close):
    rows = []
    for _, r0 in leaders.iterrows():
        r = dict(r0)
        sym = str(r["symbol"])
        start, peak = pd.Timestamp(r["start_date"]), pd.Timestamp(r["peak_date"])
        z = lc.find_overlap(intervals, sym, start, peak)
        captured = not z.empty
        r.update({
            "captured": bool(captured), "capture_date": pd.NaT, "capture_mode": "MISSED",
            "capture_progress": np.nan, "remaining_upside_ratio": np.nan, "remaining_upside": np.nan,
            "miss_reason": "NOT_HELD",
        })
        if captured:
            ent = pd.Timestamp(z.iloc[0]["entry_date"])
            if ent <= start:
                r.update({
                    "capture_date": start, "capture_mode": "PREPOSITIONED", "capture_progress": 0.0,
                    "remaining_upside_ratio": 1.0, "remaining_upside": float(r["peak_return"]), "miss_reason": None,
                })
            else:
                ep = px(close, ent, sym, None)
                sp, pp = float(r["start_price"]), float(r["peak_price"])
                total = pp / sp - 1.0
                r["capture_date"], r["capture_mode"], r["miss_reason"] = ent, "ENTERED_DURING_RUN", None
                if ep is not None and total > 0:
                    rem = pp / ep - 1.0
                    r["capture_progress"] = (ep / sp - 1.0) / total
                    r["remaining_upside"], r["remaining_upside_ratio"] = rem, rem / total
        rows.append(r)
    return pd.DataFrame(rows)


def summarize_capture_ext(df):
    x = lc.summarize_capture(df)
    if df.empty:
        return x
    w = pd.to_numeric(df["peak_return"], errors="coerce").clip(lower=0).fillna(0.0)
    cap = df["captured"].astype(bool)
    x["upside_weighted_hit_rate"] = float(w[cap].sum() / w.sum()) if float(w.sum()) > 0 else None
    return x


def build_emerging_graduates(rolling, matrices, features):
    if rolling.empty:
        return rolling.copy(), rolling.copy()
    abs_rows, rel_rows = [], []
    dvol, dvol_pct = matrices["dvol"], features["dvol_pct"]
    for _, r0 in rolling.iterrows():
        r = dict(r0)
        sym = str(r["symbol"])
        start, peak = pd.Timestamp(r["start_date"]), pd.Timestamp(r["peak_date"])
        if sym not in dvol.columns or start not in dvol.index:
            continue
        start_dv = float(dvol.at[start, sym]) if pd.notna(dvol.at[start, sym]) else np.nan
        start_pct = float(dvol_pct.at[start, sym]) if pd.notna(dvol_pct.at[start, sym]) else np.nan
        win_dv = pd.to_numeric(dvol.loc[(dvol.index >= start) & (dvol.index <= peak), sym], errors="coerce")
        win_pct = pd.to_numeric(dvol_pct.loc[(dvol_pct.index >= start) & (dvol_pct.index <= peak), sym], errors="coerce")
        future_dv = float(win_dv.max()) if win_dv.notna().any() else np.nan
        future_pct = float(win_pct.max()) if win_pct.notna().any() else np.nan
        r.update({"start_dvol": start_dv, "max_dvol_to_peak": future_dv, "start_dvol_pct": start_pct, "max_dvol_pct_to_peak": future_pct})
        if np.isfinite(start_dv) and base.DVOL_FLOOR <= start_dv < MEGA_DVOL and np.isfinite(future_dv) and future_dv >= MEGA_DVOL:
            abs_rows.append(dict(r))
        if np.isfinite(start_pct) and start_pct < 85.0 and np.isfinite(future_pct) and future_pct >= 90.0:
            rel_rows.append(dict(r))
    return pd.DataFrame(abs_rows), pd.DataFrame(rel_rows)


def named_audit(frames, entries):
    names = {"NVDA", "PLTR", "AVGO", "META", "SMCI", "APP", "VST", "SNDK", "MU", "ANET", "VRT", "CRWD", "PANW", "MSTR", "HOOD"}
    rows = []
    for variant, frame in frames.items():
        if frame.empty:
            continue
        for _, r in frame.loc[frame["symbol"].astype(str).isin(names)].iterrows():
            rows.append({
                "variant": variant, "benchmark": r.get("leader_type"), "period": r.get("period"), "symbol": r.get("symbol"),
                "start_date": r.get("start_date"), "peak_date": r.get("peak_date"), "peak_return": r.get("peak_return"),
                "captured": r.get("captured"), "capture_date": r.get("capture_date"), "capture_progress": r.get("capture_progress"),
                "remaining_upside_ratio": r.get("remaining_upside_ratio"),
            })
    for variant, edf in entries.items():
        if edf.empty:
            continue
        z = edf.loc[edf["symbol"].astype(str).isin(names)].copy().sort_values("entry_date")
        for sym, g in z.groupby("symbol"):
            r = g.iloc[0]
            rows.append({
                "variant": variant, "benchmark": "FIRST_ACTUAL_ENTRY", "period": str(pd.Timestamp(r["entry_date"]).year),
                "symbol": sym, "start_date": pd.NaT, "peak_date": pd.NaT, "peak_return": np.nan,
                "captured": True, "capture_date": r["entry_date"], "capture_progress": np.nan, "remaining_upside_ratio": np.nan,
            })
    return pd.DataFrame(rows)


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
    analysis_end, leader_start = pd.Timestamp(args.analysis_end), pd.Timestamp(args.leader_start)

    print("BUILD shared current-V38 PIT inputs", flush=True)
    meta, matrices = ex.build_inputs_ext(root, args.analysis_start, args.analysis_end, args.max_tickers, args.batch_size)
    peer_ctx = loo.build_leave_one_out_scores(root, matrices)
    features = build_features(matrices)
    print(f"UNIVERSE selected={meta['selected']} downloaded={meta['downloaded']}", flush=True)

    print("SIM baseline current mixed-12", flush=True)
    baseline = lc.simulate_current_with_entries(meta, matrices, peer_ctx, use_theme=True)
    validation = lc.validate_simulation(meta, matrices, peer_ctx, baseline)
    baseline["metrics"] = base.slice_metrics(baseline["equity"])
    baseline["trade_stats"] = rt.trade_stats(baseline["trades"])

    sims = {"BASELINE_MIXED12": baseline}
    for v in VARIANTS:
        print(f"SIM {v.name}", flush=True)
        sims[v.name] = simulate_layered(meta, matrices, peer_ctx, features, v, cost_bps=0.0)

    friction_sims = {}
    for v in [x for x in VARIANTS if x.name in {"CE_ACCEL_10_2", "CE_ACCEL_9_3", "CE_ACCEL_8_4"}]:
        print(f"SIM_COST10 {v.name}", flush=True)
        friction_sims[v.name] = simulate_layered(meta, matrices, peer_ctx, features, v, cost_bps=TCOST_BPS)

    print("BUILD ex-post leader denominators", flush=True)
    annual = lc.build_annual_leaders(matrices, leader_start, analysis_end)
    rolling = lc.build_rolling_superleaders(matrices, leader_start, analysis_end)
    core_annual = annual.loc[annual["mega_liquid"].astype(bool)].copy()
    core_rolling = rolling.loc[pd.to_numeric(rolling["early_dvol"], errors="coerce") >= MEGA_DVOL].copy()
    em_abs, em_rel = build_emerging_graduates(rolling, matrices, features)

    captures, named_frames = {}, {}
    for name, sim in sims.items():
        intervals = sim["intervals"]
        def cap(frame):
            return simple_capture(frame, intervals, matrices["close"])
        captures[name] = {
            "annual": cap(annual), "core_annual": cap(core_annual), "rolling": cap(rolling),
            "core_rolling": cap(core_rolling), "emerging_abs": cap(em_abs), "emerging_rel": cap(em_rel),
        }
        named_frames[name] = captures[name]["rolling"]

    result = {
        "status": "CORE_EMERGING_LEADER_MIX_AUDIT",
        "analysis_window": {"analysis_start": args.analysis_start, "analysis_end": args.analysis_end, "leader_start": args.leader_start, "downloaded_stocks": int(meta["downloaded"])},
        "baseline_validation": validation,
        "design": {
            "unchanged": [
                "Market Mode / NQSAR / all-stock 50MA breadth",
                "Price/DDV/trend/RS eligibility and structural biotech exclusion",
                "strict leave-one-out Theme score in ATTACK and Stock RS189 in SELECTIVE",
                "signal-at-close / execute-next-open",
                "-8% close stop, +24% first 25% partial, Peak Close -30% trail, Red next-open exit",
                "no forced trim when ATTACK falls to SELECTIVE",
            ],
            "core_proxy": f"eligible and (20d-average dollar volume >= ${CORE_DVOL_ABS:,.0f} OR cross-sectional dollar-volume percentile >= {CORE_DVOL_PCT:.0f})",
            "emerging_proxy": f"eligible, not Core, RS189>= {EMERGING_RS_FLOOR:.0f}, RS63>= {EMERGING_RS_FLOOR:.0f}",
            "enhanced_core_score": "60% current V38 rank + 25% RS63 + 15% DDV percentile",
            "enhanced_emerging_score": "50% current V38 rank + 20% RS63 + 15% 20d RS63 acceleration percentile + 10% 20d return percentile + 5% DDV acceleration percentile",
            "capacity": "layer targets gate only new entries; existing positions are never force-trimmed; unused layer capacity may spill after both layers had the opportunity to fill",
            "selective_default": "4 Core / 0 Emerging; one robustness variant tests 3 Core / 1 Emerging",
        },
        "leader_denominators": {
            "annual_liquid": int(len(annual)), "core_annual_mega_liquid": int(len(core_annual)), "rolling126_superleaders": int(len(rolling)),
            "core_rolling_mega_liquid": int(len(core_rolling)), "emerging_to_mega_abs": int(len(em_abs)),
            "emerging_to_top_liquidity_relative": int(len(em_rel)),
            "note": "Core/Emerging size is proxied by contemporaneous liquidity, not historical market cap; no current market-cap look-ahead is used.",
        },
        "variants": {}, "bootstrap_vs_baseline": {}, "friction_10bps_each_side": {},
        "caveats": [
            "Leader labels are ex-post audit denominators only; no future data enters signals.",
            "Historical market cap/share-count series are not used because coverage is not sufficiently reliable across the full universe; dollar-volume scale is the size/market-leadership proxy.",
            "Theme taxonomy is the research-branch taxonomy and can contain classification look-ahead; strict leave-one-out prevents self-influence but does not fully remove taxonomy look-ahead.",
            "Yahoo OHLCV/universe survivorship and delisting coverage can under-represent historical delisted stocks.",
            "Transaction-cost sensitivity uses 10 bps on each buy/sell cash flow; taxes and slippage beyond that are not modeled.",
        ],
    }

    for name, sim in sims.items():
        caps, ent = captures[name], sim["entries"]
        layer_mix = {}
        if not ent.empty and "entry_layer" in ent.columns:
            layer_mix = {str(k): int(v) for k, v in ent["entry_layer"].value_counts().items()}
        result["variants"][name] = {
            "metrics": base.slice_metrics(sim["equity"]), "trade_stats": rt.trade_stats(sim["trades"]),
            "entries": int(len(ent)), "entry_layer_mix": layer_mix,
            "capture": {k: summarize_capture_ext(v) for k, v in caps.items()},
        }
        sim["equity"].rename("equity").to_csv(out / f"equity_{name}.csv")
        sim["entries"].to_csv(out / f"entries_{name}.csv", index=False)
        sim["trades"].to_csv(out / f"trades_{name}.csv", index=False)
        for k, frame in caps.items():
            frame.to_csv(out / f"capture_{k}_{name}.csv", index=False)

    b_eq = sims["BASELINE_MIXED12"]["equity"]
    for name, sim in sims.items():
        if name == "BASELINE_MIXED12":
            continue
        result["bootstrap_vs_baseline"][name] = base.bootstrap_block_win(sim["equity"], b_eq, block=20, reps=4000, seed=20260903 + list(sims).index(name))

    for name, simc in friction_sims.items():
        z = sims[name]
        result["friction_10bps_each_side"][name] = {
            "metrics": base.slice_metrics(simc["equity"]),
            "full_cagr_drag": float(base.metrics(simc["equity"])["cagr"] - base.metrics(z["equity"])["cagr"]),
        }
        simc["equity"].rename("equity").to_csv(out / f"equity_cost10bps_{name}.csv")

    annual.to_csv(out / "leader_denominator_annual.csv", index=False)
    rolling.to_csv(out / "leader_denominator_rolling126.csv", index=False)
    core_annual.to_csv(out / "leader_denominator_core_annual.csv", index=False)
    core_rolling.to_csv(out / "leader_denominator_core_rolling126.csv", index=False)
    em_abs.to_csv(out / "leader_denominator_emerging_abs.csv", index=False)
    em_rel.to_csv(out / "leader_denominator_emerging_relative.csv", index=False)
    named_audit(named_frames, {k: v["entries"] for k, v in sims.items()}).to_csv(out / "named_leader_audit.csv", index=False)

    (out / "summary_core_emerging_leader_mix.json").write_text(json.dumps(safe(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== CORE_EMERGING_LEADER_MIX_JSON ===", flush=True)
    print(json.dumps(safe(result), ensure_ascii=False, indent=2), flush=True)
    print("=== END_CORE_EMERGING_LEADER_MIX_JSON ===", flush=True)


if __name__ == "__main__":
    main()
