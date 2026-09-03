from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import audit_major_leader_entry_delay as delay
import audit_ordinary_stock_market_mode_robustness as base
import audit_ordinary_stock_theme_leave_one_out as loo
import audit_ordinary_stock_exit_trail as ex
import audit_early_leader_entry_candidates as early
import audit_radar_cohort_discriminator as disc


COST_BPS_PRIMARY = 10.0
LIQ_FLOORS = (10_000_000.0, 20_000_000.0, 50_000_000.0, 100_000_000.0)
SCORES = ("RS21", "RS21_HIGH63", "RS21_HIGH_ACCEL")
CONFIRMS = ("MID", "FULL")
GATES = ("CURRENT", "BG", "NOT_RED")
EARLY_MAX_DAYS = (5, 10)
ALLOCATIONS = (
    (9, 1, 2),
    (8, 1, 3),
    (8, 2, 2),
    (7, 2, 3),
    (7, 3, 2),
)
CONFIRMED_MAX_DAYS = 63


@dataclass(frozen=True)
class Config:
    core_cap: int
    confirmed_cap: int
    early_cap: int
    score: str
    confirm: str
    gate: str
    early_max_days: int

    @property
    def key(self) -> str:
        return (
            f"C{self.core_cap}F{self.confirmed_cap}E{self.early_cap}_"
            f"{self.score}_{self.confirm}_{self.gate}_D{self.early_max_days}"
        )


def safe(v: Any) -> Any:
    return base.safe(v)


def px(frame: pd.DataFrame, date: pd.Timestamp, sym: str, fallback: float | None = None) -> float | None:
    return delay.px(frame, date, sym, fallback)


def period_metrics(eq: pd.Series) -> dict[str, Any]:
    e = pd.to_numeric(eq, errors="coerce").dropna()
    parts = {
        "full_2016_2026": e,
        "dev_2016_2020": e.loc[(e.index >= "2016-01-01") & (e.index <= "2020-12-31")],
        "confirm_2021_2023": e.loc[(e.index >= "2021-01-01") & (e.index <= "2023-12-31")],
        "holdout_2024_2026": e.loc[e.index >= "2024-01-01"],
        "since_2021": e.loc[e.index >= "2021-01-01"],
    }
    return {k: base.metrics(v) for k, v in parts.items()}


def build_signal_context(root: Path, matrices: dict[str, pd.DataFrame]) -> dict[str, Any]:
    close = matrices["close"]
    pool = delay.current_base_pool(root, matrices).fillna(False)
    rs = delay.rs_matrices(close, pool)

    prior63 = close.shift(1).rolling(63, min_periods=40).max()
    high63 = disc.percentile(close / prior63, pool)
    acc21 = disc.percentile(rs[21] - rs[21].shift(20), pool)
    ema21 = close.ewm(span=21, adjust=False, min_periods=15).mean()

    scores = {
        "RS21": rs[21].astype(np.float32),
        "RS21_HIGH63": (0.75 * rs[21] + 0.25 * high63).astype(np.float32),
        "RS21_HIGH_ACCEL": (0.50 * rs[21] + 0.25 * high63 + 0.25 * acc21).astype(np.float32),
    }

    radar = (pool & ((rs[21] >= 85.0) | (rs[42] >= 85.0) | (rs[63] >= 85.0))).fillna(False)
    fresh = (radar & ~radar.shift(1).fillna(False)).fillna(False)
    active5 = fresh.rolling(5, min_periods=1).max().fillna(False).astype(bool)

    mid = (
        pool
        & matrices["sma50"].notna()
        & matrices["sma200"].notna()
        & (close >= matrices["sma50"])
        & (matrices["sma50"] > matrices["sma200"])
        & (rs[21] >= 85.0)
    ).fillna(False)
    full = matrices["new_eligible"].fillna(False)

    return {
        "pool": pool,
        "rs": rs,
        "high63": high63,
        "acc21": acc21,
        "ema21": ema21,
        "scores": scores,
        "fresh": fresh,
        "active5": active5,
        "confirm_masks": {"MID": mid, "FULL": full},
    }


def precompute_candidates(
    meta: dict[str, Any],
    matrices: dict[str, pd.DataFrame],
    peer_ctx: dict[str, Any],
    ctx: dict[str, Any],
) -> tuple[
    dict[pd.Timestamp, list[tuple[str, dict[str, Any]]]],
    dict[pd.Timestamp, list[tuple[str, dict[str, Any]]]],
    dict[str, dict[pd.Timestamp, list[tuple[str, float]]]],
]:
    idx = pd.DatetimeIndex(meta["analysis_idx"])
    attack: dict[pd.Timestamp, list[tuple[str, dict[str, Any]]]] = {}
    selective: dict[pd.Timestamp, list[tuple[str, dict[str, Any]]]] = {}
    for i, d0 in enumerate(idx):
        d = pd.Timestamp(d0)
        attack[d] = loo.peer_ranked_candidates(d, matrices, peer_ctx, 40)
        selective[d] = loo.stock_only_candidates(d, matrices, 40)
        if (i + 1) % 400 == 0:
            print(f"CORE_CANDS {i + 1}/{len(idx)}", flush=True)

    early_by_score: dict[str, dict[pd.Timestamp, list[tuple[str, float]]]] = {}
    active = ctx["active5"]
    for name, score in ctx["scores"].items():
        by_date: dict[pd.Timestamp, list[tuple[str, float]]] = {}
        for i, d0 in enumerate(idx):
            d = pd.Timestamp(d0)
            s = pd.to_numeric(score.loc[d].where(active.loc[d]), errors="coerce").dropna().nlargest(40)
            by_date[d] = [(str(sym), float(val)) for sym, val in s.items()]
            if (i + 1) % 700 == 0:
                print(f"EARLY_CANDS {name} {i + 1}/{len(idx)}", flush=True)
        early_by_score[name] = by_date
    return attack, selective, early_by_score


def gate_allowed(meta: dict[str, Any], d: pd.Timestamp, gate: str) -> bool:
    color, bucket, _ = delay.market_state(meta, d)
    if gate == "CURRENT":
        return bool(color in ("Blue", "Green") and bucket >= 1)
    if gate == "BG":
        return bool(color in ("Blue", "Green"))
    if gate == "NOT_RED":
        return bool(color != "Red")
    raise ValueError(gate)


def entry_band(dvol: float | None) -> str:
    if dvol is None or not np.isfinite(dvol):
        return "UNKNOWN"
    if dvol < 20_000_000:
        return "10_20M"
    if dvol < 50_000_000:
        return "20_50M"
    if dvol < 100_000_000:
        return "50_100M"
    return "100M_PLUS"


def simulate(
    config: Config | None,
    meta: dict[str, Any],
    matrices: dict[str, pd.DataFrame],
    ctx: dict[str, Any],
    core_attack: dict[pd.Timestamp, list[tuple[str, dict[str, Any]]]],
    core_selective: dict[pd.Timestamp, list[tuple[str, dict[str, Any]]]],
    early_by_score: dict[str, dict[pd.Timestamp, list[tuple[str, float]]]],
    *,
    liq_floor: float = 10_000_000.0,
    cost_bps: float = COST_BPS_PRIMARY,
) -> dict[str, Any]:
    idx = pd.DatetimeIndex(meta["analysis_idx"])
    opens, closes, dvol = matrices["open"], matrices["close"], matrices["dvol"]
    cost = float(cost_bps) / 10_000.0
    is_core12 = config is None

    cash = 1.0
    pos: dict[str, dict[str, Any]] = {}
    equity: list[tuple[pd.Timestamp, float]] = []
    entries: list[dict[str, Any]] = []
    intervals: list[dict[str, Any]] = []
    red_run = 0
    promoted_confirmed = 0
    promoted_core = 0

    index_pos = {pd.Timestamp(d): i for i, d in enumerate(idx)}

    def eff_buy(raw: float) -> float:
        return raw * (1.0 + cost)

    def eff_sell(raw: float) -> float:
        return raw * (1.0 - cost)

    def close_position(sym: str, date: pd.Timestamp, raw_price: float, reason: str) -> None:
        nonlocal cash
        p = pos.pop(sym)
        sell = eff_sell(raw_price)
        proceeds = float(p["shares"]) * sell
        cash += proceeds
        total_proceeds = float(p["partial_proceeds"]) + proceeds
        intervals.append({
            "symbol": sym,
            "entry_date": p["entry_date"],
            "exit_date": date,
            "entry_price": p["entry_price"],
            "exit_price": sell,
            "entry_sleeve": p["entry_sleeve"],
            "final_sleeve": p["sleeve"],
            "exit_reason": reason,
            "initial_alloc": p["initial_alloc"],
            "realized_return": total_proceeds / p["initial_alloc"] - 1.0 if p["initial_alloc"] > 0 else np.nan,
            "entry_dvol": p["entry_dvol"],
            "entry_dvol_band": entry_band(p["entry_dvol"]),
            "entry_score": p.get("entry_score"),
            "partial_done": p["partial_done"],
        })

    def nav_open_value(date: pd.Timestamp, prev: pd.Timestamp) -> float:
        total = cash
        for sym, p in pos.items():
            raw = px(opens, date, sym, px(closes, prev, sym, p["entry_price"]))
            if raw is not None:
                total += p["shares"] * raw
        return total

    for i, d0 in enumerate(idx):
        d = pd.Timestamp(d0)
        prev = None if i == 0 else pd.Timestamp(idx[i - 1])
        if prev is not None:
            color, bucket, _ = delay.market_state(meta, prev)
            red_run = red_run + 1 if color == "Red" else 0
            red_force = color == "Red" and red_run >= 1

            if red_force:
                for sym in list(pos):
                    raw = px(opens, d, sym, px(closes, prev, sym, pos[sym]["entry_price"]))
                    if raw is not None:
                        close_position(sym, d, raw, "RED")
            else:
                for sym in list(pos):
                    p = pos[sym]
                    pc = px(closes, prev, sym, p["entry_price"])
                    if pc is None:
                        continue

                    age = index_pos[prev] - index_pos[p["entry_signal_date"]]
                    if p["sleeve"] == "EARLY" and (not is_core12) and age >= config.early_max_days:
                        raw = px(opens, d, sym, pc)
                        if raw is not None:
                            close_position(sym, d, raw, "EARLY_EXPIRY")
                        continue
                    if p["sleeve"] == "CONFIRMED" and age >= CONFIRMED_MAX_DAYS:
                        raw = px(opens, d, sym, pc)
                        if raw is not None:
                            close_position(sym, d, raw, "CONFIRMED_EXPIRY")
                        continue

                    if (not p["partial_done"]) and pc >= p["entry_price"] * 1.24:
                        raw = px(opens, d, sym, pc)
                        if raw is not None:
                            sell = eff_sell(raw)
                            sold = p["shares"] * 0.25
                            proceeds = sold * sell
                            cash += proceeds
                            p["partial_proceeds"] += proceeds
                            p["shares"] -= sold
                            p["partial_done"] = True

                    stop = max(p["entry_price"] * 0.92, p["peak_close"] * 0.70)
                    if pc <= stop and sym in pos:
                        raw = px(opens, d, sym, pc)
                        if raw is not None:
                            close_position(sym, d, raw, "STOP")

            if not red_force:
                bull = color in ("Blue", "Green")
                if is_core12:
                    core_cap = 12 if bull and bucket == 2 else 4 if bull and bucket == 1 else 0
                    confirmed_cap = 0
                    early_cap = 0
                else:
                    core_cap = config.core_cap if bull and bucket == 2 else min(3, config.core_cap) if bull and bucket == 1 else 0
                    confirmed_cap = config.confirmed_cap
                    early_cap = config.early_cap if bucket == 2 else 1 if bucket == 1 else config.early_cap

                core_list_raw = core_attack.get(prev, []) if bucket == 2 else core_selective.get(prev, []) if bucket == 1 else []
                core_list = []
                for sym, info in core_list_raw:
                    dv = px(dvol, prev, str(sym), None)
                    if dv is not None and dv >= liq_floor:
                        core_list.append((str(sym), info))
                core_take = core_list[:core_cap]
                core_symbols = {s for s, _ in core_take}

                if not is_core12 and core_cap > 0:
                    core_count = sum(1 for p in pos.values() if p["sleeve"] == "CORE")
                    for sym in list(pos):
                        if core_count >= core_cap:
                            break
                        if pos[sym]["sleeve"] in ("EARLY", "CONFIRMED") and sym in core_symbols:
                            pos[sym]["sleeve"] = "CORE"
                            pos[sym]["core_date"] = d
                            promoted_core += 1
                            core_count += 1

                if not is_core12 and confirmed_cap > 0:
                    confirm_mask = ctx["confirm_masks"][config.confirm]
                    confirmed_count = sum(1 for p in pos.values() if p["sleeve"] == "CONFIRMED")
                    for sym in list(pos):
                        if confirmed_count >= confirmed_cap:
                            break
                        if pos[sym]["sleeve"] != "EARLY":
                            continue
                        try:
                            ok = bool(confirm_mask.at[prev, sym])
                        except Exception:
                            ok = False
                        dv = px(dvol, prev, sym, None)
                        if ok and dv is not None and dv >= liq_floor:
                            pos[sym]["sleeve"] = "CONFIRMED"
                            pos[sym]["confirmed_date"] = d
                            promoted_confirmed += 1
                            confirmed_count += 1

                if core_cap > 0:
                    core_count = sum(1 for p in pos.values() if p["sleeve"] == "CORE")
                    if core_count < core_cap:
                        slot_cash = nav_open_value(d, prev) / 12.0
                        for rank, (sym, info) in enumerate(core_take, start=1):
                            if core_count >= core_cap or cash <= 0:
                                break
                            if sym in pos:
                                continue
                            raw = px(opens, d, sym, px(closes, prev, sym, None))
                            if raw is None:
                                continue
                            buy = eff_buy(raw)
                            alloc = min(slot_cash, cash)
                            if alloc <= 1e-12:
                                break
                            dv = px(dvol, prev, sym, None)
                            cash -= alloc
                            pos[sym] = {
                                "shares": alloc / buy, "entry_price": buy, "entry_date": d,
                                "entry_signal_date": prev, "peak_close": buy, "partial_done": False,
                                "partial_proceeds": 0.0, "sleeve": "CORE", "entry_sleeve": "CORE",
                                "initial_alloc": alloc, "entry_dvol": dv, "entry_score": info.get("stock_rs189"),
                            }
                            entries.append({
                                "symbol": sym, "signal_date": prev, "entry_date": d, "sleeve": "CORE",
                                "rank": rank, "entry_dvol": dv, "entry_dvol_band": entry_band(dv),
                                "score": info.get("stock_rs189"),
                            })
                            core_count += 1

                if (not is_core12) and gate_allowed(meta, prev, config.gate):
                    noncore_count = sum(1 for p in pos.values() if p["sleeve"] in ("EARLY", "CONFIRMED"))
                    desired_early = config.early_cap if bucket == 2 else (1 if bucket == 1 and noncore_count == 0 else 0)
                    e_count = sum(1 for p in pos.values() if p["sleeve"] == "EARLY")
                    if e_count < desired_early:
                        slot_cash = nav_open_value(d, prev) / 12.0
                        e_list = early_by_score[config.score].get(prev, [])
                        for rank, (sym, score) in enumerate(e_list, start=1):
                            if e_count >= desired_early or cash <= 0:
                                break
                            if sym in pos:
                                continue
                            dv = px(dvol, prev, sym, None)
                            if dv is None or dv < liq_floor:
                                continue
                            raw = px(opens, d, sym, px(closes, prev, sym, None))
                            if raw is None:
                                continue
                            buy = eff_buy(raw)
                            alloc = min(slot_cash, cash)
                            if alloc <= 1e-12:
                                break
                            cash -= alloc
                            pos[sym] = {
                                "shares": alloc / buy, "entry_price": buy, "entry_date": d,
                                "entry_signal_date": prev, "peak_close": buy, "partial_done": False,
                                "partial_proceeds": 0.0, "sleeve": "EARLY", "entry_sleeve": "EARLY",
                                "initial_alloc": alloc, "entry_dvol": dv, "entry_score": score,
                            }
                            entries.append({
                                "symbol": sym, "signal_date": prev, "entry_date": d, "sleeve": "EARLY",
                                "rank": rank, "entry_dvol": dv, "entry_dvol_band": entry_band(dv), "score": score,
                            })
                            e_count += 1

        nav = cash
        for sym, p in pos.items():
            cp = px(closes, d, sym, px(opens, d, sym, p["entry_price"]))
            if cp is None:
                cp = p["entry_price"]
            p["peak_close"] = max(float(p["peak_close"]), float(cp))
            nav += p["shares"] * cp
        equity.append((d, nav))

    last = pd.Timestamp(idx[-1])
    for sym in list(pos):
        raw = px(closes, last, sym, pos[sym]["entry_price"])
        if raw is not None:
            close_position(sym, last, raw, "OPEN_END")

    eq = pd.Series(dict(equity), dtype=float).sort_index()
    return {
        "equity": eq,
        "metrics": period_metrics(eq),
        "entries": pd.DataFrame(entries),
        "intervals": pd.DataFrame(intervals),
        "promoted_confirmed": promoted_confirmed,
        "promoted_core": promoted_core,
    }


def strict_event_eval(events: pd.DataFrame, intervals: pd.DataFrame, close: pd.DataFrame) -> dict[str, Any]:
    if events.empty:
        return {"n": 0}
    by_sym = {str(s): g.sort_values("entry_date") for s, g in intervals.groupby("symbol")} if len(intervals) else {}
    rows = []
    for ev in events.itertuples(index=False):
        sym = str(ev.symbol)
        a = pd.Timestamp(ev.anchor_date)
        e = pd.Timestamp(getattr(ev, "end_date", getattr(ev, "final_date", a)))
        ap = px(close, a, sym, None)
        captured = False
        capture_gain = np.nan
        peak_gain = np.nan
        preheld = False
        g = by_sym.get(sym)
        if ap and g is not None:
            z = g[(pd.to_datetime(g["entry_date"]) <= e) & (pd.to_datetime(g["exit_date"]) >= a)]
            if len(z):
                r = z.iloc[0]
                ed = pd.Timestamp(r["entry_date"])
                captured = True
                if ed <= a:
                    capture_gain = 0.0
                    peak_gain = 0.0
                    preheld = True
                else:
                    ep = float(r["entry_price"])
                    capture_gain = ep / ap - 1.0
                    hist = pd.to_numeric(close.loc[(close.index >= a) & (close.index <= ed), sym], errors="coerce").dropna()
                    if len(hist):
                        peak_gain = float(hist.max() / ap - 1.0)
        rows.append({
            "captured": captured, "capture_gain": capture_gain, "peak_gain_before_entry": peak_gain, "preheld": preheld
        })
    x = pd.DataFrame(rows)
    cap = x["captured"]
    pg = pd.to_numeric(x["peak_gain_before_entry"], errors="coerce")
    cg = pd.to_numeric(x["capture_gain"], errors="coerce")
    return {
        "n": int(len(x)),
        "captured_n": int(cap.sum()),
        "capture_rate": float(cap.mean()),
        "strict_within_20_all": float((cap & (pg <= 0.20)).mean()),
        "strict_within_30_all": float((cap & (pg <= 0.30)).mean()),
        "strict_within_50_all": float((cap & (pg <= 0.50)).mean()),
        "capture_gain_median": float(cg[cap].median()) if cap.any() else None,
        "peak_gain_before_entry_median": float(pg[cap].median()) if cap.any() else None,
        "preheld_share": float(x.loc[cap, "preheld"].mean()) if cap.any() else None,
    }


def trade_band_stats(intervals: pd.DataFrame) -> dict[str, Any]:
    if intervals.empty:
        return {}
    out: dict[str, Any] = {}
    for band, g in intervals.groupby("entry_dvol_band", observed=True):
        r = pd.to_numeric(g["realized_return"], errors="coerce").dropna()
        out[str(band)] = {
            "n": int(len(r)),
            "mean_return": float(r.mean()) if len(r) else None,
            "median_return": float(r.median()) if len(r) else None,
            "win_rate": float((r > 0).mean()) if len(r) else None,
            "p90": float(r.quantile(0.90)) if len(r) else None,
            "p10": float(r.quantile(0.10)) if len(r) else None,
            "early_share": float((g.loc[r.index, "entry_sleeve"] == "EARLY").mean()) if len(r) else None,
        }
    return out


def summary_row(key: str, config: Config | None, sim: dict[str, Any], annual: dict[str, Any]) -> dict[str, Any]:
    m = sim["metrics"]
    return {
        "key": key,
        "config": asdict(config) if config else {"baseline": "CORE12"},
        "full_cagr": m["full_2016_2026"].get("cagr"),
        "full_mdd": m["full_2016_2026"].get("mdd"),
        "dev_cagr": m["dev_2016_2020"].get("cagr"),
        "dev_mdd": m["dev_2016_2020"].get("mdd"),
        "confirm_cagr": m["confirm_2021_2023"].get("cagr"),
        "confirm_mdd": m["confirm_2021_2023"].get("mdd"),
        "holdout_cagr": m["holdout_2024_2026"].get("cagr"),
        "holdout_mdd": m["holdout_2024_2026"].get("mdd"),
        "since2021_cagr": m["since_2021"].get("cagr"),
        "since2021_mdd": m["since_2021"].get("mdd"),
        "entries": int(len(sim["entries"])),
        "early_entries": int((sim["entries"].get("sleeve", pd.Series(dtype=str)) == "EARLY").sum()) if len(sim["entries"]) else 0,
        "promoted_confirmed": int(sim["promoted_confirmed"]),
        "promoted_core": int(sim["promoted_core"]),
        "annual_top5_capture": annual.get("capture_rate"),
        "annual_top5_strict30": annual.get("strict_within_30_all"),
        "annual_top5_strict50": annual.get("strict_within_50_all"),
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
    print("BUILD SIGNAL CONTEXT", flush=True)
    ctx = build_signal_context(root, matrices)
    print("PRECOMPUTE CANDIDATES", flush=True)
    core_attack, core_selective, early_by_score = precompute_candidates(meta, matrices, peer_ctx, ctx)

    idx = pd.DatetimeIndex(meta["analysis_idx"])
    annual5plus = delay.annual_leader_events(matrices["close"], ctx["pool"], idx, include_partial_2026=False)
    annual_top5 = annual5plus[annual5plus["top5"]].rename(columns={"final_date": "end_date", "final_return": "future_return"})
    roll126 = early.rolling126_events(matrices["close"], ctx["pool"], idx, None)

    print("SIM BASELINE", flush=True)
    baseline = simulate(
        None, meta, matrices, ctx, core_attack, core_selective, early_by_score,
        liq_floor=10_000_000.0, cost_bps=COST_BPS_PRIMARY,
    )
    baseline_annual = strict_event_eval(annual_top5, baseline["intervals"], matrices["close"])
    rows = [summary_row("CORE12", None, baseline, baseline_annual)]

    configs = [
        Config(c, f, e, score, confirm, gate, days)
        for (c, f, e) in ALLOCATIONS
        for score in SCORES
        for confirm in CONFIRMS
        for gate in GATES
        for days in EARLY_MAX_DAYS
    ]
    for j, cfg in enumerate(configs, start=1):
        sim = simulate(
            cfg, meta, matrices, ctx, core_attack, core_selective, early_by_score,
            liq_floor=10_000_000.0, cost_bps=COST_BPS_PRIMARY,
        )
        annual = strict_event_eval(annual_top5, sim["intervals"], matrices["close"])
        rows.append(summary_row(cfg.key, cfg, sim, annual))
        if j % 15 == 0:
            print(f"GRID {j}/{len(configs)}", flush=True)

    grid = pd.DataFrame(rows)
    grid.to_csv(out / "staged_architecture_grid.csv", index=False)

    base_dev_mdd = float(grid.loc[grid["key"] == "CORE12", "dev_mdd"].iloc[0])
    candidates = grid[grid["key"] != "CORE12"].copy()
    pure = candidates.sort_values(["dev_cagr", "full_cagr"], ascending=False).iloc[0]
    guarded_pool = candidates[candidates["dev_mdd"] >= base_dev_mdd - 0.05].copy()
    guarded = guarded_pool.sort_values(["dev_cagr", "full_cagr"], ascending=False).iloc[0] if len(guarded_pool) else pure
    hindsight = candidates.sort_values(["full_cagr", "since2021_cagr"], ascending=False).iloc[0]

    cfg_map = {c.key: c for c in configs}
    selected_keys = []
    for k in [str(pure["key"]), str(guarded["key"]), str(hindsight["key"])]:
        if k not in selected_keys:
            selected_keys.append(k)

    selected_detail: dict[str, Any] = {}
    for key in selected_keys:
        cfg = cfg_map[key]
        sim = simulate(
            cfg, meta, matrices, ctx, core_attack, core_selective, early_by_score,
            liq_floor=10_000_000.0, cost_bps=COST_BPS_PRIMARY,
        )
        selected_detail[key] = {
            "config": asdict(cfg),
            "metrics": sim["metrics"],
            "annual_top5_strict": strict_event_eval(annual_top5, sim["intervals"], matrices["close"]),
            "rolling126_top10_strict": strict_event_eval(roll126, sim["intervals"], matrices["close"]),
            "trade_band_stats": trade_band_stats(sim["intervals"]),
            "entries": int(len(sim["entries"])),
            "early_entries": int((sim["entries"]["sleeve"] == "EARLY").sum()) if len(sim["entries"]) else 0,
            "promoted_confirmed": int(sim["promoted_confirmed"]),
            "promoted_core": int(sim["promoted_core"]),
        }
        sim["entries"].to_csv(out / f"entries_{key}.csv", index=False)
        sim["intervals"].to_csv(out / f"intervals_{key}.csv", index=False)
        sim["equity"].rename("equity").to_csv(out / f"equity_{key}.csv")

    liq_sensitivity: dict[str, Any] = {}
    for label, cfg in [("CORE12", None), ("DEV_GUARDED_WINNER", cfg_map[str(guarded["key"])])]:
        by_floor = {}
        for floor in LIQ_FLOORS:
            sim = simulate(
                cfg, meta, matrices, ctx, core_attack, core_selective, early_by_score,
                liq_floor=floor, cost_bps=COST_BPS_PRIMARY,
            )
            by_floor[str(int(floor))] = {
                "metrics": sim["metrics"],
                "annual_top5_strict": strict_event_eval(annual_top5, sim["intervals"], matrices["close"]),
                "trade_band_stats": trade_band_stats(sim["intervals"]),
                "entries": int(len(sim["entries"])),
            }
        liq_sensitivity[label] = by_floor

    cost_sensitivity: dict[str, Any] = {}
    for label, cfg in [("CORE12", None), ("DEV_GUARDED_WINNER", cfg_map[str(guarded["key"])])]:
        by_cost = {}
        for bps in (0.0, 10.0, 25.0):
            sim = simulate(
                cfg, meta, matrices, ctx, core_attack, core_selective, early_by_score,
                liq_floor=10_000_000.0, cost_bps=bps,
            )
            by_cost[str(bps)] = {
                "metrics": sim["metrics"],
                "entries": int(len(sim["entries"])),
            }
        cost_sensitivity[label] = by_cost

    result = {
        "status": "STAGED_EARLY_CONFIRMED_CORE_LIQUIDITY_RETURN_AUDIT",
        "scope": "research only; no main/UI/live rule changes",
        "user_liquidity_rule": {
            "price_floor": 5.0,
            "ddv_floor": 10_000_000.0,
            "structural_small_clinical_biotech_exclusion": True,
        },
        "primary_cost_bps_per_side": COST_BPS_PRIMARY,
        "architecture": {
            "total_nominal_slots": 12,
            "early": "fresh Any(RS21,RS42,RS63)>=85 radar; active 5 sessions; selected by score; next-open entry",
            "confirmed_mid": "Close>=SMA50, SMA50>SMA200, RS21>=85; removes RS63/RS189 wait",
            "confirmed_full": "current Full Eligibility; promotion releases an Early slot before current Core Top rank",
            "core": "current adopted Core ranking/exit mechanics; no rank/theme forced exit",
            "early_expiry_sessions_grid": list(EARLY_MAX_DAYS),
            "confirmed_expiry_sessions": CONFIRMED_MAX_DAYS,
            "market_gate_grid": list(GATES),
            "allocations": [list(x) for x in ALLOCATIONS],
            "scores": list(SCORES),
            "cost_note": "buy and sell prices penalized by primary per-side bps",
        },
        "selection_protocol": {
            "development_only": "2016-2020 CAGR; confirmation/holdout not used to choose development winners",
            "pure_return_winner": str(pure["key"]),
            "guarded_return_winner": str(guarded["key"]),
            "guardrail": "development MDD no more than 5 percentage points worse than CORE12 development MDD",
            "full_period_hindsight_winner": str(hindsight["key"]),
            "warning": "full-period hindsight winner is diagnostic, not adoptable selection evidence",
        },
        "baseline": rows[0],
        "winners": {
            "pure_dev": safe(pure.to_dict()),
            "guarded_dev": safe(guarded.to_dict()),
            "hindsight_full": safe(hindsight.to_dict()),
        },
        "selected_detail": safe(selected_detail),
        "liquidity_sensitivity": safe(liq_sensitivity),
        "liquidity_sensitivity_definition": "ranking universe stays at user's >=$10M rule; floors 20/50/100M only exclude lower-DDV new entries",
        "cost_sensitivity": safe(cost_sensitivity),
        "grid_count": int(len(grid)),
    }

    with open(out / "summary_staged_liquidity_return_audit.json", "w", encoding="utf-8") as f:
        json.dump(safe(result), f, ensure_ascii=False, indent=2)

    print("=== STAGED_LIQUIDITY_RETURN_RESULT ===")
    print(json.dumps(safe({
        "baseline": result["baseline"],
        "selection_protocol": result["selection_protocol"],
        "winners": result["winners"],
        "liquidity_sensitivity": result["liquidity_sensitivity"],
    }), ensure_ascii=False, indent=2))
    print("=== END_STAGED_LIQUIDITY_RETURN_RESULT ===")


if __name__ == "__main__":
    main()
