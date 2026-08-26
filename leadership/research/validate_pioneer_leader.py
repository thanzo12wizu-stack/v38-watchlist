from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf

import validate_early_rotation as er
import validate_confirmed_leadership as cl

HORIZONS = (5, 10, 20)
FEATURES = (
    "within_theme_rs63_pct",
    "within_theme_rs_accel20_pct",
    "price_breakout_recency20_pct",
    "volume_expansion_5v20_pct",
)
FEATURE_LABELS = {
    "within_theme_rs63_pct": "WITHIN_THEME_RS63",
    "within_theme_rs_accel20_pct": "WITHIN_THEME_RS_ACCEL20",
    "price_breakout_recency20_pct": "PRICE_BREAKOUT_RECENCY20",
    "volume_expansion_5v20_pct": "VOLUME_EXPANSION_5V20",
}
TOP_CUT = 2.0 / 3.0
BOTTOM_CUT = 1.0 / 3.0


def download_ohlcv(symbols: list[str], start: str, end: str, batch_size: int) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    fields = {k: [] for k in ("Close", "High", "Low", "Volume")}
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
        batch_fields = {k: {} for k in fields}
        if isinstance(raw.columns, pd.MultiIndex):
            level0 = set(str(x) for x in raw.columns.get_level_values(0))
            for ysym in yf_names:
                if ysym not in level0:
                    continue
                part = raw[ysym]
                sym = reverse[ysym]
                for field in fields:
                    if field in part.columns:
                        batch_fields[field][sym] = pd.to_numeric(part[field], errors="coerce")
        elif len(batch) == 1:
            sym = batch[0]
            for field in fields:
                if field in raw.columns:
                    batch_fields[field][sym] = pd.to_numeric(raw[field], errors="coerce")
        for field, cols in batch_fields.items():
            if cols:
                fields[field].append(pd.DataFrame(cols))
        print(f"DOWNLOAD {min(pos + batch_size, len(requested))}/{len(requested)}", flush=True)
    out: dict[str, pd.DataFrame] = {}
    for field, frames in fields.items():
        if not frames:
            raise RuntimeError(f"Yahoo download returned no usable {field} data")
        df = pd.concat(frames, axis=1)
        df = df.loc[:, ~df.columns.duplicated()].sort_index()
        df.index = pd.to_datetime(df.index).tz_localize(None)
        out[field.lower()] = df.replace([np.inf, -np.inf], np.nan)
    common = sorted(set(out["close"].columns) & set(out["high"].columns) & set(out["low"].columns) & set(out["volume"].columns))
    for key in out:
        out[key] = out[key][common]
    diag = {
        "requested": len(requested),
        "downloaded_common_ohlcv": len(common),
        "rows": int(len(out["close"])),
        "start": str(out["close"].index.min().date()),
        "end": str(out["close"].index.max().date()),
        "failed_batches": failed_batches,
    }
    return out, diag


def breakout_recency(close: pd.DataFrame, lookback: int = 20, max_age: int = 20) -> pd.DataFrame:
    prior_high = close.rolling(lookback, min_periods=max(5, int(lookback * 0.8))).max().shift(1)
    broke = close > prior_high
    arr = np.full(close.shape, np.nan, dtype=float)
    for j, col in enumerate(close.columns):
        last = -10_000
        valid = close[col].notna().to_numpy()
        flags = broke[col].fillna(False).to_numpy(bool)
        for i in range(len(close)):
            if not valid[i]:
                continue
            if flags[i]:
                last = i
            age = i - last
            arr[i, j] = float(max_age - age + 1) if 0 <= age <= max_age else 0.0
    return pd.DataFrame(arr, index=close.index, columns=close.columns)


def volume_expansion(volume: pd.DataFrame) -> pd.DataFrame:
    recent = volume.rolling(5, min_periods=3).mean()
    prior = volume.shift(5).rolling(20, min_periods=12).mean()
    return (recent / prior.replace(0.0, np.nan)).replace([np.inf, -np.inf], np.nan)


def within_members_pct(values: pd.Series) -> pd.Series:
    x = pd.to_numeric(values, errors="coerce")
    if x.notna().sum() < 3:
        return pd.Series(np.nan, index=values.index)
    return x.rank(pct=True, method="average")


def compound_daily(ret: pd.Series, horizon: int) -> float:
    x = pd.to_numeric(ret, errors="coerce").dropna()
    if len(x) < max(1, int(math.ceil(horizon * 0.8))):
        return np.nan
    x = x[x > -0.999999]
    if len(x) < max(1, int(math.ceil(horizon * 0.8))):
        return np.nan
    return float(np.expm1(np.log1p(x).sum()))


def event_peer_returns(stock_ret: pd.DataFrame, members: list[str], pos: int, horizon: int) -> dict[str, float]:
    if pos < 0 or pos + horizon >= len(stock_ret):
        return {}
    dates = stock_ret.index[pos + 1:pos + horizon + 1]
    part = stock_ret.loc[dates, members]
    sums = part.sum(axis=1, skipna=True)
    counts = part.notna().sum(axis=1)
    out: dict[str, float] = {}
    for sym in members:
        sr = part[sym]
        peer_count = counts - sr.notna().astype(int)
        peer_daily = (sums - sr.fillna(0.0)) / peer_count.replace(0, np.nan)
        peer_daily = peer_daily.where(peer_count >= 2)
        out[sym] = compound_daily(peer_daily, horizon)
    return out


def extract_stock_rows(
    events: pd.DataFrame,
    theme_members: dict[str, list[str]],
    stock_close: pd.DataFrame,
    stock_high: pd.DataFrame,
    stock_low: pd.DataFrame,
    stock_ret: pd.DataFrame,
    spy_ret: pd.Series,
    stock63: pd.DataFrame,
    breakout_score: pd.DataFrame,
    vol_expansion: pd.DataFrame,
) -> pd.DataFrame:
    spy_fwd = {h: er.forward_return(spy_ret, h) for h in HORIZONS}
    stock_fwd = {h: er.forward_return(stock_ret, h) for h in HORIZONS}
    rows: list[dict[str, Any]] = []
    date_pos = {pd.Timestamp(d): i for i, d in enumerate(stock_close.index)}

    for ei, event in enumerate(events.itertuples(index=False)):
        date = pd.Timestamp(event.date)
        theme = str(event.theme)
        pos = date_pos.get(date, -1)
        if pos < 20:
            continue
        members = [s for s in theme_members.get(theme, []) if s in stock_close.columns]
        if len(members) < 3:
            continue
        current63 = stock63.loc[date, members]
        past_date = stock_close.index[pos - 20]
        past63 = stock63.loc[past_date, members]
        rs_now = within_members_pct(current63)
        rs_past = within_members_pct(past63)
        accel_raw = rs_now - rs_past
        accel_pct = within_members_pct(accel_raw)
        breakout_pct = within_members_pct(breakout_score.loc[date, members])
        volume_pct = within_members_pct(vol_expansion.loc[date, members])
        peer_by_h = {h: event_peer_returns(stock_ret, members, pos, h) for h in HORIZONS}
        future_rank_by_h: dict[int, pd.Series] = {}
        for h in HORIZONS:
            fpos = pos + h
            if fpos < len(stock_close):
                future_rank_by_h[h] = within_members_pct(stock63.iloc[fpos][members])
            else:
                future_rank_by_h[h] = pd.Series(np.nan, index=members)
        event_id = f"{date.date()}|{theme}"
        for sym in members:
            entry = stock_close.at[date, sym]
            if pd.isna(entry) or entry <= 0:
                continue
            row: dict[str, Any] = {
                "event_id": event_id,
                "event_index": ei,
                "date": date,
                "theme": theme,
                "symbol": sym,
                "theme_rs_pct": float(event.theme_rs_pct),
                "parent_rs_pct": float(event.parent_rs_pct),
                "confirmed_parent80": bool(float(event.parent_rs_pct) >= 80.0),
                "within_theme_rs63_pct": float(rs_now.get(sym)) if pd.notna(rs_now.get(sym)) else np.nan,
                "within_theme_rs_accel20_pct": float(accel_pct.get(sym)) if pd.notna(accel_pct.get(sym)) else np.nan,
                "price_breakout_recency20_pct": float(breakout_pct.get(sym)) if pd.notna(breakout_pct.get(sym)) else np.nan,
                "volume_expansion_5v20_pct": float(volume_pct.get(sym)) if pd.notna(volume_pct.get(sym)) else np.nan,
            }
            for h in HORIZONS:
                sr = stock_fwd[h].at[date, sym] if date in stock_fwd[h].index else np.nan
                sp = spy_fwd[h].at[date] if date in spy_fwd[h].index else np.nan
                pr = peer_by_h[h].get(sym, np.nan)
                future_dates = stock_close.index[pos + 1:min(pos + h + 1, len(stock_close))]
                highs = stock_high.loc[future_dates, sym].dropna()
                lows = stock_low.loc[future_dates, sym].dropna()
                row[f"stock_ret_{h}"] = sr
                row[f"stock_minus_peers_{h}"] = sr - pr if pd.notna(sr) and pd.notna(pr) else np.nan
                row[f"stock_minus_spy_{h}"] = sr - sp if pd.notna(sr) and pd.notna(sp) else np.nan
                row[f"mfe_{h}"] = float(highs.max() / entry - 1.0) if len(highs) else np.nan
                row[f"mae_{h}"] = float(lows.min() / entry - 1.0) if len(lows) else np.nan
                fr = future_rank_by_h[h].get(sym, np.nan)
                row[f"future_top20_{h}"] = float(fr >= 0.8) if pd.notna(fr) else np.nan
            rows.append(row)
        if (ei + 1) % 500 == 0:
            print(f"EVENT_FEATURES {ei + 1}/{len(events)} rows={len(rows)}", flush=True)
    return pd.DataFrame(rows)


def paired_event_differences(rows: pd.DataFrame, feature: str, outcome: str) -> pd.DataFrame:
    use = rows[["event_id", "date", "theme", feature, outcome]].dropna().copy()
    use["bucket"] = np.where(use[feature] >= TOP_CUT, "TOP", np.where(use[feature] <= BOTTOM_CUT, "BOTTOM", "MID"))
    use = use[use["bucket"] != "MID"]
    if use.empty:
        return pd.DataFrame(columns=["event_id", "date", "theme", "diff"])
    grouped = use.groupby(["event_id", "date", "theme", "bucket"], observed=True)[outcome].mean().unstack("bucket")
    if "TOP" not in grouped.columns or "BOTTOM" not in grouped.columns:
        return pd.DataFrame(columns=["event_id", "date", "theme", "diff"])
    grouped = grouped.dropna(subset=["TOP", "BOTTOM"]).reset_index()
    grouped["diff"] = grouped["TOP"] - grouped["BOTTOM"]
    return grouped[["event_id", "date", "theme", "diff"]]


def bootstrap_mean(diff: pd.DataFrame, cluster: str, seed: int, reps: int = 4000) -> list[float | None]:
    if diff.empty:
        return [None, None]
    grouped = diff.groupby(cluster, observed=True)["diff"].mean().to_numpy(float)
    if len(grouped) < 2:
        return [None, None]
    rng = np.random.default_rng(seed)
    samples = rng.choice(grouped, size=(reps, len(grouped)), replace=True).mean(axis=1)
    lo, hi = np.quantile(samples, [0.025, 0.975])
    return [float(lo), float(hi)]


def feature_test(rows: pd.DataFrame, feature: str, outcome: str, seed: int) -> dict[str, Any]:
    diff = paired_event_differences(rows, feature, outcome)
    if diff.empty:
        return {"events": 0, "mean_top_minus_bottom": None, "median_event_diff": None, "positive_event_rate": None, "event_ci95": [None, None], "date_ci95": [None, None]}
    return {
        "events": int(len(diff)),
        "dates": int(diff["date"].nunique()),
        "themes": int(diff["theme"].nunique()),
        "mean_top_minus_bottom": float(diff["diff"].mean()),
        "median_event_diff": float(diff["diff"].median()),
        "positive_event_rate": float((diff["diff"] > 0).mean()),
        "event_ci95": bootstrap_mean(diff, "event_id", seed),
        "date_ci95": bootstrap_mean(diff, "date", seed + 10000),
    }


def summarize(rows: pd.DataFrame) -> dict[str, Any]:
    result: dict[str, Any] = {}
    contexts = {
        "ALL_MOMENTUM": rows,
        "CONFIRMED_PARENT80": rows[rows["confirmed_parent80"]],
    }
    for context, part in contexts.items():
        ctx: dict[str, Any] = {
            "rows": int(len(part)),
            "events": int(part["event_id"].nunique()),
            "dates": int(part["date"].nunique()),
            "themes": int(part["theme"].nunique()),
            "features": {},
        }
        for fi, feature in enumerate(FEATURES):
            f: dict[str, Any] = {}
            for h in HORIZONS:
                primary = feature_test(part, feature, f"stock_minus_peers_{h}", 1000 + fi * 100 + h)
                f[str(h)] = {
                    "stock_minus_peers": primary,
                    "stock_minus_spy": feature_test(part, feature, f"stock_minus_spy_{h}", 2000 + fi * 100 + h),
                    "raw_stock_return": feature_test(part, feature, f"stock_ret_{h}", 3000 + fi * 100 + h),
                    "mfe": feature_test(part, feature, f"mfe_{h}", 4000 + fi * 100 + h),
                    "mae": feature_test(part, feature, f"mae_{h}", 5000 + fi * 100 + h),
                    "future_top20": feature_test(part, feature, f"future_top20_{h}", 6000 + fi * 100 + h),
                    "primary_supported": bool(
                        primary["event_ci95"][0] is not None
                        and primary["date_ci95"][0] is not None
                        and primary["event_ci95"][0] > 0
                        and primary["date_ci95"][0] > 0
                    ),
                }
            ctx["features"][FEATURE_LABELS[feature]] = f
        result[context] = ctx
    return result


def safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [safe(v) for v in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (np.floating, float)):
        x = float(value)
        return x if math.isfinite(x) else None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", default="leadership/research/pioneer_output")
    parser.add_argument("--analysis-start", default="2016-01-04")
    parser.add_argument("--analysis-end", default="2026-06-20")
    parser.add_argument("--max-tickers", type=int, default=1500)
    parser.add_argument("--batch-size", type=int, default=75)
    parser.add_argument("--min-members", type=int, default=3)
    args = parser.parse_args()

    root = Path(args.root)
    output = root / args.output
    output.mkdir(parents=True, exist_ok=True)

    snapshot = er.load_json(root / "sector_snapshot.json")
    theme_members_all, taxonomy_candidates = er.extract_theme_members(snapshot)
    industry_map = er.read_industry_map(root / "industry_map.json")
    universe = er.read_universe_symbols(root / "universe.csv")
    selected = er.stratified_symbols(theme_members_all, set(industry_map) & universe, args.max_tickers)
    requested = selected + (["SPY"] if "SPY" not in selected else [])
    download_start = str((pd.Timestamp(args.analysis_start) - pd.Timedelta(days=420)).date())
    download_end = str((pd.Timestamp(args.analysis_end) + pd.Timedelta(days=100)).date())
    ohlcv, download_diag = download_ohlcv(requested, download_start, download_end, args.batch_size)
    close = ohlcv["close"]
    if "SPY" not in close.columns:
        raise RuntimeError("SPY benchmark missing from Yahoo download")

    stock_cols = [s for s in selected if s in close.columns]
    stock_close = close[stock_cols]
    stock_high = ohlcv["high"][stock_cols]
    stock_low = ohlcv["low"][stock_cols]
    stock_volume = ohlcv["volume"][stock_cols]
    stock_ret = er.arithmetic_returns(stock_close)
    spy_ret = er.arithmetic_returns(close[["SPY"]])["SPY"]

    theme_members = {theme: [s for s in members if s in stock_cols] for theme, members in theme_members_all.items()}
    member_counts = {theme: len(members) for theme, members in theme_members.items()}
    theme_ret = er.grouped_equal_weight(stock_ret, theme_members, args.min_members)

    industry_groups: dict[str, list[str]] = {}
    for sym in stock_cols:
        pair = industry_map.get(sym)
        if pair and pair[1]:
            industry_groups.setdefault(pair[1], []).append(sym)
    industry_ret = er.grouped_equal_weight(stock_ret, industry_groups, args.min_members)
    parent_weights = er.build_parent_weights(theme_members_all, industry_map)
    common_themes = sorted(set(theme_ret.columns) & set(parent_weights))
    theme_ret = theme_ret[common_themes]

    theme63 = er.period_return(theme_ret, 63)
    spy63 = er.period_return(spy_ret, 63)
    theme_pct = theme63.sub(spy63, axis=0).rank(axis=1, pct=True, method="average") * 100.0
    industry63 = er.period_return(industry_ret, 63)
    industry_pct = industry63.sub(spy63, axis=0).rank(axis=1, pct=True, method="average") * 100.0
    parent_pct = er.weighted_matrix(industry_pct, parent_weights, common_themes)
    breadth = er.breadth_above_ema21(stock_close, theme_members, args.min_members).reindex(columns=common_themes)

    start, end = pd.Timestamp(args.analysis_start), pd.Timestamp(args.analysis_end)
    mask = cl.momentum_mask(theme_pct, parent_pct, breadth)
    events = er.extract_events(mask, theme_pct, parent_pct, breadth, member_counts, start, end)

    stock63 = er.period_return(stock_ret, 63)
    breakout_score = breakout_recency(stock_close, 20, 20)
    vol_exp = volume_expansion(stock_volume)
    rows = extract_stock_rows(events, theme_members, stock_close, stock_high, stock_low, stock_ret, spy_ret, stock63, breakout_score, vol_exp)
    tests = summarize(rows)

    result = {
        "status": "PRELIMINARY_FIXED_CURRENT_TAXONOMY",
        "question": "Which stock-level features identify future leaders inside the same Subtheme Momentum events?",
        "bias_warning": "Current ticker→subtheme membership is applied retrospectively and the downloaded stock universe is a current-taxonomy sample. This is hypothesis filtering, not final point-in-time proof.",
        "momentum_definition_frozen": cl.MOMENTUM_CONFIG,
        "feature_definitions_frozen_before_outcomes": {
            "WITHIN_THEME_RS63": "Current 63-trading-day stock return ranked cross-sectionally within the signal theme.",
            "WITHIN_THEME_RS_ACCEL20": "Change in within-theme 63d RS percentile from 20 trading days earlier, re-ranked within the signal theme.",
            "PRICE_BREAKOUT_RECENCY20": "Recency score for a close above the prior rolling 20-day high during the latest 20 trading days, ranked within theme.",
            "VOLUME_EXPANSION_5V20": "Mean volume over latest 5 days divided by mean volume over the preceding 20 days, ranked within theme.",
        },
        "comparison_policy": "For every event-theme, compare the top third versus bottom third of each feature. Primary outcome is stock forward return minus an equal-weight arithmetic-return benchmark of the other current theme members, excluding the tested stock. No threshold optimization after outcomes.",
        "horizons": list(HORIZONS),
        "analysis_window": [args.analysis_start, args.analysis_end],
        "download": download_diag,
        "taxonomy_candidates": taxonomy_candidates,
        "coverage": {
            "selected_stocks": len(stock_cols),
            "themes_current_taxonomy": len(theme_members_all),
            "themes_with_signal_model": len(common_themes),
            "momentum_events": int(len(events)),
            "momentum_themes": int(events["theme"].nunique()) if not events.empty else 0,
            "event_stock_rows": int(len(rows)),
        },
        "tests": tests,
    }
    safe_result = safe(result)
    rows.to_csv(output / "event_stock_features.csv.gz", index=False, compression="gzip")
    (output / "summary.json").write_text(json.dumps(safe_result, ensure_ascii=False, indent=2), encoding="utf-8")
    compact = {
        "status": safe_result["status"],
        "coverage": safe_result["coverage"],
        "tests": safe_result["tests"],
    }
    print("=== PIONEER_LEADER_RESULT_JSON ===", flush=True)
    print(json.dumps(compact, ensure_ascii=False, indent=2), flush=True)
    print("=== END_PIONEER_LEADER_RESULT_JSON ===", flush=True)


if __name__ == "__main__":
    main()
