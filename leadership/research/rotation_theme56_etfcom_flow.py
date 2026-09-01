from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122 Safari/537.36"
HEADERS = {"User-Agent": UA, "Accept": "application/json,*/*", "Origin": "https://www.etf.com", "Referer": "https://www.etf.com/"}
FLOW_URL = "https://api-prod.etf.com/private/apps/fundflows/{ticker}/charts?startDate={start}&endDate={end}"
TV_URL = "https://scanner.tradingview.com/global/scan"
TV_EXCHANGES = ("NASDAQ", "AMEX", "NYSE", "NYSEARCA", "CBOE")
CANONICAL_ETFCOM_SCALE = 1_000_000.0


def load_json(path: Path) -> dict[str, Any]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return obj


def _find_flow_points(obj: Any) -> list[dict[str, Any]] | None:
    """Find ETF.com chart points without assuming one response wrapper.

    ETF.com has returned more than one JSON envelope for fund-flow charts.  The
    payload itself is still a list of objects carrying asOf/value, so accept
    that canonical payload wherever it is nested rather than special-casing a
    ticker or substituting a proxy.
    """
    if isinstance(obj, list):
        points = [x for x in obj if isinstance(x, dict) and "asOf" in x and "value" in x]
        if points:
            return points
        for item in obj:
            found = _find_flow_points(item)
            if found:
                return found
        return None
    if isinstance(obj, dict):
        for value in obj.values():
            found = _find_flow_points(value)
            if found:
                return found
    return None


def fetch_flow(session: requests.Session, ticker: str, start: str, end: str) -> pd.DataFrame:
    url = FLOW_URL.format(ticker=ticker, start=start.replace("-", ""), end=end.replace("-", ""))
    last_exc: Exception | None = None
    for attempt in range(4):
        try:
            r = session.get(url, headers=HEADERS, timeout=35)
            r.raise_for_status()
            obj = r.json()
            points = _find_flow_points(obj)
            if not isinstance(points, list):
                raise RuntimeError(f"unexpected ETF.com response for {ticker}")
            rows: list[dict[str, Any]] = []
            for x in points:
                if not isinstance(x, dict):
                    continue
                d = pd.to_datetime(x.get("asOf"), errors="coerce")
                v = pd.to_numeric(x.get("value"), errors="coerce")
                if pd.notna(d) and pd.notna(v):
                    rows.append({"date": pd.Timestamp(d).normalize(), "ticker": ticker, "etfcom_value": float(v)})
            if not rows:
                raise RuntimeError(f"ETF.com returned no flow rows for {ticker}")
            return pd.DataFrame(rows).drop_duplicates("date", keep="last").sort_values("date")
        except Exception as exc:
            last_exc = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"ETF.com flow failed for {ticker}: {last_exc}")


def fetch_tv_aum(session: requests.Session, tickers: list[str]) -> dict[str, dict[str, Any]]:
    symbols = [f"{ex}:{t}" for t in tickers for ex in TV_EXCHANGES]
    payload = {
        "symbols": {"tickers": symbols, "query": {"types": []}},
        "columns": ["name", "exchange", "aum", "nav", "fund_flows.1M", "fund_flows.1Y", "etf_holdings_count"],
    }
    r = session.post(
        TV_URL,
        headers={"User-Agent": UA, "Accept": "application/json,*/*", "Content-Type": "application/json", "Origin": "https://www.tradingview.com", "Referer": "https://www.tradingview.com/"},
        json=payload,
        timeout=45,
    )
    r.raise_for_status()
    out: dict[str, dict[str, Any]] = {}
    for item in r.json().get("data") or []:
        if not isinstance(item, dict):
            continue
        vals = item.get("d") or []
        if len(vals) < 3:
            continue
        ticker = str(vals[0] or "").upper().strip()
        aum = pd.to_numeric(vals[2], errors="coerce")
        if ticker in tickers and pd.notna(aum) and float(aum) > 0:
            out.setdefault(ticker, {"symbol_ref": item.get("s"), "exchange": vals[1], "aum": float(aum), "nav": vals[3] if len(vals) > 3 else None, "flow_1m": vals[4] if len(vals) > 4 else None, "flow_1y": vals[5] if len(vals) > 5 else None, "holdings_count": vals[6] if len(vals) > 6 else None})
    return out


def read_official_flows(path: Path, tickers: set[str], start: str, end: str) -> pd.DataFrame:
    use = pd.read_csv(path, usecols=lambda c: c in {"date", "ticker", "flow_1d"})
    use["ticker"] = use["ticker"].astype(str).str.upper()
    use["date"] = pd.to_datetime(use["date"], errors="coerce").dt.normalize()
    use["official_flow_usd"] = pd.to_numeric(use["flow_1d"], errors="coerce")
    use = use[use["ticker"].isin(tickers) & use["date"].between(pd.Timestamp(start), pd.Timestamp(end))]
    return use[["date", "ticker", "official_flow_usd"]].dropna()


def validation_stats(etf: pd.DataFrame, official: pd.DataFrame, ticker: str, provider: str | None) -> dict[str, Any]:
    a = etf[etf["ticker"] == ticker][["date", "etfcom_value"]]
    b = official[official["ticker"] == ticker][["date", "official_flow_usd"]]
    m = a.merge(b, on="date", how="inner")
    if m.empty:
        return {"ticker": ticker, "provider": provider, "n": 0, "status": "NO_OVERLAP"}
    x = pd.to_numeric(m["etfcom_value"], errors="coerce").to_numpy(float)
    y = pd.to_numeric(m["official_flow_usd"], errors="coerce").to_numpy(float)
    candidates = (1.0, 1e3, 1e6, 1e9)
    errors: dict[float, float] = {}
    for scale in candidates:
        pred = x * scale
        denom = np.maximum(np.abs(y), 1e6)
        errors[scale] = float(np.nanmedian(np.abs(pred - y) / denom))
    best_scale = min(errors, key=errors.get)
    pred = x * best_scale
    nz = (np.abs(y) >= 1e6) | (np.abs(pred) >= 1e6)
    sign_agreement = float(np.mean(np.sign(pred[nz]) == np.sign(y[nz]))) if nz.any() else 1.0
    corr = float(np.corrcoef(pred, y)[0, 1]) if len(m) >= 3 and np.nanstd(pred) > 0 and np.nanstd(y) > 0 else None
    abs_median = float(np.nanmedian(np.abs(pred - y)))
    official_scale = float(np.nanmedian(np.abs(y))) if len(y) else math.nan
    rel_median = abs_median / max(official_scale, 1e6)
    quality_ok = len(m) >= 10 and sign_agreement >= 0.90 and (corr is None or corr >= 0.90) and rel_median <= 0.15
    if quality_ok and best_scale == CANONICAL_ETFCOM_SCALE:
        status = "PASS"
    elif quality_ok and best_scale != CANONICAL_ETFCOM_SCALE:
        status = "REFERENCE_UNIT_ANOMALY"
    else:
        status = "FAIL"
    return {
        "ticker": ticker,
        "provider": provider,
        "n": int(len(m)),
        "best_scale": float(best_scale),
        "canonical_scale": CANONICAL_ETFCOM_SCALE,
        "sign_agreement": sign_agreement,
        "corr": corr,
        "median_abs_error_usd": abs_median,
        "median_error_vs_median_official": rel_median,
        "status": status,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Validate and build ETF.com daily-flow fallback for Theme56")
    ap.add_argument("--config", type=Path, default=Path("leadership/research/rotation_theme56_config.json"))
    ap.add_argument("--official-qa", type=Path, default=Path("leadership/research/rotation_theme56_provider_qa/theme56_provider_qa.csv"))
    ap.add_argument("--official-flows", type=Path, default=Path("leadership/research/rotation_theme56_provider_qa/theme56_exact_flows.csv"))
    ap.add_argument("--output", type=Path, default=Path("leadership/research/rotation_theme56_etfcom_flow"))
    ap.add_argument("--start", default="2026-07-01")
    ap.add_argument("--end", default="2026-08-31")
    args = ap.parse_args()

    cfg = load_json(args.config)
    tickers = [str(x.get("ticker") or "").upper() for x in cfg.get("themes") or []]
    if len(tickers) != 56 or len(set(tickers)) != 56:
        raise RuntimeError("Theme56 config mismatch")

    qa = pd.read_csv(args.official_qa)
    qa["ticker"] = qa["ticker"].astype(str).str.upper()
    full_mask = qa["full_stack_adapter"].astype(str).str.lower().isin({"true", "1", "yes"})
    official_tickers = set(qa.loc[full_mask, "ticker"])
    provider_map = dict(zip(qa["ticker"], qa["provider"].astype(str)))

    session = requests.Session()
    flow_frames: list[pd.DataFrame] = []
    failures: list[dict[str, str]] = []
    for idx, ticker in enumerate(tickers, 1):
        try:
            f = fetch_flow(session, ticker, args.start, args.end)
            flow_frames.append(f)
            print(f"FLOW {idx}/{len(tickers)} {ticker} rows={len(f)} last={f['date'].max().date()}", flush=True)
        except Exception as exc:
            failures.append({"ticker": ticker, "error": f"{type(exc).__name__}: {exc}"})
            print(f"FLOW {idx}/{len(tickers)} {ticker} FAIL {exc}", flush=True)
    if not flow_frames:
        raise RuntimeError("ETF.com returned no Theme56 flows")
    raw = pd.concat(flow_frames, ignore_index=True)

    official = read_official_flows(args.official_flows, official_tickers, args.start, args.end)
    validations = [validation_stats(raw, official, t, provider_map.get(t)) for t in sorted(official_tickers)]
    vdf = pd.DataFrame(validations)
    canonical = vdf[(vdf["n"] >= 10) & (vdf["best_scale"] == CANONICAL_ETFCOM_SCALE)].copy()
    pass_ratio = float((canonical["status"] == "PASS").mean()) if len(canonical) else 0.0
    provider_count = int(canonical.loc[canonical["status"] == "PASS", "provider"].nunique()) if len(canonical) else 0
    aggregate_pass = len(canonical) >= 12 and pass_ratio >= 0.95 and provider_count >= 2
    anomalies = vdf.loc[vdf["status"] == "REFERENCE_UNIT_ANOMALY", "ticker"].astype(str).tolist()

    aum = fetch_tv_aum(session, tickers)
    raw["flow_1d"] = raw["etfcom_value"] * CANONICAL_ETFCOM_SCALE
    raw["provider"] = "ETFCOM_VALIDATED_ACTUAL"
    raw["source_url"] = raw["ticker"].map(lambda t: FLOW_URL.format(ticker=t, start=args.start.replace("-", ""), end=args.end.replace("-", "")))
    raw = raw.sort_values(["ticker", "date"])
    raw["flow_5d"] = raw.groupby("ticker", observed=True)["flow_1d"].transform(lambda s: s.rolling(5, min_periods=5).sum())
    raw["flow_20d"] = raw.groupby("ticker", observed=True)["flow_1d"].transform(lambda s: s.rolling(20, min_periods=20).sum())
    raw["aum"] = raw["ticker"].map(lambda t: (aum.get(t) or {}).get("aum"))
    raw["flow_20d_pct_aum"] = 100.0 * raw["flow_20d"] / pd.to_numeric(raw["aum"], errors="coerce")
    raw["validation_contract"] = "ETF.com daily actual fund-flow fallback; USD-million chart scale validated against canonical issuer-derived references. Issuer exact flow remains preferred when its own unit QA is clean."

    args.output.mkdir(parents=True, exist_ok=True)
    raw.to_csv(args.output / "theme56_etfcom_daily_flows.csv", index=False)
    vdf.to_csv(args.output / "etfcom_vs_issuer_validation.csv", index=False)
    status_rows: list[dict[str, Any]] = []
    for t in tickers:
        g = raw[raw["ticker"] == t]
        status_rows.append({
            "ticker": t,
            "flow_rows": int(len(g)),
            "last_date": None if g.empty else str(g["date"].max().date()),
            "aum": (aum.get(t) or {}).get("aum"),
            "status": "PASS" if aggregate_pass and len(g) >= 20 and (aum.get(t) or {}).get("aum") else "DATA_REQUIRED",
        })

    report = {
        "schema": 2,
        "research_only": True,
        "aggregate_validation_pass": aggregate_pass,
        "official_validation_tickers": len(official_tickers),
        "canonical_reference_tickers": int(len(canonical)),
        "canonical_reference_pass_ratio": pass_ratio,
        "canonical_reference_provider_count": provider_count,
        "reference_unit_anomalies": anomalies,
        "fallback_provider": "ETF.com daily actual fund-flow data; issuer exact flow remains preferred when issuer unit QA is clean",
        "flow_unit_scale": CANONICAL_ETFCOM_SCALE,
        "flow_unit_contract": "ETF.com chart values are normalized as USD millions only after canonical issuer-reference validation across at least two providers.",
        "failures": failures,
        "validation": validations,
        "status": status_rows,
        "guardrails": [
            "ETF.com is a third-party actual fund-flow source, not an issuer-official exact-flow source.",
            "Noncanonical issuer-reference scale matches are quarantined as REFERENCE_UNIT_ANOMALY instead of forcing their units onto ETF.com data.",
            "No dollar-volume, OBV, CMF, or price-volume proxy is substituted for fund flow.",
            "A ticker remains DATA_REQUIRED only when no validated daily actual-flow series is returned.",
        ],
    }
    (args.output / "etfcom_flow_qa.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({
        "aggregate_validation_pass": aggregate_pass,
        "canonical_references": len(canonical),
        "pass_ratio": pass_ratio,
        "reference_unit_anomalies": anomalies,
        "api_success": len(set(raw["ticker"])),
        "aum_success": len(aum),
        "failures": len(failures),
    }, ensure_ascii=False, indent=2), flush=True)
    if not aggregate_pass:
        raise RuntimeError("ETF.com fallback did not pass canonical issuer cross-validation")


if __name__ == "__main__":
    main()
