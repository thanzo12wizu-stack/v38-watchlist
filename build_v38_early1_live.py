#!/usr/bin/env python3
"""Build the canonical V38 Early1 live signal.

This is a production port of the research definition validated as
RS21_HIGH_ACCEL / NOT_RED / DDV20 / max 10 sessions.  The signal itself is
market-mode agnostic: the normal-stock sleeve decides whether ATTACK/SELECTIVE
capacity exists.  The scoring universe follows the research tradable pool:
Price >= $5, rolling 20-session dollar volume >= $10M, with the same structural
small-clinical-biotech exclusion.  Entry candidates must additionally have
current rolling dollar volume >= $20M.

Research formula (source commit 898a684142239fa77ce6dd28b2c35b43e3b188ec):
  score = 0.50*RS21 + 0.25*HIGH63_PCT + 0.25*ACC21_PCT
  radar = tradable_pool & (RS21>=85 or RS42>=85 or RS63>=85)
  active5 = first radar appearance remains actionable for five sessions

No production Dashboard input is modified by this builder.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf

from v38_rules import clinical_biotech_exclusion

SCHEMA = "v38-early1-live-1"
CACHE_SCHEMA = "v38-early1-ohlcv-cache-1"
CACHE_DEFAULT = ".cache/v38-early1/early1-ohlcv.pkl.gz"
BASE_DDV = 10_000_000.0
ENTRY_DDV = 20_000_000.0
MIN_PRICE = 5.0
MIN_HISTORY = 84
LOOKBACK_CALENDAR_DAYS = 190
RECENT_REFRESH_DAYS = 12
MIN_HISTORY_COVERAGE = 0.85
MIN_ASOF_COVERAGE = 0.85
BATCH_SIZE = 100
RETRIES = 3


def _finite(v: Any) -> bool:
    try:
        return math.isfinite(float(v))
    except (TypeError, ValueError):
        return False


def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _read_universe(path: Path) -> tuple[list[str], dict[str, dict[str, Any]]]:
    symbols: list[str] = []
    meta: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            sym = str(row.get("シンボル") or row.get("symbol") or row.get("Symbol") or "").strip().upper()
            if not sym or sym in meta:
                continue
            symbols.append(sym)
            meta[sym] = {
                "industry": row.get("業種") or row.get("industry") or row.get("Industry"),
                "market_cap": row.get("時価総額") or row.get("market_cap") or row.get("Market Cap"),
                "revenue_ttm": row.get("売上高TTM") or row.get("revenue_ttm") or row.get("Revenue TTM"),
            }
    return symbols, meta


def _industry_symbols(path: Path) -> set[str]:
    blob = _load_json(path, {})
    if isinstance(blob, dict) and isinstance(blob.get("map"), dict):
        return {str(s).strip().upper() for s in blob["map"]}
    if isinstance(blob, dict):
        return {str(s).strip().upper() for s in blob}
    return set()


def _bio_excluded(symbols: list[str], meta: dict[str, dict[str, Any]]) -> set[str]:
    out: set[str] = set()
    for sym in symbols:
        row = meta.get(sym, {})
        decision = clinical_biotech_exclusion(
            row.get("industry"), row.get("market_cap"), row.get("revenue_ttm")
        )
        if decision.excluded:
            out.add(sym)
    return out


def _normalize(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    if len(out.index):
        idx = pd.to_datetime(out.index)
        if idx.tz is not None:
            idx = idx.tz_localize(None)
        out.index = idx.normalize()
    return out.sort_index().replace([np.inf, -np.inf], np.nan)


def _load_cache(path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not path.is_file():
        return pd.DataFrame(), pd.DataFrame()
    try:
        blob = pd.read_pickle(path, compression="gzip")
    except Exception:
        return pd.DataFrame(), pd.DataFrame()
    if not isinstance(blob, dict) or blob.get("schema") != CACHE_SCHEMA:
        return pd.DataFrame(), pd.DataFrame()
    close, volume = blob.get("close"), blob.get("volume")
    if not isinstance(close, pd.DataFrame) or not isinstance(volume, pd.DataFrame):
        return pd.DataFrame(), pd.DataFrame()
    return _normalize(close), _normalize(volume)


def _save_cache(path: Path, close: pd.DataFrame, volume: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    pd.to_pickle({"schema": CACHE_SCHEMA, "close": close, "volume": volume}, tmp, compression="gzip")
    os.replace(tmp, path)


def _merge_non_null(base: pd.DataFrame, fresh: pd.DataFrame) -> pd.DataFrame:
    if base.empty:
        return _normalize(fresh)
    if fresh.empty:
        return _normalize(base)
    left, right = _normalize(base), _normalize(fresh)
    idx = left.index.union(right.index)
    cols = left.columns.union(right.columns)
    out = left.reindex(index=idx, columns=cols)
    out.update(right.reindex(index=idx, columns=cols))
    return _normalize(out)


def _download_batch(symbols: list[str], start: str, end: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not symbols:
        return pd.DataFrame(), pd.DataFrame()
    yahoo = [s.replace(".", "-") for s in symbols]
    reverse = {s.replace(".", "-"): s for s in symbols}
    raw = yf.download(
        yahoo, start=start, end=end, auto_adjust=True, actions=False,
        progress=False, group_by="ticker", threads=True, timeout=30,
    )
    if raw is None or raw.empty:
        return pd.DataFrame(), pd.DataFrame()
    cb: dict[str, pd.Series] = {}
    vb: dict[str, pd.Series] = {}
    if isinstance(raw.columns, pd.MultiIndex):
        level0 = {str(x) for x in raw.columns.get_level_values(0)}
        for name in yahoo:
            if name not in level0:
                continue
            part = raw[name]
            if "Close" in part.columns and "Volume" in part.columns:
                cb[reverse[name]] = pd.to_numeric(part["Close"], errors="coerce")
                vb[reverse[name]] = pd.to_numeric(part["Volume"], errors="coerce")
    elif len(symbols) == 1 and "Close" in raw.columns and "Volume" in raw.columns:
        cb[symbols[0]] = pd.to_numeric(raw["Close"], errors="coerce")
        vb[symbols[0]] = pd.to_numeric(raw["Volume"], errors="coerce")
    return _normalize(pd.DataFrame(cb)), _normalize(pd.DataFrame(vb))


def _history_ready(close: pd.DataFrame, volume: pd.DataFrame, sym: str, asof: pd.Timestamp) -> bool:
    if sym not in close.columns or sym not in volume.columns:
        return False
    z = (close[sym].notna() & volume[sym].notna() & (close[sym] > 0) & (volume[sym] >= 0))
    z = z.loc[z.index <= asof]
    return int(z.sum()) >= MIN_HISTORY


def acquire_ohlcv(symbols: list[str], asof: str, cache_path: Path) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    target = pd.Timestamp(asof).normalize()
    start_full = str((target - pd.Timedelta(days=LOOKBACK_CALENDAR_DAYS)).date())
    end = str((target + pd.Timedelta(days=1)).date())
    close, volume = _load_cache(cache_path)
    close = close.loc[(close.index >= pd.Timestamp(start_full)) & (close.index <= target)] if not close.empty else close
    volume = volume.loc[(volume.index >= pd.Timestamp(start_full)) & (volume.index <= target)] if not volume.empty else volume

    full = [s for s in symbols if not _history_ready(close, volume, s, target)]
    full_set = set(full)
    recent = [s for s in symbols if s not in full_set]
    groups: list[tuple[list[str], str]] = []
    if full:
        groups.append((full, start_full))
    if recent:
        groups.append((recent, str(max(target - pd.Timedelta(days=RECENT_REFRESH_DAYS), pd.Timestamp(start_full)).date())))

    failed_batches = 0
    for names, start in groups:
        for pos in range(0, len(names), BATCH_SIZE):
            batch = names[pos:pos + BATCH_SIZE]
            ok = False
            for attempt in range(RETRIES):
                try:
                    c, v = _download_batch(batch, start, end)
                    if not c.empty:
                        close = _merge_non_null(close, c)
                        volume = _merge_non_null(volume, v)
                        ok = True
                        break
                except Exception as exc:
                    print(f"EARLY1_DOWNLOAD_FAILED pos={pos} attempt={attempt+1} {type(exc).__name__}", flush=True)
                if attempt + 1 < RETRIES:
                    time.sleep(1.5 * (attempt + 1))
            if not ok:
                failed_batches += 1
            print(f"EARLY1_DOWNLOAD {min(pos + BATCH_SIZE, len(names))}/{len(names)} start={start}", flush=True)

    close = close.reindex(columns=symbols).loc[(close.index >= pd.Timestamp(start_full)) & (close.index <= target)]
    volume = volume.reindex(index=close.index, columns=symbols)
    history_ready = sum(_history_ready(close, volume, s, target) for s in symbols)
    asof_valid = 0
    if target in close.index:
        asof_valid = int((close.loc[target].notna() & volume.loc[target].notna()).sum())
    hcov = history_ready / max(1, len(symbols))
    acov = asof_valid / max(1, len(symbols))
    quality = {
        "requested": len(symbols), "history_ready": history_ready,
        "history_coverage": hcov, "asof_valid": asof_valid,
        "asof_coverage": acov, "failed_batches": failed_batches,
        "history_min_sessions": MIN_HISTORY, "asof": asof,
        "coverage_ok": hcov >= MIN_HISTORY_COVERAGE and acov >= MIN_ASOF_COVERAGE and target in close.index,
    }
    if quality["coverage_ok"]:
        _save_cache(cache_path, close, volume)
    return close, volume, quality


def _pct_rank(values: pd.DataFrame, pool: pd.DataFrame) -> pd.DataFrame:
    return values.where(pool & values.notna()).rank(axis=1, pct=True, method="average") * 100.0


def calculate_early1(close: pd.DataFrame, volume: pd.DataFrame, symbols: list[str], excluded: set[str], asof: str) -> dict[str, Any]:
    target = pd.Timestamp(asof).normalize()
    close = close.reindex(columns=symbols).apply(pd.to_numeric, errors="coerce")
    volume = volume.reindex(index=close.index, columns=symbols).apply(pd.to_numeric, errors="coerce")
    vol20 = volume.rolling(20, min_periods=20).mean()
    dvol = close * vol20
    pool = (close >= MIN_PRICE) & (dvol >= BASE_DDV)
    if excluded:
        cols = [s for s in excluded if s in pool.columns]
        pool.loc[:, cols] = False

    ret21 = close / close.shift(21) - 1.0
    ret42 = close / close.shift(42) - 1.0
    ret63 = close / close.shift(63) - 1.0
    rs21 = _pct_rank(ret21, pool)
    rs42 = _pct_rank(ret42, pool)
    rs63 = _pct_rank(ret63, pool)
    prior63 = close.shift(1).rolling(63, min_periods=40).max()
    high63 = _pct_rank(close / prior63, pool)
    acc21 = _pct_rank(rs21 - rs21.shift(20), pool)
    score = 0.50 * rs21 + 0.25 * high63 + 0.25 * acc21

    radar = (pool & ((rs21 >= 85.0) | (rs42 >= 85.0) | (rs63 >= 85.0))).fillna(False)
    fresh = (radar & ~radar.shift(1).fillna(False)).fillna(False)
    active5 = fresh.astype(int).rolling(5, min_periods=1).max().astype(bool)

    if target not in close.index:
        raise RuntimeError(f"EARLY1_ASOF_REQUIRED latest={close.index.max() if len(close.index) else None}")
    s = pd.to_numeric(score.loc[target].where(active5.loc[target]), errors="coerce").dropna().sort_values(ascending=False)
    rows: list[dict[str, Any]] = []
    for sym, value in s.items():
        dv = dvol.at[target, sym] if sym in dvol.columns else np.nan
        if not _finite(dv) or float(dv) < ENTRY_DDV:
            continue
        rows.append({
            "rank": len(rows) + 1,
            "ticker": str(sym),
            "score": float(value),
            "rs21": float(rs21.at[target, sym]) if _finite(rs21.at[target, sym]) else None,
            "rs42": float(rs42.at[target, sym]) if _finite(rs42.at[target, sym]) else None,
            "rs63": float(rs63.at[target, sym]) if _finite(rs63.at[target, sym]) else None,
            "high63_pct": float(high63.at[target, sym]) if _finite(high63.at[target, sym]) else None,
            "acc21_pct": float(acc21.at[target, sym]) if _finite(acc21.at[target, sym]) else None,
            "daily_dollar_volume_m": float(dv) / 1_000_000.0,
            "fresh_today": bool(fresh.at[target, sym]),
            "active5": True,
            "entry_ddv20_pass": True,
        })
        if len(rows) >= 40:
            break
    return {
        "schema": SCHEMA,
        "asof": asof,
        "status": "READY",
        "strategy": "RS21_HIGH_ACCEL",
        "gate": "NOT_RED_PLUS_BREADTH_CAPACITY",
        "entry_ddv_m": 20,
        "base_pool_ddv_m": 10,
        "max_slots": 1,
        "max_hold_sessions": 10,
        "direct_core_promotion": True,
        "formula": "0.50*RS21 + 0.25*HIGH63_PCT + 0.25*ACC21_PCT",
        "radar": "Price>=5 & DDV10 & not structural small clinical biotech & (RS21>=85 or RS42>=85 or RS63>=85); first appearance active for 5 sessions",
        "candidates": rows,
        "top1": rows[0] if rows else None,
    }


def build_state(state_path: Path, universe_path: Path, industry_path: Path, cache_path: Path) -> dict[str, Any]:
    state = _load_json(state_path, {})
    asof = str(state.get("date") or "")
    if not asof:
        return {"schema": SCHEMA, "asof": None, "status": "DATA REQUIRED", "reason": "COMMAND_CENTER_ASOF_REQUIRED"}
    symbols, meta = _read_universe(universe_path)
    allowed = _industry_symbols(industry_path)
    if allowed:
        symbols = [s for s in symbols if s in allowed]
    excluded = _bio_excluded(symbols, meta)
    close, volume, quality = acquire_ohlcv(symbols, asof, cache_path)
    if not quality.get("coverage_ok"):
        return {
            "schema": SCHEMA, "asof": asof, "status": "DATA REQUIRED",
            "reason": "EARLY1_OHLCV_COVERAGE_INSUFFICIENT", "download_quality": quality,
        }
    payload = calculate_early1(close, volume, symbols, excluded, asof)
    payload["download_quality"] = quality
    payload["universe_count"] = len(symbols)
    payload["bio_excluded_count"] = len(excluded)
    return payload


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", default="state.json")
    ap.add_argument("--universe", default="universe.csv")
    ap.add_argument("--industry", default="industry_map.json")
    ap.add_argument("--cache", default=CACHE_DEFAULT)
    ap.add_argument("--out", default="v38-early1-live.json")
    args = ap.parse_args()
    payload = build_state(Path(args.state), Path(args.universe), Path(args.industry), Path(args.cache))
    Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"EARLY1_LIVE {payload.get('status')} asof={payload.get('asof')} candidates={len(payload.get('candidates') or [])}", flush=True)
    if payload.get("status") != "READY":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
