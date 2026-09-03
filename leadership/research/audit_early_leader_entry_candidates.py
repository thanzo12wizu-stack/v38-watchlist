from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import audit_major_leader_entry_delay as delay
import audit_ordinary_stock_market_mode_robustness as base
import audit_ordinary_stock_theme_leave_one_out as loo
import audit_ordinary_stock_exit_trail as ex

VARIANTS = (
    "CORE12",
    "CORE9_ONLY",
    "EARLY_RS21",
    "EARLY_ACCEL",
    "EARLY_PIONEER",
    "EARLY_TIGHT_BREAK",
    "EARLY_PIONEER_THEME",
)
EARLY_VARIANTS = tuple(v for v in VARIANTS if v.startswith("EARLY_"))


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


def build_features(root: Path, matrices: dict[str, pd.DataFrame], peer_ctx: dict[str, Any]) -> dict[str, Any]:
    close = matrices["close"]
    high = matrices["high"]
    pool = delay.current_base_pool(root, matrices)
    rs = delay.rs_matrices(close, pool)

    ema21 = close.ewm(span=21, adjust=False, min_periods=15).mean()
    accel20 = rs[21] - rs[21].shift(20)
    accel_pct = accel20.where(pool).rank(axis=1, pct=True, method="average") * 100.0
    near_high63 = close / high.rolling(63, min_periods=40).max() - 1.0

    prior20 = high.shift(1).rolling(20, min_periods=15).max()
    prior50 = high.shift(1).rolling(50, min_periods=35).max()
    dist20 = close / prior20 - 1.0
    dist50 = close / prior50 - 1.0
    watch20 = dist20.between(-0.015, 0.0, inclusive="left")
    watch50 = dist50.between(-0.015, 0.0, inclusive="left")
    recent20 = dist20.between(0.0, 0.04, inclusive="both")
    recent50 = dist50.between(0.0, 0.04, inclusive="both")
    breakout_context = watch20 | watch50 | recent20 | recent50
    extended = (dist20 > 0.08) & (dist50 > 0.08)

    breakout_score = pd.DataFrame(45.0, index=close.index, columns=close.columns, dtype=np.float32)
    breakout_score = breakout_score.mask(watch20 | watch50, 78.0)
    breakout_score = breakout_score.mask(recent20 | recent50, 90.0)
    breakout_score = breakout_score.mask((dist20 >= 0.0) & (dist50 >= 0.0) & ((dist20 <= 0.02) | (dist50 <= 0.02)), 100.0)
    breakout_score = breakout_score.mask(extended, 30.0)

    # Existing strict leave-one-out Theme score, aligned to the stock matrix.
    peer = pd.DataFrame(
        peer_ctx["best_score"], index=close.index, columns=close.columns, dtype=np.float32
    )

    return {
        "pool": pool,
        "rs": rs,
        "ema21": ema21,
        "accel20": accel20,
        "accel_pct": accel_pct,
        "near_high63": near_high63,
        "breakout_context": breakout_context,
        "extended": extended,
        "breakout_score": breakout_score,
        "peer_theme": peer,
    }


def early_score_elig(variant: str, matrices: dict[str, pd.DataFrame], f: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    close = matrices["close"]
    sma50 = matrices["sma50"]
    pool = f["pool"]
    rs21, rs42, rs63 = f["rs"][21], f["rs"][42], f["rs"][63]
    accel20, accel_pct = f["accel20"], f["accel_pct"]
    ema21 = f["ema21"]
    near_high = f["near_high63"]
    bo_ctx, extended, bo_score = f["breakout_context"], f["extended"], f["breakout_score"]
    peer = f["peer_theme"]

    ema_trend = ema21.notna() & (close >= ema21)
    sma50_trend = sma50.notna() & (close >= sma50 * 0.99)

    if variant == "EARLY_RS21":
        elig = pool & ema_trend & (rs21 >= 90.0)
        score = rs21
    elif variant == "EARLY_ACCEL":
        elig = pool & ema_trend & (rs21 >= 85.0) & (rs63 >= 60.0) & (accel20 >= 5.0)
        score = 0.50 * rs21 + 0.25 * rs42.fillna(50.0) + 0.25 * accel_pct.fillna(50.0)
    elif variant == "EARLY_PIONEER":
        ignition = bo_ctx | ((rs21 >= 93.0) & (accel20 >= 7.0))
        elig = (
            pool & ema_trend & (rs21 >= 88.0) & (rs63 >= 72.0) & (accel20 >= 5.0)
            & (near_high >= -0.20) & ignition & ~extended
        )
        score = (
            0.38 * rs21 + 0.17 * rs63 + 0.20 * accel_pct.fillna(50.0)
            + 0.25 * bo_score
        )
    elif variant == "EARLY_TIGHT_BREAK":
        elig = (
            pool & ema_trend & (rs21 >= 85.0) & (rs63 >= 65.0) & (accel20 >= 5.0)
            & (near_high >= -0.20) & bo_ctx & ~extended
        )
        score = (
            0.35 * rs21 + 0.15 * rs63 + 0.20 * accel_pct.fillna(50.0)
            + 0.30 * bo_score
        )
    elif variant == "EARLY_PIONEER_THEME":
        ignition = bo_ctx | ((rs21 >= 93.0) & (accel20 >= 7.0))
        elig = (
            pool & ema_trend & (rs21 >= 88.0) & (rs63 >= 72.0) & (accel20 >= 5.0)
            & (near_high >= -0.20) & ignition & ~extended
        )
        score = (
            0.30 * rs21 + 0.12 * rs63 + 0.18 * accel_pct.fillna(50.0)
            + 0.25 * bo_score + 0.15 * peer.fillna(50.0)
        )
    else:
        raise ValueError(variant)
    return elig.fillna(False), score.where(elig)


def precompute_candidates(
    meta: dict[str, Any], matrices: dict[str, pd.DataFrame], peer_ctx: dict[str, Any], features: dict[str, Any]
) -> tuple[dict[pd.Timestamp, list[tuple[str, dict[str, Any]]]], dict[pd.Timestamp, list[tuple[str, dict[str, Any]]]], dict[str, dict[pd.Timestamp, list[tuple[str, dict[str, Any]]]]]]:
    idx = pd.DatetimeIndex(meta["analysis_idx"])
    core_attack: dict[pd.Timestamp, list[tuple[str, dict[str, Any]]]] = {}
    core_selective: dict[pd.Timestamp, list[tuple[str, dict[str, Any]]]] = {}
    for i, d0 in enumerate(idx):
        d = pd.Timestamp(d0)
        core_attack[d] = loo.peer_ranked_candidates(d, matrices, peer_ctx, 12)
        core_selective[d] = loo.stock_only_candidates(d, matrices, 12)
        if (i + 1) % 300 == 0:
            print(f"CORE_CANDS {i + 1}/{len(idx)}", flush=True)

    early: dict[str, dict[pd.Timestamp, list[tuple[str, dict[str, Any]]]]] = {}
    for variant in EARLY_VARIANTS:
        elig, score = early_score_elig(variant, matrices, features)
        by_date: dict[pd.Timestamp, list[tuple[str, dict[str, Any]]]] = {}
        for i, d0 in enumerate(idx):
            d = pd.Timestamp(d0)
            s = pd.to_numeric(score.loc[d], errors="coerce").dropna().nlargest(12)
            rows: list[tuple[str, dict[str, Any]]] = []
            for sym, val in s.items():
                rows.append((str(sym), {
                    "early_score": float(val),
                    "rs21": float(features["rs"][21].at[d, sym]) if pd.notna(features["rs"][21].at[d, sym]) else None,
                    "rs63": float(features["rs"][63].at[d, sym]) if pd.notna(features["rs"][63].at[d, sym]) else None,
                    "accel20": float(features["accel20"].at[d, sym]) if pd.notna(features["accel20"].at[d, sym]) else None,
                }))
            by_date[d] = rows
            if (i + 1) % 600 == 0:
                print(f"{variant} CANDS {i + 1}/{len(idx)}", flush=True)
        early[variant] = by_date
    return core_attack, core_selective, early


def simulate(
    variant: str,
    meta: dict[str, Any],
    matrices: dict[str, pd.DataFrame],
    core_attack: dict[pd.Timestamp, list[tuple[str, dict[str, Any]]]],
    core_selective: dict[pd.Timestamp, list[tuple[str, dict[str, Any]]]],
    early_candidates: dict[str, dict[pd.Timestamp, list[tuple[str, dict[str, Any]]]]],
) -> dict[str, Any]:
    idx = pd.DatetimeIndex(meta["analysis_idx"])
    opens, closes = matrices["open"], matrices["close"]
    cash = 1.0
    pos: dict[str, dict[str, Any]] = {}
    equity: list[tuple[pd.Timestamp, float]] = []
    entries: list[dict[str, Any]] = []
    intervals: list[dict[str, Any]] = []
    red_run = 0

    def close_position(sym: str, date: pd.Timestamp, price: float, reason: str) -> None:
        nonlocal cash
        p = pos.pop(sym)
        cash += float(p["shares"]) * price
        intervals.append({
            "symbol": sym,
            "entry_date": p["entry_date"],
            "entry_price": p["entry_price"],
            "exit_date": date,
            "exit_price": price,
            "entry_sleeve": p["entry_sleeve"],
            "final_sleeve": p["sleeve"],
            "exit_reason": reason,
        })

    for i, d0 in enumerate(idx):
        d = pd.Timestamp(d0)
        prev = None if i == 0 else pd.Timestamp(idx[i - 1])
        if prev is not None:
            color, bucket, _ = delay.market_state(meta, prev)
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
                    if (not p["partial_done"]) and pc >= p["entry_price"] * 1.24:
                        opx = px(opens, d, sym, pc)
                        if opx is not None:
                            sold = p["shares"] * 0.25
                            cash += sold * opx
                            p["shares"] -= sold
                            p["partial_done"] = True
                    stop = max(p["entry_price"] * 0.92, p["peak_close"] * 0.70)
                    if pc <= stop:
                        opx = px(opens, d, sym, pc)
                        if opx is not None:
                            close_position(sym, d, opx, "STOP")

            bull = color in ("Blue", "Green")
            if variant == "CORE12":
                core_cap = 12 if bull and bucket == 2 else 4 if bull and bucket == 1 else 0
                early_cap = 0
            else:
                core_cap = 9 if bull and bucket == 2 else 3 if bull and bucket == 1 else 0
                early_cap = 0 if variant == "CORE9_ONLY" else 3 if bull and bucket == 2 else 1 if bull and bucket == 1 else 0

            core_list = core_attack.get(prev, []) if bucket == 2 else core_selective.get(prev, []) if bucket == 1 else []
            core_take = core_list[:core_cap]
            core_symbols = {s for s, _ in core_take}

            # Graduation: an Early holding that reaches current Core ranks consumes a Core slot without a sale/rebuy.
            core_count = sum(1 for p in pos.values() if p["sleeve"] == "CORE")
            if core_cap > 0 and core_count < core_cap:
                for sym in list(pos):
                    if core_count >= core_cap:
                        break
                    if pos[sym]["sleeve"] == "EARLY" and sym in core_symbols:
                        pos[sym]["sleeve"] = "CORE"
                        pos[sym]["graduated"] = True
                        core_count += 1

            def nav_open_value() -> float:
                total = cash
                for sym, p in pos.items():
                    opx = px(opens, d, sym, px(closes, prev, sym, p["entry_price"]))
                    if opx is not None:
                        total += p["shares"] * opx
                return total

            if (not red_force) and core_cap > 0:
                core_count = sum(1 for p in pos.values() if p["sleeve"] == "CORE")
                if core_count < core_cap:
                    slot_cash = nav_open_value() / 12.0
                    for rank, (sym, info) in enumerate(core_take, start=1):
                        if core_count >= core_cap or cash <= 0:
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
                        pos[sym] = {
                            "shares": alloc / opx, "entry_price": opx, "entry_date": d,
                            "peak_close": opx, "partial_done": False, "sleeve": "CORE",
                            "entry_sleeve": "CORE", "graduated": False,
                        }
                        entries.append({
                            "variant": variant, "symbol": sym, "signal_date": prev, "entry_date": d,
                            "entry_price": opx, "entry_sleeve": "CORE", "rank": rank, **info,
                        })
                        core_count += 1

            if (not red_force) and early_cap > 0:
                e_count = sum(1 for p in pos.values() if p["sleeve"] == "EARLY")
                if e_count < early_cap:
                    e_list = early_candidates[variant].get(prev, [])
                    slot_cash = nav_open_value() / 12.0
                    for rank, (sym, info) in enumerate(e_list, start=1):
                        if e_count >= early_cap or cash <= 0:
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
                        pos[sym] = {
                            "shares": alloc / opx, "entry_price": opx, "entry_date": d,
                            "peak_close": opx, "partial_done": False, "sleeve": "EARLY",
                            "entry_sleeve": "EARLY", "graduated": False,
                        }
                        entries.append({
                            "variant": variant, "symbol": sym, "signal_date": prev, "entry_date": d,
                            "entry_price": opx, "entry_sleeve": "EARLY", "rank": rank, **info,
                        })
                        e_count += 1

        nav = cash
        for sym, p in pos.items():
            cp = px(closes, d, sym, px(opens, d, sym, p["entry_price"]))
            if cp is None:
                cp = p["entry_price"]
            p["peak_close"] = max(p["peak_close"], cp)
            nav += p["shares"] * cp
        equity.append((d, nav))

    last = pd.Timestamp(idx[-1])
    for sym, p in pos.items():
        cp = px(closes, last, sym, p["entry_price"])
        intervals.append({
            "symbol": sym, "entry_date": p["entry_date"], "entry_price": p["entry_price"],
            "exit_date": last, "exit_price": cp, "entry_sleeve": p["entry_sleeve"],
            "final_sleeve": p["sleeve"], "exit_reason": "OPEN_END",
        })

    eq = pd.Series(dict(equity), dtype=float).sort_index()
    return {
        "equity": eq,
        "metrics": base.slice_metrics(eq),
        "entries": pd.DataFrame(entries),
        "intervals": pd.DataFrame(intervals),
    }


def annual_topk_events(close: pd.DataFrame, pool: pd.DataFrame, idx: pd.DatetimeIndex, k: int = 10) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for year in range(2016, 2026):
        dates = idx[idx.year == year]
        if len(dates) < 180:
            continue
        d0, d1 = pd.Timestamp(dates[0]), pd.Timestamp(dates[-1])
        tradable = pool.loc[dates[:20]].fillna(False).any(axis=0)
        ret = (close.loc[d1] / close.loc[d0] - 1.0).where(tradable).dropna().sort_values(ascending=False).head(k)
        for rank, (sym, r) in enumerate(ret.items(), start=1):
            rows.append({"event_type": f"ANNUAL_TOP{k}", "anchor_date": d0, "end_date": d1, "symbol": str(sym), "future_return": float(r), "rank": rank})
    return pd.DataFrame(rows)


def rolling126_events(close: pd.DataFrame, pool: pd.DataFrame, idx: pd.DatetimeIndex, min_return: float | None) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    positions = {pd.Timestamp(d): i for i, d in enumerate(close.index)}
    analysis_positions = [positions[pd.Timestamp(d)] for d in idx if pd.Timestamp(d) in positions]
    if not analysis_positions:
        return pd.DataFrame()
    first, last = min(analysis_positions), max(analysis_positions)
    for p in range(first, last - 126 + 1, 21):
        d0, d1 = pd.Timestamp(close.index[p]), pd.Timestamp(close.index[p + 126])
        if d0 not in idx or d1 > idx[-1]:
            continue
        tradable = pool.loc[d0].fillna(False)
        ret = (close.loc[d1] / close.loc[d0] - 1.0).where(tradable).dropna().sort_values(ascending=False).head(10)
        for rank, (sym, r) in enumerate(ret.items(), start=1):
            if min_return is not None and float(r) < min_return:
                continue
            rows.append({"event_type": "ROLL126_TOP10", "anchor_date": d0, "end_date": d1, "symbol": str(sym), "future_return": float(r), "rank": rank, "anchor_pos": p})
    raw = pd.DataFrame(rows)
    if raw.empty:
        return raw
    # De-duplicate overlapping labels for the same leader run.
    keep: list[int] = []
    for sym, g in raw.sort_values(["symbol", "anchor_pos"]).groupby("symbol", observed=True):
        last_kept = -10**9
        for j, r in g.iterrows():
            p = int(r["anchor_pos"])
            if p - last_kept >= 63:
                keep.append(j)
                last_kept = p
    return raw.loc[keep].sort_values(["anchor_date", "rank"]).reset_index(drop=True)


def evaluate_events(events: pd.DataFrame, intervals: pd.DataFrame, close: pd.DataFrame) -> dict[str, Any]:
    if events.empty:
        return {"n": 0}
    by_sym = {str(s): g.sort_values("entry_date") for s, g in intervals.groupby("symbol")} if len(intervals) else {}
    rows: list[dict[str, Any]] = []
    for ev in events.itertuples(index=False):
        sym, a, e = str(ev.symbol), pd.Timestamp(ev.anchor_date), pd.Timestamp(ev.end_date)
        anchor_px = px(close, a, sym, None)
        capture = None
        g = by_sym.get(sym)
        if g is not None:
            z = g[(pd.to_datetime(g["entry_date"]) <= e) & (pd.to_datetime(g["exit_date"]) >= a)]
            if len(z):
                r = z.iloc[0]
                entry_date = pd.Timestamp(r["entry_date"])
                if entry_date <= a:
                    capture = {"date": a, "gain": 0.0, "sleeve": str(r["entry_sleeve"]), "preheld": True}
                else:
                    ep = float(r["entry_price"])
                    gain = ep / anchor_px - 1.0 if anchor_px and anchor_px > 0 else np.nan
                    capture = {"date": entry_date, "gain": gain, "sleeve": str(r["entry_sleeve"]), "preheld": False}
        rows.append({
            "symbol": sym, "anchor_date": a, "future_return": float(ev.future_return),
            "captured": capture is not None,
            "capture_gain": capture["gain"] if capture else np.nan,
            "entry_sleeve": capture["sleeve"] if capture else None,
            "preheld": capture["preheld"] if capture else False,
        })
    x = pd.DataFrame(rows)
    g = pd.to_numeric(x["capture_gain"], errors="coerce")
    captured = x["captured"]
    return {
        "n": int(len(x)),
        "captured": int(captured.sum()),
        "capture_rate": float(captured.mean()),
        "within_20pct_all": float((g <= 0.20).fillna(False).mean()),
        "within_30pct_all": float((g <= 0.30).fillna(False).mean()),
        "within_50pct_all": float((g <= 0.50).fillna(False).mean()),
        "within_30pct_of_captured": float((g[captured] <= 0.30).mean()) if captured.any() else None,
        "within_50pct_of_captured": float((g[captured] <= 0.50).mean()) if captured.any() else None,
        "capture_gain_median": float(g[captured].median()) if captured.any() else None,
        "early_entry_share_of_captures": float((x.loc[captured, "entry_sleeve"] == "EARLY").mean()) if captured.any() else None,
        "preheld_share_of_captures": float(x.loc[captured, "preheld"].mean()) if captured.any() else None,
    }


def eligibility_component_audit(events: pd.DataFrame, matrices: dict[str, pd.DataFrame], f: dict[str, Any]) -> dict[str, Any]:
    if events.empty:
        return {}
    idx = matrices["close"].index
    pos = {pd.Timestamp(d): i for i, d in enumerate(idx)}
    tests = {
        "BASE_POOL": f["pool"],
        "CLOSE_GT_EMA21": matrices["close"] >= f["ema21"],
        "SMA50_GT_SMA200": matrices["sma50"] > matrices["sma200"],
        "CLOSE_GT_SMA200": matrices["close"] > matrices["sma200"],
        "RS21_GE85": f["rs"][21] >= 85.0,
        "RS63_GE85": f["rs"][63] >= 85.0,
        "RS189_GE85": f["rs"][189] >= 85.0,
        "CURRENT_FULL_ELIG": matrices["new_eligible"],
    }
    result: dict[str, Any] = {}
    for name, mask in tests.items():
        gains, delays, hits = [], [], 0
        for ev in events.itertuples(index=False):
            sym, a, e = str(ev.symbol), pd.Timestamp(ev.anchor_date), pd.Timestamp(ev.end_date)
            z = mask.loc[(mask.index >= a) & (mask.index <= e), sym].fillna(False)
            h = z.index[z]
            if not len(h):
                continue
            d = pd.Timestamp(h[0]); hits += 1
            ap = px(matrices["close"], a, sym, None); dp = px(matrices["close"], d, sym, None)
            if ap and dp:
                gains.append(dp / ap - 1.0)
            if a in pos and d in pos:
                delays.append(pos[d] - pos[a])
        result[name] = {
            "reach_rate": float(hits / len(events)),
            "gain_median": float(np.median(gains)) if gains else None,
            "delay_median_sessions": float(np.median(delays)) if delays else None,
            "within_30pct_all": float(sum(1 for x in gains if x <= 0.30) / len(events)),
        }
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--output", required=True)
    ap.add_argument("--analysis-start", default="2016-01-04")
    ap.add_argument("--analysis-end", default="2026-09-02")
    ap.add_argument("--max-tickers", type=int, default=6000)
    ap.add_argument("--batch-size", type=int, default=75)
    args = ap.parse_args()
    root = Path(args.root)
    out = root / args.output
    out.mkdir(parents=True, exist_ok=True)

    print("BUILD INPUTS", flush=True)
    meta, matrices = ex.build_inputs_ext(root, args.analysis_start, args.analysis_end, args.max_tickers, args.batch_size)
    print("BUILD LOO THEME", flush=True)
    peer_ctx = loo.build_leave_one_out_scores(root, matrices)
    print("BUILD EARLY FEATURES", flush=True)
    features = build_features(root, matrices, peer_ctx)
    print("PRECOMPUTE CANDIDATES", flush=True)
    core_attack, core_selective, early = precompute_candidates(meta, matrices, peer_ctx, features)

    idx = pd.DatetimeIndex(meta["analysis_idx"])
    annual5plus = delay.annual_leader_events(matrices["close"], features["pool"], idx, include_partial_2026=False)
    annual_top5 = annual5plus[annual5plus["top5"]].rename(columns={"final_date": "end_date", "final_return": "future_return"})
    annual_200_400 = annual5plus[annual5plus["cohort_200_400"]].rename(columns={"final_date": "end_date", "final_return": "future_return"})
    annual_400plus = annual5plus[annual5plus["cohort_400plus"]].rename(columns={"final_date": "end_date", "final_return": "future_return"})
    annual_top10 = annual_topk_events(matrices["close"], features["pool"], idx, 10)
    roll126_top10 = rolling126_events(matrices["close"], features["pool"], idx, None)
    roll126_big = rolling126_events(matrices["close"], features["pool"], idx, 0.50)

    label_sets = {
        "ANNUAL_TOP5_2016_2025": annual_top5,
        "ANNUAL_TOP10_2016_2025": annual_top10,
        "ANNUAL_200_400": annual_200_400,
        "ANNUAL_400PLUS": annual_400plus,
        "ROLL126_TOP10_DEDUP": roll126_top10,
        "ROLL126_TOP10_GE50_DEDUP": roll126_big,
    }

    result: dict[str, Any] = {
        "status": "EARLY_LEADER_ENTRY_CANDIDATE_AUDIT",
        "scope": "research only; Core rule unchanged; compare 9 Core + 3 Early / Selective 3+1 entry candidates",
        "execution": "daily close signal -> next open; same market mode, -8% initial stop, +24% 25% partial, peak-close -30% trail, Red next-open exit; no rank/theme forced exit",
        "early_variants": {
            "EARLY_RS21": "base pool + close>=EMA21 + RS21>=90; rank RS21",
            "EARLY_ACCEL": "base pool + close>=EMA21 + RS21>=85 + RS63>=60 + RS21 percentile improvement over 20 sessions>=5; rank RS21/RS42/acceleration",
            "EARLY_PIONEER": "EMA21 trend + RS21>=88 + RS63>=72 + 20-session RS21 acceleration>=5 + within 20% of 63d high + near/recent 20/50d high breakout OR very strong RS21/acceleration; no >8% extended chase",
            "EARLY_TIGHT_BREAK": "EMA21 trend + RS21>=85 + RS63>=65 + acceleration>=5 + within -1.5% to +4% of prior 20/50d high; no >8% extended chase",
            "EARLY_PIONEER_THEME": "PIONEER eligibility; ranking adds strict leave-one-out Theme score as 15% bonus",
        },
        "labels": {k: int(len(v)) for k, v in label_sets.items()},
        "variants": {},
        "eligibility_components_on_annual_top5": eligibility_component_audit(annual_top5, matrices, features),
    }

    sims: dict[str, dict[str, Any]] = {}
    for variant in VARIANTS:
        print(f"SIM {variant}", flush=True)
        sim = simulate(variant, meta, matrices, core_attack, core_selective, early)
        sims[variant] = sim
        packed = {
            "metrics": sim["metrics"],
            "entries": int(len(sim["entries"])),
            "early_entries": int((sim["entries"].get("entry_sleeve", pd.Series(dtype=str)) == "EARLY").sum()) if len(sim["entries"]) else 0,
            "leader_capture": {name: evaluate_events(events, sim["intervals"], matrices["close"]) for name, events in label_sets.items()},
        }
        result["variants"][variant] = packed
        sim["equity"].rename("equity").to_csv(out / f"equity_{variant}.csv")
        sim["entries"].to_csv(out / f"entries_{variant}.csv", index=False)
        sim["intervals"].to_csv(out / f"intervals_{variant}.csv", index=False)

    result["vs_CORE12_block20_win_probability"] = {}
    for variant in VARIANTS:
        if variant == "CORE12":
            continue
        result["vs_CORE12_block20_win_probability"][variant] = base.bootstrap_block_win(
            sims[variant]["equity"], sims["CORE12"]["equity"], block=20, reps=5000, seed=20260904 + VARIANTS.index(variant) * 17
        )

    (out / "summary_early_leader_entry_candidates.json").write_text(json.dumps(safe(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== EARLY_LEADER_ENTRY_CANDIDATES_JSON ===", flush=True)
    print(json.dumps(safe(result), ensure_ascii=False, indent=2), flush=True)
    print("=== END_EARLY_LEADER_ENTRY_CANDIDATES_JSON ===", flush=True)


if __name__ == "__main__":
    main()
