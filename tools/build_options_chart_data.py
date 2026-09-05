#!/usr/bin/env python3
"""Build presentation-only OHLCV history for Options Intelligence charts.

This module is deliberately downstream-only:
  * reads the current Options positioning ticker set,
  * fetches daily OHLCV only for chart rendering,
  * never writes to Dashboard, V38, Rotation, ranking, or Options calculations,
  * preserves last-known chart rows per ticker if a refresh fails.
"""
from __future__ import annotations

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

    fresh = sum(1 for r in out.values() if not r.get("stale"))
    stale = sum(1 for r in out.values() if r.get("stale"))
    payload = {
        "schema_version": "1.0",
        "generated_at": now,
        "session_date": str(positioning.get("session_date") or "")[:10],
        "positioning_asof": positioning.get("asof"),
        "source": "presentation_only_yfinance_daily_ohlcv",
        "upstream_read_only": [str(POSITIONING)],
        "summary": {
            "requested": len(tickers),
            "available": len(out),
            "fresh": fresh,
            "stale": stale,
            "failed_without_cache": max(0, len(tickers) - len(out)),
        },
        "errors": errors,
        "tickers": {t: out[t] for t in sorted(out)},
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False))
    return payload


if __name__ == "__main__":
    build()
