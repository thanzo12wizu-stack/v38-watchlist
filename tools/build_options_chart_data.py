#!/usr/bin/env python3
"""Build presentation-only OHLCV and Wall history for Options Intelligence charts.

This module is deliberately downstream-only:
  * reads the current Options positioning ticker set,
  * fetches daily OHLCV only for chart rendering,
  * reads existing Options histories without changing them,
  * never writes to Dashboard, V38, Rotation, ranking, or Options calculations,
  * preserves last-known chart rows per ticker if a price refresh fails.
"""
from __future__ import annotations

import csv
import json
import math
import os
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import yfinance as yf

POSITIONING = Path(os.environ.get("V38_OPT_JSON", "options_positioning.json"))
DETAIL_HISTORY = Path(os.environ.get("V38_OPT_HISTORY", "options_history.csv"))
SCAN_HISTORY = Path(os.environ.get("V38_OPT_SCAN_HISTORY", "options_scan_history.csv"))
OUT = Path(os.environ.get("V38_OPT_CHART_JSON", "options_chart_data.json"))
PERIOD = os.environ.get("V38_OPT_CHART_PERIOD", "1y")
WORKERS = max(1, int(os.environ.get("V38_OPT_CHART_WORKERS", "3")))
ATTEMPTS = max(1, int(os.environ.get("V38_OPT_CHART_ATTEMPTS", "2")))
MAX_BARS = max(220, int(os.environ.get("V38_OPT_CHART_MAX_BARS", "260")))


def _finite(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _boolish(v):
    return str(v or "").strip().lower() in {"1", "true", "yes", "y"}


def _quality_rank(v):
    return {
        "HIGH": 4,
        "OK": 4,
        "MEDIUM": 3,
        "LOW": 1,
    }.get(str(v or "").strip().upper(), 2)


def _old_payload():
    if not OUT.is_file():
        return {}
    try:
        raw = json.loads(OUT.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _positioning():
    if not POSITIONING.is_file():
        raise FileNotFoundError(POSITIONING)
    raw = json.loads(POSITIONING.read_text(encoding="utf-8"))
    tickers = raw.get("tickers") or {}
    if not isinstance(tickers, dict):
        tickers = {}
    return raw, sorted(str(t).strip().upper() for t in tickers if str(t).strip())


def _bar_date(idx):
    try:
        ts = idx
        if hasattr(ts, "tzinfo") and ts.tzinfo is not None:
            ts = ts.tz_convert("America/New_York")
        return ts.date().isoformat()
    except Exception:
        return str(idx)[:10]


def _read_wall_history(tickers):
    """Merge detailed + broad scan histories into one honest daily observation.

    Rules:
      * stale rows are excluded;
      * explicit session mismatches are excluded;
      * LOW quality is excluded from the visual history;
      * legacy wrong-side Call/Put walls are discarded independently;
      * one row per ticker/date is chosen by quality, then DETAIL over SCAN,
        then latest observation/order. No missing days are fabricated here.
    """
    wanted = set(tickers)
    chosen = {}
    order = 0
    sources = (("SCAN", SCAN_HISTORY), ("DETAIL", DETAIL_HISTORY))
    for source, path in sources:
        if not path.is_file():
            continue
        try:
            fh = path.open(encoding="utf-8-sig", newline="")
        except Exception:
            continue
        with fh:
            for row in csv.DictReader(fh):
                order += 1
                ticker = str(row.get("ticker") or "").strip().upper()
                date = str(row.get("price_session_date") or row.get("date") or "")[:10]
                if ticker not in wanted or len(date) != 10:
                    continue
                if _boolish(row.get("stale")):
                    continue
                session_flag = str(row.get("session_consistent") or "").strip()
                if session_flag and not _boolish(session_flag):
                    continue
                confidence = str(row.get("confidence") or "").strip().upper()
                if confidence == "LOW":
                    continue

                spot = _finite(row.get("spot"))
                call = _finite(row.get("call_wall"))
                put = _finite(row.get("put_wall"))
                flip = _finite(row.get("gamma_flip"))

                # Preserve the current directional-wall definition when visualising
                # old history; pre-fix wrong-side concentrations are not relabelled.
                if spot is not None and call is not None and call <= spot:
                    call = None
                if spot is not None and put is not None and put >= spot:
                    put = None
                if call is None and put is None and flip is None:
                    continue

                observed = str(row.get("observed_at") or "")
                score = (
                    _quality_rank(confidence),
                    1 if source == "DETAIL" else 0,
                    observed,
                    order,
                )
                item = {
                    "time": date,
                    "call_wall": round(call, 6) if call is not None else None,
                    "put_wall": round(put, 6) if put is not None else None,
                    "gamma_flip": round(flip, 6) if flip is not None else None,
                    "spot": round(spot, 6) if spot is not None else None,
                    "expiry": str(row.get("expiry") or ""),
                    "confidence": confidence or "UNKNOWN",
                    "source": source,
                }
                key = (ticker, date)
                prev = chosen.get(key)
                if prev is None or score >= prev[0]:
                    chosen[key] = (score, item)

    out = {t: [] for t in tickers}
    for (ticker, _date), (_score, item) in chosen.items():
        out.setdefault(ticker, []).append(item)
    for ticker in out:
        out[ticker].sort(key=lambda x: x["time"])
    return out


def _fetch_once(ticker):
    px = yf.Ticker(ticker).history(
        period=PERIOD,
        interval="1d",
        auto_adjust=False,
        actions=False,
    )
    if px is None or px.empty:
        raise RuntimeError("no price history")
    rows = []
    for idx, row in px.tail(MAX_BARS).iterrows():
        o = _finite(row.get("Open"))
        h = _finite(row.get("High"))
        l = _finite(row.get("Low"))
        c = _finite(row.get("Close"))
        v = _finite(row.get("Volume"))
        if None in (o, h, l, c):
            continue
        if h < max(o, l, c) or l > min(o, h, c):
            continue
        rows.append({
            "time": _bar_date(idx),
            "open": round(o, 6),
            "high": round(h, 6),
            "low": round(l, 6),
            "close": round(c, 6),
            "volume": round(v or 0.0, 2),
        })
    if len(rows) < 30:
        raise RuntimeError(f"insufficient bars: {len(rows)}")
    return {
        "ticker": ticker,
        "bars": rows,
        "history_session_date": rows[-1]["time"],
        "bar_count": len(rows),
        "source": "yfinance_daily_ohlcv_presentation_only",
        "period": PERIOD,
        "interval": "1d",
        "stale": False,
    }


def _fetch(ticker):
    last = None
    for attempt in range(ATTEMPTS):
        try:
            return _fetch_once(ticker)
        except Exception as exc:
            last = exc
            if attempt + 1 < ATTEMPTS:
                time.sleep((attempt + 1) * 1.5 + random.uniform(0, 0.35))
    raise last or RuntimeError("chart fetch failed")


def build():
    positioning, tickers = _positioning()
    wall_history = _read_wall_history(tickers)
    old = _old_payload()
    old_tickers = old.get("tickers") if isinstance(old.get("tickers"), dict) else {}
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    out = {}
    errors = {}

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(_fetch, t): t for t in tickers}
        for fut in as_completed(futures):
            ticker = futures[fut]
            try:
                out[ticker] = fut.result()
            except Exception as exc:
                errors[ticker] = f"{type(exc).__name__}: {str(exc)[:180]}"
                prev = old_tickers.get(ticker)
                if isinstance(prev, dict) and prev.get("bars"):
                    keep = dict(prev)
                    keep["stale"] = True
                    keep["refresh_error"] = errors[ticker]
                    out[ticker] = keep

    for ticker, rec in out.items():
        rec["wall_history"] = wall_history.get(ticker, [])
        rec["wall_history_days"] = len(rec["wall_history"])

    fresh = sum(1 for r in out.values() if not r.get("stale"))
    stale = sum(1 for r in out.values() if r.get("stale"))
    history_tickers = sum(1 for r in out.values() if r.get("wall_history"))
    history_points = sum(len(r.get("wall_history") or []) for r in out.values())
    payload = {
        "schema_version": "1.1",
        "generated_at": now,
        "session_date": str(positioning.get("session_date") or "")[:10],
        "positioning_asof": positioning.get("asof"),
        "source": "presentation_only_yfinance_daily_ohlcv_plus_existing_options_history",
        "upstream_read_only": [str(POSITIONING), str(DETAIL_HISTORY), str(SCAN_HISTORY)],
        "summary": {
            "requested": len(tickers),
            "available": len(out),
            "fresh": fresh,
            "stale": stale,
            "failed_without_cache": max(0, len(tickers) - len(out)),
            "wall_history_tickers": history_tickers,
            "wall_history_points": history_points,
        },
        "errors": errors,
        "tickers": {t: out[t] for t in sorted(out)},
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False))
    return payload


if __name__ == "__main__":
    build()
