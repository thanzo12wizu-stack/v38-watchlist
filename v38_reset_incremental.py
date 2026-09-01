#!/usr/bin/env python3
"""Incremental live engine for the adopted V38 RSI30 Panic Reset sleeve.

The research rule is unchanged:
- Day0 Theme RS63 percentile >=80
- Day0 Theme 20-session rank improvement >=15 points
- Day0 Theme Breadth21 >=60%
- Day0 stock is Theme RS63 Top3
- within 20 sessions, RSI14 touches <=30 and later records its first rise
- on that rise the stock is again Theme RS63 Top3
- entry next open, 2.9% per stock, max 4, max 2 per Theme
- fixed 20-session hold and 20-session same-symbol cooldown

Unlike the original live rebuild, this module does not download the entire
5k-symbol taxonomy every morning.  Strict LOO persists the exact Day0 Theme
features.  Existing activation RSI state is advanced from the already-built
``universe.csv`` close.  Network history is needed only when a new Day0 leader
appears, and current opens are needed only for pending entries / active exits.
Missing inputs fail closed; no missing sleeve is interpreted as 0%.
"""
from __future__ import annotations

import csv
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from build_v38_tqqq_live import download_fmp_frame, download_yahoo_chart

RESET_SLOT = 0.029
RESET_MAX_POSITIONS = 4
RESET_MAX_THEME_POSITIONS = 2
RESET_HOLD = 20
RESET_SEARCH = 20
RESET_COOLDOWN = 20
RESET_COST = 5.0 / 10000.0
RSI_N = 14
HISTORY_CALENDAR_DAYS = 150


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _monitor_band(rsi_value: float | None) -> str:
    if not _finite(rsi_value):
        return "DATA_REQUIRED"
    value = float(rsi_value)
    if value <= 30.0:
        return "RSI30_OR_BELOW"
    if value <= 35.0:
        return "WITHIN_5PT"
    if value <= 40.0:
        return "WITHIN_10PT"
    return "WATCHING"


def load_universe_close(path: Path) -> dict[str, float]:
    if not path.is_file():
        raise RuntimeError(f"RESET_UNIVERSE_REQUIRED {path}")
    out: dict[str, float] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            symbol = str(row.get("シンボル") or row.get("symbol") or row.get("Symbol") or "").strip().upper()
            value = row.get("価格") or row.get("price") or row.get("Price")
            if symbol and _finite(value) and float(value) > 0:
                out[symbol] = float(value)
    if len(out) < 1000:
        raise RuntimeError(f"RESET_UNIVERSE_PRICE_COVERAGE_LOW {len(out)}")
    return out


def _yahoo_symbol(symbol: str) -> str:
    return symbol.replace(".", "-")


def fetch_adjusted_daily(symbol: str, start: str) -> tuple[pd.DataFrame, str]:
    errors: list[str] = []
    try:
        frame = download_yahoo_chart(_yahoo_symbol(symbol), start=start)
        if frame is not None and not frame.empty:
            return frame[["Open", "Close"]].copy(), "YAHOO_CHART"
    except Exception as exc:
        errors.append(f"YAHOO_CHART={type(exc).__name__}:{exc}")
    try:
        frame = download_fmp_frame(symbol, start=start)
        if frame is not None and not frame.empty:
            return frame[["Open", "Close"]].copy(), "FMP_DIVIDEND_ADJUSTED"
    except Exception as exc:
        errors.append(f"FMP={type(exc).__name__}:{exc}")
    raise RuntimeError(f"RESET_PRICE_SOURCE_EXHAUSTED {symbol} {' | '.join(errors)}")


def fetch_adjusted_daily_many(symbols: list[str], start: str, max_workers: int = 8) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
    requested = list(dict.fromkeys(str(x).strip().upper() for x in symbols if str(x).strip()))
    frames: dict[str, pd.DataFrame] = {}
    providers: dict[str, str] = {}
    errors: dict[str, str] = {}
    if not requested:
        return frames, providers
    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, 8))) as executor:
        futures = {executor.submit(fetch_adjusted_daily, symbol, start): symbol for symbol in requested}
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                frame, provider = future.result()
                frame.index = pd.to_datetime(frame.index).tz_localize(None).normalize()
                frames[symbol] = frame.sort_index()
                providers[symbol] = provider
            except Exception as exc:
                errors[symbol] = f"{type(exc).__name__}: {exc}"
    if errors:
        sample = "; ".join(f"{k}={v}" for k, v in list(errors.items())[:8])
        raise RuntimeError(f"RESET_PRICE_COVERAGE_REQUIRED missing={len(errors)}/{len(requested)} {sample}")
    return frames, providers


def rsi_state_from_close(close: pd.Series, n: int = RSI_N) -> dict[str, float]:
    series = pd.to_numeric(close, errors="coerce").dropna()
    if len(series) < n + 2:
        raise RuntimeError(f"RESET_RSI_HISTORY_REQUIRED rows={len(series)}")
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    avg_loss = loss.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    ag = float(avg_gain.iloc[-1])
    al = float(avg_loss.iloc[-1])
    if not (_finite(ag) and _finite(al)):
        raise RuntimeError("RESET_RSI_STATE_REQUIRED")
    if al == 0.0:
        rsi = 100.0
    else:
        rs = ag / al
        rsi = 100.0 - 100.0 / (1.0 + rs)
    return {
        "close": float(series.iloc[-1]),
        "avg_gain": ag,
        "avg_loss": al,
        "rsi14": float(rsi),
    }


def advance_rsi_state(state: dict[str, Any], new_close: float, n: int = RSI_N) -> dict[str, float]:
    if not all(_finite(state.get(key)) for key in ("close", "avg_gain", "avg_loss", "rsi14")):
        raise RuntimeError("RESET_PRIOR_RSI_STATE_REQUIRED")
    old_close = float(state["close"])
    delta = float(new_close) - old_close
    gain = max(delta, 0.0)
    loss = max(-delta, 0.0)
    ag = (float(state["avg_gain"]) * (n - 1) + gain) / n
    al = (float(state["avg_loss"]) * (n - 1) + loss) / n
    if al == 0.0:
        rsi = 100.0
    else:
        rsi = 100.0 - 100.0 / (1.0 + ag / al)
    return {"close": float(new_close), "avg_gain": ag, "avg_loss": al, "rsi14": float(rsi)}


def _session_map(history: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(row.get("asof")): row for row in history.get("sessions", [])
            if isinstance(row, dict) and row.get("asof")}


def current_day0_candidates(history: dict[str, Any], asof: str) -> list[dict[str, Any]]:
    by_date = _session_map(history)
    current = by_date.get(asof)
    if not current:
        raise RuntimeError(f"RESET_STRICT_SESSION_REQUIRED {asof}")
    base_asof = str(current.get("base20_asof") or "")
    old = by_date.get(base_asof)
    if not base_asof or not old:
        raise RuntimeError(f"RESET_STRICT_BASE20_REQUIRED {base_asof or 'NONE'}")
    current_pct = current.get("normal_theme_rs63_pct") or {}
    old_pct = old.get("normal_theme_rs63_pct") or {}
    breadth = current.get("normal_theme_breadth21_pct") or {}
    top3 = current.get("theme_stock_rs63_top3") or {}
    if not breadth or not top3:
        raise RuntimeError("RESET_STRICT_DAY0_FEATURES_REQUIRED")
    out: list[dict[str, Any]] = []
    for theme, value in current_pct.items():
        if not (_finite(value) and _finite(old_pct.get(theme)) and _finite(breadth.get(theme))):
            continue
        improvement = float(value) - float(old_pct[theme])
        if float(value) < 80.0 or improvement < 15.0 or float(breadth[theme]) < 60.0:
            continue
        leaders = [str(x) for x in (top3.get(theme) or []) if str(x)]
        if len(leaders) < 3:
            continue
        for rank, symbol in enumerate(leaders[:3], 1):
            out.append({
                "day0_date": asof,
                "theme": str(theme),
                "symbol": symbol,
                "rank_priority": rank,
                "theme_rs_pct_day0": float(value),
                "theme_rank_improvement20_day0": float(improvement),
                "theme_breadth21_day0": float(breadth[theme]),
            })
    out.sort(key=lambda row: (row["theme"], row["rank_priority"], row["symbol"]))
    return out


def _current_top3(history: dict[str, Any], asof: str) -> dict[str, list[str]]:
    row = _session_map(history).get(asof) or {}
    return {str(theme): [str(x) for x in values[:3]]
            for theme, values in (row.get("theme_stock_rs63_top3") or {}).items()
            if isinstance(values, list)}


def _activation_key(row: dict[str, Any]) -> str:
    return f"{row.get('day0_date')}|{row.get('theme')}|{row.get('symbol')}"


def _best_monitor(activations: list[dict[str, Any]], positions: list[dict[str, Any]],
                  rsi_states: dict[str, dict[str, float]], current_top3: dict[str, list[str]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    active_symbols = {str(row.get("symbol")) for row in positions}
    priority = {"ACTIVE_POSITION": 0, "SIGNAL_TODAY_NEXT_OPEN": 1,
                "RSI30_TOUCHED_WAIT_RISE": 2, "APPROACHING_RSI30": 3,
                "NEAR_RSI30": 4, "WATCHING": 5, "SIGNAL_OCCURRED": 6}
    rows: list[dict[str, Any]] = []
    for act in activations:
        symbol = str(act["symbol"])
        theme = str(act["theme"])
        state = rsi_states.get(symbol, {})
        rsi = float(state["rsi14"]) if _finite(state.get("rsi14")) else None
        if symbol in active_symbols:
            status = "ACTIVE_POSITION"
        elif act.get("signal_date") == act.get("engine_asof"):
            status = "SIGNAL_TODAY_NEXT_OPEN"
        elif act.get("signal_date"):
            status = "SIGNAL_OCCURRED"
        elif act.get("touched_rsi30"):
            status = "RSI30_TOUCHED_WAIT_RISE"
        elif _finite(rsi) and float(rsi) <= 35.0:
            status = "APPROACHING_RSI30"
        elif _finite(rsi) and float(rsi) <= 40.0:
            status = "NEAR_RSI30"
        else:
            status = "WATCHING"
        rows.append({
            "symbol": symbol,
            "theme": theme,
            "status": status,
            "monitor_band": _monitor_band(rsi),
            "current_rsi14": rsi,
            "distance_to_30": max(float(rsi) - 30.0, 0.0) if _finite(rsi) else None,
            "day0_date": str(act["day0_date"]),
            "activation_age_sessions": int(act.get("age_sessions") or 0),
            "signal_window_days_left": max(0, RESET_SEARCH - int(act.get("age_sessions") or 0)),
            "theme_rs_pct_day0": float(act["theme_rs_pct_day0"]),
            "theme_rank_improvement20_day0": float(act["theme_rank_improvement20_day0"]),
            "theme_breadth21_day0": float(act["theme_breadth21_day0"]),
            "day0_rs63_rank": int(act["rank_priority"]),
            "touched_rsi30": bool(act.get("touched_rsi30")),
            "touch_date": act.get("touch_date"),
            "signal_date": act.get("signal_date"),
            "signal_top3_confirmed": bool(act.get("signal_date")),
            "current_theme_rs63_top3": symbol in current_top3.get(theme, []),
            "display_band_is_trade_rule": False,
        })
    best: dict[str, dict[str, Any]] = {}
    score_by_symbol: dict[str, tuple] = {}
    for row in rows:
        score = (
            priority.get(row["status"], 99),
            row["distance_to_30"] if row["distance_to_30"] is not None else 999.0,
            -row["signal_window_days_left"],
            row["theme"],
        )
        if row["symbol"] not in best or score < score_by_symbol[row["symbol"]]:
            best[row["symbol"]] = row
            score_by_symbol[row["symbol"]] = score
    monitor = list(best.values())
    monitor.sort(key=lambda row: (
        priority.get(row["status"], 99),
        row["distance_to_30"] if row["distance_to_30"] is not None else 999.0,
        -row["signal_window_days_left"], row["symbol"],
    ))
    summary = {
        "active_positions": sum(row["status"] == "ACTIVE_POSITION" for row in monitor),
        "signal_today": sum(row["status"] == "SIGNAL_TODAY_NEXT_OPEN" for row in monitor),
        "touched_wait_rise": sum(row["status"] == "RSI30_TOUCHED_WAIT_RISE" for row in monitor),
        "within_5pt": sum(row["monitor_band"] in {"RSI30_OR_BELOW", "WITHIN_5PT"} for row in monitor),
        "within_10pt": sum(row["monitor_band"] in {"RSI30_OR_BELOW", "WITHIN_5PT", "WITHIN_10PT"} for row in monitor),
        "watch_count": len(monitor),
    }
    return monitor, summary


def _mark_reset(reset: dict[str, Any], close_map: dict[str, float]) -> None:
    gross = 0.0
    for lot in reset["positions"]:
        symbol = str(lot["symbol"])
        if symbol not in close_map or not _finite(close_map[symbol]):
            raise RuntimeError(f"RESET_CLOSE_REQUIRED {symbol}")
        close = float(close_map[symbol])
        mark = float(lot["shares"]) * close
        lot["close"] = close
        lot["mark"] = mark
        gross += mark
    nav = float(reset["cash"]) + gross
    if nav <= 0:
        raise RuntimeError("RESET_NAV_NONPOSITIVE")
    reset["gross_value"] = gross
    reset["nav"] = nav
    reset["desired_pct"] = gross / nav * 100.0
    reset["position_count"] = len(reset["positions"])


def _open_map_for_symbols(symbols: list[str], asof: str,
                          fetcher: Callable[[list[str], str, int], tuple[dict[str, pd.DataFrame], dict[str, str]]] = fetch_adjusted_daily_many) -> tuple[dict[str, float], dict[str, str]]:
    if not symbols:
        return {}, {}
    start = str((pd.Timestamp(asof) - pd.Timedelta(days=8)).date())
    frames, providers = fetcher(symbols, start, 8)
    target = pd.Timestamp(asof)
    out: dict[str, float] = {}
    for symbol in symbols:
        frame = frames.get(symbol)
        if frame is None or target not in frame.index or not _finite(frame.at[target, "Open"]):
            raise RuntimeError(f"RESET_OPEN_REQUIRED {symbol} {asof}")
        out[symbol] = float(frame.at[target, "Open"])
    return out, providers


def _seed_new_rsi_states(symbols: list[str], asof: str,
                         fetcher: Callable[[list[str], str, int], tuple[dict[str, pd.DataFrame], dict[str, str]]] = fetch_adjusted_daily_many) -> tuple[dict[str, dict[str, float]], dict[str, str]]:
    if not symbols:
        return {}, {}
    start = str((pd.Timestamp(asof) - pd.Timedelta(days=HISTORY_CALENDAR_DAYS)).date())
    frames, providers = fetcher(symbols, start, 8)
    target = pd.Timestamp(asof)
    out: dict[str, dict[str, float]] = {}
    for symbol in symbols:
        frame = frames.get(symbol)
        if frame is None:
            raise RuntimeError(f"RESET_RSI_HISTORY_REQUIRED {symbol}")
        series = frame.loc[frame.index <= target, "Close"]
        if target not in series.index:
            raise RuntimeError(f"RESET_RSI_ASOF_REQUIRED {symbol} {asof}")
        out[symbol] = rsi_state_from_close(series)
    return out, providers


def update_reset_incremental(previous: dict[str, Any], history: dict[str, Any], asof: str,
                             *, universe_path: Path, prior_market_date: str | None,
                             fetcher: Callable[[list[str], str, int], tuple[dict[str, pd.DataFrame], dict[str, str]]] = fetch_adjusted_daily_many) -> dict[str, Any]:
    if previous.get("status") != "READY" or previous.get("engine_schema") != "v38-reset-engine-1":
        raise RuntimeError("RESET_ENGINE_SEED_READY_REQUIRED")
    prev_asof = str(previous.get("asof") or "")
    if prev_asof > asof:
        raise RuntimeError("RESET_STATE_FROM_FUTURE")
    reset = {
        **previous,
        "positions": [dict(row) for row in previous.get("positions", [])],
        "pending_entries": [dict(row) for row in previous.get("pending_entries", [])],
        "activations": [dict(row) for row in previous.get("activations", [])],
        "rsi_states": {str(k): dict(v) for k, v in (previous.get("rsi_states") or {}).items()},
        "cooldowns": {str(k): dict(v) for k, v in (previous.get("cooldowns") or {}).items()},
    }
    universe_close = load_universe_close(universe_path)
    current_top3 = _current_top3(history, asof)

    if prev_asof == asof:
        close_map = {str(lot["symbol"]): universe_close.get(str(lot["symbol"])) for lot in reset["positions"]}
        if any(not _finite(v) for v in close_map.values()):
            raise RuntimeError("RESET_SAME_SESSION_MARK_REQUIRED")
        _mark_reset(reset, {k: float(v) for k, v in close_map.items()})
        monitor, summary = _best_monitor(reset["activations"], reset["positions"], reset["rsi_states"], current_top3)
        reset["monitor"] = monitor[:100]
        reset["monitor_summary"] = summary
        return reset

    if not prior_market_date or prior_market_date != prev_asof:
        raise RuntimeError(f"RESET_STATE_GAP prev={prev_asof} market_prev={prior_market_date}")

    # Execute actions scheduled from the prior close at today's open.
    exit_symbols = [str(lot["symbol"]) for lot in reset["positions"] if int(lot.get("sessions_since_entry") or 0) >= RESET_HOLD - 1]
    entry_symbols = [str(row["symbol"]) for row in reset["pending_entries"]]
    opens, open_providers = _open_map_for_symbols(sorted(set(exit_symbols + entry_symbols)), asof, fetcher)
    cash = float(reset["cash"])
    kept: list[dict[str, Any]] = []
    for lot in reset["positions"]:
        symbol = str(lot["symbol"])
        if symbol in exit_symbols:
            cash += float(lot["shares"]) * opens[symbol] * (1.0 - RESET_COST)
        else:
            kept.append(lot)
    reset["positions"] = kept

    # Entry sizing matches the standalone research sleeve: 2.9% of open NAV.
    mark_open = cash
    for lot in reset["positions"]:
        symbol = str(lot["symbol"])
        if symbol not in opens:
            # Fetch active marks only when needed for a pending entry.
            if entry_symbols:
                extra, extra_providers = _open_map_for_symbols([symbol], asof, fetcher)
                opens.update(extra)
                open_providers.update(extra_providers)
        if symbol in opens:
            mark_open += float(lot["shares"]) * opens[symbol]
    pending = sorted(reset["pending_entries"], key=lambda row: (int(row.get("rank_priority") or 99), float(row.get("rsi_signal") or 999), str(row.get("symbol"))))
    for row in pending:
        symbol = str(row["symbol"])
        theme = str(row["theme"])
        if len(reset["positions"]) >= RESET_MAX_POSITIONS:
            continue
        if sum(str(lot.get("theme")) == theme for lot in reset["positions"]) >= RESET_MAX_THEME_POSITIONS:
            continue
        px = opens.get(symbol)
        if not _finite(px):
            raise RuntimeError(f"RESET_ENTRY_OPEN_REQUIRED {symbol}")
        amount = RESET_SLOT * mark_open
        if cash < amount * (1.0 + RESET_COST):
            continue
        cash -= amount * (1.0 + RESET_COST)
        reset["positions"].append({
            "symbol": symbol, "theme": theme, "shares": amount / float(px),
            "entry_date": asof, "sessions_since_entry": 0,
        })
    reset["cash"] = cash
    reset["pending_entries"] = []

    # Advance cooldown / activation market-session ages exactly one session.
    for row in reset["cooldowns"].values():
        row["age_sessions"] = int(row.get("age_sessions") or 0) + 1
    for act in reset["activations"]:
        act["age_sessions"] = int(act.get("age_sessions") or 0) + 1
        act["engine_asof"] = asof
    reset["activations"] = [row for row in reset["activations"] if int(row.get("age_sessions") or 0) <= RESET_SEARCH]

    # Add exact current Day0 leaders from strict LOO persisted features.
    existing_keys = {_activation_key(row) for row in reset["activations"]}
    new_acts: list[dict[str, Any]] = []
    for row in current_day0_candidates(history, asof):
        cd = reset["cooldowns"].get(str(row["symbol"]))
        if isinstance(cd, dict) and int(cd.get("age_sessions") or 0) <= RESET_COOLDOWN:
            continue
        candidate = {**row, "age_sessions": 0, "touched_rsi30": False,
                     "touch_date": None, "signal_date": None, "engine_asof": asof}
        if _activation_key(candidate) not in existing_keys:
            new_acts.append(candidate)
            existing_keys.add(_activation_key(candidate))
    reset["activations"].extend(new_acts)

    # New Day0 symbols need one historical seed. Existing symbols update only from
    # the already-built current universe close.
    needed_symbols = sorted({str(row["symbol"]) for row in reset["activations"]})
    new_state_symbols = [symbol for symbol in needed_symbols if symbol not in reset["rsi_states"]]
    seeded_states, seed_providers = _seed_new_rsi_states(new_state_symbols, asof, fetcher)
    reset["rsi_states"].update(seeded_states)
    for symbol in needed_symbols:
        if symbol in seeded_states:
            continue
        close = universe_close.get(symbol)
        if not _finite(close):
            # Rare symbol missing from today's scanner: use a small chart fallback.
            frames, providers = fetcher([symbol], str((pd.Timestamp(asof) - pd.Timedelta(days=8)).date()), 1)
            frame = frames[symbol]
            target = pd.Timestamp(asof)
            if target not in frame.index or not _finite(frame.at[target, "Close"]):
                raise RuntimeError(f"RESET_CURRENT_CLOSE_REQUIRED {symbol}")
            close = float(frame.at[target, "Close"])
            seed_providers[symbol] = providers[symbol]
        reset["rsi_states"][symbol] = advance_rsi_state(reset["rsi_states"][symbol], float(close))

    # First rise AFTER an earlier <=30 touch, with current Theme Top3 confirmation.
    just_signaled: set[str] = set()
    pending_next: list[dict[str, Any]] = []
    for act in sorted(reset["activations"], key=lambda row: (str(row["day0_date"]), str(row["theme"]), int(row["rank_priority"]), str(row["symbol"]))):
        symbol = str(act["symbol"])
        if act.get("signal_date") or symbol in just_signaled:
            continue
        state = reset["rsi_states"].get(symbol) or {}
        current_rsi = float(state["rsi14"]) if _finite(state.get("rsi14")) else None
        previous_rsi = float(state.get("previous_rsi14")) if _finite(state.get("previous_rsi14")) else None
        # advance_rsi_state does not retain previous; the live loop sets it below.
        if current_rsi is None:
            continue
        if not act.get("touched_rsi30") and current_rsi <= 30.0:
            act["touched_rsi30"] = True
            act["touch_date"] = asof
            continue
        if not act.get("touched_rsi30"):
            continue
        touch_date = str(act.get("touch_date") or "")
        if touch_date == asof:
            continue
        prev = act.get("previous_rsi14")
        if not _finite(prev):
            prev = previous_rsi
        if not _finite(prev) or current_rsi <= float(prev):
            continue
        theme = str(act["theme"])
        if symbol not in current_top3.get(theme, []):
            continue
        act["signal_date"] = asof
        just_signaled.add(symbol)
        reset["cooldowns"][symbol] = {"signal_date": asof, "age_sessions": 0}
        pending_next.append({
            "symbol": symbol, "theme": theme, "signal_date": asof,
            "rank_priority": int(act["rank_priority"]), "rsi_signal": current_rsi,
        })
    reset["pending_entries"] = pending_next

    # Save today's RSI as tomorrow's comparison value after signal evaluation.
    for act in reset["activations"]:
        state = reset["rsi_states"].get(str(act["symbol"])) or {}
        if _finite(state.get("rsi14")):
            act["previous_rsi14"] = float(state["rsi14"])
    for lot in reset["positions"]:
        if str(lot.get("entry_date")) != asof:
            lot["sessions_since_entry"] = int(lot.get("sessions_since_entry") or 0) + 1

    close_map: dict[str, float] = {}
    for lot in reset["positions"]:
        symbol = str(lot["symbol"])
        close = universe_close.get(symbol)
        if not _finite(close):
            frames, providers = fetcher([symbol], str((pd.Timestamp(asof) - pd.Timedelta(days=8)).date()), 1)
            frame = frames[symbol]
            target = pd.Timestamp(asof)
            if target not in frame.index or not _finite(frame.at[target, "Close"]):
                raise RuntimeError(f"RESET_POSITION_CLOSE_REQUIRED {symbol}")
            close = float(frame.at[target, "Close"])
            seed_providers[symbol] = providers[symbol]
        close_map[symbol] = float(close)
    _mark_reset(reset, close_map)
    reset["asof"] = asof
    reset["status"] = "READY"
    reset["strategy"] = "RS63_TOP3_RISE30_SIGTOP3"
    reset["engine_schema"] = "v38-reset-engine-1"
    reset["rebuild_policy"] = "INCREMENTAL_FROM_AUDITED_FULL_SEED; STRICT_PIT_DAY0_FEATURES; UNIVERSE_CLOSE_RSI_UPDATE"
    reset["price_sources"] = {**open_providers, **seed_providers}
    monitor, summary = _best_monitor(reset["activations"], reset["positions"], reset["rsi_states"], current_top3)
    reset["monitor"] = monitor[:100]
    reset["monitor_summary"] = summary
    reset["monitor_note"] = "Display bands only; trading signal remains RSI14<=30 then first rise with Theme RS63 Top3 confirmation."
    return reset
