from __future__ import annotations

import argparse
import csv
import io
import json
import math
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests

import rotation_divergence_proxy_backtest as proxy
import rotation_exact_flow_research as flowlib
import rotation_macro_why_qa as macroqa
import validate_pioneer_leader as pl

SECTORS = ["XLC", "XLY", "XLP", "XLE", "XLF", "XLV", "XLI", "XLB", "XLRE", "XLK", "XLU"]
INDUSTRIES = ["XBI", "XME", "SOXX", "IGV"]
MATRIX_ETFS = SECTORS + INDUSTRIES
PROVIDERS = {**{x: "SSGA" for x in SECTORS + ["XBI", "XME"]}, "SOXX": "ISHARES", "IGV": "ISHARES"}
ISHARES_FUNDS = {
    "SOXX": {"product_id": "239705", "slug": "ishares-semiconductor-etf"},
    "IGV": {"product_id": "239771", "slug": "ishares-expanded-techsoftware-sector-etf"},
}
COMPONENTS = ["breadth21", "breadth50", "ad20_score", "obv_positive20", "updown_volume20"]


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


def num(v: Any) -> float | None:
    if v is None:
        return None
    try:
        x = float(str(v).replace(",", "").replace("%", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def fetch_ishares_current_holdings(session: requests.Session, ticker: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    meta = ISHARES_FUNDS[ticker]
    url = f"https://www.ishares.com/us/products/{meta['product_id']}/{meta['slug']}/latest-holdings.csv"
    r = session.get(url, headers={"User-Agent": flowlib.UA, "Accept": "text/csv,*/*"}, timeout=45)
    r.raise_for_status()
    text = r.content.decode("utf-8-sig", errors="replace").lstrip("\ufeff")
    lines = text.splitlines()
    reported_asof = None
    for line in lines[:20]:
        if "Fund Holdings as of" in line:
            parts = next(csv.reader([line]))
            if len(parts) >= 2:
                reported_asof = parts[1].strip()
            break
    header_idx = next((i for i, line in enumerate(lines) if line.lower().startswith("ticker,") and "asset class" in line.lower()), None)
    if header_idx is None:
        raise RuntimeError(f"{ticker}: iShares holdings header missing")
    rows = []
    reader = csv.DictReader(io.StringIO("\n".join(lines[header_idx:])))
    for row in reader:
        symbol = (row.get("Ticker") or "").strip().upper()
        asset = (row.get("Asset Class") or "").strip().lower()
        if not symbol or asset != "equity":
            continue
        weight = None
        for key in ("Weight (%)", "Weight", "% of Net Assets", "Market Value Weight"):
            if key in row:
                weight = num(row.get(key))
                if weight is not None:
                    break
        rows.append({
            "sector_etf": ticker,
            "symbol": symbol,
            "weight_pct": weight,
            "name": (row.get("Name") or "").strip(),
            "source_url": url,
        })
    out = pd.DataFrame(rows).drop_duplicates("symbol", keep="first")
    if len(out) < 5:
        raise RuntimeError(f"{ticker}: only {len(out)} equity holdings parsed")
    return out.reset_index(drop=True), {"ticker": ticker, "source": "official iShares latest-holdings.csv", "reported_asof": reported_asof, "rows": len(out), "quality": "EXACT_CURRENT_MEMBERSHIP"}


def fetch_all_holdings(session: requests.Session) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    frames = []
    diag = []
    for ticker in MATRIX_ETFS:
        if PROVIDERS[ticker] == "SSGA":
            h = proxy.fetch_ssga_current_holdings(session, ticker)
            frames.append(h)
            diag.append({"ticker": ticker, "source": "official State Street daily holdings", "reported_asof": None, "rows": len(h), "quality": "EXACT_CURRENT_MEMBERSHIP"})
        else:
            h, d = fetch_ishares_current_holdings(session, ticker)
            frames.append(h)
            diag.append(d)
        print(f"LIVE_HOLDINGS {ticker}: {len(frames[-1])}", flush=True)
    return pd.concat(frames, ignore_index=True), diag


def weekly_rsi14(close: pd.Series) -> pd.Series:
    w = close.dropna().resample("W-FRI").last().dropna()
    delta = w.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    avg_loss = loss.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def rank_price(close: pd.DataFrame, tickers: list[str]) -> dict[str, pd.DataFrame]:
    spy = close["SPY"]
    etf = close[tickers]
    rel63 = etf.pct_change(63, fill_method=None).sub(spy.pct_change(63, fill_method=None), axis=0)
    rel189 = etf.pct_change(189, fill_method=None).sub(spy.pct_change(189, fill_method=None), axis=0)
    r63 = proxy.cross_section_rank(rel63, min_count=max(5, len(tickers) // 2))
    r189 = proxy.cross_section_rank(rel189, min_count=max(5, len(tickers) // 2))
    return {"rs63": rel63, "rs189": rel189, "rs63_rank": r63, "rs189_rank": r189, "price_score": (r63 + r189) / 2.0}


def build_internal(ohlcv: dict[str, pd.DataFrame], holdings: pd.DataFrame, tickers: list[str], min_source_coverage: float) -> tuple[dict[str, pd.DataFrame], pd.DataFrame, pd.DataFrame, list[dict[str, Any]]]:
    close, volume = ohlcv["close"], ohlcv["volume"]
    raw: dict[str, dict[str, pd.Series]] = {}
    diagnostics = []
    for ticker in tickers:
        source_members = holdings.loc[holdings.sector_etf == ticker, "symbol"].astype(str).tolist()
        downloaded = [s for s in source_members if s in close.columns and s in volume.columns and close[s].notna().sum() >= 80]
        source_cov = len(downloaded) / len(source_members) if source_members else 0.0
        diagnostics.append({"ticker": ticker, "source_members": len(source_members), "downloaded_members": len(downloaded), "source_member_coverage": source_cov})
        if len(downloaded) < 5 or source_cov < min_source_coverage:
            raw[ticker] = {name: pd.Series(index=close.index, dtype=float) for name in COMPONENTS}
            continue
        comp = proxy.compute_internal_components(close, volume, downloaded, min_source_coverage)
        raw[ticker] = {name: comp[name] for name in COMPONENTS}

    ranks: dict[str, pd.DataFrame] = {}
    raw_wide: dict[str, pd.DataFrame] = {}
    for name in COMPONENTS:
        wide = pd.DataFrame({ticker: raw[ticker][name] for ticker in tickers}, index=close.index)
        raw_wide[name] = wide
        ranks[name] = proxy.cross_section_rank(wide, min_count=max(5, len(tickers) // 2))
    stack = np.stack([ranks[n].to_numpy(float) for n in COMPONENTS], axis=2)
    with np.errstate(all="ignore"):
        arr = np.nanmedian(stack, axis=2)
    score = pd.DataFrame(arr, index=close.index, columns=tickers)
    score = score.where(sum(x.notna().astype(int) for x in ranks.values()) >= 4)
    delta20 = score - score.shift(20)
    flattened = {f"{name}_rank": ranks[name] for name in COMPONENTS}
    flattened.update(raw_wide)
    return flattened, score, delta20, diagnostics


def fetch_exact_flows(session: requests.Session, close: pd.DataFrame) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    ishares_ids = flowlib.resolve_ishares_portfolio_ids(session, [x for x in INDUSTRIES if PROVIDERS[x] == "ISHARES"])
    frames = []
    diag = []
    for ticker in MATRIX_ETFS:
        if PROVIDERS[ticker] == "SSGA":
            series = flowlib.fetch_ssga_nav_history(session, ticker)
        else:
            pid = ishares_ids.get(ticker)
            if pid is None:
                raise RuntimeError(f"{ticker}: iShares portfolioId missing")
            series = flowlib.fetch_ishares_nav_history(session, ticker, pid)
        raw, d = flowlib.derive_exact_flows(series)
        trading_dates = pd.DatetimeIndex(close[ticker].dropna().index)
        x = pd.DataFrame({"date": trading_dates}).merge(raw[["date", "nav", "shares_outstanding", "aum", "flow_usd", "provider", "source_url"]], on="date", how="left")
        x["ticker"] = ticker
        x["flow_1d"] = x["flow_usd"]
        x["flow_5d"] = x["flow_usd"].rolling(5, min_periods=5).sum()
        x["flow_20d"] = x["flow_usd"].rolling(20, min_periods=20).sum()
        x["flow_20d_pct_aum"] = 100.0 * x["flow_20d"] / x["aum"]
        frames.append(x)
        d["normalized_to_actual_etf_trading_days"] = True
        diag.append(d)
        print(f"LIVE_FLOW {ticker}: {x['flow_1d'].notna().sum()}", flush=True)
    return pd.concat(frames, ignore_index=True), diag


def latest_scalar(series: pd.Series) -> float | None:
    x = pd.to_numeric(series, errors="coerce").dropna()
    return None if x.empty else float(x.iloc[-1])


def classify_state(row: dict[str, Any], *, validated_sector: bool) -> tuple[str, str]:
    p = row.get("validated_price_score") if validated_sector else row.get("matrix_price_score")
    i = row.get("validated_internal_score") if validated_sector else row.get("matrix_internal_score")
    d = row.get("validated_internal_delta20") if validated_sector else row.get("matrix_internal_delta20")
    f = row.get("flow_20d_pct_aum")
    if any(x is None for x in (p, i, f)):
        return "DATA_REQUIRED", "price/internal/flowのいずれかが不足"
    if validated_sector and p >= 70 and i < 50 and f <= 0:
        return "DISTRIBUTION_WARNING", "PIT検証済みSector条件: Price>=70・Internal<50・20D Flow<=0"
    if p >= 60 and i >= 60 and f < 0:
        return "REDEMPTION_DIVERGENCE", "価格・内部は強いがETF Flowは流出。売り抜けと断定しない"
    if p >= 70 and i >= 60:
        return "CURRENT_STRENGTH", "価格・内部が同時に強い現在状態。将来Alphaは主張しない"
    if p < 60 and i >= 50 and d is not None and d >= 10 and f >= 0:
        return "EARLY_ROTATION_WATCH", "内部改善とFlow流入が価格に先行。PIT検証では買いシグナル不採用"
    if p < 45 and i < 45:
        return "WEAK_BREAKDOWN", "価格・内部がともに弱い"
    return "MIXED_HOLD", "方向不一致または閾値未達"


def macro_snapshot(session: requests.Session, ohlcv: dict[str, pd.DataFrame]) -> dict[str, Any]:
    fred = {}
    for s in macroqa.FRED_SERIES:
        df, err = macroqa.fetch_fred(session, s, "2024-01-01", str(date.today()))
        if df is None:
            fred[s] = {"quality": "DATA_REQUIRED", "error": err}
            continue
        valid = df.dropna(subset=[s])
        fred[s] = {"quality": "EXACT_OFFICIAL_FRED", "asof": None if valid.empty else str(valid.date.iloc[-1].date()), "value": None if valid.empty else float(valid[s].iloc[-1]), "change_20obs": None if len(valid) < 21 else float(valid[s].iloc[-1] - valid[s].iloc[-21])}
    cnn, err = macroqa.fetch_json(session, macroqa.CNN_CURRENT)
    ctab = macroqa.current_cnn_table(cnn)
    components = []
    if not ctab.empty:
        for r in ctab.to_dict("records"):
            components.append({"component": r["component"], "score": num(r["score"]), "rating": r.get("rating")})
    fearish = [x for x in components if x["component"] != "fear_and_greed" and str(x.get("rating") or "").lower() in {"fear", "extreme fear"}]
    greedish = [x for x in components if x["component"] != "fear_and_greed" and str(x.get("rating") or "").lower() in {"greed", "extreme greed"}]
    headline = next((x for x in components if x["component"] == "fear_and_greed"), None)
    vix = latest_scalar(ohlcv["close"]["^VIX"]) if "^VIX" in ohlcv["close"].columns else None
    return {
        "fred": fred,
        "vix": {"quality": "MARKET_PRICE_SERIES" if vix is not None else "DATA_REQUIRED", "value": vix},
        "fear_greed": {"quality": "EXACT_CNN_COMPONENTS" if err is None and len(components) == 8 else "DATA_REQUIRED", "headline": headline, "components": components, "split": bool(fearish and greedish), "fear_components": [x["component"] for x in fearish], "greed_components": [x["component"] for x in greedish]},
        "dxy": {"quality": "DATA_REQUIRED", "note": "DXYは安定取得契約未確定。FRB Broad DollarをDXYとは表示しない"},
    }


def build_observations(matrix: list[dict[str, Any]], macro: dict[str, Any]) -> list[dict[str, str]]:
    obs: list[dict[str, str]] = []
    usable = [r for r in matrix if r.get("flow_20d_usd") is not None]
    leaders = sorted(usable, key=lambda x: x["flow_20d_usd"], reverse=True)[:4]
    laggards = sorted(usable, key=lambda x: x["flow_20d_usd"])[:4]
    if leaders:
        obs.append({"type": "FLOW_LEADERS", "text": "20D Flow流入上位: " + " / ".join(f"{x['ticker']} {x['flow_20d_usd']/1e6:+.0f}M" for x in leaders)})
    if laggards:
        obs.append({"type": "FLOW_LAGGARDS", "text": "20D Flow流出上位: " + " / ".join(f"{x['ticker']} {x['flow_20d_usd']/1e6:+.0f}M" for x in laggards)})
    distributions = [r for r in matrix if r.get("state") == "DISTRIBUTION_WARNING"]
    if distributions:
        obs.append({"type": "DISTRIBUTION", "text": "PIT検証済み分配警戒: " + " / ".join(x["ticker"] for x in distributions)})
    redemptions = [r for r in matrix if r.get("state") == "REDEMPTION_DIVERGENCE"]
    if redemptions:
        obs.append({"type": "REDEMPTION_DIVERGENCE", "text": "Flow流出でも内部強: " + " / ".join(x["ticker"] for x in redemptions)})
    watches = [r for r in matrix if r.get("state") == "EARLY_ROTATION_WATCH"]
    if watches:
        obs.append({"type": "WATCH", "text": "内部先行WATCH（買いシグナルではない）: " + " / ".join(x["ticker"] for x in watches)})
    fg = macro.get("fear_greed", {})
    if fg.get("split"):
        obs.append({"type": "FEAR_GREED_SPLIT", "text": "Fear & Greed内部は分裂: Fear=" + ",".join(fg.get("fear_components", [])) + " / Greed=" + ",".join(fg.get("greed_components", []))})
    return obs


def main() -> None:
    ap = argparse.ArgumentParser(description="Research-only live Sector/Industry Rotation snapshot")
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--history", type=Path)
    ap.add_argument("--download-start", default="2025-01-01")
    ap.add_argument("--download-end", default="2026-09-02")
    ap.add_argument("--min-source-coverage", type=float, default=0.80)
    ap.add_argument("--batch-size", type=int, default=75)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    session = requests.Session()

    holdings, holdings_diag = fetch_all_holdings(session)
    symbols = sorted(set(holdings.symbol.astype(str)) | set(MATRIX_ETFS) | {"SPY", "^VIX"})
    ohlcv, dl_diag = pl.download_ohlcv(symbols, args.download_start, args.download_end, args.batch_size)
    close = ohlcv["close"]
    for ticker in ["SPY", *MATRIX_ETFS]:
        if ticker not in close.columns or close[ticker].dropna().empty:
            raise RuntimeError(f"required ETF price missing: {ticker}")

    flows, flow_diag = fetch_exact_flows(session, close)
    matrix_price = rank_price(close, MATRIX_ETFS)
    sector_price = rank_price(close, SECTORS)
    matrix_comp, matrix_internal, matrix_delta20, matrix_int_diag = build_internal(ohlcv, holdings, MATRIX_ETFS, args.min_source_coverage)
    sector_comp, sector_internal, sector_delta20, sector_int_diag = build_internal(ohlcv, holdings, SECTORS, args.min_source_coverage)

    common_dates = close[MATRIX_ETFS].dropna(how="all").index
    asof = pd.Timestamp(common_dates.max()).normalize()
    flow_latest = flows[flows.date <= asof].sort_values("date").groupby("ticker", as_index=False).tail(1).set_index("ticker")
    matrix_rows = []
    for ticker in MATRIX_ETFS:
        c = close[ticker]
        last_close = latest_scalar(c.loc[:asof])
        ema21 = latest_scalar(c.ewm(span=21, adjust=False, min_periods=15).mean().loc[:asof])
        sma50 = latest_scalar(c.rolling(50, min_periods=35).mean().loc[:asof])
        high20 = latest_scalar(c.rolling(20, min_periods=15).max().loc[:asof])
        wrsi = weekly_rsi14(c.loc[:asof])
        flowrow = flow_latest.loc[ticker] if ticker in flow_latest.index else None
        row: dict[str, Any] = {
            "asof": str(asof.date()), "ticker": ticker, "level": "SECTOR" if ticker in SECTORS else "INDUSTRY",
            "close": last_close, "weekly_rsi14": latest_scalar(wrsi),
            "above_21ema": None if last_close is None or ema21 is None else bool(last_close > ema21),
            "above_50ma": None if last_close is None or sma50 is None else bool(last_close > sma50),
            "distance_20d_high_pct": None if last_close is None or high20 in (None, 0) else 100.0 * (last_close / high20 - 1.0),
            "rs63_vs_spy": latest_scalar(matrix_price["rs63"][ticker].loc[:asof]), "rs189_vs_spy": latest_scalar(matrix_price["rs189"][ticker].loc[:asof]),
            "matrix_price_score": latest_scalar(matrix_price["price_score"][ticker].loc[:asof]), "matrix_internal_score": latest_scalar(matrix_internal[ticker].loc[:asof]), "matrix_internal_delta20": latest_scalar(matrix_delta20[ticker].loc[:asof]),
            "validated_price_score": latest_scalar(sector_price["price_score"][ticker].loc[:asof]) if ticker in SECTORS else None,
            "validated_internal_score": latest_scalar(sector_internal[ticker].loc[:asof]) if ticker in SECTORS else None,
            "validated_internal_delta20": latest_scalar(sector_delta20[ticker].loc[:asof]) if ticker in SECTORS else None,
            "flow_1d_usd": None if flowrow is None or pd.isna(flowrow.flow_1d) else float(flowrow.flow_1d),
            "flow_5d_usd": None if flowrow is None or pd.isna(flowrow.flow_5d) else float(flowrow.flow_5d),
            "flow_20d_usd": None if flowrow is None or pd.isna(flowrow.flow_20d) else float(flowrow.flow_20d),
            "flow_20d_pct_aum": None if flowrow is None or pd.isna(flowrow.flow_20d_pct_aum) else float(flowrow.flow_20d_pct_aum),
            "flow_asof": None if flowrow is None else str(pd.Timestamp(flowrow.date).date()), "flow_quality": "EXACT_OFFICIAL_SHARES_OUTSTANDING_DERIVED",
            "internal_membership_quality": "EXACT_CURRENT_MEMBERSHIP", "internal_trend_history_quality": "CURRENT_HOLDINGS_BACKCAST_PROXY_UNTIL_LIVE_HISTORY_MATURES",
        }
        comp_source = sector_comp if ticker in SECTORS else matrix_comp
        for name in COMPONENTS:
            row[name] = latest_scalar(comp_source[name][ticker].loc[:asof]) if name in comp_source else None
            row[f"{name}_rank"] = latest_scalar(comp_source[f"{name}_rank"][ticker].loc[:asof]) if f"{name}_rank" in comp_source else None
        state, reason = classify_state(row, validated_sector=ticker in SECTORS)
        row["state"] = state
        row["state_reason"] = reason
        row["state_evidence"] = "PIT_VALIDATED_2024PLUS_SECTOR_CONTEXT" if state == "DISTRIBUTION_WARNING" else "DESCRIPTIVE_NOT_TRADING_SIGNAL"
        matrix_rows.append(row)

    macro = macro_snapshot(session, ohlcv)
    observations = build_observations(matrix_rows, macro)
    report = {
        "schema": 1, "research_only": True, "asof": str(asof.date()), "matrix": matrix_rows, "macro_why": macro, "observations": observations,
        "source_quality": {"holdings": holdings_diag, "ohlcv_download": dl_diag, "matrix_internal": matrix_int_diag, "validated_sector_internal": sector_int_diag, "flow": flow_diag},
        "guardrails": [
            "Distribution Warning only uses the PIT-validated 11-Sector cross-section: Price>=70, Internal<50, Exact 20D Flow<=0.",
            "Industry ETF states are descriptive/WATCH only because historical PIT holdings are unavailable from the tested official endpoints.",
            "Confirmed/Hidden/Early Accumulation are not buy signals; PIT research rejected predictive Alpha.",
            "Redemption Divergence is diagnostic only: ETF outflow is not automatically distribution.",
            "Macro/Fear&Greed explain WHY only and never alter V38 trading Gates or exits.",
        ],
    }
    (args.output / "latest.json").write_text(json.dumps(safe(report), ensure_ascii=False, indent=2), encoding="utf-8")
    matrix_df = pd.DataFrame(matrix_rows)
    matrix_df.to_csv(args.output / "latest_matrix.csv", index=False)
    pd.DataFrame(observations).to_csv(args.output / "latest_observations.csv", index=False)

    if args.history:
        args.history.parent.mkdir(parents=True, exist_ok=True)
        hist_cols = ["asof", "ticker", "level", "state", "state_evidence", "matrix_price_score", "matrix_internal_score", "matrix_internal_delta20", "validated_price_score", "validated_internal_score", "validated_internal_delta20", "weekly_rsi14", "flow_1d_usd", "flow_5d_usd", "flow_20d_usd", "flow_20d_pct_aum", "breadth21", "breadth50", "ad20_score", "obv_positive20", "updown_volume20"]
        new = matrix_df.reindex(columns=hist_cols)
        if args.history.exists() and args.history.stat().st_size:
            old = pd.read_csv(args.history)
            new = pd.concat([old, new], ignore_index=True)
        new = new.drop_duplicates(["asof", "ticker"], keep="last").sort_values(["asof", "ticker"])
        new.to_csv(args.history, index=False)

    print(f"DONE ROTATION LIVE SNAPSHOT asof={asof.date()} rows={len(matrix_rows)}", flush=True)


if __name__ == "__main__":
    main()
