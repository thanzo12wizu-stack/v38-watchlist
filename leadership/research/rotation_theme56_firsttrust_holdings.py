from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from bs4 import BeautifulSoup, Tag

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
    if not raw or raw.startswith("$") or raw in {"-", "--", "NAN", "N/A", "CASH"} or "CASH" in raw:
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

    symbol_idx = None
    for i in range(1, min(weight_idx, 5)):
        token = cells[i].replace(" ", "").replace("-", "")
        if re.fullmatch(r"[A-Z0-9]{8,12}", token):
            candidate = clean_symbol(cells[i - 1])
            if candidate and candidate not in {"IDENTIFIER", "CUSIP"}:
                symbol_idx = i - 1
                break
    if symbol_idx is None:
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


def _parse_table(table: Tag, ticker: str, url: str) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    for tr in table.find_all("tr"):
        cells = [x.get_text(" ", strip=True) for x in tr.find_all(["th", "td"], recursive=False)]
        if not cells:
            cells = [x.get_text(" ", strip=True) for x in tr.find_all(["th", "td"])]
        rec = _row_record(cells, ticker, url)
        if rec is not None:
            records.append(rec)
    if not records:
        return pd.DataFrame()
    return pd.DataFrame(records).drop_duplicates("provider_symbol", keep="first").reset_index(drop=True)


def _same_membership(frames: list[pd.DataFrame]) -> bool:
    if not frames:
        return False
    base = set(frames[0]["provider_symbol"].astype(str))
    return all(set(x["provider_symbol"].astype(str)) == base for x in frames[1:])


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
    if expected is None:
        raise RuntimeError("official First Trust holding count not found")

    candidates: list[tuple[int, pd.DataFrame, str]] = []
    for table_idx, table in enumerate(soup.find_all("table")):
        header_text = re.sub(r"\s+", " ", table.get_text(" ", strip=True))[:500]
        low = header_text.lower()
        if not ("security name" in low and "identifier" in low and ("weight" in low or "weighting" in low)):
            continue
        frame = _parse_table(table, ticker, url)
        if not frame.empty:
            candidates.append((table_idx, frame, header_text))

    exact = [(idx, frame, header) for idx, frame, header in candidates if len(frame) == expected]
    if exact:
        exact_frames = [x[1] for x in exact]
        if len(exact_frames) > 1 and not _same_membership(exact_frames):
            detail = [(idx, len(frame)) for idx, frame, _ in exact]
            raise RuntimeError(f"ambiguous exact First Trust tables: official={expected}, candidates={detail}")
        selected_idx, out, _ = exact[0]
        selection = "EXACT_TABLE_MATCH_EXCLUDING_CURRENCY_CASH"
    else:
        table_counts = [(idx, len(frame)) for idx, frame, _ in candidates]
        raise RuntimeError(
            f"no exact First Trust holdings table: official={expected}, semantic_table_counts={table_counts}"
        )

    if out["provider_symbol"].duplicated().any():
        raise RuntimeError("duplicate provider identifiers remain after exact table selection")
    if len(out) != expected:
        raise RuntimeError(f"selected holdings count mismatch: parsed {len(out)} vs official {expected}")

    return out.reset_index(drop=True), {
        "ticker": ticker,
        "provider": "FIRSTTRUST",
        "status": "PASS",
        "rows": int(len(out)),
        "official_count": expected,
        "selected_table_index": int(selected_idx),
        "selection": selection,
        "semantic_table_counts": [{"table_index": int(idx), "rows": int(len(frame))} for idx, frame, _ in candidates],
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
        "schema": 4,
        "research_only": True,
        "candidate_count": len(TICKERS),
        "pass_count": len(passed),
        "pass_tickers": passed,
        "failures": json.loads(qa_df.loc[qa_df["status"] != "PASS"].where(pd.notna(qa_df), None).to_json(orient="records", force_ascii=False)),
        "guardrails": [
            "First Trust's official holding count explicitly excludes cash; currency/cash identifiers such as $USD/$EUR are therefore excluded before count matching.",
            "Only a semantic holdings table whose unique provider identifiers exactly equal the official excluding-cash count is accepted.",
            "Whole-page row merging is forbidden because responsive/auxiliary tables can overcount membership.",
            "No oversized table is truncated to force the official count.",
            "Provider identifiers are preserved; foreign identifiers are normalized only for market-data lookup.",
            "No Top-10 or partial table is accepted as exact membership.",
        ],
    }
    (args.output / "firsttrust_holdings_qa.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if len(passed) != len(TICKERS):
        raise RuntimeError(f"First Trust exact holdings incomplete: {passed}")


if __name__ == "__main__":
    main()
