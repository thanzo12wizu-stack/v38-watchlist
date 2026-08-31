from __future__ import annotations

import argparse
import io
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import rotation_exact_flow_research as flowlib
import validate_pioneer_leader as pl

SECTOR_ETFS = ["XLC", "XLY", "XLP", "XLE", "XLF", "XLV", "XLI", "XLB", "XLRE", "XLK", "XLU"]
HORIZONS = (5, 10, 20, 40)
COOLDOWN = 20
BOOT_REPS = 2500
DISCOVERY_END = pd.Timestamp("2023-12-31")
CONFIRM_START = pd.Timestamp("2024-01-01")
HOLDINGS_URL = "https://www.ssga.com/library-content/products/fund-data/etfs/us/holdings-daily-us-en-{ticker}.xlsx"


def safe(v: Any) -> Any:
    if isinstance(v, dict):
        return {str(k): safe(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [safe(x) for x in v]
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        x = float(v)
        return x if math.isfinite(x) else None
    if isinstance(v, pd.Timestamp):
        return v.isoformat()
    return v


def _norm_header(v: Any) -> str:
    return " ".join(str(v or "").strip().lower().split())


def _num(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(str(v).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def fetch_ssga_current_holdings(session: requests.Session, ticker: str) -> pd.DataFrame:
    url = HOLDINGS_URL.format(ticker=ticker.lower())
    r = session.get(url, headers={"User-Agent": flowlib.UA}, timeout=45)
    r.raise_for_status()
    matrix = pd.read_excel(io.BytesIO(r.content), sheet_name=0, header=None, engine="openpyxl")
    header_idx = None
    for idx, row in matrix.iterrows():
        headers = [_norm_header(x) for x in row.tolist()]
        if headers and headers[0] == "name" and "ticker" in headers and "weight" in headers:
            header_idx = idx
            break
    if header_idx is None:
        raise RuntimeError(f"{ticker}: holdings header not found")
    headers = [_norm_header(x) for x in matrix.iloc[header_idx].tolist()]
    cmap = {name: i for i, name in enumerate(headers) if name}
    rows: list[dict[str, Any]] = []
    for _, raw in matrix.iloc[header_idx + 1 :].iterrows():
        name = str(raw.iloc[cmap["name"]] if cmap.get("name") is not None else "").strip()
        if not name or name.lower() == "nan":
            break
        symbol = str(raw.iloc[cmap["ticker"]] if cmap.get("ticker") is not None else "").strip().upper()
        weight = _num(raw.iloc[cmap["weight"]]) if cmap.get("weight") is not None else None
        if not symbol or symbol.lower() == "nan" or weight is None or weight <= 0:
            continue
        if any(token in symbol for token in ("CASH", "USD", "SWAP")):
            continue
        if symbol in {ticker, "SPY"}:
            continue
        rows.append({"sector_etf": ticker, "symbol": symbol, "weight_pct": weight, "name": name, "source_url": url})
    out = pd.DataFrame(rows).drop_duplicates("symbol", keep="first")
    if len(out) < 5:
        raise RuntimeError(f"{ticker}: too few parsed equity holdings ({len(out)})")
    return out.sort_values("weight_pct", ascending=False).reset_index(drop=True)


def cross_section_rank(df: pd.DataFrame, *, min_count: int = 5) -> pd.DataFrame:
    ranks = df.rank(axis=1, pct=True, method="average") * 100.0
    valid = df.notna().sum(axis=1)
    return ranks.where(valid >= min_count, np.nan)


def coverage_guard(mask: pd.DataFrame, member_count: int, min_coverage: float) -> pd.Series:
    return mask.notna().sum(axis=1) >= max(5, int(math.ceil(member_count * min_coverage)))


def compute_internal_components(close: pd.DataFrame, volume: pd.DataFrame, members: list[str], min_coverage: float) -> pd.DataFrame:
    c = close.reindex(columns=members)
    v = volume.reindex(columns=members)
    n = len(members)

    ema21 = c.ewm(span=21, adjust=False, min_periods=15).mean()
    sma50 = c.rolling(50, min_periods=35).mean()

    b21_mask = (c > ema21).where(c.notna() & ema21.notna())
    b50_mask = (c > sma50).where(c.notna() & sma50.notna())
    b21 = 100.0 * b21_mask.mean(axis=1, skipna=True)
    b50 = 100.0 * b50_mask.mean(axis=1, skipna=True)
    b21 = b21.where(coverage_guard(b21_mask, n, min_coverage))
    b50 = b50.where(coverage_guard(b50_mask, n, min_coverage))

    ret = c.pct_change(fill_method=None)
    adv = (ret > 0).astype(float)
    dec = (ret < 0).astype(float)
    valid_ret = ret.notna()
    adv_count = adv.where(valid_ret).sum(axis=1, min_count=1)
    dec_count = dec.where(valid_ret).sum(axis=1, min_count=1)
    valid_count = valid_ret.sum(axis=1)
    ad_daily = ((adv_count - dec_count) / valid_count.replace(0, np.nan)).where(valid_count >= max(5, int(math.ceil(n * min_coverage))))
    ad20 = 50.0 * (1.0 + ad_daily.rolling(20, min_periods=15).mean())

    signed_volume = v.where(ret > 0, -v.where(ret < 0, 0.0)).where(valid_ret & v.notna())
    obv = signed_volume.fillna(0.0).cumsum()
    obv_delta20 = obv - obv.shift(20)
    obv_mask = (obv_delta20 > 0).where(obv_delta20.notna())
    obv_pos20 = 100.0 * obv_mask.mean(axis=1, skipna=True)
    obv_pos20 = obv_pos20.where(coverage_guard(obv_mask, n, min_coverage))

    up_vol = v.where(ret > 0, 0.0).where(valid_ret & v.notna()).sum(axis=1, min_count=1)
    down_vol = v.where(ret < 0, 0.0).where(valid_ret & v.notna()).sum(axis=1, min_count=1)
    vol_coverage = (valid_ret & v.notna()).sum(axis=1)
    up20 = up_vol.rolling(20, min_periods=15).sum()
    down20 = down_vol.rolling(20, min_periods=15).sum()
    uvdv20 = (up20 / down20.replace(0, np.nan)).where(vol_coverage.rolling(20, min_periods=15).median() >= max(5, int(math.ceil(n * min_coverage))))

    return pd.DataFrame({
        "breadth21": b21,
        "breadth50": b50,
        "ad20_score": ad20.clip(0, 100),
        "obv_positive20": obv_pos20,
        "updown_volume20": uvdv20,
    })


def build_panel(ohlcv: dict[str, pd.DataFrame], holdings: pd.DataFrame, exact_flows: pd.DataFrame, min_coverage: float) -> pd.DataFrame:
    close = ohlcv["close"]
    volume = ohlcv["volume"]
    if "SPY" not in close.columns:
        raise RuntimeError("SPY missing from OHLCV")
    missing_etfs = [t for t in SECTOR_ETFS if t not in close.columns]
    if missing_etfs:
        raise RuntimeError(f"sector ETF prices missing: {missing_etfs}")

    spy = close["SPY"]
    etf_close = close[SECTOR_ETFS]
    rel63 = etf_close.pct_change(63, fill_method=None).sub(spy.pct_change(63, fill_method=None), axis=0)
    rel189 = etf_close.pct_change(189, fill_method=None).sub(spy.pct_change(189, fill_method=None), axis=0)
    price63_rank = cross_section_rank(rel63)
    price189_rank = cross_section_rank(rel189)
    price_score = (price63_rank + price189_rank) / 2.0

    components: dict[str, dict[str, pd.Series]] = {}
    for etf in SECTOR_ETFS:
        members = holdings.loc[holdings["sector_etf"] == etf, "symbol"].tolist()
        members = [s for s in members if s in close.columns and s in volume.columns]
        if len(members) < 5:
            raise RuntimeError(f"{etf}: only {len(members)} holdings downloaded")
        comp = compute_internal_components(close, volume, members, min_coverage)
        components[etf] = {c: comp[c] for c in comp.columns}

    comp_names = ["breadth21", "breadth50", "ad20_score", "obv_positive20", "updown_volume20"]
    comp_rank: dict[str, pd.DataFrame] = {}
    for name in comp_names:
        wide = pd.DataFrame({etf: components[etf][name] for etf in SECTOR_ETFS})
        # All components are stronger when larger, so percentile rank direction is consistent.
        comp_rank[name] = cross_section_rank(wide)

    # No proposed 30/30/25/15 weights. Equal-median of independent cross-sectional ranks only.
    rank_stack = np.stack([comp_rank[name].to_numpy(float) for name in comp_names], axis=2)
    with np.errstate(all="ignore"):
        internal_score_arr = np.nanmedian(rank_stack, axis=2)
    internal_score = pd.DataFrame(internal_score_arr, index=close.index, columns=SECTOR_ETFS)
    internal_score = internal_score.where(sum(x.notna().astype(int) for x in comp_rank.values()) >= 4)
    internal_delta20 = internal_score - internal_score.shift(20)

    flow = exact_flows.copy()
    flow["date"] = pd.to_datetime(flow["date"]).dt.normalize()
    flow = flow[flow["ticker"].isin(SECTOR_ETFS)].copy()
    flow = flow.drop_duplicates(["date", "ticker"], keep="last")
    flow20 = flow.pivot(index="date", columns="ticker", values="flow_20d_pct_aum").reindex(columns=SECTOR_ETFS)

    rows: list[pd.DataFrame] = []
    for etf in SECTOR_ETFS:
        frame = pd.DataFrame(index=close.index)
        frame["sector"] = etf
        frame["price_score"] = price_score[etf]
        frame["price_rs63_rank"] = price63_rank[etf]
        frame["price_rs189_rank"] = price189_rank[etf]
        frame["internal_score"] = internal_score[etf]
        frame["internal_delta20"] = internal_delta20[etf]
        for name in comp_names:
            frame[f"{name}_rank"] = comp_rank[name][etf]
            frame[name] = components[etf][name]
        frame["flow20_pct_aum"] = flow20[etf].reindex(frame.index)
        frame["etf_close"] = etf_close[etf]
        frame["spy_close"] = spy
        frame["date"] = frame.index
        for h in HORIZONS:
            frame[f"fwd_excess_{h}d"] = (etf_close[etf].shift(-h) / etf_close[etf] - 1.0) - (spy.shift(-h) / spy - 1.0)
        rows.append(frame.reset_index(drop=True))
    return pd.concat(rows, ignore_index=True).sort_values(["date", "sector"]).reset_index(drop=True)


def state_mask(df: pd.DataFrame, state: str, p: float, i: float, f: float, delta: float = 10.0) -> pd.Series:
    price = df["price_score"]
    internal = df["internal_score"]
    flow = df["flow20_pct_aum"]
    if state == "CONFIRMED_ACCUMULATION":
        return (price >= p) & (internal >= i) & (flow >= f)
    if state == "HIDDEN_ACCUMULATION":
        return (price < p) & (internal >= i) & (flow >= f)
    if state == "DISTRIBUTION_TRAP":
        return (price >= p) & (internal < i) & (flow <= -f)
    if state == "REDEMPTION_DIVERGENCE":
        return (price >= p) & (internal >= i) & (flow <= -f)
    if state == "EARLY_ROTATION":
        return (price < p) & (internal >= i) & (df["internal_delta20"] >= delta) & (flow >= f)
    raise ValueError(state)


def eventize(panel: pd.DataFrame, mask: pd.Series, state: str, config: str) -> pd.DataFrame:
    use = panel[["date", "sector", *[f"fwd_excess_{h}d" for h in HORIZONS]]].copy()
    use["active"] = mask.fillna(False).to_numpy(bool)
    events: list[dict[str, Any]] = []
    for sector, grp in use.groupby("sector", sort=False):
        grp = grp.sort_values("date")
        last_accepted = -10_000
        prev = False
        for pos, row in enumerate(grp.itertuples(index=False)):
            active = bool(row.active)
            if active and not prev and pos - last_accepted >= COOLDOWN:
                rec = {"date": pd.Timestamp(row.date), "sector": sector, "state": state, "config": config}
                for h in HORIZONS:
                    rec[f"fwd_excess_{h}d"] = getattr(row, f"fwd_excess_{h}d")
                events.append(rec)
                last_accepted = pos
            prev = active
    return pd.DataFrame(events)


def trading_block_ids(dates: pd.Series, calendar: pd.DatetimeIndex, block_len: int = 20) -> np.ndarray:
    pos = pd.Series(np.arange(len(calendar)), index=calendar)
    ix = pos.reindex(pd.to_datetime(dates)).to_numpy(float)
    return np.floor(ix / block_len).astype(np.int64)


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
    return [float(x) for x in np.quantile(vals, [0.025, 0.975])]


def summarize_events(events: pd.DataFrame, calendar: pd.DatetimeIndex, seed: int) -> dict[str, Any]:
    if events.empty:
        return {"n": 0}
    ev = events.copy()
    ev["block20"] = trading_block_ids(ev["date"], calendar)
    out: dict[str, Any] = {"n": int(len(ev)), "dates": int(ev["date"].nunique()), "sectors": int(ev["sector"].nunique()), "horizons": {}}
    for j, h in enumerate(HORIZONS):
        col = f"fwd_excess_{h}d"
        x = pd.to_numeric(ev[col], errors="coerce")
        finite = ev[np.isfinite(x.to_numpy(float))].copy()
        if finite.empty:
            out["horizons"][str(h)] = {"n": 0}
            continue
        vals = finite[col].astype(float)
        out["horizons"][str(h)] = {
            "n": int(len(vals)),
            "mean": float(vals.mean()),
            "median": float(vals.median()),
            "positive_rate": float((vals > 0).mean()),
            "block20_ci95": cluster_boot_mean(finite, col, "block20", seed + j * 100),
            "sector_cluster_ci95": cluster_boot_mean(finite, col, "sector", seed + 1000 + j * 100),
        }
    return out


def period_splits(events: pd.DataFrame) -> dict[str, pd.DataFrame]:
    if events.empty:
        return {"ALL_2022_PLUS": events, "DISCOVERY_2022_2023": events, "CONFIRMATION_2024_PLUS": events}
    d = pd.to_datetime(events["date"])
    return {
        "ALL_2022_PLUS": events[d >= pd.Timestamp("2022-01-01")],
        "DISCOVERY_2022_2023": events[(d >= pd.Timestamp("2022-01-01")) & (d <= DISCOVERY_END)],
        "CONFIRMATION_2024_PLUS": events[d >= CONFIRM_START],
    }


def grid_configs(state: str) -> list[dict[str, float]]:
    configs: list[dict[str, float]] = []
    flow_cuts = (0.0, 0.5, 1.0)
    if state == "CONFIRMED_ACCUMULATION":
        for p in (65.0, 70.0, 75.0):
            for i in (55.0, 60.0, 65.0):
                for f in flow_cuts:
                    configs.append({"p": p, "i": i, "f": f, "delta": 0.0})
    elif state == "HIDDEN_ACCUMULATION":
        for p in (55.0, 60.0, 65.0):
            for i in (55.0, 60.0, 65.0):
                for f in flow_cuts:
                    configs.append({"p": p, "i": i, "f": f, "delta": 0.0})
    elif state == "DISTRIBUTION_TRAP":
        for p in (65.0, 70.0, 75.0):
            for i in (45.0, 50.0, 55.0):
                for f in flow_cuts:
                    configs.append({"p": p, "i": i, "f": f, "delta": 0.0})
    elif state == "REDEMPTION_DIVERGENCE":
        for p in (60.0, 65.0, 70.0):
            for i in (55.0, 60.0, 65.0):
                for f in flow_cuts:
                    configs.append({"p": p, "i": i, "f": f, "delta": 0.0})
    elif state == "EARLY_ROTATION":
        for p in (55.0, 60.0, 65.0):
            for i in (50.0, 55.0, 60.0):
                for delta in (5.0, 10.0, 15.0):
                    configs.append({"p": p, "i": i, "f": 0.0, "delta": delta})
    else:
        raise ValueError(state)
    return configs


def baseline_config(state: str) -> dict[str, float]:
    return {
        "CONFIRMED_ACCUMULATION": {"p": 70.0, "i": 60.0, "f": 0.0, "delta": 0.0},
        "HIDDEN_ACCUMULATION": {"p": 60.0, "i": 60.0, "f": 0.0, "delta": 0.0},
        "DISTRIBUTION_TRAP": {"p": 70.0, "i": 50.0, "f": 0.0, "delta": 0.0},
        "REDEMPTION_DIVERGENCE": {"p": 60.0, "i": 60.0, "f": 0.0, "delta": 0.0},
        "EARLY_ROTATION": {"p": 60.0, "i": 50.0, "f": 0.0, "delta": 10.0},
    }[state]


def config_key(c: dict[str, float]) -> str:
    return f"p{c['p']:.0f}_i{c['i']:.0f}_f{c['f']:.1f}_d{c['delta']:.0f}"


def main() -> None:
    ap = argparse.ArgumentParser(description="Research-only Sector Rotation divergence backtest using exact ETF flows + fixed-current-holdings internal proxy")
    ap.add_argument("--output", type=Path, default=Path("leadership/research/rotation_divergence_proxy_outputs"))
    ap.add_argument("--analysis-start", default="2022-01-03")
    ap.add_argument("--analysis-end", default="2026-08-31")
    ap.add_argument("--download-start", default="2021-01-01")
    ap.add_argument("--batch-size", type=int, default=75)
    ap.add_argument("--min-coverage", type=float, default=0.60)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    holdings_frames = []
    for etf in SECTOR_ETFS:
        h = fetch_ssga_current_holdings(session, etf)
        print(f"HOLDINGS {etf}: {len(h)}", flush=True)
        holdings_frames.append(h)
    holdings = pd.concat(holdings_frames, ignore_index=True)
    holdings.to_csv(args.output / "current_holdings_proxy.csv", index=False)

    symbols = sorted(set(holdings["symbol"].tolist()) | set(SECTOR_ETFS) | {"SPY"})
    ohlcv, download_diag = pl.download_ohlcv(symbols, args.download_start, str((pd.Timestamp(args.analysis_end) + pd.Timedelta(days=5)).date()), args.batch_size)
    downloaded = set(ohlcv["close"].columns)
    holdings["downloaded"] = holdings["symbol"].isin(downloaded)
    coverage = holdings.groupby("sector_etf").agg(current_members=("symbol", "nunique"), downloaded_members=("downloaded", "sum")).reset_index()
    coverage["download_coverage"] = coverage["downloaded_members"] / coverage["current_members"]
    coverage.to_csv(args.output / "holdings_download_coverage.csv", index=False)
    if (coverage["download_coverage"] < args.min_coverage).any():
        bad = coverage[coverage["download_coverage"] < args.min_coverage].to_dict("records")
        raise RuntimeError(f"holdings download coverage below guard: {bad}")

    flow_frames = []
    flow_diag = []
    for etf in SECTOR_ETFS:
        series = flowlib.fetch_ssga_nav_history(session, etf)
        flow_df, diag = flowlib.derive_exact_flows(series)
        flow_frames.append(flow_df)
        flow_diag.append(diag)
    exact_flows = pd.concat(flow_frames, ignore_index=True)

    panel = build_panel(ohlcv, holdings[holdings["downloaded"]].copy(), exact_flows, args.min_coverage)
    start = pd.Timestamp(args.analysis_start)
    end = pd.Timestamp(args.analysis_end)
    panel = panel[(panel["date"] >= start) & (panel["date"] <= end)].copy()
    panel.to_csv(args.output / "rotation_proxy_panel.csv", index=False, date_format="%Y-%m-%d")
    calendar = pd.DatetimeIndex(sorted(panel["date"].unique()))

    states = ["CONFIRMED_ACCUMULATION", "HIDDEN_ACCUMULATION", "DISTRIBUTION_TRAP", "REDEMPTION_DIVERGENCE", "EARLY_ROTATION"]
    report: dict[str, Any] = {
        "schema": 1,
        "research_only": True,
        "internal_quality": "PROXY_RESEARCH_ONLY_FIXED_CURRENT_HOLDINGS",
        "flow_quality": "EXACT_OFFICIAL_SHARES_OUTSTANDING_DERIVED",
        "warning": "Current SSGA sector ETF holdings are retrospectively applied to 2022-2026. This creates survivorship/taxonomy look-ahead risk. A positive result requires PIT confirmation before adoption; a negative result is sufficient to deprioritize the hypothesis.",
        "internal_composite": "Equal-median of cross-sectional percentile ranks for Breadth21, Breadth50, 20d A/D balance, percent constituents with positive 20d OBV delta, and 20d aggregate up/down volume ratio. No 30/30/25/15 weights.",
        "periods": {"discovery": "2022-01-01..2023-12-31", "confirmation": "2024-01-01..latest"},
        "coverage": {"holdings": coverage.to_dict("records"), "download": download_diag, "flow": flow_diag},
        "states": {},
    }

    sensitivity_rows: list[dict[str, Any]] = []
    baseline_events_all: list[pd.DataFrame] = []
    for si, state in enumerate(states):
        print(f"STATE {state}", flush=True)
        state_out: dict[str, Any] = {"baseline": {}, "sensitivity": {}}
        base_cfg = baseline_config(state)
        for ci, cfg in enumerate(grid_configs(state)):
            key = config_key(cfg)
            mask = state_mask(panel, state, cfg["p"], cfg["i"], cfg["f"], cfg["delta"])
            events = eventize(panel, mask, state, key)
            is_baseline = cfg == base_cfg
            if is_baseline and not events.empty:
                baseline_events_all.append(events)
            for period_name, period_events in period_splits(events).items():
                summary = summarize_events(period_events, calendar, seed=10000 + si * 1000 + ci * 10)
                state_out["sensitivity"].setdefault(key, {})[period_name] = summary
                for h in HORIZONS:
                    hs = summary.get("horizons", {}).get(str(h), {})
                    sensitivity_rows.append({
                        "state": state, "config": key, "period": period_name, "horizon": h,
                        "p": cfg["p"], "i": cfg["i"], "flow_cut_pct_aum": cfg["f"], "delta": cfg["delta"],
                        "n": hs.get("n", 0), "mean_excess": hs.get("mean"), "median_excess": hs.get("median"),
                        "positive_rate": hs.get("positive_rate"),
                        "block_ci_lo": (hs.get("block20_ci95") or [None, None])[0],
                        "block_ci_hi": (hs.get("block20_ci95") or [None, None])[1],
                    })
            if is_baseline:
                state_out["baseline"] = {"config": key, "thresholds": cfg, "periods": state_out["sensitivity"][key]}
        report["states"][state] = state_out

    sensitivity = pd.DataFrame(sensitivity_rows)
    sensitivity.to_csv(args.output / "rotation_state_sensitivity.csv", index=False)
    if baseline_events_all:
        pd.concat(baseline_events_all, ignore_index=True).sort_values(["date", "state", "sector"]).to_csv(args.output / "baseline_state_events.csv", index=False, date_format="%Y-%m-%d")

    robustness: dict[str, Any] = {}
    expected = {"CONFIRMED_ACCUMULATION": 1, "HIDDEN_ACCUMULATION": 1, "DISTRIBUTION_TRAP": -1, "EARLY_ROTATION": 1}
    for state in states:
        robust_state: dict[str, Any] = {}
        for h in HORIZONS:
            sub = sensitivity[(sensitivity["state"] == state) & (sensitivity["horizon"] == h)]
            per: dict[str, Any] = {}
            for period in ("DISCOVERY_2022_2023", "CONFIRMATION_2024_PLUS"):
                x = sub[sub["period"] == period].copy()
                vals = pd.to_numeric(x["mean_excess"], errors="coerce").dropna()
                sig_expected = None
                sign = expected.get(state)
                if sign is not None and not x.empty:
                    if sign > 0:
                        sig_expected = float((pd.to_numeric(x["block_ci_lo"], errors="coerce") > 0).mean())
                    else:
                        sig_expected = float((pd.to_numeric(x["block_ci_hi"], errors="coerce") < 0).mean())
                per[period] = {
                    "configs_with_result": int(len(vals)),
                    "median_mean_excess": float(vals.median()) if len(vals) else None,
                    "fraction_positive": float((vals > 0).mean()) if len(vals) else None,
                    "fraction_negative": float((vals < 0).mean()) if len(vals) else None,
                    "fraction_block_ci_expected_sign": sig_expected,
                }
            robust_state[str(h)] = per
        robustness[state] = robust_state
    report["robustness"] = robustness

    (args.output / "rotation_divergence_proxy_report.json").write_text(json.dumps(safe(report), ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Rotation Divergence Proxy Backtest", "",
        "**Research only. Current holdings are retrospectively applied; internals are PROXY_RESEARCH_ONLY. Exact ETF flow is reconstructed from official SSGA daily NAV + shares outstanding.**", "",
        "No 30/30/25/15 internal weights are used.", "",
        "## Baseline results", "",
        "| State | Period | 5D | 10D | 20D | 40D |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for state in states:
        base = report["states"][state]["baseline"]
        if not base:
            continue
        for period in ("DISCOVERY_2022_2023", "CONFIRMATION_2024_PLUS"):
            p = base["periods"].get(period, {})
            vals = []
            for h in HORIZONS:
                hs = p.get("horizons", {}).get(str(h), {})
                mean = hs.get("mean")
                n = hs.get("n", 0)
                vals.append("n/a" if mean is None else f"{100*mean:+.2f}% (n={n})")
            lines.append(f"| {state} | {period} | " + " | ".join(vals) + " |")
    lines += ["", "## Interpretation guardrails", "", "- Positive proxy results are not adoption evidence; they require point-in-time constituent confirmation.", "- Negative proxy results are useful for killing weak hypotheses early.", "- Threshold grids are reported in full; no best-cell cherry-pick is promoted.", "- Sector/Theme Rotation remains context only and does not alter V38 stock ranking, entries, exits, or Market Mode."]
    (args.output / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"DONE panel={len(panel)} sensitivity_rows={len(sensitivity)}", flush=True)


if __name__ == "__main__":
    main()
