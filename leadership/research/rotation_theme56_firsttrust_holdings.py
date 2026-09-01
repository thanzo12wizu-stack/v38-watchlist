from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from bs4 import BeautifulSoup

import rotation_exact_flow_research as flowlib


TICKERS = ["CIBR", "FAN", "GRID", "SKYY"]

EXCHANGE_SUFFIX = {
    "FP": ".PA", "SW": ".SW", "LN": ".L", "GY": ".DE", "GR": ".DE",
    "IM": ".MI", "DC": ".CO", "PL": ".LS", "CN": ".TO", "IT": ".TA",
    "NA": ".AS", "FH": ".HE", "SS": ".ST", "NO": ".OL", "AU": ".AX",
    "JP": ".T", "JT": ".T", "HK": ".HK", "TT": ".TW", "KS": ".KS",
    "KQ": ".KQ", "SJ": ".JO",
}


def clean_symbol(value: Any) -> str:
    raw = str(value or "").strip().upper()
    if not raw or raw in {"-", "--", "NAN", "N/A", "CASH"}:
        return ""
    raw = re.sub(r"\s+", " ", raw)
    raw = re.sub(r"/\.(?=[A-Z]{2}$)", ".", raw)  # NG/.LN -> NG.LN
    m = re.fullmatch(r"(.+?)[. ](FP|SW|LN|GY|GR|IM|DC|PL|CN|IT|NA|FH|SS|NO|AU|JP|JT|HK|TT|KS|KQ|SJ)", raw)
    if m:
        base, exch = m.group(1), m.group(2)
        base = base.replace("/", "-").strip(".- ")
        if exch == "HK" and base.isdigit():
            base = base.zfill(4)
        if exch == "DC" and base == "MAERSKB":
            base = "MAERSK-B"
        return base + EXCHANGE_SUFFIX[exch]
    if re.fullmatch(r"[A-Z]{1,6}[/.][A-Z]", raw):
        return raw.replace("/", "-").replace(".", "-")
    return raw


def parse_weight(text: str) -> float | None:
    m = re.search(r"[-+]?\d+(?:\.\d+)?", str(text).replace(",", ""))
    return float(m.group(0)) if m else None


def fetch_holdings(session: requests.Session, ticker: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    url = f"https://www.ftportfolios.com/Retail/Etf/EtfHoldings.aspx?Print=Y&Ticker={ticker}"
    r = session.get(url, headers={"User-Agent": flowlib.UA, "Accept": "text/html,*/*"}, timeout=45)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    header_tr = None
    header_cells: list[str] = []
    for tr in soup.find_all("tr"):
        cells = [x.get_text(" ", strip=True) for x in tr.find_all(["th", "td"])]
        joined = " | ".join(cells).lower()
        if "security name" in joined and "identifier" in joined and "weighting" in joined:
            header_tr = tr
            header_cells = cells
            break
    if header_tr is None:
        # First Trust occasionally renders the header as div/spans. Locate the containing table.
        for table in soup.find_all("table"):
            text = table.get_text(" ", strip=True).lower()
            if "security name" in text and "identifier" in text and "weighting" in text:
                trs = table.find_all("tr")
                for tr in trs:
                    cells = [x.get_text(" ", strip=True) for x in tr.find_all(["th", "td"])]
                    joined = " | ".join(cells).lower()
                    if "identifier" in joined and "weighting" in joined:
                        header_tr = tr
                        header_cells = cells
                        break
                if header_tr is not None:
                    break
    if header_tr is None:
        raise RuntimeError("First Trust full holdings header not found")

    norm = [re.sub(r"\s+", " ", x.strip().lower()) for x in header_cells]
    def idx_contains(needle: str) -> int:
        for i, x in enumerate(norm):
            if needle in x:
                return i
        raise RuntimeError(f"First Trust header missing {needle}: {header_cells}")

    name_i = idx_contains("security name")
    symbol_i = idx_contains("identifier")
    weight_i = idx_contains("weighting")

    table = header_tr.find_parent("table")
    if table is None:
        raise RuntimeError("First Trust holdings table parent missing")
    records: list[dict[str, Any]] = []
    passed_header = False
    for tr in table.find_all("tr"):
        if tr is header_tr:
            passed_header = True
            continue
        if not passed_header:
            continue
        cells = [x.get_text(" ", strip=True) for x in tr.find_all(["th", "td"])]
        if len(cells) <= max(name_i, symbol_i, weight_i):
            continue
        provider_symbol = cells[symbol_i].strip().upper()
        symbol = clean_symbol(provider_symbol)
        if not symbol:
            continue
        name = cells[name_i].strip()
        weight = parse_weight(cells[weight_i])
        # Ignore footer/total rows that are not security identifiers.
        if not name or weight is None or weight < -0.1 or weight > 100:
            continue
        records.append({
            "sector_etf": ticker,
            "provider_symbol": provider_symbol,
            "symbol": symbol,
            "weight_pct": weight,
            "name": name,
            "source_url": url,
            "provider": "FIRSTTRUST",
        })

    out = pd.DataFrame(records)
    if out.empty:
        raise RuntimeError("First Trust holdings parsed zero rows")
    out = out.drop_duplicates("symbol", keep="first").reset_index(drop=True)

    text = soup.get_text(" ", strip=True)
    expected = None
    m = re.search(r"Total Number of Holdings\s*\(excluding cash\)\s*:?\s*(\d+)", text, flags=re.I)
    if m:
        expected = int(m.group(1))
    if expected is not None and len(out) < max(5, expected - 1):
        raise RuntimeError(f"partial holdings rejected: parsed {len(out)} vs official {expected}")
    if len(out) < 10:
        raise RuntimeError(f"unexpectedly short First Trust holdings: {len(out)}")

    return out, {
        "ticker": ticker,
        "provider": "FIRSTTRUST",
        "status": "PASS",
        "rows": int(len(out)),
        "official_count": expected,
        "source_url": url,
        "quality": "EXACT_CURRENT_MEMBERSHIP",
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Fetch exact current First Trust holdings for Theme56 ETFs")
    ap.add_argument("--output", type=Path, default=Path("leadership/research/rotation_theme56_firsttrust"))
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    frames: list[pd.DataFrame] = []
    qa: list[dict[str, Any]] = []
    for ticker in TICKERS:
        try:
            df, diag = fetch_holdings(session, ticker)
            frames.append(df)
            qa.append(diag)
        except Exception as exc:
            qa.append({"ticker": ticker, "provider": "FIRSTTRUST", "status": "FAIL", "error": f"{type(exc).__name__}: {exc}"})
        print(json.dumps(qa[-1], ensure_ascii=False), flush=True)

    qa_df = pd.DataFrame(qa)
    qa_df.to_csv(args.output / "firsttrust_holdings_qa.csv", index=False)
    if frames:
        pd.concat(frames, ignore_index=True).drop_duplicates(["sector_etf", "symbol"]).to_csv(
            args.output / "firsttrust_exact_current_holdings.csv", index=False
        )
    passed = qa_df.loc[qa_df["status"] == "PASS", "ticker"].tolist()
    report = {
        "schema": 1,
        "research_only": True,
        "candidate_count": len(TICKERS),
        "pass_count": len(passed),
        "pass_tickers": passed,
        "guardrails": [
            "Only the complete current holdings table published by First Trust is accepted.",
            "The official holding count, when present, is used as a completeness guard.",
            "Provider identifiers are preserved; foreign identifiers are normalized only for market-data lookup.",
            "This adapter does not label NAV/Net Assets-derived estimates as Exact Flow because historical Shares Outstanding is not directly published in the pricing table.",
        ],
    }
    (args.output / "firsttrust_holdings_qa.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if len(passed) != len(TICKERS):
        raise RuntimeError(f"First Trust exact holdings incomplete: {passed}")


if __name__ == "__main__":
    main()
