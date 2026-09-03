from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import audit_ordinary_stock_market_mode_robustness as base
import audit_ordinary_stock_theme_leave_one_out as loo
import audit_ordinary_stock_exit_trail as ex
import audit_ordinary_stock_exit_overlays as ov


SELECTIVE_SLOTS = 4
PRIMARY_PEAK_PCT = 30
PRIMARY_OVERLAY = "PART25_R3"
ANNUAL_MIN_DVOL = 50_000_000.0
MEGA_MIN_DVOL = 200_000_000.0
ANNUAL_TOP_N = 20
ANNUAL_MIN_RETURN = 0.40
ROLLING_HORIZON = 126
ROLLING_MIN_MFE = 0.80
ROLLING_PERCENTILE = 0.98
ROLLING_COOLDOWN = 126


def safe(v: Any) -> Any:
    return base.safe(v)


def px(frame: pd.DataFrame, date: pd.Timestamp, sym: str, fallback: float | None = None) -> float | None:
    try:
        x = float(frame.at[date, sym])
        if np.isfinite(x) and x > 0:
            return x
    except Exception:
        pass
    return fallback


def current_candidates(
    d: pd.Timestamp,
    matrices: dict[str, pd.DataFrame],
    peer_ctx: dict[str, Any],
    bucket: int,
    use_theme: bool,
    n: int = base.N_PORT,
) -> list[tuple[str, dict[str, Any]]]:
    if use_theme:
        return ex.ranked_candidates(d, matrices, peer_ctx, bucket, n)
    elig = matrices["new_eligible"].loc[d]
    rs = matrices["rs189"].loc[d].where(elig).dropna().sort_values(ascending=False).head(n)
    return [
        (
            str(sym),
            {
                "stock_rs189": float(v),
                "peer_theme_score": None,
                "rank_score": float(v),
            },
        )
        for sym, v in rs.items()
    ]


def simulate_current_with_entries(
    meta: dict[str, Any],
    matrices: dict[str, pd.DataFrame],
    peer_ctx: dict[str, Any],
    use_theme: bool,
) -> dict[str, Any]:
    """Current normal-stock entry engine + adopted PEAK30_PART25_R3 exit, with entry/interval audit logs."""
    idx: pd.DatetimeIndex = meta["analysis_idx"]
    opens, closes = matrices["open"], matrices["close"]
    breadth, nq = meta["breadth"], meta["nq"]
    cash = 1.0
    pos: dict[str, dict[str, Any]] = {}
    equities: list[tuple[pd.Timestamp, float]] = []
    trades: list[dict[str, Any]] = []
    entries: list[dict[str, Any]] = []
    intervals: list[dict[str, Any]] = []
    red_run = 0
    variant = "LOO_THEME30" if use_theme else "STOCK_RS189"

    def close_position(sym: str, date: pd.Timestamp, price: float, reason: str) -> None:
        nonlocal cash
        p = pos.pop(sym)
        cash += p["shares"] * price
        rec = {
            "variant": variant,
            "symbol": sym,
            "entry_date": p["entry_date"],
            "exit_date": date,
            "entry_price": p["entry_price"],
            "exit_price": price,
            "return": price / p["entry_price"] - 1.0,
            "exit_reason": reason,
            "entry_bucket": p["entry_bucket"],
            "partial_done": p.get("partial_done", False),
            "stock_rs189": p.get("stock_rs189"),
            "peer_theme_score": p.get("peer_theme_score"),
            "rank_score": p.get("rank_score"),
        }
        trades.append(rec)
        intervals.append(dict(rec))

    for i, d0 in enumerate(idx):
        d = pd.Timestamp(d0)
        prev = None if i == 0 else pd.Timestamp(idx[i - 1])
        if prev is not None:
            color = str(nq.at[prev, "nq_color"]) if prev in nq.index and pd.notna(nq.at[prev, "nq_color"]) else ""
            red_run = red_run + 1 if color == "Red" else 0
            red_force = color == "Red" and red_run >= 1

            if red_force:
                for sym in list(pos):
                    opx = px(opens, d, sym, px(closes, prev, sym, pos[sym]["entry_price"]))
                    if opx is not None:
                        close_position(sym, d, opx, "RED")
            else:
                for sym in list(pos):
                    p = pos[sym]
                    pc = px(closes, prev, sym, p["entry_price"])
                    if pc is None:
                        continue
                    p["sessions"] += 1

                    if (not p["partial_done"]) and pc >= p["entry_price"] * 1.24:
                        opx = px(opens, d, sym, pc)
                        if opx is not None:
                            sold = p["shares"] * 0.25
                            cash += sold * opx
                            p["shares"] -= sold
                            p["partial_done"] = True

                    stop = p["entry_price"] * 0.92
                    reason = "HARD8"
                    peak_stop = p["peak_close"] * 0.70
                    if peak_stop > stop:
                        stop, reason = peak_stop, "PEAK30"
                    if pc <= stop:
                        opx = px(opens, d, sym, pc)
                        if opx is not None:
                            close_position(sym, d, opx, reason)

            b = float(breadth.loc[prev]) if prev in breadth.index and pd.notna(breadth.loc[prev]) else np.nan
            bucket = base.breadth_bucket(b)
            bull = color in ("Blue", "Green")
            cap = base.N_PORT if bull and bucket == 2 else SELECTIVE_SLOTS if bull and bucket == 1 else 0

            if (not red_force) and cap > 0 and len(pos) < cap:
                candidates = current_candidates(prev, matrices, peer_ctx, bucket, use_theme, base.N_PORT)
                nav_open = cash
                for sym, p in pos.items():
                    opx = px(opens, d, sym, px(closes, prev, sym, p["entry_price"]))
                    if opx is not None:
                        nav_open += p["shares"] * opx
                slot_cash = nav_open / base.N_PORT

                for rank0, (sym, c) in enumerate(candidates, start=1):
                    if len(pos) >= cap or cash <= 0:
                        break
                    if sym in pos:
                        continue
                    opx = px(opens, d, sym, px(closes, prev, sym, None))
                    if opx is None:
                        continue
                    alloc = min(slot_cash, cash)
                    if alloc <= 1e-10:
                        break
                    cash -= alloc
                    pos[sym] = {
                        "shares": alloc / opx,
                        "entry_price": opx,
                        "entry_date": d,
                        "peak_close": opx,
                        "entry_bucket": bucket,
                        "sessions": 0,
                        "partial_done": False,
                        **c,
                    }
                    entries.append(
                        {
                            "variant": variant,
                            "symbol": sym,
                            "signal_date": prev,
                            "entry_date": d,
                            "entry_price": opx,
                            "entry_bucket": bucket,
                            "candidate_rank": rank0,
                            **c,
                        }
                    )

        nav = cash
        for sym, p in pos.items():
            cp = px(closes, d, sym, px(opens, d, sym, p["entry_price"]))
            if cp is None:
                cp = p["entry_price"]
            p["peak_close"] = max(p["peak_close"], cp)
            nav += p["shares"] * cp
        equities.append((d, nav))

    last_date = pd.Timestamp(idx[-1]) if len(idx) else pd.NaT
    for sym, p in pos.items():
        intervals.append(
            {
                "variant": variant,
                "symbol": sym,
                "entry_date": p["entry_date"],
                "exit_date": pd.NaT,
                "entry_price": p["entry_price"],
                "exit_price": np.nan,
                "return": np.nan,
                "exit_reason": "OPEN",
                "entry_bucket": p["entry_bucket"],
                "partial_done": p.get("partial_done", False),
                "stock_rs189": p.get("stock_rs189"),
                "peer_theme_score": p.get("peer_theme_score"),
                "rank_score": p.get("rank_score"),
            }
        )

    eq = pd.Series(dict(equities), dtype=float).sort_index()
    return {
        "equity": eq,
        "entries": pd.DataFrame(entries),
        "trades": pd.DataFrame(trades),
        "intervals": pd.DataFrame(intervals),
        "open_positions": sorted(pos),
        "last_date": last_date,
    }


def validate_simulation(meta: dict[str, Any], matrices: dict[str, pd.DataFrame], peer_ctx: dict[str, Any], sim: dict[str, Any]) -> dict[str, Any]:
    """Exact guard: instrumented simulation must match the already-validated overlay implementation."""
    ref = ov.simulate(meta, matrices, peer_ctx, PRIMARY_PEAK_PCT, PRIMARY_OVERLAY)
    a, b = sim["equity"].align(ref["equity"], join="inner")
    if len(a) != len(ref["equity"]) or len(a) != len(sim["equity"]):
        raise RuntimeError("simulation validation failed: equity calendar mismatch")
    max_abs = float(np.nanmax(np.abs(a.to_numpy(float) - b.to_numpy(float)))) if len(a) else 0.0
    if not np.isfinite(max_abs) or max_abs > 1e-10:
        raise RuntimeError(f"simulation validation failed: equity max_abs={max_abs}")
    tr_a = sim["trades"].copy()
    tr_b = ref["trades"].copy()
    if len(tr_a) != len(tr_b):
        raise RuntimeError(f"simulation validation failed: trades {len(tr_a)} != {len(tr_b)}")
    if len(tr_a):
        keys = ["symbol", "entry_date", "exit_date", "exit_reason"]
        if not tr_a[keys].reset_index(drop=True).astype(str).equals(tr_b[keys].reset_index(drop=True).astype(str)):
            raise RuntimeError("simulation validation failed: trade identity mismatch")
        for c in ["entry_price", "exit_price", "return"]:
            xa = pd.to_numeric(tr_a[c], errors="coerce").to_numpy(float)
            xb = pd.to_numeric(tr_b[c], errors="coerce").to_numpy(float)
            if not np.allclose(xa, xb, equal_nan=True, rtol=0, atol=1e-10):
                raise RuntimeError(f"simulation validation failed: trade numeric mismatch {c}")
    return {
        "status": "PASS",
        "equity_max_abs_diff": max_abs,
        "closed_trades": int(len(tr_a)),
        "entries": int(len(sim["entries"])),
        "reference_variant": "PEAK30_PART25_R3",
    }


def period_first_last(frame: pd.DataFrame, dates: pd.DatetimeIndex) -> tuple[pd.Series, pd.Series, pd.Series]:
    sub = frame.reindex(dates)
    first = sub.bfill().iloc[0]
    last = sub.ffill().iloc[-1]
    coverage = sub.notna().sum()
    return first, last, coverage


def build_annual_leaders(
    matrices: dict[str, pd.DataFrame],
    leader_start: pd.Timestamp,
    analysis_end: pd.Timestamp,
) -> pd.DataFrame:
    close = matrices["close"]
    dvol = matrices["dvol"]
    rows: list[dict[str, Any]] = []
    years = list(range(leader_start.year, analysis_end.year + 1))

    for year in years:
        p0 = max(leader_start, pd.Timestamp(f"{year}-01-01"))
        p1 = min(analysis_end, pd.Timestamp(f"{year}-12-31"))
        dates = close.index[(close.index >= p0) & (close.index <= p1)]
        if len(dates) < 40:
            continue
        first, last, cov = period_first_last(close, dates)
        period_ret = last / first - 1.0
        min_cov = max(40, int(math.floor(len(dates) * 0.80)))
        early_dates = dates[: min(20, len(dates))]
        early_dvol = dvol.reindex(early_dates).median(axis=0, skipna=True)
        valid = (
            first.notna()
            & last.notna()
            & (first >= 5.0)
            & (cov >= min_cov)
            & (early_dvol >= ANNUAL_MIN_DVOL)
            & period_ret.notna()
            & (period_ret >= ANNUAL_MIN_RETURN)
        )
        ranked = period_ret.where(valid).dropna().sort_values(ascending=False).head(ANNUAL_TOP_N)
        for rank0, (sym, r) in enumerate(ranked.items(), start=1):
            s = close.loc[dates, sym].dropna()
            peak_date = pd.Timestamp(s.idxmax())
            peak_price = float(s.loc[peak_date])
            start_date = pd.Timestamp(s.index[0])
            start_price = float(s.iloc[0])
            rows.append(
                {
                    "leader_type": "ANNUAL_LIQUID",
                    "period": f"{year}" if p1.month == 12 else f"{year}YTD",
                    "rank": rank0,
                    "symbol": str(sym),
                    "start_date": start_date,
                    "end_date": p1,
                    "peak_date": peak_date,
                    "start_price": start_price,
                    "period_end_price": float(s.iloc[-1]),
                    "peak_price": peak_price,
                    "period_return": float(r),
                    "peak_return": peak_price / start_price - 1.0,
                    "early_dvol": float(early_dvol.loc[sym]),
                    "mega_liquid": bool(float(early_dvol.loc[sym]) >= MEGA_MIN_DVOL),
                    "coverage_sessions": int(cov.loc[sym]),
                    "period_sessions": int(len(dates)),
                }
            )
    return pd.DataFrame(rows)


def _future_max(close: pd.DataFrame, horizon: int) -> pd.DataFrame:
    rev = close.shift(-1).iloc[::-1]
    return rev.rolling(horizon, min_periods=max(20, horizon // 2)).max().iloc[::-1]


def build_rolling_superleaders(
    matrices: dict[str, pd.DataFrame],
    leader_start: pd.Timestamp,
    analysis_end: pd.Timestamp,
) -> pd.DataFrame:
    close = matrices["close"]
    dvol = matrices["dvol"]
    fmax = _future_max(close, ROLLING_HORIZON)
    mfe = fmax / close - 1.0
    pct = mfe.rank(axis=1, pct=True, method="average")
    tradable = (close >= 5.0) & (dvol >= ANNUAL_MIN_DVOL)
    cond = tradable & (mfe >= ROLLING_MIN_MFE) & (pct >= ROLLING_PERCENTILE)

    rows: list[dict[str, Any]] = []
    idx = close.index
    date_pos = {pd.Timestamp(d): i for i, d in enumerate(idx)}
    start_i = int(idx.searchsorted(leader_start))
    end_i = min(len(idx) - ROLLING_HORIZON - 1, int(idx.searchsorted(analysis_end, side="right") - 1))
    if end_i <= start_i:
        return pd.DataFrame()

    for sym in close.columns:
        vals = cond[sym].to_numpy(bool)
        last_event_i = -10_000
        for i in range(start_i, end_i + 1):
            if not vals[i]:
                continue
            prev_true = vals[i - 1] if i > 0 else False
            if prev_true:
                continue
            if i - last_event_i < ROLLING_COOLDOWN:
                continue
            j1 = min(len(idx), i + 1 + ROLLING_HORIZON)
            future = close.iloc[i + 1 : j1][sym].dropna()
            if future.empty:
                continue
            peak_date = pd.Timestamp(future.idxmax())
            peak_i = int(date_pos[peak_date])
            base_px = float(close.iat[i, close.columns.get_loc(sym)])
            peak_px = float(close.at[peak_date, sym])
            if not np.isfinite(base_px) or not np.isfinite(peak_px) or base_px <= 0:
                continue
            rows.append(
                {
                    "leader_type": "ROLLING_126_SUPERLEADER",
                    "period": str(pd.Timestamp(idx[i]).year),
                    "rank": np.nan,
                    "symbol": str(sym),
                    "start_date": pd.Timestamp(idx[i]),
                    "end_date": peak_date,
                    "peak_date": peak_date,
                    "start_price": base_px,
                    "period_end_price": peak_px,
                    "peak_price": peak_px,
                    "period_return": peak_px / base_px - 1.0,
                    "peak_return": peak_px / base_px - 1.0,
                    "early_dvol": float(dvol.iat[i, dvol.columns.get_loc(sym)]) if pd.notna(dvol.iat[i, dvol.columns.get_loc(sym)]) else np.nan,
                    "mega_liquid": bool(
                        pd.notna(dvol.iat[i, dvol.columns.get_loc(sym)])
                        and float(dvol.iat[i, dvol.columns.get_loc(sym)]) >= MEGA_MIN_DVOL
                    ),
                    "coverage_sessions": ROLLING_HORIZON,
                    "period_sessions": ROLLING_HORIZON,
                    "forward_mfe_percentile": float(pct.iat[i, pct.columns.get_loc(sym)]),
                }
            )
            last_event_i = i
    return pd.DataFrame(rows)


def find_overlap(intervals: pd.DataFrame, symbol: str, start: pd.Timestamp, peak: pd.Timestamp) -> pd.DataFrame:
    if intervals.empty:
        return intervals
    z = intervals.loc[intervals["symbol"].astype(str) == str(symbol)].copy()
    if z.empty:
        return z
    z["entry_date"] = pd.to_datetime(z["entry_date"])
    z["exit_date"] = pd.to_datetime(z["exit_date"], errors="coerce")
    active = (z["entry_date"] <= peak) & (z["exit_date"].isna() | (z["exit_date"] > start))
    return z.loc[active].sort_values("entry_date")


def candidate_passed_window(
    symbol: str,
    start: pd.Timestamp,
    peak: pd.Timestamp,
    matrices: dict[str, pd.DataFrame],
    meta: dict[str, Any],
    peer_ctx: dict[str, Any],
    use_theme: bool,
) -> tuple[bool, bool]:
    idx = meta["analysis_idx"]
    dates = idx[(idx >= start) & (idx < peak)]
    market_any = False
    rank_any = False
    for d0 in dates:
        d = pd.Timestamp(d0)
        color = str(meta["nq"].at[d, "nq_color"]) if d in meta["nq"].index and pd.notna(meta["nq"].at[d, "nq_color"]) else ""
        b = float(meta["breadth"].loc[d]) if d in meta["breadth"].index and pd.notna(meta["breadth"].loc[d]) else np.nan
        bucket = base.breadth_bucket(b)
        if color not in ("Blue", "Green") or bucket < 1:
            continue
        try:
            elig = bool(matrices["new_eligible"].at[d, symbol])
        except Exception:
            elig = False
        if not elig:
            continue
        market_any = True
        n = base.N_PORT if bucket == 2 else SELECTIVE_SLOTS
        candidates = current_candidates(d, matrices, peer_ctx, bucket, use_theme, base.N_PORT)
        names = [s for s, _ in candidates[:n]]
        if symbol in names:
            rank_any = True
            break
    return market_any, rank_any


def miss_reason(
    symbol: str,
    start: pd.Timestamp,
    peak: pd.Timestamp,
    matrices: dict[str, pd.DataFrame],
    meta: dict[str, Any],
    peer_ctx: dict[str, Any],
    use_theme: bool,
) -> str:
    if symbol not in matrices["close"].columns:
        return "OUT_OF_UNIVERSE"
    dates = matrices["close"].index[(matrices["close"].index >= start) & (matrices["close"].index < peak)]
    if len(dates) == 0:
        return "NO_WINDOW"
    close = matrices["close"].loc[dates, symbol]
    dvol = matrices["dvol"].loc[dates, symbol]
    base_pool = (close >= 5.0) & (dvol >= base.DVOL_FLOOR)
    if not bool(base_pool.fillna(False).any()):
        return "PRICE_OR_LIQUIDITY"
    trend = base_pool & (matrices["sma50"].loc[dates, symbol] > matrices["sma200"].loc[dates, symbol]) & (
        close > matrices["sma200"].loc[dates, symbol]
    )
    if not bool(trend.fillna(False).any()):
        return "TREND_FILTER"
    rs189_ok = trend & (matrices["rs189"].loc[dates, symbol] >= base.RS_MIN)
    if not bool(rs189_ok.fillna(False).any()):
        return "RS189_BELOW_85"
    rs63_ok = rs189_ok & (matrices["rs63"].loc[dates, symbol] >= base.RS_MIN)
    if not bool(rs63_ok.fillna(False).any()):
        return "RS63_BELOW_85"
    elig = matrices["new_eligible"].loc[dates, symbol].fillna(False)
    if not bool(elig.any()):
        return "ELIGIBILITY_OTHER"
    market_any, rank_any = candidate_passed_window(symbol, start, peak, matrices, meta, peer_ctx, use_theme)
    if not market_any:
        return "MARKET_GATE"
    if not rank_any:
        return "RANKING"
    return "PORTFOLIO_SLOT_OR_TIMING"


def annotate_capture(
    leaders: pd.DataFrame,
    sim: dict[str, Any],
    matrices: dict[str, pd.DataFrame],
    meta: dict[str, Any],
    peer_ctx: dict[str, Any],
    use_theme: bool,
) -> pd.DataFrame:
    if leaders.empty:
        return leaders.copy()
    out_rows: list[dict[str, Any]] = []
    intervals = sim["intervals"]
    close = matrices["close"]

    for _, row0 in leaders.iterrows():
        row = dict(row0)
        sym = str(row["symbol"])
        start = pd.Timestamp(row["start_date"])
        peak = pd.Timestamp(row["peak_date"])
        overlaps = find_overlap(intervals, sym, start, peak)
        captured = not overlaps.empty
        row["captured"] = bool(captured)
        row["capture_date"] = pd.NaT
        row["capture_mode"] = "MISSED"
        row["capture_progress"] = np.nan
        row["remaining_upside_ratio"] = np.nan
        row["remaining_upside"] = np.nan
        row["miss_reason"] = None

        if captured:
            first = overlaps.iloc[0]
            ent = pd.Timestamp(first["entry_date"])
            if ent <= start:
                cap_date = start
                mode = "PREPOSITIONED"
                progress = 0.0
                rem_ratio = 1.0
                rem_up = float(row["peak_return"])
            else:
                cap_date = ent
                mode = "ENTERED_DURING_RUN"
                ep = px(close, ent, sym, None)
                sp = float(row["start_price"])
                pp = float(row["peak_price"])
                total = pp / sp - 1.0
                if ep is not None and total > 0:
                    progress = (ep / sp - 1.0) / total
                    rem_up = pp / ep - 1.0
                    rem_ratio = rem_up / total
                else:
                    progress = np.nan
                    rem_up = np.nan
                    rem_ratio = np.nan
            row["capture_date"] = cap_date
            row["capture_mode"] = mode
            row["capture_progress"] = float(progress) if np.isfinite(progress) else np.nan
            row["remaining_upside_ratio"] = float(rem_ratio) if np.isfinite(rem_ratio) else np.nan
            row["remaining_upside"] = float(rem_up) if np.isfinite(rem_up) else np.nan
        else:
            row["miss_reason"] = miss_reason(sym, start, peak, matrices, meta, peer_ctx, use_theme)
        out_rows.append(row)

    return pd.DataFrame(out_rows)


def summarize_capture(df: pd.DataFrame) -> dict[str, Any]:
    if df.empty:
        return {"n": 0}
    cap = df["captured"].astype(bool)
    progress = pd.to_numeric(df.loc[cap, "capture_progress"], errors="coerce")
    remaining = pd.to_numeric(df.loc[cap, "remaining_upside_ratio"], errors="coerce")
    mega = df["mega_liquid"].astype(bool) if "mega_liquid" in df.columns else pd.Series(False, index=df.index)
    top10 = (pd.to_numeric(df.get("rank"), errors="coerce") <= 10) if "rank" in df.columns else pd.Series(False, index=df.index)

    def rate(mask: pd.Series) -> float | None:
        mask = mask.fillna(False)
        if not bool(mask.any()):
            return None
        return float(df.loc[mask, "captured"].astype(bool).mean())

    return {
        "n": int(len(df)),
        "captured_n": int(cap.sum()),
        "hit_rate": float(cap.mean()),
        "prepositioned_n": int((df["capture_mode"] == "PREPOSITIONED").sum()),
        "early_capture_share_of_hits_progress_le_33pct": float((progress <= 1.0 / 3.0).mean()) if progress.notna().any() else None,
        "median_capture_progress": float(progress.median()) if progress.notna().any() else None,
        "median_remaining_upside_ratio": float(remaining.median()) if remaining.notna().any() else None,
        "mega_liquid_hit_rate": rate(mega),
        "top10_hit_rate": rate(top10),
        "miss_reasons": {str(k): int(v) for k, v in df.loc[~cap, "miss_reason"].value_counts(dropna=False).items()},
    }


def annual_by_period(df: pd.DataFrame) -> dict[str, Any]:
    if df.empty:
        return {}
    return {str(period): summarize_capture(g) for period, g in df.groupby("period", sort=True)}


def compare_name_hits(a: pd.DataFrame, b: pd.DataFrame) -> dict[str, Any]:
    if a.empty or b.empty:
        return {}
    keys = ["leader_type", "period", "symbol", "start_date"]
    xa = a[keys + ["captured"]].rename(columns={"captured": "theme"})
    xb = b[keys + ["captured"]].rename(columns={"captured": "stock"})
    z = xa.merge(xb, on=keys, how="inner")
    return {
        "common_rows": int(len(z)),
        "both": int((z["theme"] & z["stock"]).sum()),
        "theme_only": int((z["theme"] & ~z["stock"]).sum()),
        "stock_only": int((~z["theme"] & z["stock"]).sum()),
        "neither": int((~z["theme"] & ~z["stock"]).sum()),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--output", required=True)
    ap.add_argument("--analysis-start", default="2020-01-02")
    ap.add_argument("--analysis-end", default="2026-09-02")
    ap.add_argument("--leader-start", default="2021-01-04")
    ap.add_argument("--max-tickers", type=int, default=6000)
    ap.add_argument("--batch-size", type=int, default=75)
    args = ap.parse_args()

    root = Path(args.root)
    out = root / args.output
    out.mkdir(parents=True, exist_ok=True)
    analysis_end = pd.Timestamp(args.analysis_end)
    leader_start = pd.Timestamp(args.leader_start)

    print("BUILD current-rule input matrices", flush=True)
    meta, matrices = ex.build_inputs_ext(root, args.analysis_start, args.analysis_end, args.max_tickers, args.batch_size)
    print(f"UNIVERSE selected={meta['selected']} downloaded={meta['downloaded']}", flush=True)

    print("BUILD strict leave-one-out peer Theme context", flush=True)
    peer_ctx = loo.build_leave_one_out_scores(root, matrices)

    print("SIM current adopted rule with entry audit", flush=True)
    theme_sim = simulate_current_with_entries(meta, matrices, peer_ctx, use_theme=True)
    validation = validate_simulation(meta, matrices, peer_ctx, theme_sim)
    print(f"SIM_VALIDATION {validation}", flush=True)

    print("SIM stock-only control with identical market/exit rules", flush=True)
    stock_sim = simulate_current_with_entries(meta, matrices, peer_ctx, use_theme=False)

    print("BUILD ex-post annual liquid-leader benchmark", flush=True)
    annual = build_annual_leaders(matrices, leader_start, analysis_end)
    print(f"ANNUAL_LEADERS n={len(annual)}", flush=True)

    print("BUILD ex-post rolling 126-session superleader benchmark", flush=True)
    rolling = build_rolling_superleaders(matrices, leader_start, analysis_end)
    print(f"ROLLING_SUPERLEADERS n={len(rolling)}", flush=True)

    print("MATCH V38 entries to leader benchmarks", flush=True)
    annual_theme = annotate_capture(annual, theme_sim, matrices, meta, peer_ctx, use_theme=True)
    annual_stock = annotate_capture(annual, stock_sim, matrices, meta, peer_ctx, use_theme=False)
    rolling_theme = annotate_capture(rolling, theme_sim, matrices, meta, peer_ctx, use_theme=True)
    rolling_stock = annotate_capture(rolling, stock_sim, matrices, meta, peer_ctx, use_theme=False)

    for name, frame in (
        ("annual_leaders_theme30.csv", annual_theme),
        ("annual_leaders_stock_only.csv", annual_stock),
        ("rolling_superleaders_theme30.csv", rolling_theme),
        ("rolling_superleaders_stock_only.csv", rolling_stock),
        ("entries_theme30_current.csv", theme_sim["entries"]),
        ("trades_theme30_current.csv", theme_sim["trades"]),
        ("entries_stock_only_current.csv", stock_sim["entries"]),
        ("trades_stock_only_current.csv", stock_sim["trades"]),
    ):
        frame.to_csv(out / name, index=False)

    result = {
        "status": "FIVE_YEAR_LEADER_CAPTURE_AUDIT",
        "analysis_window": {
            "analysis_start": args.analysis_start,
            "analysis_end": args.analysis_end,
            "leader_start": args.leader_start,
            "downloaded_stocks": int(meta["downloaded"]),
        },
        "rule": {
            "market_mode": "ATTACK=Blue/Green & breadth>=60 => 12 slots; SELECTIVE=Blue/Green & 50<=breadth<60 => 4 slots; otherwise no new normal-stock entries; Red exits next open.",
            "eligibility": "Price>=5, DDV>=10M, SMA50>SMA200, Close>SMA200, RS189>=85th pct, RS63>=85th pct, structural small clinical-biotech exclusion.",
            "attack_ranking": "70% Stock RS189 + 30% strict leave-one-out Peer Theme Score.",
            "selective_ranking": "Stock RS189 only.",
            "exit": "Close<=Entry*0.92 next-open exit; first Close>=Entry*1.24 next-open 25% partial; remaining Peak Close -30% trail; Red next-open exit.",
            "execution": "signal at close, execute next open",
        },
        "simulation_validation": validation,
        "leader_definitions": {
            "annual_liquid": {
                "periods": "2021 onward, calendar year; final year may be partial",
                "universe": "same downloaded V38 universe",
                "liquidity": f"median first-20-session DDV >= ${ANNUAL_MIN_DVOL:,.0f}",
                "coverage": ">=80% of period sessions",
                "minimum_period_return": ANNUAL_MIN_RETURN,
                "top_n": ANNUAL_TOP_N,
                "mega_liquid_threshold": MEGA_MIN_DVOL,
            },
            "rolling_126_superleader": {
                "horizon_sessions": ROLLING_HORIZON,
                "minimum_forward_mfe": ROLLING_MIN_MFE,
                "cross_sectional_percentile": ROLLING_PERCENTILE,
                "event_cooldown_sessions": ROLLING_COOLDOWN,
                "liquidity_at_start": ANNUAL_MIN_DVOL,
                "complete_horizon_required": True,
            },
        },
        "theme30_current": {
            "annual": summarize_capture(annual_theme),
            "annual_by_period": annual_by_period(annual_theme),
            "rolling126": summarize_capture(rolling_theme),
        },
        "stock_only_control": {
            "annual": summarize_capture(annual_stock),
            "annual_by_period": annual_by_period(annual_stock),
            "rolling126": summarize_capture(rolling_stock),
        },
        "theme_vs_stock_capture": {
            "annual": compare_name_hits(annual_theme, annual_stock),
            "rolling126": compare_name_hits(rolling_theme, rolling_stock),
        },
        "caveats": [
            "Leader labels are intentionally ex-post and are used only as the audit denominator; no future information enters V38 signals.",
            "Historical Theme taxonomy is the research branch taxonomy and can contain classification look-ahead; the stock-only control isolates how much the Theme overlay changes capture.",
            "Yahoo historical OHLCV survivorship/delisting coverage and the current research universe can under-represent delisted historical names.",
            "Literal index-contribution leadership needs historical float-adjusted market-cap/constituent weights; this audit measures investable price leadership among liquid V38-universe stocks.",
        ],
    }

    (out / "summary_five_year_leader_capture.json").write_text(
        json.dumps(safe(result), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("=== FIVE_YEAR_LEADER_CAPTURE_JSON ===", flush=True)
    print(json.dumps(safe(result), ensure_ascii=False, indent=2), flush=True)
    print("=== END_FIVE_YEAR_LEADER_CAPTURE_JSON ===", flush=True)


if __name__ == "__main__":
    main()
