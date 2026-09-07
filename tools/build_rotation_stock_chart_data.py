#!/usr/bin/env python3
"""Build presentation-only OHLCV shards for Rotation leader charts.

This module is deliberately downstream-only:
  * reads the current public Rotation strong-stock context,
  * fetches daily OHLCV only for chart rendering,
  * never changes Rotation/V38 ranking, market mode, or trading rules,
  * preserves last-known chart rows per ticker if a refresh fails.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import shutil
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import yfinance as yf


def _finite(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _bucket(ticker: str) -> str:
    first = (ticker or "").strip().upper()[:1]
    return first if first and "A" <= first <= "Z" else "OTHER"


def _symbols(context: dict) -> list[str]:
    out: set[str] = set()
    for item in context.get("industry_context") or []:
        if not isinstance(item, dict):
            continue
        stocks = (
            item.get("existing_emerging_or_leading_leaders_in_full_intersection")
            or item.get("existing_emerging_or_leading_leaders_in_top15_intersection")
            or []
        )
        for stock in stocks:
            if not isinstance(stock, dict):
                continue
            symbol = str(stock.get("symbol") or "").strip().upper()
            if symbol:
                out.add(symbol)
    return sorted(out)


def _bar_date(index) -> str:
    try:
        ts = index
        if getattr(ts, "tzinfo", None) is not None:
            ts = ts.tz_convert("America/New_York")
        return ts.date().isoformat()
    except Exception:
        return str(index)[:10]


def _yf_symbol(ticker: str) -> str:
    # Yahoo represents share classes such as BRK.B as BRK-B.
    return ticker.replace(".", "-")


def _fetch_once(ticker: str, period: str, max_bars: int) -> dict:
    prices = yf.Ticker(_yf_symbol(ticker)).history(
        period=period,
        interval="1d",
        auto_adjust=False,
        actions=False,
    )
    if prices is None or prices.empty:
        raise RuntimeError("no price history")

    rows = []
    for index, row in prices.tail(max_bars).iterrows():
        o = _finite(row.get("Open"))
        h = _finite(row.get("High"))
        l = _finite(row.get("Low"))
        c = _finite(row.get("Close"))
        v = _finite(row.get("Volume"))
        if None in (o, h, l, c):
            continue
        if h < max(o, l, c) or l > min(o, h, c):
            continue
        rows.append(
            {
                "time": _bar_date(index),
                "open": round(o, 6),
                "high": round(h, 6),
                "low": round(l, 6),
                "close": round(c, 6),
                "volume": round(v or 0.0, 2),
            }
        )

    if len(rows) < 30:
        raise RuntimeError(f"insufficient bars: {len(rows)}")

    return {
        "ticker": ticker,
        "bars": rows,
        "history_session_date": rows[-1]["time"],
        "bar_count": len(rows),
        "source": "yfinance_daily_ohlcv_presentation_only",
        "period": period,
        "interval": "1d",
        "stale": False,
    }


def _fetch(ticker: str, period: str, max_bars: int, attempts: int) -> dict:
    last = None
    for attempt in range(attempts):
        try:
            return _fetch_once(ticker, period, max_bars)
        except Exception as exc:  # pragma: no cover - network failures vary
            last = exc
            if attempt + 1 < attempts:
                time.sleep((attempt + 1) * 1.4 + random.uniform(0.0, 0.35))
    raise last or RuntimeError("chart fetch failed")


def _load_previous(directory: Path | None) -> dict[str, dict]:
    if directory is None or not directory.is_dir():
        return {}
    out: dict[str, dict] = {}
    for path in directory.glob("*.json"):
        if path.name == "index.json":
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        tickers = payload.get("tickers") if isinstance(payload, dict) else None
        if not isinstance(tickers, dict):
            continue
        for ticker, record in tickers.items():
            if isinstance(record, dict) and record.get("bars"):
                out[str(ticker).upper()] = record
    return out


def build(
    context_path: Path,
    output_dir: Path,
    previous_dir: Path | None,
    period: str,
    max_bars: int,
    workers: int,
    attempts: int,
) -> dict:
    context = json.loads(context_path.read_text(encoding="utf-8"))
    if context.get("status") != "READY":
        raise RuntimeError(f"Rotation stock context not READY: {context.get('status')}")
    asof = str(context.get("asof") or "")[:10]
    if len(asof) != 10:
        raise RuntimeError("Rotation stock context as-of is missing")

    symbols = _symbols(context)
    if not symbols:
        raise RuntimeError("Rotation stock context contains no visible leaders")

    previous = _load_previous(previous_dir)
    records: dict[str, dict] = {}
    errors: dict[str, str] = {}

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {
            pool.submit(_fetch, ticker, period, max_bars, max(1, attempts)): ticker
            for ticker in symbols
        }
        for future in as_completed(futures):
            ticker = futures[future]
            try:
                records[ticker] = future.result()
            except Exception as exc:
                message = f"{type(exc).__name__}: {str(exc)[:180]}"
                errors[ticker] = message
                old = previous.get(ticker)
                if old and old.get("bars"):
                    keep = dict(old)
                    keep["ticker"] = ticker
                    keep["stale"] = True
                    keep["refresh_error"] = message
                    records[ticker] = keep

    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    by_bucket: dict[str, dict[str, dict]] = {}
    for ticker in symbols:
        record = records.get(ticker)
        if not record:
            continue
        by_bucket.setdefault(_bucket(ticker), {})[ticker] = record

    for bucket, tickers in sorted(by_bucket.items()):
        shard = {
            "schema_version": "1.0",
            "generated_at": generated_at,
            "session_date": asof,
            "source": "rotation_visible_leaders_presentation_only",
            "tickers": {ticker: tickers[ticker] for ticker in sorted(tickers)},
        }
        (output_dir / f"{bucket}.json").write_text(
            json.dumps(shard, ensure_ascii=False, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )

    fresh = sum(1 for record in records.values() if not record.get("stale"))
    stale = sum(1 for record in records.values() if record.get("stale"))
    index = {
        "schema_version": "1.0",
        "generated_at": generated_at,
        "session_date": asof,
        "source": "rotation_visible_leaders_presentation_only",
        "requested": len(symbols),
        "available": len(records),
        "fresh": fresh,
        "stale": stale,
        "failed_without_cache": max(0, len(symbols) - len(records)),
        "errors": errors,
        "shards": {bucket: len(tickers) for bucket, tickers in sorted(by_bucket.items())},
        "upstream_read_only": [str(context_path)],
    }
    (output_dir / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(index, ensure_ascii=False, indent=2))
    return index


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--period", default="1y")
    parser.add_argument("--max-bars", type=int, default=260)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--attempts", type=int, default=2)
    args = parser.parse_args()

    index = build(
        context_path=args.context,
        output_dir=args.output,
        previous_dir=args.previous,
        period=args.period,
        max_bars=max(180, args.max_bars),
        workers=max(1, args.workers),
        attempts=max(1, args.attempts),
    )
    requested = int(index.get("requested") or 0)
    available = int(index.get("available") or 0)
    if requested and available / requested < 0.80:
        raise SystemExit(f"Rotation chart coverage too low: {available}/{requested}")


if __name__ == "__main__":
    main()
