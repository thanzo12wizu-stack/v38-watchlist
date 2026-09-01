from __future__ import annotations

import argparse
import csv
import io
import json
import re
from pathlib import Path
from typing import Any

import pandas as pd
import requests

import rotation_divergence_proxy_backtest as proxy
import rotation_exact_flow_research as flowlib


SSGA_ETFS = {
    "XES", "XOP", "XSD", "XME", "XBI", "KBE", "KRE", "KIE", "XRT", "XHB", "XAR",
}
ISHARES_ETFS = {
    "IGV", "SOXX", "ICLN", "IAI", "IHI", "IYT", "ITA", "WOOD",
}
SUPPORTED = SSGA_ETFS | ISHARES_ETFS


def load_config(path: Path) -> list[str]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    themes = obj.get("themes") if isinstance(obj, dict) else None
    if not isinstance(themes, list) or len(themes) != 56:
        raise RuntimeError("theme56 config must contain exactly 56 themes")
    tickers = [str(x.get("ticker") or "").upper().strip() for x in themes if isinstance(x, dict)]
    if len(tickers) != 56 or len(set(tickers)) != 56:
        raise RuntimeError("theme56 config contains duplicate/missing tickers")
    return tickers


def _ishares_text(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("d", "value", "url"):
            if key in value and value[key] is not None:
                return str(value[key]).strip()
    return "" if value is None else str(value).strip()


def resolve_ishares_product_pages(session: requests.Session, wanted: set[str]) -> dict[str, str]:
    response = session.get(flowlib.ISHARES_SCREENER_URL, headers={"User-Agent": flowlib.UA}, timeout=45)
    response.raise_for_status()
    data = response.json()
    out: dict[str, str] = {}
    if not isinstance(data, dict):
        return out
    for raw in data.values():
        if not isinstance(raw, dict) or raw.get("productType") != "ISHARES_FUND_DATA":
            continue
        ticker = (_ishares_text(raw.get("localExchangeTicker")) or "").upper()
        if ticker not in wanted:
            continue
        candidates: list[str] = []
        for value in raw.values():
            text = _ishares_text(value)
            if "/products/" in text:
                candidates.append(text)
            if isinstance(value, dict):
                for v in value.values():
                    text2 = _ishares_text(v)
                    if "/products/" in text2:
                        candidates.append(text2)
        url = next((x for x in candidates if x), "")
        if url.startswith("/"):
            url = "https://www.ishares.com" + url
        if url.startswith("http"):
            out[ticker] = url.rstrip("/")
    return out


EXCHANGE_SUFFIX_RULES: list[tuple[str, str]] = [
    ("NASDAQ", ""), ("NYSE", ""), ("CBOE", ""),
    ("SHANGHAI", ".SS"), ("SHENZHEN", ".SZ"),
    ("HONG KONG", ".HK"), ("TOKYO", ".T"),
    ("KOREA EXCHANGE", ".KS"), ("KOSDAQ", ".KQ"),
    ("TAIWAN STOCK", ".TW"), ("TAIPEI", ".TW"),
    ("COPENHAGEN", ".CO"), ("XETRA", ".DE"), ("FRANKFURT", ".DE"),
    ("LONDON", ".L"), ("EURONEXT LISBON", ".LS"), ("LISBON", ".LS"),
    ("EURONEXT PARIS", ".PA"), ("PARIS", ".PA"),
    ("EURONEXT AMSTERDAM", ".AS"), ("AMSTERDAM", ".AS"),
    ("MILAN", ".MI"), ("BORSA ITALIANA", ".MI"),
    ("MADRID", ".MC"), ("SWISS", ".SW"),
    ("HELSINKI", ".HE"), ("STOCKHOLM", ".ST"), ("OSLO", ".OL"),
    ("TORONTO", ".TO"), ("XBSP", ".SA"), ("B3", ".SA"),
    ("TEL AVIV", ".TA"), ("NATIONAL STOCK EXCHANGE OF INDIA", ".NS"),
    ("BOMBAY", ".BO"), ("INDONESIA", ".JK"), ("ISTANBUL", ".IS"),
    ("WIENER", ".VI"), ("AUSTRALIAN", ".AX"), ("JOHANNESBURG", ".JO"),
    ("SANTIAGO", ".SN"),
]


def normalize_ishares_symbol(symbol: str, exchange: str, location: str = "") -> str:
    raw = str(symbol or "").strip().upper()
    if not raw or raw in {"-", "--", "NAN"}:
        return ""
    ex = str(exchange or "").strip().upper()
    loc = str(location or "").strip().upper()
    suffix = None
    for needle, candidate in EXCHANGE_SUFFIX_RULES:
        if needle in ex:
            suffix = candidate
            break
    if suffix is None:
        # Conservative location fallback only where the local exchange is unambiguous.
        location_suffix = {
            "JAPAN": ".T", "BRAZIL": ".SA", "DENMARK": ".CO", "SWEDEN": ".ST",
            "FINLAND": ".HE", "NORWAY": ".OL", "SWITZERLAND": ".SW", "CANADA": ".TO",
            "TAIWAN": ".TW", "KOREA (SOUTH)": ".KS", "UNITED KINGDOM": ".L",
            "ISRAEL": ".TA", "AUSTRALIA": ".AX", "INDONESIA": ".JK",
        }
        suffix = location_suffix.get(loc)
    if suffix is None:
        return raw
    if suffix == "":
        if re.fullmatch(r"[A-Z]{1,6}[/.][A-Z]", raw):
            return raw.replace("/", "-").replace(".", "-")
        return raw
    if suffix == ".HK" and raw.isdigit():
        raw = raw.zfill(4)
    if suffix in {".ST", ".CO", ".OL", ".HE"}:
        raw = raw.replace(" ", "-")
    if suffix == ".L":
        raw = raw.replace("/", "").replace(" ", "-")
    return raw + suffix


def fetch_ishares_holdings(session: requests.Session, ticker: str, product_page: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    urls = [
        product_page.rstrip("/") + "/latest-holdings.csv",
        product_page.rstrip("/") + "/1467271812596.ajax?fileType=csv&fileName=holdings&dataType=fund",
    ]
    errors: list[str] = []
    for url in urls:
        try:
            r = session.get(url, headers={"User-Agent": flowlib.UA, "Accept": "text/csv,*/*"}, timeout=45)
            r.raise_for_status()
            text = r.content.decode("utf-8-sig", errors="replace").lstrip("\ufeff")
            lines = text.splitlines()
            header_idx = next((i for i, line in enumerate(lines) if line.lower().startswith("ticker,") and "asset class" in line.lower()), None)
            if header_idx is None:
                raise RuntimeError("holdings CSV header not found")
            rows: list[dict[str, Any]] = []
            for row in csv.DictReader(io.StringIO("\n".join(lines[header_idx:]))):
                provider_symbol = (row.get("Ticker") or "").strip().upper()
                asset = (row.get("Asset Class") or "").strip().lower()
                if not provider_symbol or asset != "equity":
                    continue
                exchange = (row.get("Exchange") or "").strip()
                location = (row.get("Location") or "").strip()
                symbol = normalize_ishares_symbol(provider_symbol, exchange, location)
                if not symbol:
                    continue
                weight = None
                for key in ("Weight (%)", "Weight", "% of Net Assets", "Market Value Weight"):
                    if key in row:
                        try:
                            weight = float(str(row.get(key) or "").replace(",", "").replace("%", "").strip())
                        except ValueError:
                            weight = None
                        if weight is not None:
                            break
                rows.append({
                    "sector_etf": ticker,
                    "provider_symbol": provider_symbol,
                    "symbol": symbol,
                    "weight_pct": weight,
                    "name": (row.get("Name") or "").strip(),
                    "exchange": exchange,
                    "location": location,
                    "source_url": url,
                })
            out = pd.DataFrame(rows).drop_duplicates("symbol", keep="first")
            if len(out) < 5:
                raise RuntimeError(f"too few equity holdings ({len(out)})")
            return out.reset_index(drop=True), {
                "ticker": ticker,
                "provider": "ISHARES",
                "quality": "EXACT_CURRENT_MEMBERSHIP",
                "rows": int(len(out)),
                "source_url": url,
            }
        except Exception as exc:
            errors.append(f"{url}: {type(exc).__name__}: {exc}")
    raise RuntimeError(" | ".join(errors))


def fetch_flow(session: requests.Session, ticker: str, ishares_ids: dict[str, int]) -> tuple[pd.DataFrame, dict[str, Any]]:
    if ticker in SSGA_ETFS:
        series = flowlib.fetch_ssga_nav_history(session, ticker)
    elif ticker in ISHARES_ETFS:
        pid = ishares_ids.get(ticker)
        if pid is None:
            raise RuntimeError("iShares portfolioId not found")
        series = flowlib.fetch_ishares_nav_history(session, ticker, pid)
    else:
        raise RuntimeError("unsupported provider")
    return flowlib.derive_exact_flows(series)


def main() -> None:
    ap = argparse.ArgumentParser(description="QA official holdings and exact fund-flow adapters for the Theme56 Rotation universe")
    ap.add_argument("--config", type=Path, default=Path("leadership/research/rotation_theme56_config.json"))
    ap.add_argument("--output", type=Path, default=Path("leadership/research/rotation_theme56_provider_qa"))
    ap.add_argument("--persist-flow-start", default="2022-01-01")
    args = ap.parse_args()

    universe = set(load_config(args.config))
    unexpected = sorted(SUPPORTED - universe)
    if unexpected:
        raise RuntimeError(f"provider registry contains tickers outside Theme56: {unexpected}")

    args.output.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    ishares_ids = flowlib.resolve_ishares_portfolio_ids(session, sorted(ISHARES_ETFS))
    product_pages = resolve_ishares_product_pages(session, ISHARES_ETFS)

    holdings_frames: list[pd.DataFrame] = []
    flow_frames: list[pd.DataFrame] = []
    rows: list[dict[str, Any]] = []
    for ticker in sorted(SUPPORTED):
        provider = "SSGA" if ticker in SSGA_ETFS else "ISHARES"
        rec: dict[str, Any] = {"ticker": ticker, "provider": provider}
        try:
            if provider == "SSGA":
                h = proxy.fetch_ssga_current_holdings(session, ticker)
                hdiag = {
                    "source_url": proxy.HOLDINGS_URL.format(ticker=ticker.lower()),
                }
            else:
                page = product_pages.get(ticker)
                if not page:
                    raise RuntimeError("iShares product page not resolved")
                h, hdiag = fetch_ishares_holdings(session, ticker, page)
            holdings_frames.append(h)
            rec.update(holdings_status="PASS", holdings_rows=int(len(h)), holdings_source=hdiag.get("source_url"))
        except Exception as exc:
            rec.update(holdings_status="FAIL", holdings_error=f"{type(exc).__name__}: {exc}")

        try:
            f, fdiag = fetch_flow(session, ticker, ishares_ids)
            f = f.assign(ticker=ticker)
            flow_frames.append(f)
            rec.update(
                flow_status="PASS",
                flow_rows=int(f["flow_usd"].notna().sum()),
                flow_first_date=fdiag.get("first_date"),
                flow_last_date=fdiag.get("last_date"),
                flow_source=fdiag.get("source_url"),
            )
        except Exception as exc:
            rec.update(flow_status="FAIL", flow_error=f"{type(exc).__name__}: {exc}")

        rec["full_stack_adapter"] = rec.get("holdings_status") == "PASS" and rec.get("flow_status") == "PASS"
        rows.append(rec)
        print(json.dumps(rec, ensure_ascii=False), flush=True)

    qa = pd.DataFrame(rows).sort_values(["provider", "ticker"])
    qa.to_csv(args.output / "theme56_provider_qa.csv", index=False)
    if holdings_frames:
        pd.concat(holdings_frames, ignore_index=True).to_csv(args.output / "theme56_exact_current_holdings.csv", index=False)
    if flow_frames:
        f = pd.concat(flow_frames, ignore_index=True)
        f["date"] = pd.to_datetime(f["date"], errors="coerce")
        persist_start = pd.Timestamp(args.persist_flow_start)
        f = f[f["date"] >= persist_start].copy()
        keep = [x for x in ["date", "ticker", "provider", "nav", "shares_outstanding", "aum", "flow_usd", "flow_1d", "flow_5d", "flow_20d", "flow_20d_pct_aum", "source_url"] if x in f.columns]
        f[keep].to_csv(args.output / "theme56_exact_flows.csv", index=False, date_format="%Y-%m-%d")

    failure_cols = [c for c in ["ticker", "provider", "holdings_status", "flow_status", "holdings_error", "flow_error"] if c in qa.columns]
    fail_df = qa.loc[~qa["full_stack_adapter"], failure_cols].copy()
    failures = fail_df.where(pd.notna(fail_df), None).to_dict("records") if not fail_df.empty else []
    report = {
        "schema": 3,
        "research_only": True,
        "supported_provider_families": ["SSGA", "ISHARES"],
        "candidate_count": int(len(qa)),
        "holdings_pass": int((qa["holdings_status"] == "PASS").sum()),
        "flow_pass": int((qa["flow_status"] == "PASS").sum()),
        "full_stack_adapter_pass": int(qa["full_stack_adapter"].sum()),
        "full_stack_tickers": qa.loc[qa["full_stack_adapter"], "ticker"].tolist(),
        "persisted_flow_start": args.persist_flow_start,
        "symbol_normalization": "iShares provider ticker + official Exchange/Location fields are translated to market-data lookup symbols while provider_symbol is preserved.",
        "failures": failures,
        "guardrails": [
            "Only official current holdings are accepted for Internals membership.",
            "Only official daily NAV + shares outstanding are accepted for Exact Flow.",
            "No price-volume proxy is substituted for fund flow.",
            "Provider adapter PASS does not validate the old 15-ETF state thresholds on the 56-theme cross-section.",
        ],
    }
    (args.output / "theme56_provider_qa.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
