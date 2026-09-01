from __future__ import annotations

import io
import json
import re
import time
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import requests

import rotation_theme56_etfcom_holdings as etfcom
import rotation_theme56_holdings_expansion as hx

TARGETS = ["WCLD", "BLOK", "PHO", "TAN", "IBUY", "PKB", "BOAT", "WGMI", "JETS", "PEJ"]
SA_URL = "https://stockanalysis.com/etf/{ticker}/holdings/"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122 Safari/537.36"
BASE_HEADERS = {"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,application/json,*/*"}

# Current full-list secondary source. It is used only when issuer-exact membership is unavailable.
# The page must expose a recent as-of date and a full holdings table; stale ETF.com holdings are
# never accepted as membership. ETF.com may be consulted only to resolve a foreign exchange suffix.
CMC_SLUGS = {
    "WCLD": ["wisdomtree-cloud-computing-fund"],
    "BLOK": ["amplify-transformational-data-sharing-etf", "amplify-transformational-data-sharing-etf-blok"],
    "PHO": ["invesco-water-resources-etf"],
    "TAN": ["invesco-solar-etf"],
    "IBUY": ["amplify-online-retail-etf", "amplify-online-retail-etf-ibuy"],
    "PKB": ["invesco-building-construction-etf", "invesco-building-and-construction-etf"],
    "BOAT": ["sonicshares-global-shipping-etf"],
    "WGMI": ["coinshares-bitcoin-miners-etf", "coinshares-bitcoin-mining-etf"],
    "JETS": ["us-global-jets-etf"],
    "PEJ": ["invesco-leisure-and-entertainment-etf", "invesco-dynamic-leisure-and-entertainment-etf"],
}

EXCHANGE_PREFIX = {
    "HKG": ".HK", "TYO": ".T", "TSE": ".T", "CPH": ".CO", "TSX": ".TO",
    "EPA": ".PA", "BME": ".MC", "OSL": ".OL", "TPE": ".TW", "KRX": ".KS",
    "ASX": ".AX", "LON": ".L", "ETR": ".DE", "TLV": ".TA", "STO": ".ST",
    "SWX": ".SW", "AMS": ".AS", "MIL": ".MI", "HEL": ".HE", "SGX": ".SI",
    "BKK": ".BK", "SAO": ".SA", "KUL": ".KL", "IDX": ".JK",
}
BLOOMBERG_SUFFIX = {
    "US": "", "HK": ".HK", "JP": ".T", "JT": ".T", "KS": ".KS", "KQ": ".KQ",
    "CN": ".TO", "FP": ".PA", "GR": ".DE", "GY": ".DE", "SW": ".SW", "NA": ".AS",
    "LN": ".L", "IM": ".MI", "DC": ".CO", "AU": ".AX", "NO": ".OL", "SS": ".ST",
    "SP": ".SI", "TB": ".BK", "TT": ".TW", "IT": ".TA", "TI": ".IS", "SM": ".MC",
    "SJ": ".JO", "FH": ".HE", "PL": ".LS", "BZ": ".SA", "MK": ".KL", "IJ": ".JK",
    "MM": ".MX",
}
CASH_WORDS = ("CASH", "CURRENCY", "PENDING DIVIDEND", "TREASURY OBLIGATION", "MONEY MARKET")


def normalize_name(value: Any) -> str:
    s = str(value or "").upper()
    s = re.sub(r"\b(INCORPORATED|INC|CORPORATION|CORP|LIMITED|LTD|PLC|SA|AG|NV|CO|THE|CLASS|ORDINARY|SHARES?)\b", " ", s)
    return re.sub(r"[^A-Z0-9]+", "", s)


def normalize_sa_symbol(value: Any) -> str:
    raw = str(value or "").strip().upper()
    if not raw or raw in {"N/A", "NAN", "--", "-"}:
        return ""
    m = re.fullmatch(r"([A-Z]{2,8}):\s*(.+)", raw)
    if m:
        exch, base = m.group(1), m.group(2).strip()
        suffix = EXCHANGE_PREFIX.get(exch)
        if suffix:
            if exch == "HKG" and base.isdigit():
                base = base.zfill(4)
            return base.replace("/", "-") + suffix
        if exch in {"NASDAQ", "NYSE", "NYSEARCA", "AMEX", "CBOE"}:
            return hx.clean_symbol(base)
    return normalize_bloomberg_symbol(raw)


def normalize_bloomberg_symbol(value: Any) -> str:
    raw = re.sub(r"\s+", " ", str(value or "").strip().upper())
    if not raw or raw in {"N/A", "NAN", "--", "-", "CASH&OTHER"}:
        return ""
    m = re.fullmatch(r"(.+?)\s+([A-Z]{2})", raw)
    if m and m.group(2) in BLOOMBERG_SUFFIX:
        base, code = m.group(1).strip(), m.group(2)
        if code == "HK" and base.isdigit():
            base = base.zfill(4)
        if code == "DC" and base == "MAERSKB":
            base = "MAERSK-B"
        base = base.replace("/", "-")
        return base + BLOOMBERG_SUFFIX[code]
    return hx.clean_symbol(raw)


def fetch_stockanalysis(session: requests.Session, ticker: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    url = SA_URL.format(ticker=ticker.lower())
    r = session.get(url, headers=BASE_HEADERS, timeout=35)
    r.raise_for_status()
    total = None
    m = re.search(r"Showing\s+\d+\s+of\s+([0-9,]+)\s+holdings", r.text, flags=re.I)
    if m:
        total = int(m.group(1).replace(",", ""))
    tables = pd.read_html(io.StringIO(r.text))
    best = None
    for df in tables:
        cols = {str(c).strip().lower(): c for c in df.columns}
        if "symbol" in cols and "name" in cols and len(df) >= 5 and (best is None or len(df) > len(best)):
            best = df
    if best is None:
        raise RuntimeError("StockAnalysis holdings table not found")
    cm = {str(c).strip().lower(): c for c in best.columns}
    out = pd.DataFrame({
        "provider_symbol": best[cm["symbol"]].astype(str),
        "symbol": best[cm["symbol"]].map(normalize_sa_symbol),
        "name": best[cm["name"]].astype(str),
    })
    out["name_key"] = out["name"].map(normalize_name)
    out = out[(out["symbol"] != "") & (out["name_key"] != "")].drop_duplicates("name_key")
    return out, {"total": total, "source_url": url}


def fetch_etfcom_resolver(session: requests.Session, ticker: str) -> pd.DataFrame:
    # Resolver only. ETF.com Theme56 membership is stale for some funds and is never selected here.
    url = etfcom.API_URL.format(ticker=ticker)
    r = session.get(url, headers={"User-Agent": UA, "Accept": "application/json,*/*", "Origin": "https://www.etf.com", "Referer": "https://www.etf.com/", "x-limit": "500"}, timeout=35)
    r.raise_for_status()
    records = etfcom._find_record_list(r.json()) or []
    rows = []
    for rec in records:
        raw_symbol = etfcom._value(rec, ("symbol", "ticker", "securitySymbol", "holdingSymbol"))
        name = etfcom._value(rec, ("name", "securityName", "holdingName", "description"))
        sym = normalize_bloomberg_symbol(raw_symbol)
        key = normalize_name(name)
        if sym and key:
            rows.append({"name_key": key, "symbol": sym, "provider_symbol": str(raw_symbol or "")})
    return pd.DataFrame(rows).drop_duplicates("name_key") if rows else pd.DataFrame(columns=["name_key", "symbol", "provider_symbol"])


def resolve_current_symbol(raw: Any, name: Any, current_map: dict[str, str], resolver_map: dict[str, str]) -> str:
    raw_s = re.sub(r"\s+", " ", str(raw or "").strip().upper())
    key = normalize_name(name)
    # Explicit exchange suffixes are authoritative.
    if re.search(r"\s+[A-Z]{2}$", raw_s):
        out = normalize_bloomberg_symbol(raw_s)
        if out:
            return out
    # Ordinary US tickers and class shares can be used directly. Pure numerics need an exchange.
    if re.fullmatch(r"[A-Z][A-Z0-9./-]{0,12}", raw_s):
        out = hx.clean_symbol(raw_s)
        if out:
            return out
    if key in current_map:
        return current_map[key]
    if key in resolver_map:
        return resolver_map[key]
    return ""


def fetch_cmc_current(session: requests.Session, ticker: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    errors: list[str] = []
    sa, sa_diag = fetch_stockanalysis(session, ticker)
    current_map = dict(zip(sa["name_key"], sa["symbol"]))
    try:
        er = fetch_etfcom_resolver(session, ticker)
        resolver_map = dict(zip(er["name_key"], er["symbol"]))
    except Exception:
        resolver_map = {}

    for slug in CMC_SLUGS[ticker]:
        url = f"https://companiesmarketcap.com/{slug}/holdings/"
        try:
            r = session.get(url, headers=BASE_HEADERS, timeout=40)
            r.raise_for_status()
            text = r.text
            m = re.search(r"Etf holdings as of\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})\s+Number of holdings:\s*([0-9,]+)", text, flags=re.I)
            if not m:
                raise RuntimeError("current as-of/count marker missing")
            asof = pd.to_datetime(m.group(1), errors="raise").date()
            declared = int(m.group(2).replace(",", ""))
            age_days = (date.today() - asof).days
            if age_days < -2 or age_days > 21:
                raise RuntimeError(f"stale holdings date {asof} age={age_days}")
            tables = pd.read_html(io.StringIO(text))
            best = None
            for df in tables:
                cm = {str(c).strip().lower(): c for c in df.columns}
                if "name" in cm and "ticker" in cm and len(df) >= 5 and (best is None or len(df) > len(best)):
                    best = df
            if best is None:
                raise RuntimeError("full holdings table not found")
            cm = {str(c).strip().lower(): c for c in best.columns}
            name_col, ticker_col = cm["name"], cm["ticker"]
            weight_col = next((c for k, c in cm.items() if "weight" in k), None)
            rows = []
            for _, rec in best.iterrows():
                name = str(rec.get(name_col) or "").strip()
                raw = str(rec.get(ticker_col) or "").strip()
                if not name or any(w in name.upper() for w in CASH_WORDS):
                    continue
                symbol = resolve_current_symbol(raw, name, current_map, resolver_map)
                if not symbol or symbol in {"USD", "EUR", "JPY", "GBP", "HKD", "NOK", "KRW", "CHF", "ILS", "TRY", "THB", "SGD"}:
                    continue
                weight = None
                if weight_col is not None:
                    weight = pd.to_numeric(str(rec.get(weight_col)).replace("%", "").replace(",", ""), errors="coerce")
                rows.append({
                    "sector_etf": ticker,
                    "provider_symbol": raw,
                    "symbol": symbol,
                    "weight_pct": None if pd.isna(weight) else float(weight),
                    "name": name,
                    "source_url": url,
                    "provider": "COMPANIESMARKETCAP_CURRENT_FULL_LIST",
                    "quality": "VALIDATED_CURRENT_FULL_LIST_SECONDARY",
                    "membership_asof": str(asof),
                    "declared_total_holdings": declared,
                })
            out = pd.DataFrame(rows).drop_duplicates("symbol", keep="first")
            # The published total often includes cash/currency lines. Require broad equity capture,
            # but do not manufacture missing members to hit the count.
            ratio = len(out) / max(declared, 1)
            if len(out) < 10 or ratio < 0.72 or ratio > 1.05:
                raise RuntimeError(f"resolved equity coverage {len(out)}/{declared}={ratio:.3f}")
            return out.reset_index(drop=True), {
                "ticker": ticker, "status": "PASS", "method": "CMC_CURRENT_FULL_LIST",
                "rows": len(out), "declared_total": declared, "coverage_vs_declared": ratio,
                "membership_asof": str(asof), "source_url": url, "stockanalysis_total": sa_diag.get("total"),
            }
        except Exception as exc:
            errors.append(f"{url}: {type(exc).__name__}: {exc}")
    raise RuntimeError(" | ".join(errors))


def main() -> None:
    outdir = Path("leadership/research/rotation_theme56_secondary_holdings_fallback")
    outdir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    frames: list[pd.DataFrame] = []
    qa: list[dict[str, Any]] = []
    for ticker in TARGETS:
        try:
            df, diag = fetch_cmc_current(session, ticker)
            frames.append(df)
            qa.append(diag)
        except Exception as exc:
            qa.append({"ticker": ticker, "status": "FAIL", "error": f"{type(exc).__name__}: {exc}"})
        print(json.dumps(qa[-1], ensure_ascii=False), flush=True)
        time.sleep(0.15)

    qdf = pd.DataFrame(qa)
    qdf.to_csv(outdir / "secondary_holdings_qa.csv", index=False)
    if frames:
        pd.concat(frames, ignore_index=True).drop_duplicates(["sector_etf", "symbol"]).to_csv(
            outdir / "validated_current_membership_fallback.csv", index=False
        )
    passed = qdf.loc[qdf["status"] == "PASS", "ticker"].tolist()
    report = {
        "schema": 4,
        "research_only": True,
        "candidate_count": len(TARGETS),
        "pass_count": len(passed),
        "pass_tickers": passed,
        "rows": qa,
        "quality_contract": "Current full-list secondary membership is accepted only with a holdings as-of date no older than 21 days and broad resolution of the published full equity list. ETF.com historical membership is never used to establish current membership; it may only resolve an exchange suffix for a company already present in the current full list.",
        "guardrails": [
            "Issuer exact current holdings remain preferred and override this fallback in Full Stack.",
            "The existing 80% constituent-price coverage requirement in Full Stack is not lowered.",
            "Current source membership, not stale ETF.com membership, determines which securities are included.",
            "Cash/currency rows are excluded from Internal membership.",
            "No price/volume inference is used to manufacture membership.",
            "DRAM is excluded because its short price history is the separately accepted exception.",
        ],
    }
    (outdir / "secondary_holdings_qa.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    if len(passed) != len(TARGETS):
        raise RuntimeError(f"secondary holdings fallback incomplete: {passed}")


if __name__ == "__main__":
    main()
