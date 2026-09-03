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
import audit_major_leader_entry_delay as delay
import audit_emerging_early_entry_grid as grid

CORE_ATTACK = 9
EMERGING_ATTACK = 3
CORE_SELECTIVE = 3
EMERGING_SELECTIVE = 1

VARIANTS: dict[str, dict[str, Any]] = {
    "FRESH5_RECENT": {"fresh": 5, "hold": 5, "score": "RECENT_THEME"},
    "FRESH10_RECENT": {"fresh": 10, "hold": 10, "score": "RECENT_THEME"},
    "FRESH20_RECENT": {"fresh": 20, "hold": 20, "score": "RECENT_THEME"},
    "FRESH5_ACCEL": {"fresh": 5, "hold": 5, "score": "ACCEL_THEME"},
    "FRESH10_ACCEL": {"fresh": 10, "hold": 10, "score": "ACCEL_THEME"},
    "FRESH20_ACCEL": {"fresh": 20, "hold": 20, "score": "ACCEL_THEME"},
}


def build_radar_age(pool: pd.DataFrame, close: pd.DataFrame, sma50: pd.DataFrame, rsm: dict[int, pd.DataFrame]) -> pd.DataFrame:
    signal = (
        pool.fillna(False)
        & close.gt(sma50).fillna(False)
        & ((rsm[21] >= 85.0) | (rsm[42] >= 85.0) | (rsm[63] >= 85.0)).fillna(False)
    )
    a = signal.to_numpy(bool)
    age = np.full(a.shape, 32767, dtype=np.int16)
    prev = np.zeros(a.shape[1], dtype=bool)
    prev_age = np.full(a.shape[1], 32767, dtype=np.int16)
    for i in range(a.shape[0]):
        cur = a[i]
        new = cur & ~prev
        cont = cur & prev
        row = np.full(a.shape[1], 32767, dtype=np.int16)
        row[new] = 0
        row[cont] = np.minimum(prev_age[cont] + 1, 32766)
        age[i] = row
        prev = cur
        prev_age = row
    return pd.DataFrame(age, index=signal.index, columns=signal.columns)


def fresh_candidates(
    d: pd.Timestamp,
    cfg: dict[str, Any],
    matrices: dict[str, pd.DataFrame],
    rsm: dict[int, pd.DataFrame],
    accel_pct: pd.DataFrame,
    peer_ctx: dict[str, Any],
    radar_age: pd.DataFrame,
    exclude: set[str],
    n: int = 12,
) -> list[tuple[str, dict[str, Any]]]:
    cols = list(matrices["close"].columns)
    age = radar_age.loc[d]
    mask = age.le(int(cfg["fresh"]))
    if exclude:
        common = list(set(exclude) & set(mask.index))
        if common:
            mask.loc[common] = False
    if not mask.any():
        return []

    r21 = rsm[21].loc[d].fillna(50.0)
    r42 = rsm[42].loc[d].fillna(50.0)
    r63 = rsm[63].loc[d].fillna(50.0)
    theme = grid.theme_score_series(peer_ctx, d, cols).fillna(50.0)
    freshness = (100.0 - 5.0 * age.clip(lower=0, upper=20).astype(float)).where(mask, np.nan)
    if cfg["score"] == "RECENT_THEME":
        recent = 0.50 * r21 + 0.30 * r42 + 0.20 * r63
        score = 0.50 * recent + 0.25 * theme + 0.25 * freshness
    elif cfg["score"] == "ACCEL_THEME":
        acc = accel_pct.loc[d].fillna(50.0)
        score = 0.40 * r21 + 0.20 * acc + 0.20 * theme + 0.20 * freshness
    else:
        raise ValueError(cfg["score"])
    ranked = score.where(mask).dropna().sort_values(ascending=False).head(n)
    out = []
    for sym, sc in ranked.items():
        out.append((str(sym), {
            "emerging_score": float(sc),
            "radar_age": int(age.at[sym]),
            "rs21": float(r21.at[sym]),
            "rs42": float(r42.at[sym]),
            "rs63": float(r63.at[sym]),
            "theme_score": float(theme.at[sym]),
            "accel_pct": float(accel_pct.at[d, sym]) if pd.notna(accel_pct.at[d, sym]) else None,
        }))
    return out


def simulate(meta, matrices, peer_ctx, rsm, accel_pct, radar_age, cfg, name):
    idx = pd.DatetimeIndex(meta["analysis_idx"])
    opens, closes = matrices["open"], matrices["close"]
    cash = 1.0
    pos: dict[str, dict[str, Any]] = {}
    equities: list[tuple[pd.Timestamp, float]] = []
    entries: list[dict[str, Any]] = []
    exits: list[dict[str, Any]] = []
    red_run = 0

    def close_position(sym: str, date: pd.Timestamp, price: float, reason: str) -> None:
        nonlocal cash
        p = pos.pop(sym)
        cash += p["shares"] * price
        exits.append({"variant": name, "symbol": sym, "sleeve": p["sleeve"], "entry_date": p["entry_date"], "exit_date": date, "entry_price": p["entry_price"], "exit_price": price, "return": price / p["entry_price"] - 1.0, "reason": reason})

    for i, d0 in enumerate(idx):
        d = pd.Timestamp(d0)
        prev = None if i == 0 else pd.Timestamp(idx[i - 1])
        if prev is not None:
            color, bucket, _ = delay.market_state(meta, prev)
            red_run = red_run + 1 if color == "Red" else 0
            red_force = color == "Red" and red_run >= 1

            if red_force:
                for sym in list(pos):
                    opx = delay.px(opens, d, sym, delay.px(closes, prev, sym, pos[sym]["entry_price"]))
                    if opx is not None:
                        close_position(sym, d, opx, "RED")
            else:
                for sym in list(pos):
                    p = pos[sym]
                    p["sessions"] += 1
                    pc = delay.px(closes, prev, sym, p["entry_price"])
                    if pc is None:
                        continue
                    if p["sleeve"] == "EMERGING" and p["sessions"] >= int(cfg["hold"]):
                        opx = delay.px(opens, d, sym, pc)
                        if opx is not None:
                            close_position(sym, d, opx, "RADAR_EXPIRE")
                        continue
                    if (not p["partial_done"]) and pc >= p["entry_price"] * 1.24:
                        opx = delay.px(opens, d, sym, pc)
                        if opx is not None:
                            sold = p["shares"] * 0.25
                            cash += sold * opx
                            p["shares"] -= sold
                            p["partial_done"] = True
                    stop = max(p["entry_price"] * 0.92, p["peak_close"] * 0.70)
                    if pc <= stop:
                        opx = delay.px(opens, d, sym, pc)
                        if opx is not None:
                            close_position(sym, d, opx, "STOP")

            if color in ("Blue", "Green") and bucket == 2:
                core_cap, em_cap = CORE_ATTACK, EMERGING_ATTACK
            elif color in ("Blue", "Green") and bucket == 1:
                core_cap, em_cap = CORE_SELECTIVE, EMERGING_SELECTIVE
            else:
                core_cap, em_cap = 0, 0

            core_candidates = ex.ranked_candidates(prev, matrices, peer_ctx, bucket, base.N_PORT) if core_cap > 0 else []
            core_symbols = [str(s) for s, _ in core_candidates]

            core_count = sum(p["sleeve"] == "CORE" for p in pos.values())
            if core_cap > 0 and core_count < core_cap:
                for sym in core_symbols:
                    if core_count >= core_cap:
                        break
                    if sym in pos and pos[sym]["sleeve"] == "EMERGING":
                        pos[sym]["sleeve"] = "CORE"
                        pos[sym]["promoted"] = True
                        core_count += 1

            nav_open = cash
            for sym, p in pos.items():
                opx = delay.px(opens, d, sym, delay.px(closes, prev, sym, p["entry_price"]))
                if opx is not None:
                    nav_open += p["shares"] * opx
            slot_cash = nav_open / 12.0

            core_count = sum(p["sleeve"] == "CORE" for p in pos.values())
            if (not red_force) and core_cap > 0 and core_count < core_cap:
                for rank, (sym0, cmeta) in enumerate(core_candidates, start=1):
                    sym = str(sym0)
                    if core_count >= core_cap or cash <= 1e-10:
                        break
                    if sym in pos:
                        continue
                    opx = delay.px(opens, d, sym, delay.px(closes, prev, sym, None))
                    if opx is None:
                        continue
                    alloc = min(slot_cash, cash)
                    if alloc <= 1e-10:
                        break
                    cash -= alloc
                    pos[sym] = {"sleeve": "CORE", "shares": alloc / opx, "entry_price": opx, "entry_date": d, "peak_close": opx, "partial_done": False, "promoted": False, "sessions": 0}
                    entries.append({"variant": name, "symbol": sym, "sleeve": "CORE", "signal_date": prev, "entry_date": d, "entry_price": opx, "rank": rank, **cmeta})
                    core_count += 1

            em_count = sum(p["sleeve"] == "EMERGING" for p in pos.values())
            if (not red_force) and em_cap > 0 and em_count < em_cap:
                exclude = set(pos) | set(core_symbols[:max(core_cap, 0)])
                ecands = fresh_candidates(prev, cfg, matrices, rsm, accel_pct, peer_ctx, radar_age, exclude, n=12)
                for rank, (sym, emeta) in enumerate(ecands, start=1):
                    if em_count >= em_cap or cash <= 1e-10:
                        break
                    opx = delay.px(opens, d, sym, delay.px(closes, prev, sym, None))
                    if opx is None:
                        continue
                    alloc = min(slot_cash, cash)
                    if alloc <= 1e-10:
                        break
                    cash -= alloc
                    pos[sym] = {"sleeve": "EMERGING", "shares": alloc / opx, "entry_price": opx, "entry_date": d, "peak_close": opx, "partial_done": False, "promoted": False, "sessions": 0}
                    entries.append({"variant": name, "symbol": sym, "sleeve": "EMERGING", "signal_date": prev, "entry_date": d, "entry_price": opx, "rank": rank, **emeta})
                    em_count += 1

        nav = cash
        for sym, p in pos.items():
            cp = delay.px(closes, d, sym, delay.px(opens, d, sym, p["entry_price"]))
            if cp is None:
                cp = p["entry_price"]
            p["peak_close"] = max(p["peak_close"], cp)
            nav += p["shares"] * cp
        equities.append((d, nav))

    return {"equity": pd.Series(dict(equities), dtype=float).sort_index(), "entries": pd.DataFrame(entries), "exits": pd.DataFrame(exits)}


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
    pool = delay.current_base_pool(root, matrices)
    rsm = delay.rs_matrices(matrices["close"], pool)
    accel_pct = (rsm[21] - rsm[63]).rank(axis=1, pct=True, method="average") * 100.0
    print("BUILD FRESH RADAR AGE", flush=True)
    radar_age = build_radar_age(pool, matrices["close"], matrices["sma50"], rsm)
    events = delay.annual_leader_events(matrices["close"], pool, pd.DatetimeIndex(meta["analysis_idx"]), True)

    result: dict[str, Any] = {
        "status": "EMERGING_FRESH_RADAR_ROTATION",
        "scope": "research only; main/production/UI untouched",
        "fixed": "9 Core + 3 Emerging; Selective 3+1; current Core unchanged; next-open execution; same hard -8%, +24%/25% partial, peak-close -30%, Red exit",
        "change_under_test": "Emerging only: candidate must be within N sessions of a new any(RS21,RS42,RS63)>=85 radar crossing while Close>SMA50; if not promoted to Core, release slot after N sessions",
        "variants": {},
    }
    rows = []
    for name, cfg in VARIANTS.items():
        print(f"SIM {name}", flush=True)
        sim = simulate(meta, matrices, peer_ctx, rsm, accel_pct, radar_age, cfg, name)
        packed = grid.pack_variant(name, sim, events)
        result["variants"][name] = packed
        sim["entries"].to_csv(out / f"entries_{name}.csv", index=False)
        sim["exits"].to_csv(out / f"exits_{name}.csv", index=False)
        sim["equity"].rename("equity").to_csv(out / f"equity_{name}.csv")
        l5 = packed["leaders"]["TOP1_5_2016_2025"]
        l400 = packed["leaders"]["ALL_400PLUS_2016_2025"]
        rows.append({
            "variant": name,
            "cagr_2021_plus": packed["metrics_2021_plus"].get("cagr"),
            "mdd_2021_plus": packed["metrics_2021_plus"].get("mdd"),
            "top5_capture": l5.get("capture_rate"),
            "top5_by30": l5.get("capture_by_30_rate"),
            "top5_by50": l5.get("capture_by_50_rate"),
            "top5_entry_gain_median": l5.get("entry_gain_median"),
            "plus400_capture": l400.get("capture_rate"),
            "plus400_by30": l400.get("capture_by_30_rate"),
            "plus400_entry_gain_median": l400.get("entry_gain_median"),
            "entries": packed["entry_count"],
            "emerging_entries": packed["emerging_entry_count"],
        })
    table = pd.DataFrame(rows).sort_values(["top5_by30", "plus400_by30", "top5_capture", "cagr_2021_plus"], ascending=False)
    result["comparison_sorted"] = table.to_dict(orient="records")
    table.to_csv(out / "fresh_radar_comparison.csv", index=False)
    (out / "summary_emerging_fresh_radar_rotation.json").write_text(json.dumps(base.safe(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== FRESH_RADAR_ROTATION_JSON ===", flush=True)
    print(json.dumps(base.safe({"status": result["status"], "comparison_sorted": result["comparison_sorted"]}), ensure_ascii=False, indent=2), flush=True)
    print("=== END_FRESH_RADAR_ROTATION_JSON ===", flush=True)


if __name__ == "__main__":
    main()
