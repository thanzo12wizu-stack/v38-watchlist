from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
import requests

import rotation_exact_flow_research as flowlib
import validate_pioneer_leader as pl

PROVIDERS = {
    "XBI": "SSGA",
    "XME": "SSGA",
    "SOXX": "ISHARES",
    "IGV": "ISHARES",
}


def main() -> None:
    ap = argparse.ArgumentParser(description="Official exact Fund Flow QA for target Industry ETFs")
    ap.add_argument("--start", default="2022-01-01")
    ap.add_argument("--end", default="2026-08-17")
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    start = pd.Timestamp(args.start).normalize()
    end = pd.Timestamp(args.end).normalize()
    warmup = start - pd.Timedelta(days=60)
    tickers = list(PROVIDERS)

    ohlcv, price_diag = pl.download_ohlcv(tickers, str(warmup.date()), str((end + pd.Timedelta(days=7)).date()), 20)
    close = ohlcv["close"]
    session = requests.Session()
    ishares_ids = flowlib.resolve_ishares_portfolio_ids(session, [t for t, p in PROVIDERS.items() if p == "ISHARES"])

    frames = []
    diagnostics = []
    failures = []
    for ticker, provider in PROVIDERS.items():
        try:
            if provider == "SSGA":
                series = flowlib.fetch_ssga_nav_history(session, ticker)
            else:
                pid = ishares_ids.get(ticker)
                if pid is None:
                    raise RuntimeError(f"{ticker}: iShares portfolioId not found")
                series = flowlib.fetch_ishares_nav_history(session, ticker, pid)

            raw, raw_diag = flowlib.derive_exact_flows(series)
            raw = raw[(raw["date"] >= warmup) & (raw["date"] <= end)].copy()
            trading_dates = pd.DatetimeIndex(close[ticker].dropna().index)
            trading_dates = trading_dates[(trading_dates >= warmup) & (trading_dates <= end)]
            cal = pd.DataFrame({"date": trading_dates})
            x = cal.merge(
                raw[["date", "nav", "shares_outstanding", "aum", "flow_usd", "provider", "source_url"]],
                on="date",
                how="left",
            )
            x["ticker"] = ticker
            x["flow_1d"] = x["flow_usd"]
            x["flow_5d"] = x["flow_usd"].rolling(5, min_periods=5).sum()
            x["flow_20d"] = x["flow_usd"].rolling(20, min_periods=20).sum()
            x["flow_20d_pct_aum"] = 100.0 * x["flow_20d"] / x["aum"]
            x = x[(x["date"] >= start) & (x["date"] <= end)].copy()
            frames.append(x)

            rows = len(x)
            valid = int(x["flow_1d"].notna().sum())
            coverage = valid / rows if rows else 0.0
            diagnostics.append({
                "ticker": ticker,
                "provider": provider,
                "source_url": series.source_url,
                "official_history_first": raw_diag.get("first_date"),
                "official_history_last": raw_diag.get("last_date"),
                "trading_days": rows,
                "valid_flow_1d": valid,
                "trading_day_coverage": coverage,
                "valid_flow_20d": int(x["flow_20d"].notna().sum()),
                "last_date": None if x.empty else str(x["date"].max().date()),
                "last_flow_20d_usd": None if x["flow_20d"].dropna().empty else float(x["flow_20d"].dropna().iloc[-1]),
                "last_flow_20d_pct_aum": None if x["flow_20d_pct_aum"].dropna().empty else float(x["flow_20d_pct_aum"].dropna().iloc[-1]),
                "split_events": raw_diag.get("split_events"),
            })
            print(f"INDUSTRY_FLOW {ticker} provider={provider} coverage={coverage:.2%}", flush=True)
        except Exception as exc:
            failures.append({"ticker": ticker, "provider": provider, "error": f"{type(exc).__name__}: {exc}"})
            print(f"INDUSTRY_FLOW_FAIL {ticker}: {exc}", flush=True)

    all_flows = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if not all_flows.empty:
        all_flows.sort_values(["date", "ticker"]).to_csv(args.output / "industry_exact_flows.csv", index=False, date_format="%Y-%m-%d")

    usable = len(failures) == 0 and len(diagnostics) == len(PROVIDERS) and all(d["trading_day_coverage"] >= 0.98 for d in diagnostics)
    report = {
        "schema": 1,
        "research_only": True,
        "quality": "EXACT_OFFICIAL_SHARES_OUTSTANDING_DERIVED_ON_ACTUAL_ETF_TRADING_DAYS",
        "window": {"start": str(start.date()), "end": str(end.date())},
        "providers": PROVIDERS,
        "price_calendar_download": price_diag,
        "diagnostics": diagnostics,
        "failures": failures,
        "usable_for_rotation_flow_layer": usable,
        "guardrail": "Dollar Volume is never substituted for Fund Flow. 5D/20D sums use actual ETF trading dates, not provider weekend/stale rows.",
    }
    (args.output / "industry_flow_qa_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    lines = [
        "# Industry ETF Exact Flow QA",
        "",
        f"Decision: {'PASS' if usable else 'FAIL'}",
        "",
        "| ETF | Provider | Trading-day coverage | 20D valid rows |",
        "|---|---|---:|---:|",
    ]
    for d in diagnostics:
        lines.append(f"| {d['ticker']} | {d['provider']} | {100*d['trading_day_coverage']:.2f}% | {d['valid_flow_20d']} |")
    if failures:
        lines += ["", "Failures:"] + [f"- {x['ticker']}: {x['error']}" for x in failures]
    (args.output / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"DONE INDUSTRY FLOW QA usable={usable}", flush=True)


if __name__ == "__main__":
    main()
