from __future__ import annotations

import argparse
import io
import json
import math
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import pitindex
import rotation_divergence_proxy_backtest as proxy
import rotation_exact_flow_research as flowlib
import rotation_wikipedia_pit_sector_audit as wiki
import validate_pioneer_leader as pl

SECTORS = proxy.SECTOR_ETFS
HORIZONS = (5, 10, 20, 40)
COOLDOWN = 20
BOOT_REPS = 3000
DISCOVERY_END = pd.Timestamp("2023-12-31")
CONFIRM_START = pd.Timestamp("2024-01-01")
COVERAGE_LEVELS = (0.60, 0.80, 0.90)
EXPLICIT_GICS_ANCHORS = (pd.Timestamp("2023-03-17"), pd.Timestamp("2023-03-20"))


def safe(v: Any) -> Any:
    if isinstance(v, dict):
        return {str(k): safe(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [safe(x) for x in v]
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, (np.floating, float)):
        x = float(v)
        return x if math.isfinite(x) else None
    if isinstance(v, pd.Timestamp):
        return v.isoformat()
    return v


def wikipedia_revision_roster_fast(session: requests.Session, asof: pd.Timestamp) -> tuple[pd.DataFrame, dict[str, Any]]:
    rev = wiki.revision_at_or_before(session, asof)
    params = {"action": "parse", "format": "json", "formatversion": "2", "oldid": str(rev["revid"]), "prop": "text"}
    try:
        r = session.get(wiki.WIKI_API, params=params, headers={"User-Agent": wiki.UA}, timeout=45)
        r.raise_for_status()
        html = r.json().get("parse", {}).get("text")
        if not html:
            raise RuntimeError("empty parse html")
        tables = pd.read_html(io.StringIO(html))
        chosen = None
        for t in tables:
            cols = [" ".join(map(str, c)) if isinstance(c, tuple) else str(c) for c in t.columns]
            low = [c.lower() for c in cols]
            if any("symbol" in c for c in low) and any("gics sector" in c for c in low):
                t = t.copy()
                t.columns = cols
                chosen = t
                break
        if chosen is None:
            raise RuntimeError("constituent table not found")

        def find_col(fragment: str) -> str | None:
            return next((c for c in chosen.columns if fragment in c.lower()), None)

        c_symbol = find_col("symbol")
        c_security = find_col("security")
        c_sector = find_col("gics sector")
        c_sub = find_col("gics sub-industry") or find_col("gics sub industry")
        if not c_symbol or not c_sector:
            raise RuntimeError("required columns missing")
        out = pd.DataFrame({
            "ticker": chosen[c_symbol].map(wiki.norm_ticker),
            "name": chosen[c_security].map(wiki.clean_text) if c_security else None,
            "gics_sector": chosen[c_sector].map(wiki.clean_text),
            "gics_sub_industry": chosen[c_sub].map(wiki.clean_text) if c_sub else None,
        })
        out = out.dropna(subset=["ticker"]).drop_duplicates("ticker", keep="first")
        out["sector_etf"] = out["gics_sector"].map(wiki.GICS_TO_ETF)
        return out.reset_index(drop=True), {**rev, "method": "mediawiki_parse_api"}
    except Exception:
        out = wiki.parse_revision_roster(session, rev["revid"])
        return out, {**rev, "method": "oldid_html_fallback"}


def anchor_dates(start: pd.Timestamp, end: pd.Timestamp) -> list[pd.Timestamp]:
    weekly = list(pd.date_range(start, end, freq="W-FRI"))
    hist = pitindex.get_constituents_history(str(start.date()), str(end.date()), index="sp500")
    changes = [pd.Timestamp(x).normalize() for x in pd.unique(hist["as_of"])] if not hist.empty else []
    explicit = [x for x in EXPLICIT_GICS_ANCHORS if start <= x <= end]
    return sorted(set([start, end, *weekly, *changes, *explicit]))


def build_pit_sector_snapshots(session: requests.Session, start: pd.Timestamp, end: pd.Timestamp, sleep: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    anchors = anchor_dates(start, end)
    rows: list[pd.DataFrame] = []
    qrows: list[dict[str, Any]] = []
    for i, d in enumerate(anchors, 1):
        roster, meta = wikipedia_revision_roster_fast(session, d)
        pit = pitindex.get_constituents(str(d.date()), index="sp500").copy()
        pit["ticker"] = pit["ticker"].map(wiki.norm_ticker)
        pit = pit.dropna(subset=["ticker"]).drop_duplicates("ticker", keep="first")
        pit_set = set(pit["ticker"])
        mapped = roster[roster["ticker"].isin(pit_set) & roster["sector_etf"].notna()].copy()
        mapping_rate = mapped["ticker"].nunique() / len(pit_set) if pit_set else np.nan
        inter = set(roster["ticker"]) & pit_set
        union = set(roster["ticker"]) | pit_set
        jaccard = len(inter) / len(union) if union else np.nan
        mapped["anchor_date"] = d
        mapped["revision_id"] = meta["revid"]
        mapped["revision_timestamp"] = meta["timestamp"]
        rows.append(mapped[["anchor_date", "ticker", "sector_etf", "gics_sector", "revision_id", "revision_timestamp"]])
        qrows.append({"anchor_date": d, "revision_id": meta["revid"], "revision_timestamp": meta["timestamp"], "method": meta["method"], "pit_size": len(pit_set), "wiki_size": roster["ticker"].nunique(), "jaccard": jaccard, "mapped": mapped["ticker"].nunique(), "mapping_rate": mapping_rate})
        if i % 25 == 0 or i == len(anchors):
            print(f"PIT_SECTOR {i}/{len(anchors)} {d.date()} map={mapping_rate:.2%} jac={jaccard:.2%}", flush=True)
        if sleep > 0:
            time.sleep(sleep)
    snapshots = pd.concat(rows, ignore_index=True).sort_values(["anchor_date", "ticker"]).reset_index(drop=True)
    quality = pd.DataFrame(qrows).sort_values("anchor_date").reset_index(drop=True)
    return snapshots, quality


def membership_by_day(trading_dates: pd.DatetimeIndex, sector_snapshots: pd.DataFrame) -> tuple[dict[pd.Timestamp, dict[str, list[str]]], pd.DataFrame]:
    snap_dates = pd.DatetimeIndex(sorted(pd.to_datetime(sector_snapshots["anchor_date"]).unique()))
    by_anchor: dict[pd.Timestamp, dict[str, str]] = {}
    for d, grp in sector_snapshots.groupby("anchor_date", sort=False):
        by_anchor[pd.Timestamp(d)] = dict(zip(grp["ticker"].astype(str), grp["sector_etf"].astype(str)))
    out: dict[pd.Timestamp, dict[str, list[str]]] = {}
    qrows: list[dict[str, Any]] = []
    for i, d in enumerate(trading_dates):
        pos = snap_dates.searchsorted(d, side="right") - 1
        if pos < 0:
            continue
        anchor = pd.Timestamp(snap_dates[pos])
        smap = by_anchor[anchor]
        pit = pitindex.get_constituents(str(pd.Timestamp(d).date()), index="sp500")
        tickers = [wiki.norm_ticker(x) for x in pit["ticker"].tolist()]
        tickers = [x for x in tickers if x]
        groups = {s: [] for s in SECTORS}
        mapped = 0
        for t in tickers:
            sector = smap.get(t)
            if sector in groups:
                groups[sector].append(t)
                mapped += 1
        out[pd.Timestamp(d)] = groups
        qrows.append({"date": pd.Timestamp(d), "anchor_date": anchor, "members": len(tickers), "mapped": mapped, "mapping_rate": mapped / len(tickers) if tickers else np.nan})
        if (i + 1) % 250 == 0:
            print(f"MEMBERSHIP {i+1}/{len(trading_dates)}", flush=True)
    return out, pd.DataFrame(qrows)


def download_pit_ohlcv(start: pd.Timestamp, end: pd.Timestamp, membership: dict[pd.Timestamp, dict[str, list[str]]], batch_size: int) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    tickers = sorted({t for groups in membership.values() for members in groups.values() for t in members})
    requested = tickers + ["SPY", *SECTORS]
    return pl.download_ohlcv(requested, str(start.date()), str((end + pd.Timedelta(days=70)).date()), batch_size)


def build_dynamic_components(ohlcv: dict[str, pd.DataFrame], membership: dict[pd.Timestamp, dict[str, list[str]]], global_map_q: pd.DataFrame, min_coverage: float) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    close = ohlcv["close"].copy()
    volume = ohlcv["volume"].copy()
    dates = close.index
    stock_cols = [c for c in close.columns if c not in {"SPY", *SECTORS}]
    c = close[stock_cols]
    v = volume.reindex(columns=stock_cols)
    ema21 = c.ewm(span=21, adjust=False, min_periods=15).mean()
    sma50 = c.rolling(50, min_periods=35).mean()
    ret = c.pct_change(fill_method=None)
    signed_volume = v.where(ret > 0, -v.where(ret < 0, 0.0)).where(ret.notna() & v.notna())
    obv = signed_volume.fillna(0.0).cumsum()
    obv_delta20 = obv - obv.shift(20)
    data: dict[str, pd.DataFrame] = {}
    fields = ["breadth21", "breadth50", "ad_daily", "obv_positive20", "up_volume", "down_volume", "coverage", "member_count"]
    raw = {s: {f: pd.Series(np.nan, index=dates, dtype=float) for f in fields} for s in SECTORS}
    map_q = global_map_q.set_index("date")["mapping_rate"].reindex(dates)

    for di, d in enumerate(dates):
        groups = membership.get(pd.Timestamp(d))
        if groups is None or not np.isfinite(map_q.loc[d]) or map_q.loc[d] < 0.98:
            continue
        for sector in SECTORS:
            members = [x for x in groups[sector] if x in c.columns]
            n_map = len(groups[sector])
            if n_map < 5:
                continue
            valid_members = [x for x in members if pd.notna(c.at[d, x]) and pd.notna(v.at[d, x])]
            cov = len(valid_members) / n_map
            raw[sector]["coverage"].at[d] = cov
            raw[sector]["member_count"].at[d] = n_map
            if cov < min_coverage or len(valid_members) < 5:
                continue
            vm = valid_members
            evalid = [x for x in vm if pd.notna(ema21.at[d, x])]
            svalid = [x for x in vm if pd.notna(sma50.at[d, x])]
            rvalid = [x for x in vm if pd.notna(ret.at[d, x])]
            ovalid = [x for x in vm if pd.notna(obv_delta20.at[d, x])]
            need = max(5, math.ceil(n_map * min_coverage))
            if len(evalid) >= need:
                raw[sector]["breadth21"].at[d] = 100.0 * float((c.loc[d, evalid] > ema21.loc[d, evalid]).mean())
            if len(svalid) >= need:
                raw[sector]["breadth50"].at[d] = 100.0 * float((c.loc[d, svalid] > sma50.loc[d, svalid]).mean())
            if len(rvalid) >= need:
                rr = ret.loc[d, rvalid]
                raw[sector]["ad_daily"].at[d] = float(((rr > 0).sum() - (rr < 0).sum()) / len(rvalid))
                vv = v.loc[d, rvalid]
                raw[sector]["up_volume"].at[d] = float(vv.where(rr > 0, 0.0).sum())
                raw[sector]["down_volume"].at[d] = float(vv.where(rr < 0, 0.0).sum())
            if len(ovalid) >= need:
                raw[sector]["obv_positive20"].at[d] = 100.0 * float((obv_delta20.loc[d, ovalid] > 0).mean())
        if (di + 1) % 250 == 0:
            print(f"INTERNAL cov={min_coverage:.0%} {di+1}/{len(dates)}", flush=True)

    for sector in SECTORS:
        r = raw[sector]
        ad20 = 50.0 * (1.0 + r["ad_daily"].rolling(20, min_periods=15).mean())
        up20 = r["up_volume"].rolling(20, min_periods=15).sum()
        down20 = r["down_volume"].rolling(20, min_periods=15).sum()
        data[sector] = pd.DataFrame({"breadth21": r["breadth21"], "breadth50": r["breadth50"], "ad20_score": ad20.clip(0, 100), "obv_positive20": r["obv_positive20"], "updown_volume20": up20 / down20.replace(0.0, np.nan), "stock_data_coverage": r["coverage"], "pit_member_count": r["member_count"]})
    cov_rows = []
    for s in SECTORS:
        x = data[s]["stock_data_coverage"]
        cov_rows.append({"sector": s, "coverage_level": min_coverage, "median_stock_data_coverage": float(x.median()), "p10_stock_data_coverage": float(x.quantile(0.10)), "valid_days": int((x >= min_coverage).sum())})
    return data, pd.DataFrame(cov_rows)


def cross_section_rank(wide: pd.DataFrame, min_count: int = 5) -> pd.DataFrame:
    out = wide.rank(axis=1, pct=True, method="average") * 100.0
    return out.where(wide.notna().sum(axis=1) >= min_count)


def build_panel(ohlcv: dict[str, pd.DataFrame], components: dict[str, pd.DataFrame], exact_flows: pd.DataFrame) -> pd.DataFrame:
    close = ohlcv["close"]
    if "SPY" not in close.columns or any(s not in close.columns for s in SECTORS):
        raise RuntimeError("SPY/sector ETF prices missing")
    spy = close["SPY"]
    etf = close[SECTORS]
    rs63 = etf.pct_change(63, fill_method=None).sub(spy.pct_change(63, fill_method=None), axis=0)
    rs189 = etf.pct_change(189, fill_method=None).sub(spy.pct_change(189, fill_method=None), axis=0)
    p63 = cross_section_rank(rs63)
    p189 = cross_section_rank(rs189)
    price_score = (p63 + p189) / 2.0
    comp_names = ["breadth21", "breadth50", "ad20_score", "obv_positive20", "updown_volume20"]
    comp_ranks = {}
    for name in comp_names:
        wide = pd.DataFrame({s: components[s][name] for s in SECTORS})
        comp_ranks[name] = cross_section_rank(wide)
    rank_stack = np.stack([comp_ranks[n].to_numpy(float) for n in comp_names], axis=2)
    with np.errstate(all="ignore"):
        arr = np.nanmedian(rank_stack, axis=2)
    internal = pd.DataFrame(arr, index=close.index, columns=SECTORS)
    valid_components = sum(x.notna().astype(int) for x in comp_ranks.values())
    internal = internal.where(valid_components >= 4)
    flow = exact_flows.copy()
    flow["date"] = pd.to_datetime(flow["date"]).dt.normalize()
    flow = flow[flow["ticker"].isin(SECTORS)].drop_duplicates(["date", "ticker"], keep="last")
    flow20 = flow.pivot(index="date", columns="ticker", values="flow_20d_pct_aum").reindex(columns=SECTORS)
    rows = []
    for s in SECTORS:
        f = pd.DataFrame(index=close.index)
        f["date"] = f.index
        f["sector"] = s
        f["price_score"] = price_score[s]
        f["internal_score"] = internal[s]
        f["flow20_pct_aum"] = flow20[s].reindex(f.index)
        f["stock_data_coverage"] = components[s]["stock_data_coverage"]
        f["pit_member_count"] = components[s]["pit_member_count"]
        for n in comp_names:
            f[n] = components[s][n]
            f[f"{n}_rank"] = comp_ranks[n][s]
        for h in HORIZONS:
            f[f"fwd_excess_{h}d"] = (etf[s].shift(-h) / etf[s] - 1.0) - (spy.shift(-h) / spy - 1.0)
        rows.append(f.reset_index(drop=True))
    return pd.concat(rows, ignore_index=True).sort_values(["date", "sector"]).reset_index(drop=True)


def distribution_mask(panel: pd.DataFrame, p: float, i: float, flow_cut: float) -> pd.Series:
    return (panel["price_score"] >= p) & (panel["internal_score"] < i) & (panel["flow20_pct_aum"] <= -flow_cut)


def eventize(panel: pd.DataFrame, mask: pd.Series, label: str) -> pd.DataFrame:
    cols = ["date", "sector", *[f"fwd_excess_{h}d" for h in HORIZONS]]
    use = panel[cols].copy()
    use["active"] = mask.fillna(False).to_numpy(bool)
    rows = []
    for sector, grp in use.groupby("sector", sort=False):
        grp = grp.sort_values("date")
        prev = False
        last = -10000
        for pos, row in enumerate(grp.itertuples(index=False)):
            active = bool(row.active)
            if active and not prev and pos - last >= COOLDOWN:
                rec = {"date": pd.Timestamp(row.date), "sector": sector, "condition": label}
                for h in HORIZONS:
                    rec[f"fwd_excess_{h}d"] = getattr(row, f"fwd_excess_{h}d")
                rows.append(rec)
                last = pos
            prev = active
    return pd.DataFrame(rows)


def block_ids(dates: pd.Series, calendar: pd.DatetimeIndex) -> np.ndarray:
    pos = pd.Series(np.arange(len(calendar)), index=calendar)
    x = pos.reindex(pd.to_datetime(dates)).to_numpy(float)
    return np.floor(x / 20.0).astype(np.int64)


def cluster_boot_mean(df: pd.DataFrame, value_col: str, cluster_col: str, seed: int) -> list[float | None]:
    use = df[[cluster_col, value_col]].dropna()
    if use.empty:
        return [None, None]
    agg = use.groupby(cluster_col, observed=True)[value_col].agg(["sum", "count"])
    if len(agg) < 2:
        return [None, None]
    sums = agg["sum"].to_numpy(float)
    counts = agg["count"].to_numpy(float)
    rng = np.random.default_rng(seed)
    vals = np.empty(BOOT_REPS)
    n = len(agg)
    for r in range(BOOT_REPS):
        idx = rng.integers(0, n, size=n)
        vals[r] = sums[idx].sum() / counts[idx].sum()
    return [float(x) for x in np.quantile(vals, [0.025, 0.975])]


def summarize(events: pd.DataFrame, calendar: pd.DatetimeIndex, seed: int) -> dict[str, Any]:
    if events.empty:
        return {"n": 0, "horizons": {}}
    ev = events.copy()
    ev["block20"] = block_ids(ev["date"], calendar)
    out: dict[str, Any] = {"n": len(ev), "dates": ev.date.nunique(), "sectors": ev.sector.nunique(), "horizons": {}}
    for j, h in enumerate(HORIZONS):
        col = f"fwd_excess_{h}d"
        x = pd.to_numeric(ev[col], errors="coerce")
        finite = ev[np.isfinite(x.to_numpy(float))].copy()
        if finite.empty:
            out["horizons"][str(h)] = {"n": 0}
            continue
        vals = finite[col].astype(float)
        out["horizons"][str(h)] = {"n": len(vals), "mean": float(vals.mean()), "median": float(vals.median()), "negative_rate": float((vals < 0).mean()), "block20_ci95": cluster_boot_mean(finite, col, "block20", seed + j * 100), "sector_cluster_ci95": cluster_boot_mean(finite, col, "sector", seed + 1000 + j * 100)}
    return out


def period_frames(events: pd.DataFrame) -> dict[str, pd.DataFrame]:
    if events.empty:
        return {"ALL_2022_PLUS": events, "DISCOVERY_2022_2023": events, "CONFIRMATION_2024_PLUS": events}
    d = pd.to_datetime(events.date)
    out = {"ALL_2022_PLUS": events[d >= pd.Timestamp("2022-01-01")], "DISCOVERY_2022_2023": events[(d >= pd.Timestamp("2022-01-01")) & (d <= DISCOVERY_END)], "CONFIRMATION_2024_PLUS": events[d >= CONFIRM_START]}
    for y in range(2022, 2027):
        out[str(y)] = events[d.dt.year == y]
    return out


def exact_flows(session: requests.Session, start: pd.Timestamp, end: pd.Timestamp) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    frames = []
    diag = []
    for s in SECTORS:
        series = flowlib.fetch_ssga_nav_history(session, s)
        f, d = flowlib.derive_exact_flows(series)
        f = f[(f["date"] >= start) & (f["date"] <= end)].copy()
        frames.append(f)
        diag.append(d)
        print(f"FLOW {s}: {len(f)}", flush=True)
    return pd.concat(frames, ignore_index=True), diag


def main() -> None:
    ap = argparse.ArgumentParser(description="PIT Distribution Trap validation with point-in-time S&P500 membership/GICS and official ETF fund flows")
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--warmup-start", default="2021-01-04")
    ap.add_argument("--analysis-start", default="2022-01-03")
    ap.add_argument("--analysis-end", default="2026-08-17")
    ap.add_argument("--batch-size", type=int, default=75)
    ap.add_argument("--wiki-sleep", type=float, default=0.05)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    info = pitindex.info(index="sp500")
    pit_end = pd.Timestamp(info["end_date"]).normalize()
    warmup = pd.Timestamp(args.warmup_start).normalize()
    start = pd.Timestamp(args.analysis_start).normalize()
    end = min(pd.Timestamp(args.analysis_end).normalize(), pit_end)
    if end < start:
        raise RuntimeError("PIT dataset ends before analysis window")
    session = requests.Session()
    snapshots, sector_q = build_pit_sector_snapshots(session, warmup, end, args.wiki_sleep)
    snapshots.to_csv(args.output / "pit_sector_snapshots.csv", index=False, date_format="%Y-%m-%d")
    sector_q.to_csv(args.output / "pit_sector_snapshot_quality.csv", index=False, date_format="%Y-%m-%d")
    if sector_q["mapping_rate"].min() < 0.98 or sector_q["jaccard"].min() < 0.98:
        raise RuntimeError(f"PIT sector snapshots fail strict quality gate: min_map={sector_q['mapping_rate'].min():.4f} min_jac={sector_q['jaccard'].min():.4f}")
    provisional_dates = pd.bdate_range(warmup, end)
    provisional_membership, _ = membership_by_day(provisional_dates, snapshots)
    ohlcv, download_diag = download_pit_ohlcv(warmup, end, provisional_membership, args.batch_size)
    trading_dates = ohlcv["close"].index[(ohlcv["close"].index >= warmup) & (ohlcv["close"].index <= end)]
    membership, map_q = membership_by_day(trading_dates, snapshots)
    map_q.to_csv(args.output / "daily_pit_mapping_quality.csv", index=False, date_format="%Y-%m-%d")
    if map_q["mapping_rate"].min() < 0.98:
        raise RuntimeError(f"daily PIT mapping falls below 98%: {map_q['mapping_rate'].min():.4f}")
    flows, flow_diag = exact_flows(session, warmup, end)
    flows.to_csv(args.output / "exact_sector_flows.csv", index=False, date_format="%Y-%m-%d")
    report: dict[str, Any] = {"schema": 1, "research_only": True, "pit_membership": "pitindex pinned at workflow install commit; daily membership", "pit_sector": "Wikipedia revision at-or-before observation date; weekly Friday + membership-change anchors + explicit 2023 GICS anchor", "flow_quality": "EXACT_OFFICIAL_SSGA_SHARES_OUTSTANDING_DERIVED", "internal": "PIT dynamic equal-weight; five independent components; cross-sectional ranks; median rank; no 30/30/25/15 weights", "window": {"warmup_start": str(warmup.date()), "analysis_start": str(start.date()), "analysis_end": str(end.date()), "pit_data_end": info["end_date"]}, "source_quality": {"sector_snapshot_min_mapping": float(sector_q["mapping_rate"].min()), "sector_snapshot_min_jaccard": float(sector_q["jaccard"].min()), "daily_mapping_min": float(map_q["mapping_rate"].min()), "download": download_diag, "flow": flow_diag}, "coverage_levels": {}, "decision": {}}
    result_rows = []
    all_events = []
    coverage_rows = []
    grid = [(p, i, f) for p in (65.0, 70.0, 75.0) for i in (45.0, 50.0, 55.0) for f in (0.0, 0.5, 1.0)]
    for ci, cov in enumerate(COVERAGE_LEVELS):
        components, covdiag = build_dynamic_components(ohlcv, membership, map_q, cov)
        coverage_rows.append(covdiag)
        panel = build_panel(ohlcv, components, flows)
        panel = panel[(panel["date"] >= start) & (panel["date"] <= end)].copy()
        panel.to_csv(args.output / f"distribution_pit_panel_cov{int(cov*100)}.csv", index=False, date_format="%Y-%m-%d")
        calendar = pd.DatetimeIndex(sorted(panel["date"].unique()))
        cov_out: dict[str, Any] = {"grid": {}, "ablation": {}}
        for gi, (p, icut, fcut) in enumerate(grid):
            label = f"P{int(p)}_I{int(icut)}_F{fcut:g}"
            ev = eventize(panel, distribution_mask(panel, p, icut, fcut), label)
            if not ev.empty:
                ev["coverage_level"] = cov
                ev["p"] = p
                ev["i"] = icut
                ev["flow_cut"] = fcut
                all_events.append(ev)
            po = {}
            for pi, (period, pev) in enumerate(period_frames(ev).items()):
                s = summarize(pev, calendar, seed=10000 + ci * 100000 + gi * 1000 + pi * 10)
                po[period] = s
                for h in HORIZONS:
                    hs = s.get("horizons", {}).get(str(h), {})
                    result_rows.append({"coverage_level": cov, "config": label, "p": p, "i": icut, "flow_cut": fcut, "period": period, "horizon": h, "n": hs.get("n", 0), "mean_excess": hs.get("mean"), "median_excess": hs.get("median"), "negative_rate": hs.get("negative_rate"), "block_ci_lo": (hs.get("block20_ci95") or [None, None])[0], "block_ci_hi": (hs.get("block20_ci95") or [None, None])[1], "sector_ci_lo": (hs.get("sector_cluster_ci95") or [None, None])[0], "sector_ci_hi": (hs.get("sector_cluster_ci95") or [None, None])[1]})
            cov_out["grid"][label] = po
        masks = {"FLOW_OUT_ONLY": panel["flow20_pct_aum"] <= 0, "PRICE_INTERNAL": (panel["price_score"] >= 70) & (panel["internal_score"] < 50), "FULL_DISTRIBUTION": distribution_mask(panel, 70, 50, 0)}
        for ai, (label, mask) in enumerate(masks.items()):
            ev = eventize(panel, mask, label)
            cov_out["ablation"][label] = {period: summarize(pev, calendar, seed=700000 + ci * 10000 + ai * 1000 + pi * 10) for pi, (period, pev) in enumerate(period_frames(ev).items())}
        report["coverage_levels"][str(cov)] = cov_out
    results = pd.DataFrame(result_rows)
    results.to_csv(args.output / "distribution_pit_grid_results.csv", index=False)
    pd.concat(coverage_rows, ignore_index=True).to_csv(args.output / "distribution_pit_data_coverage.csv", index=False)
    if all_events:
        pd.concat(all_events, ignore_index=True).sort_values(["date", "coverage_level", "config", "sector"]).to_csv(args.output / "distribution_pit_events.csv", index=False, date_format="%Y-%m-%d")
    robust = {}
    pass_all = True
    for cov in COVERAGE_LEVELS:
        robust[str(cov)] = {}
        for h in (20, 40):
            sub = results[(results.coverage_level == cov) & (results.period == "CONFIRMATION_2024_PLUS") & (results.horizon == h)]
            vals = pd.to_numeric(sub["mean_excess"], errors="coerce").dropna()
            frac_neg = float((vals < 0).mean()) if len(vals) else None
            median_mean = float(vals.median()) if len(vals) else None
            robust[str(cov)][str(h)] = {"configs_with_result": len(vals), "fraction_negative": frac_neg, "median_config_mean_excess": median_mean}
            if frac_neg is None or frac_neg < 0.80:
                pass_all = False
    baseline = results[(results.coverage_level == 0.80) & (results.config == "P70_I50_F0") & (results.period == "CONFIRMATION_2024_PLUS")]
    base_ok = True
    for h in (20, 40):
        r = baseline[baseline.horizon == h]
        if r.empty or pd.isna(r.iloc[0].mean_excess) or float(r.iloc[0].mean_excess) >= 0 or int(r.iloc[0].n) < 10:
            base_ok = False
    accepted_research_context = bool(pass_all and base_ok)
    report["decision"] = {"robustness": robust, "baseline_cov80": baseline.to_dict("records"), "survives_pit_as_research_distribution_context": accepted_research_context, "production_adoption": False, "trading_gate": False, "forced_exit": False, "interpretation": "Eligible only as Sector Distribution warning context; never a V38 entry/exit gate." if accepted_research_context else "Distribution proxy did not survive strict PIT robustness requirements; reject as operational signal."}
    (args.output / "distribution_pit_report.json").write_text(json.dumps(safe(report), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    lines = ["# PIT Distribution Trap Validation", "", "Research-only. No production/main/UI/trading-rule changes.", "", f"- PIT window: {start.date()} to {end.date()}", f"- PIT sector snapshot min mapping: {sector_q['mapping_rate'].min():.2%}", f"- Daily PIT mapping min: {map_q['mapping_rate'].min():.2%}", f"- Decision: {'SURVIVES AS CONTEXT CANDIDATE' if accepted_research_context else 'REJECT'}", "", "## Confirmation 2024+ baseline P70 / Internal<50 / Flow<=0", "", "| Coverage | 20D | 40D |", "|---:|---:|---:|"]
    for cov in COVERAGE_LEVELS:
        vals = []
        for h in (20, 40):
            r = results[(results.coverage_level == cov) & (results.config == "P70_I50_F0") & (results.period == "CONFIRMATION_2024_PLUS") & (results.horizon == h)]
            vals.append("n/a" if r.empty or pd.isna(r.iloc[0].mean_excess) else f"{100*r.iloc[0].mean_excess:+.2f}% (n={int(r.iloc[0].n)})")
        lines.append(f"| {cov:.0%} | {vals[0]} | {vals[1]} |")
    lines += ["", "## Guardrails", "", "- Exact Fund Flow is official shares-outstanding-derived, not volume proxy.", "- Internal participation is point-in-time and equal-weight; current holdings are not backfilled.", "- State samples are transition events with 20-trading-day per-Sector cooldown.", "- All 27 nearby thresholds are retained; no best-cell promotion.", "- Any surviving result is context only, not a V38 Gate or forced exit."]
    (args.output / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"DONE PIT_DISTRIBUTION decision={accepted_research_context} rows={len(results)}", flush=True)


if __name__ == "__main__":
    main()
