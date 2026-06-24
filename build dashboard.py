#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Command Center — dashboard builder
  A. Individual sleeve: N=8, weekly-SAR(W-FRI, AF .02/.02/.20) non-bearish filter,
     selection = 63d RS top x >200MA x weekly-SAR non-bearish x 1-theme<=4. No Stock Score gate.
  B. Allocation display: 個別30 / レバ50 / 現金20 (40/40/20 conservative alt note).
  C. Market status = MRI 地合いスコア (11-indicator weighted sum, raw 0-100, no L16 remap).
  D. 6 tabs (今日/マーケット/ポートフォリオ/ウォッチ/業種RS/ルール), all-setup chips,
     treasury yields + broad breadth, rules caveats. SAR/OniMine/算出根拠 hidden.

Data: live yfinance (CI) or cached /home/claude/bt/prices.pkl for local preview.
Run:  python3 build_dashboard.py            -> render HTML + selftest
      python3 build_dashboard.py --diag     -> print computed numbers, no HTML
      python3 build_dashboard.py --selftest -> render + assert
"""
import sys, os, json, csv, pickle, warnings, time, datetime as dt
warnings.filterwarnings("ignore")
import numpy as np, pandas as pd

CACHE        = os.environ.get("V38_CACHE",        "/home/claude/bt/prices.pkl")
UNIVERSE_CSV = os.environ.get("V38_UNIVERSE_CSV", "/mnt/project/universe.csv")
SECTOR_JSON  = os.environ.get("V38_SECTOR_JSON",  "/mnt/project/sector_snapshot.json")
OUT_HTML     = os.environ.get("V38_OUT_HTML",     "/mnt/user-data/outputs/V38_Command_Center.html")

N_PORT = 8
THEME_CAP = 4
CHIP_CAP = 24                  # max chips shown per setup/state list (rest folded to +N件)
ALLOC = (40, 40, 20)           # 個別 / レバ / 現金 (確定・本命 2026-06-24)
ALLOC_ALT = (30, 50, 20)       # 代替 (実ETFブレンド CAGR71.9/Sharpe1.94/DD-21.7)
# industries excluded from sector-RS (binary-event noise); editable blacklist
SECTOR_BLACKLIST_KEYS = ("biotech", "pharmaceutic", "drug")

# ----------------------------------------------------------------------------- inputs
def load_inputs(use_cache=True):
    rows = list(csv.DictReader(open(UNIVERSE_CSV)))
    names = {}
    order = []
    for r in rows:
        b = (r.get("Ticker") or "").strip()
        if not b:
            continue
        names[b] = (r.get("name") or "").strip()
        order.append(b)
    sj = json.load(open(SECTOR_JSON))
    s2i = sj.get("s2i", {})            # symbol -> industry (EN)
    s2t = sj.get("s2t", {})            # symbol -> [theme, microtheme]
    e2j = sj.get("e2j", {})            # industry EN -> JA
    if use_cache and os.path.exists(CACHE):
        pk = pickle.load(open(CACHE, "rb"))
    else:
        pk = fetch_live(order)          # CI path: no pre-existing cache
    return names, order, s2i, s2t, e2j, pk["W"], pk["macro"], pk["asof"]

# ----------------------------------------------------------------------------- live fetch (CI)
MACRO_TICKERS = ["^VIX", "^VIX3M", "^VVIX", "QQQ", "SPY", "HYG", "LQD",
                 "RSP", "IWM", "^TNX", "^FVX", "^TYX",
                 # equal-weight sector ETFs (Invesco) for market-representative sector RS
                 "RSPN", "RSPT", "RSPF", "RSPM", "RSPU", "RSPD",
                 "RSPH", "RSPR", "RSPS", "RSPG", "RSPC"]

def _extract(df, tickers, minbars=30):
    out = {}
    if df is None or getattr(df, "empty", True):
        return out
    multi = isinstance(df.columns, pd.MultiIndex)
    need = ["Open", "High", "Low", "Close", "Volume"]
    for t in tickers:
        try:
            sub = df[t] if multi else df
            if sub is None or sub.dropna(how="all").empty:
                continue
            if not all(c in sub.columns for c in need):
                continue
            s = sub[need].dropna(how="all")
            if len(s) < minbars:
                continue
            out[t] = s
        except Exception:
            continue
    return out

def fetch_live(order, period="2y", chunk=100, retries=3):
    """Fetch the full universe + macro live (GitHub Actions path, no cache).
    Mirrors the resumable fetch but in one process. Universe is keyed by base
    ticker; '/' tickers are skipped (yfinance chokes on them)."""
    import yfinance as yf
    rows = list(csv.DictReader(open(UNIVERSE_CSV)))
    pairs = []                                   # (base, yf_symbol)
    for r in rows:
        y = (r.get("YF_Ticker") or r.get("Ticker") or "").strip()
        b = (r.get("Ticker") or y).strip()
        if not y or "/" in y:
            continue
        pairs.append((b, y))
    y2b = {y: b for b, y in pairs}
    yfs = [y for _, y in pairs]
    sys.stderr.write("[fetch_live] universe=%d, fetching in chunks of %d...\n" % (len(pairs), chunk))

    store = {}
    for i in range(0, len(yfs), chunk):
        ch = yfs[i:i + chunk]
        for attempt in range(retries):
            try:
                df = yf.download(ch, period=period, progress=False, auto_adjust=True,
                                 group_by="ticker", threads=True)
                got = _extract(df, ch)
                store.update(got)
                missing = [t for t in ch if t not in store]
                # one retry pass only for the still-missing names (handles partial 429s)
                if missing and attempt < retries - 1:
                    time.sleep(2 * (attempt + 1))
                    continue
                break
            except Exception as e:
                if attempt < retries - 1:
                    time.sleep(3 * (attempt + 1))      # exponential-ish backoff
                    continue
                sys.stderr.write("  chunk err (gave up): %s\n" % repr(e)[:80])
        sys.stderr.write("  %d/%d  have=%d\n" % (min(i + chunk, len(yfs)), len(yfs), len(store)))

    def wide(field):
        cols = {y2b.get(y, y): df[field] for y, df in store.items()}
        return pd.DataFrame(cols).sort_index()
    W = {f: wide(f) for f in ["Open", "High", "Low", "Close", "Volume"]}

    sys.stderr.write("[fetch_live] fetching macro...\n")
    macro = {}
    try:
        md = yf.download(MACRO_TICKERS, period=period, progress=False,
                         auto_adjust=True, group_by="ticker", threads=True)
        macro = _extract(md, MACRO_TICKERS, minbars=20)
    except Exception:
        pass
    for m in [x for x in MACRO_TICKERS if x not in macro]:   # per-ticker fallback
        try:
            macro.update(_extract(yf.download([m], period=period, progress=False,
                                              auto_adjust=True), [m], minbars=20))
        except Exception:
            pass
    sys.stderr.write("[fetch_live] universe cols=%d  macro=%d/%d (VVIX=%s VIX3M=%s)\n" % (
        W["Close"].shape[1], len(macro), len(MACRO_TICKERS),
        "^VVIX" in macro, "^VIX3M" in macro))
    return {"W": W, "macro": macro, "asof": str(pd.Timestamp.utcnow())}

def theme_of(t, s2t):
    v = s2t.get(t)
    if isinstance(v, list) and v:
        return v[0]
    if isinstance(v, str) and v.strip():
        return v.strip()
    return "その他"

# ----------------------------------------------------------------------------- per-ticker metrics
def ema(s, span):
    return s.ewm(span=span, adjust=False).mean()

def weekly_sar_bullish(h, l, c):
    """Wilder Parabolic SAR on W-FRI weekly bars. Return True if current bar bullish."""
    df = pd.DataFrame({"High": h, "Low": l, "Close": c}).dropna()
    if len(df) < 15:
        return np.nan
    w = df.resample("W-FRI").agg({"High": "max", "Low": "min", "Close": "last"}).dropna()
    if len(w) < 10:
        return np.nan
    H = w["High"].values; L = w["Low"].values
    af0, step, afmax = 0.02, 0.02, 0.20
    up = w["Close"].values[1] >= w["Close"].values[0]
    sar = L[0] if up else H[0]
    ep = H[0] if up else L[0]
    af = af0
    for i in range(1, len(w)):
        prev = sar
        sar = prev + af * (ep - prev)
        if up:
            sar = min(sar, L[i-1], L[i-2] if i >= 2 else L[i-1])
            if H[i] > ep:
                ep = H[i]; af = min(af + step, afmax)
            if L[i] < sar:
                up = False; sar = ep; ep = L[i]; af = af0
        else:
            sar = max(sar, H[i-1], H[i-2] if i >= 2 else H[i-1])
            if L[i] < ep:
                ep = L[i]; af = min(af + step, afmax)
            if H[i] > sar:
                up = True; sar = ep; ep = H[i]; af = af0
    return bool(up)

def compute_metrics(W, order):
    C, O, H, L, V = W["Close"], W["Open"], W["High"], W["Low"], W["Volume"]
    idx = C.index
    recs = []
    for t in order:
        if t not in C.columns:
            continue
        c = C[t].dropna()
        if len(c) < 60:
            continue
        h = H[t].reindex(c.index); l = L[t].reindex(c.index); v = V[t].reindex(c.index)
        close = c.iloc[-1]; prev = c.iloc[-2] if len(c) >= 2 else np.nan
        sma50  = c.rolling(50).mean().iloc[-1]  if len(c) >= 50  else np.nan
        sma200 = c.rolling(200).mean().iloc[-1] if len(c) >= 200 else np.nan
        sma21  = c.iloc[-21:].mean()
        ema21  = ema(c, 21).iloc[-1]
        ret63  = close / c.iloc[-64] - 1 if len(c) >= 64 else np.nan
        ret63_l1 = c.iloc[-22] / c.iloc[-85] - 1 if len(c) >= 85 else np.nan   # 63d RS as of ~21d ago
        ret63_l2 = c.iloc[-43] / c.iloc[-106] - 1 if len(c) >= 106 else np.nan # 63d RS as of ~42d ago
        ret21  = close / c.iloc[-22] - 1 if len(c) >= 22 else np.nan
        ret20  = close / c.iloc[-21] - 1 if len(c) >= 21 else np.nan
        ret5   = close / c.iloc[-6]  - 1 if len(c) >= 6  else np.nan
        hi40   = h.iloc[-40:].max()                       # procedure HIGH_LB=40
        pb     = close / hi40 - 1 if hi40 and not np.isnan(hi40) else np.nan
        adr    = float((h.iloc[-20:] / l.iloc[-20:] - 1).mean())
        win = c.iloc[-252:] if len(c) >= 30 else c
        hi52 = win.max(); dist52 = close / hi52 - 1
        vol = v.iloc[-1]; vol20 = v.rolling(20).mean().iloc[-1] if len(v) >= 20 else np.nan
        vol50 = v.iloc[-50:].mean() if len(v) >= 50 else np.nan
        rvol = float(vol / vol50) if vol50 and not np.isnan(vol50) and vol50 > 0 else np.nan
        dvol = close * (vol20 if not np.isnan(vol20) else vol)
        # bollinger width (20) + its 126d percentile (vol contraction)
        m20 = c.rolling(20).mean(); sd20 = c.rolling(20).std()
        bbw_series = (4 * sd20) / m20
        bbw = bbw_series.iloc[-1]
        tailbw = bbw_series.dropna().iloc[-126:]
        bbw_pct = (tailbw < bbw).mean() * 100 if len(tailbw) >= 20 else np.nan
        sar_bull = weekly_sar_bullish(h, l, c)
        recs.append(dict(
            t=t, close=close, prev=prev,
            pchg=(close/prev - 1) if prev and not np.isnan(prev) else np.nan,
            sma50=sma50, sma200=sma200, ema21=ema21, sma21=sma21,
            vs50=(close/sma50 - 1) if sma50 and not np.isnan(sma50) else np.nan,
            vs200=(close/sma200 - 1) if sma200 and not np.isnan(sma200) else np.nan,
            dma21=(close/sma21 - 1) if sma21 and not np.isnan(sma21) else np.nan,
            dma50=(close/sma50 - 1) if sma50 and not np.isnan(sma50) else np.nan,
            hi40=hi40, pb=pb, adr=adr, ret5=ret5, ret20=ret20, rvol=rvol,
            ret63=ret63, ret21=ret21, hi52=hi52, dist52=dist52,
            ret63_l1=ret63_l1, ret63_l2=ret63_l2,
            vol=vol, vol20=vol20, dvol=dvol,
            volx=(vol/vol20) if vol20 and not np.isnan(vol20) and vol20 > 0 else np.nan,
            bbw=bbw, bbw_pct=bbw_pct, sar_bull=sar_bull,
        ))
    df = pd.DataFrame(recs).set_index("t")
    # RS percentile from 63d return (0-100), instantaneous for monitoring
    df["rs"] = df["ret63"].rank(pct=True) * 100
    # smoothed RS = mean of 3 RS-percentile snapshots (今/~21d前/~42d前) — used for monthly selection
    r0 = df["ret63"].rank(pct=True)
    r1 = df["ret63_l1"].rank(pct=True)
    r2 = df["ret63_l2"].rank(pct=True)
    df["rs_smooth"] = pd.concat([r0, r1, r2], axis=1).mean(axis=1, skipna=True) * 100
    return df, idx[-1]

# ----------------------------------------------------------------------------- MRI engine (C)
MRI_DEF = [
    # key, weight, lo, hi, group  (lo->0, hi->1; VIX family has hi<lo = inverted)
    ("qqq_50", 10, -0.03, 0.10, "trend"),
    ("qqq_200", 8, -0.05, 0.10, "trend"),
    ("spy_50",  6, -0.03, 0.07, "trend"),
    ("spy_200", 6, -0.05, 0.10, "trend"),
    ("vix",    12, 25.0, 13.0,  "vol"),
    ("vix_ratio", 8, 1.05, 0.95, "vol"),
    ("vvix",    5, 120.0, 80.0,  "vol"),
    ("hyglqd_20", 12, 0.98, 1.02, "credit"),
    ("hyglqd_5d",  8, -0.02, 0.02, "credit"),
    ("rsp_spy_20", 13, 0.98, 1.02, "breadth"),
    ("iwm_spy_20", 12, 0.98, 1.02, "breadth"),
]

def clamp01(x):
    return np.clip(x, 0.0, 1.0)

def mri_frame(macro):
    cl = lambda k: macro[k]["Close"] if k in macro else None
    have = {k: (cl(k) is not None) for k in
            ["QQQ","SPY","^VIX","^VIX3M","^VVIX","HYG","LQD","RSP","IWM"]}
    base = pd.DataFrame({k: cl(k) for k in ["QQQ","SPY","HYG","LQD","RSP","IWM"] if cl(k) is not None})
    base["VIX"] = cl("^VIX")
    if cl("^VIX3M") is not None: base["VIX3M"] = cl("^VIX3M")
    if cl("^VVIX") is not None:  base["VVIX"]  = cl("^VVIX")
    base = base.sort_index().ffill().dropna(how="any")
    qqq, spy = base["QQQ"], base["SPY"]
    hyglqd = base["HYG"] / base["LQD"]
    rspspy = base["RSP"] / base["SPY"]
    iwmspy = base["IWM"] / base["SPY"]
    vals = pd.DataFrame(index=base.index)
    vals["qqq_50"]  = qqq / qqq.rolling(50).mean() - 1
    vals["qqq_200"] = qqq / qqq.rolling(200).mean() - 1
    vals["spy_50"]  = spy / spy.rolling(50).mean() - 1
    vals["spy_200"] = spy / spy.rolling(200).mean() - 1
    vals["vix"]     = base["VIX"]
    vals["vix_ratio"] = (base["VIX"] / base["VIX3M"]) if "VIX3M" in base else np.nan
    vals["vvix"]    = base["VVIX"] if "VVIX" in base else np.nan
    vals["hyglqd_20"] = hyglqd / hyglqd.rolling(20).mean()
    vals["hyglqd_5d"] = hyglqd / hyglqd.shift(5) - 1
    vals["rsp_spy_20"] = rspspy / rspspy.rolling(20).mean()
    vals["iwm_spy_20"] = iwmspy / iwmspy.rolling(20).mean()

    dropped = []
    active = []
    for key, w, lo, hi, grp in MRI_DEF:
        if vals[key].dropna().empty:
            dropped.append(key)
        else:
            active.append((key, w, lo, hi, grp))
    tot_w = sum(w for _, w, _, _, _ in active)
    # MRI time series (renormalized to 100 over active weights)
    contrib = pd.DataFrame(index=vals.index)
    for key, w, lo, hi, grp in active:
        contrib[key] = w * clamp01((vals[key] - lo) / (hi - lo))
    mri = contrib.sum(axis=1) / tot_w * 100.0
    mri = mri.dropna()
    # latest breakdown
    last = vals.iloc[-1]
    breakdown = []
    for key, w, lo, hi, grp in active:
        sc01 = float(clamp01((last[key] - lo) / (hi - lo)))
        breakdown.append(dict(key=key, w=w, group=grp, raw=float(last[key]),
                              pts=w * sc01, ptsmax=w, frac=sc01))
    return mri, breakdown, dropped, active, vals

def mri_auxiliary(mri, vals, metrics):
    cur = float(mri.iloc[-1])
    ma10 = mri.rolling(10).mean()
    slope_dir = "→"
    if len(ma10.dropna()) >= 3:
        d = ma10.iloc[-1] - ma10.iloc[-3]
        slope_dir = "↑" if d > 0.4 else ("↓" if d < -0.4 else "→")
    last = vals.iloc[-1]
    # 12 bearish conditions
    qqq = vals["qqq_50"]; 
    bear = [
        last["qqq_50"]  < 0,                    # QQQ<50MA
        last["qqq_200"] < 0,                    # QQQ<200MA
        last["spy_50"]  < 0,                    # SPY<50MA
        last["spy_200"] < 0,                    # SPY<200MA
        last["vix"]     > 20,                   # VIX>20
        (last.get("vix_ratio", np.nan) > 1.00),  # backwardation
        (last.get("vvix", np.nan) > 100),        # VVIX>100
        last["hyglqd_20"] < 1.0,                # credit < 20MA
        last["hyglqd_5d"] < 0,                  # credit 5d down
        last["rsp_spy_20"] < 1.0,               # breadth(RSP/SPY)<20MA
        last["iwm_spy_20"] < 1.0,               # smallcap(IWM/SPY)<20MA
        cur < 45,                               # composite sub-neutral
    ]
    bear_n = int(np.nansum([1.0 if (b is True or b == True) else 0.0 for b in bear]))
    # peak decline from trailing 20d MRI high
    hi20 = mri.iloc[-20:].max() if len(mri) >= 5 else cur
    drop = hi20 - cur
    if drop < 3:    peak = "通常"
    elif drop < 7:  peak = "注意"
    elif drop < 12: peak = "減速"
    else:           peak = "深押し"
    return dict(cur=cur, slope=slope_dir, bear_n=bear_n, peak=peak, drop=drop, hi20=hi20)

def mri_band(v):
    if v >= 75: return ("強気（過熱・反落注意⚠）", "ovh")
    if v >= 60: return ("強気", "bull")
    if v >= 45: return ("中立", "neu")
    if v >= 30: return ("弱含み", "weak")
    return ("弱気", "bear")

# ----------------------------------------------------------------------------- NQ-SAR signal (leverage sleeve; logic hidden, only color+判定 shown)
# Authoritative source = sar_state.txt (committed by the TradingView->Pipedream
# webhook on every OniMine color flip). Falls back to the OniMine state embedded
# in a local NQ export, then to a safe default.
SAR_STATE_PATH = os.environ.get("V38_SAR_STATE", "sar_state.txt")
NQ_EXPORT_CANDIDATES = [
    os.environ.get("V38_NQ_EXPORT", ""),
    "/mnt/project/CME_MINI_DL_NQ1___1D_3.csv",
    "/mnt/project/CME_MINI_DL_NQ1___1D.csv",
]
# color -> (color label, trend judgment, sub descriptor, css class) — public-facing, logic hidden
# Severity (strong bull -> strong bear): Blue > Green > Yellow > Red
#   Blue  = price>SAR, RSI high (~64)  → strongest uptrend
#   Green = price>SAR, RSI moderate (~52) → uptrend but momentum fading (caution)
#   Yellow= price<SAR, RSI moderate (~51) → early/shallow downtrend
#   Red   = price<SAR, RSI low (~40)  → strong downtrend
SAR_JUDGMENT = {
    "Blue":   ("Blue",   "強い上昇", "継続",     "sar-blue"),
    "Green":  ("Green",  "上昇一服", "減速注意", "sar-green"),
    "Yellow": ("Yellow", "弱含み",   "警戒",     "sar-yellow"),
    "Red":    ("Red",    "下落",     "回避",     "sar-red"),
}
_SAR_ID2COLOR = {1: "Blue", 2: "Yellow", 3: "Red", 4: "Green"}

def _norm_color(s):
    if not s:
        return None
    s = str(s).strip()
    s = s[:1].upper() + s[1:].lower()
    return s if s in SAR_JUDGMENT else None

def _sar_from_nq():
    """Deep fallback: latest OniMine EXP_STATE_ID from a local NQ export (if present)."""
    for p in NQ_EXPORT_CANDIDATES:
        if p and os.path.exists(p):
            try:
                df = pd.read_csv(p)
                col = [c for c in df.columns if "EXP_STATE_ID" in c]
                if not col:
                    continue
                sid = int(df[col[0]].dropna().iloc[-1])
                return _SAR_ID2COLOR.get(sid)
            except Exception:
                continue
    return None

def _psar(h, l, c, step=0.02, mx=0.20):
    """Wilder Parabolic SAR (AF 0.02 step, 0.20 max)."""
    n = len(c); sar = np.zeros(n); bull = True; af = step; ep = l[0]; sar[0] = l[0]
    for i in range(1, n):
        sar[i] = sar[i-1] + af*(ep - sar[i-1])
        if bull:
            if l[i] < sar[i]:
                bull = False; sar[i] = ep; ep = l[i]; af = step
            elif h[i] > ep:
                ep = h[i]; af = min(af+step, mx)
        else:
            if h[i] > sar[i]:
                bull = True; sar[i] = ep; ep = h[i]; af = step
            elif l[i] < ep:
                ep = l[i]; af = min(af+step, mx)
    return sar

def _estimate_sar_from_live():
    """Fallback: estimate OniMine color from live NQ=F (PSAR + RSI).
    Blue=above SAR & RSI high, Green=above SAR & RSI moderate,
    Yellow=below SAR & RSI moderate, Red=below SAR & RSI low. None on failure."""
    try:
        import yfinance as yf
        df = yf.download("NQ=F", period="6mo", interval="1d",
                         auto_adjust=False, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.dropna()
        if len(df) < 30:
            return None
        H, L, C = df["High"].values, df["Low"].values, df["Close"].values
        sar = _psar(H, L, C)
        d = df["Close"].diff()
        up = d.clip(lower=0); dn = -d.clip(upper=0)
        ru = up.ewm(alpha=1/14, adjust=False).mean()
        rd = dn.ewm(alpha=1/14, adjust=False).mean()
        rsi = float((100 - 100/(1 + ru/rd)).iloc[-1])
        if C[-1] > sar[-1]:
            return "Blue" if rsi >= 58 else "Green"
        return "Yellow" if rsi >= 46 else "Red"
    except Exception:
        return None

def read_sar_state():
    """Return (color, source). file(確定) -> live estimate(推定) -> None(無判定/gray)."""
    for p in [SAR_STATE_PATH, "/mnt/project/sar_state.txt",
              os.path.join(os.path.dirname(CACHE), "sar_state.txt")]:
        if p and os.path.exists(p):
            c = _norm_color(open(p).read())
            if c:
                return c, "file"
    c = _estimate_sar_from_live()
    if c:
        return c, "estimate"
    return None, "none"

# ----------------------------------------------------------------------------- setups (D, all chips)
def build_setups(m):
    up200 = m["close"] > m["sma200"]
    up50  = m["close"] > m["sma50"]
    def names(mask):
        sub = m[mask].sort_values("rs", ascending=False)
        return list(sub.index)
    setups = {}
    setups["押し目"]    = names(up200 & up50 & (m["rs"] >= 70) &
                              ((m["close"]/m["ema21"]-1).abs() <= 0.03))
    setups["ブレイク近"] = names(up50 & (m["rs"] >= 70) & (m["dist52"] >= -0.03))
    setups["出来高急増"] = names(up50 & (m["pchg"] > 0) & (m["volx"] >= 2.0))
    setups["モメンタム"] = names(up50 & (m["rs"] >= 90) & (m["ret21"] >= 0.10))
    setups["ボラ収縮"]  = names(up200 & (m["bbw_pct"] <= 25) & (m["rs"] >= 55))
    setups["深押し"]    = names(up200 & (m["dist52"] <= -0.15) & (m["rs"] >= 50))
    return setups

# ----------------------------------------------------------------------------- portfolio (A)
def build_portfolio(m, s2t):
    # 確定ルール: 63日RSの3期平均(平滑化)上位 × 200MA上 × 週足SAR強気 × 1テーマ最大
    cand = m[(m["close"] > m["sma200"]) & (m["sar_bull"] == True)].copy()
    cand = cand.sort_values("rs_smooth", ascending=False)
    picks = []
    theme_count = {}
    for t, row in cand.iterrows():
        th = theme_of(t, s2t)
        if theme_count.get(th, 0) >= THEME_CAP:
            continue
        picks.append((t, th, row))
        theme_count[th] = theme_count.get(th, 0) + 1
        if len(picks) >= N_PORT:
            break
    return picks, cand

# ----------------------------------------------------------------------------- leaders + ①〜⑤ states
# Canonical state machine + leader filter from v38_auto.py / SETUP_自動更新.md
LEADER_RS = 85                                       # RS percentile >= 85 (= LEADER_RS 0.85)
STATE_DEF = [("②", "新高値圏/継続", "s-go"),
             ("③", "◎押し目（買い）", "s-buy"),
             ("①", "伸び過ぎ（待ち）", "s-wait"),
             ("④", "深押し/ベース", "s-deep"),
             ("⑤", "割れ/様子見", "s-break")]

def tag_state(r):
    """Exact replication of v38_auto.py tag(): ①〜⑤ in priority order."""
    dma50 = r["dma50"]; dma21 = r["dma21"]; pb = r["pb"]; ret5 = r["ret5"]
    if (pd.notna(dma50) and r["close"] < r["sma50"]) or (pd.notna(dma21) and dma21 < -0.06):
        return "⑤"
    if pd.notna(pb) and pb < -0.08:
        return "④"
    if (pd.notna(pb) and -0.08 <= pb <= -0.02 and pd.notna(dma21) and -0.05 <= dma21 <= 0.05
            and pd.notna(ret5) and ret5 > -0.03):
        return "③"
    if pd.notna(dma21) and dma21 > 0.10:
        return "①"
    return "②"

def build_leaders(m, s2i, e2j, s2t):
    """Leaders = RS>=85 & above 200MA, tagged with state ①〜⑤. Returns (by_state, buys)."""
    lead = m[(m["rs"] >= LEADER_RS) & (m["close"] > m["sma200"])].copy()
    if lead.empty:
        return {}, []
    lead["state"] = lead.apply(tag_state, axis=1)
    lead = lead.sort_values("rs", ascending=False)
    def info(t, r):
        th = theme_of(t, s2t)
        ind = s2i.get(t); indja = e2j.get(ind, ind) if ind else "—"
        return dict(t=t, rs=r["rs"], theme=th, ind=indja, pb=r["pb"],
                    dma21=r["dma21"], ret20=r["ret20"], adr=r["adr"], rvol=r["rvol"],
                    close=r["close"], state=r["state"])
    by_state = {}
    for code, _, _ in STATE_DEF:
        sub = lead[lead["state"] == code]
        by_state[code] = [info(t, r) for t, r in sub.iterrows()]
    # 本日◎押し目: state ③ with entry range + +15%/+30% targets (procedure formula)
    buys = []
    for t, r in lead[lead["state"] == "③"].iterrows():
        adr_d = r["close"] * r["adr"]
        lo = max(r["sma21"] - 0.5*adr_d, r["hi40"]*0.92)
        hiR = r["close"]
        if lo >= hiR:
            lo = hiR * 0.985
        mid = (lo + hiR) / 2
        d = info(t, r); d.update(lo=lo, hi=hiR, t15=mid*1.15, t30=mid*1.30)
        buys.append(d)
    return by_state, buys

# ----------------------------------------------------------------------------- sector RS
def build_sector_rs(m, s2i, e2j):
    ind = {}
    for t in m.index:
        nm = s2i.get(t)
        if not nm:
            continue
        low = nm.lower()
        if any(k in low for k in SECTOR_BLACKLIST_KEYS):
            continue
        ind.setdefault(nm, []).append(m.at[t, "rs"])
    recs = []
    for nm, lst in ind.items():
        if len(lst) < 5:                       # >=5 members (was 3) for robustness
            continue
        recs.append(dict(en=nm, ja=e2j.get(nm, nm), n=len(lst),
                         med=float(np.nanmedian(lst))))
    if not recs:
        return []
    df = pd.DataFrame(recs)
    df["score"] = df["med"].rank(pct=True) * 100
    df = df.sort_values("score", ascending=False).reset_index(drop=True)
    return df.to_dict("records")

# equal-weight sector ETF RS — market-representative, unbiased, complete (11 GICS sectors)
SECTOR_ETFS = [("RSPT","情報技術"),("RSPF","金融"),("RSPN","資本財"),("RSPD","一般消費財"),
               ("RSPM","素材"),("RSPC","通信"),("RSPU","公益"),("RSPS","生活必需品"),
               ("RSPH","ヘルスケア"),("RSPR","不動産"),("RSPG","エネルギー")]

def build_sector_etf_rs(macro):
    recs = []
    rets63 = {}
    for tk, ja in SECTOR_ETFS:
        if tk not in macro:
            continue
        c = macro[tk]["Close"].dropna()
        if len(c) < 70:
            continue
        last = float(c.iloc[-1])
        def r(d):
            return (last/float(c.iloc[-d-1])-1) if len(c) > d else np.nan
        rets63[tk] = r(63)
        recs.append(dict(tk=tk, ja=ja, d1=r(1), w1=r(5), m1=r(21), r63=r(63)))
    if not recs:
        return []
    sr = pd.Series({x["tk"]: x["r63"] for x in recs}).rank(pct=True) * 100
    for x in recs:
        x["rs"] = float(sr[x["tk"]])
    recs.sort(key=lambda x: (-(x["r63"] if x["r63"] == x["r63"] else -9)))
    return recs

# ----------------------------------------------------------------------------- breadth + yields
def build_breadth(m):
    n = len(m)
    a200 = (m["close"] > m["sma200"]).sum()
    a50  = (m["close"] > m["sma50"]).sum()
    adv  = (m["pchg"] > 0).sum()
    dec  = (m["pchg"] < 0).sum()
    nh   = (m["dist52"] >= -0.005).sum()
    return dict(n=int(n),
                pa200=100*a200/n, pa50=100*a50/n,
                adv=int(adv), dec=int(dec),
                adpct=100*adv/max(adv+dec,1),
                nh=int(nh), pnh=100*nh/n)

def build_yields(macro):
    out = {}
    for tk, lab in [("^TNX","米10年"), ("^FVX","米5年"), ("^TYX","米30年")]:
        if tk in macro:
            c = macro[tk]["Close"].dropna()
            if len(c) >= 2:
                out[lab] = dict(y=float(c.iloc[-1]), chg=float(c.iloc[-1]-c.iloc[-2]))
    return out

def build_breadth_ts(W, lookback=130):
    """% of universe above its 200-day MA, as a daily time series (S5TH analog)."""
    C = W["Close"]
    sma200 = C.rolling(200, min_periods=150).mean()
    pct = ((C > sma200).sum(axis=1) / C.notna().sum(axis=1) * 100).dropna()
    s = pct.iloc[-lookback:]
    return [(d.strftime("%Y-%m-%d"), float(v)) for d, v in s.items()]

def build_distribution(macro):
    """IBD-style distribution days: down >=0.2% on higher volume than prior day,
    counted over the trailing 25 sessions, for SPY & QQQ."""
    out = {}
    for tk in ["SPY", "QQQ"]:
        if tk not in macro:
            continue
        df = macro[tk].dropna()
        if len(df) < 30:
            continue
        c = df["Close"]; v = df["Volume"]
        dist = (c / c.shift(1) - 1 <= -0.002) & (v > v.shift(1))
        n = int(dist.iloc[-25:].sum())
        if n >= 6:   st, cls = "調整警戒", "bad"
        elif n >= 4: st, cls = "観察",    "warn"
        else:        st, cls = "良好",    "good"
        out[tk] = dict(n=n, st=st, cls=cls)
    return out

def _perf_one(c):
    last = float(c.iloc[-1])
    def ret(d):
        return (last / float(c.iloc[-d-1]) - 1) if len(c) > d else None
    jan = c[c.index.year == c.index[-1].year]
    ytd = (last / float(jan.iloc[0]) - 1) if len(jan) else None
    hi52 = float(c.iloc[-252:].max()); lo52 = float(c.iloc[-252:].min())
    pos = (last - lo52) / (hi52 - lo52) * 100 if hi52 > lo52 else None
    return dict(ytd=ytd, w1=ret(5), m1=ret(21), y1=ret(252), pos52=pos)

def build_perf(macro):
    """Performance strips for S&P500 (SPY) and NASDAQ100 (QQQ) + shared VIX."""
    out = {"indices": [], "vix": None}
    for tk, lab in [("SPY", "S&P500"), ("QQQ", "NASDAQ100")]:
        if tk in macro:
            c = macro[tk]["Close"].dropna()
            if len(c) >= 30:
                d = _perf_one(c); d["label"] = lab
                out["indices"].append(d)
    if "^VIX" in macro:
        v = macro["^VIX"]["Close"].dropna()
        if len(v):
            out["vix"] = float(v.iloc[-1])
    return out

# ----------------------------------------------------------------------------- HTML
def fmt_pct(x, d=1):
    if x is None or (isinstance(x,float) and (np.isnan(x))): return "—"
    return f"{x*100:+.{d}f}%"
def fmt_pct0(x, d=1):
    if x is None or (isinstance(x,float) and (np.isnan(x))): return "—"
    return f"{x*100:.{d}f}%"
def fmt_num(x, d=2):
    if x is None or (isinstance(x,float) and (np.isnan(x))): return "—"
    return f"{x:,.{d}f}"

def _pcls(x):
    if x is None or (isinstance(x,float) and np.isnan(x)): return "mut"
    return "pos" if x >= 0 else "neg"

def _perf_card(p):
    if not p or not p.get("indices"):
        return ""
    blocks = []
    for ix in p["indices"]:
        cells = [("YTD", fmt_pct(ix["ytd"]), _pcls(ix["ytd"])),
                 ("1週", fmt_pct(ix["w1"]), _pcls(ix["w1"])),
                 ("1カ月", fmt_pct(ix["m1"]), _pcls(ix["m1"])),
                 ("1年", fmt_pct(ix["y1"]), _pcls(ix["y1"])),
                 ("52週内位置", (f'{ix["pos52"]:.0f}%' if ix.get("pos52") is not None else "—"), "mut")]
        inner = "".join(f'<div class="c"><div class="k">{k}</div>'
                        f'<div class="v {cl}">{v}</div></div>' for k, v, cl in cells)
        blocks.append(f'<div class="ixn">{ix["label"]}</div><div class="perf">{inner}</div>')
    vix = (f'<div class="perf-vix">VIX <b>{p["vix"]:.1f}</b></div>'
           if p.get("vix") is not None else "")
    return (f'<div class="card"><h2>マーケット・パフォーマンス</h2>'
            + "".join(blocks) + vix + '</div>')

def _dd_card(dd):
    if not dd:
        return ""
    boxes = "".join(
        f'<div class="box"><div class="t">{tk}</div>'
        f'<div class="num">{d["n"]}</div>'
        f'<span class="st st-{d["cls"]}">{d["st"]}</span></div>'
        for tk, d in dd.items())
    return (f'<div class="card"><h2>ディストリビューション・デイ（直近25営業日）</h2>'
            f'<div class="sub">前日比 −0.2%以下かつ出来高が前日超の「売り抜け日」。6本以上で調整警戒</div>'
            f'<div class="dd">{boxes}</div></div>')

def _market_comment(aux, mkt, sar):
    """Auto-generated daily market read (shareable / draws repeat visits)."""
    band = mri_band(aux["cur"])[0].replace("（過熱・反落注意⚠）", "（過熱気味）")
    slope = {"↑": "上向き", "→": "横ばい", "↓": "鈍化"}.get(aux["slope"], aux["slope"])
    trend = SAR_JUDGMENT.get(sar[0], ("", "判定不可"))[1] if sar[0] else "判定不可"
    dd = mkt.get("distrib", {})
    parts = [f"地合いは<b>{band}</b>（MRI {aux['cur']:.0f}／傾き{slope}）",
             f"トレンド判定は<b>{trend}</b>"]
    warn = [k for k, v in dd.items() if v["n"] >= 6]
    if warn:
        parts.append(f"{'・'.join(warn)}に売り抜け日が積み上がり短期は調整警戒")
    elif aux["bear_n"] >= 6:
        parts.append("内部はやや弱含み")
    else:
        parts.append("内部の崩れは限定的")
    txt = "。".join(parts) + "。"
    return (f'<div class="card cmt"><h2>今日のマーケット</h2>'
            f'<div class="cmt-b">{txt}</div></div>')

def _buy_card(buys):
    if not buys:
        return ('<div class="card"><h2>本日◎押し目（③・買い候補）</h2>'
                '<div class="empty">本日の③該当なし</div></div>')
    rows = []
    for b in buys:
        rows.append(
            f'<div class="buy">'
            f'<div class="buy-h"><span class="tk">{b["t"]}</span>'
            f'<span class="rs">RS {b["rs"]:.0f}</span></div>'
            f'<div class="buy-m">{b["theme"]} ・ {b["ind"]}</div>'
            f'<div class="buy-g">'
            f'<div><span class="k">エントリー</span><span class="v">${b["lo"]:.2f}〜${b["hi"]:.2f}</span></div>'
            f'<div><span class="k">+15%目標</span><span class="v pos">${b["t15"]:.2f}</span></div>'
            f'<div><span class="k">+30%目標</span><span class="v pos">${b["t30"]:.2f}</span></div>'
            f'<div><span class="k">押し目</span><span class="v">{fmt_pct(b["pb"])}</span></div>'
            f'<div><span class="k">ADR</span><span class="v">{fmt_pct0(b["adr"])}</span></div>'
            f'<div><span class="k">RVOL</span><span class="v">{b["rvol"]:.1f}</span></div>'
            f'</div></div>')
    return (f'<div class="card"><div class="hdr"><h2>本日◎押し目（③・買い候補）</h2>'
            f'{_cp([b["t"] for b in buys])}</div>'
            f'<div class="sub">状態③のリーダーのみ・エントリーレンジと+15%/+30%目標（{len(buys)}銘柄）</div>'
            + "".join(rows) + '</div>')

def _leaders_card(by_state):
    total = sum(len(v) for v in by_state.values())
    all_tk = [x["t"] for code, _, _ in STATE_DEF for x in by_state.get(code, [])]
    secs = []
    for code, label, cls in STATE_DEF:
        lst = by_state.get(code, [])
        ticks = [x["t"] for x in lst]
        shown = lst[:CHIP_CAP]
        extra = len(lst) - len(shown)
        chips = "".join(f'<span class="chip {cls}">{x["t"]}</span>' for x in shown)
        more = f'<span class="more">+{extra}件</span>' if extra > 0 else ""
        secs.append(
            f'<div class="setup-h"><span class="nm">{code} {label}</span>'
            f'<span style="display:flex;gap:6px;align-items:center">{_cp(ticks)}'
            f'<span class="ct">{len(lst)}銘柄</span></span></div>'
            f'<div class="chips">{chips or "<span class=empty>なし</span>"}{more}</div>')
    return (f'<div class="card"><div class="hdr"><h2>リーダー監視（RS≥85・200MA上）</h2>{_cp(all_tk)}</div>'
            f'<div class="sub">高RSリーダーを状態①〜⑤で色分け（計{total}銘柄）。'
            f'③押し目買い／②継続／①伸び過ぎ待ち／④深押し／⑤様子見</div>'
            + "".join(secs) + '</div>')

CSS = r"""
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue',sans-serif;background:#0b0f17;color:#e6edf3;font-size:14px;-webkit-text-size-adjust:100%}
.wrap{max-width:680px;margin:0 auto;padding:0 12px 60px}
header{padding:14px 4px 8px}
h1{font-size:17px;font-weight:700;letter-spacing:.02em}
.asof{color:#7d8da1;font-size:11px;margin-top:2px}
.banner{border-radius:14px;padding:14px 16px;margin:10px 0 4px;border:1px solid rgba(255,255,255,.06)}
.banner .lab{font-size:12px;color:#cbd5e1;opacity:.85}
.banner .val{font-size:30px;font-weight:800;line-height:1.1;margin:2px 0}
.banner .st{font-size:13px;font-weight:700}
.b-ovh{background:linear-gradient(135deg,#14532d,#166534)}
.b-bull{background:linear-gradient(135deg,#14532d,#15803d)}
.b-neu{background:linear-gradient(135deg,#713f12,#a16207)}
.b-weak{background:linear-gradient(135deg,#7c2d12,#9a3412)}
.b-bear{background:linear-gradient(135deg,#7f1d1d,#991b1b)}
.gauge{height:10px;border-radius:6px;margin:10px 0 4px;background:linear-gradient(90deg,#991b1b 0%,#9a3412 30%,#a16207 45%,#15803d 60%,#166534 100%);position:relative}
.gauge .mk{position:absolute;top:-4px;width:3px;height:18px;background:#fff;border-radius:2px;box-shadow:0 0 4px rgba(0,0,0,.6)}
.aux{display:flex;gap:8px;margin-top:8px;flex-wrap:wrap}
.aux .a{background:rgba(0,0,0,.22);border-radius:8px;padding:5px 9px;font-size:11px}
.aux .a b{font-size:13px}
/* NQ-SAR signal pill (leverage sleeve; logic hidden) */
.sar{border-radius:14px;padding:12px 16px;margin:10px 0 4px;border:1px solid rgba(255,255,255,.10);
     display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}
.sar .lhs{display:flex;align-items:center;gap:11px}
.sar .dot{width:16px;height:16px;border-radius:50%;box-shadow:0 0 0 3px rgba(255,255,255,.15),0 0 10px rgba(0,0,0,.4);flex:0 0 auto}
.sar .lab{font-size:11px;color:#dbe4ef;opacity:.9;letter-spacing:.04em}
.sar .col{font-size:22px;font-weight:800;line-height:1.05}
.sar .rhs{text-align:right}
.sar .jud{font-size:20px;font-weight:800;line-height:1.05}
.sar .lot{font-size:11px;opacity:.92;margin-top:2px}
.sar-blue{background:linear-gradient(135deg,#0b2a6b,#1d4ed8)}   .sar-blue .dot{background:#60a5fa}
.sar-green{background:linear-gradient(135deg,#14532d,#16a34a)}  .sar-green .dot{background:#4ade80}
.sar-yellow{background:linear-gradient(135deg,#713f12,#ca8a04)} .sar-yellow .dot{background:#facc15}
.sar-red{background:linear-gradient(135deg,#7f1d1d,#dc2626)}    .sar-red .dot{background:#f87171}
.sar-gray{background:linear-gradient(135deg,#374151,#4b5563)}   .sar-gray .dot{background:#9ca3af}
.sar-badge{display:inline-block;font-size:10px;font-weight:800;border-radius:6px;padding:1px 6px;margin-left:6px;vertical-align:middle}
.sar-badge.ok{background:rgba(255,255,255,.18);color:#dffbe8}
.sar-badge.est{background:#a16207;color:#fde68a}
.sar-badge.none{background:#1f2937;color:#cbd5e1}
/* distribution-day + performance widgets */
.dd{display:flex;gap:10px;flex-wrap:wrap}
.dd .box{flex:1 1 120px;background:#0b1220;border:1px solid #1c2533;border-radius:10px;padding:10px 12px}
.dd .box .t{font-size:12px;color:#9fb0c5;font-weight:700}
.dd .box .num{font-size:26px;font-weight:800;line-height:1.1;margin:2px 0}
.dd .st{display:inline-block;font-size:11px;font-weight:700;padding:2px 8px;border-radius:7px}
.st-good{background:#14532d;color:#86efac}.st-warn{background:#713f12;color:#fde68a}.st-bad{background:#7f1d1d;color:#fca5a5}
.perf{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}
.ixn{font-size:13px;font-weight:800;color:#9ecbff;margin:10px 0 6px}
.ixn:first-child{margin-top:0}
.perf-vix{margin-top:10px;font-size:13px;color:#9fb0c5}
.perf-vix b{font-size:16px;color:#e6edf3}
.perf .c{background:#0b1220;border:1px solid #1c2533;border-radius:10px;padding:8px 10px;text-align:center}
.perf .c .k{font-size:11px;color:#7d8da1}.perf .c .v{font-size:16px;font-weight:800;margin-top:2px}
nav{position:sticky;top:0;z-index:9;background:#0b0f17;display:flex;gap:6px;overflow-x:auto;padding:8px 0;border-bottom:1px solid #1c2533}
nav button{flex:0 0 auto;background:#141b29;color:#9fb0c5;border:1px solid #1f2a3a;border-radius:18px;padding:7px 14px;font-size:13px;font-weight:600}
nav button.on{background:#1f6feb;color:#fff;border-color:#1f6feb}
section{display:none;padding-top:12px}
section.on{display:block}
.card{background:#0f1623;border:1px solid #1c2533;border-radius:12px;padding:12px 14px;margin-bottom:12px}
.card h2{font-size:14px;font-weight:700;margin-bottom:8px;color:#e6edf3}
.card .sub{font-size:11px;color:#7d8da1;margin:-4px 0 8px}
.setup-h{display:flex;justify-content:space-between;align-items:baseline;margin:10px 0 6px}
.setup-h .nm{font-size:13px;font-weight:700}
.setup-h .ct{font-size:11px;color:#7d8da1}
.chips{display:flex;flex-wrap:wrap;gap:6px}
.chip{background:#162132;border:1px solid #243349;border-radius:7px;padding:4px 8px;font-size:12px;font-weight:600;color:#cfe0f5}
.chip.hot{border-color:#2f81f7;color:#9ecbff}
.chip.ov{border-color:#a16207;color:#fde68a;background:#2a210a}
.chip.ov .b{display:inline-block;margin-left:5px;background:#a16207;color:#0b0f17;font-size:10px;font-weight:800;border-radius:5px;padding:0 5px}
/* ①〜⑤ state chips */
.chip.s-buy{background:#0f3d1f;border-color:#1f9d4d;color:#7ff0a8}
.chip.s-go{background:#10331f;border-color:#1f7a45;color:#86efac}
.chip.s-wait{background:#33290a;border-color:#a16207;color:#fde68a}
.chip.s-deep{background:#3a210f;border-color:#c2660b;color:#fdba74}
.chip.s-break{background:#33161a;border-color:#a13030;color:#fca5a5}
/* 本日◎押し目 buy cards */
.buy{background:#0c1a12;border:1px solid #1f6d3c;border-radius:11px;padding:11px 13px;margin-bottom:9px}
.buy-h{display:flex;justify-content:space-between;align-items:baseline}
.buy-h .tk{font-size:18px;font-weight:800;color:#9ff0bb}
.buy-h .rs{font-size:12px;font-weight:700;color:#7d8da1}
.buy-m{font-size:11px;color:#9fb0c5;margin:2px 0 8px}
.buy-g{display:grid;grid-template-columns:repeat(3,1fr);gap:7px}
.buy-g>div{background:rgba(0,0,0,.25);border-radius:7px;padding:5px 7px}
.buy-g .k{display:block;font-size:10px;color:#7d8da1}
.buy-g .v{font-size:13px;font-weight:700}
.cmt{background:linear-gradient(135deg,#0f1b2e,#10233b);border-color:#26415f}
.cmt-b{font-size:14px;line-height:1.65;color:#e6edf3}
.cmt-b b{color:#9ecbff}
.chart{margin-top:4px}
.chart svg{width:100%;height:auto;display:block}
.chart .cap{display:flex;justify-content:space-between;font-size:11px;color:#7d8da1;margin-top:4px}
.empty{color:#5b6b80;font-size:12px;font-style:italic}
.more{display:inline-block;color:#7d8da1;font-size:11px;font-weight:700;padding:4px 2px;vertical-align:middle}
/* copy buttons */
.cp{background:#16263a;border:1px solid #2f4a6a;border-radius:7px;color:#9ecbff;font-size:11px;
    font-weight:700;padding:3px 9px;cursor:pointer}
.cp .n{opacity:.6;font-weight:600}
.cp.done{background:#0f3d1f;border-color:#1f9d4d;color:#7ff0a8}
.hdr{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:6px}
.hdr h2{margin:0}
table{width:100%;border-collapse:collapse;font-size:12.5px}
th,td{text-align:right;padding:6px 4px;border-bottom:1px solid #18212f}
th{color:#8595aa;font-weight:600;font-size:11px}
td.l,th.l{text-align:left}
.tk{font-weight:700;color:#e6edf3}
.pos{color:#4ade80}.neg{color:#f87171}.mut{color:#8595aa}
.bar{height:6px;border-radius:4px;background:#16202e;overflow:hidden;min-width:54px;display:inline-block;vertical-align:middle}
.bar i{display:block;height:100%;background:#2f81f7}
.alloc{display:flex;height:30px;border-radius:8px;overflow:hidden;margin:6px 0}
.alloc div{display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;color:#fff}
.a-ind{background:#1f6feb}.a-lev{background:#8957e5}.a-cash{background:#3d4858}
.note{font-size:11px;color:#7d8da1;line-height:1.5;margin-top:6px}
.kv{display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid #18212f;font-size:12.5px}
.kv .k{color:#9fb0c5}.kv .v{font-weight:700}
ul.rules{font-size:12.5px;line-height:1.7;padding-left:18px;color:#cbd5e1}
ul.rules li{margin-bottom:4px}
.rh{font-size:13px;font-weight:800;color:#9ecbff;margin:14px 0 4px}
.nqt{margin:6px 0 2px}
.nqt th,.nqt td{text-align:center}
.nqt td.l,.nqt th.l{text-align:left}
.nqt tr.hl{background:rgba(56,161,105,.14)}
.nqt tr.hl td{font-weight:800;color:#e6edf3}
.nqd{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px;vertical-align:middle}
.nqd.c-bl{background:#3b82f6}.nqd.c-gr{background:#22c55e}
.nqd.c-yl{background:#eab308}.nqd.c-rd{background:#ef4444}
.warn{background:#1a1206;border:1px solid #5c4410;border-radius:8px;padding:8px 10px;font-size:11.5px;color:#d6b56a;margin-top:8px}
"""

JS = r"""
function tab(id,btn){
  document.querySelectorAll('section').forEach(s=>s.classList.remove('on'));
  document.querySelectorAll('nav button').forEach(b=>b.classList.remove('on'));
  document.getElementById(id).classList.add('on');
  btn.classList.add('on');
  window.scrollTo(0,0);
}
function copyTk(b){
  var t=b.getAttribute('data-tk')||'';
  navigator.clipboard.writeText(t).then(function(){
    var o=b.textContent; b.textContent='✓ コピー済'; b.classList.add('done');
    setTimeout(function(){b.textContent=o; b.classList.remove('done');},1200);
  });
}
"""

def _cp(tickers):
    """Copy button for a list of tickers (comma-separated to clipboard)."""
    if not tickers:
        return ""
    data = ",".join(tickers)
    return (f'<button class="cp" data-tk="{data}" onclick="copyTk(this)">'
            f'コピー <span class="n">{len(tickers)}</span></button>')

def color_pct(x):
    if x is None or (isinstance(x,float) and np.isnan(x)): return "mut"
    return "pos" if x > 0 else ("neg" if x < 0 else "mut")

def _svg_inner(ys, accent, gid, gridvals, suffix, lo_pad=4, hi_pad=4, ymin=0, ymax=100):
    """Return inner SVG (area+line) for a value series."""
    n = len(ys)
    Wd, Ht, pad = 680, 180, 6
    lo, hi = min(ys), max(ys)
    lo = max(ymin, lo - lo_pad); hi = min(ymax, hi + hi_pad)
    rng = (hi - lo) or 1
    def X(i): return pad + i * (Wd - 2*pad) / (n - 1)
    def Y(v): return pad + (1 - (v - lo)/rng) * (Ht - 2*pad)
    pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(ys))
    area = (f"M{X(0):.1f},{Y(ys[0]):.1f} "
            + " ".join(f"L{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(ys))
            + f" L{X(n-1):.1f},{Ht-pad:.1f} L{X(0):.1f},{Ht-pad:.1f} Z")
    gl = "".join(f'<line x1="{pad}" y1="{Y(g):.1f}" x2="{Wd-pad}" y2="{Y(g):.1f}" '
                 f'stroke="#1c2533" stroke-width="1"/>'
                 f'<text x="{Wd-pad}" y="{Y(g)-2:.1f}" fill="#5b6b80" font-size="9" '
                 f'text-anchor="end">{g}{suffix}</text>'
                 for g in gridvals if lo <= g <= hi)
    return (f'<svg viewBox="0 0 {Wd} {Ht}" preserveAspectRatio="none">'
            f'<defs><linearGradient id="{gid}" x1="0" y1="0" x2="0" y2="1">'
            f'<stop offset="0" stop-color="{accent}" stop-opacity="0.35"/>'
            f'<stop offset="1" stop-color="{accent}" stop-opacity="0"/></linearGradient></defs>'
            f'{gl}<path d="{area}" fill="url(#{gid})"/>'
            f'<polyline points="{pts}" fill="none" stroke="{accent}" stroke-width="2"/>'
            f'<circle cx="{X(n-1):.1f}" cy="{Y(ys[-1]):.1f}" r="3.5" fill="{accent}"/></svg>')

def _svg_breadth(ts, n_uni=None):
    """Breadth time series (S5TH analog)."""
    if not ts or len(ts) < 5:
        return ""
    ys = [v for _, v in ts]; last = ys[-1]
    svg = _svg_inner(ys, "#58a6ff", "bg", [20,40,50,60,80], "%")
    uni_txt = f"約{round(n_uni,-1):,.0f}銘柄" if n_uni else "ユニバース"
    return (f'<div class="card"><h2>ブレッドス推移（200日線上の割合）</h2>'
            f'<div class="sub">ユニバース{uni_txt}のうち200日移動平均を上回る割合・直近約6カ月</div>'
            f'<div class="chart">{svg}'
            f'<div class="cap"><span>{ts[0][0]}</span>'
            f'<span style="color:#9ecbff;font-weight:700">現在 {last:.0f}%</span>'
            f'<span>{ts[-1][0]}</span></div></div></div>')

def _svg_mri(ts):
    """MRI (market status) time series, ~6 months."""
    if not ts or len(ts) < 5:
        return ""
    ys = [v for _, v in ts]; last = ys[-1]
    band_lab = mri_band(last)[0].replace("（過熱・反落注意⚠）", "")
    svg = _svg_inner(ys, "#34d399", "mg", [30,45,60,75], "")
    return (f'<div class="card"><h2>マーケットステータス推移（MRI）</h2>'
            f'<div class="sub">地合いスコアの推移・直近約6カ月（75強気/60中立/45弱含み/30弱気）</div>'
            f'<div class="chart">{svg}'
            f'<div class="cap"><span>{ts[0][0]}</span>'
            f'<span style="color:#7ff0a8;font-weight:700">現在 {last:.0f}（{band_lab}）</span>'
            f'<span>{ts[-1][0]}</span></div></div></div>')

def _sector_etf_table(secs):
    if not secs:
        return ""
    rows = []
    for i, s in enumerate(secs, 1):
        rows.append(
            f'<tr><td class="l mut">{i}</td>'
            f'<td class="l tk" style="font-size:12px">{s["ja"]}'
            f'<span class="mut" style="font-size:10px"> {s["tk"]}</span></td>'
            f'<td>{s["rs"]:.0f}</td>'
            f'<td class="{color_pct(s["d1"])}">{fmt_pct(s["d1"])}</td>'
            f'<td class="{color_pct(s["w1"])}">{fmt_pct(s["w1"])}</td>'
            f'<td class="{color_pct(s["m1"])}">{fmt_pct(s["m1"])}</td></tr>')
    return (f'<div class="card"><h2>セクター（等ウェイトETF・市場代表）</h2>'
            f'<div class="sub">S&amp;P11セクターを等ウェイトETF（RSPx系）で評価・偏りなく全セクター網羅・強い順</div>'
            f'<table><tr><th class="l">#</th><th class="l">セクター</th><th>RS</th>'
            f'<th>日</th><th>週</th><th>月</th></tr>'
            + "".join(rows) + '</table></div>')

def render(names, m, mri, breakdown, dropped, aux, setups, picks, cand,
           sectors, breadth, yields, asof, sar, mkt, leaders):
    band_lab, band_cls = mri_band(aux["cur"])
    mk = max(0, min(100, aux["cur"]))
    # ---- トレンド判定 pill (file=確定 / live=推定 / none=無判定グレー). logic hidden
    sar_color, sar_src = sar
    if sar_color is None:                       # everything failed -> gray no-judgment
        s_lab, s_jud, s_lot, s_cls = "—", "判定不可", "データ取得不可", "sar-gray"
    else:
        s_lab, s_jud, s_lot, s_cls = SAR_JUDGMENT.get(sar_color, SAR_JUDGMENT["Blue"])
    if sar_src == "file":
        badge = '<span class="sar-badge ok">確定</span>'
    elif sar_src == "estimate":
        badge = '<span class="sar-badge est">推定</span>'
        if sar_color in ("Yellow", "Red"):      # weak-side estimate is unreliable
            s_lot = "推定・要TradingView確認"
    else:
        badge = '<span class="sar-badge none">無判定</span>'
    sar_pill = f"""
    <div class="sar {s_cls}">
      <div class="lhs">
        <span class="dot"></span>
        <div>
          <div class="lab">トレンド判定 {badge}</div>
          <div class="col">{s_lab}</div>
        </div>
      </div>
      <div class="rhs">
        <div class="jud">{s_jud}</div>
        <div class="lot">{s_lot}</div>
      </div>
    </div>"""
    # ---- MRI banner
    drop_note = ""
    if dropped:
        drop_note = f'<div class="note">注記：データ未取得のため除外し残り指標で100点満点に再正規化 → {", ".join(dropped)}</div>'
    banner = sar_pill + f"""
    <div class="banner b-{band_cls}">
      <div class="lab">マーケットステータス（MRI 地合いスコア）</div>
      <div class="val">{aux['cur']:.0f}<span style="font-size:15px;font-weight:600">/100</span></div>
      <div class="st">{band_lab}</div>
      <div class="gauge"><div class="mk" style="left:{mk}%"></div></div>
      <div class="aux">
        <div class="a">傾き <b>{aux['slope']}</b></div>
        <div class="a">ベア警戒 <b>{aux['bear_n']}</b>/12</div>
        <div class="a">ピーク低下 <b>{aux['peak']}</b></div>
      </div>
      {drop_note}
    </div>"""

    # ---- TAB 今日 — procedure-aligned (本日◎押し目 ③ + リーダー監視 ①〜⑤)
    comment = _market_comment(aux, mkt, sar)
    by_state, buys = leaders
    buy_card = _buy_card(buys)
    leaders_card = _leaders_card(by_state)
    # new 52w-high breakouts (popular draw / 集客)
    nh = m[(m["dist52"] >= -0.005)].sort_values("rs", ascending=False)
    nh_list = list(nh.index)
    nh_chips = "".join(
        f'<span class="chip{" hot" if m.at[t,"rs"]>=90 else ""}">{t}</span>' for t in nh_list)
    newhigh_card = (
        f'<div class="card"><div class="hdr"><h2>本日の新高値圏</h2>{_cp(nh_list)}</div>'
        f'<div class="sub">52週高値まで0.5%以内・RS順（{len(nh_list)}銘柄）</div>'
        f'<div class="chips">{nh_chips or "<span class=empty>該当なし</span>"}</div></div>')
    today = comment + buy_card + leaders_card + newhigh_card

    # ---- TAB ポートフォリオ
    per = ALLOC[0] / N_PORT
    rows = []
    for t, th, r in picks:
        rows.append(
            f'<tr><td class="l tk">{t}</td>'
            f'<td class="l mut" style="font-size:11px">{th}</td>'
            f'<td>{r["rs"]:.0f}</td>'
            f'<td class="{color_pct(r["pchg"])}">{fmt_pct(r["pchg"])}</td>'
            f'<td class="{color_pct(r["vs200"])}">{fmt_pct(r["vs200"])}</td>'
            f'<td class="mut">{per:.2f}%</td></tr>')
    alloc_bar = (f'<div class="alloc">'
                 f'<div class="a-ind" style="width:{ALLOC[0]}%">個別 {ALLOC[0]}</div>'
                 f'<div class="a-lev" style="width:{ALLOC[1]}%">レバ {ALLOC[1]}</div>'
                 f'<div class="a-cash" style="width:{ALLOC[2]}%">現金 {ALLOC[2]}</div></div>')
    port = (f'<div class="card"><h2>ポートフォリオ（個別株スリーブ）</h2>'
            f'<div class="sub">N={N_PORT}・③週足SARフィルタ・サブ期間頑健性検証済み</div>'
            + alloc_bar +
            f'<div class="note">配分：個別 {ALLOC[0]} / レバ {ALLOC[1]} / 現金 {ALLOC[2]}（本命）。'
            f'保守的代替 {ALLOC_ALT[0]}/{ALLOC_ALT[1]}/{ALLOC_ALT[2]}。レバ枠はTradingView側で運用。</div>'
            f'<table><tr><th class="l">銘柄</th><th class="l">テーマ</th><th>RS</th>'
            f'<th>前日比</th><th>200MA乖離</th><th>配分</th></tr>'
            + "".join(rows) + '</table>'
            f'<div class="note">選定：63日RS上位 × 200MA上 × 週足SAR非弱気 × 1テーマ最大{THEME_CAP}。'
            f'損切りなし／月次RS入替／利確ラダー0.25-0.25-0.50。</div></div>')

    # ---- TAB ウォッチ — watchlist: 複数ヒット overlap + セットアップ別 + RSリーダー控え
    from collections import Counter
    memb = Counter(); where = {}
    for nm, lst in setups.items():
        for t in lst:
            memb[t] += 1; where.setdefault(t, []).append(nm)
    multi = sorted([(t, c) for t, c in memb.items() if c >= 3],
                   key=lambda x: (-x[1], -(float(m.at[x[0], "rs"]) if x[0] in m.index else 0)))
    multi_tk = [t for t, _ in multi]
    ov_chips = "".join(
        f'<span class="chip ov" title="{"・".join(where[t])}">{t}'
        f'<span class="b">×{c}</span></span>' for t, c in multi)
    overlap_card = (
        f'<div class="card"><div class="hdr"><h2>複数ヒット（3つ以上のステータス）</h2>{_cp(multi_tk)}</div>'
        f'<div class="sub">3つ以上のセットアップに同時該当した高確度銘柄・ヒット数順（{len(multi)}銘柄）</div>'
        f'<div class="chips">{ov_chips or "<span class=empty>該当なし</span>"}</div></div>')
    setup_html = []
    for nm, lst in setups.items():
        shown = lst[:CHIP_CAP]                   # top N by RS (already RS-sorted)
        extra = len(lst) - len(shown)
        chips = "".join(
            f'<span class="chip{" hot" if (m.at[t,"rs"]>=90) else ""}">{t}</span>' for t in shown)
        more = f'<span class="more">+{extra}件</span>' if extra > 0 else ""
        setup_html.append(
            f'<div class="setup-h"><span class="nm">{nm}</span>'
            f'<span style="display:flex;gap:6px;align-items:center">{_cp(lst)}'
            f'<span class="ct">{len(lst)}</span></span></div>'
            f'<div class="chips">{chips or "<span class=empty>なし</span>"}{more}</div>')
    setup_card = (f'<div class="card"><h2>セットアップ別</h2>'
                  f'<div class="sub">押し目/ブレイク近/出来高急増/モメンタム/ボラ収縮/深押し ・各RS上位{CHIP_CAP}件</div>'
                  + "".join(setup_html) + '</div>')
    deck = cand.iloc[N_PORT:N_PORT+25]
    wrows = []
    for rank, (t, r) in enumerate(deck.iterrows(), start=N_PORT+1):
        wrows.append(
            f'<tr><td class="l mut">{rank}</td><td class="l tk">{t}</td>'
            f'<td>{r["rs"]:.0f}</td>'
            f'<td class="{color_pct(r["pchg"])}">{fmt_pct(r["pchg"])}</td>'
            f'<td class="{color_pct(r["ret63"])}">{fmt_pct(r["ret63"])}</td>'
            f'<td class="{color_pct(r["dist52"])}">{fmt_pct(r["dist52"])}</td></tr>')
    deck_card = (f'<div class="card"><div class="hdr"><h2>RSリーダー控え</h2>{_cp(list(deck.index))}</div>'
             f'<div class="sub">候補プールの{N_PORT+1}位以降（200MA上×週足SAR非弱気）</div>'
             f'<table><tr><th class="l">#</th><th class="l">銘柄</th><th>RS</th>'
             f'<th>前日比</th><th>63日</th><th>52週高値差</th></tr>'
             + "".join(wrows) + '</table></div>')
    watch = overlap_card + setup_card + deck_card

    # ---- TAB 業種RS
    srows = []
    for i, s in enumerate(sectors, 1):
        w = max(2, min(100, s["score"]))
        srows.append(
            f'<tr><td class="l mut">{i}</td>'
            f'<td class="l tk" style="font-size:12px">{s["ja"]}</td>'
            f'<td class="mut">{s["n"]}</td>'
            f'<td>{s["score"]:.0f}</td>'
            f'<td class="l"><span class="bar"><i style="width:{w}%"></i></span></td></tr>')
    sector = (_sector_etf_table(mkt.get("sector_etf", []))
              + f'<div class="card"><h2>業種RS（ユニバース内）</h2>'
              f'<div class="sub">構成銘柄RSパーセンタイル中央値を業種間で0-100ランク（≥5社）・上から強い順。'
              f'上のセクター表が市場全体の代表、こちらは保有候補プール内の相対強弱</div>'
              f'<table><tr><th class="l">#</th><th class="l">業種</th><th>社数</th>'
              f'<th>RS</th><th class="l">強さ</th></tr>'
              + "".join(srows) + '</table></div>')

    # ---- TAB マーケット
    grp_ja = {"trend":"トレンド","vol":"ボラティリティ","credit":"信用","breadth":"ブレッドス"}
    grp_rows = {}
    for b in breakdown:
        grp_rows.setdefault(b["group"], []).append(b)
    keyja = {"qqq_50":"QQQ vs50MA","qqq_200":"QQQ vs200MA","spy_50":"SPY vs50MA",
             "spy_200":"SPY vs200MA","vix":"VIX水準","vix_ratio":"VIX/VIX3M","vvix":"VVIX",
             "hyglqd_20":"HYG/LQD vs20MA","hyglqd_5d":"HYG/LQD 5日","rsp_spy_20":"RSP/SPY vs20MA",
             "iwm_spy_20":"IWM/SPY vs20MA"}
    mri_rows = []
    for g in ["trend","vol","credit","breadth"]:
        if g not in grp_rows: continue
        gp = sum(x["pts"] for x in grp_rows[g]); gm = sum(x["ptsmax"] for x in grp_rows[g])
        mri_rows.append(f'<tr><td class="l" style="color:#9ecbff;font-weight:700">{grp_ja[g]}</td>'
                        f'<td colspan="2"></td><td style="color:#9ecbff;font-weight:700">{gp:.0f}/{gm}</td></tr>')
        for x in grp_rows[g]:
            w = 100*x["frac"]
            mri_rows.append(
                f'<tr><td class="l mut" style="padding-left:12px">{keyja.get(x["key"],x["key"])}</td>'
                f'<td class="mut">{fmt_num(x["raw"],3)}</td>'
                f'<td class="l"><span class="bar"><i style="width:{w:.0f}%"></i></span></td>'
                f'<td>{x["pts"]:.1f}/{x["ptsmax"]}</td></tr>')
    ycards = "".join(
        f'<div class="kv"><span class="k">{lab}</span>'
        f'<span class="v">{d["y"]:.2f}% '
        f'<span class="{ "pos" if d["chg"]>=0 else "neg"}" style="font-size:11px">'
        f'{d["chg"]:+.2f}</span></span></div>'
        for lab, d in yields.items())
    market = (_svg_mri(mkt.get("mri_ts", []))
              + _perf_card(mkt.get("perf", {}))
              + _dd_card(mkt.get("distrib", {}))
              + _svg_breadth(mkt.get("breadth_ts", []), breadth["n"])
              + f'<div class="card"><h2>金利</h2>{ycards}</div>'
              f'<div class="card"><h2>広域ブレッドス</h2>'
              f'<div class="kv"><span class="k">200MA上</span><span class="v">{breadth["pa200"]:.0f}% '
              f'<span class="mut" style="font-size:11px">({breadth["n"]}銘柄中)</span></span></div>'
              f'<div class="kv"><span class="k">50MA上</span><span class="v">{breadth["pa50"]:.0f}%</span></div>'
              f'<div class="kv"><span class="k">上昇/下落</span><span class="v">{breadth["adv"]} / {breadth["dec"]} '
              f'<span class="mut" style="font-size:11px">({breadth["adpct"]:.0f}% up)</span></span></div>'
              f'<div class="kv"><span class="k">52週高値圏</span><span class="v">{breadth["nh"]} '
              f'<span class="mut" style="font-size:11px">({breadth["pnh"]:.1f}%)</span></span></div></div>')

    # ---- TAB ルール (確定版 2026-06-24)
    cur_jp = {"Blue": "青", "Green": "緑", "Yellow": "黄", "Red": "赤"}.get(sar[0])
    exp_rows = [("青", "c-bl", "100%", "100%"), ("緑", "c-gr", "50%", "50%"),
                ("黄", "c-yl", "50%", "0%（撤退）"), ("赤", "c-rd", "0%（全現金）", "0%（全撤退）")]
    nq_rows = ""
    for cj, cls, indv, lev in exp_rows:
        hl = ' class="hl"' if cj == cur_jp else ""
        nq_rows += (f'<tr{hl}><td class="l"><span class="nqd {cls}"></span>{cj}'
                    f'{"（現在）" if cj == cur_jp else ""}</td><td>{indv}</td><td>{lev}</td></tr>')
    cur_line = ""
    if cur_jp:
        em = {"青": ("100%", "100%"), "緑": ("50%", "50%"),
              "黄": ("50%", "0%"), "赤": ("0%", "0%")}[cur_jp]
        cur_line = (f'<div class="sub" style="margin-top:8px">現在の地合い：<b style="color:#e6edf3">{cur_jp}</b>'
                    f' → 個別 {em[0]} ／ レバ {em[1]}</div>')
    rules = (
        f'<div class="card"><h2>システムルール（確定版 2026-06-24）</h2>'
        f'<div class="sub">配分：個別 <b>{ALLOC[0]}</b> ／ レバ <b>{ALLOC[1]}</b> ／ 現金 <b>{ALLOC[2]}</b>'
        f'（{ALLOC_ALT[0]}/{ALLOC_ALT[1]}/{ALLOC_ALT[2]}も可）</div>'
        f'<div class="rh">最重要：NQ 4色で露出をスケール（全体の土台）</div>'
        f'<div class="sub">毎日トレンド判定の色を確認。色が変わったら翌日の寄りで各スリーブの露出を下表に合わせる（前日終値で確定）。</div>'
        f'<table class="nqt"><tr><th class="l">色</th><th>個別株スリーブ</th><th>レバ(TQQQ/SOXL)</th></tr>{nq_rows}</table>'
        + cur_line +
        f'<div class="rh">個別株スリーブ（{ALLOC[0]}%枠）</div>'
        f'<ul class="rules">'
        f'<li><b>選定（月初に1回）</b>：63日RSの<b>3期平均（平滑化）</b>で上位{N_PORT} × 200日線上 × 週足SAR強気 × 1テーマ最大{THEME_CAP}・各1/{N_PORT}均等（瞬間値で順位付けしない）</li>'
        f'<li><b>入替</b>：毎月フル入替（上位{N_PORT}から外れたら売る・粘らない）</li>'
        f'<li><b>利確/損切</b>：利確ラダー無し・通常損切り無し（勝ちは伸ばす／下落はNQ赤で守る）</li>'
        f'<li><b>唯一の能動的例外</b>：個別の暴落保険＝建値<b>−30%</b>で その銘柄だけ現金化（月初まで戻さない／レバには置かない）</li>'
        f'</ul>'
        f'<div class="rh">レバレッジスリーブ（{ALLOC[1]}%枠）</div>'
        f'<ul class="rules">'
        f'<li><b>配分</b>：TQQQ 50 ： SOXL 50（DD重視なら70:30可）</li>'
        f'<li><b>地合い</b>：両ETFとも<b>NQ4色</b>でゲート（SOXLも半導体SOXXではなくNQ。実測Sharpe 2.21 vs 0.99）</li>'
        f'<li><b>露出</b>：青100 ／ 緑50 ／ 黄0 ／ 赤0（全撤退）・<b>執行は寄り</b>・利確ラダー無し</li>'
        f'</ul>'
        f'<div class="rh">月中の例外処理</div>'
        f'<ul class="rules">'
        f'<li>能動的に動くのは基本「NQの色」だけ。色が変わったら翌寄りで%を合わせる</li>'
        f'<li><b>赤入り</b>＝両スリーブ全現金。<b>赤明け</b>＝個別は売った銘柄に戻さず最新トップ{N_PORT}を選び直す（赤の間に主役交代するため）</li>'
        f'<li>青⇄緑⇄黄の移動は同じ銘柄を持ったまま%だけ増減（選び直さない）</li>'
        f'<li>保有株が月中に弱っても何もしない（週足SAR弱気・200日割れ・RS低下でも売らない／月次入替で自動処理）。例外は建値−30%のみ</li>'
        f'</ul>'
        f'<div class="rh">やらないこと</div>'
        f'<ul class="rules">'
        f'<li>業種RSで銘柄を絞らない（確認用のみ・momentumが業種情報を内包）／利確ラダーを使わない／週足SARの初動だけ狙わない</li>'
        f'<li>月中に弱った個別を売らない（−30%除く）／SOXLを半導体地合いで動かさない／NQ状態を自動推定で代用しない（手動が真）</li>'
        f'</ul>'
        f'<div class="warn">⚠ 検証上の注意：個別CAGRは生存バイアスで上振れ（最大の割引要因）。レバCAGRは強気相場で上振れ。'
        f'全数字は「どの構成が優れているか」の相対比較で、絶対リターンの予測ではない。主指標はSharpeと最大DD。'
        f'NQの確定状態は手動(TradingView)が真（自動推定は青97%だが赤41%recallで退避を取りこぼす）。</div></div>')

    body = (banner + '<nav>'
            '<button class="on" onclick="tab(\'t-today\',this)">今日</button>'
            '<button onclick="tab(\'t-market\',this)">マーケット</button>'
            '<button onclick="tab(\'t-port\',this)">ポートフォリオ</button>'
            '<button onclick="tab(\'t-watch\',this)">ウォッチ</button>'
            '<button onclick="tab(\'t-sector\',this)">業種RS</button>'
            '<button onclick="tab(\'t-rules\',this)">ルール</button></nav>'
            f'<section id="t-today" class="on">{today}</section>'
            f'<section id="t-market">{market}</section>'
            f'<section id="t-port">{port}</section>'
            f'<section id="t-watch">{watch}</section>'
            f'<section id="t-sector">{sector}</section>'
            f'<section id="t-rules">{rules}</section>')

    asof_disp = pd.Timestamp(asof).tz_localize(None).strftime("%Y-%m-%d %H:%M UTC") \
        if asof else ""
    html = ("<!doctype html><html lang='ja'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>Command Center</title><style>" + CSS + "</style></head><body>"
            "<div class='wrap'><header><h1>Command Center</h1>"
            f"<div class='asof'>更新 {asof_disp}</div></header>"
            + body + "</div><script>" + JS + "</script></body></html>")
    return html

# ----------------------------------------------------------------------------- selftest
def selftest(html, picks, setups, sectors):
    errs = []
    for sid in ["t-today","t-market","t-port","t-watch","t-sector","t-rules"]:
        if f'id="{sid}"' not in html:
            errs.append(f"missing tab {sid}")
    if "MRI 地合いスコア" not in html: errs.append("banner MRI missing")
    if "トレンド判定" not in html: errs.append("trend pill missing")
    if not any(c in html for c in ["sar-blue","sar-green","sar-yellow","sar-red"]):
        errs.append("NQ-SAR color class missing")
    if f">{len(picks)}銘柄<" is None: pass
    if len(picks) != N_PORT: errs.append(f"portfolio not N={N_PORT} (got {len(picks)})")
    if "None" in html: errs.append("literal 'None' in html")
    if ">nan<" in html or " nan%" in html or "nan/100" in html: errs.append("literal nan in html")
    if "リーダー監視" not in html: errs.append("leaders card missing")
    if "本日◎押し目" not in html: errs.append("buy card missing")
    if not sectors: errs.append("sector RS empty")
    if f"N={N_PORT}" not in html: errs.append("N reflected text missing")
    return errs

# ----------------------------------------------------------------------------- main
def main():
    diag = "--diag" in sys.argv
    do_self = "--selftest" in sys.argv or not diag
    names, order, s2i, s2t, e2j, W, macro, asof = load_inputs()
    m, asof_bar = compute_metrics(W, order)
    mri, breakdown, dropped, active, vals = mri_frame(macro)
    aux = mri_auxiliary(mri, vals, m)
    setups = build_setups(m)
    picks, cand = build_portfolio(m, s2t)
    leaders = build_leaders(m, s2i, e2j, s2t)
    sectors = build_sector_rs(m, s2i, e2j)
    breadth = build_breadth(m)
    yields = build_yields(macro)
    sar = read_sar_state()
    mkt = {"distrib": build_distribution(macro), "perf": build_perf(macro),
           "sector_etf": build_sector_etf_rs(macro),
           "breadth_ts": build_breadth_ts(W),
           "mri_ts": [(d.strftime("%Y-%m-%d"), float(v)) for d, v in mri.iloc[-130:].items()]}

    if diag:
        print("=== DIAG ===")
        print(f"metrics tickers: {len(m)} | asof bar: {asof_bar.date()}")
        _sj = SAR_JUDGMENT.get(sar[0], ("", "判定不可"))[1] if sar[0] else "判定不可(無判定)"
        print(f"Trend(SAR): {sar[0]}  判定={_sj}  source={sar[1]}")
        print(f"MRI now: {aux['cur']:.1f}  band: {mri_band(aux['cur'])[0]}")
        print(f"  slope {aux['slope']} | bear {aux['bear_n']}/12 | peak {aux['peak']} (drop {aux['drop']:.1f} from {aux['hi20']:.1f})")
        print(f"  dropped indicators: {dropped or 'none'} | active weights sum: {sum(w for _,w,_,_,_ in active)}")
        print("  breakdown (key: pts/max  raw):")
        for b in breakdown:
            print(f"    {b['key']:12s} {b['pts']:5.1f}/{b['ptsmax']:<3d} raw={b['raw']:.4f}")
        print(f"\nPortfolio N={len(picks)} (theme cap {THEME_CAP}):")
        for t,th,r in picks:
            print(f"  {t:6s} RS{r['rs']:3.0f}  d%{r['pchg']*100:+5.1f}  v200{r['vs200']*100:+6.1f}  [{th}]")
        print(f"\nSetup counts:")
        for k,v in setups.items():
            print(f"  {k:8s} {len(v):4d}   {', '.join(v[:8])}{' ...' if len(v)>8 else ''}")
        bs, bys = leaders
        ltot = sum(len(v) for v in bs.values())
        print(f"\nLeaders (RS>=85 & >200MA): {ltot} total")
        for code, lab, _ in STATE_DEF:
            print(f"  {code} {lab:14s} {len(bs.get(code,[])):4d}")
        print(f"本日◎押し目 (③ buys): {len(bys)}  " +
              ", ".join(b['t'] for b in bys[:12]) + (' ...' if len(bys) > 12 else ''))
        print(f"\nSector RS top8:")
        for s in sectors[:8]:
            print(f"  {s['score']:5.1f}  {s['ja'][:24]:24s} (n={s['n']})")
        print(f"Sector RS bottom5:")
        for s in sectors[-5:]:
            print(f"  {s['score']:5.1f}  {s['ja'][:24]:24s} (n={s['n']})")
        print(f"\nBreadth: >200MA {breadth['pa200']:.0f}% | >50MA {breadth['pa50']:.0f}% | adv/dec {breadth['adv']}/{breadth['dec']} | 52wH {breadth['nh']}")
        print(f"Yields: " + " | ".join(f"{k} {d['y']:.2f}%({d['chg']:+.2f})" for k,d in yields.items()))
        dd = mkt["distrib"]; pf = mkt["perf"]
        print("Distribution days: " + (", ".join(f"{k} {v['n']}({v['st']})" for k,v in dd.items()) or "n/a"))
        if pf:
            print(f"SPY perf: YTD {fmt_pct(pf['ytd'])} 1W {fmt_pct(pf['w1'])} 1M {fmt_pct(pf['m1'])} 1Y {fmt_pct(pf['y1'])} | 52w-pos {pf['pos52']:.0f}% | VIX {pf['vix']:.1f}")
        se = mkt["sector_etf"]
        print(f"\nSector ETF RS (market-rep, {len(se)} sectors, strong->weak):")
        for s in se:
            print(f"  {s['rs']:3.0f}  {s['ja']:8s} {s['tk']}  d{fmt_pct(s['d1'])} w{fmt_pct(s['w1'])} m{fmt_pct(s['m1'])}")
        bts = mkt["breadth_ts"]
        if bts:
            print(f"Breadth TS (>200MA): {len(bts)} pts, {bts[0][1]:.0f}% -> {bts[-1][1]:.0f}%")
        print(f"SAR-bullish count: {(m['sar_bull']==True).sum()} / {m['sar_bull'].notna().sum()} valid")
        return

    html = render(names, m, mri, breakdown, dropped, aux, setups, picks, cand,
                  sectors, breadth, yields, asof, sar, mkt, leaders)
    if do_self:
        errs = selftest(html, picks, setups, sectors)
        if errs:
            print("SELFTEST FAILED:")
            for e in errs: print("  -", e)
            sys.exit(1)
        bs_, bys_ = leaders
        print("SELFTEST OK (6 tabs, MRI banner, N=%d, leaders=%d, buys=%d, sectors=%d, no None/nan)" %
              (len(picks), sum(len(v) for v in bs_.values()), len(bys_), len(sectors)))
    _outdir = os.path.dirname(OUT_HTML)
    if _outdir:
        os.makedirs(_outdir, exist_ok=True)
    open(OUT_HTML, "w").write(html)
    print("WROTE", OUT_HTML, f"({len(html)//1024} KB)")

if __name__ == "__main__":
    main()
