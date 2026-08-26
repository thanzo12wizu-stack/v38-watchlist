from __future__ import annotations

import itertools
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

import build_dashboard as bd

START = pd.Timestamp("2011-01-03")
IS_END = pd.Timestamp("2018-12-31")
OOS_START = pd.Timestamp("2019-01-01")
COST_BPS = 5.0
CORE = 0.30

ENTRY_LEVELS = [-0.5, -1.0, -1.5, -2.0, -2.5, -3.0, -3.5, -4.0]
EXIT_LEVELS = [0.0, 0.5, 1.0, 1.5, 2.0]
ALLOC_SHAPES = {
    # cumulative tactical exposure after tier 1..4; total exposure = CORE + tactical
    "even":   [0.175, 0.350, 0.525, 0.700],
    "front":  [0.250, 0.450, 0.600, 0.700],
    "back":   [0.100, 0.250, 0.450, 0.700],
    "convex": [0.100, 0.200, 0.400, 0.700],
}


def _plain(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy()
    if isinstance(x.columns, pd.MultiIndex):
        if len(set(x.columns.get_level_values(0))) == 1:
            x.columns = x.columns.get_level_values(1)
        elif len(set(x.columns.get_level_values(1))) == 1:
            x.columns = x.columns.get_level_values(0)
    x.index = pd.to_datetime(x.index).tz_localize(None)
    return x.sort_index()


def dl_one(ticker: str, start: str) -> pd.DataFrame:
    x = yf.download(ticker, start=start, progress=False, auto_adjust=True, actions=False, threads=False)
    x = _plain(x)
    need = ["Open", "High", "Low", "Close", "Volume"]
    miss = [c for c in need if c not in x.columns]
    if miss:
        raise RuntimeError(f"{ticker} missing columns: {miss}; got {list(x.columns)}")
    return x[need].dropna(subset=["Open", "Close"])


def compute_mc() -> tuple[pd.Series, pd.Series]:
    print(f"[data] downloading MC57 from {bd.MC_LONG_HISTORY_START} ...", flush=True)
    raw = yf.download(
        list(bd.MC_MARKET_TICKERS), start=bd.MC_LONG_HISTORY_START, progress=False,
        auto_adjust=True, actions=False, group_by="ticker", threads=True,
    )
    macro = bd._extract(raw, list(bd.MC_MARKET_TICKERS), minbars=30)
    missing = [t for t in bd.MC_MARKET_TICKERS if t not in macro]
    # One-ticker fallbacks match production's long-history loader behavior.
    for t in missing:
        try:
            h = yf.Ticker(t).history(start=bd.MC_LONG_HISTORY_START, auto_adjust=True)
            got = bd._extract(h, [t], minbars=30).get(t)
            if got is not None and len(got):
                macro[t] = got
        except Exception:
            pass
    print(f"[data] MC57 coverage latest: {len(macro)}/{len(bd.MC_MARKET_TICKERS)}", flush=True)
    score, _, _, _, vals = bd.mri_frame(macro, W=None)
    score = pd.to_numeric(score, errors="coerce")
    score.index = pd.to_datetime(score.index).tz_localize(None)
    cov = pd.to_numeric(vals["mc_coverage"], errors="coerce")
    cov.index = pd.to_datetime(cov.index).tz_localize(None)
    return score.sort_index(), cov.sort_index()


def vix_state_series(vix: pd.DataFrame) -> tuple[pd.Series, list[dict]]:
    # Exact state-machine facts used by current V38 build_dashboard.py.
    df = pd.DataFrame({
        "close": pd.to_numeric(vix["Close"], errors="coerce"),
        "high": pd.to_numeric(vix["High"], errors="coerce"),
    }).replace([np.inf, -np.inf], np.nan).dropna()
    df = df[(df["close"] > 0) & (df["high"] > 0)]
    df = df[df.index >= bd.VIX_CYCLE_START].copy()
    df["wma5"] = bd._vix_lwma(df["high"], bd.VIX_CYCLE_FAST).to_numpy()
    df["wma10"] = bd._vix_lwma(df["high"], bd.VIX_CYCLE_SLOW).to_numpy()

    periods = df.index.to_period("M")
    monthly_high = df["high"].groupby(periods).max()
    current_period = df.index[-1].to_period("M")
    level_by_period: dict[pd.Period, tuple[float, float, int]] = {}
    n = 0
    sx = 0.0
    sx2 = 0.0
    for p in sorted(set(periods)):
        s1, s2 = bd._vix_sigma_levels(n, sx, sx2)
        level_by_period[p] = (s1, s2, n)
        if p < current_period and p in monthly_high.index:
            mh = float(monthly_high.loc[p])
            if np.isfinite(mh) and mh > 0:
                z = math.log10(mh)
                n += 1
                sx += z
                sx2 += z * z
    df["sigma1"] = [level_by_period[p][0] for p in periods]
    df["sigma2"] = [level_by_period[p][1] for p in periods]
    df["n_months"] = [level_by_period[p][2] for p in periods]
    df = df[df["n_months"] >= bd.VIX_CYCLE_MIN_MONTHS].copy()

    state = 0
    event_peak = None
    days_in_event = 0
    rollover_seen = False
    bottom_seen = False
    post_bottom_extreme = False
    prev_w5 = prev_w10 = prev_high = None
    event_date = rollover_date = None
    labels = []
    signals: list[dict] = []
    for d, r in df.iterrows():
        if any(pd.isna(r[k]) for k in ("high", "wma5", "wma10", "sigma1", "sigma2")):
            labels.append((d, None))
            continue
        ds = pd.Timestamp(d).strftime("%Y-%m-%d")
        vh, w5, w10 = float(r["high"]), float(r["wma5"]), float(r["wma10"])
        s1, s2 = float(r["sigma1"]), float(r["sigma2"])
        bottom_signal = False
        if state == 0 and prev_high is not None and prev_high <= s1 and s1 < vh <= s2:
            signals.append({"date": ds, "type": "WATCH", "value": vh})
        if state == 0:
            if vh > s2:
                state = 1
                event_peak = vh
                days_in_event = 0
                rollover_seen = False
                bottom_seen = False
                post_bottom_extreme = False
                event_date, rollover_date = ds, None
                signals.append({"date": ds, "type": "EVENT", "value": vh})
        else:
            days_in_event += 1
            event_peak = vh if event_peak is None else max(event_peak, vh)
            if not rollover_seen and prev_w5 is not None and w5 < prev_w5:
                rollover_seen = True
                rollover_date = ds
                if not bottom_seen:
                    state = 2
                signals.append({"date": ds, "type": "ROLLOVER", "value": vh})
            cross_down = (prev_w5 is not None and prev_w10 is not None
                          and w5 < w10 and prev_w5 >= prev_w10)
            if not bottom_seen and cross_down:
                bottom_seen = True
                state = 3
                bottom_signal = True
                signals.append({"date": ds, "type": "BOTTOM", "value": vh})
            if bottom_seen and not bottom_signal and not post_bottom_extreme and vh > s2:
                post_bottom_extreme = True
                signals.append({"date": ds, "type": "RE-EXTREME", "value": vh})
            if bottom_seen and not bottom_signal and vh < s1:
                state = 0
                signals.append({"date": ds, "type": "REARM", "value": vh})
                event_peak = None
                days_in_event = 0
                rollover_seen = False
                bottom_seen = False
                post_bottom_extreme = False
                event_date = rollover_date = None
        lab = ("NORMAL" if state == 0 else "EXTREME" if state == 1 else
               "ROLLOVER" if state == 2 else
               "RE-EXTREME" if post_bottom_extreme else "BOTTOM")
        labels.append((d, lab))
        prev_w5, prev_w10, prev_high = w5, w10, vh
    s = pd.Series({pd.Timestamp(d): lab for d, lab in labels}, name="vix_state", dtype="object")
    return s.sort_index(), signals


def indicators(qqq: pd.DataFrame) -> pd.DataFrame:
    c = qqq["Close"].astype(float)
    h = qqq["High"].astype(float)
    l = qqq["Low"].astype(float)
    v = qqq["Volume"].astype(float)
    prev = c.shift(1)
    tr = pd.concat([(h-l), (h-prev).abs(), (l-prev).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    ema21 = c.ewm(span=21, adjust=False, min_periods=21).mean()
    sma50 = c.rolling(50, min_periods=50).mean()
    tp = (h+l+c)/3.0
    vwap63 = (tp*v).rolling(63, min_periods=63).sum() / v.rolling(63, min_periods=63).sum()
    vwap252 = (tp*v).rolling(252, min_periods=200).sum() / v.rolling(252, min_periods=200).sum()
    out = pd.DataFrame(index=qqq.index)
    out["ema21_atr"] = (c-ema21)/atr
    out["sma50_atr"] = (c-sma50)/atr
    out["vwap63_atr"] = (c-vwap63)/atr
    out["vwap252_atr"] = (c-vwap252)/atr
    out["qqq_close"] = c
    out["atr14"] = atr
    return out


def tier_from_value(x: float, entries: tuple[float, float, float, float]) -> int:
    # entries are ordered shallow -> deep, e.g. (-0.5,-1.5,-2.5,-3.5)
    tier = 0
    for i, e in enumerate(entries, 1):
        if x <= e:
            tier = i
    return tier


def build_target(metric: pd.Series, entries: tuple[float,float,float,float], exit_level: float,
                 tactical: list[float], mc: pd.Series | None = None, mc_gate: float | None = None,
                 vix_state: pd.Series | None = None, vix_mode: str = "none") -> pd.Series:
    idx = metric.index
    mc2 = mc.reindex(idx).ffill() if mc is not None else pd.Series(np.nan, index=idx)
    vs = vix_state.reindex(idx).ffill() if vix_state is not None else pd.Series("NORMAL", index=idx)
    pos = []
    held_tier = 0
    for d, x in metric.items():
        state = str(vs.loc[d]) if pd.notna(vs.loc[d]) else "NORMAL"
        panic = state in ("EXTREME", "ROLLOVER", "BOTTOM", "RE-EXTREME")
        if pd.isna(x):
            pos.append(CORE + (tactical[held_tier-1] if held_tier else 0.0))
            continue
        x = float(x)
        # Recovered enough: sell the tactical sleeve; core remains.
        if held_tier > 0 and x >= exit_level:
            held_tier = 0
        desired = tier_from_value(x, entries)
        if desired > held_tier:
            allow = True
            if mc_gate is not None:
                mv = mc2.loc[d]
                allow = pd.notna(mv) and float(mv) >= float(mc_gate)
                if panic and vix_mode != "none":
                    allow = True
            if allow:
                held_tier = desired

        # VIX is only a panic-buy override. It never forces a reduction.
        min_tier = 0
        if vix_mode == "phase1":
            min_tier = {"EXTREME":1, "ROLLOVER":2, "BOTTOM":3, "RE-EXTREME":4}.get(state, 0)
        elif vix_mode == "phase2":
            min_tier = {"EXTREME":2, "ROLLOVER":3, "BOTTOM":4, "RE-EXTREME":4}.get(state, 0)
        elif vix_mode == "bottom_only":
            min_tier = {"BOTTOM":4, "RE-EXTREME":4}.get(state, 0)
        if min_tier > held_tier:
            held_tier = min_tier
        pos.append(CORE + (tactical[held_tier-1] if held_tier else 0.0))
    return pd.Series(pos, index=idx, name="target", dtype=float).clip(CORE, 1.0)


def strategy_returns(target_close: pd.Series, tqqq_open: pd.Series, cost_bps: float=COST_BPS) -> pd.Series:
    # Signal is known after close t. Rebalance at next session open t+1.
    # Open-to-open return on day t is Open_t/Open_{t-1}-1, so it uses target from close t-2.
    r = tqqq_open.pct_change()
    eff = target_close.shift(2).reindex(r.index)
    turnover = target_close.diff().abs().shift(2).reindex(r.index).fillna(0.0)
    out = eff * r - turnover * (cost_bps/10000.0)
    return out.dropna()


def fixed_returns(weight: float, tqqq_open: pd.Series) -> pd.Series:
    return (weight * tqqq_open.pct_change()).dropna()


def stats(ret: pd.Series, start=None, end=None) -> dict:
    x = ret.copy().dropna()
    if start is not None:
        x = x[x.index >= pd.Timestamp(start)]
    if end is not None:
        x = x[x.index <= pd.Timestamp(end)]
    if len(x) < 30:
        return {"n":len(x), "cagr":np.nan, "mdd":np.nan, "calmar":np.nan, "total":np.nan, "vol":np.nan}
    eq = (1.0+x).cumprod()
    years = max((x.index[-1]-x.index[0]).days/365.25, len(x)/252.0)
    cagr = float(eq.iloc[-1]**(1.0/years)-1.0)
    dd = eq/eq.cummax()-1.0
    mdd = float(dd.min())
    calmar = cagr/abs(mdd) if mdd < 0 else np.nan
    vol = float(x.std(ddof=0)*np.sqrt(252))
    return {"n":len(x), "cagr":cagr, "mdd":mdd, "calmar":calmar,
            "total":float(eq.iloc[-1]-1.0), "vol":vol}


def add_stats(row: dict, ret: pd.Series) -> dict:
    for prefix, a, b in (("full", START, None), ("is", START, IS_END), ("oos", OOS_START, None),
                         ("post13", pd.Timestamp("2013-01-01"), None)):
        s = stats(ret, a, b)
        for k,v in s.items():
            row[f"{prefix}_{k}"] = v
    return row


def fmt(s: dict) -> str:
    return (f"CAGR={s['cagr']*100:6.2f}%  MDD={s['mdd']*100:7.2f}%  "
            f"Calmar={s['calmar']:.3f}  Total={s['total']*100:,.0f}%")


def main():
    print("=== TQQQ CORE30 + DEVIATION LADDER BACKTEST ===", flush=True)
    qqq = dl_one("QQQ", "2009-01-01")
    tqqq = dl_one("TQQQ", "2010-01-01")
    vix = dl_one("^VIX", "1990-01-01")
    mc, mc_cov = compute_mc()
    vstate, vsignals = vix_state_series(vix)
    ind = indicators(qqq)

    common = ind.index.intersection(tqqq.index)
    ind = ind.reindex(common)
    tqqq = tqqq.reindex(common)
    mc = mc.reindex(common).ffill()
    mc_cov = mc_cov.reindex(common).ffill()
    vstate = vstate.reindex(common).ffill()
    mask = common >= START
    ind = ind.loc[mask]
    tqqq = tqqq.loc[mask]
    mc = mc.loc[mask]
    mc_cov = mc_cov.loc[mask]
    vstate = vstate.loc[mask]

    print(f"[data] test dates: {ind.index[0].date()}..{ind.index[-1].date()} ({len(ind)} sessions)")
    print(f"[data] MC coverage: start={mc_cov.iloc[0]:.1f}% median={mc_cov.median():.1f}% latest={mc_cov.iloc[-1]:.1f}%")
    sig2011 = [s for s in vsignals if s['date'] >= START.strftime('%Y-%m-%d')]
    counts = pd.Series([s['type'] for s in sig2011]).value_counts().to_dict() if sig2011 else {}
    print(f"[data] VIX sequence signals since 2011: {counts}")

    bench = {}
    for w in (0.30, 0.50, 1.00):
        r = fixed_returns(w, tqqq["Open"])
        bench[f"TQQQ_{int(w*100)}"] = stats(r, START, None)
        print(f"[bench] TQQQ static {int(w*100):3d}%: {fmt(bench[f'TQQQ_{int(w*100)}'])}")

    # Stage 1: pure technical grid. No MC/VIX modifiers, so thresholds are learned without
    # forcing a preconceived regime rule.
    results = []
    combos = list(itertools.combinations(ENTRY_LEVELS, 4))
    # itertools keeps shallow -> deep because list is descending numerically.
    print(f"[grid] stage1 configs = {len(combos)*len(EXIT_LEVELS)*len(ALLOC_SHAPES)*4}", flush=True)
    for metric_name in ["ema21_atr", "sma50_atr", "vwap63_atr", "vwap252_atr"]:
        metric = ind[metric_name]
        for entries in combos:
            entries = tuple(float(x) for x in entries)
            for ex in EXIT_LEVELS:
                for shape, tactical in ALLOC_SHAPES.items():
                    target = build_target(metric, entries, float(ex), tactical)
                    ret = strategy_returns(target, tqqq["Open"])
                    row = {"stage":"technical", "metric":metric_name, "entries":"/".join(map(str,entries)),
                           "exit":float(ex), "shape":shape, "mc_gate":None, "vix_mode":"none",
                           "avg_exposure":float(target.mean()), "turnover":float(target.diff().abs().sum())}
                    results.append(add_stats(row, ret))
    d1 = pd.DataFrame(results)
    d1.to_csv("tqqq_stage1_grid.csv", index=False)

    # Print objective-neutral frontier slices instead of pretending one arbitrary utility is truth.
    print("\n=== STAGE1: MAX CAGR SUBJECT TO FULL-SAMPLE MDD LIMIT ===")
    for lim in (0.40,0.50,0.60,0.70):
        q = d1[d1["full_mdd"] >= -lim].sort_values(["full_cagr","full_calmar"], ascending=False).head(1)
        if len(q):
            r=q.iloc[0]
            print(f"MDD <= {lim*100:.0f}%: {r.metric} entries={r.entries} exit=+{r.exit} shape={r.shape} "
                  f"CAGR={r.full_cagr*100:.2f}% MDD={r.full_mdd*100:.2f}% Calmar={r.full_calmar:.3f} avgExp={r.avg_exposure*100:.1f}%")
    print("\n=== STAGE1: BEST FULL CALMAR ===")
    for _,r in d1.sort_values(["full_calmar","full_cagr"],ascending=False).head(10).iterrows():
        print(f"{r.metric:12s} entries={r.entries:20s} exit=+{r.exit:<3} {r.shape:6s} "
              f"CAGR={r.full_cagr*100:6.2f}% MDD={r.full_mdd*100:7.2f}% Calmar={r.full_calmar:.3f} "
              f"IS={r.is_cagr*100:6.2f}%/{r.is_mdd*100:7.2f}% OOS={r.oos_cagr*100:6.2f}%/{r.oos_mdd*100:7.2f}%")

    # Candidate union is selected from IS only for the actual regime test, avoiding OOS-based parameter selection.
    is_candidates = []
    is_candidates += list(d1.sort_values(["is_calmar","is_cagr"],ascending=False).head(25).index)
    is_candidates += list(d1.sort_values(["is_cagr","is_calmar"],ascending=False).head(25).index)
    for lim in (0.40,0.50,0.60,0.70):
        is_candidates += list(d1[d1["is_mdd"] >= -lim].sort_values(["is_cagr","is_calmar"],ascending=False).head(15).index)
    is_candidates = sorted(set(is_candidates))
    print(f"\n[grid] stage2 IS-selected base configs = {len(is_candidates)}", flush=True)

    stage2 = []
    mc_gates = [None, 35.0, 45.0, 55.0]
    vix_modes = ["none", "phase1", "phase2", "bottom_only"]
    for ix in is_candidates:
        base = d1.loc[ix]
        metric = ind[str(base.metric)]
        entries = tuple(float(x) for x in str(base.entries).split("/"))
        ex = float(base.exit)
        tactical = ALLOC_SHAPES[str(base.shape)]
        for mg in mc_gates:
            for vm in vix_modes:
                target = build_target(metric, entries, ex, tactical, mc=mc, mc_gate=mg,
                                      vix_state=vstate, vix_mode=vm)
                ret = strategy_returns(target, tqqq["Open"])
                row = {"stage":"regime", "metric":base.metric, "entries":base.entries,
                       "exit":ex, "shape":base.shape, "mc_gate":mg, "vix_mode":vm,
                       "avg_exposure":float(target.mean()), "turnover":float(target.diff().abs().sum())}
                stage2.append(add_stats(row, ret))
    d2 = pd.DataFrame(stage2)
    d2.to_csv("tqqq_stage2_regime.csv", index=False)

    print("\n=== STAGE2: IS RANKED TOP 15, WITH OOS SHOWN UNTOUCHED ===")
    top_is = d2.sort_values(["is_calmar","is_cagr"],ascending=False).head(15)
    for _,r in top_is.iterrows():
        mg = "none" if pd.isna(r.mc_gate) else f">={int(r.mc_gate)}"
        print(f"{r.metric:12s} {r.entries:20s} exit=+{r.exit:<3} {r.shape:6s} MC={mg:5s} VIX={r.vix_mode:11s} "
              f"IS {r.is_cagr*100:6.2f}%/{r.is_mdd*100:7.2f}% C={r.is_calmar:.3f} | "
              f"OOS {r.oos_cagr*100:6.2f}%/{r.oos_mdd*100:7.2f}% C={r.oos_calmar:.3f} | "
              f"FULL {r.full_cagr*100:6.2f}%/{r.full_mdd*100:7.2f}%")

    print("\n=== STAGE2: OOS RESULTS OF THE 15 IS-SELECTED WINNERS (diagnostic only) ===")
    for _,r in top_is.sort_values(["oos_calmar","oos_cagr"],ascending=False).iterrows():
        mg = "none" if pd.isna(r.mc_gate) else f">={int(r.mc_gate)}"
        print(f"{r.metric:12s} {r.entries:20s} exit=+{r.exit:<3} {r.shape:6s} MC={mg:5s} VIX={r.vix_mode:11s} "
              f"OOS CAGR={r.oos_cagr*100:6.2f}% MDD={r.oos_mdd*100:7.2f}% Calmar={r.oos_calmar:.3f}")

    # Best OOS among IS-selected top-15 is *not* treated as a clean OOS selection; saved only for inspection.
    # Also save the single best IS-calmar model's position path so panic episodes can be audited.
    best = top_is.iloc[0]
    mg = None if pd.isna(best.mc_gate) else float(best.mc_gate)
    target = build_target(ind[str(best.metric)], tuple(float(x) for x in str(best.entries).split("/")),
                          float(best.exit), ALLOC_SHAPES[str(best.shape)], mc=mc, mc_gate=mg,
                          vix_state=vstate, vix_mode=str(best.vix_mode))
    audit = pd.DataFrame({
        "QQQ": ind["qqq_close"], "metric": ind[str(best.metric)], "MC":mc,
        "MC_coverage":mc_cov, "VIX_state":vstate, "TQQQ_target":target,
    })
    audit.to_csv("tqqq_best_position_audit.csv")

    # Event audit: target and subsequent QQQ/TQQQ returns around each EVENT/BOTTOM since 2011.
    events = pd.DataFrame(sig2011)
    if len(events):
        events.to_csv("tqqq_vix_signals.csv", index=False)

    summary = {
        "asof": str(ind.index[-1].date()),
        "start": str(ind.index[0].date()),
        "sessions": int(len(ind)),
        "cost_bps": COST_BPS,
        "execution": "signal at close; rebalance next session open; open-to-open returns",
        "benchmarks": bench,
        "mc_coverage_start": float(mc_cov.iloc[0]),
        "mc_coverage_median": float(mc_cov.median()),
        "mc_coverage_latest": float(mc_cov.iloc[-1]),
        "vix_signal_counts": counts,
        "best_is_regime": {k:(None if pd.isna(v) else (float(v) if isinstance(v,(np.floating,float)) else int(v) if isinstance(v,(np.integer,)) else v)) for k,v in best.to_dict().items()},
        "n_stage1": int(len(d1)),
        "n_stage2": int(len(d2)),
        "nqsar_note": "Exact long-history NQ-SAR is not stored in current repo; trend_history.json begins 2026-06-25, so NQ-SAR is intentionally not reconstructed or backfilled here.",
    }
    Path("tqqq_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print("\n=== MACHINE SUMMARY ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
