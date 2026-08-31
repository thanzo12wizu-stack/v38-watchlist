#!/usr/bin/env python3
"""Build live desired exposures for audited Normal Stock and RSI Reset sleeves.

Normal Stock is seeded once from the full audited PEAK30_PART25_R3 research
simulator and then advanced one market session at a time using prior-close
signals and next-open execution. RSI Reset is rebuilt from forward-only PIT
Theme taxonomy over the bounded window needed by the adopted 20-session reset
and 20-session hold rules. Missing inputs fail closed as DATA REQUIRED; zero is
never substituted for an unavailable sleeve.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf

from build_v38_strict_loo_live import (
    arithmetic_returns,
    invert_memberships,
    period_return,
    taxonomy_for_asof,
)

NORMAL_MAX_POSITIONS = 12
RESET_SLOT = 0.029
RESET_MAX_POSITIONS = 4
RESET_MAX_THEME_POSITIONS = 2
RESET_HOLD = 20
RESET_COST = 5.0 / 10000.0
RESET_SEARCH = 20
RESET_COOLDOWN = 20
RESET_LOOKBACK_CALENDAR_DAYS = 190
MIN_THEME_MEMBERS = 3


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _load_json(path: Path | None, default: Any) -> Any:
    if path is None or not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def yahoo_symbol(symbol: str) -> str:
    return symbol.replace(".", "-")


def download_adjusted_ohlc(symbols: list[str], start: str, end: str,
                           batch_size: int = 150) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    requested = list(dict.fromkeys(str(s).strip().upper() for s in symbols if str(s).strip()))
    opens: list[pd.DataFrame] = []
    closes: list[pd.DataFrame] = []
    failed = 0
    for pos in range(0, len(requested), batch_size):
        batch = requested[pos:pos + batch_size]
        names = [yahoo_symbol(s) for s in batch]
        reverse = {yahoo_symbol(s): s for s in batch}
        try:
            raw = yf.download(
                names, start=start, end=end, auto_adjust=True, actions=False,
                progress=False, group_by="ticker", threads=True, timeout=30,
            )
        except Exception as exc:
            print(f"SLEEVE_DOWNLOAD_FAILED pos={pos} {type(exc).__name__}", flush=True)
            failed += 1
            continue
        if raw is None or raw.empty:
            failed += 1
            continue
        ob: dict[str, pd.Series] = {}
        cb: dict[str, pd.Series] = {}
        if isinstance(raw.columns, pd.MultiIndex):
            level0 = set(str(x) for x in raw.columns.get_level_values(0))
            for name in names:
                if name not in level0:
                    continue
                part = raw[name]
                if "Open" in part.columns and "Close" in part.columns:
                    ob[reverse[name]] = pd.to_numeric(part["Open"], errors="coerce")
                    cb[reverse[name]] = pd.to_numeric(part["Close"], errors="coerce")
        elif len(batch) == 1 and "Open" in raw.columns and "Close" in raw.columns:
            ob[batch[0]] = pd.to_numeric(raw["Open"], errors="coerce")
            cb[batch[0]] = pd.to_numeric(raw["Close"], errors="coerce")
        if ob:
            opens.append(pd.DataFrame(ob))
            closes.append(pd.DataFrame(cb))
        print(f"SLEEVE_DOWNLOAD {min(pos + batch_size, len(requested))}/{len(requested)}", flush=True)
    if not opens:
        raise RuntimeError("SLEEVE_PRICE_DOWNLOAD_EMPTY")
    op = pd.concat(opens, axis=1)
    cl = pd.concat(closes, axis=1)
    for frame in (op, cl):
        frame.index = pd.to_datetime(frame.index).tz_localize(None).normalize()
    op = op.loc[:, ~op.columns.duplicated()].sort_index().replace([np.inf, -np.inf], np.nan)
    cl = cl.loc[:, ~cl.columns.duplicated()].sort_index().replace([np.inf, -np.inf], np.nan)
    return op, cl, {"requested": len(requested), "downloaded": int(cl.shape[1]), "failed_batches": failed}


def _px(frame: pd.DataFrame, date: pd.Timestamp, symbol: str, fallback: float | None = None) -> float | None:
    try:
        x = float(frame.at[date, symbol])
        return x if math.isfinite(x) and x > 0 else fallback
    except Exception:
        return fallback


def _normal_from_seed(seed: dict[str, Any]) -> dict[str, Any]:
    if seed.get("status") != "READY" or seed.get("schema") != "v38-normal-sleeve-seed-1":
        raise RuntimeError("NORMAL_SEED_READY_REQUIRED")
    return {
        "status": "READY",
        "asof": str(seed["asof"]),
        "cash": float(seed["cash"]),
        "positions": [
            {
                "symbol": str(p["symbol"]),
                "shares": float(p["shares"]),
                "entry_price": float(p["entry_price"]),
                "entry_date": str(p["entry_date"]),
                "peak_close": float(p["peak_close"]),
                "partial_done": bool(p.get("partial_done", False)),
            }
            for p in seed.get("positions", [])
        ],
        "pending": {"full_exits": [], "partial25": [], "entries": []},
        "seed_source": seed.get("source_research_commit"),
        "seed_policy": seed.get("seed_policy"),
    }


def _ranked_entry_symbols(companion: dict[str, Any]) -> list[str]:
    market = companion.get("market", {})
    mode = market.get("mode")
    ranking = companion.get("ranking", {})
    if mode == "ATTACK" and ranking.get("strict_loo_live_status") != "READY":
        return []
    if mode not in {"ATTACK", "SELECTIVE"}:
        return []
    rows = [row for row in companion.get("candidates", []) if row.get("final_rank") is not None]
    rows.sort(key=lambda row: int(row["final_rank"]))
    return [str(row["ticker"]) for row in rows]


def _normal_pending(normal: dict[str, Any], companion: dict[str, Any], close_map: dict[str, float]) -> dict[str, Any]:
    positions = {p["symbol"]: p for p in normal["positions"]}
    market = companion.get("market", {})
    mode = str(market.get("mode") or "STOP")
    full_exits: list[dict[str, Any]] = []
    partials: list[dict[str, Any]] = []
    if mode == "DEFENSE":
        full_exits = [{"symbol": s, "reason": "NQSAR_RED"} for s in sorted(positions)]
    else:
        for sym, p in positions.items():
            close = close_map.get(sym)
            if close is None or not _finite(close):
                continue
            peak = max(float(p["peak_close"]), float(close))
            p["peak_close"] = peak
            stop = max(float(p["entry_price"]) * 0.92, peak * 0.70)
            if float(close) <= stop:
                full_exits.append({"symbol": sym, "reason": "INITIAL_OR_PEAK30_STOP"})
            elif (not p.get("partial_done")) and float(close) >= float(p["entry_price"]) * 1.24:
                partials.append({"symbol": sym, "fraction": 0.25, "reason": "PARTIAL25"})
    cap = int(market.get("new_entry_limit") or 0)
    expected_positions = len(positions) - len(full_exits)
    room = max(0, cap - expected_positions)
    ranked = _ranked_entry_symbols(companion)
    entries = []
    if room > 0:
        for sym in ranked:
            if sym in positions and not any(x["symbol"] == sym for x in full_exits):
                continue
            entries.append(sym)
            if len(entries) >= room:
                break
    return {"full_exits": full_exits, "partial25": partials, "entries": entries, "entry_cap": cap}


def _normal_mark(normal: dict[str, Any], closes: dict[str, float]) -> tuple[float, float, float]:
    gross = 0.0
    for p in normal["positions"]:
        cp = closes.get(p["symbol"])
        if not _finite(cp):
            raise RuntimeError(f"NORMAL_CLOSE_REQUIRED {p['symbol']}")
        p["peak_close"] = max(float(p["peak_close"]), float(cp))
        gross += float(p["shares"]) * float(cp)
    nav = float(normal["cash"]) + gross
    if nav <= 0:
        raise RuntimeError("NORMAL_NAV_NONPOSITIVE")
    return nav, gross, gross / nav * 100.0


def advance_normal(previous: dict[str, Any], companion: dict[str, Any], asof: str,
                   op: pd.DataFrame | None = None, cl: pd.DataFrame | None = None) -> dict[str, Any]:
    prev_asof = str(previous.get("asof") or "")
    current = dict(previous)
    current["positions"] = [dict(p) for p in previous.get("positions", [])]
    current["pending"] = dict(previous.get("pending") or {"full_exits": [], "partial25": [], "entries": []})
    date = pd.Timestamp(asof)
    if prev_asof > asof:
        raise RuntimeError("NORMAL_STATE_FROM_FUTURE")

    if prev_asof < asof:
        if op is None or cl is None or date not in op.index or date not in cl.index:
            raise RuntimeError("NORMAL_CURRENT_SESSION_PRICE_REQUIRED")
        sessions = [d for d in cl.index if pd.Timestamp(prev_asof) < d <= date]
        if len(sessions) != 1 or sessions[0] != date:
            raise RuntimeError(f"NORMAL_STATE_GAP sessions={len(sessions)}")
        pos = {p["symbol"]: p for p in current["positions"]}
        cash = float(current["cash"])
        pending = current.get("pending", {})
        for row in pending.get("full_exits", []):
            sym = str(row["symbol"])
            p = pos.get(sym)
            if p is None:
                continue
            px = _px(op, date, sym)
            if px is None:
                raise RuntimeError(f"NORMAL_OPEN_REQUIRED {sym}")
            cash += float(p["shares"]) * px
            pos.pop(sym, None)
        for row in pending.get("partial25", []):
            sym = str(row["symbol"])
            p = pos.get(sym)
            if p is None or p.get("partial_done"):
                continue
            px = _px(op, date, sym)
            if px is None:
                raise RuntimeError(f"NORMAL_OPEN_REQUIRED {sym}")
            sold = float(p["shares"]) * 0.25
            cash += sold * px
            p["shares"] = float(p["shares"]) - sold
            p["partial_done"] = True
        cap = int(pending.get("entry_cap") or 0)
        nav_open = cash
        for sym, p in pos.items():
            px = _px(op, date, sym)
            if px is None:
                raise RuntimeError(f"NORMAL_OPEN_REQUIRED {sym}")
            nav_open += float(p["shares"]) * px
        slot_cash = nav_open / NORMAL_MAX_POSITIONS
        for sym0 in pending.get("entries", []):
            sym = str(sym0)
            if len(pos) >= cap or cash <= 1e-12 or sym in pos:
                continue
            px = _px(op, date, sym)
            if px is None:
                raise RuntimeError(f"NORMAL_ENTRY_OPEN_REQUIRED {sym}")
            amount = min(slot_cash, cash)
            if amount <= 1e-10:
                break
            cash -= amount
            pos[sym] = {
                "symbol": sym, "shares": amount / px, "entry_price": px,
                "entry_date": asof, "peak_close": px, "partial_done": False,
            }
        current["cash"] = cash
        current["positions"] = list(pos.values())
        current["asof"] = asof

    close_map: dict[str, float] = {}
    if prev_asof == asof:
        for p in current["positions"]:
            if _finite(p.get("close")):
                close_map[p["symbol"]] = float(p["close"])
        if cl is not None and date in cl.index:
            for p in current["positions"]:
                px = _px(cl, date, p["symbol"])
                if px is not None:
                    close_map[p["symbol"]] = px
    else:
        close_map = {p["symbol"]: _px(cl, date, p["symbol"]) for p in current["positions"]}  # type: ignore[arg-type]
    if any(not _finite(v) for v in close_map.values()) or len(close_map) < len(current["positions"]):
        raise RuntimeError("NORMAL_MARK_CLOSE_INCOMPLETE")
    nav, gross, desired = _normal_mark(current, close_map)
    current["nav"] = nav
    current["gross_value"] = gross
    current["desired_pct"] = desired
    current["position_count"] = len(current["positions"])
    current["pending"] = _normal_pending(current, companion, close_map)
    current["status"] = "READY"
    current["strategy"] = "PEAK30_PART25_R3"
    return current


def wilder_rsi(close: pd.DataFrame, n: int = 14) -> pd.DataFrame:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    avg_loss = loss.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100.0 - 100.0 / (1.0 + rs)
    out = out.where(avg_loss != 0.0, 100.0)
    return out


def _theme_snapshot(close: pd.DataFrame, asof: pd.Timestamp, s2t: dict[str, list[str]]) -> tuple[dict[str, float], dict[str, float], dict[str, list[str]], pd.Series]:
    members = invert_memberships(s2t)
    sub = close.loc[close.index <= asof]
    stock_ret = arithmetic_returns(sub)
    stock63 = period_return(stock_ret, 63).iloc[-1]
    theme_daily: dict[str, pd.Series] = {}
    ema21 = sub.ewm(span=21, adjust=False, min_periods=15).mean()
    breadth: dict[str, float] = {}
    for theme, syms0 in members.items():
        syms = [s for s in syms0 if s in sub.columns]
        if len(syms) < MIN_THEME_MEMBERS:
            continue
        part = stock_ret[syms]
        count = part.notna().sum(axis=1)
        theme_daily[theme] = part.mean(axis=1, skipna=True).where(count >= MIN_THEME_MEMBERS)
        valid = sub.loc[asof, syms].notna() & ema21.loc[asof, syms].notna()
        nvalid = int(valid.sum())
        if nvalid >= MIN_THEME_MEMBERS:
            breadth[theme] = float((sub.loc[asof, syms][valid] > ema21.loc[asof, syms][valid]).mean() * 100.0)
    if not theme_daily:
        return {}, {}, {}, stock63
    theme63 = period_return(pd.DataFrame(theme_daily), 63).iloc[-1].dropna()
    pct = (theme63.rank(pct=True, method="average") * 100.0).to_dict()
    return {str(k): float(v) for k, v in pct.items()}, breadth, members, stock63


def build_reset_trades(close: pd.DataFrame, open_: pd.DataFrame, history: dict[str, Any], asof: str) -> pd.DataFrame:
    cal = close.index[close.index <= pd.Timestamp(asof)]
    if len(cal) < 90:
        raise RuntimeError("RESET_PRICE_HISTORY_REQUIRED")
    rsi = wilder_rsi(close, 14)
    theme_cache: dict[pd.Timestamp, tuple[dict[str, float], dict[str, float], dict[str, list[str]], pd.Series]] = {}
    def snap(d: pd.Timestamp):
        if d not in theme_cache:
            s2t, _ = taxonomy_for_asof(history, str(d.date()))
            theme_cache[d] = _theme_snapshot(close, d, s2t)
        return theme_cache[d]

    start_pos = max(63 + 20, len(cal) - 70)
    activations: list[tuple[pd.Timestamp, str, str, int]] = []
    for i in range(start_pos, len(cal)):
        d = cal[i]
        try:
            pct, breadth, members, stock63 = snap(d)
            old_pct, _, _, _ = snap(cal[i - 20])
        except RuntimeError:
            continue
        for theme, p in pct.items():
            if p < 80.0 or p - old_pct.get(theme, p) < 15.0 or breadth.get(theme, -1.0) < 60.0:
                continue
            syms = [s for s in members.get(theme, []) if s in stock63.index and _finite(stock63.get(s))]
            top = sorted(syms, key=lambda s: (-float(stock63[s]), s))[:3]
            if len(top) < 3:
                continue
            for rank, sym in enumerate(top, 1):
                activations.append((d, theme, sym, rank))

    records: list[dict[str, Any]] = []
    posmap = {d: i for i, d in enumerate(cal)}
    cooldown_until: dict[str, int] = defaultdict(lambda: -1)
    for day0, theme, sym, rank0 in sorted(activations, key=lambda x: (x[0], x[1], x[3], x[2])):
        ep = posmap[day0]
        if ep <= cooldown_until[sym]:
            continue
        last = min(len(cal) - 2, ep + RESET_SEARCH)
        rr = rsi[sym] if sym in rsi.columns else None
        if rr is None:
            continue
        touch = None
        for j in range(ep, last + 1):
            if _finite(rr.iloc[j]) and float(rr.iloc[j]) <= 30.0:
                touch = j
                break
        if touch is None:
            continue
        signal = None
        for j in range(touch + 1, last + 1):
            if _finite(rr.iloc[j]) and _finite(rr.iloc[j - 1]) and float(rr.iloc[j]) > float(rr.iloc[j - 1]):
                try:
                    _, _, members_sig, stock63_sig = snap(cal[j])
                except RuntimeError:
                    continue
                syms = [s for s in members_sig.get(theme, []) if s in stock63_sig.index and _finite(stock63_sig.get(s))]
                top_sig = sorted(syms, key=lambda s: (-float(stock63_sig[s]), s))[:3]
                if sym in top_sig:
                    signal = j
                    break
        if signal is None or signal + 1 >= len(cal):
            continue
        entry = signal + 1
        cooldown_until[sym] = signal + RESET_COOLDOWN
        records.append({
            "day0_date": day0, "theme": theme, "symbol": sym,
            "rank_priority": rank0, "signal_date": cal[signal],
            "entry_date": cal[entry], "rsi_signal": float(rr.iloc[signal]),
        })
    return pd.DataFrame(records)


def simulate_reset(close: pd.DataFrame, open_: pd.DataFrame, trades: pd.DataFrame, asof: str) -> dict[str, Any]:
    cal = close.index[close.index <= pd.Timestamp(asof)]
    cash = 1.0
    lots: list[dict[str, Any]] = []
    accepted = 0
    by_entry = {pd.Timestamp(d): g for d, g in trades.groupby("entry_date", observed=True)} if not trades.empty else {}
    for i, d in enumerate(cal):
        keep = []
        for lot in lots:
            px = _px(open_, d, lot["symbol"])
            if i >= lot["exit_i"] and px is not None:
                cash += lot["shares"] * px * (1.0 - RESET_COST)
            else:
                keep.append(lot)
        lots = keep
        if d in by_entry:
            day = by_entry[d].sort_values(["rank_priority", "rsi_signal", "symbol"])
            for r in day.itertuples(index=False):
                if len(lots) >= RESET_MAX_POSITIONS:
                    continue
                if sum(q["theme"] == r.theme for q in lots) >= RESET_MAX_THEME_POSITIONS:
                    continue
                px = _px(open_, d, r.symbol)
                if px is None:
                    continue
                mark = cash
                for q in lots:
                    qpx = _px(open_, d, q["symbol"])
                    if qpx is not None:
                        mark += q["shares"] * qpx
                amount = RESET_SLOT * mark
                if cash < amount * (1.0 + RESET_COST):
                    continue
                cash -= amount * (1.0 + RESET_COST)
                lots.append({
                    "symbol": r.symbol, "theme": r.theme, "shares": amount / px,
                    "entry_date": str(pd.Timestamp(d).date()), "exit_i": min(i + RESET_HOLD, len(cal) - 1),
                })
                accepted += 1
    d = cal[-1]
    gross = 0.0
    out_lots = []
    for lot in lots:
        cp = _px(close, d, lot["symbol"])
        if cp is None:
            raise RuntimeError(f"RESET_CLOSE_REQUIRED {lot['symbol']}")
        mark = lot["shares"] * cp
        gross += mark
        out_lots.append({**lot, "close": cp, "mark": mark})
    nav = cash + gross
    if nav <= 0:
        raise RuntimeError("RESET_NAV_NONPOSITIVE")
    return {
        "status": "READY", "strategy": "RS63_TOP3_RISE30_SIGTOP3",
        "asof": str(d.date()), "cash": cash, "nav": nav, "gross_value": gross,
        "desired_pct": gross / nav * 100.0, "position_count": len(lots),
        "positions": out_lots, "accepted_in_rebuild_window": accepted,
        "signal_count_in_rebuild_window": int(len(trades)),
        "rebuild_policy": "FORWARD_PIT_TAXONOMY; ACTIVE_THEME_80_15_60; RS63_TOP3_DAY0_AND_SIGNAL; RSI30_RISE; H20",
    }


def _data_required(asof: str | None, reason: str, normal: dict | None = None, reset: dict | None = None) -> dict[str, Any]:
    return {
        "schema": "v38-sleeve-live-1", "asof": asof, "status": "DATA REQUIRED",
        "reason": reason, "normal_stock": normal or {"status": "DATA REQUIRED"},
        "rsi_reset": reset or {"status": "DATA REQUIRED"},
    }


def _merge_desired_into_tqqq(path: Path, asof: str, normal_pct: float | None, reset_pct: float | None,
                             sleeve_status: str, reason: str | None = None) -> None:
    t = _load_json(path, {})
    if str(t.get("asof") or "") != asof or t.get("live_generation_status") != "READY":
        t["normal_stock_desired_pct"] = None
        t["reset_desired_pct"] = None
        t["sleeve_live_status"] = "DATA REQUIRED"
        t["sleeve_live_reason"] = "TQQQ_ASOF_OR_READY_MISMATCH"
    elif sleeve_status == "READY" and normal_pct is not None and reset_pct is not None:
        t["normal_stock_desired_pct"] = float(normal_pct)
        t["reset_desired_pct"] = float(reset_pct)
        t["sleeve_live_status"] = "READY"
        t["sleeve_live_reason"] = None
    else:
        t["normal_stock_desired_pct"] = None
        t["reset_desired_pct"] = None
        t["sleeve_live_status"] = "DATA REQUIRED"
        t["sleeve_live_reason"] = reason or "SLEEVE_INPUT_DATA_REQUIRED"
    _write_json(path, t)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--companion", default="v38-live-state.json")
    ap.add_argument("--state", default="v38-sleeve-state.json")
    ap.add_argument("--seed", default="v38-normal-sleeve-seed.json")
    ap.add_argument("--strict-history", default="v38-strict-loo-history.json")
    ap.add_argument("--tqqq-state", default="tqqq-panic-state.json")
    ap.add_argument("--out", default="v38-sleeve-state.json")
    ap.add_argument("--batch-size", type=int, default=150)
    args = ap.parse_args()

    companion = _load_json(Path(args.companion), {})
    asof = str(companion.get("asof") or "")
    out = Path(args.out)
    if not asof:
        payload = _data_required(None, "COMPANION_ASOF_REQUIRED")
        _write_json(out, payload)
        _merge_desired_into_tqqq(Path(args.tqqq_state), "", None, None, "DATA REQUIRED", payload["reason"])
        return
    previous = _load_json(Path(args.state), {})
    seed = _load_json(Path(args.seed), {})
    history = _load_json(Path(args.strict_history), {})
    normal: dict[str, Any] | None = None
    reset: dict[str, Any] | None = None
    try:
        prior_normal = previous.get("normal_stock") if previous.get("schema") == "v38-sleeve-live-1" else None
        if not isinstance(prior_normal, dict) or prior_normal.get("status") != "READY":
            prior_normal = _normal_from_seed(seed)
            seed_pos = {p["symbol"]: p for p in seed.get("positions", [])}
            for p in prior_normal["positions"]:
                if _finite(seed_pos.get(p["symbol"], {}).get("close")):
                    p["close"] = float(seed_pos[p["symbol"]]["close"])
        symbols_normal = sorted(({p["symbol"] for p in prior_normal.get("positions", [])}
                                 | set((prior_normal.get("pending") or {}).get("entries", []))
                                 | {"SPY"}))
        op_n = cl_n = None
        if str(prior_normal.get("asof")) <= asof:
            start_n = str((pd.Timestamp(str(prior_normal["asof"])) - pd.Timedelta(days=8)).date())
            end_n = str((pd.Timestamp(asof) + pd.Timedelta(days=1)).date())
            if symbols_normal:
                op_n, cl_n, _ = download_adjusted_ohlc(symbols_normal, start_n, end_n, min(args.batch_size, 100))
                cl_n = cl_n.loc[cl_n.index <= pd.Timestamp(asof)]
                op_n = op_n.loc[op_n.index <= pd.Timestamp(asof)]
        normal = advance_normal(prior_normal, companion, asof, op_n, cl_n)

        if not history.get("taxonomy_snapshots"):
            raise RuntimeError("RESET_PIT_TAXONOMY_HISTORY_REQUIRED")
        earliest = min(str(row.get("effective_asof")) for row in history.get("taxonomy_snapshots", []) if row.get("effective_asof"))
        symbols_reset = sorted({str(s) for row in history.get("taxonomy_snapshots", []) for s in (row.get("s2t") or {})})
        start_r = max(pd.Timestamp(earliest) - pd.Timedelta(days=100), pd.Timestamp(asof) - pd.Timedelta(days=RESET_LOOKBACK_CALENDAR_DAYS))
        op_r, cl_r, quality = download_adjusted_ohlc(symbols_reset, str(start_r.date()), str((pd.Timestamp(asof) + pd.Timedelta(days=1)).date()), args.batch_size)
        cl_r = cl_r.loc[cl_r.index <= pd.Timestamp(asof)]
        op_r = op_r.reindex(index=cl_r.index, columns=cl_r.columns)
        if pd.Timestamp(asof) not in cl_r.index:
            raise RuntimeError(f"RESET_PRICE_ASOF_REQUIRED latest={cl_r.index.max() if len(cl_r) else None}")
        reset_trades = build_reset_trades(cl_r, op_r, history, asof)
        reset = simulate_reset(cl_r, op_r, reset_trades, asof)
        reset["download_quality"] = quality
        payload = {
            "schema": "v38-sleeve-live-1", "asof": asof, "status": "READY",
            "normal_stock": normal, "rsi_reset": reset,
            "gross100_input_semantics": "CURRENT_MARKED_GROSS_EXPOSURE_OF_EACH_STANDALONE_AUDITED_SLEEVE",
            "missing_input_policy": "DATA_REQUIRED_NOT_ZERO",
            "gross100_recheck": {"run_id": 33405477190, "artifact_id": 9763251012,
                                  "reset_rule": "RS63_TOP3_RISE30_SIGTOP3", "tqqq_floor_pct": 80},
        }
    except Exception as exc:
        payload = _data_required(asof, f"{type(exc).__name__}: {exc}", normal, reset)
        print(f"SLEEVE_DATA_REQUIRED {type(exc).__name__}: {exc}", flush=True)
    _write_json(out, payload)
    ready = payload.get("status") == "READY"
    _merge_desired_into_tqqq(
        Path(args.tqqq_state), asof,
        payload.get("normal_stock", {}).get("desired_pct") if ready else None,
        payload.get("rsi_reset", {}).get("desired_pct") if ready else None,
        "READY" if ready else "DATA REQUIRED", payload.get("reason"),
    )
    print(
        f"wrote {out}: status={payload.get('status')} asof={asof} "
        f"normal={payload.get('normal_stock', {}).get('desired_pct')} "
        f"reset={payload.get('rsi_reset', {}).get('desired_pct')}", flush=True,
    )


if __name__ == "__main__":
    main()
