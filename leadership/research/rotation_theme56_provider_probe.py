from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urljoin

import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122 Safari/537.36"
HEADERS = {"User-Agent": UA, "Accept": "text/html,application/json,text/csv,*/*"}

PAGES = {
    "GLOBALX_AI": "https://www.globalxetfs.com/funds/aiq",
    "VANECK_SMH": "https://www.vaneck.com/us/en/investments/semiconductor-etf-smh/",
    "FIRSTTRUST_CIBR_HOLD": "https://www.ftportfolios.com/Retail/Etf/EtfHoldings.aspx?Print=Y&Ticker=CIBR",
    "FIRSTTRUST_CIBR_PRICE": "https://www.ftportfolios.com/Retail/Etf/EtfPriceHistory.aspx?Print=Y&Ticker=CIBR&begin=8%2F1%2F2026",
    "ARK_ARKW": "https://www.ark-funds.com/funds/arkw",
    "DEFIANCE_QTUM": "https://www.defianceetfs.com/qtum/",
    "WISDOMTREE_WCLD": "https://www.wisdomtree.com/us/products/megatrends/wcld",
    "AMPLIFY_BLOK": "https://amplifyetfs.com/blok-holdings/",
    "AMPLIFY_IBUY": "https://amplifyetfs.com/ibuy-holdings/",
    "INVESCO_PHO": "https://www.invesco.com/us/en/financial-products/etfs/invesco-water-resources-etf.html",
    "SONIC_BOAT": "https://www.sonicshares.com/boat",
    "COINSHARES_WGMI": "https://coinshares.com/us/etf/wgmi/",
    "USGLOBAL_JETS": "https://usglobaletfs.com/fund/u-s-global-jets-etf/",
    "ROUNDHILL_DRAM": "https://www.roundhillinvestments.com/etf/dram/",
}

KEY_RE = re.compile(r"(?:https?:)?//[^\"'<>\\\s]+|[\w./?=&%+-]+\.(?:csv|xlsx?|json)(?:\?[^\"'<>\\\s]*)?", re.I)


def clean_link(raw: str, base: str) -> str:
    s = raw.replace("\\/", "/").replace("&amp;", "&")
    if s.startswith("//"):
        s = "https:" + s
    elif not s.startswith("http"):
        s = urljoin(base, s)
    return s


def page_probe(session: requests.Session, name: str, url: str) -> dict:
    out = {"name": name, "url": url}
    try:
        r = session.get(url, headers=HEADERS, timeout=40, allow_redirects=True)
        out.update({"status": r.status_code, "final_url": r.url, "bytes": len(r.content), "content_type": r.headers.get("content-type")})
        text = r.text if "text" in (r.headers.get("content-type") or "").lower() or "html" in (r.headers.get("content-type") or "").lower() or r.status_code < 400 else ""
        low = text.lower()
        out["contains"] = {k: (k in low) for k in ["shares outstanding", "outstanding shares", "net assets", "assets under management", "historical", "holdings", "export", "download", "api", "nav"]}
        links = []
        for hit in KEY_RE.findall(text):
            link = clean_link(hit, r.url)
            ll = link.lower()
            if any(k in ll for k in ["nav", "hold", "histor", "price", "fund", "api", "csv", "xls", "json", "asset"]):
                links.append(link.rstrip(".,);"))
        out["candidate_links"] = list(dict.fromkeys(links))[:80]
        # Keep short snippets around the key terms only; never persist full pages.
        snippets = []
        for key in ["shares outstanding", "outstanding shares", "net assets", "historical", "export to excel", "download holdings", "fund holdings"]:
            pos = low.find(key)
            if pos >= 0:
                snippets.append(re.sub(r"\s+", " ", text[max(0, pos-180):pos+500])[:700])
        out["snippets"] = snippets[:12]
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


def endpoint_probe(session: requests.Session) -> list[dict]:
    out = []
    tests = [
        ("NASDAQ_NO_KEY", "https://data.nasdaq.com/api/v3/datatables/ETFG/FUND.json?ticker=CIBR&qopts.rows=5"),
        ("ETFCOM_DETAILS", "https://www.etf.com/api/v1/api-details"),
        ("ETFCOM_FLOW_NOAUTH", "https://api-prod.etf.com/private/apps/fundflows/CIBR/charts?startDate=20260801&endDate=20260831"),
    ]
    for name, url in tests:
        rec = {"name": name, "url": url}
        try:
            r = session.get(url, headers={**HEADERS, "Referer": "https://www.etf.com/"}, timeout=30)
            rec.update({"status": r.status_code, "bytes": len(r.content), "content_type": r.headers.get("content-type"), "prefix": re.sub(r"\s+", " ", r.text[:800])})
        except Exception as exc:
            rec["error"] = f"{type(exc).__name__}: {exc}"
        out.append(rec)

    # TradingView public scanner: request the 1M flow field for a known ETF.
    tv = {"name": "TRADINGVIEW_SCANNER_1M", "url": "https://scanner.tradingview.com/global/scan"}
    payload = {
        "symbols": {"tickers": ["NASDAQ:CIBR"], "query": {"types": []}},
        "columns": ["name", "exchange", "aum", "nav", "fund_flows.1M", "fund_flows.1Y", "etf_holdings_count"],
    }
    try:
        r = session.post(tv["url"], headers={**HEADERS, "Content-Type": "application/json", "Origin": "https://www.tradingview.com", "Referer": "https://www.tradingview.com/"}, json=payload, timeout=30)
        tv.update({"status": r.status_code, "bytes": len(r.content), "prefix": re.sub(r"\s+", " ", r.text[:1200])})
    except Exception as exc:
        tv["error"] = f"{type(exc).__name__}: {exc}"
    out.append(tv)
    return out


def globalx_csv_probe(session: requests.Session) -> dict:
    url = "https://assets.globalxetfs.com/funds/holdings/aiq_full-holdings_20260831.csv"
    rec = {"name": "GLOBALX_HOLDINGS_CSV", "url": url}
    try:
        r = session.get(url, headers=HEADERS, timeout=30)
        rec.update({"status": r.status_code, "bytes": len(r.content), "first_lines": r.text.splitlines()[:18]})
    except Exception as exc:
        rec["error"] = f"{type(exc).__name__}: {exc}"
    return rec


def main() -> None:
    outdir = Path("leadership/research/rotation_theme56_provider_probe")
    outdir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    report = {
        "schema": 1,
        "research_only": True,
        "pages": [page_probe(session, name, url) for name, url in PAGES.items()],
        "endpoints": endpoint_probe(session),
        "globalx_csv": globalx_csv_probe(session),
    }
    (outdir / "provider_probe.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"pages": [{"name": x["name"], "status": x.get("status"), "links": len(x.get("candidate_links", [])), "error": x.get("error")} for x in report["pages"]], "endpoints": report["endpoints"], "globalx": {k: report["globalx_csv"].get(k) for k in ["status", "bytes", "first_lines"]}}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
