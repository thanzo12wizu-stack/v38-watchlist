from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from research.rulebook import audit_integrated_allocation as base
from research.rulebook_v2 import audit_market_stop_reentry as ms
from research.rulebook_v3 import audit_custom_market_modes as v1

ANALYSIS_START = base.ANALYSIS_START
ANALYSIS_END = base.ANALYSIS_END
DISCOVERY_END = base.DISCOVERY_END
CONFIRM_START = base.CONFIRM_START


def safe(x):
    if isinstance(x, dict):
        return {str(k): safe(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [safe(v) for v in x]
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, (np.floating, float)):
        z = float(x)
        return z if math.isfinite(z) else None
    if isinstance(x, pd.Timestamp):
        return x.isoformat()
    return x


def periods(index: pd.DatetimeIndex):
    return {
        "DISCOVERY": index <= DISCOVERY_END,
        "CONFIRM": index >= CONFIRM_START,
    }


def candidate_stats(frame: pd.DataFrame, mask: pd.Series) -> dict:
    z = frame.loc[mask & frame.basket_20.notna(), "basket_20"]
    if z.empty:
        return {"n": 0}
    gp = float(z[z > 0].sum())
    gl = float(-z[z < 0].sum())
    return {
        "n": int(len(z)),
        "dates": int(z.index.nunique()),
        "mean20": float(z.mean()),
        "median20": float(z.median()),
        "win20": float((z > 0).mean()),
        "pf20": None if gl <= 0 else gp / gl,
        "p10_20": float(z.quantile(0.10)),
        "p90_20": float(z.quantile(0.90)),
        "mean5": float(frame.loc[z.index, "basket_5"].mean()),
        "mean10": float(frame.loc[z.index, "basket_10"].mean()),
    }


def shallow_stats(g: pd.DataFrame) -> dict:
    z = g.dropna(subset=["entry_20"]).copy()
    if z.empty:
        return {"n": 0}
    r = pd.to_numeric(z.entry_20, errors="coerce")
    mae = pd.to_numeric(z.mae_20, errors="coerce")
    gp = float(r[r > 0].sum())
    gl = float(-r[r < 0].sum())
    return {
        "n": int(len(z)),
        "dates": int(z.signal_date.nunique()),
        "symbols": int(z.symbol.nunique()),
        "mean20": float(r.mean()),
        "median20": float(r.median()),
        "win20": float((r > 0).mean()),
        "pf20": None if gl <= 0 else gp / gl,
        "mae20": float(mae.mean()),
        "p10_20": float(r.quantile(0.10)),
        "p90_20": float(r.quantile(0.90)),
    }


def build_frame(root: Path, asof: str):
    print("LOAD_MARKET", flush=True)
    market = base.load_full_market(root)
    signal = base.core_signal_frames(market, root)
    calendar = market["close"].index[(market["close"].index >= ANALYSIS_START) & (market["close"].index <= ANALYSIS_END)]
    print("BUILD_MC", flush=True)
    mc = v1.build_mc_features(asof)
    print("BUILD_NQSAR", flush=True)
    nq = base.mn.build_nqsar("2010-01-01", str((ANALYSIS_END + pd.Timedelta(days=7)).date()))
    print("BUILD_LEADERS", flush=True)
    leaders = v1.build_leader_features(market)
    print("BUILD_FORWARD", flush=True)
    fwd = v1.candidate_forward_returns(market, signal)
    frame = pd.DataFrame(index=calendar).join(mc, how="left").join(leaders, how="left").join(fwd, how="left")
    frame["nq_color"] = nq.nq_color.reindex(frame.index).ffill()
    frame = frame.dropna(subset=["mc", "nq_color"])
    return market, signal, frame


def normal_gate_simulations(frame: pd.DataFrame, market: dict, signal: dict) -> pd.DataFrame:
    nq_bg = frame.nq_color.isin(["Blue", "Green"])
    gates = {
        "NQ_BG": nq_bg,
        "NQ_BG_PA40": nq_bg & (frame.stock_pa50 >= 0.40),
        "NQ_BG_PA50": nq_bg & (frame.stock_pa50 >= 0.50),
        "NQ_BG_PA60": nq_bg & (frame.stock_pa50 >= 0.60),
        "NQ_BG_MC30_PA40": nq_bg & (frame.mc >= 30) & (frame.stock_pa50 >= 0.40),
        "NQ_BG_MC30_PA50": nq_bg & (frame.mc >= 30) & (frame.stock_pa50 >= 0.50),
        "NQ_BG_MC30_PA60": nq_bg & (frame.mc >= 30) & (frame.stock_pa50 >= 0.60),
        "NQ_BG_MC35_PA40": nq_bg & (frame.mc >= 35) & (frame.stock_pa50 >= 0.40),
        "NQ_BG_MC35_PA50": nq_bg & (frame.mc >= 35) & (frame.stock_pa50 >= 0.50),
        "NQ_BG_MC35_PA60": nq_bg & (frame.mc >= 35) & (frame.stock_pa50 >= 0.60),
        "NQ_BG_MC35_PA50_F3LT60": nq_bg & (frame.mc >= 35) & (frame.stock_pa50 >= 0.50) & (frame.f3 < 0.60),
    }
    rows = []
    for name, mask in gates.items():
        _result, daily = ms.simulate_core(market, signal, v1.permission_from_mask(frame, mask), force_exit_red=True)
        for period, vals in ms.period_metrics(daily).items():
            if period in ("ALL", "DISCOVERY", "CONFIRM", "2018Q4", "COVID2020", "BEAR2022"):
                rows.append({"rule": name, "period": period, **vals})
    return pd.DataFrame(rows)


def restart_simulations(frame: pd.DataFrame, market: dict, signal: dict) -> pd.DataFrame:
    not_red = ~frame.nq_color.eq("Red")
    t = {
        "RESTART_NQ_BG": frame.nq_color.isin(["Blue", "Green"]),
        "RESTART_PA40": not_red & (frame.stock_pa50 >= 0.40),
        "RESTART_PA50": not_red & (frame.stock_pa50 >= 0.50),
        "RESTART_MC20_PA40": not_red & (frame.mc >= 20) & (frame.stock_pa50 >= 0.40),
        "RESTART_MC20_PA50": not_red & (frame.mc >= 20) & (frame.stock_pa50 >= 0.50),
        "RESTART_MC35_PA40": not_red & (frame.mc >= 35) & (frame.stock_pa50 >= 0.40),
        "RESTART_MC35_PA50": not_red & (frame.mc >= 35) & (frame.stock_pa50 >= 0.50),
        "RESTART_MC20_PA40_D10_GE_M5": not_red & (frame.mc >= 20) & (frame.stock_pa50 >= 0.40) & (frame.stock_pa50_d10 >= -0.05),
        "RESTART_MC20_PA40_D10_GE0": not_red & (frame.mc >= 20) & (frame.stock_pa50 >= 0.40) & (frame.stock_pa50_d10 >= 0.0),
        "RESTART_MC20_PA50_D10_GE_M5": not_red & (frame.mc >= 20) & (frame.stock_pa50 >= 0.50) & (frame.stock_pa50_d10 >= -0.05),
    }
    rows = []
    for name, trigger in t.items():
        _result, daily = ms.simulate_core(market, signal, v1.reentry_permission(frame, trigger), force_exit_red=True)
        for period, vals in ms.period_metrics(daily).items():
            if period in ("ALL", "DISCOVERY", "CONFIRM", "2018Q4", "COVID2020", "BEAR2022"):
                rows.append({"rule": name, "period": period, **vals})
    return pd.DataFrame(rows)


def mode_masks(frame: pd.DataFrame, family: str) -> dict[str, pd.Series]:
    nq_bg = frame.nq_color.isin(["Blue", "Green"])
    if family == "MC30_PA50":
        attack = nq_bg & (frame.mc >= 30) & (frame.stock_pa50 >= 0.50)
    elif family == "MC35_PA40":
        attack = nq_bg & (frame.mc >= 35) & (frame.stock_pa50 >= 0.40)
    elif family == "MC35_PA50":
        attack = nq_bg & (frame.mc >= 35) & (frame.stock_pa50 >= 0.50)
    else:
        raise ValueError(family)
    selective = nq_bg & ~attack
    repair = (~nq_bg) & (frame.mc >= 20) & (frame.mc < 50) & (frame.mc_d1 > 0) & (frame.stock_pa50_d10 >= 0)
    defense = ~(attack | selective | repair)
    return {"ATTACK": attack, "SELECTIVE": selective, "REPAIR": repair, "DEFENSE": defense}


def mode_outcomes(frame: pd.DataFrame, shallow_input: Path) -> pd.DataFrame:
    shallow = pd.read_csv(shallow_input, compression="gzip", parse_dates=["signal_date", "entry_date", "touch_date"])
    shallow = shallow[
        (shallow.cohort == "MATURE")
        & (shallow.method == "M10_RSI60_DD075")
        & (shallow.mc >= 20)
        & (shallow.mc < 50)
        & shallow.mc_up1.astype(bool)
        & (shallow.sector_rs63_pct >= 70)
    ].copy()
    shallow = shallow[shallow.signal_date.between(ANALYSIS_START, ANALYSIS_END)].copy()

    rows = []
    pm = periods(frame.index)
    for family in ("MC30_PA50", "MC35_PA40", "MC35_PA50"):
        masks = mode_masks(frame, family)
        mode_series = pd.Series(index=frame.index, dtype=object)
        for mode, mask in masks.items():
            mode_series.loc[mask] = mode
        mode_map = mode_series.rename("mode").rename_axis("signal_date").reset_index()
        sh = shallow.merge(mode_map, on="signal_date", how="left", validate="many_to_one")
        for mode, mask in masks.items():
            for period, period_mask in pm.items():
                st = candidate_stats(frame, mask & pd.Series(period_mask, index=frame.index))
                rows.append({"family": family, "sleeve": "NORMAL_CANDIDATE", "mode": mode, "period": period, **st})
            for period, q in (("DISCOVERY", sh.signal_date <= DISCOVERY_END), ("CONFIRM", sh.signal_date >= CONFIRM_START)):
                st = shallow_stats(sh[(sh.mode == mode) & q])
                rows.append({"family": family, "sleeve": "SHALLOW", "mode": mode, "period": period, **st})
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--output", required=True)
    ap.add_argument("--asof", default="2026-08-28")
    ap.add_argument("--shallow-input", required=True)
    args = ap.parse_args()
    root = Path(args.root)
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    market, signal, frame = build_frame(root, args.asof)
    frame.to_csv(out / "daily_frame_v2.csv.gz", compression="gzip")

    gates = normal_gate_simulations(frame, market, signal)
    gates.to_csv(out / "normal_gate_simulations.csv", index=False)
    restarts = restart_simulations(frame, market, signal)
    restarts.to_csv(out / "restart_simulations.csv", index=False)
    modes = mode_outcomes(frame, Path(args.shallow_input))
    modes.to_csv(out / "mode_outcomes.csv", index=False)

    summary = {
        "status": "CUSTOM_MARKET_MODE_AUDIT_V2",
        "coverage": {"start": str(frame.index.min().date()), "end": str(frame.index.max().date()), "sessions": int(len(frame))},
        "focus": {
            "normal_structure": "NQSAR Blue/Green",
            "temperature": "MC57 fixed at 30/35 only after V1 plateau review",
            "broad_breadth": "current-universe percent above 50MA fixed at 40/50/60 after V1 plateau review",
            "direction": "10-session change in broad 50MA breadth only for focused restart tests",
            "damage": "F3<60 tested once as optional veto; F1/F2 removed after V1 trading-gate failure",
        },
        "mode_families": {
            "MC30_PA50": "ATTACK=NQSAR Blue/Green + MC>=30 + >50MA breadth>=50%; SELECTIVE=remaining Blue/Green; REPAIR=not Blue/Green + MC20-50 rising + 10d broad breadth nonnegative; DEFENSE=remainder",
            "MC35_PA40": "same, ATTACK uses MC>=35 and >50MA breadth>=40%",
            "MC35_PA50": "same, ATTACK uses MC>=35 and >50MA breadth>=50%",
        },
        "validation_policy": "No broad optimization in V2. Only V1 plateau-adjacent thresholds are compared on full normal-stock portfolio and the existing shallow signal set.",
        "limitations": [
            "Normal-stock sleeve is the existing comparison reconstruction, not the missing exact production ledger.",
            "Current-universe survivorship bias remains in broad breadth and stock outcomes.",
            "2022+ has already been inspected and is robustness confirmation rather than pristine OOS.",
            "Shallow sleeve uses the already-frozen mature M10 RSI60 micro-pullback condition; V2 changes only market-mode labeling.",
            "No main-branch or dashboard logic is changed.",
        ],
    }
    (out / "summary.json").write_text(json.dumps(safe(summary), ensure_ascii=False, indent=2), encoding="utf-8")
    print("CUSTOM_MARKET_MODE_V2_DONE", flush=True)


if __name__ == "__main__":
    main()
