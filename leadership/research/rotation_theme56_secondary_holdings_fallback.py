from __future__ import annotations

import io
import json
import re
import time
from pathlib import Path
from typing import Any

import pandas as pd
import requests

import rotation_theme56_etfcom_holdings as etfcom
import rotation_theme56_holdings_expansion as hx

TARGETS = ["WCLD", "BLOK", "PHO", "TAN", "IBUY", "PKB", "BOAT", "WGMI", "JETS", "PEJ"]
SA_URL = "https://stockanalysis.com/etf/{ticker}/holdings/"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122 Safari/537.36"
ETF_HEADERS_500 = {
    "User-Agent": UA,
    "Accept": "application/json,text/plain,*/*",
    "Origin": "https://www.etf.com",
    "Referer": "https://www.etf.com/",
    "x-limit": "500",
}

EXCHANGE_PREFIX = {
    "HKG": ".HK", "TYO": ".T", "TSE": ".T", "CPH": ".CO", "TSX": ".TO",
    "EPA": ".PA", "BME": ".MC", "OSL": ".OL", "TPE": ".TW", "KRX": ".KS",
    "ASX": ".AX", "LON": ".L", "ETR": ".DE", "TLV": ".TA", "STO": ".ST",
    "SWX": ".SW", "AMS": ".AS", "MIL": ".MI", "HEL": ".HE", "SGX": ".SI",
    "BKK": ".BK", "SAO": ".SA", "KUL": ".KL", "IDX": ".JK",
}


def normalize_sa_symbol(value: Any) -> str:
    raw = str(value or "").strip().upper()
    if not raw or raw in {"N/A", "NAN", "--", "-"}:
        return ""
    m = re.fullmatch(r"([A-Z]{2,5}):\s*(.+)", raw)
    if m:
        exch, base = m.group(1), m.group(2).strip()
        suffix = EXCHANGE_PREFIX.get(exch)
        if suffix:
            if exch == "HKG" and base.isdigit():
                base = base.zfill(4)
            base = base.replace("/", "-")
            if re.fullmatch(r"[A-Z0-9]+\.[A-Z]", base):
                base = base.replace(".", "-")
            return base + suffix
        if exch in {"NASDAQ", "NYSE", "NYSEARCA", "AMEX", "CBOE"}:
            return hx.clean_symbol(base)
    return hx.clean_symbol(raw)


def fetch_etfcom_500(session: requests.Session, ticker: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    url = etfcom.API_URL.format(ticker=ticker)
    last_exc: Exception | None = None
    for attempt in range(4):
        try:
            r = session.get(url, headers=ETF_HEADERS_500, timeout=35)
            r.raise_for_status()
            records = etfcom._find_record_list(r.json())
            if not records:
                raise RuntimeError("no ETF.com securities rows")
            rows = []
            for rec in records:
                raw_symbol = etfcom._value(rec, ("symbol", "ticker", "securitySymbol", "holdingSymbol"))
                symbol = hx.clean_symbol(raw_symbol)
                if not symbol:
                    continue
                rows.append({
                    "sector_etf": ticker,
                    "provider_symbol": str(raw_symbol or "").strip(),
                    "symbol": symbol,
                    "weight_pct": etfcom._num(etfcom._value(rec, ("weight", "weighting", "portfolioWeight", "percentage"))),
                    "name": str(etfcom._value(rec, ("name", "securityName", "holdingName", "description")) or "").strip(),
                    "source_url": url,
                    "provider": "ETFCOM_XLIMIT500",
                    "quality": "SECONDARY_CURRENT_MEMBERSHIP_CANDIDATE",
                })
            out = pd.DataFrame(rows)
            out = out[out["symbol"] != ""].drop_duplicates("symbol", keep="first").reset_index(drop=True)
            if len(out) < 5:
                raise RuntimeError(f"ETF.com x-limit=500 unexpectedly short: {len(out)}")
            return out, {"ticker": ticker, "rows": len(out), "source_url": url}
        except Exception as exc:
            last_exc = exc
            time.sleep(1.0 * (attempt + 1))
    raise RuntimeError(f"ETF.com x-limit=500 failed for {ticker}: {last_exc}")


def fetch_stockanalysis(session: requests.Session, ticker: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    url = SA_URL.format(ticker=ticker.lower())
    r = session.get(url, headers={"User-Agent": UA, "Accept": "text/html,*/*"}, timeout=35)
    r.raise_for_status()
    text = r.text
    total = None
    patterns = [
        r"total of\s+([0-9,]+)\s+individual holdings",
        r"Total Holdings\s*</[^>]+>\s*<[^>]+>\s*([0-9,]+)",
        r"Holdings\s*</[^>]+>\s*<[^>]+>\s*([0-9,]+)",
    ]
    for p in patterns:
        m = re.search(p, text, flags=re.I | re.S)
        if m:
            total = int(m.group(1).replace(",", ""))
            break
    tables = pd.read_html(io.StringIO(text))
    best = None
    for df in tables:
        cols = [str(c).strip().lower() for c in df.columns]
        if "symbol" in cols and "name" in cols and len(df) >= 5:
            if best is None or len(df) > len(best):
                best = df
    if best is None:
        raise RuntimeError("StockAnalysis holdings table not found")
    colmap = {str(c).strip().lower(): c for c in best.columns}
    s_col = colmap["symbol"]
    n_col = colmap.get("name")
    w_col = colmap.get("weight")
    out = pd.DataFrame({
        "sector_etf": ticker,
        "provider_symbol": best[s_col].astype(str),
        "symbol": best[s_col].map(normalize_sa_symbol),
        "weight_pct": pd.to_numeric(best[w_col].astype(str).str.replace("%", "", regex=False), errors="coerce") if w_col else None,
        "name": best[n_col].astype(str) if n_col else "",
        "source_url": url,
        "provider": "STOCKANALYSIS_FINNHUB_VISIBLE",
        "quality": "VISIBLE_TOP_HOLDINGS_CANDIDATE",
    })
    out = out[out["symbol"] != ""].drop_duplicates("symbol", keep="first").reset_index(drop=True)
    if total is None:
        raise RuntimeError("StockAnalysis total holdings count not found")
    return out, {"ticker": ticker, "declared_total": total, "visible_rows": len(out), "source_url": url}


def main() -> None:
    outdir = Path("leadership/research/rotation_theme56_secondary_holdings_fallback")
    outdir.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    frames = []
    qa = []
    for ticker in TARGETS:
        try:
            e, ed = fetch_etfcom_500(s, ticker)
            a, ad = fetch_stockanalysis(s, ticker)
            total = int(ad["declared_total"])
            e_ratio = len(e) / total if total else 0.0
            a_ratio = len(a) / total if total else 0.0
            union = pd.concat([e, a], ignore_index=True).drop_duplicates("symbol", keep="first")
            union_ratio = len(union) / total if total else 0.0

            method = None
            selected = None
            # Prefer one internally consistent source; use a union only when neither source alone
            # reaches the pre-existing 80% Internal membership threshold.
            if 0.80 <= e_ratio <= 1.10:
                selected = e.copy()
                method = "ETFCOM_XLIMIT500"
            elif 0.80 <= a_ratio <= 1.10:
                selected = a.copy()
                method = "STOCKANALYSIS_VISIBLE"
            elif 0.80 <= union_ratio <= 1.10:
                selected = union.copy()
                method = "ETFCOM_PLUS_STOCKANALYSIS"

            status = "PASS" if selected is not None and total >= 5 else "FAIL"
            if selected is not None:
                ratio = len(selected) / total
                selected["sector_etf"] = ticker
                selected["provider"] = method
                selected["quality"] = "VALIDATED_CURRENT_MEMBERSHIP_80PCT_PLUS"
                selected["declared_total_holdings"] = total
                selected["estimated_membership_coverage"] = ratio
                frames.append(selected)
            else:
                ratio = max(e_ratio, a_ratio, union_ratio)

            row = {
                "ticker": ticker,
                "status": status,
                "selected_method": method,
                "selected_rows": None if selected is None else len(selected),
                "etfcom_rows": len(e),
                "stockanalysis_visible_rows": len(a),
                "union_rows": len(union),
                "declared_total": total,
                "etfcom_coverage": e_ratio,
                "stockanalysis_coverage": a_ratio,
                "union_coverage": union_ratio,
                "estimated_coverage": ratio,
                "etfcom_source": ed.get("source_url"),
                "count_source": ad.get("source_url"),
            }
            qa.append(row)
        except Exception as exc:
            qa.append({"ticker": ticker, "status": "FAIL", "error": f"{type(exc).__name__}: {exc}"})
        print(json.dumps(qa[-1], ensure_ascii=False), flush=True)
        time.sleep(0.2)

    qdf = pd.DataFrame(qa)
    qdf.to_csv(outdir / "secondary_holdings_qa.csv", index=False)
    if frames:
        pd.concat(frames, ignore_index=True).drop_duplicates(["sector_etf", "symbol"]).to_csv(outdir / "validated_current_membership_fallback.csv", index=False)
    passed = qdf.loc[qdf["status"] == "PASS", "ticker"].tolist()
    report = {
        "schema": 2,
        "research_only": True,
        "candidate_count": len(TARGETS),
        "pass_count": len(passed),
        "pass_tickers": passed,
        "rows": qa,
        "quality_contract": "Fallback membership is accepted only when a current ETF.com x-limit=500 list, StockAnalysis/Finnhub visible list, or their conservative union covers 80%-110% of an independently declared current total holdings count. It is not labeled issuer-exact.",
        "guardrails": [
            "Issuer exact current holdings remain preferred.",
            "The existing 80% constituent-price coverage requirement is not lowered.",
            "A selected membership set exceeding 110% of the declared current holding count is rejected.",
            "No price/volume inference is used to manufacture membership.",
            "DRAM is excluded from this fallback because its short history is the separately accepted exception.",
        ],
    }
    (outdir / "secondary_holdings_qa.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    if len(passed) != len(TARGETS):
        raise RuntimeError(f"secondary holdings fallback incomplete: {passed}")


if __name__ == "__main__":
    main()
