from __future__ import annotations

import argparse
import csv
import io
import json
from pathlib import Path

import pandas as pd
import requests

FUNDS = {
    "SOXX": {"product_id": "239705", "slug": "ishares-semiconductor-etf"},
    "IGV": {"product_id": "239771", "slug": "ishares-expanded-tech-software-sector-etf"},
}
TEST_DATES = ["20221230", "20231229", "20241231", "20251231", "20260630"]
UA = "Mozilla/5.0 V38-Rotation-Research/1.0"


def endpoint(ticker: str, asof: str) -> str:
    f = FUNDS[ticker]
    return f"https://www.ishares.com/us/products/{f['product_id']}/{f['slug']}/latest-holdings.csv?asOfDate={asof}"


def parse_holdings_csv(text: str) -> dict:
    text = text.lstrip("\ufeff")
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
        return {"reported_asof": reported_asof, "parsed": False, "equity_rows": 0}
    reader = csv.DictReader(io.StringIO("\n".join(lines[header_idx:])))
    tickers = []
    for row in reader:
        ticker = (row.get("Ticker") or "").strip()
        asset = (row.get("Asset Class") or "").strip().lower()
        if ticker and asset == "equity":
            tickers.append(ticker)
    return {"reported_asof": reported_asof, "parsed": True, "equity_rows": len(tickers), "sample_tickers": tickers[:5]}


def normalized_reported(v: str | None) -> str | None:
    if not v:
        return None
    dt = pd.to_datetime(v, errors="coerce")
    return None if pd.isna(dt) else dt.strftime("%Y%m%d")


def main() -> None:
    ap = argparse.ArgumentParser(description="Audit official iShares latest-holdings endpoint for historical asOfDate support")
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    rows = []
    for ticker in FUNDS:
        for asof in TEST_DATES:
            url = endpoint(ticker, asof)
            rec = {"ticker": ticker, "requested_asof": asof, "url": url}
            try:
                r = session.get(url, headers={"User-Agent": UA, "Accept": "text/csv,*/*"}, timeout=30)
                rec["http_status"] = r.status_code
                rec["bytes"] = len(r.content)
                if r.ok:
                    rec.update(parse_holdings_csv(r.content.decode("utf-8-sig", errors="replace")))
                else:
                    rec.update({"reported_asof": None, "parsed": False, "equity_rows": 0})
            except Exception as exc:
                rec.update({"http_status": None, "bytes": 0, "reported_asof": None, "parsed": False, "equity_rows": 0, "error": f"{type(exc).__name__}: {exc}"})
            rec["reported_asof_normalized"] = normalized_reported(rec.get("reported_asof"))
            rec["requested_date_honored"] = rec["reported_asof_normalized"] == asof
            rows.append(rec)
            print(f"ISHARES_HOLDINGS {ticker} req={asof} reported={rec.get('reported_asof_normalized')} rows={rec.get('equity_rows')} honored={rec['requested_date_honored']}", flush=True)

    df = pd.DataFrame(rows)
    df.to_csv(args.output / "ishares_holdings_archive_qa.csv", index=False)
    valid_current = df[(df.http_status == 200) & (df.parsed == True) & (df.equity_rows >= 5)]
    honored = valid_current[valid_current.requested_date_honored == True]
    funds = {}
    for ticker in FUNDS:
        a = valid_current[valid_current.ticker == ticker]
        h = honored[honored.ticker == ticker]
        funds[ticker] = {
            "endpoint_returns_valid_holdings": int(len(a)) == len(TEST_DATES),
            "requested_dates_honored": int(len(h)),
            "tests": len(TEST_DATES),
            "historical_asof_supported_for_test_set": int(len(h)) == len(TEST_DATES),
            "reported_dates": sorted(set(a.reported_asof_normalized.dropna().astype(str))),
        }
    usable = all(v["historical_asof_supported_for_test_set"] for v in funds.values())
    current_live = all(v["endpoint_returns_valid_holdings"] for v in funds.values())
    report = {
        "schema": 2,
        "research_only": True,
        "source": "official iShares latest-holdings.csv endpoint",
        "funds": funds,
        "usable_as_quarterly_pit_holdings_2022_2026": usable,
        "usable_for_live_internal_membership": current_live,
        "decision": "PIT_PASS" if usable else ("LIVE_ONLY" if current_live else "FAIL"),
        "guardrail": "A 200 response is not historical evidence unless the returned Fund Holdings as-of date matches the requested date.",
    }
    (args.output / "ishares_holdings_archive_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# iShares Holdings Archive QA v2", "", f"Decision: {report['decision']}", ""]
    for t, v in funds.items():
        lines.append(f"- {t}: historical honored {v['requested_dates_honored']}/{v['tests']}; returned dates={v['reported_dates']}")
    (args.output / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"DONE ISHARES HOLDINGS ARCHIVE QA v2 decision={report['decision']}", flush=True)


if __name__ == "__main__":
    main()
