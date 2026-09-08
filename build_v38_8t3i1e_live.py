#!/usr/bin/env python3
"""Dedicated live candidate builder for the researched V38 8T+3I+1E stock architecture.

Research-only port on the research branch. It builds the CORE candidate Top12 only:
  Trend: Price>=5, DDV10, clinical-biotech exclusion, SMA50>SMA200,
         Close>SMA200, completed Weekly NQSAR Blue/Green; rank by RS63.
  Ignition: Price>=5, DDV10, clinical-biotech exclusion, completed Weekly
            NQSAR Blue/Green, fresh RS radar active within 5 sessions; rank by
            0.50*RS21 + 0.25*HIGH63_PCT + 0.25*ACC21_PCT.
  Merge pattern: T,T,T,I,T,T,T,I,T,T,I,T, de-duplicated.

Important invariants:
- No RS63>=85 or RS189>=85 hard gate on Trend eligibility.
- Candidate Top12 is created BEFORE the DDV20 entry filter. DDV20 is emitted as
  entry_ddv20_pass and remains enforced by build_v38_sleeve_live.
- Early1 is NOT rebuilt here; the existing independent Early1 one-slot sleeve
  remains unchanged.
- Weekly NQSAR uses completed NYSE weeks only, including Thursday release on
  Good-Friday weeks and other Friday-holiday shortened weeks.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf
from pandas.tseries.holiday import (
    AbstractHolidayCalendar,
    GoodFriday,
    Holiday,
    USLaborDay,
    USMartinLutherKingJr,
    USMemorialDay,
    USPresidentsDay,
    USThanksgivingDay,
    nearest_workday,
)

import build_dashboard as bd
from v38_rules import clinical_biotech_exclusion

SCHEMA = "v38-8t3i1e-candidates-1"
MIN_PRICE = 5.0
BASE_DDV = 10_000_000.0
ENTRY_DDV = 20_000_000.0
MIN_COVERAGE = 0.85
PATTERN = ("T", "T", "T", "I", "T", "T", "T", "I", "T", "T", "I", "T")
STATE = {"Red": 0, "Yellow": 1, "Green": 2, "Blue": 3}


class _NYSERegularHolidayCalendar(AbstractHolidayCalendar):
    rules = [
        Holiday("New Years Day", month=1, day=1, observance=nearest_workday),
        USMartinLutherKingJr,
        USPresidentsDay,
        GoodFriday,
        USMemorialDay,
        Holiday("Juneteenth", month=6, day=19, start_date="2022-06-19", observance=nearest_workday),
        Holiday("Independence Day", month=7, day=4, observance=nearest_workday),
        USLaborDay,
        USThanksgivingDay,
        Holiday("Christmas", month=12, day=25, observance=nearest_workday),
    ]


_SPECIAL_NYSE_CLOSURES = {
    pd.Timestamp("2004-06-11"),  # Reagan funeral
    pd.Timestamp("2007-01-02"),  # Ford funeral
    pd.Timestamp("2012-10-29"),  # Hurricane Sandy
    pd.Timestamp("2012-10-30"),
    pd.Timestamp("2018-12-05"),  # G.H.W. Bush funeral
    pd.Timestamp("2025-01-09"),  # Carter funeral
}


def _safe(x: Any) -> Any:
    if isinstance(x, dict):
        return {str(k): _safe(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_safe(v) for v in x]
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, (np.floating, float)):
        z = float(x)
        return z if math.isfinite(z) else None
    if isinstance(x, pd.Timestamp):
        return str(x.date())
    return x


def _normalize(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    if len(out.index):
        idx = pd.to_datetime(out.index)
        if idx.tz is not None:
            idx = idx.tz_localize(None)
        out.index = idx.normalize()
    return out.sort_index().replace([np.inf, -np.inf], np.nan)


def _read_universe(path: Path) -> tuple[list[str], set[str]]:
    symbols: list[str] = []
    excluded: set[str] = set()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            sym = str(row.get("シンボル") or row.get("symbol") or row.get("Symbol") or "").strip().upper()
            if not sym or sym in symbols:
                continue
            symbols.append(sym)
            decision = clinical_biotech_exclusion(
                row.get("業種") or row.get("industry") or row.get("Industry"),
                row.get("時価総額") or row.get("market_cap") or row.get("Market Cap"),
                row.get("売上高TTM") or row.get("revenue_ttm") or row.get("Revenue TTM"),
            )
            if decision.excluded:
                excluded.add(sym)
    return symbols, excluded


def _ys(symbol: str) -> str:
    return symbol.replace(".", "-")


def download_adjusted_ohlcv(
    symbols: list[str], start: str, end: str, batch_size: int = 100
) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    fields = {k: [] for k in ("open", "high", "low", "close", "volume")}
    requested = list(dict.fromkeys(symbols))
    failed_batches = 0
    for pos in range(0, len(requested), batch_size):
        batch = requested[pos : pos + batch_size]
        names = [_ys(s) for s in batch]
        reverse = {_ys(s): s for s in batch}
        try:
            raw = yf.download(
                names,
                start=start,
                end=end,
                auto_adjust=True,
                actions=False,
                progress=False,
                group_by="ticker",
                threads=True,
                timeout=30,
            )
        except Exception as exc:
            print(f"8T3I_DOWNLOAD_FAIL pos={pos} {type(exc).__name__}", flush=True)
            failed_batches += 1
            continue
        if raw is None or raw.empty:
            failed_batches += 1
            continue
        bucket = {k: {} for k in fields}
        if isinstance(raw.columns, pd.MultiIndex):
            level0 = {str(x) for x in raw.columns.get_level_values(0)}
            for name in names:
                if name not in level0:
                    continue
                part = raw[name]
                sym = reverse[name]
                for key, label in (
                    ("open", "Open"),
                    ("high", "High"),
                    ("low", "Low"),
                    ("close", "Close"),
                    ("volume", "Volume"),
                ):
                    if label in part.columns:
                        z = pd.to_numeric(part[label], errors="coerce")
                        if z.notna().any():
                            bucket[key][sym] = z
        elif len(batch) == 1:
            sym = batch[0]
            for key, label in (
                ("open", "Open"),
                ("high", "High"),
                ("low", "Low"),
                ("close", "Close"),
                ("volume", "Volume"),
            ):
                if label in raw.columns:
                    z = pd.to_numeric(raw[label], errors="coerce")
                    if z.notna().any():
                        bucket[key][sym] = z
        for key in fields:
            if bucket[key]:
                fields[key].append(pd.DataFrame(bucket[key]))
        if pos % (batch_size * 5) == 0 or pos + batch_size >= len(requested):
            print(f"8T3I_DOWNLOAD {min(pos + batch_size, len(requested))}/{len(requested)}", flush=True)

    out: dict[str, pd.DataFrame] = {}
    for key, parts in fields.items():
        frame = pd.concat(parts, axis=1) if parts else pd.DataFrame()
        if not frame.empty:
            frame = _normalize(frame)
            frame = frame.loc[:, ~frame.columns.duplicated(keep="last")]
        out[key] = frame
    common = [
        s
        for s in requested
        if all(s in out[k].columns and out[k][s].notna().any() for k in out)
    ]
    for key in out:
        out[key] = out[key].reindex(columns=common)
    quality = {
        "requested": len(requested),
        "downloaded_common": len(common),
        "coverage": len(common) / max(1, len(requested)),
        "failed_batches": failed_batches,
    }
    return out, quality


def nyse_sessions(start: pd.Timestamp | str, end: pd.Timestamp | str) -> pd.DatetimeIndex:
    start = pd.Timestamp(start).normalize()
    end = pd.Timestamp(end).normalize()
    base = pd.date_range(start, end, freq="B")
    holidays = _NYSERegularHolidayCalendar().holidays(start=start, end=end)
    sessions = base.difference(pd.DatetimeIndex(holidays).normalize())
    special = pd.DatetimeIndex(sorted(x for x in _SPECIAL_NYSE_CLOSURES if start <= x <= end))
    if len(special):
        sessions = sessions.difference(special)
    return sessions


def _last_nyse_session(period: pd.Period) -> pd.Timestamp:
    start = pd.Timestamp(period.start_time).normalize()
    end = pd.Timestamp(period.end_time).normalize()
    sessions = nyse_sessions(start, end)
    if not len(sessions):
        raise RuntimeError(f"NO_NYSE_SESSION_FOR_WEEK {period}")
    return pd.Timestamp(sessions[-1]).normalize()


def completed_weekly_ohlc(
    high: pd.DataFrame, low: pd.DataFrame, close: pd.DataFrame, asof: pd.Timestamp
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    target = pd.Timestamp(asof).normalize()
    h = high.loc[high.index <= target]
    l = low.loc[low.index <= target]
    c = close.loc[close.index <= target]
    periods = c.index.to_period("W-FRI")
    hh = h.groupby(periods).max()
    ll = l.groupby(periods).min()
    cc = c.groupby(periods).last()
    actual = pd.Series(c.index, index=periods).groupby(level=0).max().reindex(cc.index)
    keep: list[bool] = []
    for p in cc.index:
        last_expected = _last_nyse_session(p)
        last_actual = pd.Timestamp(actual.loc[p]).normalize() if pd.notna(actual.loc[p]) else pd.NaT
        keep.append(pd.notna(last_actual) and last_actual >= last_expected and last_expected <= target)
    hh = hh.loc[keep]
    ll = ll.loc[keep]
    cc = cc.loc[keep]
    actual = actual.reindex(cc.index)
    idx = pd.DatetimeIndex(pd.to_datetime(actual.to_numpy())).normalize()
    hh.index = idx
    ll.index = idx
    cc.index = idx
    return hh, ll, cc


def exact_states(
    high: pd.DataFrame, low: pd.DataFrame, close: pd.DataFrame, min_rows: int = 30
) -> pd.DataFrame:
    out = pd.DataFrame(np.int8(-1), index=close.index, columns=close.columns)
    good = 0
    for j, sym in enumerate(close.columns, 1):
        z = pd.DataFrame({"h": high[sym], "l": low[sym], "c": close[sym]}).dropna()
        if len(z) < min_rows:
            continue
        h = z.h.to_numpy(float)
        l = z.l.to_numpy(float)
        c = z.c.to_numpy(float)
        sar = bd._psar(h, l, c, step=0.02, mx=0.08)
        ema = z.c.ewm(span=21, adjust=False).mean().to_numpy(float)
        d = z.c.diff()
        up = d.clip(lower=0)
        dn = -d.clip(upper=0)
        ru = up.ewm(alpha=1 / 14, adjust=False).mean()
        rd = dn.ewm(alpha=1 / 14, adjust=False).mean()
        rsi = (100.0 - 100.0 / (1.0 + ru / rd.replace(0, np.nan))).to_numpy(float)
        bd._onimine_state(c, sar, ema, rsi)
        colors = list(bd._LAST_ONIMINE_SERIES or [])
        if len(colors) != len(z):
            continue
        out.loc[z.index, sym] = np.asarray([STATE.get(str(v), -1) for v in colors], dtype=np.int8)
        good += 1
        if j % 500 == 0 or j == len(close.columns):
            print(f"8T3I_WEEKLY_NQSAR {j}/{len(close.columns)} good={good}", flush=True)
    return out


def _pct(values: pd.DataFrame, pool: pd.DataFrame) -> pd.DataFrame:
    return values.where(pool & values.notna()).rank(axis=1, pct=True, method="average") * 100.0


def build_feature_frames(
    ohlcv: dict[str, pd.DataFrame], bio_excluded: set[str], asof: pd.Timestamp
) -> dict[str, Any]:
    target = pd.Timestamp(asof).normalize()
    h = ohlcv["high"].loc[:target]
    l = ohlcv["low"].loc[:target]
    c = ohlcv["close"].loc[:target]
    v = ohlcv["volume"].loc[:target]
    ddv = c * v.rolling(20, min_periods=20).mean()
    pool = (c >= MIN_PRICE) & (ddv >= BASE_DDV)
    ex = [s for s in bio_excluded if s in pool.columns]
    if ex:
        pool.loc[:, ex] = False
    sma50 = c.rolling(50, min_periods=50).mean()
    sma200 = c.rolling(200, min_periods=200).mean()
    struct = pool & (sma50 > sma200) & (c > sma200)
    q21 = _pct(c / c.shift(21) - 1.0, pool)
    q42 = _pct(c / c.shift(42) - 1.0, pool)
    q63 = _pct(c / c.shift(63) - 1.0, pool)
    q189 = _pct(c / c.shift(189) - 1.0, pool)
    prior63 = c.shift(1).rolling(63, min_periods=40).max()
    high63 = _pct(c / prior63, pool)
    acc21 = _pct(q21 - q21.shift(20), pool)
    early_score = 0.50 * q21 + 0.25 * high63 + 0.25 * acc21
    radar = (pool & ((q21 >= 85.0) | (q42 >= 85.0) | (q63 >= 85.0))).fillna(False)
    fresh = (radar & ~radar.shift(1).fillna(False)).fillna(False)
    radar_active = fresh.astype(int).rolling(5, min_periods=1).max().astype(bool)

    wh, wl, wc = completed_weekly_ohlc(h, l, c, target)
    ws0 = exact_states(wh, wl, wc, 30)
    wb = ws0.reindex(c.index).ffill().fillna(-1).astype(np.int8) >= 2
    return {
        "close": c,
        "ddv": ddv,
        "pool": pool,
        "struct": struct,
        "sma50": sma50,
        "sma200": sma200,
        "q21": q21,
        "q42": q42,
        "q63": q63,
        "q189": q189,
        "early_score": early_score,
        "radar_active": radar_active,
        "weekly_bull": wb,
        "weekly_state": ws0,
    }


def candidate_rows(asof: pd.Timestamp, m: dict[str, Any]) -> list[dict[str, Any]]:
    d = pd.Timestamp(asof).normalize()
    if d not in m["close"].index:
        raise RuntimeError(f"8T3I_ASOF_REQUIRED {d.date()}")
    pool = m["pool"].loc[d].fillna(False)
    struct = m["struct"].loc[d].fillna(False)
    wb = m["weekly_bull"].loc[d].fillna(False)
    q63 = pd.to_numeric(m["q63"].loc[d], errors="coerce")
    ddv = pd.to_numeric(m["ddv"].loc[d], errors="coerce")
    early_score = pd.to_numeric(m["early_score"].loc[d], errors="coerce")
    radar = m["radar_active"].loc[d].fillna(False)

    trend = q63.where(pool & struct & wb).dropna().sort_values(ascending=False).index.tolist()
    ignition = early_score.where(pool & wb & radar).dropna().sort_values(ascending=False).index.tolist()
    lists = {"T": trend, "I": ignition}
    ptr = {"T": 0, "I": 0}
    chosen: list[str] = []
    sources: list[str] = []
    for src in PATTERN:
        arr = lists[src]
        while ptr[src] < len(arr) and arr[ptr[src]] in chosen:
            ptr[src] += 1
        if ptr[src] >= len(arr):
            continue
        sym = str(arr[ptr[src]])
        ptr[src] += 1
        chosen.append(sym)
        sources.append(src)

    rows: list[dict[str, Any]] = []
    for rank, (sym, src) in enumerate(zip(chosen[:12], sources[:12]), 1):
        dv = ddv.get(sym, np.nan)
        rs = q63.get(sym, np.nan)
        score = early_score.get(sym, np.nan)
        rows.append(
            {
                "ticker": sym,
                "final_rank": rank,
                "source": "IGNITION" if src == "I" else "TREND",
                "daily_dollar_volume_m": float(dv) / 1_000_000.0 if pd.notna(dv) else None,
                "entry_ddv20_pass": bool(pd.notna(dv) and float(dv) >= ENTRY_DDV),
                "stock_rs63_pct": float(rs) if pd.notna(rs) else None,
                "ignition_score": float(score) if src == "I" and pd.notna(score) else None,
            }
        )
    return rows


def build_state(
    ohlcv: dict[str, pd.DataFrame], bio_excluded: set[str], asof: str, quality: dict[str, Any] | None = None
) -> dict[str, Any]:
    target = pd.Timestamp(asof).normalize()
    m = build_feature_frames(ohlcv, bio_excluded, target)
    rows = candidate_rows(target, m)
    first11 = rows[:11]
    return {
        "schema": SCHEMA,
        "asof": str(target.date()),
        "status": "READY",
        "strategy": "8T3I1E",
        "core_pattern": list(PATTERN),
        "core_attack_cap": 11,
        "core_selective_cap": 3,
        "early1_separate_cap": 1,
        "top12_then_ddv20": True,
        "trend_definition": "Price>=5 & DDV10 & bio-excluded & SMA50>SMA200 & Close>SMA200 & completed Weekly NQSAR Blue/Green; rank RS63; no RS63/RS189 hard threshold",
        "ignition_definition": "Price>=5 & DDV10 & bio-excluded & completed Weekly NQSAR Blue/Green & fresh RS radar active5; rank 0.50*RS21+0.25*HIGH63_PCT+0.25*ACC21_PCT",
        "candidates": rows,
        "first11_source_counts": {
            "TREND": sum(r["source"] == "TREND" for r in first11),
            "IGNITION": sum(r["source"] == "IGNITION" for r in first11),
        },
        "quality": quality or {},
        "production_changed": False,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--asof", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--batch-size", type=int, default=100)
    ap.add_argument("--lookback-days", type=int, default=2200)
    a = ap.parse_args()
    root = Path(a.root)
    target = pd.Timestamp(a.asof).normalize()
    symbols, bio = _read_universe(root / "universe.csv")
    start = str((target - pd.Timedelta(days=a.lookback_days)).date())
    end = str((target + pd.Timedelta(days=1)).date())
    ohlcv, quality = download_adjusted_ohlcv(symbols, start, end, a.batch_size)
    if float(quality.get("coverage") or 0.0) < MIN_COVERAGE:
        raise RuntimeError(f"8T3I_COVERAGE_REQUIRED {quality}")
    if target not in ohlcv["close"].index:
        raise RuntimeError(f"8T3I_ASOF_MARKET_SESSION_REQUIRED {target.date()}")
    state = build_state(ohlcv, bio, str(target.date()), quality)
    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(_safe(state), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("8T3I_READY", json.dumps(_safe({"asof": state["asof"], "rows": len(state["candidates"]), "source_counts": state["first11_source_counts"], "quality": quality}), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
