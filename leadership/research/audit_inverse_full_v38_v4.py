from __future__ import annotations
import argparse, json
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd
import yfinance as yf

import audit_gross100_allocation as g100

TRADING_DAYS = 252
BASE_T_COST_BP = 5.0
PRODUCTS = ["PSQ", "QID", "SQQQ"]
PERIODS = {
    "FULL": ("2016-01-04", "2026-03-20"),
    "TRAIN_2016_2021": ("2016-01-04", "2021-12-31"),
    "HOLDOUT_2022_2026": ("2022-01-03", "2026-03-20"),
    "2016_2019": ("2016-01-04", "2019-12-31"),
    "2020_2021": ("2020-01-01", "2021-12-31"),
    "2022_2023": ("2022-01-03", "2023-12-29"),
    "2024_2026": ("2024-01-02", "2026-03-20"),
}


def safe(x: Any) -> Any:
    if isinstance(x, dict): return {str(k): safe(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)): return [safe(v) for v in x]
    if isinstance(x, (np.integer,)): return int(x)
    if isinstance(x, (np.floating,)): return None if not np.isfinite(x) else float(x)
    if isinstance(x, pd.Timestamp): return str(x)
    return x


def norm_idx(x):
    z = pd.DatetimeIndex(pd.to_datetime(x))
    if z.tz is not None:
        z = z.tz_convert("America/New_York").tz_localize(None)
    return z.normalize()


def metrics(r: pd.Series) -> dict[str, float]:
    x = pd.to_numeric(r, errors="coerce").fillna(0).to_numpy(float)
    if len(x) == 0:
        return {"cagr": np.nan, "mdd": np.nan, "sharpe": np.nan, "calmar": np.nan, "end": np.nan}
    eq = np.cumprod(1 + x)
    yrs = max((len(x) - 1) / 252, 1e-9)
    cagr = float(eq[-1] ** (1 / yrs) - 1) if eq[-1] > 0 else -1.0
    dd = eq / np.maximum.accumulate(eq) - 1
    sd = float(np.std(x, ddof=1))
    sh = float(np.sqrt(252) * np.mean(x) / sd) if sd > 0 else np.nan
    return {
        "cagr": cagr,
        "mdd": float(dd.min()),
        "sharpe": sh,
        "calmar": float(cagr / abs(dd.min())) if dd.min() < 0 else np.nan,
        "end": float(eq[-1]),
    }


def rolling252(r: pd.Series) -> dict[str, float]:
    z = (1 + pd.to_numeric(r, errors="coerce").fillna(0)).rolling(252).apply(np.prod, raw=True) - 1
    z = z.dropna()
    return {
        "rolling252_worst": float(z.min()),
        "rolling252_p10": float(z.quantile(.10)),
        "rolling252_median": float(z.median()),
        "rolling252_positive": float((z > 0).mean()),
    }


def cooldown_events(cond: pd.Series, cooldown: int) -> pd.Series:
    c = cond.fillna(False).astype(bool)
    raw = (c & ~c.shift(1, fill_value=False)).to_numpy(bool)
    out = np.zeros(len(c), bool)
    last = -10**9
    for i, x in enumerate(raw):
        if x and i - last > cooldown:
            out[i] = True
            last = i
    return pd.Series(out, index=c.index)


def build_active(events: pd.Series, hold: int, kill_signal: pd.Series | None = None) -> tuple[pd.Series, pd.Series]:
    # Signal is known at close i. Position starts at next session open: return indices i+1..i+hold.
    n = len(events)
    active = np.zeros(n, bool)
    eid = np.full(n, -1, int)
    for evnum, i in enumerate(np.flatnonzero(events.to_numpy(bool))):
        for t in range(i + 1, min(n, i + 1 + hold)):
            if kill_signal is not None and t - 1 >= 0 and bool(kill_signal.iloc[t - 1]):
                break
            active[t] = True
            eid[t] = evnum
    return pd.Series(active, index=events.index), pd.Series(eid, index=events.index)


def price_returns(idx: pd.DatetimeIndex, start: str, end: str) -> pd.DataFrame:
    raw = yf.download(
        PRODUCTS,
        start=(pd.Timestamp(start) - pd.Timedelta(days=20)).date().isoformat(),
        end=(pd.Timestamp(end) + pd.Timedelta(days=10)).date().isoformat(),
        auto_adjust=True,
        actions=False,
        progress=False,
        threads=False,
        group_by="column",
    )
    if raw.empty:
        raise RuntimeError("inverse product download empty")
    op = raw["Open"].copy()
    if isinstance(op, pd.Series):
        op = op.to_frame(PRODUCTS[0])
    op.index = norm_idx(op.index)
    op = op[~op.index.duplicated(keep="last")].sort_index()
    out = pd.DataFrame(index=idx)
    for p in PRODUCTS:
        s = pd.to_numeric(op[p], errors="coerce").reindex(idx)
        # Open-to-next-open return indexed by opening date, same convention as Stage56 TQQQ return.
        out[p] = s.shift(-1) / s - 1
    return out


def baseline_components(ordinary, reset, tq, feat):
    d = (feat.reset_index()
         .merge(ordinary, on="date", how="inner")
         .merge(reset, on="date", how="inner")
         .merge(tq, on="date", how="inner"))
    d = d.sort_values("date").reset_index(drop=True)
    target = pd.to_numeric(d["target_M30_TOUCH30_F80_D10"], errors="coerce").fillna(0).to_numpy(float)
    eff_t = np.zeros(len(d), float)
    eff_t[2:] = target[:-2]
    desired_o = pd.to_numeric(d["gross_exposure_ord"], errors="coerce").fillna(0).to_numpy(float)
    desired_r = pd.to_numeric(d["gross_exposure_rsi"], errors="coerce").fillna(0).to_numpy(float)
    alloc = g100.reset_first_tqqq_floor(np.column_stack([eff_t, desired_o, desired_r]), .65)
    at, ao, ar = alloc.T
    ro = pd.to_numeric(d["return_ord"], errors="coerce").fillna(0).to_numpy(float)
    rr = pd.to_numeric(d["return_rsi"], errors="coerce").fillna(0).to_numpy(float)
    rt = pd.to_numeric(d["tqqq_ret_usd"], errors="coerce").fillna(0).to_numpy(float)
    so = np.divide(ao, desired_o, out=np.zeros_like(ao), where=desired_o > 1e-12)
    sr = np.divide(ar, desired_r, out=np.zeros_like(ar), where=desired_r > 1e-12)
    d["base_t"] = at
    d["base_o"] = ao
    d["base_r"] = ar
    d["base_gross"] = at + ao + ar
    d["o_contrib"] = so * ro
    d["r_contrib"] = sr * rr
    d["tqqq_ret"] = rt
    turn = np.zeros(len(d))
    turn[1:] = np.abs(np.diff(at))
    d["baseline_ret"] = d.o_contrib + d.r_contrib + at * rt - turn * (BASE_T_COST_BP / 10000)
    return d


def signal_defs(d: pd.DataFrame) -> dict[str, pd.Series]:
    red = d["nq_color"].astype(str).eq("Red")
    below50 = pd.to_numeric(d["qqq_dist_sma50"], errors="coerce") < 0
    slope50 = pd.to_numeric(d["sma50_slope10"], errors="coerce") < 0
    core = red & below50 & slope50
    notdeep = ((pd.to_numeric(d["qqq_rsi14"], errors="coerce") > 34)
               & (pd.to_numeric(d["qqq_atr_dist50"], errors="coerce") > -2.0)
               & (pd.to_numeric(d["qqq_dd20"], errors="coerce") > -.10))
    failed = (below50
              & (pd.to_numeric(d["qqq_ret5"], errors="coerce") > 0)
              & (pd.to_numeric(d["qqq_ret1"], errors="coerce") < 0)
              & pd.to_numeric(d["qqq_dist_ema21"], errors="coerce").between(-.015, .01)
              & slope50 & red)
    return {
        "CORE_TREND_NQSAR": core,
        "CORE_NOTDEEP": core & notdeep,
        "CORE_RATE": core & (pd.to_numeric(d["real10_chg5_z252"], errors="coerce") >= .75),
        "CORE_MC": core & (pd.to_numeric(d["mc_chg5"], errors="coerce") < -3),
        "CORE_BREADTH": core & (pd.to_numeric(d["breadth50"], errors="coerce") < 50) & (pd.to_numeric(d["breadth_chg10"], errors="coerce") < 0),
        "FAILED_RALLY_NQSAR": failed,
        "RED_ENTRY_NOTDEEP": pd.to_numeric(d["nq_red_entry"], errors="coerce").fillna(0).eq(1) & notdeep,
    }


def guards(d: pd.DataFrame) -> dict[str, pd.Series]:
    panic_actual = pd.to_numeric(d["panic_episode"], errors="coerce").fillna(0) > 0
    stage56 = (pd.to_numeric(d["target_M30_TOUCH30_F80_D10"], errors="coerce").fillna(0)
               > pd.to_numeric(d["target_CURRENT30"], errors="coerce").fillna(0) + 1e-9)
    deep = ((pd.to_numeric(d["vix_term_ratio"], errors="coerce") > 1.05)
            | (pd.to_numeric(d["qqq_rsi14"], errors="coerce") <= 30)
            | (pd.to_numeric(d["qqq_atr_dist50"], errors="coerce") <= -2.5))
    return {
        "PANIC_ACTUAL": panic_actual,
        "PANIC_OR_STAGE56": panic_actual | stage56,
        "PANIC_DEEP": panic_actual | stage56 | deep,
    }


def overlay_positions(d, active: pd.Series, design: str) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    bt = d.base_t.to_numpy(float)
    bo = d.base_o.to_numpy(float)
    br = d.base_r.to_numpy(float)
    act = active.to_numpy(bool)
    t = bt.copy()
    inv = {p: np.zeros(len(d), float) for p in PRODUCTS}
    gross = bt + bo + br
    spare = np.maximum(0, 1 - gross)
    if design == "T_OFF":
        t[act] = 0
    elif design == "T_TRIM50":
        t[act] = .5 * bt[act]
    elif design == "QID_FLIP_T":
        q = np.minimum(bt, .30)
        t[act] = np.maximum(0, bt[act] - q[act])
        inv["QID"][act] = q[act]
    elif design == "QID_CASH15":
        inv["QID"][act] = np.minimum(.15, spare[act])
    elif design == "QID_CASH30":
        inv["QID"][act] = np.minimum(.30, spare[act])
    elif design == "QID_TARGET30":
        cap = np.minimum(.30, bt + spare)
        q = np.where(act, cap, 0)
        take = np.minimum(bt, q)
        t = np.where(act, bt - take, bt)
        inv["QID"] = q
    elif design == "PSQ_CASH30":
        inv["PSQ"][act] = np.minimum(.30, spare[act])
    elif design == "SQQQ_CASH10":
        inv["SQQQ"][act] = np.minimum(.10, spare[act])
    elif design == "SQQQ_CASH15":
        inv["SQQQ"][act] = np.minimum(.15, spare[act])
    else:
        raise ValueError(design)
    total = t + bo + br + sum(inv.values())
    if np.nanmax(total) > 1.0000001:
        raise RuntimeError(f"gross cap violation {design} {np.nanmax(total)}")
    return t, inv


def compute_variant(d, invret, active, design, cost_bp: float) -> pd.Series:
    t, inv = overlay_positions(d, active, design)
    ret = d.o_contrib.to_numpy(float) + d.r_contrib.to_numpy(float) + t * d.tqqq_ret.to_numpy(float)
    tt = np.zeros(len(d))
    tt[1:] = np.abs(np.diff(t))
    ret -= tt * (cost_bp / 10000)
    for p, w in inv.items():
        rp = pd.to_numeric(invret[p], errors="coerce").fillna(0).to_numpy(float)
        ret += w * rp
        tr = np.zeros(len(d))
        tr[1:] = np.abs(np.diff(w))
        ret -= tr * (cost_bp / 10000)
    return pd.Series(ret, index=d.index)


def period_metrics(d, r, row):
    for lab, (aa, bb) in PERIODS.items():
        m = (d.date >= pd.Timestamp(aa)) & (d.date <= pd.Timestamp(bb))
        z = metrics(r.loc[m])
        for k, v in z.items(): row[f"{lab}_{k}"] = v
    return row


def event_table(d, events, active, eid, variant, baseline, signal_name, design, hold, cooldown, guard_name):
    rows = []
    for j, i in enumerate(np.flatnonzero(events.to_numpy(bool))):
        mask = eid.to_numpy() == j
        if not mask.any(): continue
        diff = float(np.prod(1 + variant.to_numpy()[mask]) / np.prod(1 + baseline.to_numpy()[mask]) - 1)
        rows.append({
            "signal": signal_name, "design": design, "hold": hold, "cooldown": cooldown, "guard": guard_name,
            "event_id": j, "signal_date": d.date.iloc[i], "year": int(d.date.iloc[i].year),
            "active_days": int(mask.sum()), "delta_vs_baseline": diff,
            "baseline_window": float(np.prod(1 + baseline.to_numpy()[mask]) - 1),
            "variant_window": float(np.prod(1 + variant.to_numpy()[mask]) - 1),
            "base_t_at_first_active": float(d.base_t.to_numpy()[np.flatnonzero(mask)[0]]),
        })
    return pd.DataFrame(rows)


def leave_event_stress(d, invret, events, active, eid, design, cost, baseline):
    full = compute_variant(d, invret, active, design, cost)
    tab = event_table(d, events, active, eid, full, baseline, "CORE_TREND_NQSAR", design, 2, 10, "DYNAMIC_PANIC")
    if tab.empty: return {}
    deltas = []
    for ev in tab.event_id:
        a2 = active.copy()
        a2.loc[eid.eq(ev)] = False
        deltas.append(metrics(compute_variant(d, invret, a2, design, cost))["cagr"])
    order = tab.sort_values("delta_vs_baseline", ascending=False)
    a_top1 = active.copy()
    a_top1.loc[eid.eq(int(order.iloc[0].event_id))] = False
    a_top2 = a_top1.copy()
    if len(order) > 1:
        a_top2.loc[eid.eq(int(order.iloc[1].event_id))] = False
    return {
        "event_n": int(len(tab)),
        "event_mean_delta": float(tab.delta_vs_baseline.mean()),
        "event_median_delta": float(tab.delta_vs_baseline.median()),
        "event_win": float((tab.delta_vs_baseline > 0).mean()),
        "worst_event": float(tab.delta_vs_baseline.min()),
        "best_event": float(tab.delta_vs_baseline.max()),
        "loo_cagr_min": float(np.min(deltas)),
        "loo_cagr_max": float(np.max(deltas)),
        "top1_removed_cagr": metrics(compute_variant(d, invret, a_top1, design, cost))["cagr"],
        "top2_removed_cagr": metrics(compute_variant(d, invret, a_top2, design, cost))["cagr"],
    }


def paired_block_boot(a: pd.Series, b: pd.Series, block: int, nsim: int, seed: int) -> dict:
    aa = a.to_numpy(float); bb = b.to_numpy(float); n = len(aa)
    rng = np.random.default_rng(seed); nb = int(np.ceil(n / block)); offs = np.arange(block)
    wins = []; ddw = []; calw = []; cdelta = []; years = n / 252
    for s in range(0, nsim, 200):
        k = min(200, nsim - s)
        starts = rng.integers(0, n - block + 1, size=(k, nb))
        ix = (starts[:, :, None] + offs).reshape(k, -1)[:, :n]
        x = aa[ix]; y = bb[ix]
        lx = np.log1p(x).sum(1); ly = np.log1p(y).sum(1)
        cx = np.exp(lx / years) - 1; cy = np.exp(ly / years) - 1
        ex = np.cumprod(1 + x, axis=1); ey = np.cumprod(1 + y, axis=1)
        dx = (ex / np.maximum.accumulate(ex, axis=1) - 1).min(1)
        dy = (ey / np.maximum.accumulate(ey, axis=1) - 1).min(1)
        calx = cx / np.maximum(np.abs(dx), 1e-12); caly = cy / np.maximum(np.abs(dy), 1e-12)
        wins.append(cx > cy); ddw.append(dx >= dy); calw.append(calx > caly); cdelta.append(cx - cy)
    w = np.concatenate(wins); dw = np.concatenate(ddw); cw = np.concatenate(calw); cd = np.concatenate(cdelta)
    return {
        "block": block, "nsim": nsim,
        "p_cagr_gt_base": float(w.mean()), "p_mdd_no_worse": float(dw.mean()), "p_calmar_gt_base": float(cw.mean()),
        "cagr_delta_median": float(np.median(cd)), "cagr_delta_p05": float(np.quantile(cd, .05)), "cagr_delta_p95": float(np.quantile(cd, .95)),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", required=True)
    ap.add_argument("--gross100", required=True)
    ap.add_argument("--tqqq", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--bootstrap-sims", type=int, default=2000)
    a = ap.parse_args()
    out = Path(a.output); out.mkdir(parents=True, exist_ok=True)

    feat = pd.read_csv(a.features, compression="gzip", parse_dates=["date"]).sort_values("date")
    ordinary = pd.read_csv(Path(a.gross100) / "gross100_final_reset_components/ordinary_PEAK30_PART25_R3_daily.csv.gz", compression="gzip", parse_dates=["date"])
    reset = pd.read_csv(Path(a.gross100) / "gross100_final_reset_components/rsi_RESET_RISE30_S029_P4_H20_daily.csv.gz", compression="gzip", parse_dates=["date"])
    tq = pd.read_csv(a.tqqq, compression="gzip", parse_dates=["date"])
    ordinary = ordinary.rename(columns={"gross_exposure": "gross_exposure_ord", "return": "return_ord"})
    reset = reset.rename(columns={"gross_exposure": "gross_exposure_rsi", "return": "return_rsi"})
    d = baseline_components(ordinary, reset, tq, feat)
    idx = norm_idx(d.date); d["date"] = idx
    invret = price_returns(idx, str(d.date.min().date()), str(d.date.max().date()))
    invret.index = d.index

    bm = metrics(d.baseline_ret)
    if abs(bm["cagr"] - 0.470025795426962) > 5e-6 or abs(bm["mdd"] - (-0.2323359830178694)) > 5e-6:
        raise RuntimeError(f"baseline reproduction failed {bm}")
    sigs = signal_defs(d); gd = guards(d)
    designs = ["T_OFF", "T_TRIM50", "QID_FLIP_T", "QID_CASH15", "QID_CASH30", "QID_TARGET30", "PSQ_CASH30", "SQQQ_CASH10", "SQQQ_CASH15"]
    base_period = {}
    for lab, (aa, bb) in PERIODS.items():
        m = (d.date >= pd.Timestamp(aa)) & (d.date <= pd.Timestamp(bb))
        base_period[lab] = metrics(d.baseline_ret.loc[m])

    rows = []; ledgers = []
    for sname, cond0 in sigs.items():
        for cooldown in [5, 10, 20]:
            ev0 = cooldown_events(cond0, cooldown)
            for gname in ["STATIC_PANIC", "DYNAMIC_PANIC", "DYNAMIC_DEEP"]:
                signal_guard = gd["PANIC_OR_STAGE56"] if gname != "DYNAMIC_DEEP" else gd["PANIC_DEEP"]
                ev = ev0 & ~signal_guard
                kill = None
                if gname == "DYNAMIC_PANIC": kill = gd["PANIC_OR_STAGE56"]
                elif gname == "DYNAMIC_DEEP": kill = gd["PANIC_DEEP"]
                for hold in [1, 2, 3, 4, 5]:
                    active, eid = build_active(ev, hold, kill)
                    for design in designs:
                        for cost in [5, 10, 20]:
                            r = compute_variant(d, invret, active, design, cost)
                            mm = metrics(r)
                            row = {
                                "signal": sname, "cooldown": cooldown, "guard": gname, "hold": hold, "design": design,
                                "cost_bp": cost, "signal_events": int(ev.sum()), "active_days": int(active.sum()), "avg_gross_base": float(d.base_gross.mean()),
                                **{f"FULL_{k}": v for k, v in mm.items()},
                            }
                            for k in ["cagr", "mdd", "sharpe", "calmar"]:
                                row[f"FULL_delta_{k}"] = mm[k] - bm[k]
                            period_metrics(d, r, row)
                            rows.append(row)
                            if sname == "CORE_TREND_NQSAR" and cooldown == 10 and gname == "DYNAMIC_PANIC" and hold in [1,2,3,4,5] and cost == 5:
                                z = event_table(d, ev, active, eid, r, d.baseline_ret, sname, design, hold, cooldown, gname)
                                if len(z): ledgers.append(z)
    res = pd.DataFrame(rows)
    for lab in PERIODS:
        for k in ["cagr", "mdd", "sharpe", "calmar"]:
            res[f"{lab}_delta_{k}"] = res[f"{lab}_{k}"] - base_period[lab][k]
    subd = [f"{x}_delta_cagr" for x in ["2016_2019", "2020_2021", "2022_2023", "2024_2026"]]
    res["positive_subperiods"] = res[subd].gt(0).sum(axis=1)
    res["stable_train_hold"] = (res.TRAIN_2016_2021_delta_cagr > 0) & (res.HOLDOUT_2022_2026_delta_cagr > 0)
    res["mdd_not_worse_both"] = (res.TRAIN_2016_2021_delta_mdd >= -.01) & (res.HOLDOUT_2022_2026_delta_mdd >= -.01)
    res["robust_pass"] = res.stable_train_hold & res.mdd_not_worse_both & (res.positive_subperiods >= 3)
    res.to_csv(out / "portfolio_grid.csv", index=False)
    if ledgers:
        pd.concat(ledgers, ignore_index=True).to_csv(out / "core_event_ledger.csv", index=False)

    fixed_specs = [
        ("CORE_QID_CASH15_H2", "CORE_TREND_NQSAR", 10, 2, "QID_CASH15", 5),
        ("CORE_QID_CASH30_H2", "CORE_TREND_NQSAR", 10, 2, "QID_CASH30", 5),
        ("CORE_QID_FLIP_H2", "CORE_TREND_NQSAR", 10, 2, "QID_FLIP_T", 5),
        ("CORE_QID_TARGET30_H2", "CORE_TREND_NQSAR", 10, 2, "QID_TARGET30", 5),
        ("CORE_T_OFF_H2", "CORE_TREND_NQSAR", 10, 2, "T_OFF", 5),
        ("CORE_PSQ30_H2", "CORE_TREND_NQSAR", 10, 2, "PSQ_CASH30", 5),
        ("CORE_SQQQ10_H2", "CORE_TREND_NQSAR", 10, 2, "SQQQ_CASH10", 5),
    ]
    fixed = []; boot = []; stress = []
    for nm, sname, cd, h, design, cost in fixed_specs:
        ev = cooldown_events(sigs[sname], cd) & ~gd["PANIC_OR_STAGE56"]
        act, eid = build_active(ev, h, gd["PANIC_OR_STAGE56"])
        r = compute_variant(d, invret, act, design, cost)
        row = {"name": nm, "events": int(ev.sum()), "active_days": int(act.sum()), **metrics(r), **rolling252(r)}
        for lab, (aa, bb) in PERIODS.items():
            m = (d.date >= pd.Timestamp(aa)) & (d.date <= pd.Timestamp(bb))
            mm = metrics(r.loc[m])
            for k, v in mm.items(): row[f"{lab}_{k}"] = v
            row[f"{lab}_delta_cagr"] = mm["cagr"] - base_period[lab]["cagr"]
            row[f"{lab}_delta_mdd"] = mm["mdd"] - base_period[lab]["mdd"]
        fixed.append(row)
        for block in [20, 63, 120]:
            boot.append({"name": nm, **paired_block_boot(r, d.baseline_ret, block, a.bootstrap_sims, 3800 + block + len(boot))})
        if design in ["QID_CASH15", "QID_CASH30", "QID_FLIP_T", "QID_TARGET30", "T_OFF"]:
            stress.append({"name": nm, **leave_event_stress(d, invret, ev, act, eid, design, cost, d.baseline_ret)})
    pd.DataFrame(fixed).to_csv(out / "fixed_candidates.csv", index=False)
    pd.DataFrame(boot).to_csv(out / "paired_block_bootstrap.csv", index=False)
    pd.DataFrame(stress).to_csv(out / "event_concentration_stress.csv", index=False)

    costrows = []
    ev = cooldown_events(sigs["CORE_TREND_NQSAR"], 10) & ~gd["PANIC_OR_STAGE56"]
    act, _ = build_active(ev, 2, gd["PANIC_OR_STAGE56"])
    for design in ["T_OFF", "QID_FLIP_T", "QID_CASH15", "QID_CASH30", "QID_TARGET30", "PSQ_CASH30", "SQQQ_CASH10", "SQQQ_CASH15"]:
        for cost in [5, 10, 20, 40]:
            r = compute_variant(d, invret, act, design, cost)
            mm = metrics(r)
            costrows.append({"design": design, "cost_bp": cost, **mm, "delta_cagr": mm["cagr"] - bm["cagr"], "delta_mdd": mm["mdd"] - bm["mdd"]})
    pd.DataFrame(costrows).to_csv(out / "cost_stress.csv", index=False)

    ly = []
    for nm, sname, cd, h, design, cost in fixed_specs:
        ev = cooldown_events(sigs[sname], cd) & ~gd["PANIC_OR_STAGE56"]
        act, _ = build_active(ev, h, gd["PANIC_OR_STAGE56"])
        r = compute_variant(d, invret, act, design, cost)
        for yr in sorted(d.date.dt.year.unique()):
            m = d.date.dt.year.ne(yr)
            mv = metrics(r.loc[m]); mb = metrics(d.baseline_ret.loc[m])
            ly.append({"name": nm, "left_out_year": int(yr), "delta_cagr": mv["cagr"] - mb["cagr"], "delta_mdd": mv["mdd"] - mb["mdd"], "delta_calmar": mv["calmar"] - mb["calmar"]})
    pd.DataFrame(ly).to_csv(out / "leave_one_year_out.csv", index=False)

    wf = []
    candidate_designs = ["QID_CASH15", "QID_CASH30", "QID_FLIP_T", "PSQ_CASH30", "SQQQ_CASH10", "SQQQ_CASH15", "T_OFF"]
    folds = [
        ("WF1", "2016-01-04", "2019-12-31", "2020-01-01", "2021-12-31"),
        ("WF2", "2016-01-04", "2021-12-31", "2022-01-03", "2023-12-29"),
        ("WF3", "2016-01-04", "2023-12-29", "2024-01-02", "2026-03-20"),
    ]
    ev = cooldown_events(sigs["CORE_TREND_NQSAR"], 10) & ~gd["PANIC_OR_STAGE56"]
    for fold, ta, tb, va, vb in folds:
        candidates = []
        for design in candidate_designs:
            for hold in [1, 2, 3, 4, 5]:
                act, _ = build_active(ev, hold, gd["PANIC_OR_STAGE56"])
                r = compute_variant(d, invret, act, design, 5)
                mt = (d.date >= ta) & (d.date <= tb); mv = (d.date >= va) & (d.date <= vb)
                pm = metrics(r.loc[mt]); pb = metrics(d.baseline_ret.loc[mt])
                candidates.append((pm["cagr"] - pb["cagr"], pm["mdd"] - pb["mdd"], pm["calmar"] - pb["calmar"], design, hold, r, mv))
        eligible = [x for x in candidates if x[1] >= -.01]
        pick = max(eligible if eligible else candidates, key=lambda x: (x[0], x[2]))
        dc, dm, dcal, design, hold, r, mv = pick
        vv = metrics(r.loc[mv]); vb0 = metrics(d.baseline_ret.loc[mv])
        wf.append({
            "fold": fold, "train": f"{ta}:{tb}", "validation": f"{va}:{vb}", "selected_design": design, "selected_hold": hold,
            "train_delta_cagr": dc, "train_delta_mdd": dm, "train_delta_calmar": dcal,
            "validation_delta_cagr": vv["cagr"] - vb0["cagr"], "validation_delta_mdd": vv["mdd"] - vb0["mdd"], "validation_delta_calmar": vv["calmar"] - vb0["calmar"],
        })
    pd.DataFrame(wf).to_csv(out / "walk_forward.csv", index=False)

    diag = []
    ev = cooldown_events(sigs["CORE_TREND_NQSAR"], 10) & ~gd["PANIC_OR_STAGE56"]
    for i in np.flatnonzero(ev.to_numpy(bool)):
        j = i + 1
        if j >= len(d): continue
        diag.append({
            "signal_date": d.date.iloc[i], "next_date": d.date.iloc[j], "base_t_next": float(d.base_t.iloc[j]), "base_gross_next": float(d.base_gross.iloc[j]),
            "breadth50": float(d.breadth50.iloc[i]), "rsi14": float(d.qqq_rsi14.iloc[i]),
            "real10_shock": float(d.real10_chg5_z252.iloc[i]) if pd.notna(d.real10_chg5_z252.iloc[i]) else None,
        })
    pd.DataFrame(diag).to_csv(out / "core_signal_diagnostics.csv", index=False)

    robust = res[res.robust_pass].sort_values(["FULL_delta_calmar", "FULL_delta_cagr"], ascending=False)
    summary = {
        "status": "RESEARCH_ONLY_NO_PRODUCTION_CHANGE",
        "baseline": {"definition": "Audited Gross100 RESET_TFLOOR_065 + Stage56 M30_TOUCH30_F80_D10/CURRENT30 hierarchy", **bm, **rolling252(d.baseline_ret)},
        "baseline_reproduction": "PASS",
        "signals_tested": list(sigs.keys()), "grid_rows": int(len(res)), "robust_pass_rows": int(len(robust)),
        "best_robust": robust.head(20).to_dict("records"), "fixed_candidates": fixed, "walk_forward": wf,
        "mechanics": {
            "signal": "close-known, next-open position", "inverse_return": "actual adjusted open-to-next-open",
            "gross_cap": "<=100%; ordinary/reset allocations never displaced by inverse sleeve",
            "baseline_timing": "same Gross100 target lag2 convention",
            "panic": "skip if frozen panic or actual Stage56 overlay active; dynamic exit next open",
            "costs": "baseline 5bp; overlay stress 5/10/20/40bp",
            "validation": "train/holdout, four subperiods, leave-year/event, paired block bootstrap, walk-forward",
        },
    }
    (out / "summary_v4.json").write_text(json.dumps(safe(summary), ensure_ascii=False, indent=2), encoding="utf-8")
    print("===V4 SUMMARY===")
    print(json.dumps(safe({"baseline": summary["baseline"], "grid_rows": len(res), "robust_pass_rows": len(robust), "top_fixed": fixed, "walk_forward": wf}), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
