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
    "KQ": ".KQ", "SJ": ".JO", "SP": ".SI", "TB": ".BK", "BZ": ".SA",
    "MK": ".KL", "IJ": ".JK",
}


def clean_symbol(value: Any) -> str:
    raw = str(value or "").strip().upper()
    if not raw or raw in {"-", "--", "NAN", "N/A", "CASH"} or "CASH" in raw:
        return ""
    raw = re.sub(r"\s+", " ", raw)
    raw = re.sub(r"/\.(?=[A-Z]{2}$)", ".", raw)
    exchanges = "|".join(EXCHANGE_SUFFIX)
    m = re.fullmatch(rf"(.+?)[. ]({exchanges})", raw)
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


def _row_record(cells: list[str], ticker: str, url: str) -> dict[str, Any] | None:
    cells = [re.sub(r"\s+", " ", str(x)).strip() for x in cells]
    if len(cells) < 5:
        return None
    low = " | ".join(cells).lower()
    if "security name" in low and "identifier" in low:
        return None

    weight_idx = None
    for i in range(len(cells) - 1, -1, -1):
        if re.fullmatch(r"[-+]?\d+(?:\.\d+)?\s*%", cells[i].replace(",", "")):
            weight_idx = i
            break
    if weight_idx is None:
        return None
    weight = parse_weight(cells[weight_idx])
    if weight is None or weight < -0.1 or weight > 100:
        return None

    # First Trust desktop and responsive tables use the same semantic order:
    # Security Name | Identifier | CUSIP | Classification | Shares | Market Value | Weighting.
    # Some rendered variants prepend a blank/sort cell, so anchor the identifier to a CUSIP-like
    # cell instead of assuming an absolute column index.
    symbol_idx = None
    for i in range(1, min(weight_idx, 5)):
        token = cells[i].replace(" ", "").replace("-", "")
        if re.fullmatch(r"[A-Z0-9]{8,12}", token) and i >= 1:
            candidate = clean_symbol(cells[i - 1])
            if candidate and candidate not in {"IDENTIFIER", "CUSIP"}:
                symbol_idx = i - 1
                break
    if symbol_idx is None:
        # Fallback for rows where the identifier itself is in column 1 and the security id is
        # not CUSIP-shaped (common for foreign securities in FAN/GRID).
        for i in range(1, min(weight_idx, 4)):
            candidate = clean_symbol(cells[i])
            if candidate and len(candidate) <= 18 and not any(ch.isspace() for ch in candidate):
                symbol_idx = i
                break
    if symbol_idx is None:
        return None

    provider_symbol = cells[symbol_idx].strip().upper()
    symbol = clean_symbol(provider_symbol)
    if not symbol:
        return None
    name_idx = max(0, symbol_idx - 1)
    name = cells[name_idx].strip()
    if not name or name.upper() in {"SECURITY NAME", "TOTAL"}:
        return None
    return {
        "sector_etf": ticker,
        "provider_symbol": provider_symbol,
        "symbol": symbol,
        "weight_pct": weight,
        "name": name,
        "source_url": url,
        "provider": "FIRSTTRUST",
    }


def fetch_holdings(session: requests.Session, ticker: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    url = f"https://www.ftportfolios.com/Retail/Etf/EtfHoldings.aspx?Print=Y&Ticker={ticker}"
    r = session.get(url, headers={"User-Agent": flowlib.UA, "Accept": "text/html,*/*"}, timeout=45)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    text = soup.get_text(" ", strip=True)
    expected = None
    m = re.search(r"Total Number of Holdings\s*\(excluding cash\)\s*:?\s*(\d+)", text, flags=re.I)
    if m:
        expected = int(m.group(1))

    records: list[dict[str, Any]] = []
    # Do not restrict parsing to the first parent table. First Trust emits several responsive
    # table fragments; the earlier parser saw only the first 1-3 rows. Scan all rendered rows,
    # then de-duplicate by provider identifier.
    for tr in soup.find_all("tr"):
        cells = [x.get_text(" ", strip=True) for x in tr.find_all(["th", "td"])]
        rec = _row_record(cells, ticker, url)
        if rec is not None:
            records.append(rec)

    out = pd.DataFrame(records)
    if out.empty:
        raise RuntimeError("First Trust holdings parsed zero rows")
    out = out.drop_duplicates("provider_symbol", keep="first").reset_index(drop=True)

    if expected is not None and len(out) != expected:
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
        pd.concat(frames, ignore_index=True).drop_duplicates(["sector_etf", "provider_symbol"]).to_csv(
            args.output / "firsttrust_exact_current_holdings.csv", index=False
        )
    passed = qa_df.loc[qa_df["status"] == "PASS", "ticker"].tolist()
    report = {
        "schema": 2,
        "research_only": True,
        "candidate_count": len(TICKERS),
        "pass_count": len(passed),
        "pass_tickers": passed,
        "guardrails": [
            "Only the complete current holdings rows published by First Trust are accepted.",
            "The official holding count is required to match the parsed unique provider identifiers.",
            "Provider identifiers are preserved; foreign identifiers are normalized only for market-data lookup.",
            "No Top-10 or partial table is accepted as exact membership.",
        ],
    }
    (args.output / "firsttrust_holdings_qa.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if len(passed) != len(TICKERS):
        raise RuntimeError(f"First Trust exact holdings incomplete: {passed}")


if __name__ == "__main__":
    main()
