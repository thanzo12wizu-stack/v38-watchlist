from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import validate_early_rotation as er
import validate_confirmed_leadership as cl
import validate_pioneer_leader as pl
import validate_rs_periods as rs
import validate_sector_stock_stack as ss
import validate_lead_lag_sequence as ll

HORIZONS = (5, 10, 20)
DISCOVERY_END = pd.Timestamp("2021-12-31")
CONFIRM_START = pd.Timestamp("2022-01-01")
IGNITION_CUT = 2.0 / 3.0
ENTRY_WINDOW = 20
INDUSTRY_ACCEL_LOOKBACK = 20
INDUSTRY_ACCEL_CUT = 10.0
INDUSTRY_CONFIRM_CUT = 80.0

FILTERS = (
    "ALL_CONTINUOUS",
    "AGE_1_5",
    "AGE_6_10",
    "AGE_11_20",
    "IND_LT60",
    "IND_60_80",
    "IND_GE80",
    "IND_LT80_ACCEL_POS",
    "IND_LT80_ACCEL10",
    "IND_60_80_ACCEL_POS",
    "IND_60_80_ACCEL10",
    "IND_60_80_ACCEL10_BREADTH60",
    "SECTOR_GE80",
    "SECTOR_LT80",
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


def compound_daily(ret: pd.Series, horizon: int) -> float:
    x = pd.to_numeric(ret, errors="coerce").dropna()
    x = x[x > -0.999999]
    if len(x) < max(1, int(math.ceil(horizon * 0.8))):
        return np.nan
    return float(np.expm1(np.log1p(x).sum()))


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


def filter_mask(rows: pd.DataFrame, name: str) -> pd.Series:
    if name == "ALL_CONTINUOUS":
        return rows["continuous_momentum"]
    if name == "AGE_1_5":
        return rows["continuous_momentum"] & rows["theme_age"].between(1, 5)
    if name == "AGE_6_10":
        return rows["continuous_momentum"] & rows["theme_age"].between(6, 10)
    if name == "AGE_11_20":
        return rows["continuous_momentum"] & rows["theme_age"].between(11, 20)
    if name == "IND_LT60":
        return rows["continuous_momentum"] & (rows["industry_rs"] < 60)
    if name == "IND_60_80":
        return rows["continuous_momentum"] & rows["industry_rs"].between(60, 80, inclusive="left")
    if name == "IND_GE80":
        return rows["continuous_momentum"] & (rows["industry_rs"] >= 80)
    if name == "IND_LT80_ACCEL_POS":
        return rows["continuous_momentum"] & (rows["industry_rs"] < 80) & (rows["industry_delta20"] > 0)
    if name == "IND_LT80_ACCEL10":
        return rows["continuous_momentum"] & (rows["industry_rs"] < 80) & (rows["industry_delta20"] >= INDUSTRY_ACCEL_CUT)
    if name == "IND_60_80_ACCEL_POS":
        return rows["continuous_momentum"] & rows["industry_rs"].between(60, 80, inclusive="left") & (rows["industry_delta20"] > 0)
    if name == "IND_60_80_ACCEL10":
        return rows["continuous_momentum"] & rows["industry_rs"].between(60, 80, inclusive="left") & (rows["industry_delta20"] >= INDUSTRY_ACCEL_CUT)
    if name == "IND_60_80_ACCEL10_BREADTH60":
        return rows["continuous_momentum"] & rows["industry_rs"].between(60, 80, inclusive="left") & (rows["industry_delta20"] >= INDUSTRY_ACCEL_CUT) & (rows["breadth"] >= 0.60)
    if name == "SECTOR_GE80":
        return rows["continuous_momentum"] & (rows["sector_rs"] >= 80)
    if name == "SECTOR_LT80":
        return rows["continuous_momentum"] & (rows["sector_rs"] < 80)
    raise KeyError(name)


def summarize_entries(rows: pd.DataFrame, horizon: int, seed: int) -> dict[str, Any]:
    peer = f"stock_minus_peers_{horizon}"
    spy = f"stock_minus_spy_{horizon}"
    mfe = f"mfe_{horizon}"
    mae = f"mae_{horizon}"
    use = rows[["entry_id", "entry_date", "theme", "symbol", peer, spy, mfe, mae]].dropna(subset=[peer]).copy()
    if use.empty:
        return {"rows": 0}
    ev = use.groupby(["entry_id", "entry_date", "theme"], observed=True).agg(
        peer=(peer, "mean"), spy=(spy, "mean"), mfe=(mfe, "mean"), mae=(mae, "mean"), stocks=("symbol", "nunique")
    ).reset_index()
    disc = ev.loc[ev["entry_date"] <= DISCOVERY_END, "peer"]
    conf = ev.loc[ev["entry_date"] >= CONFIRM_START, "peer"]
    alpha_bonf = 0.05 / len(FILTERS)
    return {
        "rows": int(len(use)),
        "entries": int(len(ev)),
        "dates": int(ev["entry_date"].nunique()),
        "themes": int(ev["theme"].nunique()),
        "mean_stocks_per_entry": float(ev["stocks"].mean()),
        "peer_mean": float(ev["peer"].mean()),
        "peer_median": float(ev["peer"].median()),
        "peer_positive_rate": float((ev["peer"] > 0).mean()),
        "peer_date_ci95": cluster_boot_ci(ev, "peer", "entry_date", seed),
        "peer_theme_ci95": cluster_boot_ci(ev, "peer", "theme", seed + 1000),
        "peer_date_bonferroni_ci": cluster_boot_ci(ev, "peer", "entry_date", seed + 2000, alpha=alpha_bonf),
        "peer_theme_bonferroni_ci": cluster_boot_ci(ev, "peer", "theme", seed + 3000, alpha=alpha_bonf),
        "spy_mean": float(ev["spy"].mean()),
        "mfe_mean": float(ev["mfe"].mean()),
        "mae_mean": float(ev["mae"].mean()),
        "discovery_peer_mean": float(disc.mean()) if len(disc) else None,
        "confirmation_peer_mean": float(conf.mean()) if len(conf) else None,
        "discovery_n": int(len(disc)),
        "confirmation_n": int(len(conf)),
    }


def event_level_feature_ic(rows: pd.DataFrame, feature: str, horizon: int, seed: int) -> dict[str, Any]:
    peer = f"stock_minus_peers_{horizon}"
    use = rows.loc[rows["continuous_momentum"], ["entry_id", "entry_date", "theme", feature, peer]].dropna().copy()
    if use.empty:
        return {"n": 0}
    ev = use.groupby(["entry_id", "entry_date", "theme"], observed=True).agg(feature=(feature, "first"), peer=(peer, "mean")).reset_index()
    if len(ev) < 5 or ev["feature"].nunique() < 3:
        return {"n": int(len(ev)), "spearman": None}
    corr = float(ev["feature"].rank().corr(ev["peer"].rank()))
    return {
        "n": int(len(ev)),
        "spearman": corr,
        "discovery_spearman": float(ev.loc[ev["entry_date"] <= DISCOVERY_END, "feature"].rank().corr(ev.loc[ev["entry_date"] <= DISCOVERY_END, "peer"].rank())) if (ev["entry_date"] <= DISCOVERY_END).sum() >= 5 else None,
        "confirmation_spearman": float(ev.loc[ev["entry_date"] >= CONFIRM_START, "feature"].rank().corr(ev.loc[ev["entry_date"] >= CONFIRM_START, "peer"].rank())) if (ev["entry_date"] >= CONFIRM_START).sum() >= 5 else None,
    }


def future_industry_confirm(series: pd.Series, pos: int, horizon: int = 20) -> bool:
    hi = min(len(series), pos + horizon + 1)
    if pos + 1 >= hi:
        return False
    future = pd.to_numeric(series.iloc[pos + 1:hi], errors="coerce")
    return bool((future >= INDUSTRY_CONFIRM_CUT).any())


def build_entry_rows(
    events: pd.DataFrame,
    momentum_mask: pd.DataFrame,
    theme_members: dict[str, list[str]],
    stock_close: pd.DataFrame,
    stock_high: pd.DataFrame,
    stock_low: pd.DataFrame,
    stock_ret: pd.DataFrame,
    spy_ret: pd.Series,
    stock_period21: pd.DataFrame,
    theme_pct: pd.DataFrame,
    parent_industry_pct: pd.DataFrame,
    parent_sector_pct: pd.DataFrame,
    breadth: pd.DataFrame,
) -> pd.DataFrame:
    date_pos = {pd.Timestamp(d): i for i, d in enumerate(stock_close.index)}
    stock_fwd = {h: er.forward_return(stock_ret, h) for h in HORIZONS}
    spy_fwd = {h: er.forward_return(spy_ret, h) for h in HORIZONS}
    rank_cache: dict[tuple[str, pd.Timestamp], pd.Series] = {}

    def ranks(theme: str, date: pd.Timestamp) -> pd.Series:
        key = (theme, date)
        if key in rank_cache:
            return rank_cache[key]
        members = [s for s in theme_members.get(theme, []) if s in stock_period21.columns]
        if date not in stock_period21.index or len(members) < 3:
            out = pd.Series(np.nan, index=members)
        else:
            out = rs.rank_within(stock_period21.loc[date, members])
        rank_cache[key] = out
        return out

    records: list[dict[str, Any]] = []
    for ei, event in enumerate(events.itertuples(index=False)):
        event_date = pd.Timestamp(event.date)
        theme = str(event.theme)
        event_pos = date_pos.get(event_date, -1)
        members = [s for s in theme_members.get(theme, []) if s in stock_close.columns]
        if event_pos < 1 or len(members) < 3 or theme not in momentum_mask.columns:
            continue
        max_pos = min(len(stock_close.index) - 1, event_pos + ENTRY_WINDOW)
        first_cross: dict[str, int] = {}
        for p in range(event_pos + 1, max_pos + 1):
            d = stock_close.index[p]
            prev_d = stock_close.index[p - 1]
            cur = ranks(theme, d)
            prev = ranks(theme, prev_d)
            for sym in members:
                if sym in first_cross:
                    continue
                cv = cur.get(sym, np.nan)
                pv = prev.get(sym, np.nan)
                if pd.notna(cv) and pd.notna(pv) and float(cv) >= IGNITION_CUT and float(pv) < IGNITION_CUT:
                    first_cross[sym] = p

        for sym, p in first_cross.items():
            entry_date = stock_close.index[p]
            if entry_date not in momentum_mask.index:
                continue
            active_slice = momentum_mask.loc[event_date:entry_date, theme]
            continuous = bool(len(active_slice) and active_slice.fillna(False).all())
            if not bool(momentum_mask.at[entry_date, theme]):
                continue
            entry_price = stock_close.at[entry_date, sym]
            if pd.isna(entry_price) or entry_price <= 0:
                continue

            ind_series = parent_industry_pct[theme] if theme in parent_industry_pct.columns else pd.Series(dtype=float)
            sec_series = parent_sector_pct[theme] if theme in parent_sector_pct.columns else pd.Series(dtype=float)
            if entry_date not in ind_series.index:
                continue
            ipos = ind_series.index.get_indexer([entry_date])[0]
            ind_now = ind_series.iloc[ipos]
            ind_prev = ind_series.iloc[ipos - INDUSTRY_ACCEL_LOOKBACK] if ipos >= INDUSTRY_ACCEL_LOOKBACK else np.nan
            ind_delta = float(ind_now - ind_prev) if pd.notna(ind_now) and pd.notna(ind_prev) else np.nan
            sec_now = sec_series.loc[entry_date] if len(sec_series) and entry_date in sec_series.index else np.nan
            th_now = theme_pct.at[entry_date, theme] if entry_date in theme_pct.index and theme in theme_pct.columns else np.nan
            th_prev_pos = theme_pct.index.get_indexer([entry_date])[0] if entry_date in theme_pct.index else -1
            th_prev = theme_pct.iloc[th_prev_pos - 20][theme] if th_prev_pos >= 20 and theme in theme_pct.columns else np.nan
            th_delta = float(th_now - th_prev) if pd.notna(th_now) and pd.notna(th_prev) else np.nan
            br = breadth.at[entry_date, theme] if entry_date in breadth.index and theme in breadth.columns else np.nan
            future_confirm = future_industry_confirm(ind_series, ipos, 20) if pd.notna(ind_now) and float(ind_now) < 80 else False

            base = {
                "entry_id": f"{entry_date.date()}|{theme}",
                "event_id": f"{event_date.date()}|{theme}",
                "event_date": event_date,
                "entry_date": entry_date,
                "theme": theme,
                "symbol": sym,
                "theme_age": int(p - event_pos),
                "continuous_momentum": continuous,
                "industry_rs": float(ind_now) if pd.notna(ind_now) else np.nan,
                "industry_delta20": ind_delta,
                "sector_rs": float(sec_now) if pd.notna(sec_now) else np.nan,
                "theme_rs": float(th_now) if pd.notna(th_now) else np.nan,
                "theme_delta20": th_delta,
                "breadth": float(br) if pd.notna(br) else np.nan,
                "future_industry_confirm20": future_confirm,
            }

            peer_by_h = {h: rs.event_peer_returns(stock_ret, members, p, h).get(sym, np.nan) for h in HORIZONS}
            for h in HORIZONS:
                sr = stock_fwd[h].at[entry_date, sym] if entry_date in stock_fwd[h].index else np.nan
                sp = spy_fwd[h].at[entry_date] if entry_date in spy_fwd[h].index else np.nan
                pr = peer_by_h[h]
                future_dates = stock_close.index[p + 1:min(p + h + 1, len(stock_close))]
                highs = stock_high.loc[future_dates, sym].dropna()
                lows = stock_low.loc[future_dates, sym].dropna()
                base[f"stock_ret_{h}"] = sr
                base[f"stock_minus_peers_{h}"] = sr - pr if pd.notna(sr) and pd.notna(pr) else np.nan
                base[f"stock_minus_spy_{h}"] = sr - sp if pd.notna(sr) and pd.notna(sp) else np.nan
                base[f"mfe_{h}"] = float(highs.max() / entry_price - 1.0) if len(highs) else np.nan
                base[f"mae_{h}"] = float(lows.min() / entry_price - 1.0) if len(lows) else np.nan
            records.append(base)
        if (ei + 1) % 500 == 0:
            print(f"IGNITION_ENTRIES {ei + 1}/{len(events)} rows={len(records)} cache={len(rank_cache)}", flush=True)
    return pd.DataFrame(records)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", default="leadership/research/ignition_entry_output")
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
    download_start = str((pd.Timestamp(args.analysis_start) - pd.Timedelta(days=520)).date())
    download_end = str((pd.Timestamp(args.analysis_end) + pd.Timedelta(days=120)).date())
    ohlcv, download_diag = pl.download_ohlcv(requested, download_start, download_end, args.batch_size)
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
    rows = build_entry_rows(
        events, momentum_mask, theme_members, stock_close, stock_high, stock_low, stock_ret, spy_ret,
        stock_period21, theme_pct, parent_industry_pct, parent_sector_pct, breadth,
    )

    result: dict[str, Any] = {
        "status": "PRELIMINARY_FIXED_CURRENT_TAXONOMY",
        "question": "Can post-Subtheme-Momentum stock RS21 ignition become an actionable pioneer entry using only information known on the ignition date?",
        "frozen_definitions": {
            "subtheme_momentum": cl.MOMENTUM_CONFIG,
            "entry": "first stock cross into within-theme RS21 top third during 1-20 trading days after a Subtheme Momentum event; ignition date itself must still satisfy Momentum",
            "primary_requires_continuous_momentum": True,
            "industry_rs": "63d equal-weight TradingView Industry return vs SPY, cross-Industry percentile, constituent-weighted to theme",
            "industry_buckets": ["<60", "60-80", ">=80"],
            "industry_delta20_buckets": ["<=0", "0-10", ">=10 rank points"],
            "filters": list(FILTERS),
            "horizons": list(HORIZONS),
            "no_future_industry_information_in_actionable_filters": True,
        },
        "coverage": {
            "selected_stocks": len(stock_cols),
            "momentum_events": int(len(events)),
            "entry_rows": int(len(rows)),
            "continuous_entry_rows": int(rows["continuous_momentum"].sum()) if len(rows) else 0,
            "entry_dates": int(rows["entry_date"].nunique()) if len(rows) else 0,
            "themes": int(rows["theme"].nunique()) if len(rows) else 0,
        },
        "download": download_diag,
        "taxonomy_candidates": taxonomy_candidates,
        "filters": {},
        "feature_ic": {},
        "future_industry_confirmation_diagnostic": {},
    }

    for h in HORIZONS:
        hres: dict[str, Any] = {}
        for i, name in enumerate(FILTERS):
            part = rows[filter_mask(rows, name).fillna(False)].copy()
            hres[name] = summarize_entries(part, h, 10000 + h * 100 + i)
        result["filters"][str(h)] = hres
        result["feature_ic"][str(h)] = {
            feature: event_level_feature_ic(rows, feature, h, 20000 + h * 100 + j)
            for j, feature in enumerate(("theme_age", "industry_rs", "industry_delta20", "sector_rs", "breadth", "theme_rs", "theme_delta20"))
        }

    diag_base = rows[rows["continuous_momentum"] & (rows["industry_rs"] < 80)].copy()
    for name in ("ALL_LT80", "ACCEL_POS", "ACCEL10", "IND_60_80_ACCEL10"):
        if name == "ALL_LT80":
            part = diag_base
        elif name == "ACCEL_POS":
            part = diag_base[diag_base["industry_delta20"] > 0]
        elif name == "ACCEL10":
            part = diag_base[diag_base["industry_delta20"] >= 10]
        else:
            part = diag_base[diag_base["industry_rs"].between(60, 80, inclusive="left") & (diag_base["industry_delta20"] >= 10)]
        result["future_industry_confirmation_diagnostic"][name] = {
            "rows": int(len(part)),
            "entries": int(part["entry_id"].nunique()) if len(part) else 0,
            "future_confirm20_rate": float(part["future_industry_confirm20"].mean()) if len(part) else None,
        }

    safe_result = safe(result)
    rows.to_csv(output / "ignition_entry_rows.csv.gz", index=False, compression="gzip")
    (output / "summary.json").write_text(json.dumps(safe_result, ensure_ascii=False, indent=2), encoding="utf-8")
    compact = {
        "status": safe_result["status"],
        "coverage": safe_result["coverage"],
        "filters": safe_result["filters"],
        "feature_ic": safe_result["feature_ic"],
        "future_industry_confirmation_diagnostic": safe_result["future_industry_confirmation_diagnostic"],
    }
    print("=== IGNITION_ENTRY_RESULT_JSON ===", flush=True)
    print(json.dumps(compact, ensure_ascii=False, indent=2), flush=True)
    print("=== END_IGNITION_ENTRY_RESULT_JSON ===", flush=True)


if __name__ == "__main__":
    main()
