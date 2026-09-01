from __future__ import annotations

import argparse
import io
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122 Safari/537.36"
SA_URL = "https://stockanalysis.com/etf/dram/holdings/"
TV_URL = "https://scanner.tradingview.com/global/scan"
TV_EXCHANGES = ("CBOE", "AMEX", "NYSEARCA", "NYSE", "NASDAQ")
NON_EQUITY_WORDS = (
    "TREASURY", "SWAP", "SOUTH KOREA WON", "CHINESE YUAN", "TAIWAN DOLLAR",
    "CASH", "CURRENCY", "MONEY MARKET",
)


def normalize_symbol(raw: Any) -> str:
    s = re.sub(r"\s+", " ", str(raw or "").strip().upper())
    if not s or s in {"N/A", "NAN", "--", "-"}:
        return ""
    m = re.fullmatch(r"KRX:\s*(\d{4,6})", s)
    if m:
        return m.group(1).zfill(6) + ".KS"
    for old, new in ((".JP", ".T"), (".TT", ".TW"), (".C1", ".SS")):
        if s.endswith(old):
            return s[: -len(old)] + new
    if re.fullmatch(r"[A-Z][A-Z0-9.-]{0,12}", s):
        return s.replace(".", "-") if "." in s else s
    return ""


def fetch_holdings(session: requests.Session) -> tuple[pd.DataFrame, dict[str, Any]]:
    r = session.get(
        SA_URL,
        headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,*/*"},
        timeout=40,
    )
    r.raise_for_status()
    text = r.text
    asof_match = re.search(r"As\s+of\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})", text, flags=re.I)
    if not asof_match:
        raise RuntimeError("DRAM StockAnalysis holdings as-of date missing")
    asof = pd.to_datetime(asof_match.group(1), errors="raise").date()
    age_days = (date.today() - asof).days
    if age_days < -2 or age_days > 7:
        raise RuntimeError(f"DRAM holdings stale: asof={asof} age_days={age_days}")

    total_match = re.search(r"total\s+of\s+([0-9,]+)\s+individual\s+holdings", text, flags=re.I)
    declared_total = int(total_match.group(1).replace(",", "")) if total_match else None
    tables = pd.read_html(io.StringIO(text))
    best: pd.DataFrame | None = None
    for df in tables:
        cols = {str(c).strip().lower(): c for c in df.columns}
        if "symbol" in cols and "name" in cols and len(df) >= 10 and (best is None or len(df) > len(best)):
            best = df
    if best is None:
        raise RuntimeError("DRAM holdings table not found")

    cm = {str(c).strip().lower(): c for c in best.columns}
    weight_col = next((c for k, c in cm.items() if "weight" in k), None)
    rows: list[dict[str, Any]] = []
    for _, rec in best.iterrows():
        raw_symbol = str(rec.get(cm["symbol"]) or "").strip()
        name = str(rec.get(cm["name"]) or "").strip()
        upper_name = name.upper()
        if not name or any(word in upper_name for word in NON_EQUITY_WORDS):
            continue
        symbol = normalize_symbol(raw_symbol)
        if not symbol or ".TRS" in raw_symbol.upper():
            continue
        weight = None
        if weight_col is not None:
            weight = pd.to_numeric(
                str(rec.get(weight_col)).replace("%", "").replace(",", ""),
                errors="coerce",
            )
        rows.append({
            "sector_etf": "DRAM",
            "provider_symbol": raw_symbol,
            "symbol": symbol,
            "weight_pct": None if pd.isna(weight) else float(weight),
            "name": name,
            "membership_asof": str(asof),
            "source_url": SA_URL,
            "provider": "STOCKANALYSIS_FINNHUB_CURRENT",
            "quality": "SUPPLEMENTAL_CURRENT_EQUITY_ONLY",
        })
    out = pd.DataFrame(rows).drop_duplicates("symbol", keep="first")
    if len(out) < 8:
        raise RuntimeError(f"DRAM direct-equity membership too small: {len(out)}")
    return out.reset_index(drop=True), {
        "membership_asof": str(asof),
        "membership_age_days": age_days,
        "declared_total_holdings": declared_total,
        "direct_equity_rows": int(len(out)),
        "source_url": SA_URL,
        "quality": "SUPPLEMENTAL_CURRENT_EQUITY_ONLY",
        "note": "Direct listed equities only. Treasury collateral, currencies and total-return swaps are excluded from the supplemental Internal calculation.",
    }


def fetch_tradingview_flow_1m(session: requests.Session) -> dict[str, Any]:
    payload = {
        "symbols": {"tickers": [f"{ex}:DRAM" for ex in TV_EXCHANGES], "query": {"types": []}},
        "columns": ["name", "exchange", "aum", "fund_flows.1M", "nav"],
    }
    r = session.post(
        TV_URL,
        headers={
            "User-Agent": UA,
            "Accept": "application/json,*/*",
            "Content-Type": "application/json",
            "Origin": "https://www.tradingview.com",
            "Referer": "https://www.tradingview.com/",
        },
        json=payload,
        timeout=45,
    )
    r.raise_for_status()
    candidates: list[dict[str, Any]] = []
    for item in r.json().get("data") or []:
        vals = item.get("d") or []
        if len(vals) < 4 or str(vals[0] or "").upper() != "DRAM":
            continue
        aum = pd.to_numeric(vals[2], errors="coerce")
        flow = pd.to_numeric(vals[3], errors="coerce")
        if pd.notna(aum) and float(aum) > 0 and pd.notna(flow):
            candidates.append({
                "symbol_ref": item.get("s"),
                "exchange": vals[1],
                "aum_usd": float(aum),
                "flow_1m_usd": float(flow),
                "nav": None if len(vals) < 5 or pd.isna(pd.to_numeric(vals[4], errors="coerce")) else float(vals[4]),
            })
    if not candidates:
        raise RuntimeError("TradingView DRAM fund_flows.1M unavailable")
    row = max(candidates, key=lambda x: x["aum_usd"])
    row["flow_1m_pct_aum"] = 100.0 * row["flow_1m_usd"] / row["aum_usd"]
    row["flow_window"] = "1M"
    row["flow_provider"] = "TRADINGVIEW_FUND_FLOWS_1M"
    row["flow_quality"] = "SUPPLEMENTAL_ACTUAL_FUND_FLOW_1M"
    row["note"] = "TradingView fund_flows.1M field. It is displayed as 1M and is not relabeled as the validated Theme56 20-trading-day Flow series."
    return row


def main() -> None:
    ap = argparse.ArgumentParser(description="Build DRAM supplemental current membership and 1M actual fund-flow context")
    ap.add_argument("--output", type=Path, default=Path("leadership/research/rotation_theme56_dram_supplement"))
    args = ap.parse_args()

    session = requests.Session()
    holdings, holdings_qa = fetch_holdings(session)
    flow = fetch_tradingview_flow_1m(session)
    args.output.mkdir(parents=True, exist_ok=True)
    holdings.to_csv(args.output / "dram_current_equity_holdings.csv", index=False)
    report = {
        "schema": 1,
        "research_only": True,
        "ticker": "DRAM",
        "inception_date": "2026-04-02",
        "rs189_pending": True,
        "holdings": holdings_qa,
        "flow": flow,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "guardrails": [
            "This supplement does not change the existing 55-theme Price, Internal or 20D Flow rankings.",
            "DRAM short price history remains separate from the RS189-based composite until enough observations exist.",
            "DRAM Internal is supplemental and uses direct listed equities only; derivatives/collateral/currencies are excluded.",
            "DRAM 1M Flow is an actual fund-flow field and remains explicitly labeled 1M; it is not substituted into the validated 20D Flow ranking or state rules.",
        ],
    }
    (args.output / "dram_supplement.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "ticker": "DRAM",
        "membership_asof": holdings_qa["membership_asof"],
        "direct_equity_rows": holdings_qa["direct_equity_rows"],
        "flow_1m_usd": flow["flow_1m_usd"],
        "flow_1m_pct_aum": flow["flow_1m_pct_aum"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
