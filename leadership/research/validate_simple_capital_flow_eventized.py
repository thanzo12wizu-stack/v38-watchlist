from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import validate_early_rotation as er
import validate_pioneer_leader as pl
import validate_simple_capital_flow as scf

HORIZONS = (5, 10, 20)
COOLDOWN = 20
DISCOVERY_END = pd.Timestamp("2021-12-31")
CONFIRM_START = pd.Timestamp("2022-01-01")
BOOT_REPS = 3000


def safe(x: Any) -> Any:
    if isinstance(x, dict):
        return {str(k): safe(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [safe(v) for v in x]
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, (np.floating, float)):
        v = float(x)
        return v if math.isfinite(v) else None
    if isinstance(x, pd.Timestamp):
        return x.isoformat()
    return x


def forward_compound(ret: pd.Series, h: int) -> pd.Series:
    out = pd.Series(1.0, index=ret.index, dtype="float64")
    valid = pd.Series(True, index=ret.index)
    for k in range(1, h + 1):
        r = pd.to_numeric(ret.shift(-k), errors="coerce")
        valid &= r.notna()
        out *= 1.0 + r.fillna(0.0)
    return (out - 1.0).where(valid)


def cooldown_crossings(q: pd.Series, accepted_states: set[int], cooldown: int = COOLDOWN) -> list[tuple[pd.Timestamp, int]]:
    x = pd.to_numeric(q, errors="coerce")
    vals = x.to_numpy(float)
    dates = x.index
    out: list[tuple[pd.Timestamp, int]] = []
    last = -10_000
    prev = np.nan
    for i, v in enumerate(vals):
        if not np.isfinite(v):
            prev = v
            continue
        state = int(v)
        crossed = state in accepted_states and (not np.isfinite(prev) or int(prev) != state)
        if crossed and i - last >= cooldown:
            out.append((pd.Timestamp(dates[i]), state))
            last = i
        prev = v
    return out


def block_ids(dates: pd.Series, trading_dates: pd.DatetimeIndex, block_len: int = 20) -> np.ndarray:
    pos = pd.Series(np.arange(len(trading_dates)), index=trading_dates)
    ix = pos.reindex(pd.to_datetime(dates)).to_numpy(float)
    if not np.isfinite(ix).all():
        raise RuntimeError("event date missing from trading calendar")
    return np.floor(ix / float(block_len)).astype(np.int64)


def cluster_boot_mean(df: pd.DataFrame, value_col: str, cluster_col: str, seed: int, reps: int = BOOT_REPS) -> list[float | None]:
    use = df[[cluster_col, value_col]].dropna()
    if use.empty:
        return [None, None]
    agg = use.groupby(cluster_col, observed=True)[value_col].agg(["sum", "count"])
    if len(agg) < 2:
        return [None, None]
    sums = agg["sum"].to_numpy(float)
    counts = agg["count"].to_numpy(float)
    rng = np.random.default_rng(seed)
    vals = np.empty(reps, dtype=float)
    n = len(agg)
    for r in range(reps):
        idx = rng.integers(0, n, size=n)
        vals[r] = sums[idx].sum() / counts[idx].sum()
    return [float(v) for v in np.quantile(vals, [0.025, 0.975])]


def cluster_boot_diff(df: pd.DataFrame, value_col: str, group_col: str, hi: str, lo: str, cluster_col: str, seed: int, reps: int = BOOT_REPS) -> list[float | None]:
    use = df[[cluster_col, group_col, value_col]].dropna()
    use = use[use[group_col].isin([hi, lo])]
    clusters = list(pd.unique(use[cluster_col]))
    if len(clusters) < 2:
        return [None, None]
    pos = {c: i for i, c in enumerate(clusters)}
    hs = np.zeros(len(clusters)); hc = np.zeros(len(clusters))
    ls = np.zeros(len(clusters)); lc = np.zeros(len(clusters))
    agg = use.groupby([cluster_col, group_col], observed=True)[value_col].agg(["sum", "count"]).reset_index()
    for row in agg.itertuples(index=False):
        i = pos[getattr(row, cluster_col)]
        if getattr(row, group_col) == hi:
            hs[i], hc[i] = float(row.sum), float(row.count)
        else:
            ls[i], lc[i] = float(row.sum), float(row.count)
    rng = np.random.default_rng(seed)
    vals: list[float] = []
    n = len(clusters)
    for _ in range(reps):
        idx = rng.integers(0, n, size=n)
        if hc[idx].sum() > 0 and lc[idx].sum() > 0:
            vals.append(float(hs[idx].sum() / hc[idx].sum() - ls[idx].sum() / lc[idx].sum()))
    if not vals:
        return [None, None]
    return [float(v) for v in np.quantile(vals, [0.025, 0.975])]


def summarize(df: pd.DataFrame, value_col: str, trading_dates: pd.DatetimeIndex, seed: int, extra_clusters: tuple[str, ...] = ()) -> dict[str, Any]:
    use = df.dropna(subset=[value_col]).copy()
    if use.empty:
        return {"n": 0}
    use["block20"] = block_ids(use["date"], trading_dates, 20)
    out: dict[str, Any] = {
        "n": int(len(use)),
        "dates": int(use.date.nunique()),
        "mean": float(use[value_col].mean()),
        "median": float(use[value_col].median()),
        "positive_rate": float((use[value_col] > 0).mean()),
        "block20_ci95": cluster_boot_mean(use, value_col, "block20", seed),
    }
    if "sector" in use.columns:
        out["sectors"] = int(use.sector.nunique())
        out["sector_equal_weight_mean"] = float(use.groupby("sector", observed=True)[value_col].mean().mean())
        out["sector_cluster_ci95"] = cluster_boot_mean(use, value_col, "sector", seed + 1000)
    for j, c in enumerate(extra_clusters):
        if c in use.columns:
            out[f"{c}_cluster_ci95"] = cluster_boot_mean(use, value_col, c, seed + 2000 + j * 1000)
    return out


def summarize_diff(df: pd.DataFrame, value_col: str, group_col: str, hi: str, lo: str, trading_dates: pd.DatetimeIndex, seed: int, extra_clusters: tuple[str, ...] = ()) -> dict[str, Any]:
    use = df[df[group_col].isin([hi, lo])].dropna(subset=[value_col]).copy()
    a = use[use[group_col] == hi][value_col]
    b = use[use[group_col] == lo][value_col]
    if a.empty or b.empty:
        return {"hi_n": int(len(a)), "lo_n": int(len(b)), "difference": None}
    use["block20"] = block_ids(use["date"], trading_dates, 20)
    out: dict[str, Any] = {
        "hi_n": int(len(a)),
        "lo_n": int(len(b)),
        "difference": float(a.mean() - b.mean()),
        "block20_ci95": cluster_boot_diff(use, value_col, group_col, hi, lo, "block20", seed),
    }
    if "sector" in use.columns:
        out["sector_cluster_ci95"] = cluster_boot_diff(use, value_col, group_col, hi, lo, "sector", seed + 1000)
    for j, c in enumerate(extra_clusters):
        if c in use.columns:
            out[f"{c}_cluster_ci95"] = cluster_boot_diff(use, value_col, group_col, hi, lo, c, seed + 2000 + j * 1000)
    return out


def split_frames(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    d = pd.to_datetime(df.date)
    return {
        "ALL": df,
        "DISCOVERY_2016_2021": df[d <= DISCOVERY_END],
        "CONFIRMATION_2022_PLUS": df[d >= CONFIRM_START],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--output", required=True)
    ap.add_argument("--analysis-start", default="2016-01-04")
    ap.add_argument("--analysis-end", default="2026-06-20")
    ap.add_argument("--max-tickers", type=int, default=6000)
    ap.add_argument("--batch-size", type=int, default=75)
    args = ap.parse_args()

    root = Path(args.root)
    outdir = root / args.output
    outdir.mkdir(parents=True, exist_ok=True)
    start = pd.Timestamp(args.analysis_start)
    end = pd.Timestamp(args.analysis_end)

    industry_map = er.read_industry_map(root / "industry_map.json")
    universe = er.read_universe_symbols(root / "universe.csv")
    mapped = sorted(s for s in universe if s in industry_map and industry_map[s][0])
    if args.max_tickers and len(mapped) > args.max_tickers:
        mapped = mapped[:args.max_tickers]
    requested = mapped + (["SPY"] if "SPY" not in mapped else [])
    download_start = str((start - pd.Timedelta(days=120)).date())
    download_end = str((end + pd.Timedelta(days=90)).date())
    ohlcv, download_diag = pl.download_ohlcv(requested, download_start, download_end, args.batch_size)

    close_all = ohlcv["close"]
    if "SPY" not in close_all.columns:
        raise RuntimeError("SPY missing")
    stock_cols = [s for s in mapped if s in close_all.columns]
    close = close_all[stock_cols]
    volume = ohlcv["volume"][stock_cols]
    spy = close_all["SPY"]

    sector_groups: dict[str, list[str]] = {}
    for sym in stock_cols:
        sector = str(industry_map[sym][0])
        sector_groups.setdefault(sector, []).append(sym)
    sector_groups = {k: [s for s in v if s in close.columns] for k, v in sector_groups.items() if len(v) >= 3}
    eligible = sorted({s for v in sector_groups.values() for s in v})
    close = close[eligible]
    volume = volume[eligible]
    stock_cols = eligible

    dollar_volume = (close * volume).where((close > 0) & (volume >= 0))
    sector_dv = pd.DataFrame(index=close.index)
    for sector, members in sector_groups.items():
        members = [s for s in members if s in stock_cols]
        if len(members) >= 3:
            sector_dv[sector] = dollar_volume[members].sum(axis=1, min_count=1)
    sector_groups = {k: [s for s in v if s in stock_cols] for k, v in sector_groups.items() if k in sector_dv.columns}

    market_dv = sector_dv.sum(axis=1, min_count=1)
    sector_share = sector_dv.div(market_dv.replace(0.0, np.nan), axis=0)
    sector_flow = scf.rolling_ratio(sector_share, 5, 20)
    sector_q = scf.quintiles(sector_flow)

    stock_capture = pd.DataFrame(index=close.index, columns=stock_cols, dtype="float32")
    for sector, members in sector_groups.items():
        members = [s for s in members if s in stock_cols]
        share = dollar_volume[members].div(sector_dv[sector].replace(0.0, np.nan), axis=0)
        stock_capture.loc[:, members] = scf.rolling_ratio(share, 5, 20).astype("float32")
    stock_q = scf.quintiles(stock_capture)

    eval_dates = close.index[(close.index >= start) & (close.index <= end)]
    trading_dates = close.index

    sector_events: list[dict[str, Any]] = []
    for sector in sector_q.columns:
        q = sector_q[sector].reindex(eval_dates)
        for date, state in cooldown_crossings(q, {1, 5}, COOLDOWN):
            sector_events.append({"date": date, "sector": sector, "state": f"Q{state}"})
    sector_events_df = pd.DataFrame(sector_events)

    stock_events: list[dict[str, Any]] = []
    for sym in stock_q.columns:
        q = stock_q[sym].reindex(eval_dates)
        sector = str(industry_map[sym][0])
        for date, state in cooldown_crossings(q, {5}, COOLDOWN):
            sq = sector_q.at[date, sector] if date in sector_q.index and sector in sector_q.columns else np.nan
            if pd.notna(sq):
                stock_events.append({"date": date, "symbol": sym, "sector": sector, "sector_q": int(sq)})
    stock_events_df = pd.DataFrame(stock_events)

    stock_ret = close.pct_change(fill_method=None)
    sector_daily = pd.DataFrame(index=close.index)
    for sector, members in sector_groups.items():
        members = [s for s in members if s in stock_ret.columns]
        sector_daily[sector] = stock_ret[members].mean(axis=1, skipna=True)
    spy_ret = spy.pct_change(fill_method=None)

    result: dict[str, Any] = {
        "status": "PRELIMINARY_FIXED_CURRENT_UNIVERSE_EVENTIZED_SIMPLE_CAPITAL_FLOW",
        "design": {
            "hypothesis_unchanged": True,
            "sector_flow": "Sector dollar-volume market share: recent5/prior20; daily quintile",
            "stock_capture": "Stock dollar-volume share within Sector: recent5/prior20; daily quintile",
            "sector_event": "first entry into Q1/Q5 after another state; joint 20 trading-day cooldown per Sector",
            "stock_event": "first entry into Stock Capture Q5; 20 trading-day cooldown per symbol",
            "combined_test": "at Sector Flow Q5 event, one event-level portfolio comparison: Stock Capture Q5 vs other stocks in same Sector",
            "overlap_control": "20d entity cooldown plus 20-trading-day block bootstrap",
            "clusters": "Sector for Sector events; Sector and symbol for Stock events",
            "no_gates": "no RS, Stage, Base, EPS, Subtheme Momentum, MC57",
            "warning": "current universe/current Sector map retrospectively applied",
        },
        "coverage": {
            "stocks": len(stock_cols),
            "sectors": len(sector_groups),
            "days": int(len(eval_dates)),
            "sector_events": int(len(sector_events_df)),
            "sector_event_dates": int(sector_events_df.date.nunique()) if len(sector_events_df) else 0,
            "stock_capture_q5_events": int(len(stock_events_df)),
            "stock_event_dates": int(stock_events_df.date.nunique()) if len(stock_events_df) else 0,
            "download": download_diag,
        },
        "horizons": {},
    }

    for hi, h in enumerate(HORIZONS):
        print(f"HORIZON {h}", flush=True)
        stock_fwd = close.shift(-h) / close - 1.0
        sector_fwd = pd.DataFrame(index=close.index)
        for sector in sector_daily.columns:
            sector_fwd[sector] = forward_compound(sector_daily[sector], h)
        spy_fwd = forward_compound(spy_ret, h)

        srows: list[dict[str, Any]] = []
        for ev in sector_events_df.itertuples(index=False):
            date = pd.Timestamp(ev.date); sector = str(ev.sector); state = str(ev.state)
            if date not in sector_fwd.index or pd.isna(sector_fwd.at[date, sector]) or pd.isna(spy_fwd.get(date, np.nan)):
                continue
            rec: dict[str, Any] = {
                "date": date, "sector": sector, "state": state,
                "sector_minus_spy": float(sector_fwd.at[date, sector] - spy_fwd.at[date]),
            }
            if state == "Q5":
                members = [s for s in sector_groups[sector] if s in stock_fwd.columns]
                row = stock_fwd.loc[date, members]
                qrow = stock_q.loc[date, members]
                sel = row[(qrow == 5) & row.notna()]
                mid = row[(qrow >= 2) & (qrow <= 4) & row.notna()]
                oth = row[(qrow != 5) & row.notna()]
                if len(sel) >= 2 and len(oth) >= 3:
                    rec["capture_q5_minus_other"] = float(sel.mean() - oth.mean())
                    rec["capture_q5_n"] = int(len(sel))
                    rec["other_n"] = int(len(oth))
                if len(sel) >= 2 and len(mid) >= 3:
                    rec["capture_q5_minus_mid"] = float(sel.mean() - mid.mean())
                    rec["mid_n"] = int(len(mid))
            srows.append(rec)
        sdf = pd.DataFrame(srows)

        crows: list[dict[str, Any]] = []
        for ev in stock_events_df.itertuples(index=False):
            date = pd.Timestamp(ev.date); sym = str(ev.symbol); sector = str(ev.sector); sq = int(ev.sector_q)
            if date not in stock_fwd.index or sym not in stock_fwd.columns:
                continue
            sr = stock_fwd.at[date, sym]
            if pd.isna(sr):
                continue
            peers = [s for s in sector_groups[sector] if s != sym and s in stock_fwd.columns]
            pv = stock_fwd.loc[date, peers].dropna()
            if len(pv) < 2:
                continue
            crows.append({
                "date": date, "symbol": sym, "sector": sector,
                "sector_q": sq, "sector_group": "Q5" if sq == 5 else "Q1_4",
                "stock_minus_sector_peers": float(sr - pv.mean()),
            })
        cdf = pd.DataFrame(crows)

        hres: dict[str, Any] = {"sector_event": {}, "combined_at_sector_q5": {}, "stock_capture_event": {}}
        for si, (split_name, sf) in enumerate(split_frames(sdf).items()):
            hres["sector_event"][split_name] = {
                "Q5": summarize(sf[sf.state == "Q5"], "sector_minus_spy", trading_dates, 10000 + hi * 1000 + si * 50),
                "Q1": summarize(sf[sf.state == "Q1"], "sector_minus_spy", trading_dates, 10001 + hi * 1000 + si * 50),
                "Q5_minus_Q1": summarize_diff(sf, "sector_minus_spy", "state", "Q5", "Q1", trading_dates, 10002 + hi * 1000 + si * 50),
            }
            q5sf = sf[sf.state == "Q5"].copy()
            hres["combined_at_sector_q5"][split_name] = {
                "capture_q5_minus_other": summarize(q5sf, "capture_q5_minus_other", trading_dates, 11000 + hi * 1000 + si * 50),
                "capture_q5_minus_mid": summarize(q5sf, "capture_q5_minus_mid", trading_dates, 11001 + hi * 1000 + si * 50),
            }

        for si, (split_name, cf) in enumerate(split_frames(cdf).items()):
            qsum: dict[str, Any] = {}
            for q in range(1, 6):
                qsum[f"Q{q}"] = summarize(cf[cf.sector_q == q], "stock_minus_sector_peers", trading_dates, 12000 + hi * 1000 + si * 100 + q, extra_clusters=("symbol",))
            qsum["sectorQ5_minus_Q1_4"] = summarize_diff(cf, "stock_minus_sector_peers", "sector_group", "Q5", "Q1_4", trading_dates, 12100 + hi * 1000 + si * 100, extra_clusters=("symbol",))
            hres["stock_capture_event"][split_name] = qsum

        result["horizons"][str(h)] = hres

    (outdir / "eventized_capital_flow_results.json").write_text(json.dumps(safe(result), indent=2), encoding="utf-8")
    sector_events_df.to_csv(outdir / "sector_events.csv", index=False)
    stock_events_df.to_csv(outdir / "stock_capture_events.csv", index=False)
    print(json.dumps({"RESULT": safe(result)}, separators=(",", ":")), flush=True)


if __name__ == "__main__":
    main()
