from __future__ import annotations
import argparse, json
from pathlib import Path
import numpy as np, pandas as pd, yfinance as yf
import audit_inverse_full_v38_v4 as v4

TAX = 0.20315


def red_episode_ids(red: pd.Series) -> pd.Series:
    x = red.fillna(False).to_numpy(bool); out = np.full(len(x), -1, int); eid = -1; on = False
    for i, z in enumerate(x):
        if z and not on: eid += 1
        on = z
        if z: out[i] = eid
    return pd.Series(out, index=red.index)


def one_per_red(cond: pd.Series, red: pd.Series) -> pd.Series:
    ep = red_episode_ids(red); out = np.zeros(len(cond), bool)
    for e in sorted(set(ep[ep >= 0].tolist())):
        ix = np.flatnonzero((ep.to_numpy() == e) & cond.fillna(False).to_numpy(bool))
        if len(ix): out[ix[0]] = True
    return pd.Series(out, index=cond.index)


def corrected_variant(d, invret, active, design, inv_cost_bp=5):
    # Audited baseline TQQQ friction remains 5bp. Only inverse sleeve friction is stressed.
    t, inv = v4.overlay_positions(d, active, design)
    ret = d.o_contrib.to_numpy(float) + d.r_contrib.to_numpy(float) + t * d.tqqq_ret.to_numpy(float)
    tt = np.zeros(len(d)); tt[1:] = np.abs(np.diff(t)); ret -= tt * (5 / 10000)
    for p, w in inv.items():
        rp = pd.to_numeric(invret[p], errors="coerce").fillna(0).to_numpy(float)
        ret += w * rp
        tr = np.zeros(len(d)); tr[1:] = np.abs(np.diff(w)); ret -= tr * (inv_cost_bp / 10000)
    return pd.Series(ret, index=d.index)


def cluster_boot_event(tab: pd.DataFrame, nsim=10000, seed=55):
    if tab.empty: return {}
    groups = [g.delta_vs_baseline.to_numpy(float) for _, g in tab.groupby("red_episode")]
    rng = np.random.default_rng(seed); means = []
    for _ in range(nsim):
        take = rng.integers(0, len(groups), size=len(groups))
        z = np.concatenate([groups[j] for j in take]); means.append(np.mean(z))
    a = np.array(means)
    return {
        "clusters": len(groups), "events": len(tab), "mean": float(tab.delta_vs_baseline.mean()),
        "median": float(tab.delta_vs_baseline.median()), "win": float((tab.delta_vs_baseline > 0).mean()),
        "boot_mean_p05": float(np.quantile(a, .05)), "boot_mean_median": float(np.median(a)),
        "boot_mean_p95": float(np.quantile(a, .95)), "p_mean_positive": float((a > 0).mean()),
    }


def load_all(a):
    feat = pd.read_csv(a.features, compression="gzip", parse_dates=["date"]).sort_values("date")
    ordinary = pd.read_csv(Path(a.gross100) / "gross100_final_reset_components/ordinary_PEAK30_PART25_R3_daily.csv.gz", compression="gzip", parse_dates=["date"])
    reset = pd.read_csv(Path(a.gross100) / "gross100_final_reset_components/rsi_RESET_RISE30_S029_P4_H20_daily.csv.gz", compression="gzip", parse_dates=["date"])
    tq = pd.read_csv(a.tqqq, compression="gzip", parse_dates=["date"])
    ordinary = ordinary.rename(columns={"gross_exposure": "gross_exposure_ord", "return": "return_ord"})
    reset = reset.rename(columns={"gross_exposure": "gross_exposure_rsi", "return": "return_rsi"})
    d = v4.baseline_components(ordinary, reset, tq, feat); d["date"] = v4.norm_idx(d.date)
    idx = v4.norm_idx(d.date); inv = v4.price_returns(idx, str(d.date.min().date()), str(d.date.max().date())); inv.index = d.index
    return d, inv


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", required=True); ap.add_argument("--gross100", required=True); ap.add_argument("--tqqq", required=True); ap.add_argument("--output", required=True)
    a = ap.parse_args(); out = Path(a.output); out.mkdir(parents=True, exist_ok=True)
    d, inv = load_all(a); bm = v4.metrics(d.baseline_ret)
    assert abs(bm["cagr"] - 0.470025795426962) < 5e-6
    red = d.nq_color.astype(str).eq("Red"); below50 = d.qqq_dist_sma50 < 0; slope50 = d.sma50_slope10 < 0; core = red & below50 & slope50
    mc = pd.to_numeric(d.mc_chg5, errors="coerce"); guard = v4.guards(d)["PANIC_OR_STAGE56"]; deep = v4.guards(d)["PANIC_DEEP"]
    rep = red_episode_ids(red); d["red_episode"] = rep
    defs = {"CORE": core}
    for th in [-2, -3, -4, -5]: defs[f"MC{th}"] = core & (mc < th)
    defs["MC-3_ONE_RED"] = one_per_red(core & (mc < -3), red)

    rows = []; led = []; boots = []
    designs = ["QID_CASH15", "QID_CASH30", "PSQ_CASH30", "SQQQ_CASH10", "SQQQ_CASH15"]
    for sname, cond in defs.items():
        for mode in ["COOLDOWN10", "ONE_RED"]:
            ev = one_per_red(cond, red) if mode == "ONE_RED" else v4.cooldown_events(cond, 10)
            ev = ev & ~guard
            for kg, kill in [("PANIC", guard), ("DEEP", deep)]:
                for hold in [2, 3, 4]:
                    act, eid = v4.build_active(ev, hold, kill)
                    for design in designs:
                        r = corrected_variant(d, inv, act, design, 5)
                        row = {"signal": sname, "mode": mode, "kill": kg, "hold": hold, "design": design, "events": int(ev.sum()), **v4.metrics(r)}
                        for lab, (aa, bb) in v4.PERIODS.items():
                            m = (d.date >= aa) & (d.date <= bb); mm = v4.metrics(r.loc[m]); mb = v4.metrics(d.baseline_ret.loc[m])
                            row[f"{lab}_delta_cagr"] = mm["cagr"] - mb["cagr"]; row[f"{lab}_delta_mdd"] = mm["mdd"] - mb["mdd"]
                        rows.append(row)
                        if sname == "MC-3" and mode == "COOLDOWN10" and kg == "PANIC" and design in ["QID_CASH15", "QID_CASH30"] and hold in [2, 3, 4]:
                            t = v4.event_table(d, ev, act, eid, r, d.baseline_ret, sname, design, hold, 10, kg)
                            if len(t):
                                mp = {pd.Timestamp(d.date.iloc[i]): int(rep.iloc[i]) for i in np.flatnonzero(ev.to_numpy(bool))}
                                t["red_episode"] = pd.to_datetime(t.signal_date).map(mp); led.append(t)
                                boots.append({"signal": sname, "design": design, "hold": hold, **cluster_boot_event(t, 10000, 5500 + hold + (30 if design.endswith("30") else 0))})
    res = pd.DataFrame(rows); res.to_csv(out / "focused_grid.csv", index=False)
    if led: pd.concat(led, ignore_index=True).to_csv(out / "focused_event_ledger.csv", index=False)
    pd.DataFrame(boots).to_csv(out / "event_cluster_bootstrap.csv", index=False)

    costs = []; ev = v4.cooldown_events(defs["MC-3"], 10) & ~guard
    for hold in [2, 3, 4]:
        act, _ = v4.build_active(ev, hold, guard)
        for design in ["QID_CASH15", "QID_CASH30", "PSQ_CASH30", "SQQQ_CASH10", "SQQQ_CASH15"]:
            for c in [5, 10, 20, 40, 80]:
                r = corrected_variant(d, inv, act, design, c); mm = v4.metrics(r)
                costs.append({"hold": hold, "design": design, "inverse_cost_bp": c, **mm, "delta_cagr": mm["cagr"] - bm["cagr"], "delta_mdd": mm["mdd"] - bm["mdd"]})
    pd.DataFrame(costs).to_csv(out / "corrected_cost_stress.csv", index=False)

    ev = v4.cooldown_events(defs["MC-3"], 10) & ~guard; act, eid = v4.build_active(ev, 3, guard)
    full = corrected_variant(d, inv, act, "QID_CASH30", 5)
    exclusions = {"NONE": [], "NO_2020": [2020], "NO_2022": [2022], "NO_2020_2022": [2020, 2022], "NO_2018_2020_2022": [2018, 2020, 2022], "NO_2024_2026": [2024, 2026]}
    exrows = []
    for name, yrs in exclusions.items():
        a2 = act.copy()
        for j, i in enumerate(np.flatnonzero(ev.to_numpy(bool))):
            if int(d.date.iloc[i].year) in yrs: a2.loc[eid.eq(j)] = False
        r = corrected_variant(d, inv, a2, "QID_CASH30", 5); mm = v4.metrics(r)
        exrows.append({"exclusion": name, "removed_years": ",".join(map(str, yrs)), "events_remaining": int(sum(int(d.date.iloc[i].year) not in yrs for i in np.flatnonzero(ev.to_numpy(bool)))), **mm, "delta_cagr": mm["cagr"] - bm["cagr"], "delta_mdd": mm["mdd"] - bm["mdd"]})
    pd.DataFrame(exrows).to_csv(out / "crisis_exclusion.csv", index=False)

    tab = v4.event_table(d, ev, act, eid, full, d.baseline_ret, "MC-3", "QID_CASH30", 3, 10, "PANIC")
    mp = {pd.Timestamp(d.date.iloc[i]): int(rep.iloc[i]) for i in np.flatnonzero(ev.to_numpy(bool))}; tab["red_episode"] = pd.to_datetime(tab.signal_date).map(mp)
    order = tab.sort_values("delta_vs_baseline", ascending=False); conc = []
    for k in [0, 1, 2, 3, 5]:
        a2 = act.copy()
        for j in order.head(k).event_id.astype(int): a2.loc[eid.eq(j)] = False
        r = corrected_variant(d, inv, a2, "QID_CASH30", 5); mm = v4.metrics(r)
        conc.append({"top_positive_events_removed": k, **mm, "delta_cagr": mm["cagr"] - bm["cagr"], "delta_mdd": mm["mdd"] - bm["mdd"]})
    for k in [1, 2, 3]:
        a2 = act.copy()
        for j in tab.sort_values("delta_vs_baseline").head(k).event_id.astype(int): a2.loc[eid.eq(j)] = False
        r = corrected_variant(d, inv, a2, "QID_CASH30", 5); mm = v4.metrics(r)
        conc.append({"top_positive_events_removed": -k, **mm, "delta_cagr": mm["cagr"] - bm["cagr"], "delta_mdd": mm["mdd"] - bm["mdd"]})
    pd.DataFrame(conc).to_csv(out / "event_concentration.csv", index=False)

    pb = []
    for hold in [2, 3, 4]:
        act, _ = v4.build_active(ev, hold, guard); r = corrected_variant(d, inv, act, "QID_CASH30", 5)
        for block in [20, 63, 120, 252]: pb.append({"hold": hold, **v4.paired_block_boot(r, d.baseline_ret, block, 5000, 6500 + hold + block)})
    pd.DataFrame(pb).to_csv(out / "calendar_block_bootstrap.csv", index=False)

    fx = yf.download("JPY=X", start="2015-12-01", end="2026-04-01", auto_adjust=True, actions=False, progress=False, threads=False)
    if isinstance(fx.columns, pd.MultiIndex): fx.columns = fx.columns.get_level_values(0)
    fxo = pd.to_numeric(fx["Open"], errors="coerce"); fxo.index = v4.norm_idx(fxo.index); fxo = fxo.reindex(v4.norm_idx(d.date)).ffill()
    fxr = fxo.shift(-1) / fxo - 1; fxr.index = d.index
    q_usd = inv["QID"]; q_jpy = (1 + q_usd) * (1 + fxr) - 1; fxrows = []
    for hold in [2, 3, 4]:
        act, eid = v4.build_active(ev, hold, guard)
        for label, qret in [("USD", q_usd), ("JPY", q_jpy)]:
            vals = []
            for j, i in enumerate(np.flatnonzero(ev.to_numpy(bool))):
                mask = eid.eq(j).to_numpy()
                if mask.any(): vals.append(float(np.prod(1 + qret.to_numpy()[mask]) - 1))
            vals = np.array(vals, float); aft = np.where(vals > 0, vals * (1 - TAX), vals)
            fxrows.append({"hold": hold, "currency": label, "n": len(vals), "mean": float(np.nanmean(vals)), "median": float(np.nanmedian(vals)), "win": float(np.nanmean(vals > 0)), "aftertax_conservative_mean": float(np.nanmean(aft)), "worst": float(np.nanmin(vals)), "best": float(np.nanmax(vals))})
    pd.DataFrame(fxrows).to_csv(out / "fx_tax_event_sensitivity.csv", index=False)

    eps = []
    for e, g in d[d.red_episode >= 0].groupby("red_episode"):
        idxs = g.index; hits = ev.loc[idxs]
        eps.append({"red_episode": int(e), "start": g.date.min(), "end": g.date.max(), "sessions": len(g), "mc3_events": int(hits.sum())})
    pd.DataFrame(eps).to_csv(out / "red_episode_clusters.csv", index=False)

    fixed = res[(res.signal == "MC-3") & (res.mode == "COOLDOWN10") & (res.kill == "PANIC") & (res.design == "QID_CASH30")].sort_values("hold")
    summary = {
        "status": "RESEARCH_ONLY_NO_PRODUCTION_CHANGE", "baseline": bm,
        "fixed_mc3_qid30": fixed.to_dict("records"), "event_cluster_bootstrap": boots,
        "core_rule": "NQSAR Red AND QQQ below SMA50 AND SMA50 slope<0 AND MC57 5d change<-3; eventized; 10d cooldown; skip/kill panic; QID from spare gross only; gross<=100",
        "notes": ["V5 is confirmatory robustness after V4 discovery; no production change.", "Cost stress changes inverse sleeve friction only; audited baseline TQQQ friction remains 5bp.", "JPY event sensitivity is incremental QID sleeve only, not a full portfolio JPY conversion."],
    }
    (out / "summary_v5.json").write_text(json.dumps(v4.safe(summary), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(v4.safe(summary), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
