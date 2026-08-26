from __future__ import annotations

import argparse
import csv
import json
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
import yfinance as yf


HORIZONS = (5, 10, 20)
DISCOVERY_END = pd.Timestamp("2021-12-31")
VALIDATION_START = pd.Timestamp("2022-01-01")
VALIDATION_END = pd.Timestamp("2026-06-30")


@dataclass(frozen=True)
class UniverseRow:
    symbol: str
    sector: str


def load_universe(path: Path) -> list[UniverseRow]:
    rows: list[UniverseRow] = []
    seen: set[str] = set()
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            symbol = str(row.get("シンボル") or row.get("symbol") or row.get("Symbol") or "").strip().upper()
            sector = str(row.get("セクター") or row.get("sector") or "").strip()
            if not symbol or symbol in seen or not sector:
                continue
            seen.add(symbol)
            rows.append(UniverseRow(symbol, sector))
    return rows


def yahoo_symbol(symbol: str) -> str:
    return symbol.replace("/", "-").replace(".", "-")


def _extract_field(downloaded: pd.DataFrame, query_symbols: list[str], field: str) -> pd.DataFrame:
    if downloaded is None or downloaded.empty:
        return pd.DataFrame()
    if isinstance(downloaded.columns, pd.MultiIndex):
        l0 = set(map(str, downloaded.columns.get_level_values(0)))
        l1 = set(map(str, downloaded.columns.get_level_values(1)))
        if field in l0:
            out = downloaded[field].copy()
        elif field in l1:
            out = downloaded.xs(field, axis=1, level=1).copy()
        else:
            return pd.DataFrame()
    else:
        if len(query_symbols) != 1 or field not in downloaded.columns:
            return pd.DataFrame()
        out = downloaded[[field]].copy()
        out.columns = [query_symbols[0]]
    out = out.apply(pd.to_numeric, errors="coerce")
    return out


def download_panel(symbols: list[str], *, start_date: str, batch_size: int) -> dict[str, pd.DataFrame]:
    fields = {"Close": [], "High": [], "Low": []}
    for start in range(0, len(symbols), batch_size):
        source = symbols[start:start + batch_size]
        query = [yahoo_symbol(s) for s in source]
        data = yf.download(
            query,
            start=start_date,
            interval="1d",
            auto_adjust=True,
            actions=False,
            progress=False,
            threads=True,
            group_by="column",
            timeout=30,
        )
        reverse = {q: s for q, s in zip(query, source)}
        for field in fields:
            frame = _extract_field(data, query, field)
            if not frame.empty:
                frame = frame.rename(columns=reverse)
                fields[field].append(frame)
        print(f"download {min(start + batch_size, len(symbols))}/{len(symbols)}", flush=True)
    out: dict[str, pd.DataFrame] = {}
    for field, parts in fields.items():
        if not parts:
            out[field] = pd.DataFrame()
            continue
        frame = pd.concat(parts, axis=1)
        frame = frame.loc[:, ~frame.columns.duplicated()]
        frame.index = pd.to_datetime(frame.index).tz_localize(None)
        out[field] = frame.sort_index()
    return out


def rolling_rel_high(relative: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    prior = relative.rolling(window, min_periods=window).max().shift(1)
    return relative.gt(prior)


def rolling_z(series: pd.Series, window: int = 252) -> pd.Series:
    mean = series.rolling(window, min_periods=80).mean()
    std = series.rolling(window, min_periods=80).std(ddof=0).replace(0, np.nan)
    return (series - mean) / std


def eventize(signal: pd.Series, cooldown: int = 20) -> list[pd.Timestamp]:
    dates: list[pd.Timestamp] = []
    last_pos = -10_000
    prev = False
    for i, value in enumerate(signal.fillna(False).astype(bool).to_numpy()):
        if value and not prev and i - last_pos >= cooldown:
            dates.append(signal.index[i])
            last_pos = i
        prev = value
    return dates


def sector_index(close: pd.DataFrame, members: list[str]) -> pd.Series:
    cols = [s for s in members if s in close.columns]
    if not cols:
        return pd.Series(dtype=float)
    rets = close[cols].pct_change(fill_method=None)
    ew = rets.mean(axis=1, skipna=True).fillna(0.0)
    return (1.0 + ew).cumprod()


def sector_features(
    close: pd.DataFrame,
    spy: pd.Series,
    members: list[str],
) -> tuple[pd.DataFrame, pd.Series]:
    cols = [s for s in members if s in close.columns]
    c = close[cols]
    stock_rel = c.div(spy, axis=0)
    rel_high = rolling_rel_high(stock_rel, 20)
    rel_high_breadth = rel_high.mean(axis=1)
    rel_high_5 = rel_high_breadth.rolling(5, min_periods=3).mean()
    velocity = rel_high_5 - rel_high_5.shift(5)
    velocity_z = rolling_z(velocity)

    ema21 = c.ewm(span=21, adjust=False, min_periods=21).mean()
    above21 = c.gt(ema21).mean(axis=1)

    idx = sector_index(close, cols)
    idx_ema21 = idx.ewm(span=21, adjust=False, min_periods=21).mean()
    sec_rel = idx / (spy / float(spy.dropna().iloc[0]))
    sec_rel20 = sec_rel.pct_change(20, fill_method=None)
    sec_rel20_delta = sec_rel20 - sec_rel20.shift(5)

    feats = pd.DataFrame({
        "rel_high_breadth5": rel_high_5,
        "diffusion_velocity": velocity,
        "diffusion_z": velocity_z,
        "above21_share": above21,
        "sector_rel20": sec_rel20,
        "sector_rel20_delta": sec_rel20_delta,
        "sector_above21": idx.gt(idx_ema21),
    })
    return feats, idx


def ignition_signal(features: pd.DataFrame) -> pd.Series:
    level_floor = features["rel_high_breadth5"].rolling(252, min_periods=80).quantile(0.60)
    return (
        features["diffusion_z"].ge(1.0)
        & features["rel_high_breadth5"].ge(level_floor)
        & features["above21_share"].ge(0.55)
        & features["sector_rel20"].gt(0)
        & features["sector_rel20_delta"].gt(0)
        & features["sector_above21"].fillna(False)
    )


def fwd_return(series: pd.Series, date: pd.Timestamp, horizon: int) -> float | None:
    try:
        i = series.index.get_loc(date)
    except KeyError:
        return None
    if isinstance(i, slice) or i + horizon >= len(series):
        return None
    a, b = series.iloc[i], series.iloc[i + horizon]
    if pd.isna(a) or pd.isna(b) or a <= 0:
        return None
    return float(b / a - 1.0)


def cross_sectional_rank(close: pd.DataFrame, date: pd.Timestamp, horizon: int) -> pd.Series:
    if date not in close.index:
        return pd.Series(dtype=float)
    i = close.index.get_loc(date)
    if isinstance(i, slice) or i < horizon:
        return pd.Series(dtype=float)
    ret = close.iloc[i].div(close.iloc[i - horizon]).sub(1.0)
    return ret.rank(pct=True) * 100.0


def recent_breakout_mask(relative: pd.DataFrame, date: pd.Timestamp, lookback: int = 10) -> tuple[pd.Series, pd.Series]:
    if date not in relative.index:
        return pd.Series(False, index=relative.columns), pd.Series(np.nan, index=relative.columns)
    i = relative.index.get_loc(date)
    if isinstance(i, slice) or i < 30:
        return pd.Series(False, index=relative.columns), pd.Series(np.nan, index=relative.columns)
    high = rolling_rel_high(relative, 20)
    window = high.iloc[max(0, i - lookback):i]
    mask = window.any(axis=0)
    ages = pd.Series(np.nan, index=relative.columns)
    for col in relative.columns:
        hits = np.flatnonzero(window[col].fillna(False).to_numpy())
        if len(hits):
            ages[col] = float(i - (max(0, i - lookback) + hits[-1]))
    return mask, ages


def matched_controls(
    sector_symbols: list[str],
    leaders: list[str],
    rs63: pd.Series,
    rs189: pd.Series,
) -> dict[str, str]:
    controls: dict[str, str] = {}
    used: set[str] = set()
    candidates = [s for s in sector_symbols if s not in leaders]
    for leader in leaders:
        if leader not in rs63.index or leader not in rs189.index:
            continue
        best: tuple[float, str] | None = None
        for c in candidates:
            if c in used or c not in rs63.index or c not in rs189.index:
                continue
            if pd.isna(rs63[c]) or pd.isna(rs189[c]):
                continue
            dist = abs(float(rs63[c] - rs63[leader])) + 0.5 * abs(float(rs189[c] - rs189[leader]))
            if best is None or dist < best[0]:
                best = (dist, c)
        if best:
            controls[leader] = best[1]
            used.add(best[1])
    return controls


def bootstrap_ci(values: pd.Series, clusters: pd.Series, *, iterations: int, seed: int) -> tuple[float | None, float | None]:
    valid = pd.DataFrame({"v": values, "c": clusters}).dropna()
    if valid.empty or valid["c"].nunique() < 2:
        return None, None
    rng = random.Random(seed)
    names = list(valid["c"].unique())
    means: list[float] = []
    for _ in range(iterations):
        sample = [rng.choice(names) for _ in names]
        pieces = [valid.loc[valid["c"] == c, "v"] for c in sample]
        means.append(float(pd.concat(pieces, ignore_index=True).mean()))
    lo, hi = np.quantile(means, [0.025, 0.975])
    return float(lo), float(hi)


def summarize(df: pd.DataFrame, value_col: str, *, iterations: int = 1000) -> dict[str, Any]:
    d = df[np.isfinite(pd.to_numeric(df[value_col], errors="coerce"))].copy()
    if d.empty:
        return {"n": 0, "mean": None}
    d[value_col] = pd.to_numeric(d[value_col], errors="coerce")
    d["block20"] = (pd.to_datetime(d["date"]).map(pd.Timestamp.toordinal) // 20).astype(int)
    result: dict[str, Any] = {
        "n": int(len(d)),
        "mean": float(d[value_col].mean()),
        "median": float(d[value_col].median()),
        "positive_rate": float((d[value_col] > 0).mean()),
    }
    for name in ("block20", "sector", "symbol"):
        if name not in d.columns:
            continue
        lo, hi = bootstrap_ci(d[value_col], d[name], iterations=iterations, seed=41 + len(name))
        result[f"{name}_ci95"] = [lo, hi]
    if "sector" in d.columns:
        sec = d.groupby("sector")[value_col].mean()
        result["sector_positive_share"] = float((sec > 0).mean()) if len(sec) else None
        result["sectors"] = int(len(sec))
    return result


def split_name(date: pd.Timestamp) -> str | None:
    if date <= DISCOVERY_END:
        return "2016-2021"
    if VALIDATION_START <= date <= VALIDATION_END:
        return "2022-2026H1"
    return None


def run(args: argparse.Namespace) -> dict[str, Any]:
    universe = load_universe(args.universe)
    if args.max_symbols:
        universe = universe[:args.max_symbols]
    symbols = [r.symbol for r in universe]
    sector_map: dict[str, list[str]] = {}
    for r in universe:
        sector_map.setdefault(r.sector, []).append(r.symbol)

    query = [args.benchmark] + [s for s in symbols if s != args.benchmark]
    panel = download_panel(query, start_date=args.start_date, batch_size=args.batch_size)
    close = panel["Close"].dropna(axis=1, how="all")
    high = panel["High"].reindex_like(close)
    low = panel["Low"].reindex_like(close)
    if args.benchmark not in close.columns:
        raise RuntimeError("benchmark unavailable")
    spy = close[args.benchmark].dropna()
    common_index = close.index.intersection(spy.index)
    close = close.reindex(common_index)
    high = high.reindex(common_index)
    low = low.reindex(common_index)
    spy = spy.reindex(common_index)

    valid_symbols = [s for s in symbols if s in close.columns and close[s].notna().sum() >= 250]
    close = close[[args.benchmark] + [s for s in valid_symbols if s != args.benchmark]]
    high = high.reindex(columns=close.columns)
    low = low.reindex(columns=close.columns)

    sector_rows: list[dict[str, Any]] = []
    leader_rows: list[dict[str, Any]] = []
    entry_rows: list[dict[str, Any]] = []
    symbol_last_event: dict[str, int] = {}
    date_pos = {d: i for i, d in enumerate(close.index)}

    for sector, raw_members in sector_map.items():
        members = [s for s in raw_members if s in close.columns and s != args.benchmark]
        if len(members) < args.min_sector_members:
            continue
        feats, sec_idx = sector_features(close, spy, members)
        signal = ignition_signal(feats)
        events = eventize(signal, cooldown=20)
        stock_to_sector_rel = close[members].div(sec_idx, axis=0)

        for event_date in events:
            split = split_name(event_date)
            if split is None:
                continue
            row = {"date": event_date, "sector": sector, "symbol": sector, "split": split}
            for h in HORIZONS:
                sec_ret = fwd_return(sec_idx, event_date, h)
                spy_ret = fwd_return(spy, event_date, h)
                row[f"excess_{h}d"] = (sec_ret - spy_ret) if sec_ret is not None and spy_ret is not None else np.nan
            row.update({
                "diffusion_z": float(feats.at[event_date, "diffusion_z"]) if pd.notna(feats.at[event_date, "diffusion_z"]) else np.nan,
                "rel_high_breadth5": float(feats.at[event_date, "rel_high_breadth5"]) if pd.notna(feats.at[event_date, "rel_high_breadth5"]) else np.nan,
                "above21_share": float(feats.at[event_date, "above21_share"]) if pd.notna(feats.at[event_date, "above21_share"]) else np.nan,
            })
            sector_rows.append(row)

            rs63 = cross_sectional_rank(close.drop(columns=[args.benchmark], errors="ignore"), event_date, 63)
            rs189 = cross_sectional_rank(close.drop(columns=[args.benchmark], errors="ignore"), event_date, 189)
            pre_mask, ages = recent_breakout_mask(stock_to_sector_rel, event_date, 10)
            i = date_pos[event_date]
            current_rel = stock_to_sector_rel.loc[event_date]
            rel_high20 = stock_to_sector_rel.rolling(20, min_periods=20).max().loc[event_date]
            persistent = current_rel.div(rel_high20).sub(1.0).ge(-0.03)
            leaders = [
                s for s in members
                if bool(pre_mask.get(s, False))
                and bool(persistent.get(s, False))
                and float(rs63.get(s, 0) or 0) >= 80
                and float(rs189.get(s, 0) or 0) >= 80
                and i - symbol_last_event.get(s, -10_000) >= 20
            ]
            controls = matched_controls(members, leaders, rs63, rs189)

            for s in leaders:
                symbol_last_event[s] = i
                lr = {"date": event_date, "sector": sector, "symbol": s, "split": split, "lead_age": ages.get(s)}
                control = controls.get(s)
                for h in HORIZONS:
                    sr = fwd_return(close[s], event_date, h)
                    sec_r = fwd_return(sec_idx, event_date, h)
                    lr[f"sector_excess_{h}d"] = (sr - sec_r) if sr is not None and sec_r is not None else np.nan
                    if control:
                        cr = fwd_return(close[control], event_date, h)
                        lr[f"matched_diff_{h}d"] = (sr - cr) if sr is not None and cr is not None else np.nan
                lr["control"] = control
                lr["rs63"] = float(rs63.get(s)) if pd.notna(rs63.get(s)) else np.nan
                lr["rs189"] = float(rs189.get(s)) if pd.notna(rs189.get(s)) else np.nan
                leader_rows.append(lr)

                ema21 = close[s].ewm(span=21, adjust=False, min_periods=21).mean()
                for j in range(i + 1, min(i + 8, len(close.index))):
                    d = close.index[j]
                    if pd.isna(low.at[d, s]) or pd.isna(close.at[d, s]) or pd.isna(ema21.at[d]):
                        continue
                    if low.at[d, s] <= ema21.at[d] * 1.01 and close.at[d, s] >= ema21.at[d] and close.at[d, s] >= close[s].iloc[j - 1]:
                        er = {"date": d, "event_date": event_date, "sector": sector, "symbol": s, "split": split, "trigger": "EMA21_RECLAIM"}
                        for h in (5, 10, 20):
                            sr = fwd_return(close[s], d, h)
                            sec_r = fwd_return(sec_idx, d, h)
                            er[f"sector_excess_{h}d"] = (sr - sec_r) if sr is not None and sec_r is not None else np.nan
                        entry_rows.append(er)
                        break

    sectors_df = pd.DataFrame(sector_rows)
    leaders_df = pd.DataFrame(leader_rows)
    entries_df = pd.DataFrame(entry_rows)

    report: dict[str, Any] = {
        "schema": 1,
        "method": {
            "sector_event": "relative-high breadth diffusion z>=1, level>=rolling 60th pct, >21EMA share>=55%, sector relative 20d positive+accelerating, synthetic sector >21EMA",
            "sector_cooldown": 20,
            "leader": "pre-event T-10..T-1 Stock/Sector relative 20d high, current persistence within 3%, RS63>=80, RS189>=80",
            "symbol_cooldown": 20,
            "entry": "first EMA21 reclaim in T+1..T+7",
            "bootstrap": "20-day date blocks plus sector/symbol cluster resampling",
        },
        "coverage": {
            "source_symbols": len(symbols),
            "valid_symbols": len(valid_symbols),
            "sectors": len({r["sector"] for r in sector_rows}),
            "sector_events": len(sector_rows),
            "leader_events": len(leader_rows),
            "entry_events": len(entry_rows),
        },
        "sector": {},
        "leader": {},
        "entry": {},
    }
    for split in ("2016-2021", "2022-2026H1"):
        sd = sectors_df[sectors_df.get("split") == split] if not sectors_df.empty else pd.DataFrame()
        ld = leaders_df[leaders_df.get("split") == split] if not leaders_df.empty else pd.DataFrame()
        ed = entries_df[entries_df.get("split") == split] if not entries_df.empty else pd.DataFrame()
        report["sector"][split] = {f"{h}d": summarize(sd, f"excess_{h}d", iterations=args.bootstrap) if not sd.empty else {"n": 0} for h in HORIZONS}
        report["leader"][split] = {}
        for h in HORIZONS:
            report["leader"][split][f"sector_excess_{h}d"] = summarize(ld, f"sector_excess_{h}d", iterations=args.bootstrap) if not ld.empty else {"n": 0}
            report["leader"][split][f"matched_diff_{h}d"] = summarize(ld, f"matched_diff_{h}d", iterations=args.bootstrap) if not ld.empty else {"n": 0}
        report["entry"][split] = {f"sector_excess_{h}d": summarize(ed, f"sector_excess_{h}d", iterations=args.bootstrap) if not ed.empty else {"n": 0} for h in HORIZONS}

    validation = report["entry"]["2022-2026H1"].get("sector_excess_10d", {})
    block_ci = validation.get("block20_ci95") or [None, None]
    sector_ci = validation.get("sector_ci95") or [None, None]
    adoption = (
        (validation.get("n") or 0) >= 50
        and (validation.get("mean") or -999) >= 0.003
        and block_ci[0] is not None and block_ci[0] > 0
        and sector_ci[0] is not None and sector_ci[0] > 0
        and (validation.get("sector_positive_share") or 0) >= 0.60
    )
    report["decision"] = {
        "adopt": bool(adoption),
        "rule": "Validation EMA21-reclaim 10d sector excess >=+0.30%, block and sector CI lower>0, >=60% sectors positive, n>=50",
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.events:
        args.events.parent.mkdir(parents=True, exist_ok=True)
        sectors_df.to_csv(args.events.with_name("diffusion_sector_events.csv"), index=False)
        leaders_df.to_csv(args.events.with_name("diffusion_leader_events.csv"), index=False)
        entries_df.to_csv(args.events.with_name("diffusion_entry_events.csv"), index=False)
    return report


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--universe", type=Path, default=Path("universe.csv"))
    p.add_argument("--output", type=Path, default=Path("leadership/research/diffusion_report.json"))
    p.add_argument("--events", type=Path, default=Path("leadership/research/events.csv"))
    p.add_argument("--benchmark", default="SPY")
    p.add_argument("--start-date", default="2015-01-01")
    p.add_argument("--batch-size", type=int, default=80)
    p.add_argument("--max-symbols", type=int, default=0)
    p.add_argument("--min-sector-members", type=int, default=20)
    p.add_argument("--bootstrap", type=int, default=1000)
    args = p.parse_args()
    report = run(args)
    print(json.dumps({"coverage": report["coverage"], "decision": report["decision"], "validation": report["entry"]["2022-2026H1"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
