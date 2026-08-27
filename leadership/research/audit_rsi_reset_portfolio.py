from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

import audit_rsi_reset_robust as base

COST = 5.0 / 10000.0


def safe(x):
    if isinstance(x, dict): return {str(k): safe(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)): return [safe(v) for v in x]
    if isinstance(x, (np.integer,)): return int(x)
    if isinstance(x, (np.floating, float)):
        z = float(x)
        return z if math.isfinite(z) else None
    return x


def metrics(nav: pd.Series) -> dict:
    nav = nav.dropna()
    if len(nav) < 2: return {"n": int(len(nav))}
    years = max((nav.index[-1] - nav.index[0]).days / 365.2425, 1 / 252)
    dd = nav / nav.cummax() - 1.0
    return {"n": int(len(nav)), "end": float(nav.iloc[-1]),
            "cagr": float(nav.iloc[-1] ** (1 / years) - 1), "mdd": float(dd.min())}


def simulate(cal, op, cl, active, ema21, trades, slot, max_pos, hold, mode, stop8):
    cash = 1.0
    lots = []
    navs, expos, conc = [], [], []
    accepted = skipped_cap = skipped_theme = adds = 0
    turnover = 0.0
    by_entry = {d: g for d, g in trades.groupby("entry_date", observed=True)}
    for i, d in enumerate(cal):
        # Known-at-prior-close exits execute at today's open. Fixed holding exits do too.
        keep = []
        for z in lots:
            px = op.at[d, z["symbol"]] if z["symbol"] in op.columns else np.nan
            due = i >= z["exit_i"]
            stopped = stop8 and i > z["entry_i"] + 1 and z.get("stop_next", False)
            if (due or stopped) and pd.notna(px):
                gross = z["shares"] * px
                cash += gross * (1 - COST)
                turnover += gross
            else:
                keep.append(z)
        lots = keep

        # Confirmation tranche: prior close above EMA21 and reconstructed theme active.
        if mode == "tranche" and i > 0:
            for z in lots:
                if z["added"] or i >= z["exit_i"]: continue
                s, th = z["symbol"], z["theme"]
                ok = (s in cl.columns and th in active.columns and
                      pd.notna(cl.iloc[i-1][s]) and pd.notna(ema21.iloc[i-1][s]) and
                      cl.iloc[i-1][s] > ema21.iloc[i-1][s] and bool(active.iloc[i-1][th]))
                px = op.at[d, s] if s in op.columns else np.nan
                mark = cash + sum(q["shares"] * op.at[d, q["symbol"]] for q in lots
                                  if q["symbol"] in op.columns and pd.notna(op.at[d, q["symbol"]]))
                amount = slot * 0.5 * mark
                if ok and pd.notna(px) and px > 0 and cash >= amount * (1 + COST):
                    sh = amount / px
                    cash -= amount * (1 + COST)
                    z["shares"] += sh; z["added"] = True; adds += 1; turnover += amount

        # New entries are frozen prior-audit events; deterministic priority avoids hindsight.
        if d in by_entry:
            day = by_entry[d].sort_values(["rank_priority", "rsi_signal", "symbol"])
            for r in day.itertuples(index=False):
                if len(lots) >= max_pos: skipped_cap += 1; continue
                if sum(q["theme"] == r.theme for q in lots) >= 2: skipped_theme += 1; continue
                px = op.at[d, r.symbol] if r.symbol in op.columns else np.nan
                if pd.isna(px) or px <= 0: continue
                mark = cash + sum(q["shares"] * op.at[d, q["symbol"]] for q in lots
                                  if q["symbol"] in op.columns and pd.notna(op.at[d, q["symbol"]]))
                frac = slot * (0.5 if mode == "tranche" else 1.0)
                amount = frac * mark
                if cash < amount * (1 + COST): skipped_cap += 1; continue
                cash -= amount * (1 + COST); turnover += amount
                lots.append({"symbol": r.symbol, "theme": r.theme, "shares": amount / px,
                             "entry_i": i, "exit_i": min(i + hold, len(cal) - 1),
                             "entry_px": px, "added": mode != "tranche", "stop_next": False})
                accepted += 1

        close_nav = cash
        gross = 0.0
        for z in lots:
            px = cl.at[d, z["symbol"]] if z["symbol"] in cl.columns else np.nan
            if pd.notna(px): gross += z["shares"] * px
            z["stop_next"] = bool(pd.notna(px) and px / z["entry_px"] - 1 <= -0.08)
        close_nav += gross
        navs.append(close_nav); expos.append(gross / close_nav if close_nav > 0 else np.nan); conc.append(len(lots))
    ns = pd.Series(navs, index=cal)
    out = {**metrics(ns), "avg_exposure": float(np.nanmean(expos)), "max_exposure": float(np.nanmax(expos)),
           "max_concurrent": int(max(conc) if conc else 0), "accepted": accepted,
           "skipped_position_cap": skipped_cap, "skipped_theme_cap": skipped_theme,
           "confirmation_adds": adds, "turnover_nav": float(turnover / np.mean(navs))}
    return out, pd.DataFrame({"date": cal, "nav": navs, "exposure": expos, "positions": conc})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--trades", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    root, out = Path(args.root), Path(args.output); out.mkdir(parents=True, exist_ok=True)
    prior = pd.read_csv(args.trades, compression="gzip", parse_dates=["day0_date", "signal_date", "entry_date"])
    t = prior[prior.method.eq("RISE_LE30_W20")].copy()
    t["rank_priority"] = t.rank_type.map({"RS63_TOP3": 0, "RS189_TOP3": 1}).fillna(9)
    t = t.sort_values(["day0_date", "theme", "symbol", "rank_priority"]).drop_duplicates(
        ["day0_date", "theme", "symbol"], keep="first")
    market = base.rebuild_market(root, "2016-01-04", "2026-06-30", 6000, 75, 3)
    cl, op, active = market["close"], market["open"], market["active"]
    ema21 = cl.ewm(span=21, adjust=False).mean()
    cal = cl.index
    t = t[t.entry_date.isin(cal) & t.symbol.isin(cl.columns)].copy()

    rows = []; series = {}
    for period, lo, hi in [("ALL", "2016-01-04", "2026-06-30"), ("DISCOVERY", "2016-01-04", "2021-12-31"), ("CONFIRM", "2022-01-03", "2026-06-30")]:
        ix = cal[(cal >= lo) & (cal <= hi)]
        tt = t[t.entry_date.isin(ix)]
        for slot in (0.015, 0.029, 0.058):
            for max_pos in (3, 6):
                for hold in (10, 20, 40):
                    for mode in ("full", "tranche"):
                        for stop8 in (False, True):
                            # Stop sensitivity is decision-relevant at 20d only.
                            if stop8 and hold != 20: continue
                            nm = f"S{slot:.3f}_P{max_pos}_H{hold}_{mode}" + ("_STOP8" if stop8 else "")
                            m, s = simulate(ix, op, cl, active, ema21, tt, slot, max_pos, hold, mode, stop8)
                            rows.append({"period": period, "scenario": nm, "slot": slot, "max_pos": max_pos,
                                         "hold": hold, "mode": mode, "stop8": stop8, **m})
                            if period == "ALL" and nm in {"S0.029_P6_H20_full", "S0.029_P6_H20_tranche", "S0.029_P6_H20_full_STOP8"}:
                                z = s.rename(columns={c: f"{nm}_{c}" for c in ("nav", "exposure", "positions")})
                                series[nm] = z.set_index("date")
    res = pd.DataFrame(rows)
    res.to_csv(out / "portfolio_scenarios.csv", index=False)
    wide = pd.concat(series.values(), axis=1).reset_index()
    wide.to_csv(out / "selected_daily_series.csv.gz", index=False, compression="gzip")
    # Handoff is descriptive only: it does not manufacture a normal-book return series.
    hand = []
    for r in t.itertuples(index=False):
        p = cal.get_loc(r.entry_date)
        found = None
        for j in range(p, min(p + 21, len(cal))):
            if (r.symbol in cl.columns and r.theme in active.columns and
                pd.notna(cl.iloc[j][r.symbol]) and pd.notna(ema21.iloc[j][r.symbol]) and
                cl.iloc[j][r.symbol] > ema21.iloc[j][r.symbol] and bool(active.iloc[j][r.theme])):
                found = j; break
        hand.append({"entry_date": r.entry_date, "symbol": r.symbol, "theme": r.theme,
                     "handoff": found is not None, "handoff_days": None if found is None else found - p})
    hd = pd.DataFrame(hand); hd.to_csv(out / "handoff_diagnostics.csv", index=False)
    summary = {"status": "RSI_RESET_PORTFOLIO_AUDIT", "input_rows": int(len(t)),
               "definitions": {"entry": "prior audited RISE_LE30_W20 signal, next open",
                 "slot": "fraction of live total NAV per accepted position",
                 "tranche": "half at entry; half next open after prior close above EMA21 and theme active",
                 "caps": "maximum open positions plus at most two positions per theme",
                 "stop8": "prior close at least 8% below original entry; sell next open",
                 "cost": "5 bps per side"},
               "handoff_rate_20d": float(hd.handoff.mean()) if len(hd) else None,
               "handoff_days_median": float(hd.loc[hd.handoff, "handoff_days"].median()) if hd.handoff.any() else None,
               "download": market["diag"],
               "limitations": ["Current-universe/current-taxonomy retrospective bias remains.",
                 "This validates the panic sleeve and handoff incidence, not the normal-book portfolio return.",
                 "Tax and USDJPY are excluded here; TQQQ mandate audit handles portfolio currency/tax sensitivity."]}
    (out / "summary.json").write_text(json.dumps(safe(summary), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(safe(summary), ensure_ascii=False, indent=2), flush=True)
    print(res[res.period.eq("ALL")].sort_values(["mdd", "cagr"], ascending=[False, False]).head(20).to_string(index=False), flush=True)


if __name__ == "__main__": main()
