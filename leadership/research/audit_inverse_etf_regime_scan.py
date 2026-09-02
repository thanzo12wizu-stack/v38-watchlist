from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from itertools import combinations
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf

import audit_ordinary_stock_market_mode_robustness as market_mode
import audit_rsi30_mc_nqsar as market_audit

TRAIN_END = pd.Timestamp("2021-12-31")
HOLDOUT_START = pd.Timestamp("2022-01-03")
PRODUCTS = ["PSQ", "QID", "SQQQ"]
HORIZONS = [1, 3, 5, 10, 20]
PERIODS = {
    "ALL": ("2016-01-04", "2026-03-20"),
    "TRAIN_2016_2021": ("2016-01-04", "2021-12-31"),
    "HOLDOUT_2022_2026": ("2022-01-03", "2026-03-20"),
    "2016_2019": ("2016-01-04", "2019-12-31"),
    "2020_2021": ("2020-01-01", "2021-12-31"),
    "2022_2023": ("2022-01-03", "2023-12-29"),
    "2024_2026": ("2024-01-02", "2026-03-20"),
}

def safe(x: Any) -> Any:
    if isinstance(x, dict):
        return {str(k): safe(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [safe(v) for v in x]
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating, float)):
        v = float(x)
        return v if np.isfinite(v) else None
    if isinstance(x, pd.Timestamp):
        return x.isoformat()
    return x

def norm_idx(idx) -> pd.DatetimeIndex:
    x = pd.to_datetime(idx)
    try:
        x = x.tz_localize(None)
    except TypeError:
        x = x.tz_convert(None)
    return pd.DatetimeIndex(x).normalize()

def dl(symbols: list[str], start: str, end: str) -> dict[str, pd.DataFrame]:
    raw = yf.download(symbols, start=start, end=end, auto_adjust=True, actions=False,
                      progress=False, threads=False, group_by="column")
    if raw.empty:
        raise RuntimeError("market download empty")
    out: dict[str, pd.DataFrame] = {}
    if isinstance(raw.columns, pd.MultiIndex):
        lv0 = set(raw.columns.get_level_values(0))
        for field in ["Open", "High", "Low", "Close", "Volume"]:
            if field in lv0:
                z = raw[field].copy()
                if isinstance(z, pd.Series):
                    z = z.to_frame(symbols[0])
                z.index = norm_idx(z.index)
                out[field.lower()] = z.sort_index()
    else:
        for field in ["Open", "High", "Low", "Close", "Volume"]:
            if field in raw.columns:
                z = raw[[field]].copy()
                z.columns = [symbols[0]]
                z.index = norm_idx(z.index)
                out[field.lower()] = z.sort_index()
    return out

def rsi14(s: pd.Series) -> pd.Series:
    d = s.diff()
    up = d.clip(lower=0)
    dn = -d.clip(upper=0)
    ru = up.ewm(alpha=1/14, adjust=False).mean()
    rd = dn.ewm(alpha=1/14, adjust=False).mean()
    return 100.0 - 100.0 / (1.0 + ru / rd)

def adx14(h: pd.Series, l: pd.Series, c: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    up = h.diff()
    dn = -l.diff()
    plus_dm = up.where((up > dn) & (up > 0), 0.0)
    minus_dm = dn.where((dn > up) & (dn > 0), 0.0)
    tr = pd.concat([(h-l).abs(), (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/14, adjust=False).mean()
    pdi = 100 * plus_dm.ewm(alpha=1/14, adjust=False).mean() / atr
    mdi = 100 * minus_dm.ewm(alpha=1/14, adjust=False).mean() / atr
    dx = 100 * (pdi-mdi).abs() / (pdi+mdi)
    adx = dx.ewm(alpha=1/14, adjust=False).mean()
    return adx, pdi, mdi

def build_features(root: Path, rates_path: Path, panic_path: Path, start: str, end: str,
                   max_tickers: int, batch_size: int) -> tuple[pd.DataFrame, dict[str, pd.DataFrame], dict[str, Any]]:
    a0 = pd.Timestamp(start)
    a1 = pd.Timestamp(end)
    warm = str((a0 - pd.Timedelta(days=500)).date())
    dl_end = str((a1 + pd.Timedelta(days=15)).date())

    meta, _m = market_mode.build_inputs(root, start, end, max_tickers, batch_size)
    idx = pd.DatetimeIndex(meta["analysis_idx"]).normalize()
    feat = pd.DataFrame(index=idx)
    feat["breadth50"] = pd.to_numeric(meta["breadth"], errors="coerce").reindex(idx)
    nq = meta["nq"].reindex(idx)
    feat["nq_color"] = nq["nq_color"]
    sev = {"Red": 0.0, "Yellow": 1.0, "Green": 2.0, "Blue": 3.0}
    feat["nq_sev"] = feat.nq_color.map(sev)
    feat["nq_red"] = feat.nq_color.eq("Red").astype(float)
    feat["nq_yellow_red"] = feat.nq_color.isin(["Yellow","Red"]).astype(float)
    feat["nq_red_entry"] = (feat.nq_color.eq("Red") & ~feat.nq_color.shift(1).eq("Red")).astype(float)
    red = feat.nq_color.eq("Red")
    grp = (~red).cumsum()
    feat["nq_red_run"] = red.groupby(grp).cumsum().astype(float)

    mc = market_audit.build_mc(end).reindex(idx).ffill(limit=2)
    for c in mc.columns:
        if c == "mc":
            feat["mc57"] = pd.to_numeric(mc[c], errors="coerce")
        elif pd.api.types.is_bool_dtype(mc[c]):
            feat[c] = mc[c].astype(float)
        else:
            feat[c] = pd.to_numeric(mc[c], errors="coerce")
    feat["mc_chg1"] = feat.mc57.diff(1)
    feat["mc_chg5"] = feat.mc57.diff(5)
    feat["mc_chg10"] = feat.mc57.diff(10)

    symbols = ["QQQ", "^VIX", "^VIX3M", "HYG", "LQD", "RSP", "SPY", "IWM", "SOXX",
               "XLY", "XLP", "TLT", "UUP", "PSQ", "QID", "SQQQ"]
    mkt = dl(symbols, warm, dl_end)
    close = mkt["close"].reindex(idx).ffill(limit=2)
    opn = mkt["open"].reindex(idx).ffill(limit=2)
    high = mkt["high"].reindex(idx).ffill(limit=2)
    low = mkt["low"].reindex(idx).ffill(limit=2)
    vol = mkt["volume"].reindex(idx)

    q = close["QQQ"]
    qh, ql = high["QQQ"], low["QQQ"]
    qo = opn["QQQ"]
    ema21 = q.ewm(span=21, adjust=False).mean()
    sma50 = q.rolling(50, min_periods=50).mean()
    sma200 = q.rolling(200, min_periods=200).mean()
    tr = pd.concat([(qh-ql).abs(), (qh-q.shift()).abs(), (ql-q.shift()).abs()], axis=1).max(axis=1)
    atr14 = tr.ewm(alpha=1/14, adjust=False).mean()
    ret = q.pct_change()
    adx, pdi, mdi = adx14(qh, ql, q)

    feat["qqq_ret1"] = q.pct_change(1)
    feat["qqq_ret5"] = q.pct_change(5)
    feat["qqq_ret10"] = q.pct_change(10)
    feat["qqq_ret20"] = q.pct_change(20)
    feat["qqq_dd20"] = q / q.rolling(20, min_periods=20).max() - 1
    feat["qqq_dd63"] = q / q.rolling(63, min_periods=63).max() - 1
    feat["qqq_dd252"] = q / q.rolling(252, min_periods=126).max() - 1
    feat["qqq_dist_ema21"] = q / ema21 - 1
    feat["qqq_dist_sma50"] = q / sma50 - 1
    feat["qqq_dist_sma200"] = q / sma200 - 1
    feat["qqq_atr_dist50"] = (q - sma50) / atr14
    feat["ema21_slope5"] = ema21.pct_change(5)
    feat["sma50_slope10"] = sma50.pct_change(10)
    feat["sma200_slope20"] = sma200.pct_change(20)
    feat["qqq_rsi14"] = rsi14(q)
    feat["qqq_atr14_pct"] = atr14 / q
    feat["qqq_rv10"] = ret.rolling(10).std() * np.sqrt(252)
    feat["qqq_rv20"] = ret.rolling(20).std() * np.sqrt(252)
    feat["qqq_adx14"] = adx
    feat["qqq_minus_di14"] = mdi
    feat["qqq_plus_di14"] = pdi
    feat["qqq_dmi_spread"] = mdi - pdi
    qv = vol["QQQ"]
    feat["dist_days10"] = ((q < q.shift()) & (qv > qv.shift())).rolling(10).sum()
    feat["gap1"] = qo / q.shift() - 1
    feat["gapdown_count10"] = (feat.gap1 <= -0.01).rolling(10).sum()

    vix = close["^VIX"]
    vix3m = close["^VIX3M"]
    feat["vix"] = vix
    feat["vix_chg5"] = vix.pct_change(5)
    feat["vix_chg10"] = vix.pct_change(10)
    feat["vix_pct252"] = vix.rolling(252, min_periods=126).rank(pct=True)
    feat["vix_term_ratio"] = vix / vix3m
    feat["vix_backward"] = (feat.vix_term_ratio > 1.0).astype(float)

    def ratio_mom(name: str, aa: str, bb: str, n: int):
        rr = close[aa] / close[bb]
        feat[name] = rr.pct_change(n)

    ratio_mom("hyg_lqd_mom5", "HYG", "LQD", 5)
    ratio_mom("hyg_lqd_mom20", "HYG", "LQD", 20)
    ratio_mom("rsp_spy_mom20", "RSP", "SPY", 20)
    ratio_mom("iwm_qqq_mom20", "IWM", "QQQ", 20)
    ratio_mom("soxx_qqq_mom20", "SOXX", "QQQ", 20)
    ratio_mom("xly_xlp_mom20", "XLY", "XLP", 20)
    ratio_mom("tlt_qqq_mom20", "TLT", "QQQ", 20)
    feat["hyg_ret20"] = close["HYG"].pct_change(20)
    feat["uup_ret20"] = close["UUP"].pct_change(20)

    feat["breadth_chg5"] = feat.breadth50.diff(5)
    feat["breadth_chg10"] = feat.breadth50.diff(10)
    feat["breadth_ma10"] = feat.breadth50.rolling(10).mean()
    feat["breadth_disp10"] = feat.breadth50 - feat.breadth_ma10

    rates = pd.read_csv(rates_path, parse_dates=["date"]).set_index("date").sort_index()
    rates.index = norm_idx(rates.index)
    rate_cols = [
        "dgs2", "dgs10", "real10", "be10", "curve_2s10s_bp",
        "dgs2_level_pct252", "dgs10_level_pct252", "real10_level_pct252",
        "dgs2_chg5_z252", "dgs10_chg5_z252", "real10_chg5_z252",
        "dgs2_acc5_z252", "dgs10_acc5_z252", "real10_acc5_z252",
        "rate_shock_z5", "duration_shock_z5", "inflation_shock_z5",
        "rate_accel_z5", "duration_accel_z5", "real_share_shock",
        "curve_chg5_z252", "curve_acc5_z252",
    ]
    rates = rates.reindex(idx).ffill(limit=7)
    for c in rate_cols:
        if c in rates.columns:
            feat[c] = pd.to_numeric(rates[c], errors="coerce")

    panic = pd.read_csv(panic_path, parse_dates=["date", "end_date"])
    feat["panic_episode"] = 0.0
    for _, r in panic.iterrows():
        aa, bb = pd.Timestamp(r.date).normalize(), pd.Timestamp(r.end_date).normalize()
        feat.loc[(feat.index >= aa) & (feat.index <= bb), "panic_episode"] = 1.0

    prod_open = opn[PRODUCTS].copy()
    outcomes: dict[str, pd.DataFrame] = {}
    for p in PRODUCTS:
        z = pd.DataFrame(index=idx)
        for h in HORIZONS:
            z[f"fwd{h}"] = prod_open[p].shift(-(h+1)) / prod_open[p].shift(-1) - 1.0
        z["oo_ret"] = prod_open[p].shift(-1) / prod_open[p] - 1.0
        outcomes[p] = z

    diag = {
        "analysis_start": str(idx.min().date()),
        "analysis_end": str(idx.max().date()),
        "sessions": len(idx),
        "breadth_nonnull": int(feat.breadth50.notna().sum()),
        "mc_nonnull": int(feat.mc57.notna().sum()),
        "nqsar_nonnull": int(feat.nq_color.notna().sum()),
        "rate_nonnull": int(feat.rate_shock_z5.notna().sum()),
        "panic_sessions": int(feat.panic_episode.sum()),
        "product_open_nonnull": {p: int(prod_open[p].notna().sum()) for p in PRODUCTS},
    }
    return feat, outcomes, diag

def event_mask(cond: pd.Series) -> pd.Series:
    c = cond.fillna(False).astype(bool)
    return c & ~c.shift(1, fill_value=False)

def event_stats(cond: pd.Series, outcome: pd.Series, period_mask: pd.Series,
                calendar: pd.DatetimeIndex, seed: int) -> dict[str, Any]:
    ev = event_mask(cond) & period_mask
    z = pd.DataFrame({"r": outcome, "ev": ev}, index=calendar)
    z = z.loc[z.ev & z.r.notna(), ["r"]].copy()
    if len(z) == 0:
        return {"n": 0}
    pos = pd.Series(np.arange(len(calendar)), index=calendar).reindex(z.index)
    z["block20"] = (pos // 20).astype(int).to_numpy()
    r = z.r.astype(float)
    out = {
        "n": int(len(r)),
        "mean": float(r.mean()),
        "median": float(r.median()),
        "win": float((r > 0).mean()),
        "p10": float(r.quantile(.10)),
        "p90": float(r.quantile(.90)),
        "worst": float(r.min()),
        "best": float(r.max()),
    }
    blocks = z.groupby("block20").r.mean().to_numpy(float)
    if len(blocks) >= 5:
        rng = np.random.default_rng(seed)
        draws = rng.choice(blocks, size=(4000, len(blocks)), replace=True).mean(axis=1)
        out["lo"] = float(np.quantile(draws, .025))
        out["hi"] = float(np.quantile(draws, .975))
        out["p_two"] = float(min(1.0, 2 * min((draws <= 0).mean(), (draws >= 0).mean())))
    return out

def bh_qvalues(pvals: pd.Series) -> pd.Series:
    p = pd.to_numeric(pvals, errors="coerce")
    good = p.notna()
    x = p[good].to_numpy(float)
    if len(x) == 0:
        return pd.Series(np.nan, index=p.index)
    order = np.argsort(x)
    ranked = x[order]
    q = ranked * len(x) / np.arange(1, len(x)+1)
    q = np.minimum.accumulate(q[::-1])[::-1]
    q = np.clip(q, 0, 1)
    back = np.empty_like(q)
    back[order] = q
    out = pd.Series(np.nan, index=p.index)
    out.loc[good] = back
    return out

def numeric_candidates(feat: pd.DataFrame) -> dict[str, pd.Series]:
    continuous = [
        "nq_sev", "nq_red_run", "mc57", "mc_chg1", "mc_chg5", "mc_chg10",
        "breadth50", "breadth_chg5", "breadth_chg10", "breadth_disp10",
        "qqq_ret1", "qqq_ret5", "qqq_ret10", "qqq_ret20",
        "qqq_dd20", "qqq_dd63", "qqq_dd252", "qqq_dist_ema21",
        "qqq_dist_sma50", "qqq_dist_sma200", "qqq_atr_dist50",
        "ema21_slope5", "sma50_slope10", "sma200_slope20", "qqq_rsi14",
        "qqq_atr14_pct", "qqq_rv10", "qqq_rv20", "qqq_adx14", "qqq_dmi_spread",
        "dist_days10", "gap1", "gapdown_count10",
        "vix", "vix_chg5", "vix_chg10", "vix_pct252", "vix_term_ratio",
        "hyg_lqd_mom5", "hyg_lqd_mom20", "rsp_spy_mom20", "iwm_qqq_mom20",
        "soxx_qqq_mom20", "xly_xlp_mom20", "tlt_qqq_mom20", "hyg_ret20", "uup_ret20",
        "dgs2", "dgs10", "real10", "be10", "curve_2s10s_bp",
        "dgs2_level_pct252", "dgs10_level_pct252", "real10_level_pct252",
        "dgs2_chg5_z252", "dgs10_chg5_z252", "real10_chg5_z252",
        "dgs2_acc5_z252", "dgs10_acc5_z252", "real10_acc5_z252",
        "rate_shock_z5", "duration_shock_z5", "inflation_shock_z5",
        "rate_accel_z5", "duration_accel_z5", "real_share_shock",
        "curve_chg5_z252", "curve_acc5_z252",
    ]
    train = feat.index <= TRAIN_END
    out: dict[str, pd.Series] = {}
    for c in continuous:
        if c not in feat:
            continue
        s = pd.to_numeric(feat[c], errors="coerce")
        st = s.loc[train].dropna()
        if len(st) < 250 or st.nunique() < 10:
            continue
        for q, lab in [(0.20, "LOW20"), (0.33, "LOW33"), (0.67, "HIGH33"), (0.80, "HIGH20")]:
            th = float(st.quantile(q))
            if "LOW" in lab:
                out[f"{c}__{lab}__{th:.6g}"] = s <= th
            else:
                out[f"{c}__{lab}__{th:.6g}"] = s >= th
    cats = {
        "NQSAR_RED": feat.nq_color.eq("Red"),
        "NQSAR_YELLOW_RED": feat.nq_color.isin(["Yellow", "Red"]),
        "NQSAR_RED_ENTRY": feat.nq_red_entry.eq(1),
        "MC_FALLING": feat.mc_chg5 < 0,
        "BREADTH_LT50": feat.breadth50 < 50,
        "BREADTH_LT40": feat.breadth50 < 40,
        "QQQ_BELOW50": feat.qqq_dist_sma50 < 0,
        "QQQ_BELOW200": feat.qqq_dist_sma200 < 0,
        "QQQ_50SLOPE_DOWN": feat.sma50_slope10 < 0,
        "VIX_BACKWARD": feat.vix_term_ratio > 1,
        "CREDIT_WEAK": feat.hyg_lqd_mom20 < 0,
        "RATE_SHOCK": feat.rate_shock_z5 >= .75,
        "REAL10_SHOCK": feat.real10_chg5_z252 >= .75,
    }
    out.update(cats)
    return out

def fixed_flags(feat: pd.DataFrame) -> dict[str, pd.Series]:
    return {
        "NQSAR_RED": feat.nq_color.eq("Red"),
        "NQSAR_YELLOW_RED": feat.nq_color.isin(["Yellow", "Red"]),
        "BREADTH_LT50": feat.breadth50 < 50,
        "BREADTH_FALLING10": feat.breadth_chg10 < -5,
        "QQQ_BELOW50": feat.qqq_dist_sma50 < 0,
        "QQQ_50SLOPE_DOWN": feat.sma50_slope10 < 0,
        "QQQ_BELOW200": feat.qqq_dist_sma200 < 0,
        "QQQ_DMI_BEAR": feat.qqq_dmi_spread > 5,
        "MC_FALLING5": feat.mc_chg5 < -3,
        "VIX_RISING5": feat.vix_chg5 > .15,
        "VIX_BACKWARD": feat.vix_term_ratio > 1.0,
        "CREDIT_WEAK": feat.hyg_lqd_mom20 < 0,
        "BREADTH_RS_WEAK": feat.rsp_spy_mom20 < 0,
        "SEMIS_WEAK": feat.soxx_qqq_mom20 < 0,
        "CYCLICAL_WEAK": feat.xly_xlp_mom20 < 0,
        "RATE_SHOCK": feat.rate_shock_z5 >= .75,
        "REAL10_SHOCK": feat.real10_chg5_z252 >= .75,
        "DURATION_SHOCK": feat.duration_shock_z5 >= .75,
    }

def run_screen(feat: pd.DataFrame, outcomes: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    candidates = numeric_candidates(feat)
    train_mask = pd.Series(feat.index <= TRAIN_END, index=feat.index)
    hold_mask = pd.Series(feat.index >= HOLDOUT_START, index=feat.index)
    rows = []
    k = 0
    for name, cond in candidates.items():
        for p in PRODUCTS:
            for h in [5,10,20]:
                a = event_stats(cond, outcomes[p][f"fwd{h}"], train_mask, feat.index, 38+k)
                b = event_stats(cond, outcomes[p][f"fwd{h}"], hold_mask, feat.index, 38000+k)
                rows.append({
                    "condition": name, "product": p, "horizon": h,
                    "train_n": a.get("n",0), "train_mean": a.get("mean"),
                    "train_win": a.get("win"), "train_lo": a.get("lo"), "train_hi": a.get("hi"),
                    "train_p": a.get("p_two"), "train_worst": a.get("worst"),
                    "hold_n": b.get("n",0), "hold_mean": b.get("mean"),
                    "hold_win": b.get("win"), "hold_lo": b.get("lo"), "hold_hi": b.get("hi"),
                    "hold_p": b.get("p_two"), "hold_worst": b.get("worst"),
                })
                k += 1
    uni = pd.DataFrame(rows)
    uni["train_q"] = bh_qvalues(uni.train_p)
    uni["hold_q"] = bh_qvalues(uni.hold_p)
    uni["stable_positive"] = (
        (uni.train_n >= 20) & (uni.hold_n >= 10)
        & (uni.train_mean > 0) & (uni.hold_mean > 0)
    )
    uni["robust_score"] = np.minimum(uni.train_mean.fillna(-9), uni.hold_mean.fillna(-9))

    flags = fixed_flags(feat)
    rows = []
    k = 0
    for (n1, c1), (n2, c2) in combinations(flags.items(), 2):
        cond = c1 & c2
        for p in PRODUCTS:
            a = event_stats(cond, outcomes[p]["fwd10"], train_mask, feat.index, 100000+k)
            b = event_stats(cond, outcomes[p]["fwd10"], hold_mask, feat.index, 200000+k)
            rows.append({
                "flag1": n1, "flag2": n2, "product": p,
                "train_n": a.get("n",0), "train_mean": a.get("mean"), "train_win": a.get("win"),
                "train_p": a.get("p_two"), "hold_n": b.get("n",0),
                "hold_mean": b.get("mean"), "hold_win": b.get("win"), "hold_p": b.get("p_two"),
            })
            k += 1
    pair = pd.DataFrame(rows)
    pair["train_q"] = bh_qvalues(pair.train_p)
    pair["hold_q"] = bh_qvalues(pair.hold_p)
    pair["stable_positive"] = (
        (pair.train_n >= 15) & (pair.hold_n >= 8)
        & (pair.train_mean > 0) & (pair.hold_mean > 0)
    )
    pair["robust_score"] = np.minimum(pair.train_mean.fillna(-9), pair.hold_mean.fillna(-9))
    return uni, pair

def build_scores(feat: pd.DataFrame) -> pd.DataFrame:
    s = pd.DataFrame(index=feat.index)
    s["trend"] = ((feat.qqq_dist_sma50 < 0) & (feat.sma50_slope10 < 0)).astype(int)
    s["internals"] = ((feat.breadth50 < 50) | (feat.breadth_chg10 < -8)).astype(int)
    s["nqsar"] = feat.nq_color.eq("Red").astype(int)
    s["vol"] = ((feat.vix_chg5 > .15) | (feat.vix_term_ratio > 1)).astype(int)
    s["credit"] = (feat.hyg_lqd_mom20 < 0).astype(int)
    s["leadership"] = ((feat.rsp_spy_mom20 < 0) & (feat.soxx_qqq_mom20 < 0)).astype(int)
    s["mc"] = (feat.mc_chg5 < -3).astype(int)
    s["rates"] = ((feat.rate_shock_z5 >= .75) | (feat.real10_chg5_z252 >= .75)).astype(int)
    s["core_score"] = s[["trend","internals","nqsar","vol","credit","leadership","mc"]].sum(axis=1)
    s["plus_rate_score"] = s.core_score + s.rates
    s["panic_guard"] = feat.panic_episode.eq(1)
    s["deep_oversold"] = ((feat.qqq_rsi14 <= 28) & (feat.vix >= 28) & (feat.qqq_dd20 <= -.08))
    return s

def hysteresis(score: pd.Series, enter: int, exit_: int, guard: pd.Series) -> pd.Series:
    hold = False
    vals = []
    for d in score.index:
        if bool(guard.loc[d]):
            hold = False
        elif not hold and float(score.loc[d]) >= enter:
            hold = True
        elif hold and float(score.loc[d]) <= exit_:
            hold = False
        vals.append(hold)
    return pd.Series(vals, index=score.index, dtype=bool)

def perf_from_ret(r: pd.Series) -> dict[str, Any]:
    x = pd.to_numeric(r, errors="coerce").fillna(0.0)
    if len(x) < 5:
        return {"n": int(len(x))}
    nav = (1+x).cumprod()
    yrs = len(x)/252
    dd = nav/nav.cummax()-1
    vol = x.std(ddof=1)*np.sqrt(252)
    cagr = nav.iloc[-1]**(1/yrs)-1 if yrs > 0 and nav.iloc[-1] > 0 else np.nan
    return {
        "n": int(len(x)), "cagr": float(cagr), "maxdd": float(dd.min()),
        "ann_vol": float(vol), "sharpe": float(x.mean()/x.std(ddof=1)*np.sqrt(252)) if x.std(ddof=1)>0 else None,
        "calmar": float(cagr/abs(dd.min())) if dd.min()<0 else None,
        "final_nav": float(nav.iloc[-1]),
        "positive_days": float((x>0).mean()),
        "worst_day": float(x.min()), "best_day": float(x.max()),
    }

def run_strategies(feat: pd.DataFrame, outcomes: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    scores = build_scores(feat)
    rows = []
    daily = pd.DataFrame(index=feat.index)
    daily = daily.join(scores)
    yearly_rows = []
    variants = []
    for score_name in ["core_score", "plus_rate_score"]:
        for enter, exit_ in [(2,0),(3,1),(4,2)]:
            for guard_name, guard in [
                ("NO_GUARD", pd.Series(False,index=feat.index)),
                ("PANIC_GUARD", scores.panic_guard),
                ("PANIC_PLUS_DEEP", scores.panic_guard | scores.deep_oversold),
            ]:
                hold_close = hysteresis(scores[score_name], enter, exit_, guard)
                variants.append((score_name, enter, exit_, guard_name, hold_close))
    for p in PRODUCTS:
        oo = outcomes[p]["oo_ret"].reindex(feat.index)
        for score_name, enter, exit_, guard_name, hold_close in variants:
            pos_open = hold_close.shift(1, fill_value=False).astype(float)
            for weight in [0.15,0.30,0.50]:
                for cost_bp in [0,5,10]:
                    turnover = pos_open.diff().abs().fillna(pos_open.abs())
                    ret = weight*pos_open*oo.fillna(0) - weight*turnover*(cost_bp/10000.0)
                    name = f"{p}_{weight:.2f}_{score_name}_E{enter}X{exit_}_{guard_name}_C{cost_bp}"
                    daily[name] = ret
                    for period,(aa,bb) in PERIODS.items():
                        mask=(ret.index>=aa)&(ret.index<=bb)
                        m=perf_from_ret(ret.loc[mask])
                        rows.append({
                            "strategy":name, "product":p, "weight":weight, "score":score_name,
                            "enter":enter, "exit":exit_, "guard":guard_name, "cost_bp_side":cost_bp,
                            "period":period, "holding_days":int(pos_open.loc[mask].sum()),
                            "entries":int(((pos_open.diff()==1)&mask).sum()),
                            **m,
                        })
                    if weight==0.30 and cost_bp==5:
                        for year,g in ret.groupby(ret.index.year):
                            m=perf_from_ret(g)
                            yearly_rows.append({
                                "strategy":name, "year":int(year),
                                "holding_days":int(pos_open.loc[g.index].sum()),
                                "entries":int((pos_open.loc[g.index].diff()==1).sum()), **m
                            })
    return pd.DataFrame(rows), pd.DataFrame(yearly_rows), daily.reset_index(names="date")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--rates", required=True)
    ap.add_argument("--panic", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--start", default="2016-01-04")
    ap.add_argument("--end", default="2026-03-20")
    ap.add_argument("--max-tickers", type=int, default=6000)
    ap.add_argument("--batch-size", type=int, default=75)
    a=ap.parse_args()
    root=Path(a.root)
    out=Path(a.output); out.mkdir(parents=True, exist_ok=True)
    feat,outcomes,diag=build_features(root,Path(a.rates),Path(a.panic),a.start,a.end,a.max_tickers,a.batch_size)
    uni,pair=run_screen(feat,outcomes)
    strat,yearly,daily=run_strategies(feat,outcomes)

    feat.reset_index(names="date").to_csv(out/"inverse_feature_state.csv.gz",index=False,compression="gzip")
    uni.sort_values(["stable_positive","robust_score"],ascending=[False,False]).to_csv(out/"inverse_univariate_screen.csv",index=False)
    pair.sort_values(["stable_positive","robust_score"],ascending=[False,False]).to_csv(out/"inverse_pair_screen.csv",index=False)
    strat.to_csv(out/"inverse_strategy_performance.csv",index=False)
    yearly.to_csv(out/"inverse_strategy_yearly.csv",index=False)
    daily.to_csv(out/"inverse_strategy_daily.csv.gz",index=False,compression="gzip")

    hold = strat[strat.period.eq("HOLDOUT_2022_2026")].copy()
    train = strat[strat.period.eq("TRAIN_2016_2021")][["strategy","cagr","maxdd","calmar"]].rename(
        columns={"cagr":"train_cagr","maxdd":"train_maxdd","calmar":"train_calmar"})
    rank=hold.merge(train,on="strategy",how="left")
    rank["min_cagr"]=rank[["cagr","train_cagr"]].min(axis=1)
    rank["stable_positive"]=(rank.cagr>0)&(rank.train_cagr>0)
    rank=rank.sort_values(["stable_positive","min_cagr","calmar"],ascending=[False,False,False])

    best_uni=uni[(uni.stable_positive)&(uni.horizon.eq(10))].sort_values("robust_score",ascending=False).head(25)
    best_pair=pair[pair.stable_positive].sort_values("robust_score",ascending=False).head(25)
    best_strat=rank.head(30)
    summary={
        "status":"RESEARCH_ONLY_NO_PRODUCTION_CHANGE",
        "mechanics":{
            "signals":"All indicators use signal-day close; strategy position begins next session open.",
            "products":"Actual auto-adjusted PSQ/QID/SQQQ OHLC; daily-reset path is preserved.",
            "split":"2016-2021 train, 2022-2026-03-20 holdout.",
            "univariate":"Train quantile thresholds frozen before holdout; eventized condition-entry returns; 20-session block bootstrap; BH FDR.",
            "pairs":"Pre-specified cross-family pair flags; eventized 10-session outcomes; BH FDR.",
            "strategies":"Family-level score with hysteresis, 15/30/50% sleeve, 0/5/10bp-per-side cost, panic guard variants.",
        },
        "diagnostics":diag,
        "best_univariate_10d":best_uni.to_dict("records"),
        "best_pairs_10d":best_pair.to_dict("records"),
        "best_strategies_holdout":best_strat.to_dict("records"),
    }
    (out/"summary.json").write_text(json.dumps(safe(summary),ensure_ascii=False,indent=2),encoding="utf-8")
    print("===INVERSE_SCAN_SUMMARY===")
    print(json.dumps(safe(summary),ensure_ascii=False,separators=(",",":")))
    print("===END===")

if __name__ == "__main__":
    main()
