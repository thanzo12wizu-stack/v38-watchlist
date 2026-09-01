from __future__ import annotations

import argparse
import io
import json
import re
from pathlib import Path
from typing import Any

import pandas as pd
import requests

import rotation_exact_flow_research as flowlib


GLOBALX_ETFS = {
    "AIQ", "BOTZ", "HYDR", "DRIV", "URA", "DTCR", "SHLD", "LIT", "GNOM", "COPX", "PAVE", "SIL",
}
VANECK_SLUGS = {
    "OIH": "oil-services-etf-oih",
    "SMH": "semiconductor-etf-smh",
    "MOO": "agribusiness-etf-moo",
    "SLX": "steel-etf-slx",
    "NLR": "uranium-nuclear-etf-nlr",
    "REMX": "rare-earth-strategic-metals-etf-remx",
    "PPH": "pharmaceutical-etf-pph",
    "GDX": "gold-miners-etf-gdx",
}


def clean_symbol(value: Any) -> str:
    s = str(value or "").strip().upper()
    if not s or s in {"NAN", "--", "-"}:
        return ""
    # VanEck US listings are commonly rendered as "NVDA US" in spreadsheets.
    if re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,9} US", s):
        s = s[:-3].strip()
    return s


def fetch_globalx(session: requests.Session, ticker: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    page = f"https://www.globalxetfs.com/funds/{ticker.lower()}"
    r = session.get(page, headers={"User-Agent": flowlib.UA}, timeout=45)
    r.raise_for_status()
    pattern = re.compile(rf"https://assets\.globalxetfs\.com/funds/holdings/{ticker.lower()}_full-holdings_\d{{8}}\.csv", re.I)
    hits = pattern.findall(r.text)
    if not hits:
        # Some page payloads escape slashes but retain the filename.
        m = re.search(rf"[^\"']*{ticker.lower()}_full-holdings_\d{{8}}\.csv", r.text, re.I)
        if m:
            raw = m.group(0).replace("\\/", "/")
            if raw.startswith("https://"):
                hits = [raw]
    if not hits:
        raise RuntimeError("official Full Holdings CSV URL not found on fund page")
    url = sorted(set(hits))[-1]
    h = session.get(url, headers={"User-Agent": flowlib.UA, "Accept": "text/csv,*/*"}, timeout=45)
    h.raise_for_status()
    df = pd.read_csv(io.BytesIO(h.content))
    ticker_col = next((c for c in df.columns if str(c).strip().lower() == "ticker"), None)
    name_col = next((c for c in df.columns if str(c).strip().lower() == "name"), None)
    weight_col = next((c for c in df.columns if "net assets" in str(c).lower() and "%" in str(c)), None)
    if ticker_col is None:
        raise RuntimeError(f"Ticker column missing: {list(df.columns)}")
    out = pd.DataFrame({
        "sector_etf": ticker,
        "provider_symbol": df[ticker_col].astype(str),
        "symbol": df[ticker_col].map(clean_symbol),
        "weight_pct": pd.to_numeric(df[weight_col], errors="coerce") if weight_col else None,
        "name": df[name_col].astype(str) if name_col else "",
        "source_url": url,
        "provider": "GLOBALX",
    })
    out = out[out["symbol"] != ""].drop_duplicates("symbol", keep="first")
    if len(out) < 5:
        raise RuntimeError(f"too few holdings parsed: {len(out)}")
    return out.reset_index(drop=True), {"ticker": ticker, "provider": "GLOBALX", "rows": int(len(out)), "source_url": url, "quality": "EXACT_CURRENT_MEMBERSHIP"}


def fetch_vaneck(session: requests.Session, ticker: str, slug: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    url = f"https://www.vaneck.com/us/en/investments/{slug}/downloads/holdings/"
    r = session.get(url, headers={"User-Agent": flowlib.UA, "Accept": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,*/*"}, timeout=60)
    r.raise_for_status()
    matrix = pd.read_excel(io.BytesIO(r.content), header=None, engine="openpyxl")
    header_idx = None
    for idx, row in matrix.head(40).iterrows():
        vals = {str(x).strip().lower() for x in row.tolist() if pd.notna(x)}
        if "ticker" in vals and any("holding name" in x for x in vals):
            header_idx = idx
            break
    if header_idx is None:
        raise RuntimeError("VanEck holdings XLS header not found")
    headers = [str(x).strip() if pd.notna(x) else "" for x in matrix.iloc[header_idx].tolist()]
    data = matrix.iloc[header_idx + 1:].copy()
    data.columns = headers
    ticker_col = next((c for c in data.columns if c.lower() == "ticker"), None)
    name_col = next((c for c in data.columns if "holding name" in c.lower()), None)
    weight_col = next((c for c in data.columns if "% of net" in c.lower()), None)
    if ticker_col is None:
        raise RuntimeError("VanEck Ticker column missing")
    out = pd.DataFrame({
        "sector_etf": ticker,
        "provider_symbol": data[ticker_col].astype(str),
        "symbol": data[ticker_col].map(clean_symbol),
        "weight_pct": pd.to_numeric(data[weight_col], errors="coerce") if weight_col else None,
        "name": data[name_col].astype(str) if name_col else "",
        "source_url": url,
        "provider": "VANECK",
    })
    out = out[out["symbol"] != ""].drop_duplicates("symbol", keep="first")
    if len(out) < 5:
        raise RuntimeError(f"too few holdings parsed: {len(out)}")
    return out.reset_index(drop=True), {"ticker": ticker, "provider": "VANECK", "rows": int(len(out)), "source_url": url, "quality": "EXACT_CURRENT_MEMBERSHIP"}


def main() -> None:
    ap = argparse.ArgumentParser(description="Expand Theme56 official current holdings beyond SSGA/iShares")
    ap.add_argument("--output", type=Path, default=Path("leadership/research/rotation_theme56_holdings_expansion"))
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    frames: list[pd.DataFrame] = []
    rows: list[dict[str, Any]] = []

    for ticker in sorted(GLOBALX_ETFS):
        try:
            h, d = fetch_globalx(session, ticker)
            frames.append(h)
            rows.append({**d, "status": "PASS"})
        except Exception as exc:
            rows.append({"ticker": ticker, "provider": "GLOBALX", "status": "FAIL", "error": f"{type(exc).__name__}: {exc}"})
    for ticker, slug in sorted(VANECK_SLUGS.items()):
        try:
            h, d = fetch_vaneck(session, ticker, slug)
            frames.append(h)
            rows.append({**d, "status": "PASS"})
        except Exception as exc:
            rows.append({"ticker": ticker, "provider": "VANECK", "status": "FAIL", "error": f"{type(exc).__name__}: {exc}"})

    qa = pd.DataFrame(rows).sort_values(["provider", "ticker"])
    qa.to_csv(args.output / "holdings_expansion_qa.csv", index=False)
    if frames:
        pd.concat(frames, ignore_index=True).to_csv(args.output / "exact_current_holdings_expansion.csv", index=False)
    passed = qa[qa["status"] == "PASS"]
    report = {
        "schema": 1,
        "research_only": True,
        "candidate_count": int(len(qa)),
        "pass_count": int(len(passed)),
        "pass_tickers": passed["ticker"].tolist(),
        "failures": qa.loc[qa["status"] != "PASS"].where(pd.notna(qa), None).to_dict("records"),
        "guardrail": "This expands only exact current membership for Internals. It does not claim Exact Flow availability.",
    }
    (args.output / "holdings_expansion_qa.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
