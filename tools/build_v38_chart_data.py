#!/usr/bin/env python3
"""Build presentation-only daily OHLCV shards for V38 inline charts.

This is downstream display data only. It reads v38-live-state.json to discover
visible symbols and never changes V38 ranking, Market Mode, sleeves, or rules.
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

SYMBOL_KEYS = {"ticker", "symbol"}
NON_TICKERS = {
    "READY", "LIVE", "STOP", "ATTACK", "SELECTIVE", "DEFENSE",
    "YELLOW", "GREEN", "BLUE", "RED", "NONE", "HOLD", "PASS", "FAIL",
}


def finite(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def looks_like_ticker(value) -> bool:
    text = str(value or "").strip().upper()
    if not text or len(text) > 10 or text in NON_TICKERS:
        return False
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-")
    return all(ch in allowed for ch in text) and any(ch.isalpha() for ch in text)


def bucket(ticker: str) -> str:
    first = str(ticker or "").strip().upper()[:1]
    return first if "A" <= first <= "Z" else "OTHER"


def collect_symbol_fields(node, out: set[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if str(key).lower() in SYMBOL_KEYS and looks_like_ticker(value):
                out.add(str(value).strip().upper())
            collect_symbol_fields(value, out)
    elif isinstance(node, list):
        for value in node:
            collect_symbol_fields(value, out)


def visible_symbols(state: dict) -> list[str]:
    out = {"QQQ", "TQQQ"}
    collect_symbol_fields(state, out)
    ranking = state.get("ranking") if isinstance(state, dict) else {}
    if isinstance(ranking, dict):
        for key, value in ranking.items():
            if not isinstance(value, list):
                continue
            if not any(token in str(key).lower() for token in ("top", "core", "reopen")):
                continue
            for item in value:
                if looks_like_ticker(item):
                    out.add(str(item).strip().upper())
    return sorted(out)


def bar_date(index) -> str:
    try:
        ts = index
        if getattr(ts, "tzinfo", None) is not None:
            ts = ts.tz_convert("America/New_York")
        return ts.date().isoformat()
    except Exception:
        return str(index)[:10]


def yahoo_symbol(ticker: str) -> str:
    return ticker.replace(".", "-")


def fetch_once(ticker: str, period: str, max_bars: int) -> dict:
    prices = yf.Ticker(yahoo_symbol(ticker)).history(
        period=period, interval="1d", auto_adjust=False, actions=False
    )
    if prices is None or prices.empty:
        raise RuntimeError("no price history")

    rows = []
    for index, row in prices.tail(max_bars).iterrows():
        o, h, l, c = (finite(row.get(k)) for k in ("Open", "High", "Low", "Close"))
        v = finite(row.get("Volume"))
        if None in (o, h, l, c):
            continue
        if h < max(o, l, c) or l > min(o, h, c):
            continue
        rows.append({
            "time": bar_date(index),
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
        "source": "yfinance_daily_ohlcv_v38_presentation_only",
        "period": period,
        "interval": "1d",
        "stale": False,
    }


def fetch(ticker: str, period: str, max_bars: int, attempts: int) -> dict:
    last = None
    for attempt in range(attempts):
        try:
            return fetch_once(ticker, period, max_bars)
        except Exception as exc:  # pragma: no cover
            last = exc
            if attempt + 1 < attempts:
                time.sleep((attempt + 1) * 1.4 + random.uniform(0.0, 0.35))
    raise last or RuntimeError("chart fetch failed")


def previous_records(directory: Path | None) -> dict[str, dict]:
    if directory is None or not directory.is_dir():
        return {}
    out = {}
    for path in directory.glob("*.json"):
        if path.name == "index.json":
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for ticker, record in (payload.get("tickers") or {}).items():
            if isinstance(record, dict) and record.get("bars"):
                out[str(ticker).upper()] = record
    return out


def build(state_path: Path, output_dir: Path, previous_dir: Path | None,
          period: str, max_bars: int, workers: int, attempts: int) -> dict:
    state = json.loads(state_path.read_text(encoding="utf-8"))
    asof = str(state.get("asof") or "")[:10]
    if len(asof) != 10:
        raise RuntimeError("V38 live state as-of is missing")
    symbols = visible_symbols(state)
    if not symbols:
        raise RuntimeError("V38 live state contains no visible symbols")

    old = previous_records(previous_dir)
    records, errors = {}, {}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(fetch, t, period, max_bars, max(1, attempts)): t for t in symbols}
        for future in as_completed(futures):
            ticker = futures[future]
            try:
                records[ticker] = future.result()
            except Exception as exc:
                message = f"{type(exc).__name__}: {str(exc)[:180]}"
                errors[ticker] = message
                if ticker in old:
                    keep = dict(old[ticker])
                    keep.update({"ticker": ticker, "stale": True, "refresh_error": message})
                    records[ticker] = keep

    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    grouped: dict[str, dict[str, dict]] = {}
    for ticker in symbols:
        if ticker in records:
            grouped.setdefault(bucket(ticker), {})[ticker] = records[ticker]

    for key, tickers in sorted(grouped.items()):
        payload = {
            "schema_version": "1.0",
            "generated_at": generated_at,
            "session_date": asof,
            "source": "v38_visible_symbols_presentation_only",
            "tickers": {t: tickers[t] for t in sorted(tickers)},
        }
        (output_dir / f"{key}.json").write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )

    fresh = sum(not bool(r.get("stale")) for r in records.values())
    stale = sum(bool(r.get("stale")) for r in records.values())
    index = {
        "schema_version": "1.0",
        "generated_at": generated_at,
        "session_date": asof,
        "source": "v38_visible_symbols_presentation_only",
        "requested": len(symbols),
        "available": len(records),
        "fresh": fresh,
        "stale": stale,
        "failed_without_cache": max(0, len(symbols) - len(records)),
        "errors": errors,
        "shards": {k: len(v) for k, v in sorted(grouped.items())},
        "upstream_read_only": [str(state_path)],
    }
    (output_dir / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(index, ensure_ascii=False, indent=2))
    return index


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--state", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--previous", type=Path)
    p.add_argument("--period", default="1y")
    p.add_argument("--max-bars", type=int, default=260)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--attempts", type=int, default=2)
    args = p.parse_args()

    index = build(
        args.state, args.output, args.previous, args.period,
        max(180, args.max_bars), max(1, args.workers), max(1, args.attempts),
    )
    requested, available = int(index["requested"]), int(index["available"])
    if requested and available / requested < 0.80:
        raise SystemExit(f"V38 chart coverage too low: {available}/{requested}")


if __name__ == "__main__":
    main()
