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

CORE_ATTACK = 9
EMERGING_ATTACK = 3
CORE_SELECTIVE = 3
EMERGING_SELECTIVE = 1

VARIANTS: dict[str, dict[str, Any]] = {
    "R21_85_THEME": {"r21": 85.0, "r42": None, "theme": None, "rise50": False, "score": "R21_THEME"},
    "R21_80_THEME": {"r21": 80.0, "r42": None, "theme": None, "rise50": False, "score": "R21_THEME"},
    "R21_85_T60": {"r21": 85.0, "r42": None, "theme": 60.0, "rise50": False, "score": "R21_THEME"},
    "R21_80_T60": {"r21": 80.0, "r42": None, "theme": 60.0, "rise50": False, "score": "R21_THEME"},
    "RECENT_ANY85": {"r21": None, "r42": None, "theme": None, "rise50": False, "score": "RECENT_THEME", "any85": True},
    "R21_85_ACCEL": {"r21": 85.0, "r42": None, "theme": None, "rise50": False, "score": "ACCEL_THEME"},
    "R21_80_ACCEL": {"r21": 80.0, "r42": None, "theme": None, "rise50": False, "score": "ACCEL_THEME"},
    "R21_80_ACCEL_T60": {"r21": 80.0, "r42": None, "theme": 60.0, "rise50": False, "score": "ACCEL_THEME"},
    "R21_85_THEME_RISE50": {"r21": 85.0, "r42": None, "theme": None, "rise50": True, "score": "R21_THEME"},
    "R21_80_ACCEL_RISE50": {"r21": 80.0, "r42": None, "theme": None, "rise50": True, "score": "ACCEL_THEME"},
}


def theme_score_series(peer_ctx: dict[str, Any], d: pd.Timestamp, columns: list[str]) -> pd.Series:
    di = peer_ctx["date_pos"].get(pd.Timestamp(d))
    if di is None:
        return pd.Series(np.nan, index=columns, dtype=float)
    arr = peer_ctx["best_score"][di]
    out = pd.Series(np.nan, index=columns, dtype=float)
    for sym in columns:
        si = peer_ctx["stock_pos"].get(sym)
        if si is not None:
            x = float(arr[si])
            if np.isfinite(x):
                out.at[sym] = x
    return out


def emerging_candidates(
    d: pd.Timestamp,
    cfg: dict[str, Any],
    matrices: dict[str, pd.DataFrame],
    pool: pd.DataFrame,
    rsm: dict[int, pd.DataFrame],
    accel_pct: pd.DataFrame,
    peer_ctx: dict[str, Any],
    exclude: set[str],
    n: int = 12,
) -> list[tuple[str, dict[str, Any]]]:
    cols = list(matrices["close"].columns)
    c = matrices["close"].loc[d]
    s50 = matrices["sma50"].loc[d]
    mask = pool.loc[d].fillna(False) & c.gt(s50).fillna(False)
    if cfg.get("rise50"):
        mask &= s50.gt(matrices["sma50"].shift(20).loc[d]).fillna(False)
    r21 = rsm[21].loc[d]
    r42 = rsm[42].loc[d]
    r63 = rsm[63].loc[d]
    if cfg.get("any85"):
        mask &= ((r21 >= 85.0) | (r42 >= 85.0) | (r63 >= 85.0)).fillna(False)
    else:
        if cfg.get("r21") is not None:
            mask &= (r21 >= float(cfg["r21"])).fillna(False)
        if cfg.get("r42") is not None:
            mask &= (r42 >= float(cfg["r42"])).fillna(False)
    theme = theme_score_series(peer_ctx, d, cols)
    if cfg.get("theme") is not None:
        mask &= (theme >= float(cfg["theme"])).fillna(False)
    if exclude:
        common = list(set(exclude) & set(mask.index))
        if common:
            mask.loc[common] = False
    if not mask.any():
        return []
    theme_use = theme.fillna(50.0)
    r21_use = r21.fillna(50.0)
    r42_use = r42.fillna(50.0)
    if cfg["score"] == "R21_THEME":
        score = 0.70 * r21_use + 0.30 * theme_use
    elif cfg["score"] == "RECENT_THEME":
        recent = 0.50 * r21_use + 0.30 * r42_use + 0.20 * r63.fillna(50.0)
        score = 0.70 * recent + 0.30 * theme_use
    elif cfg["score"] == "ACCEL_THEME":
        acc = accel_pct.loc[d].fillna(50.0)
        score = 0.50 * r21_use + 0.20 * acc + 0.30 * theme_use
    else:
        raise ValueError(cfg["score"])
    ranked = score.where(mask).dropna().sort_values(ascending=False).head(n)
    out: list[tuple[str, dict[str, Any]]] = []
    for sym, sc in ranked.items():
        out.append((str(sym), {
            "emerging_score": float(sc),
            "rs21": float(r21.get(sym)) if pd.notna(r21.get(sym)) else None,
            "rs42": float(r42.get(sym)) if pd.notna(r42.get(sym)) else None,
            "theme_score": float(theme.get(sym)) if pd.notna(theme.get(sym)) else None,
            "accel_pct": float(accel_pct.at[d, sym]) if pd.notna(accel_pct.at[d, sym]) else None,
        }))
    return out


def metrics_from(eq: pd.Series, start: str) -> dict[str, Any]:
    return base.metrics(eq.loc[eq.index >= pd.Timestamp(start)])


def simulate(
    meta: dict[str, Any], matrices: dict[str, pd.DataFrame], peer_ctx: dict[str, Any],
    pool: pd.DataFrame, rsm: dict[int, pd.DataFrame], accel_pct: pd.DataFrame,
    cfg: dict[str, Any], name: str,
) -> dict[str, Any]:
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
                    pc = delay.px(closes, prev, sym, p["entry_price"])
                    if pc is None:
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

            # Promote an Emerging holding when it becomes one of the current Core candidates and there is Core room.
            core_count = sum(p["sleeve"] == "CORE" for p in pos.values())
            if core_cap > 0 and core_count < core_cap:
                for sym in core_symbols:
                    if core_count >= core_cap:
                        break
                    if sym in pos and pos[sym]["sleeve"] == "EMERGING":
                        pos[sym]["sleeve"] = "CORE"
                        pos[sym]["promoted"] = True
                        core_count += 1

            em_count = sum(p["sleeve"] == "EMERGING" for p in pos.values())
            nav_open = cash
            for sym, p in pos.items():
                opx = delay.px(opens, d, sym, delay.px(closes, prev, sym, p["entry_price"]))
                if opx is not None:
                    nav_open += p["shares"] * opx
            slot_cash = nav_open / 12.0

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
                    pos[sym] = {"sleeve": "CORE", "shares": alloc / opx, "entry_price": opx, "entry_date": d, "peak_close": opx, "partial_done": False, "promoted": False}
                    entries.append({"variant": name, "symbol": sym, "sleeve": "CORE", "signal_date": prev, "entry_date": d, "entry_price": opx, "rank": rank, **cmeta})
                    core_count += 1

            em_count = sum(p["sleeve"] == "EMERGING" for p in pos.values())
            if (not red_force) and em_cap > 0 and em_count < em_cap:
                exclude = set(pos) | set(core_symbols[:max(core_cap, 0)])
                ecands = emerging_candidates(prev, cfg, matrices, pool, rsm, accel_pct, peer_ctx, exclude, n=12)
                for rank, (sym, emeta) in enumerate(ecands, start=1):
                    if em_count >= em_cap or cash <= 1e-10:
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
                    pos[sym] = {"sleeve": "EMERGING", "shares": alloc / opx, "entry_price": opx, "entry_date": d, "peak_close": opx, "partial_done": False, "promoted": False}
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

    eq = pd.Series(dict(equities), dtype=float).sort_index()
    return {"equity": eq, "entries": pd.DataFrame(entries), "exits": pd.DataFrame(exits)}


def leader_capture(events: pd.DataFrame, entries: pd.DataFrame, start_year: int | None = None, end_year: int | None = None) -> dict[str, Any]:
    ev = events.copy()
    if start_year is not None:
        ev = ev[ev["year"] >= start_year]
    if end_year is not None:
        ev = ev[ev["year"] <= end_year]
    if ev.empty:
        return {"n": 0}
    eg = {str(k): v.sort_values("entry_date") for k, v in entries.groupby("symbol")} if len(entries) else {}
    gains: list[float] = []
    captured_flags: list[bool] = []
    within30: list[bool] = []
    within50: list[bool] = []
    before100: list[bool] = []
    emerg_hits = 0
    for r in ev.itertuples(index=False):
        sym = str(r.symbol)
        g = eg.get(sym)
        hit = None
        if g is not None:
            z = g[(g["entry_date"] >= pd.Timestamp(r.anchor_date)) & (g["entry_date"] <= pd.Timestamp(r.final_date))]
            if len(z):
                hit = z.iloc[0]
        if hit is None:
            captured_flags.append(False); within30.append(False); within50.append(False); before100.append(False)
            continue
        gain = float(hit["entry_price"] / float(r.anchor_price) - 1.0)
        gains.append(gain)
        captured_flags.append(True)
        within30.append(gain <= 0.30); within50.append(gain <= 0.50); before100.append(gain < 1.00)
        emerg_hits += int(str(hit["sleeve"]) == "EMERGING")
    n = len(ev)
    return {
        "n": int(n),
        "captured": int(sum(captured_flags)),
        "capture_rate": float(np.mean(captured_flags)),
        "capture_by_30_rate": float(np.mean(within30)),
        "capture_by_50_rate": float(np.mean(within50)),
        "capture_before_100_rate": float(np.mean(before100)),
        "entry_gain_median": float(np.median(gains)) if gains else None,
        "entry_gain_p75": float(np.quantile(gains, 0.75)) if gains else None,
        "emerging_first_entries": int(emerg_hits),
    }


def pack_variant(name: str, sim: dict[str, Any], events: pd.DataFrame) -> dict[str, Any]:
    eq, entries = sim["equity"], sim["entries"]
    complete = events[events["complete_year"]].copy()
    top5 = complete[complete["top5"]]
    p200 = complete[complete["cohort_200_400"]]
    p400 = complete[complete["cohort_400plus"]]
    return {
        "metrics_full": base.metrics(eq),
        "metrics_2021_plus": metrics_from(eq, "2021-01-01"),
        "metrics_2022_plus": metrics_from(eq, "2022-01-03"),
        "entry_count": int(len(entries)),
        "emerging_entry_count": int((entries["sleeve"] == "EMERGING").sum()) if len(entries) else 0,
        "leaders": {
            "TOP1_5_2016_2025": leader_capture(top5, entries),
            "TOP1_5_2016_2020": leader_capture(top5, entries, 2016, 2020),
            "TOP1_5_2021_2025": leader_capture(top5, entries, 2021, 2025),
            "ALL_200_400_2016_2025": leader_capture(p200, entries),
            "ALL_400PLUS_2016_2025": leader_capture(p400, entries),
        },
    }


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
    print("BUILD RS", flush=True)
    rsm = delay.rs_matrices(matrices["close"], pool)
    accel_pct = (rsm[21] - rsm[63]).rank(axis=1, pct=True, method="average") * 100.0
    events = delay.annual_leader_events(matrices["close"], pool, pd.DatetimeIndex(meta["analysis_idx"]), True)

    result: dict[str, Any] = {
        "status": "EMERGING_EARLY_ENTRY_GRID",
        "scope": "research only; main/production/UI untouched",
        "fixed": "9 Core + 3 Emerging; Selective 3+1; daily next-open refill; current Core rank; hard -8%, +24%/25% partial, peak-close -30%, Red full exit",
        "emerging_common": "tradable pool + Close>SMA50; Emerging can catch both pre-Core and Core-ranking misses; promotion to Core when Core-ranked and Core room exists",
        "variants": {},
    }
    for name, cfg in VARIANTS.items():
        print(f"SIM {name}", flush=True)
        sim = simulate(meta, matrices, peer_ctx, pool, rsm, accel_pct, cfg, name)
        result["variants"][name] = pack_variant(name, sim, events)
        sim["entries"].to_csv(out / f"entries_{name}.csv", index=False)
        sim["exits"].to_csv(out / f"exits_{name}.csv", index=False)
        sim["equity"].rename("equity").to_csv(out / f"equity_{name}.csv")

    # Sortable compact table, but do not auto-adopt any variant.
    rows = []
    for name, v in result["variants"].items():
        l = v["leaders"]["TOP1_5_2016_2025"]
        rows.append({
            "variant": name,
            "cagr_full": v["metrics_full"].get("cagr"), "mdd_full": v["metrics_full"].get("mdd"),
            "cagr_2021_plus": v["metrics_2021_plus"].get("cagr"), "mdd_2021_plus": v["metrics_2021_plus"].get("mdd"),
            "top5_capture": l.get("capture_rate"), "top5_by30": l.get("capture_by_30_rate"),
            "top5_by50": l.get("capture_by_50_rate"), "top5_entry_gain_median": l.get("entry_gain_median"),
            "entries": v["entry_count"], "emerging_entries": v["emerging_entry_count"],
        })
    table = pd.DataFrame(rows).sort_values(["top5_by30", "top5_capture", "cagr_2021_plus"], ascending=False)
    table.to_csv(out / "variant_comparison.csv", index=False)
    result["comparison_sorted"] = table.to_dict(orient="records")
    (out / "summary_emerging_early_entry_grid.json").write_text(json.dumps(base.safe(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== EMERGING_EARLY_ENTRY_GRID_JSON ===", flush=True)
    print(json.dumps(base.safe({"status": result["status"], "comparison_sorted": result["comparison_sorted"]}), ensure_ascii=False, indent=2), flush=True)
    print("=== END_EMERGING_EARLY_ENTRY_GRID_JSON ===", flush=True)


if __name__ == "__main__":
    main()
