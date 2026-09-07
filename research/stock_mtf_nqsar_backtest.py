from __future__ import annotations

import argparse
import json
import math
import re
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf

import build_dashboard as bd

N_PORT = 12
DVOL_FLOOR = 10_000_000.0
RS_MIN = 85.0
DISC_END = pd.Timestamp("2021-12-31")
CONF_START = pd.Timestamp("2022-01-03")
BIO_EXCLUDE_INDUSTRIES = {"Biotechnology", "Pharmaceuticals: Other"}
BIO_KEEP_MCAP = 10_000_000_000.0
BIO_REVENUE_MAX = 50_000_000.0
TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-/]{0,9}$")

PRIMARY_VARIANTS = ["V0", "V1_WEEK", "V2_MONTH", "V3_ALIGN", "V4_BULL_BULL_GATE", "V5_BEAR_BEAR_EXCLUDE"]
VARIANT_DESCRIPTIONS = {
    "V0": "RS189 controlled baseline; no stock MTF overlay",
    "V1_WEEK": "weekly Bull priority, then RS189",
    "V2_MONTH": "monthly Bull priority, then RS189",
    "V3_ALIGN": "Bull/Bull first, then number of Bull timeframes, then RS189",
    "V4_BULL_BULL_GATE": "hard gate: weekly Bull AND monthly Bull; rank by RS189",
    "V5_BEAR_BEAR_EXCLUDE": "exclude Bear/Bear; then V3 alignment priority",
}


def safe(x: Any) -> Any:
    if isinstance(x, dict):
        return {str(k): safe(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [safe(v) for v in x]
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, (np.floating, float)):
        z = float(x)
        return z if math.isfinite(z) else None
    if isinstance(x, pd.Timestamp):
        return x.isoformat()
    return x


def yahoo_symbol(symbol: str) -> str:
    return symbol.replace(".", "-")


def load_symbols_and_bio(root: Path, max_tickers: int) -> tuple[list[str], set[str], dict[str, Any]]:
    u = pd.read_csv(root / "universe.csv")
    sym_col = "シンボル" if "シンボル" in u.columns else u.columns[0]
    u[sym_col] = u[sym_col].astype(str).str.strip().str.upper()
    u = u[u[sym_col].map(lambda s: bool(TICKER_RE.fullmatch(s)))].drop_duplicates(sym_col)

    s2t_symbols: set[str] = set()
    try:
        snap = json.loads((root / "sector_snapshot.json").read_text(encoding="utf-8"))
        node = snap.get("s2t") if isinstance(snap, dict) else None
        if isinstance(node, dict):
            s2t_symbols = {str(k).strip().upper() for k in node if TICKER_RE.fullmatch(str(k).strip().upper())}
    except Exception:
        pass
    if s2t_symbols:
        u = u[u[sym_col].isin(s2t_symbols)]

    if max_tickers and len(u) > max_tickers:
        mc_col = "時価総額" if "時価総額" in u.columns else None
        if mc_col:
            u["__mc"] = pd.to_numeric(u[mc_col], errors="coerce")
            u = u.sort_values(["__mc", sym_col], ascending=[False, True]).head(max_tickers)
        else:
            u = u.sort_values(sym_col).head(max_tickers)

    symbols = u[sym_col].tolist()
    bio: set[str] = set()
    ind_col = "業種" if "業種" in u.columns else None
    mc_col = "時価総額" if "時価総額" in u.columns else None
    rev_col = "売上高TTM" if "売上高TTM" in u.columns else None
    if ind_col and mc_col and rev_col:
        ind = u[ind_col].astype(str)
        mc = pd.to_numeric(u[mc_col], errors="coerce")
        rev = pd.to_numeric(u[rev_col], errors="coerce")
        mask = ind.isin(BIO_EXCLUDE_INDUSTRIES) & (mc < BIO_KEEP_MCAP) & rev.notna() & (rev < BIO_REVENUE_MAX)
        bio = set(u.loc[mask, sym_col])
    return symbols, bio, {"universe_rows": int(len(u)), "s2t_filter_used": bool(s2t_symbols), "bio_excluded": int(len(bio))}


def _extract_batch(raw: pd.DataFrame, names: list[str], reverse: dict[str, str]) -> dict[str, dict[str, pd.Series]]:
    out: dict[str, dict[str, pd.Series]] = {k: {} for k in ("open", "high", "low", "close", "volume")}
    if raw is None or raw.empty:
        return out
    if isinstance(raw.columns, pd.MultiIndex):
        level0 = set(str(x) for x in raw.columns.get_level_values(0))
        for name in names:
            if name not in level0:
                continue
            part = raw[name]
            sym = reverse.get(name)
            if not sym:
                continue
            for field, key in (("Open", "open"), ("High", "high"), ("Low", "low"), ("Close", "close"), ("Volume", "volume")):
                if field in part.columns:
                    s = pd.to_numeric(part[field], errors="coerce")
                    if s.notna().any():
                        out[key][sym] = s
    elif len(names) == 1:
        sym = reverse[names[0]]
        for field, key in (("Open", "open"), ("High", "high"), ("Low", "low"), ("Close", "close"), ("Volume", "volume")):
            if field in raw.columns:
                s = pd.to_numeric(raw[field], errors="coerce")
                if s.notna().any():
                    out[key][sym] = s
    return out


def download_ohlcv(symbols: list[str], start: str, end: str, batch_size: int) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    pieces: dict[str, list[pd.DataFrame]] = {k: [] for k in ("open", "high", "low", "close", "volume")}
    failed_batches = 0
    requested = list(dict.fromkeys(symbols))
    for pos in range(0, len(requested), batch_size):
        batch = requested[pos:pos + batch_size]
        names = [yahoo_symbol(s) for s in batch]
        reverse = {yahoo_symbol(s): s for s in batch}
        raw = None
        last_err = None
        for attempt in range(2):
            try:
                raw = yf.download(
                    names, start=start, end=end, auto_adjust=True, actions=False,
                    progress=False, group_by="ticker", threads=True, timeout=30,
                )
                if raw is not None and not raw.empty:
                    break
            except Exception as exc:
                last_err = exc
            time.sleep(1.0 + attempt)
        got = _extract_batch(raw, names, reverse) if raw is not None else {k: {} for k in pieces}
        if not got["close"]:
            failed_batches += 1
            print(f"DOWNLOAD_BATCH_FAILED pos={pos} err={type(last_err).__name__ if last_err else 'EMPTY'}", flush=True)
        for key in pieces:
            if got[key]:
                pieces[key].append(pd.DataFrame(got[key]))
        if (pos // batch_size) % 5 == 0 or pos + batch_size >= len(requested):
            print(f"DOWNLOAD {min(pos + batch_size, len(requested))}/{len(requested)}", flush=True)

    frames: dict[str, pd.DataFrame] = {}
    for key, arr in pieces.items():
        frame = pd.concat(arr, axis=1) if arr else pd.DataFrame()
        if not frame.empty:
            idx = pd.to_datetime(frame.index)
            try:
                idx = idx.tz_localize(None)
            except TypeError:
                idx = idx.tz_convert(None)
            frame.index = idx.normalize()
            frame = frame.loc[:, ~frame.columns.duplicated(keep="last")].sort_index().replace([np.inf, -np.inf], np.nan)
        frames[key] = frame

    close = frames["close"]
    if close.empty:
        raise RuntimeError("No usable OHLCV data")
    common = [s for s in requested if s in close.columns and close[s].notna().sum() >= 252]
    if len(common) < 500:
        raise RuntimeError(f"downloaded stock coverage too small: {len(common)}")
    for key in frames:
        frames[key] = frames[key].reindex(columns=common)
    diag = {
        "requested": len(requested), "downloaded": len(common), "failed_batches": failed_batches,
        "coverage": len(common) / len(requested) if requested else None,
    }
    return frames, diag


def download_nqsar(start: str, end: str) -> pd.DataFrame:
    raw = yf.download("NQ=F", start=start, end=end, auto_adjust=False, progress=False, threads=False, timeout=30)
    if raw is None or raw.empty:
        raise RuntimeError("NQ=F download empty")
    if isinstance(raw.columns, pd.MultiIndex):
        if "NQ=F" in raw.columns.get_level_values(-1):
            raw = raw.xs("NQ=F", axis=1, level=-1)
        else:
            raw.columns = raw.columns.get_level_values(0)
    raw.index = pd.to_datetime(raw.index)
    try:
        raw.index = raw.index.tz_localize(None)
    except TypeError:
        raw.index = raw.index.tz_convert(None)
    raw.index = raw.index.normalize()
    df = raw[["High", "Low", "Close"]].apply(pd.to_numeric, errors="coerce").dropna()
    h, l, c = df.High.to_numpy(float), df.Low.to_numpy(float), df.Close.to_numpy(float)
    sar = bd._psar(h, l, c, step=0.02, mx=0.08)
    ema21 = df.Close.ewm(span=21, adjust=False).mean().to_numpy(float)
    d = df.Close.diff()
    up = d.clip(lower=0)
    dn = -d.clip(upper=0)
    ru = up.ewm(alpha=1 / 14, adjust=False).mean()
    rd = dn.ewm(alpha=1 / 14, adjust=False).mean()
    rsi = (100.0 - 100.0 / (1.0 + ru / rd)).to_numpy(float)
    bd._onimine_state(c, sar, ema21, rsi)
    colors = list(bd._LAST_ONIMINE_SERIES or [])
    if len(colors) != len(df):
        raise RuntimeError(f"NQSAR length mismatch {len(colors)} != {len(df)}")
    return pd.DataFrame({"nq_color": colors}, index=df.index)


def period_last(close: pd.DataFrame, freq: str) -> pd.DataFrame:
    periods = close.index.to_period(freq)
    out = close.groupby(periods).last()
    actual = pd.Series(close.index, index=periods).groupby(level=0).max()
    out.index = pd.DatetimeIndex(actual.reindex(out.index).to_numpy())
    return out


def mtf_states(close: pd.DataFrame, weekly=(10, 30, 4), monthly=(10, 20, 3)) -> dict[str, pd.DataFrame]:
    wfast, wslow, wslope = weekly
    mfast, mslow, mslope = monthly
    wc = period_last(close, "W-FRI")
    mc = period_last(close, "M")
    w1 = wc.rolling(wfast, min_periods=wfast).mean()
    w2 = wc.rolling(wslow, min_periods=wslow).mean()
    m1 = mc.rolling(mfast, min_periods=mfast).mean()
    m2 = mc.rolling(mslow, min_periods=mslow).mean()
    wb = (wc > w1) & (w1 > w2) & (w2 > w2.shift(wslope))
    wr = (wc < w2) & (w1 < w2) & (w2 < w2.shift(wslope))
    mb = (mc > m1) & (m1 > m2) & (m2 > m2.shift(mslope))
    mr = (mc < m2) & (m1 < m2) & (m2 < m2.shift(mslope))
    out = {}
    for name, frame in (("week_bull", wb), ("week_bear", wr), ("month_bull", mb), ("month_bear", mr)):
        out[name] = frame.reindex(close.index).ffill().fillna(False).astype(bool)
    return out


def metrics(equity: pd.Series) -> dict[str, Any]:
    e = pd.to_numeric(equity, errors="coerce").dropna()
    if len(e) < 5:
        return {"n": int(len(e))}
    r = e.pct_change(fill_method=None).dropna()
    years = max(len(r) / 252.0, 1 / 252.0)
    cagr = float((e.iloc[-1] / e.iloc[0]) ** (1 / years) - 1) if e.iloc[0] > 0 else np.nan
    dd = e / e.cummax() - 1
    sd = float(r.std(ddof=1)) if len(r) > 1 else np.nan
    sharpe = float(r.mean() / sd * np.sqrt(252)) if np.isfinite(sd) and sd > 0 else np.nan
    return {"n": len(e), "total_return": float(e.iloc[-1] / e.iloc[0] - 1), "cagr": cagr, "mdd": float(dd.min()), "sharpe": sharpe}


def slices(eq: pd.Series) -> dict[str, dict[str, Any]]:
    return {
        "full": metrics(eq),
        "discovery_2016_2021": metrics(eq.loc[eq.index <= DISC_END]),
        "confirmation_2022_plus": metrics(eq.loc[eq.index >= CONF_START]),
        "2016_2019": metrics(eq.loc[(eq.index >= "2016-01-01") & (eq.index <= "2019-12-31")]),
        "2020_2021": metrics(eq.loc[(eq.index >= "2020-01-01") & (eq.index <= "2021-12-31")]),
        "2022_2023": metrics(eq.loc[(eq.index >= "2022-01-01") & (eq.index <= "2023-12-31")]),
        "2024_plus": metrics(eq.loc[eq.index >= "2024-01-01"]),
    }


def breadth_bucket(x: Any) -> int:
    try:
        z = float(x)
    except Exception:
        return -1
    if not np.isfinite(z):
        return -1
    if z < 50:
        return 0
    if z < 60:
        return 1
    return 2


def market_mode(color: str, breadth: Any) -> str:
    c = str(color or "").title()
    if c == "Red":
        return "DEFENSE"
    if c == "Yellow" or c not in {"Blue", "Green"}:
        return "STOP"
    b = breadth_bucket(breadth)
    if b == 2:
        return "ATTACK"
    if b == 1:
        return "SELECTIVE"
    return "STOP"


def rank_candidates(d: pd.Timestamp, matrices: dict[str, pd.DataFrame], variant: str, n: int = N_PORT) -> list[str]:
    elig = matrices["eligible"].loc[d].fillna(False)
    rs = pd.to_numeric(matrices["rs189"].loc[d], errors="coerce")
    wb = matrices["week_bull"].loc[d].fillna(False)
    mb = matrices["month_bull"].loc[d].fillna(False)
    wr = matrices["week_bear"].loc[d].fillna(False)
    mr = matrices["month_bear"].loc[d].fillna(False)
    mask = elig & rs.notna()
    if variant == "V4_BULL_BULL_GATE":
        mask &= wb & mb
    elif variant.startswith("V5"):
        mask &= ~(wr & mr)
    z = pd.DataFrame({"rs": rs[mask], "wb": wb[mask].astype(int), "mb": mb[mask].astype(int)})
    if z.empty:
        return []
    z["bb"] = z.wb * z.mb
    z["nb"] = z.wb + z.mb
    if variant == "V0" or variant == "V4_BULL_BULL_GATE":
        z = z.sort_values(["rs"], ascending=False)
    elif variant == "V1_WEEK":
        z = z.sort_values(["wb", "rs"], ascending=False)
    elif variant == "V2_MONTH":
        z = z.sort_values(["mb", "rs"], ascending=False)
    else:
        z = z.sort_values(["bb", "nb", "rs"], ascending=False)
    return list(z.head(n).index)


def state_at(d: pd.Timestamp, sym: str, matrices: dict[str, pd.DataFrame]) -> str:
    wb = bool(matrices["week_bull"].at[d, sym])
    mb = bool(matrices["month_bull"].at[d, sym])
    wr = bool(matrices["week_bear"].at[d, sym])
    mr = bool(matrices["month_bear"].at[d, sym])
    if wb and mb:
        return "BULL_BULL"
    if wr and mr:
        return "BEAR_BEAR"
    if wb:
        return "WEEK_BULL_ONLY"
    if mb:
        return "MONTH_BULL_ONLY"
    return "MIXED_NEUTRAL"


def simulate(meta: dict[str, Any], matrices: dict[str, pd.DataFrame], variant: str, cost_bps: float = 0.0) -> dict[str, Any]:
    idx: pd.DatetimeIndex = meta["analysis_idx"]
    opens, closes = matrices["open"], matrices["close"]
    nq, breadth = meta["nq"], meta["breadth"]
    cost = max(0.0, float(cost_bps)) / 10000.0
    cash = 1.0
    pos: dict[str, dict[str, Any]] = {}
    equity_rows: list[tuple[pd.Timestamp, float]] = []
    trades: list[dict[str, Any]] = []
    date_pos = {pd.Timestamp(d): i for i, d in enumerate(idx)}

    def px(frame: pd.DataFrame, d: pd.Timestamp, s: str, fallback: float | None = None) -> float | None:
        try:
            z = float(frame.at[d, s])
            if np.isfinite(z) and z > 0:
                return z
        except Exception:
            pass
        return fallback

    def finish(s: str, d: pd.Timestamp, pprice: float, reason: str) -> None:
        nonlocal cash
        p = pos.pop(s)
        proceeds = float(p["shares"]) * pprice * (1.0 - cost)
        cash += proceeds
        realized = float(p["realized"]) + proceeds
        trades.append({
            "symbol": s, "entry_date": p["entry_date"], "exit_date": d,
            "entry_price": p["entry_price"], "exit_price": pprice,
            "return": realized / float(p["cost_basis"]) - 1.0,
            "partial_taken": bool(p["partial_taken"]), "exit_reason": reason,
            "hold_sessions": int(date_pos.get(d, 0) - date_pos.get(p["entry_date"], 0)),
            "entry_state": p["entry_state"], "entry_mode": p["entry_mode"],
            "max_close_return": float(p["peak"] / p["entry_price"] - 1.0),
        })

    for i, d0 in enumerate(idx):
        d = pd.Timestamp(d0)
        prev = pd.Timestamp(idx[i - 1]) if i else None
        if prev is not None:
            color = str(nq.at[prev, "nq_color"]) if prev in nq.index and pd.notna(nq.at[prev, "nq_color"]) else ""
            mode = market_mode(color, breadth.get(prev, np.nan))
            for s in list(pos):
                p = pos.get(s)
                if p is None:
                    continue
                pc = px(closes, prev, s, p["entry_price"])
                op = px(opens, d, s, pc)
                if pc is None or op is None:
                    continue
                if color.title() == "Red":
                    finish(s, d, op, "NQSAR_RED")
                    continue
                stop = max(float(p["entry_price"]) * 0.92, float(p["peak"]) * 0.70)
                if pc <= stop:
                    reason = "INITIAL_STOP" if float(p["entry_price"]) * 0.92 >= float(p["peak"]) * 0.70 else "PEAK30_STOP"
                    finish(s, d, op, reason)
                    continue
                if (not p["partial_taken"]) and pc >= float(p["entry_price"]) * 1.24:
                    sell_shares = min(float(p["initial_shares"]) * 0.25, float(p["shares"]))
                    proceeds = sell_shares * op * (1.0 - cost)
                    p["shares"] -= sell_shares
                    p["realized"] += proceeds
                    p["partial_taken"] = True
                    cash += proceeds

            capacity = 12 if mode == "ATTACK" else 4 if mode == "SELECTIVE" else 0
            if capacity > len(pos):
                cands = rank_candidates(prev, matrices, variant, N_PORT)
                nav_open = cash
                for s, p in pos.items():
                    op = px(opens, d, s, px(closes, prev, s, p["entry_price"]))
                    if op is not None:
                        nav_open += float(p["shares"]) * op
                slot_cash = nav_open / N_PORT
                for s in cands:
                    if len(pos) >= capacity or cash <= 1e-12:
                        break
                    if s in pos:
                        continue
                    op = px(opens, d, s, px(closes, prev, s, None))
                    if op is None:
                        continue
                    alloc = min(slot_cash, cash)
                    if alloc <= 1e-12:
                        break
                    shares = alloc / (op * (1.0 + cost))
                    cash -= alloc
                    pos[s] = {
                        "shares": shares, "initial_shares": shares, "cost_basis": alloc, "realized": 0.0,
                        "entry_price": op, "entry_date": d, "peak": op, "partial_taken": False,
                        "entry_state": state_at(prev, s, matrices), "entry_mode": mode,
                    }

        nav = cash
        for s, p in pos.items():
            cp = px(closes, d, s, px(opens, d, s, p["entry_price"]))
            if cp is None:
                cp = float(p["entry_price"])
            p["peak"] = max(float(p["peak"]), cp)
            nav += float(p["shares"]) * cp
        equity_rows.append((d, nav))

    eq = pd.Series(dict(equity_rows), dtype=float).sort_index()
    tdf = pd.DataFrame(trades)
    return {"equity": eq, "metrics": slices(eq), "trades": tdf, "open_positions": len(pos)}


def trade_summary(tdf: pd.DataFrame) -> dict[str, Any]:
    if tdf.empty:
        return {"n": 0}
    r = pd.to_numeric(tdf["return"], errors="coerce").dropna()
    out = {
        "n": int(len(tdf)), "mean_return": float(r.mean()), "median_return": float(r.median()),
        "win_rate": float((r > 0).mean()), "partial_rate": float(tdf.partial_taken.mean()),
        "avg_hold_sessions": float(pd.to_numeric(tdf.hold_sessions, errors="coerce").mean()),
        "initial_stop_rate": float((tdf.exit_reason == "INITIAL_STOP").mean()),
        "peak30_stop_rate": float((tdf.exit_reason == "PEAK30_STOP").mean()),
        "red_exit_rate": float((tdf.exit_reason == "NQSAR_RED").mean()),
        "avg_max_close_return": float(pd.to_numeric(tdf.max_close_return, errors="coerce").mean()),
    }
    for st in ("BULL_BULL", "WEEK_BULL_ONLY", "MONTH_BULL_ONLY", "MIXED_NEUTRAL", "BEAR_BEAR"):
        g = tdf[tdf.entry_state == st]
        out[f"state_{st}_n"] = int(len(g))
        out[f"state_{st}_mean_return"] = float(g["return"].mean()) if len(g) else None
    return out


def candidate_state_stats(matrices: dict[str, pd.DataFrame], analysis_idx: pd.DatetimeIndex) -> pd.DataFrame:
    close = matrices["close"]
    eligible = matrices["eligible"]
    wb, mb = matrices["week_bull"], matrices["month_bull"]
    wr, mr = matrices["week_bear"], matrices["month_bear"]
    states = {
        "BULL_BULL": wb & mb,
        "BEAR_BEAR": wr & mr,
        "WEEK_BULL_ONLY": wb & ~mb & ~(wr & mr),
        "MONTH_BULL_ONLY": mb & ~wb & ~(wr & mr),
        "MIXED_NEUTRAL": ~(wb & mb) & ~(wr & mr) & ~wb & ~mb,
    }
    fwds = {h: close.shift(-h) / close - 1.0 for h in (5, 10, 20)}
    rows = []
    slice_defs = {
        "full": pd.Series(True, index=close.index),
        "discovery_2016_2021": pd.Series(close.index <= DISC_END, index=close.index),
        "confirmation_2022_plus": pd.Series(close.index >= CONF_START, index=close.index),
    }
    analysis_mask = pd.Series(close.index.isin(analysis_idx), index=close.index)
    for sl, rowmask in slice_defs.items():
        for st, sm in states.items():
            m = eligible & sm
            m = m.loc[rowmask & analysis_mask]
            record = {"slice": sl, "state": st, "signals": int(m.to_numpy(dtype=bool).sum())}
            for h, f in fwds.items():
                vals = f.loc[m.index].where(m).to_numpy(dtype=float)
                z = vals[np.isfinite(vals)]
                record[f"fwd{h}_n"] = int(len(z))
                record[f"fwd{h}_mean"] = float(np.mean(z)) if len(z) else None
                record[f"fwd{h}_median"] = float(np.median(z)) if len(z) else None
                record[f"fwd{h}_win"] = float(np.mean(z > 0)) if len(z) else None
            rows.append(record)
    return pd.DataFrame(rows)


def market_interactions(meta: dict[str, Any], matrices: dict[str, pd.DataFrame]) -> pd.DataFrame:
    idx = meta["analysis_idx"]
    close = matrices["close"]
    f20 = close.shift(-20) / close - 1.0
    elig = matrices["eligible"]
    wb, mb = matrices["week_bull"], matrices["month_bull"]
    wr, mr = matrices["week_bear"], matrices["month_bear"]
    states = {"BULL_BULL": wb & mb, "BEAR_BEAR": wr & mr, "ONE_OR_NEUTRAL": ~(wb & mb) & ~(wr & mr)}
    mode_series = pd.Series(index=idx, dtype=object)
    for d in idx:
        color = meta["nq"].at[d, "nq_color"] if d in meta["nq"].index and pd.notna(meta["nq"].at[d, "nq_color"]) else ""
        mode_series.at[d] = market_mode(color, meta["breadth"].get(d, np.nan))
    rows = []
    for mode in ("ATTACK", "SELECTIVE", "STOP", "DEFENSE"):
        dates = mode_series.index[mode_series == mode]
        if len(dates) == 0:
            continue
        for st, sm in states.items():
            m = elig.loc[dates] & sm.loc[dates]
            vals = f20.loc[dates].where(m).to_numpy(dtype=float)
            z = vals[np.isfinite(vals)]
            rows.append({"market_mode": mode, "state": st, "n": int(len(z)), "fwd20_mean": float(np.mean(z)) if len(z) else None, "fwd20_win": float(np.mean(z > 0)) if len(z) else None})
    return pd.DataFrame(rows)


def leader_miss_table(meta: dict[str, Any], matrices: dict[str, pd.DataFrame]) -> pd.DataFrame:
    close = matrices["close"]
    acc = {v: {"rejected": 0, "base_big": 0, "retained_big": 0, "rejected_big": 0, "rejected_50": 0, "maxes": []} for v in PRIMARY_VARIANTS[1:]}
    for d in meta["analysis_idx"]:
        color = meta["nq"].at[d, "nq_color"] if d in meta["nq"].index and pd.notna(meta["nq"].at[d, "nq_color"]) else ""
        if market_mode(color, meta["breadth"].get(d, np.nan)) not in {"ATTACK", "SELECTIVE"}:
            continue
        base = rank_candidates(d, matrices, "V0", N_PORT)
        if not base:
            continue
        loc = close.index.get_loc(d)
        future_end = min(len(close), loc + 127)
        base_future = {}
        for s in base:
            cur = close.at[d, s] if s in close.columns else np.nan
            fut = close[s].iloc[loc + 1:future_end] if s in close.columns else pd.Series(dtype=float)
            mx = float(fut.max() / cur - 1.0) if np.isfinite(cur) and cur > 0 and fut.notna().any() else np.nan
            base_future[s] = mx
        for v in PRIMARY_VARIANTS[1:]:
            selected = set(rank_candidates(d, matrices, v, N_PORT))
            for s, mx in base_future.items():
                if np.isfinite(mx) and mx >= 1.0:
                    acc[v]["base_big"] += 1
                    if s in selected:
                        acc[v]["retained_big"] += 1
                if s not in selected:
                    acc[v]["rejected"] += 1
                    if np.isfinite(mx):
                        acc[v]["maxes"].append(mx)
                        acc[v]["rejected_big"] += int(mx >= 1.0)
                        acc[v]["rejected_50"] += int(mx >= 0.5)
    rows = []
    for v, a in acc.items():
        rows.append({
            "variant": v, "rejected_baseline_top12": a["rejected"], "baseline_big_leader_instances": a["base_big"],
            "retained_big_leader_instances": a["retained_big"],
            "big_leader_retention": a["retained_big"] / a["base_big"] if a["base_big"] else None,
            "rejected_big_leader_instances": a["rejected_big"], "rejected_gt50_instances": a["rejected_50"],
            "rejected_future126_max_mean": float(np.mean(a["maxes"])) if a["maxes"] else None,
        })
    return pd.DataFrame(rows)


def block_bootstrap_prob_better(a: pd.Series, b: pd.Series, start: pd.Timestamp | None = None, block: int = 20, reps: int = 1000, seed: int = 20260907) -> float | None:
    x = pd.concat([a.pct_change(fill_method=None).rename("a"), b.pct_change(fill_method=None).rename("b")], axis=1).dropna()
    if start is not None:
        x = x.loc[x.index >= start]
    if len(x) < block * 5:
        return None
    diff = np.log1p(x.a.clip(lower=-0.999999)).to_numpy() - np.log1p(x.b.clip(lower=-0.999999)).to_numpy()
    starts = np.arange(0, len(diff) - block + 1)
    rng = np.random.default_rng(seed)
    wins = 0
    for _ in range(reps):
        total = 0.0
        n = 0
        while n < len(diff):
            s = int(rng.choice(starts))
            take = min(block, len(diff) - n)
            total += float(diff[s:s + take].sum())
            n += take
        wins += total > 0
    return wins / reps


def build_inputs(root: Path, analysis_start: str, analysis_end: str, max_tickers: int, batch_size: int, weekly: tuple[int, int, int], monthly: tuple[int, int, int]) -> tuple[dict[str, Any], dict[str, pd.DataFrame]]:
    symbols, bio_excluded, udiag = load_symbols_and_bio(root, max_tickers)
    warmup_start = str((pd.Timestamp(analysis_start) - pd.Timedelta(days=1200)).date())
    end_excl = str((pd.Timestamp(analysis_end) + pd.Timedelta(days=10)).date())
    ohlcv, ddiag = download_ohlcv(symbols, warmup_start, end_excl, batch_size)
    close, volume = ohlcv["close"], ohlcv["volume"]
    common = [s for s in close.columns if s in volume.columns]
    for k in ohlcv:
        ohlcv[k] = ohlcv[k].reindex(columns=common)
    close, volume = ohlcv["close"], ohlcv["volume"]
    sma50 = close.rolling(50, min_periods=50).mean()
    sma200 = close.rolling(200, min_periods=200).mean()
    vol20 = volume.rolling(20, min_periods=20).mean()
    dvol = close * vol20
    ret63 = close / close.shift(63) - 1.0
    ret189 = close / close.shift(189) - 1.0
    base_pool = (close >= 5.0) & (dvol >= DVOL_FLOOR)
    excols = [s for s in bio_excluded if s in base_pool.columns]
    if excols:
        base_pool.loc[:, excols] = False
    rs63 = ret63.where(base_pool & ret63.notna()).rank(axis=1, pct=True) * 100.0
    rs189 = ret189.where(base_pool & ret189.notna()).rank(axis=1, pct=True) * 100.0
    eligible = base_pool & (sma50 > sma200) & (close > sma200) & (rs63 >= RS_MIN) & (rs189 >= RS_MIN)

    nobs = close.notna().sum(axis=1)
    floor = max(5, min(30, int(max(1, close.shape[1]) * 0.20)))
    valid50 = sma50.notna().sum(axis=1)
    breadth = close.gt(sma50).sum(axis=1) / valid50.replace(0, np.nan) * 100.0
    breadth = breadth.where(valid50 >= np.maximum(floor, nobs * 0.45))

    states = mtf_states(close, weekly=weekly, monthly=monthly)
    analysis_idx = close.index[(close.index >= pd.Timestamp(analysis_start)) & (close.index <= pd.Timestamp(analysis_end))]
    if len(analysis_idx) < 1000:
        raise RuntimeError(f"analysis calendar too short {len(analysis_idx)}")
    nq = download_nqsar(str((pd.Timestamp(analysis_start) - pd.Timedelta(days=60)).date()), end_excl)
    nq = nq.reindex(close.index).ffill(limit=2)
    cov = float(nq.loc[analysis_idx, "nq_color"].notna().mean())
    if cov < 0.95:
        raise RuntimeError(f"NQSAR coverage too low {cov:.2%}")

    matrices = {"open": ohlcv["open"], "close": close, "rs63": rs63, "rs189": rs189, "eligible": eligible, **states}
    meta = {
        "analysis_idx": analysis_idx, "breadth": breadth, "nq": nq,
        "universe": {**udiag, **ddiag, "downloaded_common": len(common), "nqsar_coverage": cov},
        "weekly_params": weekly, "monthly_params": monthly,
    }
    return meta, matrices


def run_suite(meta: dict[str, Any], matrices: dict[str, pd.DataFrame]) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    results: dict[str, Any] = {}
    metric_rows, trade_rows = [], []
    for v in PRIMARY_VARIANTS:
        print(f"SIM {v}", flush=True)
        res = simulate(meta, matrices, v, 0.0)
        results[v] = res
        for sl, m in res["metrics"].items():
            metric_rows.append({"variant": v, "slice": sl, **m})
        trade_rows.append({"variant": v, **trade_summary(res["trades"]), "open_positions_end": res["open_positions"]})
    return results, pd.DataFrame(metric_rows), pd.DataFrame(trade_rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--output", required=True)
    ap.add_argument("--analysis-start", default="2016-01-04")
    ap.add_argument("--analysis-end", default="2026-09-04")
    ap.add_argument("--max-tickers", type=int, default=6000)
    ap.add_argument("--batch-size", type=int, default=100)
    args = ap.parse_args()
    root = Path(args.root)
    out = root / args.output
    out.mkdir(parents=True, exist_ok=True)

    meta, matrices = build_inputs(root, args.analysis_start, args.analysis_end, args.max_tickers, args.batch_size, weekly=(10, 30, 4), monthly=(10, 20, 3))
    results, variant_metrics, trade_stats = run_suite(meta, matrices)

    print("CANDIDATE STATE STATS", flush=True)
    cand = candidate_state_stats(matrices, meta["analysis_idx"])
    interaction = market_interactions(meta, matrices)
    print("LEADER MISS", flush=True)
    leader = leader_miss_table(meta, matrices)

    bootstrap_rows = []
    base_eq = results["V0"]["equity"]
    for v in PRIMARY_VARIANTS[1:]:
        for sl, start in (("full", None), ("confirmation_2022_plus", CONF_START)):
            bootstrap_rows.append({
                "variant": v, "slice": sl,
                "prob_outperform_v0_block20": block_bootstrap_prob_better(results[v]["equity"], base_eq, start=start, seed=20260907 + PRIMARY_VARIANTS.index(v) * 17 + (1 if start is not None else 0)),
            })
    bootstrap = pd.DataFrame(bootstrap_rows)

    cost_rows = []
    for v in ("V0", "V3_ALIGN", "V4_BULL_BULL_GATE", "V5_BEAR_BEAR_EXCLUDE"):
        for bps in (10.0, 25.0):
            print(f"COST_STRESS {v} {bps}bps", flush=True)
            r = simulate(meta, matrices, v, bps)
            m = r["metrics"]["confirmation_2022_plus"]
            cost_rows.append({"variant": v, "cost_bps_per_side": bps, **m})
    cost_stress = pd.DataFrame(cost_rows)

    sens_rows = []
    for name, wpar, mpar in (
        ("V5_FAST", (8, 24, 3), (8, 18, 2)),
        ("V5_SLOW", (12, 36, 6), (12, 24, 4)),
    ):
        print(f"SENSITIVITY {name}", flush=True)
        st = mtf_states(matrices["close"], weekly=wpar, monthly=mpar)
        mx = dict(matrices)
        mx.update(st)
        rr = simulate(meta, mx, "V5_BEAR_BEAR_EXCLUDE", 0.0)
        for sl in ("full", "confirmation_2022_plus"):
            sens_rows.append({"variant": name, "weekly": str(wpar), "monthly": str(mpar), "slice": sl, **rr["metrics"][sl]})
    sensitivity = pd.DataFrame(sens_rows)

    year_rows = []
    for v, res in results.items():
        eq = res["equity"]
        for year in range(pd.Timestamp(args.analysis_start).year, pd.Timestamp(args.analysis_end).year + 1):
            m = metrics(eq.loc[eq.index.year == year])
            year_rows.append({"variant": v, "year": year, **m})
    year_metrics = pd.DataFrame(year_rows)

    variant_metrics.to_csv(out / "variant_metrics.csv", index=False)
    trade_stats.to_csv(out / "trade_stats.csv", index=False)
    cand.to_csv(out / "candidate_state_stats.csv", index=False)
    interaction.to_csv(out / "market_interaction.csv", index=False)
    leader.to_csv(out / "leader_miss.csv", index=False)
    bootstrap.to_csv(out / "bootstrap.csv", index=False)
    cost_stress.to_csv(out / "cost_stress.csv", index=False)
    sensitivity.to_csv(out / "sensitivity.csv", index=False)
    year_metrics.to_csv(out / "year_metrics.csv", index=False)

    summary = {
        "methodology": {
            "purpose": "incremental Stock MTF trend value test; not a literal production V38 P&L reproduction",
            "market_gate": "audited NQSAR + all-stock 50MA breadth; Attack 12 / Selective 4 / Stop 0 / Red next-open exit",
            "eligibility": "Price>=5, 20d DDV>=10M, SMA50>SMA200, Close>SMA200, RS63>=85, RS189>=85, structural clinical biotech exclusion",
            "exit": "close-based -8% initial / +24% partial25 / PeakClose-30%, all next-open; Red next-open",
            "ranking_control": "RS189-only baseline across all variants to isolate MTF incremental value. Live Attack Theme30 is intentionally not backfilled with hindsight taxonomy.",
            "weekly_bull": "completed-week Close>SMA10>SMA30 and SMA30 rising vs 4 completed weeks ago",
            "weekly_bear": "completed-week Close<SMA30, SMA10<SMA30 and SMA30 falling vs 4 completed weeks ago",
            "monthly_bull": "completed-month Close>SMA10>SMA20 and SMA20 rising vs 3 completed months ago",
            "monthly_bear": "completed-month Close<SMA20, SMA10<SMA20 and SMA20 falling vs 3 completed months ago",
            "lookahead_guard": "week/month states become available only at actual last trading close of the completed period",
            "bias": "current-universe / survivor and current structural classification bias remain, matching the known upper-bound nature of prior V38 research",
        },
        "variant_descriptions": VARIANT_DESCRIPTIONS,
        "analysis_start": args.analysis_start, "analysis_end": args.analysis_end,
        "universe": meta["universe"], "weekly_params": meta["weekly_params"], "monthly_params": meta["monthly_params"],
        "primary_metrics": {v: safe(results[v]["metrics"]) for v in PRIMARY_VARIANTS},
        "trade_summary": {v: safe(trade_summary(results[v]["trades"])) for v in PRIMARY_VARIANTS},
        "bootstrap": safe(bootstrap.to_dict("records")),
        "leader_miss": safe(leader.to_dict("records")),
    }
    (out / "summary.json").write_text(json.dumps(safe(summary), ensure_ascii=False, indent=2), encoding="utf-8")
    print("DONE", json.dumps({"output": str(out), "universe": meta["universe"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
