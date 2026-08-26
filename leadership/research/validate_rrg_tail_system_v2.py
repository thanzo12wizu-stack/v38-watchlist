from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf

import validate_early_rotation as er
import validate_confirmed_leadership as cl
import validate_rrg_tail_system as rt


def download_ohlcvo(symbols: list[str], start: str, end: str, batch_size: int) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    """Research-local adjusted OHLCV downloader including Open.

    This intentionally does not alter the shared pioneer downloader used by existing research.
    """
    field_names = ("Open", "Close", "High", "Low", "Volume")
    frames: dict[str, list[pd.DataFrame]] = {f: [] for f in field_names}
    requested = list(dict.fromkeys(symbols))
    failed_batches = 0
    for pos in range(0, len(requested), batch_size):
        batch = requested[pos: pos + batch_size]
        yf_names = [er.yahoo_symbol(s) for s in batch]
        reverse = {er.yahoo_symbol(s): s for s in batch}
        try:
            raw = yf.download(
                yf_names,
                start=start,
                end=end,
                auto_adjust=True,
                actions=False,
                progress=False,
                group_by="ticker",
                threads=True,
                timeout=30,
            )
        except Exception:
            failed_batches += 1
            continue
        if raw is None or raw.empty:
            failed_batches += 1
            continue
        batch_fields: dict[str, dict[str, pd.Series]] = {f: {} for f in field_names}
        if isinstance(raw.columns, pd.MultiIndex):
            level0 = set(str(x) for x in raw.columns.get_level_values(0))
            for ysym in yf_names:
                if ysym not in level0:
                    continue
                part = raw[ysym]
                sym = reverse[ysym]
                for field in field_names:
                    if field in part.columns:
                        batch_fields[field][sym] = pd.to_numeric(part[field], errors="coerce")
        elif len(batch) == 1:
            sym = batch[0]
            for field in field_names:
                if field in raw.columns:
                    batch_fields[field][sym] = pd.to_numeric(raw[field], errors="coerce")
        for field, cols in batch_fields.items():
            if cols:
                frames[field].append(pd.DataFrame(cols))
        print(f"DOWNLOAD_OHLCVO {min(pos + batch_size, len(requested))}/{len(requested)}", flush=True)

    out: dict[str, pd.DataFrame] = {}
    for field, parts in frames.items():
        if not parts:
            raise RuntimeError(f"Yahoo returned no usable {field} data")
        df = pd.concat(parts, axis=1)
        df = df.loc[:, ~df.columns.duplicated()].sort_index()
        df.index = pd.to_datetime(df.index).tz_localize(None)
        out[field.lower()] = df.replace([np.inf, -np.inf], np.nan)
    common = sorted(set.intersection(*(set(out[k].columns) for k in out)))
    for key in out:
        out[key] = out[key][common]
    return out, {
        "requested": len(requested),
        "downloaded_common_ohlcvo": len(common),
        "rows": int(len(out["close"])),
        "start": str(out["close"].index.min().date()),
        "end": str(out["close"].index.max().date()),
        "failed_batches": failed_batches,
    }


def conversion_by_date(events: pd.DataFrame, col: str) -> dict[str, float | int | None]:
    if events.empty:
        return {"events": 0, "dates": 0, "event_weighted": None, "date_equal": None}
    x = events[["date", col]].dropna().copy()
    if x.empty:
        return {"events": 0, "dates": 0, "event_weighted": None, "date_equal": None}
    return {
        "events": int(len(x)),
        "dates": int(x.date.nunique()),
        "event_weighted": float(x[col].astype(float).mean()),
        "date_equal": float(x.groupby("date", observed=True)[col].mean().mean()),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--output", required=True)
    ap.add_argument("--analysis-start", default="2016-01-04")
    ap.add_argument("--analysis-end", default="2026-06-30")
    ap.add_argument("--max-tickers", type=int, default=6000)
    ap.add_argument("--batch-size", type=int, default=75)
    ap.add_argument("--min-members", type=int, default=3)
    args = ap.parse_args()

    root = Path(args.root)
    out = root / args.output
    out.mkdir(parents=True, exist_ok=True)
    snap = er.load_json(root / "sector_snapshot.json")
    theme_members_all, taxonomy_diag = er.extract_theme_members(snap)
    industry_map = er.read_industry_map(root / "industry_map.json")
    universe = er.read_universe_symbols(root / "universe.csv")
    selected = er.stratified_symbols(theme_members_all, set(industry_map) & universe, args.max_tickers)
    requested = selected + (["SPY"] if "SPY" not in selected else [])
    download_start = str((pd.Timestamp(args.analysis_start) - pd.Timedelta(days=620)).date())
    download_end = str((pd.Timestamp(args.analysis_end) + pd.Timedelta(days=140)).date())
    ohlcv, diag = download_ohlcvo(requested, download_start, download_end, args.batch_size)

    close_all = ohlcv["close"]
    if "SPY" not in close_all.columns:
        raise RuntimeError("SPY missing from OHLCV download")
    stock_cols = [s for s in selected if s in close_all.columns]
    close = close_all[stock_cols]
    open_ = ohlcv["open"][stock_cols]
    high = ohlcv["high"][stock_cols]
    low = ohlcv["low"][stock_cols]
    volume = ohlcv["volume"][stock_cols]
    stock_ret = close.pct_change(fill_method=None)
    spy_ret = close_all["SPY"].pct_change(fill_method=None)

    theme_members = {t: [s for s in members if s in stock_cols] for t, members in theme_members_all.items()}
    member_counts = {t: len(members) for t, members in theme_members.items()}
    theme_ret = er.grouped_equal_weight(stock_ret, theme_members, args.min_members)
    spy63 = er.period_return(spy_ret, 63)
    theme63 = er.period_return(theme_ret, 63)
    theme_pct = theme63.sub(spy63, axis=0).rank(axis=1, pct=True, method="average") * 100.0
    breadth = er.breadth_above_ema21(close, theme_members, args.min_members).reindex(columns=theme_ret.columns)

    industry_groups: dict[str, list[str]] = defaultdict(list)
    for sym in stock_cols:
        if sym in industry_map and industry_map[sym][1]:
            industry_groups[industry_map[sym][1]].append(sym)
    industry_ret = er.grouped_equal_weight(stock_ret, dict(industry_groups), args.min_members)
    industry_weights = er.build_parent_weights(theme_members_all, industry_map)
    industry63 = er.period_return(industry_ret, 63)
    industry_pct = industry63.sub(spy63, axis=0).rank(axis=1, pct=True, method="average") * 100.0
    parent = er.weighted_matrix(industry_pct, industry_weights, list(theme_ret.columns)).reindex(columns=theme_ret.columns)

    start, end = pd.Timestamp(args.analysis_start), pd.Timestamp(args.analysis_end)
    momentum_mask = cl.momentum_mask(theme_pct, parent, breadth)
    momentum_events = er.extract_events(momentum_mask, theme_pct, parent, breadth, member_counts, start, end)
    masks, strength = rt.make_rrg_like(theme_ret, spy_ret, theme_pct, breadth)
    family_map = rt.primary_family(theme_members, industry_map)
    theme_sets = {t: set(members) for t, members in theme_members.items()}

    result: dict[str, Any] = {
        "status": "PRELIMINARY_CURRENT_TAXONOMY_RRG_LIKE_TAIL_V2",
        "bias_warning": "Current universe and current taxonomy are retrospectively applied; treat as hypothesis validation, not survivorship-free proof.",
        "design": {
            "rrg_like_not_jdk": True,
            "theme_event_cooldown": rt.COOLDOWN,
            "same_day_robustness": ["EVENT_WEIGHTED", "DATE_EQUAL", "FAMILY_DATE_EQUAL", "OVERLAP_DEDUP_DATE_EQUAL"],
            "overlap_jaccard_cut": rt.OVERLAP_JACCARD,
            "entry_timing": "signal close known -> next trading day open",
            "symbol_cooldown": rt.COOLDOWN,
            "runner_comparison_requires_full_63_sessions": True,
        },
        "download": diag,
        "taxonomy_candidates": taxonomy_diag,
        "coverage": {"stocks": len(stock_cols), "themes": len(theme_ret.columns), "momentum_events": int(len(momentum_events))},
        "rrg": {},
        "trades": {},
    }

    primary_out: pd.DataFrame | None = None
    for j, (name, mask) in enumerate(masks.items()):
        events = rt.extract_cross_events(mask, strength, start, end)
        eo = rt.add_theme_outcomes(events, theme_ret, spy_ret, momentum_events, momentum_mask)
        eo.to_csv(out / f"rrg_{name.lower()}_events.csv", index=False)
        conf = eo[eo.date >= rt.CONFIRM_START].copy() if len(eo) else eo.copy()
        item: dict[str, Any] = {
            "events": int(len(eo)),
            "event_dates": int(eo.date.nunique()) if len(eo) else 0,
            "confirmation_events": int(len(conf)),
            "conversion": {},
            "returns": {},
        }
        for h in (5, 10, 20):
            item["conversion"][str(h)] = {
                "all_active": conversion_by_date(eo, f"momentum_active_within_{h}"),
                "all_new_event": conversion_by_date(eo, f"momentum_event_within_{h}"),
                "confirmation_active": conversion_by_date(conf, f"momentum_active_within_{h}"),
                "confirmation_new_event": conversion_by_date(conf, f"momentum_event_within_{h}"),
            }
        for h in rt.HORIZONS:
            value = f"spy_excess_{h}"
            all_modes = rt.aggregate_modes(eo, value, family_map, theme_sets)
            conf_modes = rt.aggregate_modes(conf, value, family_map, theme_sets) if len(conf) else {}
            item["returns"][str(h)] = {
                "all": {mode: rt.summary(frame, value, theme_ret.index, 10000 + j * 1000 + h * 20 + i) for i, (mode, frame) in enumerate(all_modes.items())},
                "confirmation_2022_plus": {mode: rt.summary(frame, value, theme_ret.index, 20000 + j * 1000 + h * 20 + i) for i, (mode, frame) in enumerate(conf_modes.items())},
            }
        result["rrg"][name] = item
        if name == "PRIMARY":
            primary_out = eo

    if primary_out is not None and len(primary_out):
        entries = rt.trade_entries(primary_out, theme_members, close, open_, high, low, volume)
        if len(entries):
            # Fair policy comparison: every retained entry must have all 63 post-entry sessions available.
            entries = entries[(entries["signal_pos"] + rt.MAX_HOLD) < len(close)].copy()
        result["coverage"]["full63_entries"] = int(len(entries))
        result["coverage"]["full63_entry_dates"] = int(entries.entry_date.nunique()) if len(entries) else 0
        entries.to_csv(out / "entries_full63.csv", index=False)
        ema10 = close.ewm(span=10, adjust=False, min_periods=8).mean()
        ema21 = close.ewm(span=21, adjust=False, min_periods=15).mean()
        policies = (
            "HOLD20", "HOLD63", "FAST3_RUNNER10", "FAST3_RUNNER21",
            "FAST3_RUNNER21_PARTIAL", "FAST3_THEME_TIGHTEN",
        )
        all_trade_frames: list[pd.DataFrame] = []
        for policy in policies:
            rows = []
            for row in entries.itertuples(index=False):
                z = rt.simulate_one(row, policy, close, open_, high, low, ema10, ema21, momentum_mask)
                rows.append({**row._asdict(), "policy": policy, **z})
            td = pd.DataFrame(rows)
            all_trade_frames.append(td)
            result["trades"][policy] = {period: rt.trade_stats(td, period) for period in ("ALL", "DISCOVERY", "CONFIRMATION")}
        trade_results = pd.concat(all_trade_frames, ignore_index=True) if all_trade_frames else pd.DataFrame()
        trade_results.to_csv(out / "trade_results_full63.csv.gz", index=False, compression="gzip")

    safe_result = rt.safe(result)
    (out / "summary.json").write_text(json.dumps(safe_result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("===RRG_TAIL_V2_RESULT===")
    print(json.dumps(safe_result, ensure_ascii=False, separators=(",", ":")))
    print("===END===", flush=True)


if __name__ == "__main__":
    main()
