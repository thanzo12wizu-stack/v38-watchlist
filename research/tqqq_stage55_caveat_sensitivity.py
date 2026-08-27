from __future__ import annotations
from pathlib import Path
import json
import numpy as np
import pandas as pd
import yfinance as yf

# Reuse Stage51's exact daily portfolio, MC/NQSAR-linked runner and QQQ RSI30 signal.
src = Path("research/tqqq_stage51_4h_rsi30_entry_backtest.py").read_text()
prefix = src.split("# ---------- event study:")[0]
exec(compile(prefix, "stage51-prefix", "exec"), globals())

print("\n=== STAGE55 MC57 / NQSAR CAVEAT SENSITIVITY ===", flush=True)

# ---------------------------------------------------------------------------
# Final candidate evaluator. Only the audited input under test is changed.
SP = {"method": "touch30", "gate": "ANY", "floor": 1.0, "maxd": 10}
QQQ30 = SIG["touch30"]

def final_target(B, vx):
    cur = current_trace(B)
    return rsi_overlay(B, vx, QQQ30, SP, cur, None, False)

def eval_target(B, t, dates):
    m, _, _ = from_target(B, t, COST)
    pre = account_end(B["ret"], t, COST, 0.0, dates)
    aft = account_end(B["ret"], t, COST, TAX, dates)
    return {
        "pre_cagr": float(pre["cagr"]),
        "pre_mdd": float(pre["mdd"]),
        "tax_cagr": float(aft["cagr"]),
        "tax_end": float(aft["end"]),
        "avg_exp": float(m["avg_exp"]),
        "turnover": float(m["turnover"]),
    }

REF_T = final_target(B0, VX)
REF = eval_target(B0, REF_T, D)
print("[reference]", REF, flush=True)

# ---------------------------------------------------------------------------
# NQSAR: validate the archived research reconstruction against the committed
# recent authoritative trend_history, compare a standard two-bar-clamped PSAR,
# and measure how much the FINAL RSI30_ANY portfolio changes.
def psar_archived(h, l, step=.02, mx=.08):
    h = np.asarray(h, float); l = np.asarray(l, float); n = len(h)
    s = np.zeros(n); bull = True; af = step; ep = l[0]; s[0] = l[0]
    for i in range(1, n):
        s[i] = s[i-1] + af * (ep - s[i-1])
        if bull:
            if l[i] < s[i]:
                bull = False; s[i] = ep; ep = l[i]; af = step
            elif h[i] > ep:
                ep = h[i]; af = min(af + step, mx)
        else:
            if h[i] > s[i]:
                bull = True; s[i] = ep; ep = h[i]; af = step
            elif l[i] < ep:
                ep = l[i]; af = min(af + step, mx)
    return s

def psar_clamped(h, l, step=.02, mx=.08):
    h = np.asarray(h, float); l = np.asarray(l, float); n = len(h)
    s = np.full(n, np.nan); bull = True; af = step; ep = l[0]; s[0] = l[0]
    for i in range(1, n):
        s[i] = s[i-1] + af * (ep - s[i-1])
        if bull:
            s[i] = min(s[i], l[i-1]) if i < 2 else min(s[i], l[i-1], l[i-2])
            if l[i] < s[i]:
                bull = False; s[i] = ep; ep = l[i]; af = step
            elif h[i] > ep:
                ep = h[i]; af = min(af + step, mx)
        else:
            s[i] = max(s[i], h[i-1]) if i < 2 else max(s[i], h[i-1], h[i-2])
            if h[i] > s[i]:
                bull = True; s[i] = ep; ep = h[i]; af = step
            elif l[i] < ep:
                ep = l[i]; af = min(af + step, mx)
    return s

def rsi_wilder(c, n=14):
    x = pd.Series(c, dtype=float)
    d = x.diff(); up = d.clip(lower=0); dn = (-d).clip(lower=0)
    au = up.ewm(alpha=1/n, adjust=False, min_periods=n).mean()
    ad = dn.ewm(alpha=1/n, adjust=False, min_periods=n).mean()
    rs = au / ad.replace(0, np.nan)
    y = 100 - 100 / (1 + rs)
    return y.where(ad.ne(0), 100.0).to_numpy()

def nq_colors(frame, clamp=False):
    C = frame["Close"].astype(float).to_numpy()
    Hh = frame["High"].astype(float).to_numpy()
    Ll = frame["Low"].astype(float).to_numpy()
    S = psar_clamped(Hh, Ll) if clamp else psar_archived(Hh, Ll)
    E = pd.Series(C, index=frame.index).ewm(span=21, adjust=False).mean().to_numpy()
    R = rsi_wilder(C, 14)
    above = C > S
    state = "Green" if above[0] else "Yellow"
    bsu = bsd = 99; prev = None; out = []
    for i in range(len(C)):
        bsu = 0 if (i > 0 and above[i] and not above[i-1]) else bsu + 1
        bsd = 0 if (i > 0 and (not above[i]) and above[i-1]) else bsd + 1
        ri = float(R[i]) if np.isfinite(R[i]) else 50.0
        dr = ri - prev if prev is not None else 0.0
        if above[i]:
            if state == "Blue":
                state = "Green" if C[i] < E[i] else "Blue"
            else:
                state = "Blue" if (ri > 52 and bsu >= 2 and dr <= 3.0) else "Green"
        else:
            if state == "Red":
                state = "Yellow" if ri > 50 else "Red"
            else:
                state = "Red" if (ri < 47 and bsd >= 2 and dr >= -3.0) else "Yellow"
        prev = ri
        out.append(state)
    return pd.Series(out, index=pd.DatetimeIndex(frame.index).tz_localize(None).normalize(), dtype="object")

NQ_ARCH = nq_colors(nqraw, False)
NQ_CLAMP = nq_colors(nqraw, True)

truth = pd.Series(dtype="object")
try:
    arr = json.loads(Path("trend_history.json").read_text(encoding="utf-8"))
    truth = pd.Series({pd.Timestamp(d).normalize(): c for d, c in arr}, dtype="object")
except Exception:
    pass

def validate_nq(s, name):
    if truth.empty:
        return {"variant": name, "n": 0, "state_accuracy": None, "transition_accuracy": None, "mismatches": None}
    p = s.reindex(truth.index).ffill()
    a = truth.reindex(p.index)
    ok = p.notna() & a.notna(); p = p[ok]; a = a[ok]
    if not len(p):
        return {"variant": name, "n": 0, "state_accuracy": None, "transition_accuracy": None, "mismatches": None}
    ta = a.ne(a.shift(1)); tp = p.ne(p.shift(1))
    return {
        "variant": name,
        "n": int(len(p)),
        "state_accuracy": float((p == a).mean()),
        "transition_accuracy": float((tp == ta).mean()),
        "mismatches": int((p != a).sum()),
    }

NQVAL = pd.DataFrame([validate_nq(NQ_ARCH, "ARCHIVED"), validate_nq(NQ_CLAMP, "CLAMPED")])
NQVAL.to_csv("tqqq_stage55_nqsar_validation.csv", index=False)

color_map = {"Red": 0, "Yellow": 1, "Green": 2, "Blue": 3}
nq_variants = {
    "ARCHIVED": NQ_ARCH,
    "CLAMPED": NQ_CLAMP,
}
nq_rows = []
for name, ser in nq_variants.items():
    vals = ser.reindex(pd.DatetimeIndex(D).normalize()).ffill()
    nqv = np.array([color_map.get(str(x), 1) for x in vals], dtype=np.int8)
    B = {k: B0[k].copy() for k in KEYS}; B["nq"] = nqv
    t = final_target(B, VX)
    row = {"variant": name, **eval_target(B, t, D)}
    row["target_diff_days_vs_ref"] = int(np.sum(np.abs(t - REF_T) > 1e-12))
    row["tax_cagr_delta_vs_ref"] = row["tax_cagr"] - REF["tax_cagr"]
    row["mdd_delta_vs_ref"] = row["pre_mdd"] - REF["pre_mdd"]
    nq_rows.append(row)

# Upper-bound dependence test: remove only the NQSAR Red block (all sessions non-red).
B_NR = {k: B0[k].copy() for k in KEYS}; B_NR["nq"] = np.ones(len(D), dtype=np.int8)
T_NR = final_target(B_NR, VX)
row = {"variant": "NO_NQSAR_RED_BLOCK", **eval_target(B_NR, T_NR, D)}
row["target_diff_days_vs_ref"] = int(np.sum(np.abs(T_NR - REF_T) > 1e-12))
row["tax_cagr_delta_vs_ref"] = row["tax_cagr"] - REF["tax_cagr"]
row["mdd_delta_vs_ref"] = row["pre_mdd"] - REF["pre_mdd"]
nq_rows.append(row)
NQSENS = pd.DataFrame(nq_rows)
NQSENS.to_csv("tqqq_stage55_nqsar_sensitivity.csv", index=False)

# ---------------------------------------------------------------------------
# MC57 survivorship pressure test. The true delisted historical universe is not
# recoverable here. Instead, compare the current 57-name score to fixed cohorts
# containing only the earliest-listed current names. This directly tests whether
# later additions materially drive the thresholds used by RSI30_ANY (20 and 35).
tickers = list(bt.bd.MC_MARKET_TICKERS)
start = getattr(bt.bd, "MC_LONG_HISTORY_START", "1992-01-01")
print(f"[mc55] downloading fixed current universe from {start}", flush=True)
macro = {}
raw = yf.download(tickers, start=start, auto_adjust=True, progress=False, group_by="ticker", threads=True)
macro.update(bt.bd._extract(raw, tickers, minbars=30))
for t in [x for x in tickers if x not in macro]:
    try:
        h = yf.Ticker(t).history(start=start, auto_adjust=True)
        got = bt.bd._extract(h, [t], minbars=30).get(t)
        if got is not None and len(got):
            macro[t] = got
    except Exception:
        pass
if len(macro) < 40:
    raise RuntimeError(f"MC57 sensitivity fetch too sparse: {len(macro)}/57")

inc = []
for t in tickers:
    f = macro.get(t)
    if f is None or not len(f):
        continue
    ix = pd.DatetimeIndex(f.index)
    if ix.tz is not None: ix = ix.tz_localize(None)
    inc.append({"ticker": t, "first": pd.Timestamp(ix.min()).normalize(), "last": pd.Timestamp(ix.max()).normalize(), "bars": int(len(ix))})
INC = pd.DataFrame(inc).sort_values(["first", "ticker"]).reset_index(drop=True)
INC.assign(first=INC["first"].dt.strftime("%Y-%m-%d"), last=INC["last"].dt.strftime("%Y-%m-%d")).to_csv(
    "tqqq_stage55_mc57_inceptions.csv", index=False
)

full_score, _, _, _, _ = bt.bd.mri_frame(macro, W=None)
full_score = pd.to_numeric(full_score, errors="coerce")
full_score.index = pd.DatetimeIndex(full_score.index)
if full_score.index.tz is not None: full_score.index = full_score.index.tz_localize(None)
full_on_D = full_score.reindex(pd.DatetimeIndex(D).normalize()).ffill()

mc_rows = []
for ncohort in (40, 47, 50, 57):
    names = INC.head(min(ncohort, len(INC))).ticker.tolist()
    sub = {t: macro[t] for t in names}
    sc, _, _, _, _ = bt.bd.mri_frame(sub, W=None)
    sc = pd.to_numeric(sc, errors="coerce")
    sc.index = pd.DatetimeIndex(sc.index)
    if sc.index.tz is not None: sc.index = sc.index.tz_localize(None)
    scD = sc.reindex(pd.DatetimeIndex(D).normalize()).ffill()
    valid = scD.notna() & full_on_D.notna()
    row = {"cohort": f"EARLIEST_{ncohort}", "n_tickers": int(len(names)), "valid_days": int(valid.sum())}
    if valid.sum() < 500:
        row["error"] = "insufficient overlapping MC days"
        mc_rows.append(row)
        continue
    a = full_on_D[valid].astype(float); b = scD[valid].astype(float)
    row.update({
        "error": "",
        "score_corr": float(a.corr(b)),
        "median_abs_score_diff": float((a-b).abs().median()),
        "p95_abs_score_diff": float((a-b).abs().quantile(.95)),
        "gate20_agreement": float(((a >= 20) == (b >= 20)).mean()),
        "gate35_agreement": float(((a >= 35) == (b >= 35)).mean()),
    })
    ids = np.flatnonzero(valid.to_numpy())
    # Require a contiguous suffix to avoid silently bridging missing score dates.
    first = int(ids[0])
    ids = np.arange(first, len(D))
    sc_arr = scD.to_numpy(float)[ids]
    finite = np.isfinite(sc_arr)
    if not finite.all():
        row["error"] = "non-contiguous cohort MC score"
        mc_rows.append(row)
        continue
    B = {k: B0[k][ids].copy() for k in KEYS}; B["mc"] = sc_arr
    vx = VX[ids]; sig = QQQ30[ids]; dates = D.iloc[ids].reset_index(drop=True)
    cur = current_trace(B)
    t = rsi_overlay(B, vx, sig, SP, cur, None, False)
    cohort_stats = eval_target(B, t, dates)

    BF = {k: B0[k][ids].copy() for k in KEYS}
    curf = current_trace(BF)
    tf = rsi_overlay(BF, vx, sig, SP, curf, None, False)
    full_stats = eval_target(BF, tf, dates)
    row.update({
        "strategy_start": str(pd.Timestamp(dates.iloc[0]).date()),
        "cohort_pre_cagr": cohort_stats["pre_cagr"],
        "cohort_pre_mdd": cohort_stats["pre_mdd"],
        "cohort_tax_cagr": cohort_stats["tax_cagr"],
        "full_samewindow_pre_cagr": full_stats["pre_cagr"],
        "full_samewindow_pre_mdd": full_stats["pre_mdd"],
        "full_samewindow_tax_cagr": full_stats["tax_cagr"],
        "tax_cagr_delta": cohort_stats["tax_cagr"] - full_stats["tax_cagr"],
        "mdd_delta": cohort_stats["pre_mdd"] - full_stats["pre_mdd"],
        "target_diff_days": int(np.sum(np.abs(t - tf) > 1e-12)),
    })
    mc_rows.append(row)

MCSENS = pd.DataFrame(mc_rows)
MCSENS.to_csv("tqqq_stage55_mc57_cohort_sensitivity.csv", index=False)

# ---------------------------------------------------------------------------
# Severity labels are descriptive only; they do not auto-change the strategy.
arch_acc = NQVAL.set_index("variant").loc["ARCHIVED", "state_accuracy"] if len(NQVAL) else np.nan
clamped = NQSENS.set_index("variant").loc["CLAMPED"]
nq_material = (
    abs(float(clamped["tax_cagr_delta_vs_ref"])) >= .02
    or abs(float(clamped["mdd_delta_vs_ref"])) >= .03
)
mc47 = MCSENS[MCSENS["cohort"] == "EARLIEST_47"]
mc_material = True
if len(mc47) and not str(mc47.iloc[0].get("error", "")):
    r = mc47.iloc[0]
    mc_material = (
        abs(float(r.get("tax_cagr_delta", np.nan))) >= .02
        or abs(float(r.get("mdd_delta", np.nan))) >= .03
        or float(r.get("gate20_agreement", 0)) < .90
        or float(r.get("gate35_agreement", 0)) < .90
    )

summary = {
    "reference": REF,
    "nqsar": {
        "recent_validation": NQVAL.to_dict("records"),
        "strategy_sensitivity": NQSENS.to_dict("records"),
        "archived_recent_state_accuracy": None if pd.isna(arch_acc) else float(arch_acc),
        "material_sensitivity": bool(nq_material),
        "remaining_caveat": "Recent trend_history can validate the reconstruction only over the committed recent window; full-history TradingView EXP_STATE_ID is still unavailable.",
    },
    "mc57": {
        "cohort_sensitivity": MCSENS.to_dict("records"),
        "material_sensitivity_earliest47": bool(mc_material),
        "remaining_caveat": "This pressure test excludes later-listed current ETFs but still cannot reconstruct delisted historical ETFs; universe survivorship is therefore not fully eliminated.",
    },
    "decision": {
        "strategy_change": "NONE",
        "candidate": "QQQ_RSI30 / RSI30_ANY",
        "reason": "Stage55 is a validity sensitivity audit only. It does not optimize new thresholds or alter the proven execution hierarchy.",
    },
}
Path("tqqq_stage55_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
print("\nNQSAR VALIDATION"); print(NQVAL.to_string(index=False))
print("\nNQSAR SENSITIVITY"); print(NQSENS.to_string(index=False))
print("\nMC57 COHORT SENSITIVITY"); print(MCSENS.to_string(index=False))
print("\nSUMMARY"); print(json.dumps(summary, ensure_ascii=False, default=str))
