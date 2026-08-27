from __future__ import annotations
from pathlib import Path
import json
import numpy as np
import pandas as pd
import yfinance as yf

# Reuse Stage51's exact data/portfolio/tax machinery up to the event-study body.
src = Path("research/tqqq_stage51_4h_rsi30_entry_backtest.py").read_text()
prefix = src.split("# ---------- event study:")[0]
exec(compile(prefix, "stage51-prefix", "exec"), globals())

print("\n=== STAGE53 FINAL INPUT / RSI SOURCE AUDIT ===", flush=True)
NSIM = 1000
H = 2520
BLOCK = 120
SEED53 = 530827

# ---------------------------------------------------------------------------
# Fast Stage52-equivalent state machines, semantically identical to Stage51.
def fast_daily(B, vx, cur=None, boundaries=None, trace=False):
    if cur is None:
        cur = current_trace(B)
    t = target_aggr(B, cur)
    seed = seed_arr(B, vx)
    rec = consec_true(B["gte10"], 2) & (B["nq"] != 0) & (B["mc"] >= 35)
    bset = set([] if boundaries is None else boundaries)
    active = False
    entry = -1
    consumed = -1
    age = 10**9
    last_seed = -1
    act = np.zeros(len(t), bool)
    entries = 0
    for i in range(len(t)):
        if i in bset:
            active = False
            entry = -1
            consumed = -1
            age = 10**9
            last_seed = -1
        if seed[i]:
            age = 0
            last_seed = i
        else:
            age += 1
        recent = age <= SPEC["lookback"]
        if (not active) and recent and rec[i] and (not cur["risklock"][i]) and last_seed > consumed:
            active = True
            entry = i
            consumed = last_seed
            entries += 1
        if active:
            if seed[i]:
                consumed = max(consumed, i)
            bad = (cur["risklock"][i] or (B["nq"][i] == 0) or
                   ((not B["a200"][i]) and (not B["a252"][i])) or
                   (i - entry) >= SPEC["maxd"])
            if bad:
                active = False
                entry = -1
            else:
                t[i] = max(t[i], 1.0)
                act[i] = True
    out = {"target": np.clip(t, 0, 1), "active": act, "seed": seed, "entries": entries}
    return out if trace else out["target"]


def fast_overlay_from_dr(B, sig, sp, cur, dr, boundaries=None):
    t = dr["target"].copy()
    seed = dr["seed"]
    bset = set([] if boundaries is None else boundaries)
    active = False
    entry = -1
    consumed = -1
    age = 10**9
    last_seed = -1
    rawbear = (~B["a200"]) & (~B["a252"])
    for i in range(len(t)):
        if i in bset:
            active = False
            entry = -1
            consumed = -1
            age = 10**9
            last_seed = -1
        if seed[i]:
            age = 0
            last_seed = i
        else:
            age += 1
        recent = age <= SPEC["lookback"]
        allow = ((B["mc"][i] >= 25 and (not rawbear[i])) if sp["gate"] == "STRUCT"
                 else (B["mc"][i] >= 20))
        if (not active) and recent and sig[i] and allow and last_seed > consumed:
            active = True
            entry = i
            consumed = last_seed
        if active:
            if seed[i]:
                consumed = max(consumed, i)
            if dr["active"][i]:
                active = False
                entry = -1
            else:
                bad = ((B["mc"][i] < 20) or
                       (sp["gate"] == "STRUCT" and rawbear[i]) or
                       ((i - entry) >= sp["maxd"]))
                if bad:
                    active = False
                    entry = -1
                else:
                    t[i] = max(t[i], sp["floor"])
    return np.clip(t, 0, 1)


cur0 = current_trace(B0)
DR0 = fast_daily(B0, VX, cur0, None, True)
_ref = rsi_overlay(B0, VX, SIG["touch30"], {"method": "touch30", "gate": "ANY", "floor": 1.0, "maxd": 10}, cur0, None, False)
_fast = fast_overlay_from_dr(B0, SIG["touch30"], {"gate": "ANY", "floor": 1.0, "maxd": 10}, cur0, DR0, None)
if not np.allclose(_ref, _fast, atol=1e-12):
    raise RuntimeError("Stage53 fast engine does not reproduce Stage51 RSI30_ANY")
print("[semantic-check] Stage53 fast engine matches Stage51 RSI30_ANY exactly", flush=True)

# ---------------------------------------------------------------------------
# QQQ 5m -> TQQQ 5m proxy.
# Every session resets to the ACTUAL split-adjusted TQQQ open. Within the session,
# each QQQ 5m return is levered 3x. This is explicitly a proxy, never labeled as
# actual historical TQQQ intraday data.
def _norm_et_frame(x):
    x = bt._plain(x)
    idx = pd.DatetimeIndex(x.index)
    if idx.tz is not None:
        idx = idx.tz_convert("America/New_York").tz_localize(None)
    x.index = idx
    return x.sort_index()


def make_tqqq_proxy5(q5, topen):
    q = q5.copy().sort_values("ds")
    q["date"] = pd.to_datetime(q["ds"]).dt.normalize()
    rows = []
    ts = topen.copy()
    ts.index = pd.DatetimeIndex(ts.index).tz_localize(None).normalize()
    for d, g in q.groupby("date", sort=True):
        o = ts.get(pd.Timestamp(d), np.nan)
        if not np.isfinite(o):
            continue
        g = g.sort_values("ds").copy()
        cc = g["Close"].to_numpy(float)
        oo = g["Open"].to_numpy(float)
        if len(g) == 0:
            continue
        prev = np.r_[oo[0], cc[:-1]]
        rr = np.divide(cc, prev, out=np.ones_like(cc), where=np.isfinite(prev) & (prev != 0)) - 1.0
        gross = np.maximum(1e-8, 1.0 + 3.0 * rr)
        px = float(o) * np.cumprod(gross)
        z = pd.DataFrame({"ds": g["ds"].to_numpy(), "date": pd.Timestamp(d), "Close": px})
        rows.append(z)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=["ds", "date", "Close"])


def bars4_from_close5(x):
    z = x.copy()
    mins = pd.to_datetime(z["ds"]).dt.hour * 60 + pd.to_datetime(z["ds"]).dt.minute
    z = z[(mins >= 570) & (mins < 960)].copy()
    mins = pd.to_datetime(z["ds"]).dt.hour * 60 + pd.to_datetime(z["ds"]).dt.minute
    z["date"] = pd.to_datetime(z["ds"]).dt.normalize()
    z["slot"] = np.where(mins < 810, 0, 1)
    b = z.groupby(["date", "slot"], sort=True).agg(Close=("Close", "last"), n=("Close", "size")).reset_index()
    b = b[b["n"] >= 6].copy().sort_values(["date", "slot"]).reset_index(drop=True)
    b["rsi14"] = wilder_rsi(b["Close"].to_numpy(float), 14)
    return b


topen_hist = tq.Open.astype(float).copy()
topen_hist.index = pd.DatetimeIndex(topen_hist.index).tz_localize(None).normalize()
proxy5 = make_tqqq_proxy5(x5[["ds", "Open", "Close"]].copy(), topen_hist)
tb4 = bars4_from_close5(proxy5)

def touch_signal(r, level):
    r = np.asarray(r, float)
    return (r <= level) & np.r_[False, r[:-1] > level]


TQ_THRESH = (20, 25, 30, 35, 40)
for th in TQ_THRESH:
    tb4[f"touch{th}"] = touch_signal(tb4["rsi14"].to_numpy(float), th)

tdsig = tb4.groupby("date")[[f"touch{x}" for x in TQ_THRESH]].max().astype(bool)
TSIG = {
    th: tdsig[f"touch{th}"].reindex(pd.DatetimeIndex(D).normalize()).fillna(False).to_numpy(bool)
    for th in TQ_THRESH
}

# QQQ-vs-proxy signal similarity.
sigcmp = []
qqq30 = SIG["touch30"]
for th in TQ_THRESH:
    s = TSIG[th]
    inter = int(np.sum(qqq30 & s))
    union = int(np.sum(qqq30 | s))
    sigcmp.append({
        "source": f"TQQQ_PROXY_RSI{th}",
        "qqq30_events": int(np.sum(qqq30)),
        "events": int(np.sum(s)),
        "same_day_intersection": inter,
        "same_day_union": union,
        "jaccard": float(inter / union) if union else np.nan,
        "daily_agreement": float(np.mean(qqq30 == s)),
    })
SIGCMP = pd.DataFrame(sigcmp)
SIGCMP.to_csv("tqqq_stage53_signal_similarity.csv", index=False)

# ---------------------------------------------------------------------------
# Recent actual TQQQ 5m validation of the proxy construction.
recent_quality = {
    "available": False,
    "reason": "",
    "bars": 0,
    "rsi_corr": None,
    "median_abs_rsi_diff": None,
    "p95_abs_rsi_diff": None,
    "touch30_agreement": None,
}
try:
    q5r = yf.download("QQQ", period="60d", interval="5m", auto_adjust=True, actions=False,
                      progress=False, threads=False, prepost=False)
    t5r = yf.download("TQQQ", period="60d", interval="5m", auto_adjust=True, actions=False,
                      progress=False, threads=False, prepost=False)
    q5r = _norm_et_frame(q5r)
    t5r = _norm_et_frame(t5r)
    if len(q5r) and len(t5r):
        q5r = q5r.reset_index().rename(columns={q5r.index.name or "index": "ds"})
        if "ds" not in q5r.columns:
            q5r = q5r.rename(columns={q5r.columns[0]: "ds"})
        t5r = t5r.reset_index().rename(columns={t5r.index.name or "index": "ds"})
        if "ds" not in t5r.columns:
            t5r = t5r.rename(columns={t5r.columns[0]: "ds"})
        qmins = pd.to_datetime(q5r.ds).dt.hour * 60 + pd.to_datetime(q5r.ds).dt.minute
        tmins = pd.to_datetime(t5r.ds).dt.hour * 60 + pd.to_datetime(t5r.ds).dt.minute
        q5r = q5r[(qmins >= 570) & (qmins < 960)].copy()
        t5r = t5r[(tmins >= 570) & (tmins < 960)].copy()
        t5r["date"] = pd.to_datetime(t5r.ds).dt.normalize()
        ropen = t5r.groupby("date").Open.first().astype(float)
        pr = make_tqqq_proxy5(q5r[["ds", "Open", "Close"]].copy(), ropen)
        p4 = bars4_from_close5(pr)
        actual = t5r[["ds", "Close"]].copy()
        a4 = bars4_from_close5(actual)
        m = p4.merge(a4, on=["date", "slot"], suffixes=("_proxy", "_actual"))
        if len(m) >= 30:
            rp = m["rsi14_proxy"].to_numpy(float)
            ra = m["rsi14_actual"].to_numpy(float)
            ok = np.isfinite(rp) & np.isfinite(ra)
            dlt = np.abs(rp[ok] - ra[ok])
            tp = touch_signal(rp, 30)
            ta = touch_signal(ra, 30)
            recent_quality = {
                "available": True,
                "reason": "",
                "start": str(pd.Timestamp(m.date.min()).date()),
                "end": str(pd.Timestamp(m.date.max()).date()),
                "bars": int(len(m)),
                "rsi_corr": float(np.corrcoef(rp[ok], ra[ok])[0, 1]) if np.sum(ok) > 5 else None,
                "median_abs_rsi_diff": float(np.median(dlt)) if len(dlt) else None,
                "p95_abs_rsi_diff": float(np.quantile(dlt, .95)) if len(dlt) else None,
                "touch30_agreement": float(np.mean(tp == ta)),
                "proxy_touch30": int(np.sum(tp)),
                "actual_touch30": int(np.sum(ta)),
            }
        else:
            recent_quality["reason"] = f"too few aligned bars: {len(m)}"
    else:
        recent_quality["reason"] = "Yahoo returned empty recent intraday data"
except Exception as exc:
    recent_quality["reason"] = f"{type(exc).__name__}: {exc}"
Path("tqqq_stage53_recent_proxy_quality.json").write_text(
    json.dumps(recent_quality, ensure_ascii=False, indent=2, default=str)
)
print("[recent proxy quality]", recent_quality, flush=True)

# ---------------------------------------------------------------------------
# Historical portfolio comparison: Stage51 QQQ RSI30 versus TQQQ-proxy RSI levels.
def eval_target(name, t):
    m, _, _ = from_target(B0, t, COST)
    pre = account_end(B0["ret"], t, COST, 0.0, D)
    aft = account_end(B0["ret"], t, COST, TAX, D)
    return {
        "candidate": name,
        "pre_cagr": pre["cagr"],
        "pre_mdd": pre["mdd"],
        "tax_cagr": aft["cagr"],
        "tax_end": aft["end"],
        "avg_exp": m["avg_exp"],
        "turnover": m["turnover"],
    }

sp = {"gate": "ANY", "floor": 1.0, "maxd": 10}
targets = {
    "AGGR": target_aggr(B0, cur0),
    "DAILY_R10": DR0["target"],
    "QQQ_RSI30": _fast,
}
signal_map = {"QQQ_RSI30": qqq30}
for th in TQ_THRESH:
    nm = f"TQQQ_PROXY_RSI{th}"
    signal_map[nm] = TSIG[th]
    targets[nm] = fast_overlay_from_dr(B0, TSIG[th], sp, cur0, DR0, None)

HIST = pd.DataFrame([eval_target(nm, t) for nm, t in targets.items()])
HIST.to_csv("tqqq_stage53_rsi_source_scan.csv", index=False)

# Fixed subperiods and cost sensitivity.
PER = [("2011-2015", 2011, 2015), ("2016-2018", 2016, 2018), ("2019-2021", 2019, 2021),
       ("2022-2024", 2022, 2024), ("2025-2026", 2025, 2026)]
sub = []
costs = []
for nm, t in targets.items():
    for lab, a, b in PER:
        ix = np.flatnonzero((YY51 >= a) & (YY51 <= b))
        if len(ix) < 20:
            continue
        dd = D.iloc[ix].reset_index(drop=True)
        pre = account_end(B0["ret"][ix], t[ix], COST, 0.0, dd)
        aft = account_end(B0["ret"][ix], t[ix], COST, TAX, dd)
        sub.append({"candidate": nm, "period": lab, "pre_cagr": pre["cagr"],
                    "pre_mdd": pre["mdd"], "tax_cagr": aft["cagr"]})
    for bps in (5, 10, 20):
        cc = bps / 10000.0
        pre = account_end(B0["ret"], t, cc, 0.0, D)
        aft = account_end(B0["ret"], t, cc, TAX, D)
        costs.append({"candidate": nm, "cost_bps": bps, "pre_cagr": pre["cagr"],
                      "pre_mdd": pre["mdd"], "tax_cagr": aft["cagr"], "tax_end": aft["end"]})
pd.DataFrame(sub).to_csv("tqqq_stage53_subperiods.csv", index=False)
pd.DataFrame(costs).to_csv("tqqq_stage53_costs.csv", index=False)

# Matched moving-block bootstrap. State is reset at block boundaries.
N = len(B0["ret"])
nb = int(np.ceil(H / BLOCK))
offs = np.arange(BLOCK)
rng = np.random.default_rng(SEED53)
starts = rng.integers(0, N - BLOCK + 1, size=(NSIM, nb))
paths = (starts[:, :, None] + offs).reshape(NSIM, -1)[:, :H]
bounds = list(range(BLOCK, H, BLOCK))
mcrows = []
mc_candidates = ["QQQ_RSI30"] + [f"TQQQ_PROXY_RSI{x}" for x in TQ_THRESH]
for z in range(NSIM):
    ix = paths[z]
    B = {k: B0[k][ix].copy() for k in KEYS}
    vx = VX[ix].copy()
    cur = current_trace(B)
    dr = fast_daily(B, vx, cur, bounds, True)
    for nm in mc_candidates:
        sg = signal_map[nm][ix].copy()
        t = fast_overlay_from_dr(B, sg, sp, cur, dr, bounds)
        pre = account_end(B["ret"], t, COST, 0.0, None)
        aft = account_end(B["ret"], t, COST, TAX, None)
        mcrows.append({"sim": z, "candidate": nm, "tax_end": aft["end"],
                       "tax_cagr": aft["cagr"], "pre_mdd": pre["mdd"]})
    if (z + 1) % 100 == 0:
        print("[mc53]", z + 1, "/", NSIM, flush=True)
MC = pd.DataFrame(mcrows)
MC.to_csv("tqqq_stage53_mc.csv", index=False)

def qntl(x, p):
    return float(np.quantile(np.asarray(x, float), p))

ms = []
for nm, g in MC.groupby("candidate"):
    ms.append({
        "candidate": nm,
        "tax_end_mean": float(g.tax_end.mean()),
        "tax_end_median": qntl(g.tax_end, .5),
        "tax_end_p05": qntl(g.tax_end, .05),
        "tax_cagr_median": qntl(g.tax_cagr, .5),
        "tax_cagr_p05": qntl(g.tax_cagr, .05),
        "mdd_median": qntl(g.pre_mdd, .5),
        "mdd_p05": qntl(g.pre_mdd, .05),
        "p_tax30": float(np.mean(g.tax_cagr >= .30)),
        "p_mdd50": float(np.mean(g.pre_mdd < -.50)),
    })
MCS = pd.DataFrame(ms)
MCS.to_csv("tqqq_stage53_mc_summary.csv", index=False)

piv = MC.pivot(index="sim", columns="candidate", values=["tax_end", "pre_mdd"])
pair = []
for nm in mc_candidates:
    if nm == "QQQ_RSI30":
        continue
    ratio = piv[("tax_end", nm)] / piv[("tax_end", "QQQ_RSI30")]
    dm = piv[("pre_mdd", nm)] - piv[("pre_mdd", "QQQ_RSI30")]
    pair.append({
        "candidate": nm,
        "p_end_better_qqq30": float(np.mean(ratio > 1)),
        "end_ratio_median": float(np.median(ratio)),
        "end_ratio_p05": qntl(ratio, .05),
        "mdd_delta_median": float(np.median(dm)),
        "p_mdd_no_worse_qqq30": float(np.mean(dm >= 0)),
    })
PAIR = pd.DataFrame(pair)
PAIR.to_csv("tqqq_stage53_pairwise.csv", index=False)

# ---------------------------------------------------------------------------
# NQSAR proxy audit.
# Stage16+ uses the archived no-clamp PSAR reconstruction. Compare it to the
# alternate standard clamp and to committed authoritative recent colors.
def psar_clamped(h, l, step=.02, mx=.08):
    h = np.asarray(h, float)
    l = np.asarray(l, float)
    n = len(h)
    s = np.full(n, np.nan)
    bull = True
    af = step
    ep = l[0]
    s[0] = l[0]
    for i in range(1, n):
        s[i] = s[i-1] + af * (ep - s[i-1])
        if bull:
            if i >= 2:
                s[i] = min(s[i], l[i-1], l[i-2])
            else:
                s[i] = min(s[i], l[i-1])
            if l[i] < s[i]:
                bull = False
                s[i] = ep
                ep = l[i]
                af = step
            elif h[i] > ep:
                ep = h[i]
                af = min(af + step, mx)
        else:
            if i >= 2:
                s[i] = max(s[i], h[i-1], h[i-2])
            else:
                s[i] = max(s[i], h[i-1])
            if h[i] > s[i]:
                bull = True
                s[i] = ep
                ep = h[i]
                af = step
            elif l[i] < ep:
                ep = l[i]
                af = min(af + step, mx)
    return s


def nq_colors_custom(frame, clamp):
    C = frame.Close.astype(float).to_numpy()
    Hh = frame.High.astype(float).to_numpy()
    Ll = frame.Low.astype(float).to_numpy()
    S = psar_clamped(Hh, Ll) if clamp else psar(Hh, Ll)
    E = pd.Series(C, index=frame.index).ewm(span=21, adjust=False).mean().to_numpy()
    R = rsi(C)
    a = C > S
    st = "Green" if a[0] else "Yellow"
    up = dn = 99
    prev = None
    out = []
    for i in range(len(C)):
        up = 0 if i > 0 and a[i] and not a[i-1] else up + 1
        dn = 0 if i > 0 and (not a[i]) and a[i-1] else dn + 1
        ri = float(R[i]) if np.isfinite(R[i]) else 50.0
        dr = ri - prev if prev is not None else 0.0
        if a[i]:
            if st == "Blue":
                st = "Green" if C[i] < E[i] else "Blue"
            else:
                st = "Blue" if ri > 52 and up >= 2 and dr <= 3 else "Green"
        else:
            if st == "Red":
                st = "Yellow" if ri > 50 else "Red"
            else:
                st = "Red" if ri < 47 and dn >= 2 and dr >= -3 else "Yellow"
        prev = ri
        out.append(st)
    return pd.Series(out, index=frame.index, dtype="object")


nq_arch = nq_colors_custom(nqraw, False)
nq_clamp = nq_colors_custom(nqraw, True)
actual = pd.Series(dtype="object")
try:
    arr = json.loads(Path("trend_history.json").read_text())
    actual = pd.Series({pd.Timestamp(d): c for d, c in arr}, dtype="object")
except Exception:
    pass

def nq_validate(s, name):
    if actual.empty:
        return {"proxy": name, "n": 0, "accuracy": None, "transition_accuracy": None}
    p = s.reindex(actual.index).ffill()
    a = actual.reindex(p.index)
    ok = p.notna() & a.notna()
    p = p[ok]
    a = a[ok]
    if not len(p):
        return {"proxy": name, "n": 0, "accuracy": None, "transition_accuracy": None}
    trans_a = a.ne(a.shift(1))
    trans_p = p.ne(p.shift(1))
    return {
        "proxy": name,
        "n": int(len(p)),
        "accuracy": float((p == a).mean()),
        "transition_accuracy": float((trans_p == trans_a).mean()),
        "mismatches": int((p != a).sum()),
    }

NQVAL = pd.DataFrame([nq_validate(nq_arch, "ARCHIVED"), nq_validate(nq_clamp, "CLAMPED")])
NQVAL.to_csv("tqqq_stage53_nqsar_recent_validation.csv", index=False)

mp = {"Red": 0, "Yellow": 1, "Green": 2, "Blue": 3}
nq_variants = {
    "ARCHIVED": np.array([mp.get(str(x), 1) for x in nq_arch.reindex(pd.DatetimeIndex(D)).ffill()], dtype=np.int8),
    "CLAMPED": np.array([mp.get(str(x), 1) for x in nq_clamp.reindex(pd.DatetimeIndex(D)).ffill()], dtype=np.int8),
}
nqsens = []
for label, nqv in nq_variants.items():
    B = {k: B0[k].copy() for k in KEYS}
    B["nq"] = nqv
    cur = current_trace(B)
    dr = fast_daily(B, VX, cur, None, True)
    t = fast_overlay_from_dr(B, qqq30, sp, cur, dr, None)
    pre = account_end(B["ret"], t, COST, 0.0, D)
    aft = account_end(B["ret"], t, COST, TAX, D)
    nqsens.append({"variant": label, "pre_cagr": pre["cagr"], "pre_mdd": pre["mdd"],
                   "tax_cagr": aft["cagr"], "tax_end": aft["end"], "avg_exp": float(np.mean(t))})
NQSENS = pd.DataFrame(nqsens)
NQSENS.to_csv("tqqq_stage53_nqsar_sensitivity.csv", index=False)

# ---------------------------------------------------------------------------
# MC57 PIT / expanding-universe audit.
# This can verify no pre-inception fill and quantify sensitivity to later ETF
# additions. It cannot recreate delisted ETFs that are absent from the current
# fixed universe, so "survivorship eliminated" is intentionally NOT claimed.
mc_audit = {"available": False, "reason": "", "universe": int(len(bt.bd.MC_MARKET_TICKERS))}
mctickers = []
mcyears = []
mcsens = []
try:
    asof = pd.Timestamp(D.iloc[-1]).normalize()
    macro = bt.bd._fetch_mc_long_history(asof=asof)
    if not macro:
        raise RuntimeError("MC long-history fetch returned empty")
    for t in bt.bd.MC_MARKET_TICKERS:
        f = macro.get(t)
        if f is None or not len(f):
            mctickers.append({"ticker": t, "first": "", "last": "", "bars": 0})
        else:
            ix = pd.DatetimeIndex(f.index).tz_localize(None)
            mctickers.append({"ticker": t, "first": str(ix.min().date()), "last": str(ix.max().date()), "bars": int(len(ix))})
    MCT = pd.DataFrame(mctickers).sort_values(["first", "ticker"])
    MCT.to_csv("tqqq_stage53_mc57_inceptions.csv", index=False)

    calendar = pd.DatetimeIndex(sorted(set().union(*[
        set(pd.DatetimeIndex(v.index).tz_localize(None)) for v in macro.values() if len(v)
    ])))
    cnt = pd.Series(0, index=calendar, dtype=int)
    for f in macro.values():
        ix = pd.DatetimeIndex(f.index).tz_localize(None)
        cnt.loc[cnt.index.intersection(ix)] += 1
    yy = cnt.index.year
    for y in sorted(set(yy)):
        g = cnt[yy == y]
        mcyears.append({"year": int(y), "min_available": int(g.min()), "median_available": float(g.median()),
                        "max_available": int(g.max())})
    pd.DataFrame(mcyears).to_csv("tqqq_stage53_mc57_coverage_by_year.csv", index=False)

    # Full score and earliest-N fixed cohorts.
    full_score, _, _, _, full_vals = bt.bd.mri_frame(macro, W=None)
    full_score = pd.to_numeric(full_score, errors="coerce")
    full_score.index = pd.DatetimeIndex(full_score.index).tz_localize(None)
    inception = MCT[MCT.bars > 0].copy()
    inception["first_ts"] = pd.to_datetime(inception["first"])
    inception = inception.sort_values(["first_ts", "ticker"])
    for ncohort in (30, 40, 50, 57):
        names = inception.head(min(ncohort, len(inception))).ticker.tolist()
        if len(names) < min(ncohort, 20):
            continue
        submacro = {t: macro[t] for t in names if t in macro}
        try:
            sc, _, _, _, vals = bt.bd.mri_frame(submacro, W=None)
        except Exception as exc:
            mcsens.append({"cohort": f"EARLIEST_{ncohort}", "n_tickers": len(submacro), "error": f"{type(exc).__name__}: {exc}"})
            continue
        sc = pd.to_numeric(sc, errors="coerce")
        sc.index = pd.DatetimeIndex(sc.index).tz_localize(None)
        cmp = pd.concat([full_score.rename("full"), sc.rename("cohort")], axis=1).dropna()
        cmp = cmp[(cmp.index >= pd.Timestamp(D.iloc[0])) & (cmp.index <= pd.Timestamp(D.iloc[-1]))]
        row = {"cohort": f"EARLIEST_{ncohort}", "n_tickers": len(submacro), "error": ""}
        if len(cmp) >= 100:
            row.update({
                "common_days": int(len(cmp)),
                "score_corr": float(cmp.corr().iloc[0, 1]),
                "median_abs_score_diff": float((cmp.full - cmp.cohort).abs().median()),
                "p95_abs_score_diff": float((cmp.full - cmp.cohort).abs().quantile(.95)),
            })
            mcarr = sc.reindex(pd.DatetimeIndex(D)).ffill().to_numpy(float)
            valid = np.isfinite(mcarr)
            if valid.sum() >= 500:
                first = int(np.flatnonzero(valid)[0])
                ids2 = np.arange(first, len(mcarr))
                B = {k: B0[k][ids2].copy() for k in KEYS}
                B["mc"] = mcarr[ids2]
                vx = VX[ids2]
                sg = qqq30[ids2]
                dd = D.iloc[ids2].reset_index(drop=True)
                cur = current_trace(B)
                dr = fast_daily(B, vx, cur, None, True)
                tt = fast_overlay_from_dr(B, sg, sp, cur, dr, None)
                aft = account_end(B["ret"], tt, COST, TAX, dd)
                pre = account_end(B["ret"], tt, COST, 0.0, dd)

                # Baseline on exactly the same dates.
                BB = {k: B0[k][ids2].copy() for k in KEYS}
                curb = current_trace(BB)
                drb = fast_daily(BB, vx, curb, None, True)
                tb = fast_overlay_from_dr(BB, sg, sp, curb, drb, None)
                aftb = account_end(BB["ret"], tb, COST, TAX, dd)
                preb = account_end(BB["ret"], tb, COST, 0.0, dd)
                row.update({
                    "strategy_start": str(pd.Timestamp(dd.iloc[0]).date()),
                    "cohort_pre_cagr": pre["cagr"],
                    "cohort_pre_mdd": pre["mdd"],
                    "cohort_tax_cagr": aft["cagr"],
                    "baseline_samewindow_pre_cagr": preb["cagr"],
                    "baseline_samewindow_pre_mdd": preb["mdd"],
                    "baseline_samewindow_tax_cagr": aftb["cagr"],
                    "tax_cagr_delta": aft["cagr"] - aftb["cagr"],
                    "mdd_delta": pre["mdd"] - preb["mdd"],
                })
        mcsens.append(row)
    pd.DataFrame(mcsens).to_csv("tqqq_stage53_mc57_cohort_sensitivity.csv", index=False)
    mc_audit.update({
        "available": True,
        "asof": str(asof.date()),
        "downloaded": int(len(macro)),
        "earliest_first": str(MCT[MCT.bars > 0]["first"].min()),
        "latest_first": str(MCT[MCT.bars > 0]["first"].max()),
        "survivorship_note": "Current fixed ETF list only: pre-inception rows remain missing, but delisted historical ETFs are not reconstructed.",
    })
except Exception as exc:
    mc_audit["reason"] = f"{type(exc).__name__}: {exc}"
Path("tqqq_stage53_mc57_audit.json").write_text(json.dumps(mc_audit, ensure_ascii=False, indent=2, default=str))
print("[mc57 audit]", mc_audit, flush=True)

# ---------------------------------------------------------------------------
# Decision summary. QQQ stays the default unless a proxy variant wins robustly
# AND the recent actual-TQQQ validation says the proxy itself is sufficiently close.
qqq_hist = HIST.set_index("candidate").loc["QQQ_RSI30"]
proxy_hist = HIST[HIST.candidate.str.startswith("TQQQ_PROXY_")].sort_values(["tax_cagr", "pre_mdd"], ascending=[False, False])
best_proxy = proxy_hist.iloc[0].to_dict() if len(proxy_hist) else None
best_pair = None
if best_proxy is not None and len(PAIR):
    z = PAIR[PAIR.candidate == best_proxy["candidate"]]
    if len(z):
        best_pair = z.iloc[0].to_dict()

proxy_quality_ok = (
    bool(recent_quality.get("available"))
    and recent_quality.get("rsi_corr") is not None
    and float(recent_quality["rsi_corr"]) >= .97
    and recent_quality.get("median_abs_rsi_diff") is not None
    and float(recent_quality["median_abs_rsi_diff"]) <= 3.0
)
proxy_robust_win = (
    best_pair is not None
    and float(best_pair.get("p_end_better_qqq30", 0)) >= .70
    and float(best_pair.get("end_ratio_median", 0)) > 1.02
    and float(best_pair.get("p_mdd_no_worse_qqq30", 0)) >= .50
)
rsi_recommendation = best_proxy["candidate"] if (proxy_quality_ok and proxy_robust_win) else "QQQ_RSI30"

summary = {
    "portfolio_start": str(pd.Timestamp(D.iloc[0]).date()),
    "portfolio_end": str(pd.Timestamp(D.iloc[-1]).date()),
    "stage51_reference": {
        "candidate": "QQQ_RSI30",
        "pre_cagr": float(qqq_hist.pre_cagr),
        "pre_mdd": float(qqq_hist.pre_mdd),
        "tax_cagr": float(qqq_hist.tax_cagr),
        "avg_exp": float(qqq_hist.avg_exp),
    },
    "best_tqqq_proxy": best_proxy,
    "best_proxy_pairwise": best_pair,
    "recent_proxy_quality": recent_quality,
    "rsi_source_recommendation": rsi_recommendation,
    "rsi_decision_rule": "Switch away from QQQ only if recent actual-TQQQ proxy validation is tight and matched bootstrap shows a robust terminal-wealth win without worse DD.",
    "nqsar_recent_validation": NQVAL.to_dict("records"),
    "nqsar_sensitivity": NQSENS.to_dict("records"),
    "mc57_audit": mc_audit,
    "mc57_cohort_sensitivity": mcsens,
    "caveats": [
        "Historical TQQQ 4H before the recent Yahoo intraday window is a QQQ-derived 3x intraday proxy reset to actual daily TQQQ open; it is not actual TQQQ intraday history.",
        "MC57 audit can prove no pre-inception filling and quantify current-universe expansion sensitivity, but cannot reconstruct delisted historical ETFs absent from the fixed current list.",
        "Authoritative historical NQSAR EXP_STATE_ID is unavailable; only recent committed trend_history can validate the reconstructed proxy.",
        "USDJPY/dividend tax remain outside the model.",
        "Moving-block bootstrap is robustness analysis, not a forecast probability distribution.",
    ],
}
Path("tqqq_stage53_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str))

FINAL = HIST.merge(MCS, on="candidate", how="left").merge(PAIR, on="candidate", how="left")
FINAL.to_csv("tqqq_stage53_final_rank.csv", index=False)
print("\n=== STAGE53 RSI SOURCE HISTORICAL ===")
print(HIST.sort_values(["tax_cagr", "pre_mdd"], ascending=[False, False]).to_string(index=False))
print("\n=== STAGE53 PAIRWISE VS QQQ_RSI30 ===")
print(PAIR.to_string(index=False))
print("\n=== STAGE53 NQSAR VALIDATION ===")
print(NQVAL.to_string(index=False))
print("\n=== STAGE53 NQSAR SENSITIVITY ===")
print(NQSENS.to_string(index=False))
print("\n=== STAGE53 DECISION ===")
print(json.dumps({
    "rsi_source_recommendation": rsi_recommendation,
    "proxy_quality_ok": proxy_quality_ok,
    "proxy_robust_win": proxy_robust_win,
    "mc57_available": mc_audit.get("available"),
}, ensure_ascii=False, indent=2))
