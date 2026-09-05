from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import audit_ordinary_stock_market_mode_robustness as base
import audit_ordinary_stock_exit_trail as ex
import audit_ordinary_stock_theme_leave_one_out as loo
import audit_ordinary_stock_rebalance_vs_trail as rt
import audit_leader_factor_horizon_discovery as disc
import audit_early_liquidity_label_sensitivity as ls


DDV20 = 20_000_000.0
CORE_SLOTS = 12
SELECTIVE_SLOTS = 4
EARLY_SLOTS = 1
TCOST_BPS = 10.0
DEV_YEARS = range(2016, 2021)
OOS_YEARS = range(2021, 2026)
LABEL_FLOORS = (10_000_000.0, 20_000_000.0, 50_000_000.0)


@dataclass(frozen=True)
class Architecture:
    name: str
    attack_total: int
    selective_total: int
    core_attack_cap: int
    core_selective_cap: int
    slot_divisor: int


ARCHS = (
    # Primary reconstruction: Early1 lives inside the existing 12-position gross envelope.
    Architecture("WITHIN12", 12, 4, 12, 4, 12),
    # Sensitivity only: Core12 plus one Early slot, all positions normalized to 1/13 NAV.
    Architecture("OVERLAY13", 13, 5, 12, 4, 13),
)


def safe(v: Any) -> Any:
    return base.safe(v)


def pct(frame: pd.DataFrame, mask: pd.DataFrame) -> pd.DataFrame:
    return (frame.where(mask).rank(axis=1, pct=True, method="average") * 100.0).astype(np.float32)


def px(frame: pd.DataFrame, d: pd.Timestamp, sym: str, fallback: float | None = None) -> float | None:
    try:
        x = float(frame.at[d, sym])
        if np.isfinite(x) and x > 0:
            return x
    except Exception:
        pass
    return fallback


def build_ddv20_inputs(root: Path, matrices: dict[str, pd.DataFrame]) -> tuple[dict[str, pd.DataFrame], dict[int, pd.DataFrame], pd.DataFrame]:
    """Rebuild the research DDV20 universe and RS percentiles without changing shared/live constants."""
    m = {k: v.copy() if isinstance(v, pd.DataFrame) else v for k, v in matrices.items()}
    close, dvol = m["close"], m["dvol"]
    base20 = (close >= 5.0) & (dvol >= DDV20)
    bio = base.read_structural_bio_exclusions(root, list(close.columns))
    if bio:
        cols = [s for s in bio if s in base20.columns]
        if cols:
            base20.loc[:, cols] = False
    rs: dict[int, pd.DataFrame] = {}
    for h in (21, 42, 63, 189):
        r = close / close.shift(h) - 1.0
        rs[h] = (r.where(base20 & r.notna()).rank(axis=1, pct=True, method="average") * 100.0).astype(np.float32)
    m["rs63"] = rs[63]
    m["rs189"] = rs[189]
    m["new_eligible"] = base20 & (m["sma50"] > m["sma200"]) & (close > m["sma200"]) & (rs[189] >= 85.0) & (rs[63] >= 85.0)
    m["continuation_eligible"] = base20 & (m["sma50"] > m["sma200"]) & (rs[189] >= 85.0)
    return m, rs, base20


def build_early_scores(m: dict[str, pd.DataFrame], rs: dict[int, pd.DataFrame], base20: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    close, dvol = m["close"], m["dvol"]
    radar = base20 & ((rs[21] >= 85.0) | (rs[42] >= 85.0) | (rs[63] >= 85.0))
    prior63 = close.shift(1).rolling(63, min_periods=40).max()
    high63 = pct(close / prior63, radar)
    acc10 = pct(rs[21] - rs[21].shift(10), radar)
    b = (0.50 * rs[21].where(radar).fillna(50.0) + 0.25 * high63.fillna(50.0) + 0.25 * acc10.fillna(50.0)).astype(np.float32)
    liq = pct(np.log(dvol.clip(lower=1.0)), radar)
    liq_acc10 = pct(dvol / dvol.shift(10) - 1.0, radar)
    la = (0.80 * b + 0.10 * liq.fillna(50.0) + 0.10 * liq_acc10.fillna(50.0)).astype(np.float32)
    return radar, {"BASE": b, "LIQ_ACCEL": la}


def core_candidates(d: pd.Timestamp, m: dict[str, pd.DataFrame], peer_ctx: dict[str, Any], bucket: int, n: int = CORE_SLOTS):
    if bucket == 1:
        return loo.stock_only_candidates(d, m, n)
    return loo.peer_ranked_candidates(d, m, peer_ctx, n)


def early_top1(d: pd.Timestamp, score: pd.DataFrame, radar: pd.DataFrame, held: set[str]) -> tuple[str, float] | None:
    s = score.loc[d].where(radar.loc[d]).dropna().sort_values(ascending=False)
    for sym, val in s.items():
        if str(sym) not in held:
            return str(sym), float(val)
    return None


def year_metrics(eq: pd.Series) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for y, z in eq.groupby(eq.index.year):
        z = z.dropna()
        if len(z) < 2:
            continue
        ret = float(z.iloc[-1] / z.iloc[0] - 1.0)
        dd = z / z.cummax() - 1.0
        out[str(int(y))] = {"return": ret, "mdd": float(dd.min()), "sessions": int(len(z))}
    return out


def simulate(
    meta: dict[str, Any],
    m: dict[str, pd.DataFrame],
    peer_ctx: dict[str, Any],
    radar: pd.DataFrame,
    early_score: pd.DataFrame,
    score_name: str,
    arch: Architecture,
    cost_bps: float = 0.0,
) -> dict[str, Any]:
    idx: pd.DatetimeIndex = meta["analysis_idx"]
    opens, closes = m["open"], m["close"]
    breadth, nq = meta["breadth"], meta["nq"]
    cost = float(cost_bps) / 10000.0
    cash = 1.0
    pos: dict[str, dict[str, Any]] = {}
    equities: list[tuple[pd.Timestamp, float]] = []
    entries: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    promotions: list[dict[str, Any]] = []
    slot_log: list[dict[str, Any]] = []
    red_run = 0

    def close_pos(sym: str, d: pd.Timestamp, price: float, reason: str) -> None:
        nonlocal cash
        p = pos.pop(sym)
        proceeds = p["shares"] * price * (1.0 - cost)
        cash += proceeds
        gross_ret = price / p["entry_price"] - 1.0
        trades.append({
            "variant": score_name, "architecture": arch.name, "symbol": sym,
            "entry_date": p["entry_date"], "exit_date": d, "entry_price": p["entry_price"], "exit_price": price,
            "return": gross_ret, "exit_reason": reason, "entry_layer": p["entry_layer"],
            "promoted": bool(p.get("promoted", False)), "entry_alloc": p["entry_alloc"],
            "realized_pnl_proxy": p["entry_alloc"] * gross_ret,
        })

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
                        close_pos(sym, d, opx, "RED")
            else:
                # Same adopted winner-holding exit for Core and Early; no rank/theme exit.
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
                    ps = p["peak_close"] * 0.70
                    if ps > stop:
                        stop, reason = ps, "PEAK30"
                    if pc <= stop:
                        opx = px(opens, d, sym, pc)
                        if opx is not None:
                            close_pos(sym, d, opx, reason)

            b = float(breadth.loc[prev]) if prev in breadth.index and pd.notna(breadth.loc[prev]) else np.nan
            bucket = base.breadth_bucket(b)
            bull = color in ("Blue", "Green")
            core_cap = arch.core_attack_cap if bull and bucket == 2 else arch.core_selective_cap if bull and bucket == 1 else 0
            total_cap = arch.attack_total if bull and bucket == 2 else arch.selective_total if bull and bucket == 1 else 1
            if color == "Red":
                total_cap = 0

            cc = core_candidates(prev, m, peer_ctx, bucket, CORE_SLOTS) if core_cap > 0 else []
            core_set = {sym for sym, _ in cc}

            # Direct Early -> Core promotion: no sell/re-entry and no price reset.
            for sym, p in list(pos.items()):
                if p["layer"] == "EARLY" and sym in core_set:
                    p["layer"] = "CORE"
                    p["promoted"] = True
                    promotions.append({
                        "variant": score_name, "architecture": arch.name, "symbol": sym,
                        "entry_date": p["entry_date"], "promotion_signal_date": prev,
                        "sessions_to_promotion": int(p["sessions"]),
                        "entry_price": p["entry_price"], "promotion_close": px(closes, prev, sym, p["entry_price"]),
                    })

            early_held = [s for s, p in pos.items() if p["layer"] == "EARLY"]
            held = set(pos)
            top1 = early_top1(prev, early_score, radar, held)

            # Reserve one gross slot for Early only when an Early signal actually exists.
            reserve = 1 if (not red_force and not early_held and top1 is not None) else 0
            if arch.name == "WITHIN12":
                core_fill_limit = max(0, total_cap - reserve)
            else:
                core_fill_limit = min(core_cap, total_cap - reserve)

            nav_open = cash
            for sym, p in pos.items():
                opx = px(opens, d, sym, px(closes, prev, sym, p["entry_price"]))
                if opx is not None:
                    nav_open += p["shares"] * opx
            slot_cash = nav_open / float(arch.slot_divisor)

            # Core refill first, but do not consume a reserved Early slot.
            core_now = sum(1 for p in pos.values() if p["layer"] == "CORE")
            for rank0, (sym, c) in enumerate(cc, start=1):
                if len(pos) >= core_fill_limit or core_now >= core_cap or cash <= 1e-12:
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
                    "sessions": 0, "partial_done": False, "entry_layer": "CORE", "layer": "CORE",
                    "promoted": False, "entry_alloc": alloc, **c,
                }
                core_now += 1
                entries.append({
                    "variant": score_name, "architecture": arch.name, "symbol": sym, "signal_date": prev,
                    "entry_date": d, "entry_price": opx, "entry_layer": "CORE", "candidate_rank": rank0,
                    "entry_alloc": alloc, **c,
                })

            # Single Early slot. No Full Eligibility and no breadth/NQSAR Blue-Green entry gate; Red remains portfolio defense.
            action = "NO_SIGNAL"
            cand_sym = top1[0] if top1 else None
            cand_score = top1[1] if top1 else None
            early_held = [s for s, p in pos.items() if p["layer"] == "EARLY"]
            if red_force:
                action = "RED_BLOCK"
            elif early_held:
                action = "OCCUPIED"
            elif top1 is not None and len(pos) < total_cap and cash > 1e-12:
                sym, sval = top1
                opx = px(opens, d, sym, px(closes, prev, sym, None))
                if opx is not None:
                    alloc = min(slot_cash, cash)
                    if alloc > 1e-10:
                        cash -= alloc
                        investable = alloc * (1.0 - cost)
                        pos[sym] = {
                            "shares": investable / opx, "entry_price": opx, "entry_date": d, "peak_close": opx,
                            "sessions": 0, "partial_done": False, "entry_layer": "EARLY", "layer": "EARLY",
                            "promoted": False, "entry_alloc": alloc, "early_score": sval,
                        }
                        entries.append({
                            "variant": score_name, "architecture": arch.name, "symbol": sym, "signal_date": prev,
                            "entry_date": d, "entry_price": opx, "entry_layer": "EARLY", "candidate_rank": 1,
                            "early_score": sval, "entry_alloc": alloc,
                        })
                        action = "ENTER"
            elif top1 is not None:
                action = "CAPACITY_BLOCK"

            slot_log.append({
                "date": prev, "variant": score_name, "architecture": arch.name,
                "candidate_symbol": cand_sym, "candidate_score": cand_score,
                "action": action, "early_slot_symbol": next((s for s, p in pos.items() if p["layer"] == "EARLY"), None),
                "positions": int(len(pos)), "core_positions": int(sum(1 for p in pos.values() if p["layer"] == "CORE")),
                "market_color": color, "breadth_bucket": int(bucket),
            })

        nav = cash
        for sym, p in pos.items():
            cp = px(closes, d, sym, px(opens, d, sym, p["entry_price"]))
            if cp is None:
                cp = p["entry_price"]
            p["peak_close"] = max(p["peak_close"], cp)
            nav += p["shares"] * cp
        equities.append((d, nav))

    eq = pd.Series(dict(equities), dtype=float).sort_index()
    return {
        "equity": eq,
        "entries": pd.DataFrame(entries),
        "trades": pd.DataFrame(trades),
        "promotions": pd.DataFrame(promotions),
        "slot_log": pd.DataFrame(slot_log),
    }


def first_entry_capture(leaders: pd.DataFrame, sim: dict[str, Any], close: pd.DataFrame) -> pd.DataFrame:
    entries = sim["entries"].copy()
    if not entries.empty:
        entries["signal_date"] = pd.to_datetime(entries["signal_date"])
        entries["entry_date"] = pd.to_datetime(entries["entry_date"])
    rows: list[dict[str, Any]] = []
    for _, rr in leaders.iterrows():
        z = dict(rr)
        sym = str(rr["symbol"]); start = pd.Timestamp(rr["start_date"]); peak = pd.Timestamp(rr["peak_date"]); sp = float(rr["start_price"])
        hit = entries.loc[(entries["symbol"].astype(str) == sym) & (entries["entry_date"] >= start) & (entries["entry_date"] <= peak)].sort_values("entry_date") if not entries.empty else entries
        z.update({"entered": False, "entry_layer_actual": None, "first_entry_date": pd.NaT, "first_entry_runup": np.nan, "le30": False, "le50": False})
        if not hit.empty:
            r0 = hit.iloc[0]; ed = pd.Timestamp(r0["entry_date"]); ep = px(close, ed, sym, float(r0["entry_price"]))
            run = float(ep / sp - 1.0) if ep is not None and sp > 0 else np.nan
            z.update({
                "entered": True, "entry_layer_actual": str(r0["entry_layer"]), "first_entry_date": ed,
                "first_entry_runup": run, "le30": bool(np.isfinite(run) and run <= 0.30), "le50": bool(np.isfinite(run) and run <= 0.50),
            })
        rows.append(z)
    return pd.DataFrame(rows)


def capture_pack(df: pd.DataFrame) -> dict[str, Any]:
    if df.empty:
        return {"n": 0}
    ent = df["entered"].astype(bool)
    run = pd.to_numeric(df.loc[ent, "first_entry_runup"], errors="coerce")
    return {
        "n": int(len(df)), "entered_n": int(ent.sum()), "entered_rate": float(ent.mean()),
        "le30_rate": float(df["le30"].astype(bool).mean()), "le50_rate": float(df["le50"].astype(bool).mean()),
        "median_first_entry_runup": float(run.median()) if run.notna().any() else None,
        "early_entry_n": int((df["entry_layer_actual"] == "EARLY").sum()),
        "core_entry_n": int((df["entry_layer_actual"] == "CORE").sum()),
    }


def split_capture(df: pd.DataFrame) -> dict[str, Any]:
    years = pd.to_numeric(df["period"].astype(str).str[:4], errors="coerce")
    return {
        "all": capture_pack(df),
        "dev_2016_2020": capture_pack(df.loc[years.isin(list(DEV_YEARS))]),
        "oos_2021_2025": capture_pack(df.loc[years.isin(list(OOS_YEARS))]),
        "by_year": {str(int(y)): capture_pack(df.loc[years == y]) for y in sorted(years.dropna().unique())},
    }


def top1_signal_capture(leaders: pd.DataFrame, slot_log: pd.DataFrame, close: pd.DataFrame) -> dict[str, Any]:
    rows = []
    logs = slot_log.copy()
    logs["date"] = pd.to_datetime(logs["date"])
    for _, rr in leaders.iterrows():
        sym = str(rr["symbol"]); start = pd.Timestamp(rr["start_date"]); peak = pd.Timestamp(rr["peak_date"]); sp = float(rr["start_price"])
        z = logs.loc[(logs["candidate_symbol"].astype(str) == sym) & (logs["date"] >= start) & (logs["date"] <= peak)].sort_values("date")
        rec = {"period": rr["period"], "rank": rr["rank"], "symbol": sym, "top1_seen": False, "top1_le30": False, "top1_le50": False, "first_top1_runup": np.nan, "blocked_while_early": False}
        if not z.empty:
            d = pd.Timestamp(z.iloc[0]["date"]); p = px(close, d, sym)
            run = float(p / sp - 1.0) if p is not None and sp > 0 else np.nan
            rec.update({
                "top1_seen": True, "top1_le30": bool(np.isfinite(run) and run <= 0.30), "top1_le50": bool(np.isfinite(run) and run <= 0.50),
                "first_top1_runup": run, "blocked_while_early": bool((z["action"] == "OCCUPIED").any()),
            })
        rows.append(rec)
    df = pd.DataFrame(rows)
    years = pd.to_numeric(df["period"].astype(str).str[:4], errors="coerce")
    def pack(z: pd.DataFrame) -> dict[str, Any]:
        if z.empty: return {"n": 0}
        seen = z["top1_seen"].astype(bool); run = pd.to_numeric(z.loc[seen, "first_top1_runup"], errors="coerce")
        return {
            "n": int(len(z)), "top1_seen_rate": float(seen.mean()), "top1_le30_rate": float(z["top1_le30"].mean()),
            "top1_le50_rate": float(z["top1_le50"].mean()), "median_first_top1_runup": float(run.median()) if run.notna().any() else None,
            "blocked_while_early_n": int(z["blocked_while_early"].sum()),
        }
    return {
        "all": pack(df), "dev_2016_2020": pack(df.loc[years.isin(list(DEV_YEARS))]), "oos_2021_2025": pack(df.loc[years.isin(list(OOS_YEARS))]),
        "by_year": {str(int(y)): pack(df.loc[years == y]) for y in sorted(years.dropna().unique())},
    }


def promotion_pack(prom: pd.DataFrame, entries: pd.DataFrame) -> dict[str, Any]:
    ee = entries.loc[entries["entry_layer"] == "EARLY"].copy() if not entries.empty else entries
    if ee.empty:
        return {"early_entries": 0, "promotions": 0, "promotion_rate": None}
    n = int(len(ee)); p = int(len(prom)); sess = pd.to_numeric(prom.get("sessions_to_promotion", pd.Series(dtype=float)), errors="coerce")
    return {
        "early_entries": n, "early_symbols": int(ee["symbol"].nunique()), "promotions": p,
        "promotion_rate": float(p / n), "median_sessions_to_promotion": float(sess.median()) if sess.notna().any() else None,
    }


def pnl_concentration(trades: pd.DataFrame, start_year: int = 2021) -> dict[str, Any]:
    if trades.empty:
        return {"n": 0}
    z = trades.copy(); z["exit_date"] = pd.to_datetime(z["exit_date"]); z = z.loc[z["exit_date"].dt.year >= start_year]
    if z.empty: return {"n": 0}
    by = z.groupby("symbol", observed=True)["realized_pnl_proxy"].sum().sort_values(ascending=False)
    pos = by[by > 0]
    total_pos = float(pos.sum())
    return {
        "n": int(len(z)), "symbols": int(z["symbol"].nunique()),
        "top1_positive_pnl_share": float(pos.iloc[:1].sum() / total_pos) if total_pos > 0 else None,
        "top5_positive_pnl_share": float(pos.iloc[:5].sum() / total_pos) if total_pos > 0 else None,
        "top_positive_symbols": [{"symbol": str(s), "pnl_proxy": float(v)} for s, v in pos.head(10).items()],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="."); ap.add_argument("--output", required=True)
    ap.add_argument("--analysis-start", default="2016-01-04"); ap.add_argument("--analysis-end", default="2025-12-31")
    ap.add_argument("--max-tickers", type=int, default=6000); ap.add_argument("--batch-size", type=int, default=75)
    args = ap.parse_args()
    root = Path(args.root); out = root / args.output; out.mkdir(parents=True, exist_ok=True)

    print("BUILD shared PIT inputs", flush=True)
    meta, raw = ex.build_inputs_ext(root, args.analysis_start, args.analysis_end, args.max_tickers, args.batch_size)
    m, rs, base20 = build_ddv20_inputs(root, raw)
    print("BUILD LOO theme context on same prices", flush=True)
    peer_ctx = loo.build_leave_one_out_scores(root, m)
    radar, scores = build_early_scores(m, rs, base20)

    print("FREEZE independent annual Top5 labels", flush=True)
    labels: dict[str, pd.DataFrame] = {}
    for floor in LABEL_FLOORS:
        key = f"LABEL_DDV{int(floor / 1_000_000)}"
        all20 = ls.build_annual_leaders_floor(m, pd.Timestamp(args.analysis_start), pd.Timestamp(args.analysis_end), floor)
        labels[key] = all20.loc[pd.to_numeric(all20["rank"], errors="coerce") <= 5].copy()
        labels[key].to_csv(out / f"annual_top5_{key}.csv", index=False)

    result: dict[str, Any] = {
        "status": "EARLY1_OPERATIONAL_FINAL_AUDIT",
        "design": {
            "purpose": "Final confirmatory BASE vs dev-selected LIQ_ACCEL comparison in a one-Early-slot operational portfolio reconstruction.",
            "core": "Research DDV20 Core; Attack current V38 70% RS189 + 30% LOO Theme, Selective RS189; 12/4 caps; same exits.",
            "early": "DDV20 Radar; no Full Eligibility; no Blue/Green/Breadth entry gate; Red remains defense; one slot; same winner-holding exits; direct promotion when held Early reaches current Core candidate set.",
            "BASE": "50% RS21 + 25% 63d-high proximity + 25% RS21 10-session acceleration.",
            "LIQ_ACCEL": "80% BASE + 10% current DDV percentile + 10% DDV 10-session acceleration percentile; frozen by prior 2016-2020 audit.",
            "primary_architecture": "WITHIN12: Early1 is inside the existing 12-position gross envelope. A slot is reserved only when an Early signal exists.",
            "architecture_sensitivity": "OVERLAY13: Core12 + Early1, all slots normalized to 1/13 NAV; not a tuning candidate.",
            "historical_note": "The exact earlier Early1 implementation that produced the previously discussed CAGR is not present in the current research tree, so this audit does not claim byte-for-byte reproduction. It uses only the known current invariants and tests architecture sensitivity explicitly.",
            "oos": "2021-2025 is confirmatory only; no coefficient or threshold is selected from it.",
            "no_main_change": True, "no_live_change": True,
        },
        "coverage": {"downloaded": int(meta["downloaded"]), "sessions": int(len(m["close"])), "symbols": int(len(m["close"].columns))},
        "architectures": {},
    }

    sims: dict[tuple[str, str], dict[str, Any]] = {}
    for arch in ARCHS:
        result["architectures"][arch.name] = {"variants": {}, "bootstrap_liq_vs_base": None, "cost10bps": {}}
        for name in ("BASE", "LIQ_ACCEL"):
            print(f"SIM {arch.name} {name}", flush=True)
            sim = simulate(meta, m, peer_ctx, radar, scores[name], name, arch, 0.0)
            sims[(arch.name, name)] = sim
            ent = sim["entries"]; tr = sim["trades"]
            v: dict[str, Any] = {
                "metrics": base.slice_metrics(sim["equity"]), "year_metrics": year_metrics(sim["equity"]),
                "trade_stats": rt.trade_stats(tr), "entries": int(len(ent)),
                "early_entries": int((ent["entry_layer"] == "EARLY").sum()) if not ent.empty else 0,
                "core_entries": int((ent["entry_layer"] == "CORE").sum()) if not ent.empty else 0,
                "promotion": promotion_pack(sim["promotions"], ent),
                "pnl_concentration_oos": pnl_concentration(tr, 2021),
                "labels": {}, "top1_signal": {},
            }
            for lkey, leaders in labels.items():
                cap = first_entry_capture(leaders, sim, m["close"])
                cap.to_csv(out / f"capture_{arch.name}_{name}_{lkey}.csv", index=False)
                v["labels"][lkey] = split_capture(cap)
                v["top1_signal"][lkey] = top1_signal_capture(leaders, sim["slot_log"], m["close"])
            result["architectures"][arch.name]["variants"][name] = v
            sim["equity"].rename("equity").to_csv(out / f"equity_{arch.name}_{name}.csv")
            ent.to_csv(out / f"entries_{arch.name}_{name}.csv", index=False)
            tr.to_csv(out / f"trades_{arch.name}_{name}.csv", index=False)
            sim["promotions"].to_csv(out / f"promotions_{arch.name}_{name}.csv", index=False)
            sim["slot_log"].to_csv(out / f"slot_log_{arch.name}_{name}.csv", index=False)

        result["architectures"][arch.name]["bootstrap_liq_vs_base"] = base.bootstrap_block_win(
            sims[(arch.name, "LIQ_ACCEL")]["equity"], sims[(arch.name, "BASE")]["equity"], block=20, reps=10000, seed=91001 if arch.name == "WITHIN12" else 91002
        )
        for name in ("BASE", "LIQ_ACCEL"):
            print(f"SIM COST10 {arch.name} {name}", flush=True)
            sc = simulate(meta, m, peer_ctx, radar, scores[name], name, arch, TCOST_BPS)
            result["architectures"][arch.name]["cost10bps"][name] = {
                "metrics": base.slice_metrics(sc["equity"]),
                "cagr_drag": float(base.metrics(sc["equity"])["cagr"] - base.metrics(sims[(arch.name, name)]["equity"])["cagr"]),
            }

    # Predeclare final decision from the primary architecture without tuning on secondary architectures.
    pbase = result["architectures"]["WITHIN12"]["variants"]["BASE"]
    pliq = result["architectures"]["WITHIN12"]["variants"]["LIQ_ACCEL"]
    mb = pbase["metrics"]["confirmation"]; ml = pliq["metrics"]["confirmation"]
    cb = pbase["labels"]["LABEL_DDV20"]["oos_2021_2025"]; cl = pliq["labels"]["LABEL_DDV20"]["oos_2021_2025"]
    result["decision_inputs_primary"] = {
        "oos_cagr_delta": (float(ml["cagr"]) - float(mb["cagr"])) if ml.get("cagr") is not None and mb.get("cagr") is not None else None,
        "oos_mdd_delta": (float(ml["mdd"]) - float(mb["mdd"])) if ml.get("mdd") is not None and mb.get("mdd") is not None else None,
        "label20_le30_delta": float(cl["le30_rate"] - cb["le30_rate"]),
        "label20_le50_delta": float(cl["le50_rate"] - cb["le50_rate"]),
        "base_capture": cb, "liq_capture": cl,
    }

    path = out / "summary_early1_operational_final.json"
    path.write_text(json.dumps(safe(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== EARLY1_OPERATIONAL_FINAL_JSON ===", flush=True)
    print(json.dumps(safe(result), ensure_ascii=False, indent=2), flush=True)
    print("=== END_EARLY1_OPERATIONAL_FINAL_JSON ===", flush=True)


if __name__ == "__main__":
    main()
