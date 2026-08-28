from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

import build_dashboard as bd
from research.rulebook import audit_integrated_allocation as base
from research.rulebook_v2 import audit_market_stop_reentry as ms

ANALYSIS_START = base.ANALYSIS_START
ANALYSIS_END = base.ANALYSIS_END
DISCOVERY_END = base.DISCOVERY_END
CONFIRM_START = base.CONFIRM_START
COST = base.COST


def safe(x):
    if isinstance(x, dict):
        return {str(k): safe(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [safe(v) for v in x]
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, (np.floating, float)):
        v = float(x)
        return v if math.isfinite(v) else None
    if isinstance(x, pd.Timestamp):
        return x.isoformat()
    return x


def normalize_index(obj):
    z = obj.copy()
    idx = pd.to_datetime(z.index)
    try:
        idx = idx.tz_localize(None)
    except TypeError:
        idx = idx.tz_convert(None)
    z.index = idx.normalize()
    return z[~z.index.duplicated(keep="last")].sort_index()


def build_mc_features(asof: str) -> pd.DataFrame:
    macro = bd._fetch_mc_long_history(asof=pd.Timestamp(asof))
    if len(macro) < 50:
        raise RuntimeError(f"MC long-history coverage too low: {len(macro)}/57")
    mc, _breakdown, _dropped, _active, vals = bd.mri_frame(macro, W=None)
    vals = normalize_index(vals)
    mc = normalize_index(pd.to_numeric(mc, errors="coerce").rename("mc"))
    z = vals.join(mc, how="outer")
    for h in (1, 3, 5, 10):
        z[f"mc_d{h}"] = z.mc - z.mc.shift(h)
    z["mc_up1"] = z.mc_d1 > 0
    return z


def build_leader_features(market: dict) -> pd.DataFrame:
    C = market["close"].astype(float)
    H = market["high"].astype(float)
    V = market["volume"].astype(float)
    ma50 = C.rolling(50).mean()
    ma200 = C.rolling(200).mean()
    dv = (C * V).rolling(20, min_periods=15).mean()
    split_bad = (C.pct_change(fill_method=None).abs() > 1.5).rolling(189).max().fillna(0).astype(bool)
    pool = (ma50 > ma200) & (C >= 5.0) & (dv >= 10_000_000.0) & ~split_bad
    r189 = C.pct_change(189, fill_method=None).where(pool)
    rk = r189.rank(axis=1, ascending=False)
    rs189p = r189.rank(axis=1, pct=True) * 100.0
    rs63 = C.pct_change(63, fill_method=None).where(pool).rank(axis=1, pct=True) * 100.0
    ret20 = C.pct_change(20, fill_method=None)
    d52 = C / H.rolling(252).max() - 1.0

    observable = (
        C.notna() & ma200.notna() & ma50.notna() & dv.notna() & C.shift(189).notna() & ~split_bad
    )
    was24 = rk.shift(20) <= 24
    rank_drop = was24 & observable & pool & (rk > 36)
    elig_drop = was24 & observable & ~pool
    den_all = was24.sum(axis=1).replace(0, np.nan)
    den_obs = (was24 & observable).sum(axis=1).replace(0, np.nan)
    coverage = den_obs / den_all
    f1 = (rank_drop | elig_drop).sum(axis=1) / den_obs
    f1 = f1.where(coverage >= 0.70)

    top24 = rk <= 24
    obs63 = top24 & rs63.notna()
    f2 = ((rs63 < 85.0) & obs63).sum(axis=1) / obs63.sum(axis=1).replace(0, np.nan)

    qual = (rs189p >= 85.0) & (C > ma200) & pool
    f3 = (qual & ((ret20 <= 0) | (d52 < -0.15))).sum(axis=1) / qual.sum(axis=1).replace(0, np.nan)

    obs50 = C.notna() & ma50.notna()
    obs200 = C.notna() & ma200.notna()
    stock_pa50 = ((C > ma50) & obs50).sum(axis=1) / obs50.sum(axis=1).replace(0, np.nan)
    stock_pa200 = ((C > ma200) & obs200).sum(axis=1) / obs200.sum(axis=1).replace(0, np.nan)

    z = pd.DataFrame(index=C.index)
    z["f1"] = f1
    z["f1_coverage"] = coverage
    z["f2"] = f2
    z["f3"] = f3
    z["leader_queue_n"] = qual.sum(axis=1)
    z["stock_pa50"] = stock_pa50
    z["stock_pa200"] = stock_pa200
    z["stock_pa50_d10"] = stock_pa50 - stock_pa50.shift(10)
    z["stock_pa200_d10"] = stock_pa200 - stock_pa200.shift(10)
    return z


def candidate_forward_returns(market: dict, signal: dict) -> pd.DataFrame:
    C, O = market["close"], market["open"]
    leader = (
        (signal["sma50"] > signal["sma200"])
        & (signal["dollar_volume"] >= 10_000_000.0)
        & (C >= 5.0)
        & (signal["rs189"] >= 85.0)
        & (signal["rs63"] >= 85.0)
        & (C > signal["sma200"])
    )
    leader = leader & (~signal["excluded"])
    ranks = signal["rs189"].where(leader).rank(axis=1, ascending=False, method="first")
    top12 = ranks <= 12
    out = pd.DataFrame(index=C.index)
    entry = O.shift(-1)
    for h in (5, 10, 20):
        r = C.shift(-h) / entry - 1.0 - 2.0 * COST
        out[f"basket_{h}"] = r.where(top12).mean(axis=1, skipna=True)
        out[f"basket_n_{h}"] = r.where(top12).count(axis=1)
    return out


def block_ci(frame: pd.DataFrame, mask: pd.Series, col: str, seed: int) -> tuple[float | None, float | None]:
    q = frame.loc[mask & frame[col].notna(), [col]].copy()
    if len(q) < 40:
        return None, None
    pos = pd.Series(np.arange(len(frame.index)), index=frame.index)
    q["block"] = (pos.reindex(q.index).to_numpy() // 20).astype(int)
    means = q.groupby("block", observed=True)[col].mean().to_numpy(float)
    if len(means) < 5:
        return None, None
    rng = np.random.default_rng(seed)
    draws = rng.choice(means, size=(2000, len(means)), replace=True).mean(axis=1)
    lo, hi = np.quantile(draws, [0.025, 0.975])
    return float(lo), float(hi)


def outcome_stats(frame: pd.DataFrame, mask: pd.Series, period: str, seed: int) -> dict:
    if period == "DISCOVERY":
        pm = frame.index <= DISCOVERY_END
    elif period == "CONFIRM":
        pm = frame.index >= CONFIRM_START
    else:
        pm = pd.Series(True, index=frame.index)
    m = pd.Series(mask, index=frame.index).fillna(False) & pd.Series(pm, index=frame.index)
    z = frame.loc[m & frame.basket_20.notna(), "basket_20"]
    if z.empty:
        return {"n": 0}
    pos = z[z > 0].sum()
    neg = -z[z < 0].sum()
    ci = block_ci(frame, m, "basket_20", seed)
    return {
        "n": int(len(z)),
        "mean20": float(z.mean()),
        "median20": float(z.median()),
        "win20": float((z > 0).mean()),
        "pf20": None if neg <= 0 else float(pos / neg),
        "p10_20": float(z.quantile(0.10)),
        "ci95_mean20": list(ci),
        "mean5": float(frame.loc[m, "basket_5"].mean()),
        "mean10": float(frame.loc[m, "basket_10"].mean()),
    }


def threshold_scan(frame: pd.DataFrame) -> pd.DataFrame:
    specs = [
        ("mc", ">=", [15, 20, 25, 30, 35, 40, 45, 50]),
        ("pillar_short", ">=", [30, 40, 50, 60, 70]),
        ("pillar_medium", ">=", [30, 40, 50, 60, 70]),
        ("pillar_long", ">=", [30, 40, 50, 60, 70]),
        ("pillar_damage", ">=", [30, 40, 50, 60, 70]),
        ("breadth_delta10", ">=", [-10, -5, 0, 5, 10]),
        ("stock_pa50", ">=", [0.30, 0.40, 0.50, 0.60, 0.70]),
        ("stock_pa50_d10", ">=", [-0.10, -0.05, 0.0, 0.05, 0.10]),
        ("f1", "<=", [0.20, 0.30, 0.40, 0.50]),
        ("f2", "<=", [0.25, 0.40, 0.50, 0.60]),
        ("f3", "<=", [0.40, 0.50, 0.60, 0.70]),
    ]
    rows = []
    seed = 100
    for feature, op, levels in specs:
        for level in levels:
            mask = frame[feature] >= level if op == ">=" else frame[feature] <= level
            for period in ("DISCOVERY", "CONFIRM"):
                st = outcome_stats(frame, mask, period, seed)
                rows.append({"feature": feature, "op": op, "threshold": level, "period": period, **st})
                seed += 1
    return pd.DataFrame(rows)


def combo_scan(frame: pd.DataFrame) -> pd.DataFrame:
    nq_bg = frame.nq_color.isin(["Blue", "Green"])
    nq_not_red = ~frame.nq_color.eq("Red")
    combos = {
        "NQ_BG": nq_bg,
        "NQ_NOT_RED": nq_not_red,
        "NQ_BG_MC20": nq_bg & (frame.mc >= 20),
        "NQ_BG_MC30": nq_bg & (frame.mc >= 30),
        "NQ_BG_MC35": nq_bg & (frame.mc >= 35),
        "NQ_BG_MC35_F1LT30": nq_bg & (frame.mc >= 35) & (frame.f1 < 0.30),
        "NQ_BG_MC35_F2LT40": nq_bg & (frame.mc >= 35) & (frame.f2 < 0.40),
        "NQ_BG_MC35_F3LT60": nq_bg & (frame.mc >= 35) & (frame.f3 < 0.60),
        "NQ_BG_MC30_BD0": nq_bg & (frame.mc >= 30) & (frame.breadth_delta10 >= 0),
        "NQ_BG_MC30_PA50": nq_bg & (frame.mc >= 30) & (frame.stock_pa50 >= 0.50),
        "NOT_RED_MC20_UP1": nq_not_red & (frame.mc >= 20) & (frame.mc_d1 > 0),
        "NOT_RED_MC25_BD0": nq_not_red & (frame.mc >= 25) & (frame.breadth_delta10 >= 0),
        "NOT_RED_MC25_BD0_F3LT60": nq_not_red & (frame.mc >= 25) & (frame.breadth_delta10 >= 0) & (frame.f3 < 0.60),
    }
    rows = []
    seed = 5000
    for name, mask in combos.items():
        for period in ("DISCOVERY", "CONFIRM"):
            rows.append({"rule": name, "period": period, **outcome_stats(frame, mask, period, seed)})
            seed += 1
    return pd.DataFrame(rows)


def permission_from_mask(frame: pd.DataFrame, mask: pd.Series) -> pd.DataFrame:
    p = pd.Series(mask, index=frame.index).fillna(False).astype(bool)
    return pd.DataFrame({
        "permission": p,
        "recovery": p & ~p.shift(1, fill_value=False),
        "nq_color": frame.nq_color.astype(str),
    }, index=frame.index)


def reentry_permission(frame: pd.DataFrame, trigger: pd.Series) -> pd.DataFrame:
    color = frame.nq_color.astype(str)
    trig = pd.Series(trigger, index=frame.index).fillna(False).astype(bool)
    permission = pd.Series(False, index=frame.index, dtype=bool)
    recovery = pd.Series(False, index=frame.index, dtype=bool)
    seen_red = False
    reopened = False
    prior = False
    for d in frame.index:
        c = color.at[d]
        if c == "Red":
            seen_red = True
            reopened = False
            allowed = False
        elif not seen_red:
            allowed = c in ("Blue", "Green")
        else:
            if (not reopened) and trig.at[d]:
                reopened = True
            allowed = reopened
        permission.at[d] = allowed
        recovery.at[d] = allowed and not prior
        prior = allowed
    return pd.DataFrame({"permission": permission, "recovery": recovery, "nq_color": color}, index=frame.index)


def simulation_comparison(frame: pd.DataFrame, market: dict, signal: dict) -> pd.DataFrame:
    nq_bg = frame.nq_color.isin(["Blue", "Green"])
    dynamic = {
        "BASE_NQ_BG": nq_bg,
        "NQ_BG_MC20": nq_bg & (frame.mc >= 20),
        "NQ_BG_MC30": nq_bg & (frame.mc >= 30),
        "NQ_BG_MC35": nq_bg & (frame.mc >= 35),
        "NQ_BG_MC35_F1LT30": nq_bg & (frame.mc >= 35) & (frame.f1 < 0.30),
        "NQ_BG_MC35_F2LT40": nq_bg & (frame.mc >= 35) & (frame.f2 < 0.40),
        "NQ_BG_MC35_F3LT60": nq_bg & (frame.mc >= 35) & (frame.f3 < 0.60),
    }
    rows = []
    for name, mask in dynamic.items():
        _res, daily = ms.simulate_core(market, signal, permission_from_mask(frame, mask), force_exit_red=True)
        for period, vals in ms.period_metrics(daily).items():
            if period in ("ALL", "DISCOVERY", "CONFIRM", "2018Q4", "COVID2020", "BEAR2022"):
                rows.append({"family": "ongoing_gate", "rule": name, "period": period, **vals})

    not_red = ~frame.nq_color.eq("Red")
    triggers = {
        "RESTART_NQ_BG": nq_bg,
        "RESTART_MC20_UP1": not_red & (frame.mc >= 20) & (frame.mc_d1 > 0),
        "RESTART_MC25_BD0": not_red & (frame.mc >= 25) & (frame.breadth_delta10 >= 0),
        "RESTART_MC25_BD0_F3LT60": not_red & (frame.mc >= 25) & (frame.breadth_delta10 >= 0) & (frame.f3 < 0.60),
        "RESTART_MC30_BD5_F3LT60": not_red & (frame.mc >= 30) & (frame.breadth_delta10 >= 5) & (frame.f3 < 0.60),
        "RESTART_MC25_PA50UP_F3LT60": not_red & (frame.mc >= 25) & (frame.stock_pa50_d10 >= 0) & (frame.f3 < 0.60),
    }
    for name, trigger in triggers.items():
        _res, daily = ms.simulate_core(market, signal, reentry_permission(frame, trigger), force_exit_red=True)
        for period, vals in ms.period_metrics(daily).items():
            if period in ("ALL", "DISCOVERY", "CONFIRM", "2018Q4", "COVID2020", "BEAR2022"):
                rows.append({"family": "restart_only", "rule": name, "period": period, **vals})
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--output", required=True)
    ap.add_argument("--asof", default="2026-08-28")
    args = ap.parse_args()
    root = Path(args.root)
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    print("LOAD_MARKET", flush=True)
    market = base.load_full_market(root)
    signal = base.core_signal_frames(market, root)
    calendar = market["close"].index[(market["close"].index >= ANALYSIS_START) & (market["close"].index <= ANALYSIS_END)]

    print("BUILD_MC", flush=True)
    mc = build_mc_features(args.asof)
    print("BUILD_NQSAR", flush=True)
    nq = base.mn.build_nqsar("2010-01-01", str((ANALYSIS_END + pd.Timedelta(days=7)).date()))
    print("BUILD_LEADER_FEATURES", flush=True)
    leaders = build_leader_features(market)
    print("BUILD_FORWARD_BASKETS", flush=True)
    fwd = candidate_forward_returns(market, signal)

    frame = pd.DataFrame(index=calendar)
    frame = frame.join(mc, how="left").join(leaders, how="left").join(fwd, how="left")
    frame["nq_color"] = nq.nq_color.reindex(frame.index).ffill()
    frame = frame.dropna(subset=["mc", "nq_color"])
    frame.to_csv(out / "daily_indicator_frame.csv.gz", compression="gzip")

    features = [
        "mc", "mc_d1", "mc_d5", "pillar_short", "pillar_medium", "pillar_long", "pillar_damage",
        "breadth_level", "breadth_delta10", "f1", "f2", "f3", "stock_pa50", "stock_pa200",
        "stock_pa50_d10", "stock_pa200_d10",
    ]
    corr = frame[features].corr(method="spearman", min_periods=100)
    corr.to_csv(out / "indicator_spearman.csv")

    th = threshold_scan(frame)
    th.to_csv(out / "threshold_scan.csv", index=False)
    combos = combo_scan(frame)
    combos.to_csv(out / "combo_scan.csv", index=False)
    sims = simulation_comparison(frame, market, signal)
    sims.to_csv(out / "simulation_comparison.csv", index=False)

    summary = {
        "status": "CUSTOM_MARKET_MODE_AUDIT_V1",
        "coverage": {"start": str(frame.index.min().date()), "end": str(frame.index.max().date()), "sessions": len(frame)},
        "indicators": {
            "NQSAR": "production-reconstructed NQ four-color state",
            "MC57": "production 57 ETF x 12 equal-metric MC15 temperature",
            "MC_pillars": "momentum / breadth / trend / damage plus breadth level and 10-session change",
            "F1": "20-session-ago top24 leader dropout rate; dashboard reference warning 20%, red 30%",
            "F2": "current top24 whose RS63 is below85; dashboard reference caution25%, red40%",
            "F3": "RS189>=85 queue in pullback/damage state; dashboard reference caution40%, red60%",
            "broad_breadth": "current-universe percent above 50MA/200MA and 10-session change",
        },
        "design": {
            "threshold_policy": "small predeclared grids around existing dashboard thresholds; no optimizer-selected arbitrary cutpoints",
            "validation": "2016-2021 Discovery and 2022-2026-03 Confirmation shown separately",
            "outcome": "next-open to 5/10/20-session return of daily top12 normal-stock candidates, plus full normal-stock portfolio simulation",
            "dependency_control": "Spearman correlation table used to identify redundant indicators",
            "uncertainty": "20-session cluster bootstrap CI for forward 20-session means",
        },
        "limitations": [
            "Normal-stock portfolio is the existing comparison reconstruction, not the missing exact production ledger.",
            "Current-universe survivorship bias remains in leader/breadth features and stock outcomes.",
            "Confirmation has already been inspected in prior research; it is robustness confirmation, not pristine OOS.",
            "No dashboard or main-branch logic is changed by this audit.",
        ],
    }
    (out / "summary.json").write_text(json.dumps(safe(summary), ensure_ascii=False, indent=2), encoding="utf-8")
    print("CUSTOM_MARKET_MODE_AUDIT_DONE", flush=True)


if __name__ == "__main__":
    main()
