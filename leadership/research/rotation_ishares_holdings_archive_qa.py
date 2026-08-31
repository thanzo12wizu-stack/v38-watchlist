from __future__ import annotations

import argparse
import csv
import io
import json
import re
from pathlib import Path

import requests

FUNDS = {
    "SOXX": {"product_id": "239705", "slug": "ishares-semiconductor-etf"},
    "IGV": {"product_id": "239771", "slug": "ishares-expanded-techsoftware-sector-etf"},
}
TEST_DATES = [
    "20220331", "20220630", "20220930", "20221230",
    "20230331", "20230630", "20230929", "20231229",
    "20240328", "20240628", "20240930", "20241231",
    "20250331", "20250630", "20250930", "20251231",
    "20260331", "20260630",
]
UA = "Mozilla/5.0 V38-Rotation-Research/1.0"


def endpoint(ticker: str, asof: str) -> str:
    f = FUNDS[ticker]
    return (
        f"https://www.ishares.com/us/products/{f['product_id']}/{f['slug']}/1467271812596.ajax"
        f"?fileType=csv&fileName={ticker}_holdings&dataType=fund&asOfDate={asof}"
    )


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
    header_idx = None
    for i, line in enumerate(lines):
        low = line.lower()
        if low.startswith("ticker,") and "name" in low and "weight" in low:
            header_idx = i
            break
    if header_idx is None:
        return {"reported_asof": reported_asof, "parsed": False, "equity_rows": 0, "header_idx": None}
    reader = csv.DictReader(io.StringIO("\n".join(lines[header_idx:])))
    equity_rows = 0
    tickers = []
    for row in reader:
        ticker = (row.get("Ticker") or "").strip()
        asset = (row.get("Asset Class") or "").strip().lower()
        if ticker and asset == "equity":
            equity_rows += 1
            tickers.append(ticker)
    return {
        "reported_asof": reported_asof,
        "parsed": True,
        "equity_rows": equity_rows,
        "sample_tickers": tickers[:5],
        "header_idx": header_idx,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Audit official iShares holdings download archive availability")
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
                    parsed = parse_holdings_csv(r.content.decode("utf-8-sig", errors="replace"))
                    rec.update(parsed)
                else:
                    rec.update({"reported_asof": None, "parsed": False, "equity_rows": 0})
            except Exception as exc:
                rec.update({"http_status": None, "bytes": 0, "reported_asof": None, "parsed": False, "equity_rows": 0, "error": f"{type(exc).__name__}: {exc}"})
            rows.append(rec)
            print(f"ISHARES_HOLDINGS {ticker} {asof} status={rec.get('http_status')} rows={rec.get('equity_rows',0)} reported={rec.get('reported_asof')}", flush=True)

    import pandas as pd
    df = pd.DataFrame(rows)
    df.to_csv(args.output / "ishares_holdings_archive_qa.csv", index=False)
    good = df[(df["http_status"] == 200) & (df["parsed"] == True) & (df["equity_rows"] >= 5)]
    by_ticker = {}
    for ticker in FUNDS:
        x = good[good["ticker"] == ticker]
        by_ticker[ticker] = {
            "tests": len(TEST_DATES),
            "successful_dates": int(len(x)),
            "oldest_success_requested": None if x.empty else str(x["requested_asof"].min()),
            "newest_success_requested": None if x.empty else str(x["requested_asof"].max()),
            "all_test_dates_successful": int(len(x)) == len(TEST_DATES),
        }
    usable = all(v["all_test_dates_successful"] for v in by_ticker.values())
    report = {
        "schema": 1,
        "research_only": True,
        "source": "official iShares Download Holdings CSV endpoint with explicit asOfDate",
        "funds": by_ticker,
        "usable_as_quarterly_pit_holdings_2022_2026": usable,
        "note": "This tests quarter-end archive availability. It does not imply daily historical holdings availability.",
    }
    (args.output / "ishares_holdings_archive_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# iShares Holdings Archive QA", "", f"Decision for quarterly PIT: {'PASS' if usable else 'FAIL'}", ""]
    for t, v in by_ticker.items():
        lines.append(f"- {t}: {v['successful_dates']}/{v['tests']} tested quarter-end dates; oldest={v['oldest_success_requested']}")
    (args.output / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"DONE ISHARES HOLDINGS ARCHIVE QA usable={usable}", flush=True)


if __name__ == "__main__":
    main()
