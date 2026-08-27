from __future__ import annotations

from pathlib import Path
import json
import numpy as np
import pandas as pd
import yfinance as yf

# Reuse Stage51 only through data construction and audited signal definitions.
src = Path("research/tqqq_stage51_4h_rsi30_entry_backtest.py").read_text()
prefix = src.split("# ---------- portfolio scan ----------")[0]
exec(compile(prefix, "stage51-data-prefix", "exec"), globals())

print("\n=== STAGE56 MANDATE / FX / PORTFOLIO AUDIT ===", flush=True)
TAX56 = 0.20315
SEED56 = 560827

# First 4H RSI up-turn while still at/below 30. This was not tested in Stage51.
rr = b4.rsi14.to_numpy(float)
rise = np.zeros(len(rr), bool)
rise[2:] = (rr[2:] <= 30) & (rr[2:] > rr[1:-1]) & (rr[1:-1] <= rr[:-2])
b4["rise30"] = rise
rise_day = b4.groupby("date").rise30.max().astype(bool)
SIG["rise30"] = rise_day.reindex(pd.DatetimeIndex(D).normalize()).fillna(False).to_numpy(bool)


def mandate_overlay(B, vx, sig, floor, exit_kind, cur=None, boundaries=None, trace=False):
    """30%-mandate hierarchy plus a temporary crash RSI sleeve; next-open execution."""
    if cur is None: cur = current_trace(B)
    t = cur["target"].copy()
    seed = seed_arr(B, vx)
    bset = set([] if boundaries is None else boundaries)
    age = 10**9; active = False; entry = -1; consumed = -1; entries = 0
    act = np.zeros(len(t), bool)
    rawbear = (~B["a200"]) & (~B["a252"])
    for i in range(len(t)):
        if i in bset: age = 10**9; active = False; entry = -1; consumed = -1
        age = 0 if seed[i] else age + 1
        recent = age <= SPEC["lookback"]
        last = np.flatnonzero(seed[:i+1]); sid = int(last[-1]) if len(last) else -1
        allow = B["mc"][i] >= 20  # Stage51 ANY gate; STRUCT did not improve results.
        if (not active) and recent and sig[i] and allow and sid > consumed:
            active = True; entry = i; consumed = sid; entries += 1
        if active:
            if seed[i]: consumed = max(consumed, i)
            held = i - entry
            if exit_kind == "D5": done = held >= 5
            elif exit_kind == "D10": done = held >= 10
            elif exit_kind == "EMA10": done = held >= 2 and B["gte10"][i]
            elif exit_kind == "EMA21": done = held >= 2 and (not B["lte21"][i])
            else: raise ValueError(exit_kind)
            bad = B["mc"][i] < 20 or (rawbear[i] and held >= 10) or done or held >= 20
            if bad: active = False; entry = -1
            else: t[i] = max(t[i], floor); act[i] = True
    z = np.clip(t, 0, 1)
    return {"target": z, "active": act, "entries": entries} if trace else z


cur0 = current_trace(B0)
targets = {"CURRENT30": cur0["target"].copy(), "FINAL80_100": target_aggr(B0, cur0)}
specs = {}
for method in ("touch30", "rise30"):
    for floor in (.50, .65, .80, 1.00):
        for exit_kind in ("D5", "D10", "EMA10", "EMA21"):
            nm = f"M30_{method.upper()}_F{int(floor*100)}_{exit_kind}"
            specs[nm] = {"method": method, "floor": floor, "exit": exit_kind}
            targets[nm] = mandate_overlay(B0, VX, SIG[method], floor, exit_kind, cur0)


def eval_one(ret, t, dates, cost=COST):
    m, sr, eff = from_target({**B0, "ret": np.asarray(ret)}, t, cost)
    pre = account_end(ret, t, cost, 0.0, dates)
    tax = account_end(ret, t, cost, TAX56, dates)
    return {"pre_cagr": pre["cagr"], "pre_mdd": pre["mdd"], "pre_end": pre["end"],
            "tax_cagr": tax["cagr"], "tax_end": tax["end"], "taxes_paid": tax["taxes_paid"],
            "avg_exp": m["avg_exp"], "turnover": m["turnover"]}


hist = []
for nm, t in targets.items(): hist.append({"candidate": nm, **specs.get(nm, {}), **eval_one(B0["ret"], t, D)})
HIST = pd.DataFrame(hist)
HIST.to_csv("tqqq_stage56_mandate_scan.csv", index=False)

# Fixed subperiods and cost sensitivity, with no candidate selection on these windows.
periods = [("2011-2018", 2011, 2018), ("2019-2022", 2019, 2022), ("2023-2026", 2023, 2026)]
yy = pd.to_datetime(D).dt.year.to_numpy(); subs = []; costs = []
for nm, t in targets.items():
    for label, a, b in periods:
        ix = np.flatnonzero((yy >= a) & (yy <= b)); dd = D.iloc[ix].reset_index(drop=True)
        Bx = {k: B0[k][ix] for k in KEYS}
        pre = account_end(Bx["ret"], t[ix], COST, 0, dd); tax = account_end(Bx["ret"], t[ix], COST, TAX56, dd)
        subs.append({"candidate": nm, "period": label, "pre_cagr": pre["cagr"], "pre_mdd": pre["mdd"], "tax_cagr": tax["cagr"]})
    for bps in (5, 10, 20): costs.append({"candidate": nm, "cost_bps": bps, **eval_one(B0["ret"], t, D, bps/10000)})
pd.DataFrame(subs).to_csv("tqqq_stage56_subperiods.csv", index=False)
pd.DataFrame(costs).to_csv("tqqq_stage56_costs.csv", index=False)

# USDJPY open-to-open exposure: cash remains JPY; only the invested TQQQ sleeve carries FX.
fx = bt.dl_one("JPY=X", "2010-01-01")
fxr = fx.Open.astype(float).pct_change().reindex(pd.DatetimeIndex(D)).ffill().fillna(0).to_numpy(float)
ret_jpy = (1 + B0["ret"]) * (1 + fxr) - 1
fxrows = []
for nm, t in targets.items():
    usd = eval_one(B0["ret"], t, D); jpy = eval_one(ret_jpy, t, D)
    fxrows.append({"candidate": nm, "usd_tax_cagr": usd["tax_cagr"], "usd_pre_mdd": usd["pre_mdd"],
                   "jpy_tax_cagr": jpy["tax_cagr"], "jpy_pre_mdd": jpy["pre_mdd"],
                   "fx_cagr_delta": jpy["tax_cagr"] - usd["tax_cagr"], "fx_mdd_delta": jpy["pre_mdd"] - usd["pre_mdd"]})
pd.DataFrame(fxrows).to_csv("tqqq_stage56_fx_tax.csv", index=False)

# Dividend withholding sensitivity. Adjusted TQQQ prices already include gross distributions.
raw = yf.download("TQQQ", start="2010-01-01", progress=False, auto_adjust=False, actions=True, threads=False)
raw = bt._plain(raw)
div = raw["Dividends"].reindex(pd.DatetimeIndex(D)).fillna(0) if "Dividends" in raw else pd.Series(0.0, index=pd.DatetimeIndex(D))
unadj = raw["Close"].shift(1).reindex(pd.DatetimeIndex(D)).ffill()
dy = (div / unadj).fillna(0).to_numpy(float)
divrows = []
for nm, t in targets.items():
    for rate in (0.0, TAX56, 0.282835):
        # Approximation: distribution tax drag applies to prior-close signaled invested weight.
        drag = np.r_[0.0, t[:-1]] * dy * rate
        z = eval_one((1 + B0["ret"]) * (1 - drag) - 1, t, D)
        divrows.append({"candidate": nm, "distribution_tax_rate": rate, "tax_cagr": z["tax_cagr"], "pre_mdd": z["pre_mdd"]})
pd.DataFrame(divrows).to_csv("tqqq_stage56_dividend_tax.csv", index=False)

# Matched block bootstrap only for the decision set, not the full design grid.
decision = ["CURRENT30", "FINAL80_100", "M30_TOUCH30_F80_D10", "M30_TOUCH30_F100_D10",
            "M30_RISE30_F80_D10", "M30_RISE30_F100_D10"]
N = len(B0["ret"]); H56 = 2520; block = 120; nsim = 500
rng = np.random.default_rng(SEED56); nb = int(np.ceil(H56 / block)); offs = np.arange(block)
starts = rng.integers(0, N-block+1, size=(nsim, nb)); paths = (starts[:,:,None] + offs).reshape(nsim, -1)[:,:H56]
bounds = list(range(block, H56, block)); mc = []
for z, ix in enumerate(paths):
    B = {k: B0[k][ix].copy() for k in KEYS}; vx = VX[ix]; cur = current_trace(B)
    tg = {"CURRENT30": cur["target"], "FINAL80_100": target_aggr(B, cur)}
    for nm in decision[2:]:
        sp = specs[nm]; tg[nm] = mandate_overlay(B, vx, SIG[sp["method"]][ix], sp["floor"], sp["exit"], cur, bounds)
    for nm, t in tg.items():
        pre = account_end(B["ret"], t, COST, 0, None); tax = account_end(B["ret"], t, COST, TAX56, None)
        mc.append({"sim": z, "candidate": nm, "tax_end": tax["end"], "tax_cagr": tax["cagr"], "pre_mdd": pre["mdd"]})
    if (z+1) % 50 == 0: print("[mc56]", z+1, "/", nsim, flush=True)
MC = pd.DataFrame(mc); MC.to_csv("tqqq_stage56_mc.csv", index=False)
sm = []
for nm, g in MC.groupby("candidate"):
    sm.append({"candidate": nm, "tax_end_median": float(g.tax_end.median()), "tax_end_p05": float(g.tax_end.quantile(.05)),
               "tax_cagr_median": float(g.tax_cagr.median()), "tax_cagr_p05": float(g.tax_cagr.quantile(.05)),
               "mdd_median": float(g.pre_mdd.median()), "mdd_p05": float(g.pre_mdd.quantile(.05))})
pd.DataFrame(sm).to_csv("tqqq_stage56_mc_summary.csv", index=False)

# Daily components for the subsequent stock/TQQQ overlap audit.
daily = pd.DataFrame({"date": pd.to_datetime(D), "tqqq_ret_usd": B0["ret"], "tqqq_ret_jpy": ret_jpy})
for nm in decision: daily[f"target_{nm}"] = targets[nm]
daily.to_csv("tqqq_stage56_daily.csv.gz", index=False, compression="gzip")

summary = {"status": "STAGE56_MANDATE_FX_TAX_AUDIT", "coverage": {"start": str(pd.Timestamp(D.iloc[0]).date()), "end": str(pd.Timestamp(D.iloc[-1]).date()), "days": len(D)},
 "decision_set": decision,
 "definitions": {"CURRENT30": "existing hierarchy target with 30% normal exposure and its risk locks",
   "FINAL80_100": "previous research baseline that raises normal exposure to 80%, then 100% in healthy bull",
   "RSI": "temporary floor over CURRENT30 after frozen crash seed; signal at 4H close, rebalance next session open",
   "FX": "TQQQ adjusted open-to-open USD total return compounded with JPY-per-USD open-to-open return",
   "tax": "20.315% annual realized gain tax with three-year loss carry; terminal liquidation included"},
 "limitations": ["No pristine untouched OOS remains.", "JPY=X daily open is a tradable-timing approximation, not the broker's exact conversion rate.",
   "Dividend withholding is a sensitivity around adjusted prices; foreign-tax-credit treatment is investor-specific.",
   "MC57 PIT/survivorship and NQSAR proxy caveats from Stage54/55 remain; they are not retested here."]}
Path("tqqq_stage56_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
print(HIST.sort_values(["tax_cagr", "pre_mdd"], ascending=[False, False]).head(20).to_string(index=False), flush=True)
print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
