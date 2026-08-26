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
import validate_pioneer_leader as pl
import validate_rs_periods as rs
import validate_sector_stock_stack as ss
import validate_ignition_entry as ie

HORIZONS = (5, 10, 20)
DISCOVERY_END = pd.Timestamp("2021-12-31")
CONFIRM_START = pd.Timestamp("2022-01-01")
ENTRY_WINDOW = 20

FEATURES = (
    "close_location",
    "rvol20",
    "signed_rvol20",
    "ema21_atr",
    "sma50_atr",
    "dist_prior_high20",
    "dist_prior_high63",
    "compression_5v20",
    "gap_pct",
    "rs252_pct",
)

FEATURE_BUCKETS: dict[str, tuple[tuple[str, float | None, float | None], ...]] = {
    "close_location": (("LT50", None, 0.50), ("50_75", 0.50, 0.75), ("GE75", 0.75, None)),
    "rvol20": (("LT1", None, 1.0), ("1_1P5", 1.0, 1.5), ("GE1P5", 1.5, None)),
    "signed_rvol20": (("LE0", None, 0.0), ("0_1P5", 0.0, 1.5), ("GE1P5", 1.5, None)),
    "ema21_atr": (("LT1", None, 1.0), ("1_2", 1.0, 2.0), ("GE2", 2.0, None)),
    "sma50_atr": (("LT2", None, 2.0), ("2_4", 2.0, 4.0), ("GE4", 4.0, None)),
    "dist_prior_high20": (("LE_M5PCT", None, -0.05), ("M5_TO_0", -0.05, 0.0), ("GE0_BREAKOUT", 0.0, None)),
    "dist_prior_high63": (("LE_M5PCT", None, -0.05), ("M5_TO_0", -0.05, 0.0), ("GE0_BREAKOUT", 0.0, None)),
    "compression_5v20": (("LE0P75", None, 0.75), ("0P75_1", 0.75, 1.0), ("GT1", 1.0, None)),
    "gap_pct": (("DOWN_GE2", None, -0.02), ("ABS_LT2", -0.02, 0.02), ("UP_GE2", 0.02, None)),
    "rs252_pct": (("BOTTOM_THIRD", None, 1.0 / 3.0), ("MID_THIRD", 1.0 / 3.0, 2.0 / 3.0), ("TOP_THIRD", 2.0 / 3.0, None)),
}

CANDIDATE_FILTERS = (
    "ALL_CONTINUOUS",
    "STRONG_CLOSE_RVOL",
    "TIGHT_BREAKOUT20",
    "FRESH_NOT_EXTENDED",
    "RS252_TOP",
    "IND_LT80_ONLY",
)


def safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe(v) for v in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (np.floating, float)):
        x = float(value)
        return x if math.isfinite(x) else None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


def download_ohlcv(symbols: list[str], start: str, end: str, batch_size: int) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    fields = {k: [] for k in ("Open", "Close", "High", "Low", "Volume")}
    requested = list(dict.fromkeys(symbols))
    failed_batches = 0
    for pos in range(0, len(requested), batch_size):
        batch = requested[pos:pos + batch_size]
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
    common = sorted(set.intersection(*(set(df.columns) for df in out.values())))
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


def true_range(high: pd.DataFrame, low: pd.DataFrame, close: pd.DataFrame) -> pd.DataFrame:
    prev = close.shift(1)
    a = (high - low).to_numpy(float)
    b = (high - prev).abs().to_numpy(float)
    c = (low - prev).abs().to_numpy(float)
    stack = np.stack([a, b, c], axis=0)
    arr = np.nanmax(stack, axis=0)
    all_nan = np.isnan(stack).all(axis=0)
    arr[all_nan] = np.nan
    return pd.DataFrame(arr, index=close.index, columns=close.columns)


def compute_feature_matrices(ohlcv: dict[str, pd.DataFrame], stock_cols: list[str], stock_ret: pd.DataFrame) -> dict[str, pd.DataFrame]:
    open_ = ohlcv["open"][stock_cols]
    close = ohlcv["close"][stock_cols]
    high = ohlcv["high"][stock_cols]
    low = ohlcv["low"][stock_cols]
    volume = ohlcv["volume"][stock_cols]
    prev_close = close.shift(1)

    day_range = (high - low).replace(0.0, np.nan)
    close_location = ((close - low) / day_range).clip(lower=0.0, upper=1.0)

    prior_vol20 = volume.shift(1).rolling(20, min_periods=12).mean()
    rvol20 = (volume / prior_vol20.replace(0.0, np.nan)).replace([np.inf, -np.inf], np.nan)
    day_ret = close / prev_close - 1.0
    signed_rvol20 = rvol20 * np.sign(day_ret)

    tr = true_range(high, low, close)
    atr14 = tr.rolling(14, min_periods=10).mean()
    ema21 = close.ewm(span=21, adjust=False, min_periods=15).mean()
    sma50 = close.rolling(50, min_periods=35).mean()
    ema21_atr = (close - ema21) / atr14.replace(0.0, np.nan)
    sma50_atr = (close - sma50) / atr14.replace(0.0, np.nan)

    prior_high20 = high.shift(1).rolling(20, min_periods=15).max()
    prior_high63 = high.shift(1).rolling(63, min_periods=45).max()
    dist_prior_high20 = close / prior_high20 - 1.0
    dist_prior_high63 = close / prior_high63 - 1.0

    tr_prior = tr.shift(1)
    tr5 = tr_prior.rolling(5, min_periods=4).mean()
    tr20 = tr_prior.rolling(20, min_periods=12).mean()
    compression_5v20 = tr5 / tr20.replace(0.0, np.nan)

    gap_pct = open_ / prev_close - 1.0
    stock252 = er.period_return(stock_ret, 252)

    return {
        "close_location": close_location,
        "rvol20": rvol20,
        "signed_rvol20": signed_rvol20,
        "ema21_atr": ema21_atr,
        "sma50_atr": sma50_atr,
        "dist_prior_high20": dist_prior_high20,
        "dist_prior_high63": dist_prior_high63,
        "compression_5v20": compression_5v20,
        "gap_pct": gap_pct,
        "stock252": stock252,
    }


def enrich_rows(rows: pd.DataFrame, matrices: dict[str, pd.DataFrame], theme_members: dict[str, list[str]]) -> pd.DataFrame:
    if rows.empty:
        return rows.copy()
    out = rows.copy()
    scalar_features = [f for f in FEATURES if f != "rs252_pct"]
    values: dict[str, list[float]] = {f: [] for f in scalar_features}
    rs252_values: list[float] = []
    rs_cache: dict[tuple[str, pd.Timestamp], pd.Series] = {}
    stock252 = matrices["stock252"]

    for row in out.itertuples(index=False):
        d = pd.Timestamp(row.entry_date)
        sym = str(row.symbol)
        theme = str(row.theme)
        for feature in scalar_features:
            matrix = matrices[feature]
            v = matrix.at[d, sym] if d in matrix.index and sym in matrix.columns else np.nan
            values[feature].append(float(v) if pd.notna(v) else np.nan)

        key = (theme, d)
        if key not in rs_cache:
            members = [s for s in theme_members.get(theme, []) if s in stock252.columns]
            if d in stock252.index and len(members) >= 3:
                rs_cache[key] = rs.rank_within(stock252.loc[d, members])
            else:
                rs_cache[key] = pd.Series(np.nan, index=members)
        rv = rs_cache[key].get(sym, np.nan)
        rs252_values.append(float(rv) if pd.notna(rv) else np.nan)

    for feature, vals in values.items():
        out[feature] = vals
    out["rs252_pct"] = rs252_values
    out["new_high20"] = out["dist_prior_high20"] >= 0.0
    out["new_high63"] = out["dist_prior_high63"] >= 0.0
    return out


def cluster_boot_ci(table: pd.DataFrame, value_col: str, cluster_col: str, seed: int, alpha: float = 0.05, reps: int = 3000) -> list[float | None]:
    use = table[[cluster_col, value_col]].dropna()
    if use.empty:
        return [None, None]
    grouped = use.groupby(cluster_col, observed=True)[value_col].mean().to_numpy(float)
    if len(grouped) < 2:
        return [None, None]
    rng = np.random.default_rng(seed)
    draws = rng.choice(grouped, size=(reps, len(grouped)), replace=True).mean(axis=1)
    lo, hi = np.quantile(draws, [alpha / 2, 1 - alpha / 2])
    return [float(lo), float(hi)]


def summarize(rows: pd.DataFrame, horizon: int, seed: int, alpha: float = 0.05) -> dict[str, Any]:
    peer = f"stock_minus_peers_{horizon}"
    spy = f"stock_minus_spy_{horizon}"
    mfe = f"mfe_{horizon}"
    mae = f"mae_{horizon}"
    cols = ["entry_id", "entry_date", "theme", "symbol", peer, spy, mfe, mae]
    use = rows[cols].dropna(subset=[peer]).copy()
    if use.empty:
        return {"rows": 0}
    ev = use.groupby(["entry_id", "entry_date", "theme"], observed=True).agg(
        peer=(peer, "mean"),
        spy=(spy, "mean"),
        mfe=(mfe, "mean"),
        mae=(mae, "mean"),
        stocks=("symbol", "nunique"),
    ).reset_index()
    disc = ev.loc[ev["entry_date"] <= DISCOVERY_END, "peer"]
    conf = ev.loc[ev["entry_date"] >= CONFIRM_START, "peer"]
    return {
        "rows": int(len(use)),
        "entries": int(len(ev)),
        "dates": int(ev["entry_date"].nunique()),
        "themes": int(ev["theme"].nunique()),
        "peer_mean": float(ev["peer"].mean()),
        "peer_median": float(ev["peer"].median()),
        "peer_positive_rate": float((ev["peer"] > 0).mean()),
        "peer_date_ci": cluster_boot_ci(ev, "peer", "entry_date", seed, alpha=alpha),
        "peer_theme_ci": cluster_boot_ci(ev, "peer", "theme", seed + 1000, alpha=alpha),
        "spy_mean": float(ev["spy"].mean()),
        "mfe_mean": float(ev["mfe"].mean()),
        "mae_mean": float(ev["mae"].mean()),
        "discovery_peer_mean": float(disc.mean()) if len(disc) else None,
        "confirmation_peer_mean": float(conf.mean()) if len(conf) else None,
        "discovery_n": int(len(disc)),
        "confirmation_n": int(len(conf)),
    }


def bucket_mask(values: pd.Series, lo: float | None, hi: float | None) -> pd.Series:
    x = pd.to_numeric(values, errors="coerce")
    mask = x.notna()
    if lo is not None:
        mask &= x >= lo
    if hi is not None:
        mask &= x < hi
    return mask


def candidate_mask(rows: pd.DataFrame, name: str) -> pd.Series:
    base = rows["continuous_momentum"].fillna(False)
    if name == "ALL_CONTINUOUS":
        return base
    if name == "STRONG_CLOSE_RVOL":
        return base & (rows["close_location"] >= 0.75) & (rows["rvol20"] >= 1.5)
    if name == "TIGHT_BREAKOUT20":
        return base & (rows["compression_5v20"] <= 0.75) & rows["new_high20"].fillna(False)
    if name == "FRESH_NOT_EXTENDED":
        return base & rows["new_high20"].fillna(False) & (rows["ema21_atr"] < 2.0)
    if name == "RS252_TOP":
        return base & (rows["rs252_pct"] >= 2.0 / 3.0)
    if name == "IND_LT80_ONLY":
        return base & (rows["industry_rs"] < 80)
    raise KeyError(name)


def paired_delta_vs_complement(rows: pd.DataFrame, selected: pd.Series, horizon: int, seed: int, cluster: str) -> dict[str, Any]:
    peer = f"stock_minus_peers_{horizon}"
    use = rows.loc[rows["continuous_momentum"].fillna(False), ["entry_date", "theme", peer]].copy()
    use["selected"] = selected.loc[use.index].fillna(False).to_numpy()
    use = use.dropna(subset=[peer])
    if use.empty:
        return {"pairs": 0, "delta": None, "ci95": [None, None]}

    if cluster == "entry_date":
        keys = ["entry_date"]
    elif cluster == "theme":
        keys = ["theme"]
    else:
        raise KeyError(cluster)

    agg = use.groupby(keys + ["selected"], observed=True)[peer].mean().unstack("selected")
    if True not in agg.columns or False not in agg.columns:
        return {"pairs": 0, "delta": None, "ci95": [None, None]}
    paired = (agg[True] - agg[False]).dropna()
    if len(paired) < 2:
        return {"pairs": int(len(paired)), "delta": float(paired.mean()) if len(paired) else None, "ci95": [None, None]}
    rng = np.random.default_rng(seed)
    arr = paired.to_numpy(float)
    draws = rng.choice(arr, size=(3000, len(arr)), replace=True).mean(axis=1)
    return {
        "pairs": int(len(arr)),
        "delta": float(arr.mean()),
        "ci95": [float(x) for x in np.quantile(draws, [0.025, 0.975])],
    }


def stock_level_feature_ic(rows: pd.DataFrame, feature: str, horizon: int) -> dict[str, Any]:
    peer = f"stock_minus_peers_{horizon}"
    use = rows.loc[rows["continuous_momentum"].fillna(False), ["entry_date", "theme", feature, peer]].dropna()
    if len(use) < 5 or use[feature].nunique() < 3:
        return {"n": int(len(use)), "spearman": None}
    disc = use[use["entry_date"] <= DISCOVERY_END]
    conf = use[use["entry_date"] >= CONFIRM_START]

    def corr(frame: pd.DataFrame) -> float | None:
        if len(frame) < 5 or frame[feature].nunique() < 3:
            return None
        return float(frame[feature].rank().corr(frame[peer].rank()))

    return {
        "n": int(len(use)),
        "spearman": corr(use),
        "discovery_spearman": corr(disc),
        "confirmation_spearman": corr(conf),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", default="leadership/research/ignition_quality_output")
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

    download_start = str((pd.Timestamp(args.analysis_start) - pd.Timedelta(days=620)).date())
    download_end = str((pd.Timestamp(args.analysis_end) + pd.Timedelta(days=120)).date())
    ohlcv, download_diag = download_ohlcv(requested, download_start, download_end, args.batch_size)
    close = ohlcv["close"]
    if "SPY" not in close.columns:
        raise RuntimeError("SPY benchmark missing")

    stock_cols = [s for s in selected if s in close.columns]
    stock_close = close[stock_cols]
    stock_high = ohlcv["high"][stock_cols]
    stock_low = ohlcv["low"][stock_cols]
    stock_ret = er.arithmetic_returns(stock_close)
    spy_ret = er.arithmetic_returns(close[["SPY"]])["SPY"]
    theme_members = {t: [s for s in members if s in stock_cols] for t, members in theme_members_all.items()}
    member_counts = {t: len(members) for t, members in theme_members.items()}
    theme_ret = er.grouped_equal_weight(stock_ret, theme_members, args.min_members)

    industry_groups: dict[str, list[str]] = {}
    sector_groups: dict[str, list[str]] = {}
    for sym in stock_cols:
        pair = industry_map.get(sym)
        if not pair:
            continue
        sector, industry = pair
        if sector:
            sector_groups.setdefault(sector, []).append(sym)
        if industry:
            industry_groups.setdefault(industry, []).append(sym)

    industry_ret = er.grouped_equal_weight(stock_ret, industry_groups, args.min_members)
    sector_ret = er.grouped_equal_weight(stock_ret, sector_groups, args.min_members)
    industry_weights = er.build_parent_weights(theme_members_all, industry_map)
    sector_weights = ss.build_sector_weights(theme_members_all, industry_map)
    common_themes = sorted(set(theme_ret.columns) & set(industry_weights) & set(sector_weights))
    theme_ret = theme_ret[common_themes]

    theme63 = er.period_return(theme_ret, 63)
    spy63 = er.period_return(spy_ret, 63)
    theme_pct = theme63.sub(spy63, axis=0).rank(axis=1, pct=True, method="average") * 100.0
    industry63 = er.period_return(industry_ret, 63)
    industry_pct = industry63.sub(spy63, axis=0).rank(axis=1, pct=True, method="average") * 100.0
    parent_industry_pct = er.weighted_matrix(industry_pct, industry_weights, common_themes)
    sector63 = er.period_return(sector_ret, 63)
    sector_pct = sector63.sub(spy63, axis=0).rank(axis=1, pct=True, method="average") * 100.0
    parent_sector_pct = er.weighted_matrix(sector_pct, sector_weights, common_themes)
    breadth = er.breadth_above_ema21(stock_close, theme_members, args.min_members).reindex(columns=common_themes)

    start, end = pd.Timestamp(args.analysis_start), pd.Timestamp(args.analysis_end)
    momentum_mask = cl.momentum_mask(theme_pct, parent_industry_pct, breadth)
    events = er.extract_events(momentum_mask, theme_pct, parent_industry_pct, breadth, member_counts, start, end)
    stock_period21 = er.period_return(stock_ret, 21)

    original_peer = ie.rs.event_peer_returns
    peer_cache: dict[tuple[tuple[str, ...], int, int], dict[str, float]] = {}

    def cached_peer(stock_ret_arg: pd.DataFrame, members: list[str], pos: int, horizon: int) -> dict[str, float]:
        key = (tuple(members), int(pos), int(horizon))
        if key not in peer_cache:
            peer_cache[key] = original_peer(stock_ret_arg, members, pos, horizon)
        return peer_cache[key]

    ie.rs.event_peer_returns = cached_peer

    rows = ie.build_entry_rows(
        events,
        momentum_mask,
        theme_members,
        stock_close,
        stock_high,
        stock_low,
        stock_ret,
        spy_ret,
        stock_period21,
        theme_pct,
        parent_industry_pct,
        parent_sector_pct,
        breadth,
    )

    matrices = compute_feature_matrices(ohlcv, stock_cols, stock_ret)
    rows = enrich_rows(rows, matrices, theme_members)
    primary = rows[rows["continuous_momentum"].fillna(False)].copy()

    result: dict[str, Any] = {
        "status": "PRELIMINARY_FIXED_CURRENT_TAXONOMY",
        "question": "Which ignition-date stock-quality features improve post-Subtheme-Momentum RS21 ignition outcomes using only information known at the ignition close?",
        "frozen_definitions": {
            "subtheme_momentum": cl.MOMENTUM_CONFIG,
            "entry": "first stock cross into within-theme RS21 top third during 1-20 trading days after Subtheme Momentum; entry at ignition close; Momentum must still be active",
            "primary_outcome": "stock forward total return minus equal-weight same-theme peer return",
            "horizons": list(HORIZONS),
            "features": {
                "close_location": "(Close-Low)/(High-Low) on ignition day",
                "rvol20": "ignition-day volume / prior 20-day mean volume",
                "signed_rvol20": "rvol20 times sign(ignition-day close-to-close return)",
                "ema21_atr": "(Close-EMA21)/simple ATR14",
                "sma50_atr": "(Close-SMA50)/simple ATR14",
                "dist_prior_high20": "Close/prior 20-day intraday high - 1",
                "dist_prior_high63": "Close/prior 63-day intraday high - 1",
                "compression_5v20": "prior 5-day mean true range / prior 20-day mean true range",
                "gap_pct": "Open/prior Close - 1",
                "rs252_pct": "within-theme percentile of 252-day return",
            },
            "feature_buckets": FEATURE_BUCKETS,
            "candidate_filters": {
                "STRONG_CLOSE_RVOL": "close_location>=0.75 and rvol20>=1.5",
                "TIGHT_BREAKOUT20": "compression_5v20<=0.75 and Close>=prior 20-day high",
                "FRESH_NOT_EXTENDED": "Close>=prior 20-day high and ema21_atr<2",
                "RS252_TOP": "within-theme RS252 top third",
                "IND_LT80_ONLY": "Industry RS<80; carried forward as maturity guard from prior stage",
            },
            "discovery_confirmation_split": ["2016-2021", "2022-2026H1"],
            "no_future_information_in_filters": True,
        },
        "coverage": {
            "selected_stocks": len(stock_cols),
            "momentum_events": int(len(events)),
            "entry_rows": int(len(rows)),
            "continuous_entry_rows": int(len(primary)),
            "entry_dates": int(primary["entry_date"].nunique()) if len(primary) else 0,
            "themes": int(primary["theme"].nunique()) if len(primary) else 0,
        },
        "download": download_diag,
        "taxonomy_candidates": taxonomy_candidates,
        "feature_ic": {},
        "feature_buckets": {},
        "candidate_filters": {},
        "new_high_binary": {},
    }

    for h in HORIZONS:
        result["feature_ic"][str(h)] = {
            feature: stock_level_feature_ic(primary, feature, h)
            for feature in FEATURES
        }

        bucket_results: dict[str, Any] = {}
        for fi, (feature, buckets) in enumerate(FEATURE_BUCKETS.items()):
            fres: dict[str, Any] = {}
            for bi, (label, lo, hi) in enumerate(buckets):
                part = primary[bucket_mask(primary[feature], lo, hi)]
                fres[label] = summarize(part, h, 10000 + h * 1000 + fi * 10 + bi)
            bucket_results[feature] = fres
        result["feature_buckets"][str(h)] = bucket_results

        binary_results: dict[str, Any] = {}
        for bi, feature in enumerate(("new_high20", "new_high63")):
            binary_results[feature] = {
                "FALSE": summarize(primary[~primary[feature].fillna(False)], h, 20000 + h * 100 + bi * 2),
                "TRUE": summarize(primary[primary[feature].fillna(False)], h, 20001 + h * 100 + bi * 2),
            }
        result["new_high_binary"][str(h)] = binary_results

        candidate_results: dict[str, Any] = {}
        alpha_bonf = 0.05 / max(1, len(CANDIDATE_FILTERS) - 1)
        for ci, name in enumerate(CANDIDATE_FILTERS):
            mask = candidate_mask(primary, name)
            part = primary[mask]
            cres = summarize(part, h, 30000 + h * 100 + ci, alpha=alpha_bonf if name != "ALL_CONTINUOUS" else 0.05)
            if name != "ALL_CONTINUOUS":
                cres["delta_vs_complement_by_date"] = paired_delta_vs_complement(
                    primary, mask, h, 40000 + h * 100 + ci, "entry_date"
                )
                cres["delta_vs_complement_by_theme"] = paired_delta_vs_complement(
                    primary, mask, h, 50000 + h * 100 + ci, "theme"
                )
            candidate_results[name] = cres
        result["candidate_filters"][str(h)] = candidate_results

    safe_result = safe(result)
    rows.to_csv(output / "ignition_quality_rows.csv.gz", index=False, compression="gzip")
    (output / "summary.json").write_text(json.dumps(safe_result, ensure_ascii=False, indent=2), encoding="utf-8")

    compact = {
        "status": safe_result["status"],
        "coverage": safe_result["coverage"],
        "feature_ic": safe_result["feature_ic"],
        "feature_buckets": safe_result["feature_buckets"],
        "candidate_filters": safe_result["candidate_filters"],
        "new_high_binary": safe_result["new_high_binary"],
    }
    print("=== IGNITION_QUALITY_RESULT_JSON ===", flush=True)
    print(json.dumps(compact, ensure_ascii=False, indent=2), flush=True)
    print("=== END_IGNITION_QUALITY_RESULT_JSON ===", flush=True)


if __name__ == "__main__":
    main()
