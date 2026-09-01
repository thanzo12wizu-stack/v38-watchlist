from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd
import requests

import rotation_theme56_holdings_expansion as hx

TICKERS = ["PHO", "TAN", "PKB", "PEJ"]
URL = "https://dng-api.invesco.com/cache/v1/accounts/en_US/shareclasses/{ticker}/holdings/fund?idType=ticker&interval=daily&productType=ETF&loadType=initial"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://www.invesco.com",
    "Referer": "https://www.invesco.com/",
}

WEIGHT_KEYS = ("percentageOfTotalNetAssets", "weightPercentage", "weight", "percentage", "percentOfPortfolio")
TICKER_KEYS = ("ticker", "symbol", "holdingTicker", "asset")
NAME_KEYS = ("issuerName", "name", "securityName", "holdingName")


def find_rows(data: Any, depth: int = 0) -> list[dict[str, Any]] | None:
    if depth > 8 or data is None:
        return None
    if isinstance(data, list):
        rows = [r for r in data if isinstance(r, dict)]
        if rows:
            def holding_like(r: dict[str, Any]) -> bool:
                return any(r.get(k) not in (None, "") for k in TICKER_KEYS) and any(r.get(k) is not None for k in WEIGHT_KEYS)
            if sum(holding_like(r) for r in rows) >= max(1, len(rows)//2):
                return rows
        for item in data:
            found = find_rows(item, depth + 1)
            if found:
                return found
    elif isinstance(data, dict):
        for key in ("holdings", "fundHoldings", "holding", "data", "items", "rows"):
            if key in data:
                found = find_rows(data[key], depth + 1)
                if found:
                    return found
        for value in data.values():
            if isinstance(value, (dict, list)):
                found = find_rows(value, depth + 1)
                if found:
                    return found
    return None


def first(row: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for k in keys:
        if row.get(k) not in (None, ""):
            return row.get(k)
    return None


def fetch_one(session: requests.Session, ticker: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    url = URL.format(ticker=ticker)
    r = session.get(url, headers=HEADERS, timeout=45)
    r.raise_for_status()
    obj = r.json()
    rows = find_rows(obj)
    if not rows:
        raise RuntimeError("DNG response has no holding-like rows")
    out_rows = []
    for row in rows:
        raw = str(first(row, TICKER_KEYS) or "").strip().upper()
        sym = hx.clean_symbol(raw)
        weight = pd.to_numeric(first(row, WEIGHT_KEYS), errors="coerce")
        name = str(first(row, NAME_KEYS) or raw).strip()
        if not sym or pd.isna(weight) or float(weight) <= 0:
            continue
        if raw.startswith(("CASH", "USD")) or "RECEIVABLE" in raw or "PAYABLE" in raw or "DEPOSIT" in raw:
            continue
        out_rows.append({
            "sector_etf": ticker,
            "provider_symbol": raw,
            "symbol": sym,
            "weight_pct": float(weight),
            "name": name,
            "source_url": url,
            "provider": "INVESCO_DNG",
        })
    out = pd.DataFrame(out_rows).drop_duplicates("symbol", keep="first")
    if len(out) < 15:
        raise RuntimeError(f"DNG holdings unexpectedly short: {len(out)}")
    total_weight = float(pd.to_numeric(out["weight_pct"], errors="coerce").sum())
    if not (90 <= total_weight <= 110):
        # Some payloads may express fraction weights. Normalize only when clearly 0-1 scale.
        if 0.90 <= total_weight <= 1.10:
            out["weight_pct"] = pd.to_numeric(out["weight_pct"], errors="coerce") * 100.0
            total_weight *= 100.0
        else:
            raise RuntimeError(f"DNG total weight suspicious: {total_weight}")
    return out.reset_index(drop=True), {
        "ticker": ticker,
        "status": "PASS",
        "provider": "INVESCO_DNG",
        "rows": int(len(out)),
        "weight_sum": total_weight,
        "source_url": url,
        "quality": "EXACT_CURRENT_MEMBERSHIP",
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path("leadership/research/rotation_theme56_invesco_dng"))
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    frames = []
    qa = []
    for ticker in TICKERS:
        try:
            df, diag = fetch_one(session, ticker)
            frames.append(df)
            qa.append(diag)
        except Exception as exc:
            qa.append({"ticker": ticker, "status": "FAIL", "provider": "INVESCO_DNG", "error": f"{type(exc).__name__}: {exc}"})
        print(json.dumps(qa[-1], ensure_ascii=False), flush=True)
    qdf = pd.DataFrame(qa)
    qdf.to_csv(args.output / "invesco_dng_qa.csv", index=False)
    if frames:
        pd.concat(frames, ignore_index=True).drop_duplicates(["sector_etf","symbol"]).to_csv(args.output / "invesco_exact_current_holdings.csv", index=False)
    passed = qdf.loc[qdf["status"] == "PASS", "ticker"].tolist()
    report = {"schema": 1, "research_only": True, "pass_count": len(passed), "pass_tickers": passed, "qa": json.loads(qdf.where(pd.notna(qdf), None).to_json(orient="records", force_ascii=False))}
    (args.output / "invesco_dng_qa.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if len(passed) != len(TICKERS):
        raise RuntimeError(f"Invesco DNG incomplete: {len(passed)}/{len(TICKERS)}")

if __name__ == "__main__":
    main()
