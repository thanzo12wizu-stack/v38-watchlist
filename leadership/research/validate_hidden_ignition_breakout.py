from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import validate_early_rotation as er
import validate_ignition_quality as iq
import validate_rs_periods as rs

HORIZONS = (5, 10, 20)
BREAKOUT_WINDOW = 10
HIDDEN_HIGH_GAP = -0.05
INDUSTRY_MAX = 80.0


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


def paired_summary(rows: pd.DataFrame, horizon: int, seed: int) -> dict[str, Any]:
    if rows.empty:
        return {"rows": 0}
    bpeer = f"stock_minus_peers_{horizon}"
    bspy = f"stock_minus_spy_{horizon}"
    bmfe = f"mfe_{horizon}"
    bmae = f"mae_{horizon}"
    ipeer = f"ignition_peer_{horizon}"
    ispy = f"ignition_spy_{horizon}"
    imfe = f"ignition_mfe_{horizon}"
    imae = f"ignition_mae_{horizon}"
    use = rows[["ignition_date", "theme", "symbol", bpeer, bspy, bmfe, bmae, ipeer, ispy, imfe, imae]].dropna(subset=[bpeer, ipeer]).copy()
    if use.empty:
        return {"rows": 0}
    use["peer_delta_wait_minus_ignite"] = use[bpeer] - use[ipeer]
    use["spy_delta_wait_minus_ignite"] = use[bspy] - use[ispy]
    use["mfe_delta_wait_minus_ignite"] = use[bmfe] - use[imfe]
    use["mae_delta_wait_minus_ignite"] = use[bmae] - use[imae]
    return {
        "rows": int(len(use)),
        "dates": int(use["ignition_date"].nunique()),
        "themes": int(use["theme"].nunique()),
        "ignition_peer_mean": float(use[ipeer].mean()),
        "breakout_peer_mean": float(use[bpeer].mean()),
        "peer_delta_wait_minus_ignite": float(use["peer_delta_wait_minus_ignite"].mean()),
        "peer_delta_date_ci95": iq.cluster_boot_ci(use, "peer_delta_wait_minus_ignite", "ignition_date", seed),
        "peer_delta_theme_ci95": iq.cluster_boot_ci(use, "peer_delta_wait_minus_ignite", "theme", seed + 1000),
        "ignition_spy_mean": float(use[ispy].mean()),
        "breakout_spy_mean": float(use[bspy].mean()),
        "spy_delta_wait_minus_ignite": float(use["spy_delta_wait_minus_ignite"].mean()),
        "ignition_mfe_mean": float(use[imfe].mean()),
        "breakout_mfe_mean": float(use[bmfe].mean()),
        "mfe_delta_wait_minus_ignite": float(use["mfe_delta_wait_minus_ignite"].mean()),
        "ignition_mae_mean": float(use[imae].mean()),
        "breakout_mae_mean": float(use[bmae].mean()),
        "mae_delta_wait_minus_ignite": float(use["mae_delta_wait_minus_ignite"].mean()),
    }


def build_breakout_rows(
    hidden: pd.DataFrame,
    theme_members: dict[str, list[str]],
    close: pd.DataFrame,
    high: pd.DataFrame,
    low: pd.DataFrame,
    stock_ret: pd.DataFrame,
    spy_ret: pd.Series,
) -> tuple[pd.DataFrame, set[str]]:
    prior_high20 = high.shift(1).rolling(20, min_periods=15).max()
    date_pos = {pd.Timestamp(d): i for i, d in enumerate(close.index)}
    stock_fwd = {h: er.forward_return(stock_ret, h) for h in HORIZONS}
    spy_fwd = {h: er.forward_return(spy_ret, h) for h in HORIZONS}
    peer_cache: dict[tuple[tuple[str, ...], int, int], dict[str, float]] = {}

    def peer_returns(members: list[str], pos: int, horizon: int) -> dict[str, float]:
        key = (tuple(members), int(pos), int(horizon))
        if key not in peer_cache:
            peer_cache[key] = rs.event_peer_returns(stock_ret, members, pos, horizon)
        return peer_cache[key]

    records: list[dict[str, Any]] = []
    breakout_keys: set[str] = set()
    for i, row in enumerate(hidden.itertuples(index=False)):
        ignition_date = pd.Timestamp(row.entry_date)
        theme = str(row.theme)
        sym = str(row.symbol)
        key = f"{ignition_date.date()}|{theme}|{sym}"
        p0 = date_pos.get(ignition_date, -1)
        if p0 < 0 or sym not in close.columns:
            continue
        members = [s for s in theme_members.get(theme, []) if s in close.columns]
        if len(members) < 3:
            continue
        bpos = None
        for p in range(p0 + 1, min(p0 + BREAKOUT_WINDOW + 1, len(close))):
            d = close.index[p]
            c = close.at[d, sym]
            ph = prior_high20.at[d, sym]
            if pd.notna(c) and pd.notna(ph) and float(c) > float(ph):
                bpos = p
                break
        if bpos is None:
            continue
        breakout_date = close.index[bpos]
        entry_price = close.at[breakout_date, sym]
        if pd.isna(entry_price) or entry_price <= 0:
            continue
        breakout_keys.add(key)
        rec: dict[str, Any] = {
            "entry_id": f"{breakout_date.date()}|{theme}",
            "entry_date": breakout_date,
            "ignition_date": ignition_date,
            "ignition_entry_id": str(row.entry_id),
            "theme": theme,
            "symbol": sym,
            "breakout_delay": int(bpos - p0),
            "industry_rs_at_ignition": float(row.industry_rs),
            "dist_prior_high20_at_ignition": float(row.dist_prior_high20),
        }
        for h in HORIZONS:
            sr = stock_fwd[h].at[breakout_date, sym] if breakout_date in stock_fwd[h].index else np.nan
            sp = spy_fwd[h].at[breakout_date] if breakout_date in spy_fwd[h].index else np.nan
            pr = peer_returns(members, bpos, h).get(sym, np.nan)
            future_dates = close.index[bpos + 1:min(bpos + h + 1, len(close))]
            highs = high.loc[future_dates, sym].dropna()
            lows = low.loc[future_dates, sym].dropna()
            rec[f"stock_ret_{h}"] = sr
            rec[f"stock_minus_peers_{h}"] = sr - pr if pd.notna(sr) and pd.notna(pr) else np.nan
            rec[f"stock_minus_spy_{h}"] = sr - sp if pd.notna(sr) and pd.notna(sp) else np.nan
            rec[f"mfe_{h}"] = float(highs.max() / entry_price - 1.0) if len(highs) else np.nan
            rec[f"mae_{h}"] = float(lows.min() / entry_price - 1.0) if len(lows) else np.nan
            rec[f"ignition_peer_{h}"] = getattr(row, f"stock_minus_peers_{h}")
            rec[f"ignition_spy_{h}"] = getattr(row, f"stock_minus_spy_{h}")
            rec[f"ignition_mfe_{h}"] = getattr(row, f"mfe_{h}")
            rec[f"ignition_mae_{h}"] = getattr(row, f"mae_{h}")
        records.append(rec)
        if (i + 1) % 200 == 0:
            print(f"BREAKOUT_SCAN {i + 1}/{len(hidden)} found={len(records)}", flush=True)
    return pd.DataFrame(records), breakout_keys


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--quality-rows", default="leadership/research/ignition_quality_tmp/ignition_quality_rows.csv.gz")
    parser.add_argument("--output", default="leadership/research/hidden_ignition_breakout_output")
    parser.add_argument("--analysis-start", default="2016-01-04")
    parser.add_argument("--analysis-end", default="2026-06-20")
    parser.add_argument("--max-tickers", type=int, default=1500)
    parser.add_argument("--batch-size", type=int, default=75)
    args = parser.parse_args()

    root = Path(args.root)
    output = root / args.output
    output.mkdir(parents=True, exist_ok=True)
    quality_path = root / args.quality_rows
    quality = pd.read_csv(quality_path, compression="gzip", parse_dates=["entry_date", "event_date"])
    hidden_mask = (
        quality["continuous_momentum"].fillna(False)
        & (pd.to_numeric(quality["dist_prior_high20"], errors="coerce") <= HIDDEN_HIGH_GAP)
        & (pd.to_numeric(quality["industry_rs"], errors="coerce") < INDUSTRY_MAX)
    )
    hidden = quality[hidden_mask].copy()
    hidden["row_key"] = hidden.apply(lambda r: f"{pd.Timestamp(r.entry_date).date()}|{r.theme}|{r.symbol}", axis=1)

    snapshot = er.load_json(root / "sector_snapshot.json")
    theme_members_all, taxonomy_candidates = er.extract_theme_members(snapshot)
    industry_map = er.read_industry_map(root / "industry_map.json")
    universe = er.read_universe_symbols(root / "universe.csv")
    selected = er.stratified_symbols(theme_members_all, set(industry_map) & universe, args.max_tickers)
    requested = selected + (["SPY"] if "SPY" not in selected else [])
    download_start = str((pd.Timestamp(args.analysis_start) - pd.Timedelta(days=120)).date())
    download_end = str((pd.Timestamp(args.analysis_end) + pd.Timedelta(days=120)).date())
    ohlcv, download_diag = iq.download_ohlcv(requested, download_start, download_end, args.batch_size)
    close = ohlcv["close"]
    if "SPY" not in close.columns:
        raise RuntimeError("SPY missing")
    stock_cols = [s for s in selected if s in close.columns]
    stock_close = close[stock_cols]
    stock_high = ohlcv["high"][stock_cols]
    stock_low = ohlcv["low"][stock_cols]
    stock_ret = er.arithmetic_returns(stock_close)
    spy_ret = er.arithmetic_returns(close[["SPY"]])["SPY"]
    theme_members = {t: [s for s in members if s in stock_cols] for t, members in theme_members_all.items()}

    breakout, breakout_keys = build_breakout_rows(hidden, theme_members, stock_close, stock_high, stock_low, stock_ret, spy_ret)
    broke_ignition = hidden[hidden["row_key"].isin(breakout_keys)].copy()
    no_breakout = hidden[~hidden["row_key"].isin(breakout_keys)].copy()

    result: dict[str, Any] = {
        "status": "PRELIMINARY_FIXED_CURRENT_TAXONOMY",
        "question": "For hidden RS21 ignition, does waiting up to 10 trading days for a first close above the prior 20-day intraday high improve actionable forward outcomes?",
        "frozen_definitions": {
            "hidden_ignition": "continuous Subtheme Momentum + new RS21 top-third ignition + ignition close at least 5% below prior 20-day intraday high + Industry RS<80",
            "breakout": "first subsequent close strictly above prior 20-day intraday high, within 10 trading days after ignition",
            "ignition_entry": "ignition close",
            "breakout_entry": "breakout close",
            "horizons": list(HORIZONS),
            "primary_outcome": "stock total return minus equal-weight same-theme peer return",
            "future_conditioning_note": "later-breakout vs no-breakout ignition-day groups are diagnostic only; breakout-close entry is actionable only when breakout occurs",
        },
        "coverage": {
            "hidden_rows": int(len(hidden)),
            "hidden_dates": int(hidden["entry_date"].nunique()),
            "hidden_themes": int(hidden["theme"].nunique()),
            "breakout_rows": int(len(breakout)),
            "breakout_rate_rows": float(len(breakout) / len(hidden)) if len(hidden) else None,
            "no_breakout_rows": int(len(no_breakout)),
            "median_breakout_delay": float(breakout["breakout_delay"].median()) if len(breakout) else None,
        },
        "download": download_diag,
        "taxonomy_candidates": taxonomy_candidates,
        "ignition_all": {},
        "ignition_later_breakout_diagnostic": {},
        "ignition_no_breakout_diagnostic": {},
        "breakout_entry": {},
        "paired_wait_vs_ignition": {},
    }
    for h in HORIZONS:
        result["ignition_all"][str(h)] = iq.summarize(hidden, h, 11000 + h)
        result["ignition_later_breakout_diagnostic"][str(h)] = iq.summarize(broke_ignition, h, 12000 + h)
        result["ignition_no_breakout_diagnostic"][str(h)] = iq.summarize(no_breakout, h, 13000 + h)
        result["breakout_entry"][str(h)] = iq.summarize(breakout, h, 14000 + h) if len(breakout) else {"rows": 0}
        result["paired_wait_vs_ignition"][str(h)] = paired_summary(breakout, h, 15000 + h)

    safe_result = safe(result)
    hidden.to_csv(output / "hidden_ignition_rows.csv.gz", index=False, compression="gzip")
    breakout.to_csv(output / "breakout_entry_rows.csv.gz", index=False, compression="gzip")
    (output / "summary.json").write_text(json.dumps(safe_result, ensure_ascii=False, indent=2), encoding="utf-8")
    compact = {
        "status": safe_result["status"],
        "coverage": safe_result["coverage"],
        "ignition_all": safe_result["ignition_all"],
        "ignition_later_breakout_diagnostic": safe_result["ignition_later_breakout_diagnostic"],
        "ignition_no_breakout_diagnostic": safe_result["ignition_no_breakout_diagnostic"],
        "breakout_entry": safe_result["breakout_entry"],
        "paired_wait_vs_ignition": safe_result["paired_wait_vs_ignition"],
    }
    print("=== HIDDEN_IGNITION_BREAKOUT_RESULT_JSON ===", flush=True)
    print(json.dumps(compact, ensure_ascii=False, indent=2), flush=True)
    print("=== END_HIDDEN_IGNITION_BREAKOUT_RESULT_JSON ===", flush=True)


if __name__ == "__main__":
    main()
