#!/usr/bin/env python3
"""Build one presentation-only OHLCV shard for the Options Intelligence universe.

The builder is intentionally downstream-only. It reads universe.csv/state.json and
existing chart caches, fetches only the bucket assigned to this runner, and never
writes to Dashboard/V38/Options ranking inputs.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import yfinance as yf


def finite(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def bucket_for(ticker: str) -> str:
    first = str(ticker or "").strip().upper()[:1]
    return first if "A" <= first <= "Z" else "OTHER"


def yf_symbol(ticker: str) -> str:
    return ticker.replace(".", "-")


def read_session(state_path: Path) -> str:
    raw = json.loads(state_path.read_text(encoding="utf-8"))
    session = str(raw.get("date") or raw.get("session_date") or "")[:10]
    if len(session) != 10:
        raise RuntimeError(f"state session missing: {session!r}")
    return session


def read_symbols(universe_path: Path, bucket: str) -> list[str]:
    out: set[str] = set()
    with universe_path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            ticker = str(row.get("シンボル") or row.get("ticker") or "").strip().upper()
            if not ticker or bucket_for(ticker) != bucket:
                continue
            out.add(ticker)
    return sorted(out)


def compact_bars(rows: list[dict], max_bars: int) -> list[list]:
    out = []
    for row in rows[-max_bars:]:
        t = str(row.get("time") or "")[:10]
        o = finite(row.get("open"))
        h = finite(row.get("high"))
        l = finite(row.get("low"))
        c = finite(row.get("close"))
        v = finite(row.get("volume"))
        if len(t) != 10 or None in (o, h, l, c):
            continue
        if h < max(o, l, c) or l > min(o, h, c):
            continue
        out.append([t, round(o, 6), round(h, 6), round(l, 6), round(c, 6), round(v or 0.0, 2)])
    return out


def expand_bars(rows) -> list[dict]:
    out = []
    for row in rows or []:
        if isinstance(row, list) and len(row) >= 5:
            out.append({
                "time": str(row[0])[:10],
                "open": row[1],
                "high": row[2],
                "low": row[3],
                "close": row[4],
                "volume": row[5] if len(row) > 5 else 0,
            })
        elif isinstance(row, dict):
            out.append(row)
    return out


def load_previous(path: Path) -> dict[str, dict]:
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    tickers = raw.get("tickers") if isinstance(raw, dict) else None
    return tickers if isinstance(tickers, dict) else {}


def load_seed_options(path: Path, bucket: str) -> dict[str, dict]:
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out = {}
    for ticker, rec in (raw.get("tickers") or {}).items():
        ticker = str(ticker).upper()
        if bucket_for(ticker) == bucket and isinstance(rec, dict) and rec.get("bars"):
            out[ticker] = rec
    return out


def load_seed_rotation(directory: Path, bucket: str) -> dict[str, dict]:
    path = directory / f"{bucket}.json"
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out = {}
    for ticker, rec in (raw.get("tickers") or {}).items():
        ticker = str(ticker).upper()
        if isinstance(rec, dict) and rec.get("bars"):
            out[ticker] = rec
    return out


def record_from_any(ticker: str, rec: dict, max_bars: int, session: str | None = None) -> dict | None:
    bars = compact_bars(expand_bars(rec.get("bars") or []), max_bars)
    if len(bars) < 30:
        return None
    last = bars[-1][0]
    return {
        "bars": bars,
        "history_session_date": last,
        "bar_count": len(bars),
        "source": str(rec.get("source") or "existing_chart_cache"),
        "period": "1y",
        "interval": "1d",
        "stale": bool(session and last != session),
    }


def bar_date(index) -> str:
    try:
        ts = index
        if getattr(ts, "tzinfo", None) is not None:
            ts = ts.tz_convert("America/New_York")
        return ts.date().isoformat()
    except Exception:
        return str(index)[:10]


def fetch_once(ticker: str, period: str, max_bars: int) -> list[dict]:
    frame = yf.Ticker(yf_symbol(ticker)).history(
        period=period,
        interval="1d",
        auto_adjust=False,
        actions=False,
    )
    if frame is None or frame.empty:
        raise RuntimeError("no price history")
    rows = []
    for index, row in frame.tail(max_bars).iterrows():
        o = finite(row.get("Open"))
        h = finite(row.get("High"))
        l = finite(row.get("Low"))
        c = finite(row.get("Close"))
        v = finite(row.get("Volume"))
        if None in (o, h, l, c):
            continue
        if h < max(o, l, c) or l > min(o, h, c):
            continue
        rows.append({
            "time": bar_date(index),
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "volume": v or 0.0,
        })
    if len(rows) < 2:
        raise RuntimeError(f"insufficient bars: {len(rows)}")
    return rows


def fetch_with_retry(ticker: str, period: str, max_bars: int, attempts: int) -> list[dict]:
    last = None
    for attempt in range(max(1, attempts)):
        try:
            return fetch_once(ticker, period, max_bars)
        except Exception as exc:
            last = exc
            if attempt + 1 < attempts:
                time.sleep((attempt + 1) * 1.5 + random.uniform(0.0, 0.45))
    raise last or RuntimeError("price fetch failed")


def merge_rows(old_rows, new_rows, max_bars: int) -> list[dict]:
    by_date = {}
    for row in [*expand_bars(old_rows), *new_rows]:
        t = str(row.get("time") or "")[:10]
        if len(t) == 10:
            by_date[t] = row
    return [by_date[key] for key in sorted(by_date)][-max_bars:]


def build(args) -> dict:
    bucket = args.bucket.upper()
    if bucket != "OTHER" and (len(bucket) != 1 or not ("A" <= bucket <= "Z")):
        raise RuntimeError(f"invalid bucket: {bucket}")

    session = read_session(args.state)
    symbols = read_symbols(args.universe, bucket)
    if not symbols:
        raise RuntimeError(f"no universe symbols for bucket {bucket}")

    previous = load_previous(args.previous / f"{bucket}.json") if args.previous else {}
    seeds = {}
    seeds.update(load_seed_rotation(args.rotation_seed, bucket))
    seeds.update(load_seed_options(args.options_seed, bucket))

    records: dict[str, dict] = {}
    errors: dict[str, str] = {}
    to_fetch: list[tuple[str, str]] = []

    for ticker in symbols:
        chosen = None
        for source in (previous.get(ticker), seeds.get(ticker)):
            if isinstance(source, dict):
                rec = record_from_any(ticker, source, args.max_bars, session)
                if rec and (chosen is None or rec["history_session_date"] > chosen["history_session_date"]):
                    chosen = rec
        if chosen:
            records[ticker] = chosen
            if chosen["history_session_date"] == session:
                continue
            to_fetch.append((ticker, "10d"))
        else:
            to_fetch.append((ticker, args.period))

    def task(ticker: str, period: str):
        limit = args.max_bars if period == args.period else min(args.max_bars, 20)
        return ticker, period, fetch_with_retry(ticker, period, limit, args.attempts)

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {pool.submit(task, ticker, period): (ticker, period) for ticker, period in to_fetch}
        for future in as_completed(futures):
            ticker, period = futures[future]
            try:
                _ticker, _period, fresh_rows = future.result()
                base_rows = records.get(ticker, {}).get("bars") or []
                merged = merge_rows(base_rows, fresh_rows, args.max_bars)
                compact = compact_bars(merged, args.max_bars)
                if len(compact) < 30:
                    raise RuntimeError(f"insufficient merged bars: {len(compact)}")
                last = compact[-1][0]
                records[ticker] = {
                    "bars": compact,
                    "history_session_date": last,
                    "bar_count": len(compact),
                    "source": "yfinance_daily_ohlcv_presentation_only",
                    "period": "1y",
                    "interval": "1d",
                    "stale": last != session,
                }
            except Exception as exc:
                errors[ticker] = f"{type(exc).__name__}: {str(exc)[:180]}"
                if ticker in records:
                    records[ticker]["stale"] = records[ticker].get("history_session_date") != session
                    records[ticker]["refresh_error"] = errors[ticker]

    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    available = {ticker: records[ticker] for ticker in symbols if ticker in records}
    fresh = sum(1 for rec in available.values() if rec.get("history_session_date") == session)
    stale = len(available) - fresh
    payload = {
        "schema_version": "1.0",
        "generated_at": generated_at,
        "session_date": session,
        "bucket": bucket,
        "source": "options_intelligence_universe_price_history_presentation_only",
        "requested": len(symbols),
        "available": len(available),
        "fresh": fresh,
        "stale": stale,
        "failed_without_cache": max(0, len(symbols) - len(available)),
        "errors": errors,
        "tickers": available,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(json.dumps({k: payload[k] for k in ("bucket", "session_date", "requested", "available", "fresh", "stale", "failed_without_cache")}, ensure_ascii=False))
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--universe", type=Path, default=Path("universe.csv"))
    parser.add_argument("--state", type=Path, default=Path("state.json"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--previous", type=Path, default=Path("options_price_history"))
    parser.add_argument("--options-seed", type=Path, default=Path("options_chart_data.json"))
    parser.add_argument("--rotation-seed", type=Path, default=Path("rotation/data/stock-chart"))
    parser.add_argument("--period", default="1y")
    parser.add_argument("--max-bars", type=int, default=260)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--attempts", type=int, default=3)
    args = parser.parse_args()
    args.max_bars = max(180, args.max_bars)
    args.workers = max(1, args.workers)
    args.attempts = max(1, args.attempts)
    payload = build(args)
    requested = int(payload.get("requested") or 0)
    available = int(payload.get("available") or 0)
    if requested and available / requested < 0.80:
        raise SystemExit(f"bucket coverage too low: {args.bucket} {available}/{requested}")


if __name__ == "__main__":
    main()
