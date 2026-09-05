#!/usr/bin/env python3
"""Daily broad Options refresh for every liquid common stock.

This module is intentionally downstream-only:
  * READS command-center.html / state.json / universe.csv / detailed Options output.
  * NEVER writes to Dashboard, V38, Rotation, or Leadership artifacts.
  * Writes only broad Options scan/history/status artifacts.

The daily universe is deliberately broad and does not use RS / Theme / trend:
  - common stock
  - price >= configured minimum (default $5)
  - Dashboard daily-dollar-volume >= configured minimum (default $10M)

Every eligible name is checked every run. Names already refreshed successfully by the
same-session detailed Options builder count as fresh and are not fetched twice. All
remaining eligible names are attempted in throttled batches. "no options" and
"no 7-21DTE expiry" are current observations, not stale-data fallbacks.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pandas as pd
import yfinance as yf

import build_options_positioning_directional as directional

base = directional.base

DASHBOARD_HTML = Path(os.environ.get("V38_OPT_DASHBOARD_HTML", "command-center.html"))
STATE_JSON = Path(os.environ.get("V38_STATE_JSON", "state.json"))
UNIVERSE_CSV = Path(os.environ.get("V38_UNIVERSE_CSV", "universe.csv"))
POSITIONING_JSON = Path(os.environ.get("V38_OPT_JSON", "options_positioning.json"))
SCAN_HIST = Path(os.environ.get("V38_OPT_SCAN_HISTORY", "options_scan_history.csv"))
SCAN_STATE = Path(os.environ.get("V38_OPT_SCAN_STATE", "options_scan_state.json"))
STATUS_JSON = Path(os.environ.get("V38_OPT_DAILY_STATUS", "options_daily_liquid_status.json"))

MIN_PRICE = float(os.environ.get("V38_OPT_MIN_PRICE", "5"))
MIN_DVOL_M = float(os.environ.get("V38_OPT_MIN_DVOL_M", "10"))
WORKERS = max(1, int(os.environ.get("V38_OPT_SCAN_WORKERS", "2")))
BATCH_SIZE = max(1, int(os.environ.get("V38_OPT_DAILY_BATCH_SIZE", "20")))
BATCH_PAUSE_SECONDS = max(0.0, float(os.environ.get("V38_OPT_DAILY_BATCH_PAUSE", "1.5")))
MAX_PASSES = max(1, int(os.environ.get("V38_OPT_DAILY_MAX_PASSES", "3")))
PASS_PAUSE_SECONDS = max(0.0, float(os.environ.get("V38_OPT_DAILY_PASS_PAUSE", "30")))
RATE_LIMIT_PAUSE_SECONDS = max(0.0, float(os.environ.get("V38_OPT_DAILY_RATE_LIMIT_PAUSE", "45")))
MIN_TERMINAL_RATIO = float(os.environ.get("V38_OPT_DAILY_MIN_TERMINAL_RATIO", "0.98"))

TERMINAL = {"ok", "no_options", "no_swing_expiry", "insufficient"}
TRANSIENT = {"rate_limited", "error"}


def _finite(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _day(v: Any) -> str:
    return str(v or "")[:10]


def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _embedded_json(path: Path, name: str) -> Any:
    text = path.read_text(encoding="utf-8")
    marker = f"window.{name}="
    start = text.find(marker)
    if start < 0:
        raise RuntimeError(f"{path}:{marker} not found")
    start += len(marker)
    end = text.find(";</script>", start)
    if end < 0:
        raise RuntimeError(f"{path}: terminator for {name} not found")
    return json.loads(text[start:end])


def _universe_metadata(path: Path) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            ticker = str(row.get("シンボル") or row.get("ticker") or row.get("symbol") or "").strip().upper()
            if not ticker:
                continue
            out[ticker] = {
                "security_type": str(row.get("証券種別") or row.get("security_type") or "").strip().lower(),
                "security_subtype": str(row.get("証券サブタイプ") or row.get("security_subtype") or "").strip().lower(),
                "exchange": str(row.get("取引所") or row.get("exchange") or "").strip(),
                "name": str(row.get("名称") or row.get("name") or "").strip(),
            }
    return out


def load_liquid_universe() -> tuple[list[str], dict[str, dict[str, Any]], dict[str, Any]]:
    """Return broad daily universe from the existing Dashboard liquidity measure."""
    state = _load_json(STATE_JSON, {})
    state_date = _day(state.get("date"))

    calc = _embedded_json(DASHBOARD_HTML, "CALC")
    details = _embedded_json(DASHBOARD_HTML, "DET")
    calc_date = _day(calc.get("asof"))
    if not isinstance(details, dict):
        raise RuntimeError("Dashboard window.DET must be an object")
    if state_date and calc_date and state_date != calc_date:
        raise RuntimeError(f"LIQUIDITY_ASOF_MISMATCH state={state_date} dashboard={calc_date}")
    session_date = state_date or calc_date
    if not session_date:
        raise RuntimeError("LIQUIDITY_SESSION_DATE_REQUIRED")

    meta = _universe_metadata(UNIVERSE_CSV)
    eligible: list[str] = []
    rows: dict[str, dict[str, Any]] = {}
    common_count = 0
    priced_count = 0
    liquid_count = 0

    for raw_ticker, det in details.items():
        ticker = str(raw_ticker or "").strip().upper()
        if not ticker or not isinstance(det, dict):
            continue
        m = meta.get(ticker) or {}
        if m.get("security_type") != "stock" or m.get("security_subtype") != "common":
            continue
        common_count += 1
        px = _finite(det.get("px"))
        dvol = _finite(det.get("dvol"))
        if px is None or px < MIN_PRICE:
            continue
        priced_count += 1
        if dvol is None or dvol < MIN_DVOL_M:
            continue
        liquid_count += 1
        eligible.append(ticker)
        rows[ticker] = {
            "ticker": ticker,
            "price": px,
            "dvol_m": dvol,
            "name": m.get("name") or "",
            "exchange": m.get("exchange") or "",
        }

    eligible = list(dict.fromkeys(eligible))
    quality = {
        "session_date": session_date,
        "liquidity_source": "command-center.html:window.DET.dvol",
        "dashboard_asof": calc_date,
        "state_asof": state_date,
        "dashboard_detail_rows": len(details),
        "common_stock_rows": common_count,
        "price_gte_min_rows": priced_count,
        "liquid_eligible": liquid_count,
        "min_price": MIN_PRICE,
        "min_daily_dollar_volume_m": MIN_DVOL_M,
        "rs_or_theme_filter_used": False,
    }
    return eligible, rows, quality


def _fresh_detail_tickers(eligible: set[str], session_date: str) -> set[str]:
    raw = _load_json(POSITIONING_JSON, {})
    out = set()
    for ticker, rec in (raw.get("tickers") or {}).items():
        tk = str(ticker).strip().upper()
        if tk not in eligible or not isinstance(rec, dict):
            continue
        if rec.get("refresh_failed") or rec.get("stale"):
            continue
        if _day(rec.get("price_session_date")) != session_date:
            continue
        if rec.get("session_consistent") is not True:
            continue
        out.add(tk)
    return out


def _failure_status(exc: Exception) -> str:
    msg = (type(exc).__name__ + " " + str(exc)).lower()
    if any(x in msg for x in ("ratelimit", "rate limit", "too many", "429")):
        return "rate_limited"
    return "error"


def _swing_expiry(expiries: list[str], session_date: str) -> str | None:
    base_day = pd.Timestamp(session_date).normalize()
    candidates = []
    for expiry in expiries or []:
        try:
            dte = int((pd.Timestamp(expiry).normalize() - base_day).days)
        except Exception:
            continue
        if 7 <= dte <= 21:
            candidates.append((abs(dte - 14), dte, str(expiry)))
    if not candidates:
        return None
    candidates.sort()
    return candidates[0][2]


def _atr14(px: pd.DataFrame, spot: float) -> float:
    try:
        tr = pd.concat(
            [
                px["High"] - px["Low"],
                (px["High"] - px["Close"].shift()).abs(),
                (px["Low"] - px["Close"].shift()).abs(),
            ],
            axis=1,
        ).max(axis=1)
        atr = _finite(tr.rolling(14).mean().iloc[-1])
        if atr is None or atr <= 0:
            atr = _finite(tr.tail(14).mean())
        if atr is not None and atr > 0:
            return float(atr)
    except Exception:
        pass
    return max(float(spot) * 0.02, 0.01)


def _fetch_one(ticker: str, session_date: str, dvol_m: float, observed_at: str):
    try:
        y = yf.Ticker(ticker)
        expiries = [str(x) for x in (y.options or [])]
        if not expiries:
            return ticker, "no_options", None, "no option expiries"
        expiry = _swing_expiry(expiries, session_date)
        if not expiry:
            return ticker, "no_swing_expiry", None, "no 7-21DTE expiry"

        px = y.history(period="3mo", auto_adjust=False)
        if px is None or px.empty:
            return ticker, "error", None, "no price history"
        pc = directional._price_context(ticker, px, observed_at)
        spot = float(pc["spot"])
        atr = _atr14(px, spot)

        ch = y.option_chain(expiry)
        # Use the completed market session as the date anchor for DTE/T.
        session_anchor = f"{session_date}T20:00:00+00:00"
        rec = directional.analyse_expiry(ch.calls, ch.puts, spot, expiry, session_anchor)
        if not rec:
            return ticker, "insufficient", None, "no usable 7-21DTE expiry"

        gf = rec.get("gamma_flip")
        row = {
            "date": session_date,
            "ticker": ticker,
            "expiry": rec.get("expiry") or expiry,
            "dte": rec.get("dte"),
            "spot": round(spot, 4),
            "atr14": round(atr, 4),
            "call_wall": rec.get("call_wall"),
            "put_wall": rec.get("put_wall"),
            "gamma_flip": gf,
            "net_gex": round(float(rec.get("net_gex") or 0.0), 2),
            "call_wall_pct": (
                round(float(rec["call_wall"]) / spot - 1.0, 5)
                if rec.get("call_wall") is not None
                else None
            ),
            "put_wall_pct": (
                round(float(rec["put_wall"]) / spot - 1.0, 5)
                if rec.get("put_wall") is not None
                else None
            ),
            "flip_pct": (
                round(float(gf) / spot - 1.0, 5) if gf is not None else None
            ),
            "total_oi": int(float(rec.get("total_oi") or 0)),
            "call_oi": int(float(rec.get("call_oi") or 0)),
            "put_oi": int(float(rec.get("put_oi") or 0)),
            "n_strikes": rec.get("n_strikes"),
            "regime": base.regime(spot, gf, atr),
            "confidence": rec.get("confidence"),
            "expected_move": rec.get("expected_move"),
            "expected_move_pct": rec.get("expected_move_pct"),
            "expected_move_method": rec.get("expected_move_method"),
            "expected_low": rec.get("expected_low"),
            "expected_high": rec.get("expected_high"),
            "observed_at": observed_at,
            "price_session_date": pc.get("price_session_date"),
            "price_source": pc.get("price_source"),
            "history_session_date": pc.get("history_session_date"),
            "session_consistent": pc.get("session_consistent"),
            "dvol_m": round(float(dvol_m), 4),
            "liquidity_source": "command-center.html:window.DET.dvol",
            "period_bucket": "swing_7_21",
        }
        return ticker, "ok", row, ""
    except Exception as exc:
        return ticker, _failure_status(exc), None, f"{type(exc).__name__}: {str(exc)[:180]}"


def _load_state() -> dict[str, Any]:
    raw = _load_json(SCAN_STATE, {})
    return raw if isinstance(raw, dict) else {}


def _write_state(state: dict[str, Any]) -> None:
    SCAN_STATE.write_text(
        json.dumps(state, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )


def _upsert_history(new_rows: list[dict[str, Any]]) -> None:
    if not new_rows:
        return
    merged: dict[tuple[str, str, str], dict[str, Any]] = {}
    fields: list[str] = []
    if SCAN_HIST.is_file():
        with SCAN_HIST.open(encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            for name in reader.fieldnames or []:
                if name not in fields:
                    fields.append(name)
            for row in reader:
                key = (_day(row.get("date")), str(row.get("ticker") or "").upper(), str(row.get("expiry") or ""))
                if key[0] and key[1]:
                    merged[key] = row
    for row in new_rows:
        for name in row:
            if name not in fields:
                fields.append(name)
        key = (_day(row.get("date")), str(row.get("ticker") or "").upper(), str(row.get("expiry") or ""))
        merged[key] = row

    SCAN_HIST.parent.mkdir(parents=True, exist_ok=True)
    with SCAN_HIST.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for key in sorted(merged):
            writer.writerow(merged[key])


def _write_status(payload: dict[str, Any]) -> None:
    STATUS_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def run_daily(count_only: bool = False) -> int:
    eligible, info, universe_quality = load_liquid_universe()
    session_date = universe_quality["session_date"]
    if count_only:
        print(json.dumps(universe_quality, ensure_ascii=False, sort_keys=True))
        return 0

    eligible_set = set(eligible)
    detail_fresh = _fresh_detail_tickers(eligible_set, session_date)
    targets = [tk for tk in eligible if tk not in detail_fresh]
    observed_at = base._now()

    state = _load_state()
    pending = list(targets)
    attempts_by_ticker: dict[str, int] = {}
    final_status: dict[str, str] = {}
    final_error: dict[str, str] = {}
    rows_by_ticker: dict[str, dict[str, Any]] = {}

    started = time.time()
    for pass_no in range(1, MAX_PASSES + 1):
        if not pending:
            break
        if pass_no > 1 and PASS_PAUSE_SECONDS > 0:
            time.sleep(PASS_PAUSE_SECONDS * (pass_no - 1))
        this_pass = list(pending)
        pending = []
        sys.stderr.write(f"[opt-daily] pass={pass_no}/{MAX_PASSES} targets={len(this_pass)}\n")

        for start in range(0, len(this_pass), BATCH_SIZE):
            batch = this_pass[start : start + BATCH_SIZE]
            with ThreadPoolExecutor(max_workers=min(WORKERS, len(batch))) as ex:
                results = list(
                    ex.map(
                        lambda tk: _fetch_one(
                            tk, session_date, float(info[tk]["dvol_m"]), observed_at
                        ),
                        batch,
                    )
                )

            rate_limited = 0
            for ticker, status, row, error in results:
                attempts_by_ticker[ticker] = attempts_by_ticker.get(ticker, 0) + 1
                final_status[ticker] = status
                final_error[ticker] = error or ""
                if row is not None:
                    rows_by_ticker[ticker] = row
                if status == "rate_limited":
                    rate_limited += 1
                if status in TRANSIENT and pass_no < MAX_PASSES:
                    pending.append(ticker)

            done = min(start + len(batch), len(this_pass))
            sys.stderr.write(
                f"[opt-daily] pass={pass_no} {done}/{len(this_pass)} "
                f"rate_limited={rate_limited}\n"
            )
            if rate_limited >= max(2, math.ceil(len(batch) * 0.4)) and RATE_LIMIT_PAUSE_SECONDS > 0:
                sys.stderr.write(
                    f"[opt-daily] provider throttle detected; sleep={RATE_LIMIT_PAUSE_SECONDS:.0f}s\n"
                )
                time.sleep(RATE_LIMIT_PAUSE_SECONDS)
            elif BATCH_PAUSE_SECONDS > 0 and done < len(this_pass):
                time.sleep(BATCH_PAUSE_SECONDS)

    for ticker in targets:
        status = final_status.get(ticker, "error")
        error = final_error.get(ticker, "not attempted")
        state[ticker] = {
            "checked_at": observed_at,
            "session_date": session_date,
            "status": status,
            "error": error or None,
            "attempts": attempts_by_ticker.get(ticker, 0),
            "daily_liquid": True,
        }
    for ticker in detail_fresh:
        state[ticker] = {
            "checked_at": observed_at,
            "session_date": session_date,
            "status": "detail_fresh",
            "error": None,
            "attempts": 0,
            "daily_liquid": True,
        }

    _write_state(state)
    _upsert_history(list(rows_by_ticker.values()))

    counts = {k: 0 for k in ("ok", "no_options", "no_swing_expiry", "insufficient", "rate_limited", "error")}
    for ticker in targets:
        status = final_status.get(ticker, "error")
        counts[status if status in counts else "error"] += 1

    attempted_unique = len(attempts_by_ticker)
    terminal = sum(counts[k] for k in TERMINAL)
    terminal_ratio = terminal / len(targets) if targets else 1.0
    daily_checked_total = len(detail_fresh) + terminal
    daily_checked_ratio = daily_checked_total / len(eligible) if eligible else 1.0
    fresh_options_total = len(detail_fresh) + counts["ok"]
    fresh_options_ratio = fresh_options_total / len(eligible) if eligible else 1.0
    unresolved = len(targets) - terminal

    status_payload = {
        "schema": "options-daily-liquid-status-1",
        "observed_at": observed_at,
        **universe_quality,
        "eligible_total": len(eligible),
        "detail_fresh": len(detail_fresh),
        "broad_requested": len(targets),
        "broad_attempted_unique": attempted_unique,
        "broad_terminal": terminal,
        "broad_terminal_ratio": round(terminal_ratio, 6),
        "daily_checked_total": daily_checked_total,
        "daily_checked_ratio": round(daily_checked_ratio, 6),
        "fresh_options_total": fresh_options_total,
        "fresh_options_ratio": round(fresh_options_ratio, 6),
        "unresolved": unresolved,
        "counts": counts,
        "passes": MAX_PASSES,
        "workers": WORKERS,
        "batch_size": BATCH_SIZE,
        "elapsed_seconds": round(time.time() - started, 1),
        "policy": {
            "daily_all_liquid": True,
            "period": "swing_7_21",
            "stale_fallback_as_current": False,
            "detail_fresh_avoids_duplicate_provider_call": True,
            "transient_failures_retried": True,
        },
    }
    _write_status(status_payload)

    sys.stderr.write(
        "[opt-daily] eligible=%d detail_fresh=%d broad=%d attempted=%d "
        "ok=%d no_options=%d no_swing=%d insufficient=%d rate_limited=%d error=%d "
        "checked=%.1f%% fresh_options=%.1f%% elapsed=%.0fs\n"
        % (
            len(eligible),
            len(detail_fresh),
            len(targets),
            attempted_unique,
            counts["ok"],
            counts["no_options"],
            counts["no_swing_expiry"],
            counts["insufficient"],
            counts["rate_limited"],
            counts["error"],
            daily_checked_ratio * 100.0,
            fresh_options_ratio * 100.0,
            time.time() - started,
        )
    )

    if attempted_unique != len(targets):
        sys.stderr.write(
            f"::error::Daily liquid Options attempt coverage incomplete: "
            f"{attempted_unique}/{len(targets)}\n"
        )
        return 2
    if terminal_ratio < MIN_TERMINAL_RATIO:
        sys.stderr.write(
            f"::error::Daily liquid Options terminal coverage {terminal_ratio:.1%} "
            f"below required {MIN_TERMINAL_RATIO:.1%}. Previous committed snapshot is preserved.\n"
        )
        return 2
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count-only", action="store_true")
    args = parser.parse_args()
    return run_daily(count_only=args.count_only)


if __name__ == "__main__":
    sys.exit(main())
