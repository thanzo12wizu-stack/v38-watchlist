from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import audit_distribution_trap_trade_screen as screen
import audit_rotation_exit_overlays as core


class CurrentClassificationState:
    """Current-classification bridge for sensitivity only. This is NOT PIT."""
    def __init__(self, panel: pd.DataFrame, sector_map: dict[str, str]):
        self.panel = panel
        self.sector_map = sector_map
        self.panel_dates = set(panel.index.get_level_values(0))

    def sector(self, sym: str, d: pd.Timestamp) -> str | None:
        return self.sector_map.get(str(sym).upper().replace(".", "-"))

    def state(self, sym: str, d: pd.Timestamp) -> dict[str, Any] | None:
        d = pd.Timestamp(d).normalize()
        if d not in self.panel_dates:
            return None
        sec = self.sector(sym, d)
        if not sec or (d, sec) not in self.panel.index:
            return None
        r = self.panel.loc[(d, sec)]
        if isinstance(r, pd.DataFrame):
            r = r.iloc[-1]
        return {
            "sector": sec,
            "price_score": float(r["price_score"]) if pd.notna(r.get("price_score")) else np.nan,
            "internal_score": float(r["internal_score"]) if pd.notna(r.get("internal_score")) else np.nan,
            "internal_delta20": float(r["internal_delta20"]) if pd.notna(r.get("internal_delta20")) else np.nan,
            "flow20_pct_aum": float(r["flow20_pct_aum"]) if pd.notna(r.get("flow20_pct_aum")) else np.nan,
        }


def build_current_map(universe_path: Path) -> dict[str, str]:
    u = pd.read_csv(universe_path)
    sym_col = "シンボル" if "シンボル" in u.columns else "symbol"
    sec_col = "セクター" if "セクター" in u.columns else "sector"
    ind_col = "業種" if "業種" in u.columns else "industry"
    out = {}
    for sym, sec, ind in zip(u[sym_col], u[sec_col], u[ind_col]):
        etf = screen.current_sector_etf(sec, ind)
        if etf:
            out[str(sym).strip().upper().replace(".", "-")] = etf
    return out


def latest_mapper_validation(universe_path: Path, snapshots_path: Path) -> dict[str, Any]:
    u = pd.read_csv(universe_path)
    s = pd.read_csv(snapshots_path)
    s["asof"] = pd.to_datetime(s["asof"]).dt.normalize()
    s["ticker"] = s["ticker"].astype(str).str.upper().str.replace(".", "-", regex=False)
    return screen.latest_current_validation(u, s)


def px(frame: pd.DataFrame, date: pd.Timestamp, sym: str, fallback=None):
    try:
        x = float(frame.at[date, sym])
        if np.isfinite(x) and x > 0:
            return x
    except Exception:
        pass
    return fallback


def replay_episode(
    row: pd.Series,
    v: core.Variant,
    state_source,
    matrices: dict[str, pd.DataFrame],
    analysis_idx: pd.DatetimeIndex,
) -> dict[str, Any]:
    opens, closes = matrices["open"], matrices["close"]
    sym = str(row["symbol"])
    entry_date = pd.Timestamp(row["entry_date"])
    baseline_exit = pd.Timestamp(row["exit_date"])
    entry_price = float(row["entry_price"])
    baseline_exit_price = float(row["exit_price"])
    baseline_return = float(row["total_return"])
    loc = pd.Series(np.arange(len(analysis_idx)), index=analysis_idx)
    if entry_date not in loc.index or baseline_exit not in loc.index:
        return {"usable": False}
    ie, ix = int(loc.at[entry_date]), int(loc.at[baseline_exit])
    if ix <= ie:
        return {"usable": False}

    shares = 1.0
    realized = 0.0
    partial_done = False
    extra_done = False
    latched = False
    warning_streak = 0
    first_warning = None
    warning_sector = None
    exit_date = baseline_exit
    exit_price = baseline_exit_price
    exit_reason = "BASELINE_ORIGINAL_EXIT"
    rotation_exit = False
    peak = entry_price

    # Entry-day close is part of Peak Close before the next session's decision.
    ec = px(closes, entry_date, sym, entry_price)
    peak = max(peak, ec if ec is not None else entry_price)

    for j in range(ie + 1, ix + 1):
        d = pd.Timestamp(analysis_idx[j])
        prev = pd.Timestamp(analysis_idx[j - 1])
        pc = px(closes, prev, sym, entry_price)
        if pc is None:
            continue
        peak = max(peak, pc)
        st = state_source.state(sym, prev)
        active = core.warning(st, v)
        warning_streak = warning_streak + 1 if active else 0
        armed = active and warning_streak >= max(1, v.persistence)
        if armed and first_warning is None:
            first_warning = prev
            warning_sector = st.get("sector") if st else None
        if armed and v.trail_latched and v.trail_pct is not None:
            latched = True

        # At the original baseline exit date, do not invent a later exit. If Rotation
        # also acts that morning it has the same execution price, so the P/L is unchanged.
        if d == baseline_exit:
            exit_date = d
            exit_price = baseline_exit_price
            exit_reason = "BASELINE_ORIGINAL_EXIT"
            break

        opx = px(opens, d, sym, pc)
        if opx is None:
            continue
        if v.full_exit and armed:
            exit_date, exit_price, exit_reason, rotation_exit = d, opx, "ROT_FULL", True
            break

        if v.trail_pct is not None:
            tight_active = latched if v.trail_latched else armed
            if tight_active:
                tight_stop = peak * (1.0 - float(v.trail_pct) / 100.0)
                # Baseline itself survived this session. Only the tighter overlay can
                # create an earlier exit here.
                if pc <= tight_stop:
                    exit_date, exit_price, exit_reason, rotation_exit = d, opx, f"ROT_TRAIL{int(v.trail_pct)}", True
                    break

        # Baseline adopted partial: +24% close -> next-open 25%, once.
        if (not partial_done) and pc >= entry_price * 1.24:
            sold = shares * 0.25
            realized += sold * opx
            shares -= sold
            partial_done = True

        if v.extra_partial > 0 and armed and not extra_done:
            sold = shares * float(v.extra_partial)
            realized += sold * opx
            shares -= sold
            extra_done = True

        dc = px(closes, d, sym, pc)
        if dc is not None:
            peak = max(peak, dc)

    total_proceeds = realized + shares * exit_price
    overlay_return = total_proceeds / entry_price - 1.0

    # Future upside after the overlay exit, using the same analysis calendar.
    iexit = int(loc.at[exit_date]) if exit_date in loc.index else None
    future = {}
    for h in (20, 40, 63):
        mx = np.nan
        if iexit is not None:
            s = pd.to_numeric(closes.reindex(analysis_idx).iloc[iexit + 1:min(len(analysis_idx), iexit + 1 + h)].get(sym), errors="coerce").dropna()
            if len(s) and exit_price > 0:
                mx = float(s.max() / exit_price - 1.0)
        future[h] = mx

    return {
        "usable": True,
        "symbol": sym,
        "entry_date": entry_date,
        "baseline_exit_date": baseline_exit,
        "overlay_exit_date": exit_date,
        "baseline_return": baseline_return,
        "overlay_return": overlay_return,
        "delta_vs_baseline": overlay_return - baseline_return,
        "days_earlier": int((baseline_exit - exit_date).days),
        "rotation_exit": rotation_exit,
        "extra_partial": extra_done,
        "first_warning_date": first_warning,
        "warning_sector": warning_sector,
        "post20_max": future[20],
        "post40_max": future[40],
        "post63_max": future[63],
        "baseline_big50": baseline_return >= 0.50,
        "baseline_big100": baseline_return >= 1.00,
        "baseline_big200": baseline_return >= 2.00,
        "baseline_big400": baseline_return >= 4.00,
    }


def paired_summary(df: pd.DataFrame) -> dict[str, Any]:
    if df.empty:
        return {"n": 0}
    z = df[df["usable"] == True].copy()  # noqa: E712
    if z.empty:
        return {"n": 0}
    acted = z[z["rotation_exit"] | z["extra_partial"]]
    def m(col, data=z):
        x = pd.to_numeric(data[col], errors="coerce").dropna()
        return float(x.mean()) if len(x) else None
    return {
        "n": int(len(z)),
        "acted_n": int(len(acted)),
        "acted_rate": float(len(acted) / len(z)),
        "mean_delta_vs_baseline_all": m("delta_vs_baseline"),
        "mean_delta_vs_baseline_acted": m("delta_vs_baseline", acted) if len(acted) else None,
        "median_delta_vs_baseline_acted": float(pd.to_numeric(acted["delta_vs_baseline"], errors="coerce").median()) if len(acted) else None,
        "acted_better_rate": float((pd.to_numeric(acted["delta_vs_baseline"], errors="coerce") > 0).mean()) if len(acted) else None,
        "mean_days_earlier_acted": m("days_earlier", acted) if len(acted) else None,
        "post20_ge20_rate": float((pd.to_numeric(acted["post20_max"], errors="coerce") >= .20).mean()) if len(acted) else None,
        "post40_ge20_rate": float((pd.to_numeric(acted["post40_max"], errors="coerce") >= .20).mean()) if len(acted) else None,
        "post63_ge50_rate": float((pd.to_numeric(acted["post63_max"], errors="coerce") >= .50).mean()) if len(acted) else None,
        "baseline_big50_acted": int(acted["baseline_big50"].sum()) if len(acted) else 0,
        "baseline_big100_acted": int(acted["baseline_big100"].sum()) if len(acted) else 0,
        "baseline_big200_acted": int(acted["baseline_big200"].sum()) if len(acted) else 0,
        "baseline_big400_acted": int(acted["baseline_big400"].sum()) if len(acted) else 0,
    }


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

    panel, snapshots = core.load_rotation(args.panel, args.snapshots)
    strict = core.PITState(panel, snapshots)
    current_map = build_current_map(root / "universe.csv")
    broad = CurrentClassificationState(panel, current_map)
    mapping_validation = latest_mapper_validation(root / "universe.csv", args.snapshots)

    meta, matrices = core.ex.build_inputs_ext(root, args.analysis_start, args.analysis_end, args.max_tickers, args.batch_size)
    peer_ctx = core.loo.build_leave_one_out_scores(root, matrices)
    base_sim = core.simulate(meta, matrices, peer_ctx, strict, core.VARIANTS[0])
    base_trades = base_sim["trades"].copy()

    result = {
        "status": "ROTATION_EXIT_SENSITIVITY_RESEARCH",
        "research_only": True,
        "primary_evidence": "STRICT_PIT",
        "secondary_evidence": "CURRENT_CLASSIFICATION_LOOKAHEAD_SENSITIVITY",
        "mapping_validation": mapping_validation,
        "strict_fixed_entry": {},
        "broad_fixed_entry": {},
        "broad_portfolio": {},
    }

    for v in core.VARIANTS:
        strict_rows = [replay_episode(r, v, strict, matrices, meta["analysis_idx"]) for _, r in base_trades.iterrows()]
        broad_rows = [replay_episode(r, v, broad, matrices, meta["analysis_idx"]) for _, r in base_trades.iterrows()]
        sdf = pd.DataFrame(strict_rows)
        bdf = pd.DataFrame(broad_rows)
        sdf.to_csv(out / f"paired_strict_{v.name}.csv", index=False)
        bdf.to_csv(out / f"paired_broad_{v.name}.csv", index=False)
        result["strict_fixed_entry"][v.name] = paired_summary(sdf)
        result["broad_fixed_entry"][v.name] = paired_summary(bdf)

        print(f"BROAD SIM {v.name}", flush=True)
        sim = core.simulate(meta, matrices, peer_ctx, broad, v)
        sim["equity"].rename("equity").to_csv(out / f"broad_equity_{v.name}.csv")
        sim["trades"].to_csv(out / f"broad_trades_{v.name}.csv", index=False)
        result["broad_portfolio"][v.name] = {
            "metrics": core.period_metrics(sim["equity"]),
            "trade_summary": core.trade_summary(sim["trades"]),
            "coverage": sim["coverage"],
            "vs_base": None if v.name == "BASE" else {
                "2022_plus": core.bootstrap_period(sim["equity"], base_sim["equity"], core.PANEL_START, 710000 + core.VARIANTS.index(v)),
                "2024_plus": core.bootstrap_period(sim["equity"], base_sim["equity"], core.CONFIRM_START, 720000 + core.VARIANTS.index(v)),
                "2025_plus": core.bootstrap_period(sim["equity"], base_sim["equity"], core.RECENT_START, 730000 + core.VARIANTS.index(v)),
            },
        }

    # BASE fixed-entry replay should reproduce the baseline trade return mechanically.
    replay = pd.read_csv(out / "paired_strict_BASE.csv")
    err = pd.to_numeric(replay["delta_vs_baseline"], errors="coerce").dropna().abs()
    result["fixed_entry_replay_qa"] = {
        "n": int(len(err)),
        "mean_abs_error": float(err.mean()) if len(err) else None,
        "max_abs_error": float(err.max()) if len(err) else None,
    }
    result["guardrails"] = [
        "Strict PIT is primary. Current-classification mapping is explicitly look-ahead sensitivity only.",
        "Fixed-entry paired tests hold original entry and original baseline exit cap fixed, isolating Rotation exit action from portfolio refill effects.",
        "No Theme56 current-membership retrospective is used as primary evidence.",
        "No production rule is modified by this research workflow.",
    ]
    (out / "summary_rotation_exit_sensitivity.json").write_text(json.dumps(core.safe(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== ROTATION_EXIT_SENSITIVITY_JSON ===")
    print(json.dumps(core.safe(result), ensure_ascii=False, indent=2))
    print("=== END_ROTATION_EXIT_SENSITIVITY_JSON ===")


if __name__ == "__main__":
    main()
