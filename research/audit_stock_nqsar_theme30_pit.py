from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf

import build_dashboard as bd
import build_v38_strict_loo_live as loo
from v38_rules import clinical_biotech_exclusion, peer_theme_score

PIT_EFFECTIVE = pd.Timestamp("2026-06-22")
ANALYSIS_END = pd.Timestamp("2026-09-04")
N_PORT = 12
SELECTIVE = 4
RS_MIN = 85.0
DDV_POOL = 10_000_000.0
DDV_ENTRY = 20_000_000.0


def finite(x: Any) -> bool:
    try:
        return math.isfinite(float(x))
    except Exception:
        return False


def safe(x: Any) -> Any:
    if isinstance(x, dict):
        return {str(k): safe(v) for k, v in x.items()}
    if isinstance(x, list):
        return [safe(v) for v in x]
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating, float)):
        z = float(x)
        return z if math.isfinite(z) else None
    if isinstance(x, pd.Timestamp):
        return str(x.date())
    return x


def load_universe(path: Path) -> tuple[list[str], set[str]]:
    u = pd.read_csv(path)
    sym_col = "シンボル" if "シンボル" in u.columns else u.columns[0]
    symbols = [str(x).strip().upper() for x in u[sym_col] if str(x).strip() and str(x).strip().lower() != "nan"]
    symbols = list(dict.fromkeys(symbols))
    ind_col = "業種" if "業種" in u.columns else None
    mc_col = "時価総額" if "時価総額" in u.columns else None
    rev_col = "売上高TTM" if "売上高TTM" in u.columns else None
    excluded: set[str] = set()
    if ind_col and mc_col and rev_col:
        for _, row in u.iterrows():
            s = str(row[sym_col]).strip().upper()
            if not s or s.lower() == "nan":
                continue
            d = clinical_biotech_exclusion(row.get(ind_col), row.get(mc_col), row.get(rev_col))
            if d.excluded:
                excluded.add(s)
    return symbols, excluded


def ys(s: str) -> str:
    return s.replace(".", "-")


def download_ohlcv(symbols: list[str], start: str, end: str, batch_size: int) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    fields = {k: [] for k in ("open", "high", "low", "close", "volume")}
    failed = 0
    requested = list(dict.fromkeys(symbols))
    for pos in range(0, len(requested), batch_size):
        batch = requested[pos:pos + batch_size]
        names = [ys(s) for s in batch]
        reverse = {ys(s): s for s in batch}
        try:
            raw = yf.download(names, start=start, end=end, auto_adjust=True, actions=False,
                              progress=False, group_by="ticker", threads=True, timeout=30)
        except Exception as exc:
            print(f"STOCK_DOWNLOAD_FAIL pos={pos} {type(exc).__name__}", flush=True)
            failed += 1
            continue
        if raw is None or raw.empty:
            failed += 1
            continue
        bucket = {k: {} for k in fields}
        if isinstance(raw.columns, pd.MultiIndex):
            level0 = set(str(x) for x in raw.columns.get_level_values(0))
            for name in names:
                if name not in level0:
                    continue
                part = raw[name]
                sym = reverse[name]
                for k, field in (("open", "Open"), ("high", "High"), ("low", "Low"), ("close", "Close"), ("volume", "Volume")):
                    if field in part.columns:
                        z = pd.to_numeric(part[field], errors="coerce")
                        if z.notna().any():
                            bucket[k][sym] = z
        elif len(batch) == 1:
            sym = batch[0]
            for k, field in (("open", "Open"), ("high", "High"), ("low", "Low"), ("close", "Close"), ("volume", "Volume")):
                if field in raw.columns:
                    z = pd.to_numeric(raw[field], errors="coerce")
                    if z.notna().any():
                        bucket[k][sym] = z
        for k in fields:
            if bucket[k]:
                fields[k].append(pd.DataFrame(bucket[k]))
        if pos % (batch_size * 5) == 0 or pos + batch_size >= len(requested):
            print(f"STOCK_DOWNLOAD {min(pos + batch_size, len(requested))}/{len(requested)}", flush=True)
    out: dict[str, pd.DataFrame] = {}
    for k, parts in fields.items():
        f = pd.concat(parts, axis=1) if parts else pd.DataFrame()
        if not f.empty:
            f.index = pd.to_datetime(f.index).tz_localize(None).normalize()
            f = f.loc[:, ~f.columns.duplicated(keep="last")].sort_index().replace([np.inf, -np.inf], np.nan)
        out[k] = f
    common = [s for s in requested if all(s in out[k].columns and out[k][s].notna().any() for k in out)]
    for k in out:
        out[k] = out[k].reindex(columns=common)
    return out, {"requested": len(requested), "downloaded_common": len(common), "coverage": len(common) / max(1, len(requested)), "failed_batches": failed}


def exact_nqsar(high: pd.DataFrame, low: pd.DataFrame, close: pd.DataFrame, min_rows: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    bull = pd.DataFrame(False, index=close.index, columns=close.columns, dtype=bool)
    red = pd.DataFrame(False, index=close.index, columns=close.columns, dtype=bool)
    good = 0
    for j, s in enumerate(close.columns, 1):
        z = pd.DataFrame({"h": high[s], "l": low[s], "c": close[s]}).dropna()
        if len(z) < min_rows:
            continue
        h, l, c = z.h.to_numpy(float), z.l.to_numpy(float), z.c.to_numpy(float)
        sar = bd._psar(h, l, c, step=0.02, mx=0.08)
        ema21 = z.c.ewm(span=21, adjust=False).mean().to_numpy(float)
        d = z.c.diff(); up = d.clip(lower=0); dn = -d.clip(upper=0)
        ru = up.ewm(alpha=1/14, adjust=False).mean(); rd = dn.ewm(alpha=1/14, adjust=False).mean()
        rsi = (100.0 - 100.0 / (1.0 + ru / rd)).to_numpy(float)
        bd._onimine_state(c, sar, ema21, rsi)
        colors = list(bd._LAST_ONIMINE_SERIES or [])
        if len(colors) != len(z):
            continue
        bull.loc[z.index, s] = [str(x) in {"Blue", "Green"} for x in colors]
        red.loc[z.index, s] = [str(x) == "Red" for x in colors]
        good += 1
        if j % 500 == 0 or j == len(close.columns):
            print(f"STOCK_NQSAR {j}/{len(close.columns)} good={good}", flush=True)
    return bull, red


def period_ohlc_completed(high: pd.DataFrame, low: pd.DataFrame, close: pd.DataFrame, freq: str, last_asof: pd.Timestamp):
    period = close.index.to_period(freq)
    h = high.groupby(period).max(); l = low.groupby(period).min(); c = close.groupby(period).last()
    actual = pd.Series(close.index, index=period).groupby(level=0).max()
    keep = []
    for p in c.index:
        if freq.startswith("W"):
            keep.append(pd.Timestamp(p.end_time).normalize() <= last_asof)
        else:
            keep.append(pd.Timestamp(p.end_time).normalize() <= last_asof)
    h = h.loc[keep]; l = l.loc[keep]; c = c.loc[keep]
    actual = actual.reindex(c.index)
    idx = pd.DatetimeIndex(actual.to_numpy())
    h.index = idx; l.index = idx; c.index = idx
    return h, l, c


def completed_to_daily(frame: pd.DataFrame, daily_index: pd.DatetimeIndex) -> pd.DataFrame:
    return frame.reindex(daily_index).ffill().fillna(False).astype(bool)


def market_nqsar(start: str, end: str) -> pd.DataFrame:
    raw = yf.download("NQ=F", start=start, end=end, auto_adjust=False, progress=False, threads=False)
    if isinstance(raw.columns, pd.MultiIndex):
        if "NQ=F" in raw.columns.get_level_values(-1):
            raw = raw.xs("NQ=F", axis=1, level=-1)
        else:
            raw.columns = raw.columns.get_level_values(0)
    raw.index = pd.to_datetime(raw.index).tz_localize(None).normalize()
    z = raw[["High", "Low", "Close"]].astype(float).dropna().sort_index()
    h, l, c = z.High.to_numpy(float), z.Low.to_numpy(float), z.Close.to_numpy(float)
    sar = bd._psar(h, l, c, step=0.02, mx=0.08)
    ema21 = z.Close.ewm(span=21, adjust=False).mean().to_numpy(float)
    d = z.Close.diff(); up = d.clip(lower=0); dn = -d.clip(upper=0)
    ru = up.ewm(alpha=1/14, adjust=False).mean(); rd = dn.ewm(alpha=1/14, adjust=False).mean()
    rsi = (100.0 - 100.0 / (1.0 + ru / rd)).to_numpy(float)
    bd._onimine_state(c, sar, ema21, rsi)
    colors = list(bd._LAST_ONIMINE_SERIES or [])
    return pd.DataFrame({"nq_color": colors}, index=z.index)


def mode(color: Any, breadth: Any) -> str:
    c = str(color or "").title()
    if c == "Red": return "DEFENSE"
    if c != "Blue" and c != "Green": return "STOP"
    if not finite(breadth): return "STOP"
    b = float(breadth)
    if b >= 60: return "ATTACK"
    if b >= 50: return "SELECTIVE"
    return "STOP"


def theme_scores_by_date(theme_close: pd.DataFrame, s2t: dict[str, list[str]], end_asof: pd.Timestamp, target_symbols: list[str]):
    sessions = list(theme_close.index[(theme_close.index >= PIT_EFFECTIVE) & (theme_close.index <= end_asof)])
    if len(sessions) < 21:
        raise RuntimeError("PIT sessions < 21")
    snapshots: dict[str, dict[str, Any]] = {}
    target = set(target_symbols)
    score_by_date: dict[pd.Timestamp, dict[str, float]] = {}
    for i, d in enumerate(sessions):
        if i < 20:
            continue
        oldd = sessions[i-20]
        for x in (oldd, d):
            key = str(pd.Timestamp(x).date())
            if key not in snapshots:
                print(f"PIT_SNAPSHOT {key}", flush=True)
                snapshots[key] = loo.compute_session_snapshot(theme_close, s2t, pd.Timestamp(x))
        history = {
            "schema": "v38-strict-loo-history-1",
            "sessions": [snapshots[str(pd.Timestamp(oldd).date())], snapshots[str(pd.Timestamp(d).date())]],
            "covered_market_sessions": i + 1,
            "coverage_start_asof": str(PIT_EFFECTIVE.date()),
            "coverage_end_asof": str(pd.Timestamp(d).date()),
        }
        live = loo.build_live(history, s2t, snapshots[str(pd.Timestamp(d).date())], str(pd.Timestamp(oldd).date()))
        day_scores: dict[str, float] = {}
        for s in target:
            rec = live.get("candidates", {}).get(s, {})
            themes = rec.get("themes", {}) if isinstance(rec, dict) else {}
            best = None
            if isinstance(themes, dict):
                for _, r in themes.items():
                    if not isinstance(r, dict): continue
                    try:
                        sc = peer_theme_score(r["theme_rs63_pct"], r["acceleration20_pct"], r["breadth21_pct"])
                    except Exception:
                        continue
                    best = sc if best is None else max(best, sc)
            day_scores[s] = 50.0 if best is None else float(best)
        score_by_date[pd.Timestamp(d)] = day_scores
        print(f"PIT_SCORE {pd.Timestamp(d).date()} targets={len(day_scores)}", flush=True)
    return score_by_date, {"pit_market_sessions": len(sessions), "scored_sessions": len(score_by_date), "first_scored": str(min(score_by_date).date()), "last_scored": str(max(score_by_date).date()), "computed_snapshots": len(snapshots)}


def build_stock_inputs(ohlcv: dict[str, pd.DataFrame], bio_excluded: set[str], analysis_end: pd.Timestamp):
    close, volume = ohlcv["close"], ohlcv["volume"]
    sma50 = close.rolling(50, min_periods=50).mean(); sma200 = close.rolling(200, min_periods=200).mean()
    vol20 = volume.rolling(20, min_periods=20).mean(); ddv = close * vol20
    base_pool = (close >= 5.0) & (ddv >= DDV_POOL)
    ex = [s for s in bio_excluded if s in base_pool.columns]
    if ex: base_pool.loc[:, ex] = False
    ret63 = close / close.shift(63) - 1.0; ret189 = close / close.shift(189) - 1.0
    rs63 = ret63.where(base_pool).rank(axis=1, pct=True) * 100.0
    rs189 = ret189.where(base_pool).rank(axis=1, pct=True) * 100.0
    elig = base_pool & (sma50 > sma200) & (close > sma200) & (rs63 >= RS_MIN) & (rs189 >= RS_MIN)
    nobs = close.notna().sum(axis=1); valid = sma50.notna().sum(axis=1)
    floor = max(5, min(30, int(max(1, close.shape[1]) * .20)))
    breadth = close.gt(sma50).sum(axis=1) / valid.replace(0, np.nan) * 100.0
    breadth = breadth.where(valid >= np.maximum(floor, nobs * .45))
    print("NQSAR DAILY", flush=True)
    day_bull, day_red = exact_nqsar(ohlcv["high"], ohlcv["low"], close, 60)
    print("NQSAR WEEKLY", flush=True)
    wh, wl, wc = period_ohlc_completed(ohlcv["high"], ohlcv["low"], close, "W-FRI", analysis_end)
    wb0, wr0 = exact_nqsar(wh, wl, wc, 30)
    week_bull = completed_to_daily(wb0, close.index); week_red = completed_to_daily(wr0, close.index)
    print("NQSAR MONTHLY", flush=True)
    mh, ml, mc = period_ohlc_completed(ohlcv["high"], ohlcv["low"], close, "M", analysis_end)
    mb0, mr0 = exact_nqsar(mh, ml, mc, 24)
    month_bull = completed_to_daily(mb0, close.index); month_red = completed_to_daily(mr0, close.index)
    return {"open": ohlcv["open"], "close": close, "ddv": ddv, "rs63": rs63, "rs189": rs189,
            "eligible": elig, "breadth": breadth, "day_bull": day_bull, "day_red": day_red,
            "week_bull": week_bull, "week_red": week_red, "month_bull": month_bull, "month_red": month_red}


def ranked(date: pd.Timestamp, variant: str, mx: dict[str, pd.DataFrame], theme_scores: dict[pd.Timestamp, dict[str, float]], market_mode: str):
    elig = mx["eligible"].loc[date].fillna(False)
    rs = pd.to_numeric(mx["rs189"].loc[date], errors="coerce")
    ddv = pd.to_numeric(mx["ddv"].loc[date], errors="coerce")
    wb = mx["week_bull"].loc[date].fillna(False); db = mx["day_bull"].loc[date].fillna(False)
    mr = mx["month_red"].loc[date].fillna(False)
    mask = elig & rs.notna()
    if variant == "WEEK_GATE": mask &= wb
    rows = []
    ts = theme_scores.get(date, {})
    for s in rs.index[mask]:
        r = float(rs[s]); th = float(ts.get(str(s), 50.0))
        score = .70 * r + .30 * th if market_mode == "ATTACK" else r
        rows.append({"symbol": str(s), "score": score, "rs189": r, "theme30": th,
                     "week_bull": bool(wb[s]), "day_bull": bool(db[s]), "month_not_red": not bool(mr[s]),
                     "ddv": float(ddv[s]) if finite(ddv[s]) else None})
    if variant in {"CURRENT", "WEEK_GATE"}:
        key = lambda x: (x["score"], x["rs189"])
    elif variant == "WEEK_PRIORITY":
        key = lambda x: (x["week_bull"], x["score"], x["rs189"])
    elif variant == "DAY_PRIORITY":
        key = lambda x: (x["day_bull"], x["score"], x["rs189"])
    elif variant == "WEEK_MONTH_NOT_RED_PRIORITY":
        key = lambda x: (x["week_bull"] and x["month_not_red"], x["week_bull"], x["score"], x["rs189"])
    else:
        raise ValueError(variant)
    rows.sort(key=key, reverse=True)
    top12 = rows[:N_PORT]
    liquid = [r for r in top12 if r["ddv"] is not None and r["ddv"] >= DDV_ENTRY]
    return liquid, top12


def simulate(variant: str, idx: pd.DatetimeIndex, mx: dict[str, pd.DataFrame], theme_scores, nq: pd.DataFrame, cost_bps: float = 0.0):
    cost = cost_bps / 10000.0
    cash = 1.0; pos: dict[str, dict[str, Any]] = {}; navs = []; trades = []; entries = []; exposures = []
    opens, closes = mx["open"], mx["close"]
    def px(frame, d, s, fallback=None):
        try:
            z = float(frame.at[d, s]); return z if math.isfinite(z) and z > 0 else fallback
        except Exception: return fallback
    def finish(s, d, p, reason):
        nonlocal cash
        rec = pos.pop(s); proceeds = rec["shares"] * p * (1-cost); cash += proceeds
        realized = rec["realized"] + proceeds
        trades.append({"symbol": s, "entry_date": rec["entry_date"], "exit_date": d,
                       "return": realized / rec["cost_basis"] - 1.0, "reason": reason,
                       "partial": rec["partial"], "entry_week_bull": rec["entry_week_bull"],
                       "entry_theme30": rec["entry_theme30"]})
    for i, d0 in enumerate(idx):
        d = pd.Timestamp(d0); prev = pd.Timestamp(idx[i-1]) if i else None
        if prev is not None:
            color = str(nq.at[prev, "nq_color"]) if prev in nq.index and pd.notna(nq.at[prev, "nq_color"]) else ""
            mm = mode(color, mx["breadth"].get(prev, np.nan))
            for s in list(pos):
                rec = pos.get(s)
                if rec is None: continue
                pc = px(closes, prev, s, rec["entry_price"]); op = px(opens, d, s, pc)
                if pc is None or op is None: continue
                if color.title() == "Red": finish(s, d, op, "RED"); continue
                stop = max(rec["entry_price"] * .92, rec["peak"] * .70)
                if pc <= stop:
                    finish(s, d, op, "INITIAL_STOP" if rec["entry_price"]*.92 >= rec["peak"]*.70 else "PEAK30_STOP"); continue
                if (not rec["partial"]) and pc >= rec["entry_price"] * 1.24:
                    sell = min(rec["initial_shares"]*.25, rec["shares"])
                    proceeds = sell * op * (1-cost); rec["shares"] -= sell; rec["realized"] += proceeds; rec["partial"] = True; cash += proceeds
            cap = N_PORT if mm == "ATTACK" else SELECTIVE if mm == "SELECTIVE" else 0
            if cap > len(pos) and prev in theme_scores:
                cands, _ = ranked(prev, variant, mx, theme_scores, mm)
                nav_open = cash
                for s, rec in pos.items():
                    op = px(opens, d, s, px(closes, prev, s, rec["entry_price"]))
                    if op is not None: nav_open += rec["shares"] * op
                slot_cash = nav_open / N_PORT
                for c in cands:
                    if len(pos) >= cap or cash <= 1e-12: break
                    s = c["symbol"]
                    if s in pos: continue
                    op = px(opens, d, s, px(closes, prev, s, None))
                    if op is None: continue
                    alloc = min(slot_cash, cash)
                    shares = alloc / (op * (1+cost)); cash -= alloc
                    pos[s] = {"shares": shares, "initial_shares": shares, "entry_price": op, "entry_date": d,
                              "peak": op, "partial": False, "realized": 0.0, "cost_basis": alloc,
                              "entry_week_bull": c["week_bull"], "entry_theme30": c["theme30"]}
                    entries.append({"signal_date": prev, "entry_date": d, **c, "market_mode": mm})
        nav = cash; invested = 0.0
        for s, rec in pos.items():
            cp = px(closes, d, s, px(opens, d, s, rec["entry_price"])) or rec["entry_price"]
            rec["peak"] = max(rec["peak"], cp); val = rec["shares"] * cp; invested += val; nav += val
        navs.append((d, nav)); exposures.append((d, invested/nav if nav > 0 else 0.0))
    eq = pd.Series(dict(navs), dtype=float).sort_index(); exp = pd.Series(dict(exposures), dtype=float).sort_index()
    ret = eq.pct_change(fill_method=None).dropna(); dd = eq/eq.cummax()-1
    metrics = {"days": len(eq), "total_return": float(eq.iloc[-1]/eq.iloc[0]-1), "mdd": float(dd.min()),
               "daily_sharpe_ann": float(ret.mean()/ret.std(ddof=1)*np.sqrt(252)) if len(ret)>2 and ret.std(ddof=1)>0 else None,
               "avg_exposure": float(exp.mean()), "entries": len(entries), "closed_trades": len(trades), "open_positions_end": len(pos)}
    return {"equity": eq, "entries": pd.DataFrame(entries), "trades": pd.DataFrame(trades), "metrics": metrics}


def forward_selection_stats(idx, mx, theme_scores, nq, variants):
    rows = []
    closes, opens = mx["close"], mx["open"]
    posmap = {pd.Timestamp(d): i for i, d in enumerate(idx)}
    for d in idx[:-1]:
        if d not in theme_scores: continue
        color = str(nq.at[d, "nq_color"]) if d in nq.index and pd.notna(nq.at[d, "nq_color"]) else ""
        mm = mode(color, mx["breadth"].get(d, np.nan))
        if mm not in {"ATTACK", "SELECTIVE"}: continue
        for v in variants:
            liquid, top12 = ranked(d, v, mx, theme_scores, mm)
            for rank, c in enumerate(liquid, 1):
                i = posmap.get(pd.Timestamp(d)); entry_i = i+1 if i is not None else None
                if entry_i is None or entry_i >= len(idx): continue
                ed = pd.Timestamp(idx[entry_i]); ep = opens.at[ed, c["symbol"]] if c["symbol"] in opens.columns else np.nan
                rec = {"variant": v, "signal_date": d, "symbol": c["symbol"], "rank": rank, "market_mode": mm,
                       "week_bull": c["week_bull"], "theme30": c["theme30"]}
                for h in (5,10,20):
                    j = entry_i + h - 1
                    cp = closes.at[pd.Timestamp(idx[j]), c["symbol"]] if j < len(idx) and c["symbol"] in closes.columns else np.nan
                    rec[f"fwd{h}"] = float(cp/ep-1) if finite(ep) and finite(cp) and float(ep)>0 else None
                rows.append(rec)
    df = pd.DataFrame(rows); summary = []
    for v in variants:
        g = df[df.variant == v]
        r = {"variant": v, "selections": len(g), "dates": int(g.signal_date.nunique()) if len(g) else 0,
             "week_bull_share": float(g.week_bull.mean()) if len(g) else None, "theme30_mean": float(g.theme30.mean()) if len(g) else None}
        for h in (5,10,20):
            z = pd.to_numeric(g[f"fwd{h}"], errors="coerce").dropna()
            r[f"fwd{h}_n"] = len(z); r[f"fwd{h}_mean"] = float(z.mean()) if len(z) else None
            r[f"fwd{h}_median"] = float(z.median()) if len(z) else None; r[f"fwd{h}_win"] = float((z>0).mean()) if len(z) else None
        summary.append(r)
    return df, pd.DataFrame(summary)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--root", default="."); ap.add_argument("--output", required=True); ap.add_argument("--batch-size", type=int, default=100)
    args = ap.parse_args(); root = Path(args.root); out = root/args.output; out.mkdir(parents=True, exist_ok=True)
    hist = json.loads((root/"v38-strict-loo-history.json").read_text(encoding="utf-8"))
    snaps = hist.get("taxonomy_snapshots", [])
    if len(snaps) != 1 or str(snaps[0].get("effective_asof")) != str(PIT_EFFECTIVE.date()):
        raise RuntimeError(f"unexpected PIT taxonomy snapshots {[(x.get('effective_asof'), x.get('last_seen_asof')) for x in snaps]}")
    s2t = snaps[0]["s2t"]
    symbols, bio_excluded = load_universe(root/"universe.csv")
    stock_start = "2024-01-01"; end_excl = "2026-09-05"
    print("DOWNLOAD STOCK OHLCV", flush=True)
    ohlcv, stock_diag = download_ohlcv(symbols, stock_start, end_excl, args.batch_size)
    if stock_diag["coverage"] < .85: raise RuntimeError(f"stock coverage low {stock_diag}")
    stock_symbols = list(ohlcv["close"].columns)
    print("DOWNLOAD PIT THEME CLOSE", flush=True)
    theme_symbols = sorted(s2t)
    theme_close, theme_diag = loo.download_adjusted_close(theme_symbols, "2026-01-01", end_excl, args.batch_size)
    if float(theme_diag.get("coverage") or 0) < .85: raise RuntimeError(f"theme coverage low {theme_diag}")
    print("BUILD STOCK INPUTS", flush=True)
    mx = build_stock_inputs(ohlcv, bio_excluded, ANALYSIS_END)
    print("BUILD PIT THEME SCORES", flush=True)
    theme_scores, pit_diag = theme_scores_by_date(theme_close, s2t, ANALYSIS_END, stock_symbols)
    nq = market_nqsar("2026-03-01", end_excl).reindex(mx["close"].index).ffill(limit=2)
    first = max(min(theme_scores), PIT_EFFECTIVE)
    idx = mx["close"].index[(mx["close"].index >= first) & (mx["close"].index <= ANALYSIS_END)]
    idx = pd.DatetimeIndex([d for d in idx if d in theme_scores or d > min(theme_scores)])
    variants = ["CURRENT", "WEEK_PRIORITY", "WEEK_GATE", "DAY_PRIORITY", "WEEK_MONTH_NOT_RED_PRIORITY"]
    results = {}; metrics = []
    for v in variants:
        print("SIM", v, flush=True); r = simulate(v, idx, mx, theme_scores, nq, 0.0); results[v] = r; metrics.append({"variant": v, **r["metrics"]})
    cost_rows = []
    for v in ("CURRENT", "WEEK_PRIORITY"):
        for bps in (10.0, 25.0):
            print("COST", v, bps, flush=True); r = simulate(v, idx, mx, theme_scores, nq, bps); cost_rows.append({"variant": v, "cost_bps_per_side": bps, **r["metrics"]})
    sel_df, sel_summary = forward_selection_stats(idx, mx, theme_scores, nq, variants)
    overlap_rows = []
    for d in idx:
        if d not in theme_scores: continue
        color = str(nq.at[d, "nq_color"]) if d in nq.index and pd.notna(nq.at[d, "nq_color"]) else ""; mm = mode(color, mx["breadth"].get(d, np.nan))
        if mm not in {"ATTACK","SELECTIVE"}: continue
        _, b = ranked(d, "CURRENT", mx, theme_scores, mm); _, w = ranked(d, "WEEK_PRIORITY", mx, theme_scores, mm)
        bs = {x["symbol"] for x in b}; ws = {x["symbol"] for x in w}
        overlap_rows.append({"date": d, "market_mode": mm, "baseline_top12": len(bs), "week_top12": len(ws), "overlap": len(bs&ws),
                             "overlap_pct": len(bs&ws)/max(1,len(bs)), "baseline_week_bull_share": np.mean([x["week_bull"] for x in b]) if b else None})
    pd.DataFrame(metrics).to_csv(out/"portfolio_metrics.csv", index=False)
    pd.DataFrame(cost_rows).to_csv(out/"cost_stress.csv", index=False)
    sel_summary.to_csv(out/"selection_forward_summary.csv", index=False); sel_df.to_csv(out/"selection_rows.csv", index=False)
    pd.DataFrame(overlap_rows).to_csv(out/"top12_overlap.csv", index=False)
    for v, r in results.items():
        r["equity"].rename("equity").to_csv(out/f"equity_{v}.csv")
        r["entries"].to_csv(out/f"entries_{v}.csv", index=False)
        r["trades"].to_csv(out/f"trades_{v}.csv", index=False)
    summary = {"methodology": {"pit_taxonomy_effective": str(PIT_EFFECTIVE.date()), "pit_pre_effective_used": False,
        "attack_rank": "0.70*RS189 + 0.30*strict LOO Peer Theme Full3; missing valid theme neutral 50 after PIT readiness",
        "selective_rank": "RS189", "entry_liquidity": "rank DDV>=10M pool -> Top12 -> DDV>=20M; no backfill below Top12",
        "stock_nqsar": "same PSAR(.02,.08)+EMA21+Wilder RSI14+bd._onimine_state; weekly/monthly completed bars only",
        "exit": "close -8% initial; +24% partial25 next open; remaining PeakClose-30%; market NQSAR Red next open",
        "early1": "excluded/held outside audit to isolate ordinary Core candidate selection"},
        "stock_download": stock_diag, "theme_download": theme_diag, "pit": pit_diag, "analysis_first": str(idx.min().date()), "analysis_last": str(idx.max().date()),
        "portfolio": metrics, "cost_stress": cost_rows, "selection_forward": safe(sel_summary.to_dict("records")), "top12_overlap": safe(pd.DataFrame(overlap_rows).to_dict("records"))}
    (out/"summary.json").write_text(json.dumps(safe(summary), ensure_ascii=False, indent=2), encoding="utf-8")
    print("DONE_PIT", json.dumps({"stock": stock_diag, "theme": theme_diag, "pit": pit_diag, "days": len(idx)}, ensure_ascii=False), flush=True)

if __name__ == "__main__": main()
