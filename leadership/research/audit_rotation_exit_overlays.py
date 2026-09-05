from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import audit_ordinary_stock_exit_trail as ex
import audit_ordinary_stock_market_mode_robustness as base
import audit_ordinary_stock_theme_leave_one_out as loo

SELECTIVE_SLOTS = 4
PANEL_START = pd.Timestamp("2022-04-18")
CONFIRM_START = pd.Timestamp("2024-01-01")
RECENT_START = pd.Timestamp("2025-01-01")


@dataclass(frozen=True)
class Variant:
    name: str
    threshold: float | None = None
    require_flow_out: bool = False
    persistence: int = 1
    trail_pct: float | None = None
    trail_latched: bool = True
    extra_partial: float = 0.0
    full_exit: bool = False


VARIANTS = [
    Variant("BASE"),
    Variant("TRAIL25_LATCH_W10", threshold=-10, trail_pct=25, trail_latched=True),
    Variant("TRAIL25_LATCH_W15", threshold=-15, trail_pct=25, trail_latched=True),
    Variant("TRAIL25_LATCH_W20", threshold=-20, trail_pct=25, trail_latched=True),
    Variant("TRAIL20_DYNAMIC_W10", threshold=-10, trail_pct=20, trail_latched=False),
    Variant("TRAIL20_LATCH_W10", threshold=-10, trail_pct=20, trail_latched=True),
    Variant("TRAIL20_LATCH_W15", threshold=-15, trail_pct=20, trail_latched=True),
    Variant("TRAIL20_LATCH_W20", threshold=-20, trail_pct=20, trail_latched=True),
    Variant("EXTRA25_W10", threshold=-10, extra_partial=0.25),
    Variant("EXTRA25_W20", threshold=-20, extra_partial=0.25),
    Variant("FULL_W20", threshold=-20, full_exit=True),
    Variant("FULL_W10_P2", threshold=-10, persistence=2, full_exit=True),
    Variant("FULL_W20_FLOW", threshold=-20, require_flow_out=True, full_exit=True),
    Variant("COMBO_EXTRA25_TRAIL20_W10", threshold=-10, trail_pct=20, trail_latched=True, extra_partial=0.25),
]


def safe(v: Any) -> Any:
    if isinstance(v, dict):
        return {str(k): safe(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [safe(x) for x in v]
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        x = float(v)
        return x if math.isfinite(x) else None
    if isinstance(v, pd.Timestamp):
        return v.isoformat()
    return v


def load_rotation(panel_path: Path, snapshots_path: Path) -> tuple[pd.DataFrame, dict[pd.Timestamp, dict[str, str]]]:
    panel = pd.read_csv(panel_path)
    panel["date"] = pd.to_datetime(panel["date"]).dt.normalize()
    sector_col = "sector" if "sector" in panel.columns else "ticker"
    panel["sector"] = panel[sector_col].astype(str).str.upper()
    panel = panel.sort_values(["sector", "date"]).drop_duplicates(["sector", "date"], keep="last")
    if "internal_delta20" not in panel.columns:
        panel["internal_delta20"] = panel.groupby("sector", observed=True)["internal_score"].transform(lambda s: pd.to_numeric(s, errors="coerce") - pd.to_numeric(s, errors="coerce").shift(20))
    else:
        panel["internal_delta20"] = pd.to_numeric(panel["internal_delta20"], errors="coerce")
    for c in ("price_score", "internal_score", "flow20_pct_aum"):
        if c in panel.columns:
            panel[c] = pd.to_numeric(panel[c], errors="coerce")
    panel = panel.set_index(["date", "sector"]).sort_index()

    snap = pd.read_csv(snapshots_path)
    snap["asof"] = pd.to_datetime(snap["asof"]).dt.normalize()
    snap["ticker"] = snap["ticker"].astype(str).str.upper().str.replace(".", "-", regex=False)
    snap["sector_etf"] = snap["sector_etf"].astype(str).str.upper()
    by_date: dict[pd.Timestamp, dict[str, str]] = {}
    for d, g in snap.dropna(subset=["ticker", "sector_etf"]).groupby("asof", sort=True):
        by_date[pd.Timestamp(d)] = dict(zip(g["ticker"], g["sector_etf"]))
    return panel, by_date


class PITState:
    def __init__(self, panel: pd.DataFrame, snapshots: dict[pd.Timestamp, dict[str, str]]):
        self.panel = panel
        self.snapshots = snapshots
        self.snapshot_dates = np.array(sorted(snapshots), dtype="datetime64[ns]")
        self.panel_dates = set(panel.index.get_level_values(0))

    def sector(self, sym: str, d: pd.Timestamp) -> str | None:
        if len(self.snapshot_dates) == 0:
            return None
        x = np.datetime64(pd.Timestamp(d).normalize(), "ns")
        i = int(np.searchsorted(self.snapshot_dates, x, side="right") - 1)
        if i < 0:
            return None
        asof = pd.Timestamp(self.snapshot_dates[i])
        # Monthly PIT snapshots. Reject stale classification instead of carrying a
        # former S&P500 membership indefinitely after removal.
        if (pd.Timestamp(d).normalize() - asof).days > 40:
            return None
        return self.snapshots.get(asof, {}).get(str(sym).upper().replace(".", "-"))

    def state(self, sym: str, d: pd.Timestamp) -> dict[str, Any] | None:
        d = pd.Timestamp(d).normalize()
        if d not in self.panel_dates:
            return None
        sec = self.sector(sym, d)
        if not sec:
            return None
        key = (d, sec)
        if key not in self.panel.index:
            return None
        r = self.panel.loc[key]
        if isinstance(r, pd.DataFrame):
            r = r.iloc[-1]
        return {
            "sector": sec,
            "price_score": float(r["price_score"]) if pd.notna(r.get("price_score")) else np.nan,
            "internal_score": float(r["internal_score"]) if pd.notna(r.get("internal_score")) else np.nan,
            "internal_delta20": float(r["internal_delta20"]) if pd.notna(r.get("internal_delta20")) else np.nan,
            "flow20_pct_aum": float(r["flow20_pct_aum"]) if pd.notna(r.get("flow20_pct_aum")) else np.nan,
        }


def warning(st: dict[str, Any] | None, v: Variant) -> bool:
    if v.threshold is None or st is None:
        return False
    p = st.get("price_score")
    d = st.get("internal_delta20")
    if not (np.isfinite(p) and np.isfinite(d)):
        return False
    if p < 70.0 or d > float(v.threshold):
        return False
    if v.require_flow_out:
        f = st.get("flow20_pct_aum")
        if not np.isfinite(f) or f > 0.0:
            return False
    return True


def period_metrics(eq: pd.Series) -> dict[str, Any]:
    e = pd.to_numeric(eq, errors="coerce").dropna()
    return {
        "panel_2022_plus": base.metrics(e.loc[e.index >= PANEL_START]),
        "confirmation_2024_plus": base.metrics(e.loc[e.index >= CONFIRM_START]),
        "recent_2025_plus": base.metrics(e.loc[e.index >= RECENT_START]),
    }


def post_exit_diagnostics(tdf: pd.DataFrame, closes: pd.DataFrame, idx: pd.DatetimeIndex) -> pd.DataFrame:
    if tdf.empty:
        return tdf
    pos = {pd.Timestamp(d): i for i, d in enumerate(idx)}
    out = []
    for _, r0 in tdf.iterrows():
        r = r0.to_dict()
        d = pd.Timestamp(r["exit_date"])
        sym = str(r["symbol"])
        i = pos.get(d)
        ep = float(r["exit_price"])
        for h in (20, 40, 63):
            val = np.nan
            if i is not None and sym in closes.columns and ep > 0:
                future = pd.to_numeric(closes.iloc[i + 1:min(len(idx), i + 1 + h)][sym], errors="coerce").dropna()
                if len(future):
                    val = float(future.max() / ep - 1.0)
            r[f"post_exit_max_{h}d"] = val
        out.append(r)
    return pd.DataFrame(out)


def trade_summary(tdf: pd.DataFrame) -> dict[str, Any]:
    if tdf.empty:
        return {"n": 0}
    z = tdf.copy()
    ret = pd.to_numeric(z["total_return"], errors="coerce").dropna()
    rot = z[z["rotation_action"].fillna(False).astype(bool)]
    def mean_col(df: pd.DataFrame, c: str):
        x = pd.to_numeric(df.get(c), errors="coerce").dropna()
        return float(x.mean()) if len(x) else None
    return {
        "n": int(len(z)),
        "mean_total_return": float(ret.mean()) if len(ret) else None,
        "median_total_return": float(ret.median()) if len(ret) else None,
        "win_rate": float((ret > 0).mean()) if len(ret) else None,
        "rotation_action_trades": int(len(rot)),
        "rotation_action_rate": float(len(rot) / len(z)) if len(z) else None,
        "mean_mfe_to_exit": mean_col(z, "mfe_to_exit"),
        "mean_peak_capture": mean_col(z[z["mfe_to_exit"] > 0], "peak_capture"),
        "mfe_ge50_n": int((pd.to_numeric(z["mfe_to_exit"], errors="coerce") >= .50).sum()),
        "mfe_ge100_n": int((pd.to_numeric(z["mfe_to_exit"], errors="coerce") >= 1.00).sum()),
        "rotation_exit_post20_ge20_rate": float((pd.to_numeric(rot["post_exit_max_20d"], errors="coerce") >= .20).mean()) if len(rot) else None,
        "rotation_exit_post40_ge20_rate": float((pd.to_numeric(rot["post_exit_max_40d"], errors="coerce") >= .20).mean()) if len(rot) else None,
        "rotation_exit_post63_ge50_rate": float((pd.to_numeric(rot["post_exit_max_63d"], errors="coerce") >= .50).mean()) if len(rot) else None,
        "rotation_exit_mean_post40_max": mean_col(rot, "post_exit_max_40d"),
    }


def simulate(meta, matrices, peer_ctx, pit: PITState, v: Variant):
    idx: pd.DatetimeIndex = meta["analysis_idx"]
    opens, closes = matrices["open"], matrices["close"]
    breadth, nq = meta["breadth"], meta["nq"]
    cash = 1.0
    pos: dict[str, dict[str, Any]] = {}
    equities: list[tuple[pd.Timestamp, float]] = []
    trades: list[dict[str, Any]] = []
    red_run = 0
    coverage = {"held_days_panel": 0, "mapped_sector_days": 0, "state_days": 0, "warning_days": 0}

    def px(frame, date, sym, fallback=None):
        try:
            x = float(frame.at[date, sym])
            if np.isfinite(x) and x > 0:
                return x
        except Exception:
            pass
        return fallback

    def sell_partial(p, price: float, frac_remaining: float, key: str):
        nonlocal cash
        sold = p["shares"] * frac_remaining
        if sold <= 0:
            return
        cash += sold * price
        p["shares"] -= sold
        p["realized_proceeds"] += sold * price
        p[key] = True

    def close_position(sym, date, price, reason, rotation_action=False):
        nonlocal cash
        p = pos.pop(sym)
        final_proceeds = p["shares"] * price
        cash += final_proceeds
        total_proceeds = p["realized_proceeds"] + final_proceeds
        total_ret = total_proceeds / p["initial_alloc"] - 1.0 if p["initial_alloc"] > 0 else np.nan
        mfe = p["peak_close"] / p["entry_price"] - 1.0
        capture = total_ret / mfe if np.isfinite(mfe) and mfe > 0 else np.nan
        trades.append({
            "variant": v.name, "symbol": sym, "entry_date": p["entry_date"], "exit_date": date,
            "entry_price": p["entry_price"], "exit_price": price, "total_return": total_ret,
            "mfe_to_exit": mfe, "peak_capture": capture, "exit_reason": reason,
            "entry_bucket": p["entry_bucket"], "baseline_partial_done": p["partial_done"],
            "rotation_extra_done": p["rotation_extra_done"], "rotation_latched": p["rotation_latched"],
            "rotation_action": bool(rotation_action or p["rotation_extra_done"] or p["rotation_latched"]),
            "first_warning_date": p.get("first_warning_date"), "warning_sector": p.get("warning_sector"),
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
                        close_position(sym, d, opx, "RED", False)
            else:
                for sym in list(pos):
                    p = pos[sym]
                    pc = px(closes, prev, sym, p["entry_price"])
                    if pc is None:
                        continue
                    p["sessions"] += 1
                    st = pit.state(sym, prev)
                    if prev >= PANEL_START:
                        coverage["held_days_panel"] += 1
                        if pit.sector(sym, prev):
                            coverage["mapped_sector_days"] += 1
                        if st is not None:
                            coverage["state_days"] += 1
                    active = warning(st, v)
                    p["warning_streak"] = p["warning_streak"] + 1 if active else 0
                    armed = active and p["warning_streak"] >= max(1, v.persistence)
                    if active:
                        coverage["warning_days"] += 1
                    if armed and p.get("first_warning_date") is None:
                        p["first_warning_date"] = prev
                        p["warning_sector"] = st.get("sector") if st else None
                    if armed and v.trail_latched and v.trail_pct is not None:
                        p["rotation_latched"] = True

                    stop = p["entry_price"] * .92
                    reason = "HARD8"
                    base_peak_stop = p["peak_close"] * .70
                    if base_peak_stop > stop:
                        stop, reason = base_peak_stop, "PEAK30"
                    tight = False
                    if v.trail_pct is not None:
                        tight = p["rotation_latched"] if v.trail_latched else armed
                        if tight:
                            tstop = p["peak_close"] * (1.0 - float(v.trail_pct) / 100.0)
                            if tstop > stop:
                                stop, reason = tstop, f"ROT_TRAIL{int(v.trail_pct)}"

                    full_rotation = bool(v.full_exit and armed)
                    stop_hit = bool(pc <= stop)
                    if full_rotation or stop_hit:
                        opx = px(opens, d, sym, pc)
                        if opx is not None:
                            close_position(sym, d, opx, "ROT_FULL" if full_rotation else reason, full_rotation or reason.startswith("ROT_"))
                        continue

                    opx = px(opens, d, sym, pc)
                    if opx is None:
                        continue
                    # Adopted V38 partial: first close >= +24%, sell 25% next open.
                    if (not p["partial_done"]) and pc >= p["entry_price"] * 1.24:
                        sell_partial(p, opx, .25, "partial_done")
                    # Rotation extra partial is once per position and only after the warning is armed.
                    if v.extra_partial > 0 and armed and not p["rotation_extra_done"]:
                        sell_partial(p, opx, float(v.extra_partial), "rotation_extra_done")

            b = float(breadth.loc[prev]) if prev in breadth.index and pd.notna(breadth.loc[prev]) else np.nan
            bucket = base.breadth_bucket(b)
            bull = color in ("Blue", "Green")
            cap = base.N_PORT if bull and bucket == 2 else SELECTIVE_SLOTS if bull and bucket == 1 else 0
            if (not red_force) and cap > 0 and len(pos) < cap:
                candidates = ex.ranked_candidates(prev, matrices, peer_ctx, bucket, base.N_PORT)
                nav_open = cash
                for sym, p in pos.items():
                    opx = px(opens, d, sym, px(closes, prev, sym, p["entry_price"]))
                    if opx is not None:
                        nav_open += p["shares"] * opx
                slot_cash = nav_open / base.N_PORT
                for sym, c in candidates:
                    if len(pos) >= cap or cash <= 0:
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
                        "shares": alloc / opx, "initial_alloc": alloc, "realized_proceeds": 0.0,
                        "entry_price": opx, "entry_date": d, "peak_close": opx,
                        "entry_bucket": bucket, "sessions": 0, "partial_done": False,
                        "rotation_extra_done": False, "rotation_latched": False, "warning_streak": 0,
                        "first_warning_date": None, "warning_sector": None, **c,
                    }

        nav = cash
        for sym, p in pos.items():
            cp = px(closes, d, sym, px(opens, d, sym, p["entry_price"]))
            if cp is None:
                cp = p["entry_price"]
            p["peak_close"] = max(p["peak_close"], cp)
            nav += p["shares"] * cp
        equities.append((d, nav))

    eq = pd.Series(dict(equities), dtype=float).sort_index()
    tdf = post_exit_diagnostics(pd.DataFrame(trades), closes, idx)
    return {"equity": eq, "trades": tdf, "coverage": coverage}


def bootstrap_period(eq_a: pd.Series, eq_b: pd.Series, start: pd.Timestamp, seed: int) -> dict[str, Any]:
    a = eq_a.loc[eq_a.index >= start]
    b = eq_b.reindex(a.index)
    if len(a) < 80 or len(b.dropna()) < 80:
        return {"n": int(len(a))}
    return base.bootstrap_block_win(a, b, block=20, reps=5000, seed=seed)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--panel", type=Path, required=True)
    ap.add_argument("--snapshots", type=Path, required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--analysis-start", default="2022-04-18")
    ap.add_argument("--analysis-end", default="2026-06-20")
    ap.add_argument("--max-tickers", type=int, default=6000)
    ap.add_argument("--batch-size", type=int, default=60)
    args = ap.parse_args()
    root = Path(args.root)
    out = root / args.output
    out.mkdir(parents=True, exist_ok=True)

    panel, snapshots = load_rotation(args.panel, args.snapshots)
    pit = PITState(panel, snapshots)
    meta, matrices = ex.build_inputs_ext(root, args.analysis_start, args.analysis_end, args.max_tickers, args.batch_size)
    peer_ctx = loo.build_leave_one_out_scores(root, matrices)

    sims = {}
    for j, v in enumerate(VARIANTS):
        print(f"SIM {j+1}/{len(VARIANTS)} {v.name}", flush=True)
        sims[v.name] = simulate(meta, matrices, peer_ctx, pit, v)
        sims[v.name]["equity"].rename("equity").to_csv(out / f"equity_{v.name}.csv")
        sims[v.name]["trades"].to_csv(out / f"trades_{v.name}.csv", index=False)

    base_eq = sims["BASE"]["equity"]
    result = {
        "status": "ROTATION_EXIT_OVERLAY_RESEARCH",
        "research_only": True,
        "guardrails": [
            "Entry, ranking, market mode, -8% initial stop, +24%/25% adopted partial and baseline PeakClose-30% trail are unchanged.",
            "Rotation signal is prior-close PIT 11-sector state, executed next open; no Theme56 current-membership retrospective is used for the primary test.",
            "Monthly PIT sector snapshot must be <=40 calendar days old; otherwise the stock is unmapped and Rotation cannot act.",
            "Rotation variants change exits only; they do not block or promote entries.",
        ],
        "warning_core": "sector PriceScore>=70 AND InternalScore 20-session delta <= threshold; optional exact 20D Flow/AUM<=0",
        "variants": {},
        "vs_base_block20": {},
    }
    for k, v in enumerate(VARIANTS):
        sim = sims[v.name]
        result["variants"][v.name] = {
            "definition": v.__dict__,
            "metrics": period_metrics(sim["equity"]),
            "trade_summary": trade_summary(sim["trades"]),
            "pit_position_day_coverage": sim["coverage"],
        }
        if v.name != "BASE":
            result["vs_base_block20"][v.name] = {
                "2022_plus": bootstrap_period(sim["equity"], base_eq, PANEL_START, 410000 + k),
                "2024_plus": bootstrap_period(sim["equity"], base_eq, CONFIRM_START, 420000 + k),
                "2025_plus": bootstrap_period(sim["equity"], base_eq, RECENT_START, 430000 + k),
            }

    # Baseline mapping coverage is the cleanest denominator because overlay exits can
    # alter later portfolio composition.
    cov = result["variants"]["BASE"]["pit_position_day_coverage"]
    held = cov.get("held_days_panel", 0)
    state = cov.get("state_days", 0)
    result["strict_pit_coverage"] = {
        **cov,
        "state_coverage_of_held_position_days": (state / held) if held else None,
        "interpretation": "Strict-PIT primary evidence applies only to position-days with contemporaneous S&P500 sector membership and audited 11-sector state.",
    }
    (out / "summary_rotation_exit_overlays.json").write_text(json.dumps(safe(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== ROTATION_EXIT_JSON ===", flush=True)
    print(json.dumps(safe(result), ensure_ascii=False, indent=2), flush=True)
    print("=== END_ROTATION_EXIT_JSON ===", flush=True)


if __name__ == "__main__":
    main()
