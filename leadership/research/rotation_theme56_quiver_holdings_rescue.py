from __future__ import annotations

import argparse
import io
import json
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pandas as pd
import requests
from bs4 import BeautifulSoup

import rotation_theme56_holdings_expansion as hx

FUNDS = {
    "WCLD": "WisdomTree Cloud Computing Fund",
    "BLOK": "Amplify Blockchain Technology ETF",
    "PHO": "Invesco Water Resources ETF",
    "TAN": "Invesco Solar ETF",
    "IBUY": "Amplify Online Retail ETF",
    "PKB": "Invesco Building & Construction ETF",
    "BOAT": "SonicShares Global Shipping ETF",
    "WGMI": "CoinShares Bitcoin Mining ETF",
    "JETS": "U.S. Global Jets ETF",
    "PEJ": "Invesco Leisure and Entertainment ETF",
}

BASE = "https://www.quiverquant.com/etf/{fund}"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122 Safari/537.36"
HEADERS = {"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,*/*"}

CASH_NAMES = (
    "US DOLLARS", "JAPANESE YEN", "SWEDISH KRONA", "EURO", "POUND STERLING",
    "OTHER ASSETS AND LIABILITIES", "CASH & OTHER", "CASH", "SECURITIES LENDING",
    "COLLATERAL", "CURRENCY",
)
MONEY_MARKET_SUFFIXES = ("XX",)


def parse_declared_count(text: str) -> int:
    m = re.search(r"ETF currently has .*? and\s+([0-9,]+)\s+holdings\b", text, flags=re.I)
    if not m:
        m = re.search(r"\b([0-9,]+)\s+holdings\b", text, flags=re.I)
    if not m:
        raise RuntimeError("declared holdings count not found")
    return int(m.group(1).replace(",", ""))


def parse_last_updated_age_days(text: str) -> float:
    m = re.search(r"Last Updated:\s*([^\n]+)", text, flags=re.I)
    if not m:
        raise RuntimeError("Last Updated marker not found")
    raw = re.sub(r"\s+", " ", m.group(1)).strip().lower()
    n = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(minute|hour|day|week)s?\s+ago", raw)
    if not n:
        if raw.startswith("just now"):
            return 0.0
        raise RuntimeError(f"unparsed Last Updated value: {raw}")
    value = float(n.group(1))
    unit = n.group(2)
    if unit == "minute":
        return value / 1440.0
    if unit == "hour":
        return value / 24.0
    if unit == "day":
        return value
    return value * 7.0


def normalize_quiver_symbol(value: Any) -> str:
    raw = re.sub(r"\s+", " ", str(value or "").strip().upper())
    if not raw or raw in {"NAN", "N/A", "--", "-"}:
        return ""
    # Turkish provider notation: THYAO.E.IS / PGSUS.E.IS -> Yahoo THYAO.IS / PGSUS.IS.
    raw = re.sub(r"\.E\.IS$", ".IS", raw)
    # Quiver may render local class shares with a space before the class letter.
    # Yahoo uses a hyphen before the class letter while retaining the exchange suffix.
    m = re.fullmatch(r"([A-Z0-9]+)\s+([A-Z])\.(CO|ST|TO)$", raw)
    if m:
        raw = f"{m.group(1)}-{m.group(2)}.{m.group(3)}"
    # Canadian class shares such as BBD.B.TO -> BBD-B.TO.
    m = re.fullmatch(r"([A-Z0-9]+)\.([A-Z])\.(TO|V)$", raw)
    if m:
        raw = f"{m.group(1)}-{m.group(2)}.{m.group(3)}"
    return hx.clean_symbol(raw)


def is_non_equity(symbol: str, name: str) -> bool:
    up = str(name or "").upper().strip()
    if not symbol:
        return True
    if any(x in up for x in CASH_NAMES):
        return True
    if symbol.endswith(MONEY_MARKET_SUFFIXES) and ("MONEY" in up or "GOV" in up or "SHORT" in up or "INSTL" in up):
        return True
    return False


def choose_holdings_table(tables: list[pd.DataFrame]) -> pd.DataFrame:
    candidates: list[pd.DataFrame] = []
    for df in tables:
        cols = {str(c).strip().lower(): c for c in df.columns}
        if "ticker" in cols and "name" in cols and any("est" in k and "value" in k for k in cols):
            candidates.append(df)
    if not candidates:
        raise RuntimeError("Quiver last-reported holdings table not found")
    return max(candidates, key=len)


def fetch_current(session: requests.Session, ticker: str, fund: str, max_age_days: float) -> tuple[pd.DataFrame, dict[str, Any]]:
    url = BASE.format(fund=quote(fund, safe=""))
    r = session.get(url, headers=HEADERS, timeout=45)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    text = soup.get_text("\n", strip=True)
    declared = parse_declared_count(text)
    age_days = parse_last_updated_age_days(text)
    if age_days > max_age_days:
        raise RuntimeError(f"Quiver holdings stale: age_days={age_days:.2f}")

    table = choose_holdings_table(pd.read_html(io.StringIO(r.text)))
    cmap = {str(c).strip().lower(): c for c in table.columns}
    tcol = cmap["ticker"]
    ncol = cmap["name"]
    vcol = next(c for k, c in cmap.items() if "est" in k and "value" in k)

    rows: list[dict[str, Any]] = []
    for _, rec in table.iterrows():
        provider_symbol = str(rec.get(tcol) or "").strip()
        name = str(rec.get(ncol) or "").strip()
        symbol = normalize_quiver_symbol(provider_symbol)
        if is_non_equity(symbol, name):
            continue
        rows.append({
            "sector_etf": ticker,
            "provider_symbol": provider_symbol,
            "symbol": symbol,
            "weight_pct": None,
            "name": name,
            "source_url": url,
            "provider": "QUIVER_CURRENT_FULL_LIST",
            "quality": "VALIDATED_CURRENT_FULL_LIST_SECONDARY",
            "source_last_updated_age_days": age_days,
            "declared_total_holdings": declared,
            "estimated_value": str(rec.get(vcol) or ""),
        })
    out = pd.DataFrame(rows)
    if out.empty:
        raise RuntimeError("Quiver current table produced zero equity rows")
    out = out.drop_duplicates("symbol", keep="first").reset_index(drop=True)
    ratio = len(out) / max(declared, 1)
    # Quiver's declared total may include cash/currency/money-market rows, so equity rows can be
    # slightly below the headline holding count. Require a genuinely broad current membership set.
    if len(out) < 10 or ratio < 0.75 or ratio > 1.05:
        raise RuntimeError(f"current equity coverage rejected: {len(out)}/{declared}={ratio:.3f}")
    return out, {
        "ticker": ticker,
        "status": "PASS",
        "rows": int(len(out)),
        "declared_total": declared,
        "coverage_vs_declared": ratio,
        "source_last_updated_age_days": age_days,
        "source_url": url,
        "quality": "VALIDATED_CURRENT_FULL_LIST_SECONDARY",
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Rescue the final ten Theme56 current memberships from Quiver full holdings pages")
    ap.add_argument("--output", type=Path, default=Path("leadership/research/rotation_theme56_secondary_holdings_fallback"))
    ap.add_argument("--max-age-days", type=float, default=14.0)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    frames: list[pd.DataFrame] = []
    qa: list[dict[str, Any]] = []
    for ticker, fund in FUNDS.items():
        try:
            df, diag = fetch_current(session, ticker, fund, args.max_age_days)
            frames.append(df)
            qa.append(diag)
        except Exception as exc:
            qa.append({"ticker": ticker, "status": "FAIL", "error": f"{type(exc).__name__}: {exc}"})
        print(json.dumps(qa[-1], ensure_ascii=False), flush=True)
        time.sleep(0.15)

    qdf = pd.DataFrame(qa)
    qdf.to_csv(args.output / "secondary_holdings_qa.csv", index=False)
    if frames:
        pd.concat(frames, ignore_index=True).drop_duplicates(["sector_etf", "symbol"]).to_csv(
            args.output / "validated_current_membership_fallback.csv", index=False
        )
    passed = qdf.loc[qdf["status"] == "PASS", "ticker"].tolist()
    report = {
        "schema": 5,
        "research_only": True,
        "candidate_count": len(FUNDS),
        "pass_count": len(passed),
        "pass_tickers": passed,
        "rows": qa,
        "quality_contract": "Issuer-exact current holdings remain preferred. Quiver is used only for the ten unresolved funds and only when its server-rendered full reported holdings page is fresh and broadly matches its own declared holding count.",
        "guardrails": [
            "This fallback is labeled VALIDATED_CURRENT_FULL_LIST_SECONDARY, never issuer-exact.",
            "Quiver membership older than the configured freshness guard is rejected.",
            "Cash, currencies and money-market collateral are excluded from constituent Internals.",
            "Full Stack retains its independent 80% constituent market-price coverage requirement.",
            "No stale ETF.com membership or price/volume inference is used to manufacture current membership.",
            "DRAM is not part of this rescue; its short history is the accepted exception.",
        ],
    }
    (args.output / "secondary_holdings_qa.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    if len(passed) != len(FUNDS):
        raise RuntimeError(f"Quiver current holdings rescue incomplete: {passed}")


if __name__ == "__main__":
    main()
