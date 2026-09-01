from __future__ import annotations

import argparse
import io
import json
import re
import time
from html import unescape
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup

import rotation_theme56_holdings_expansion as hx

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122 Safari/537.36"
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}
TARGETS = ["WCLD", "BLOK", "IBUY", "WGMI", "PHO", "TAN", "PKB", "PEJ", "BOAT", "JETS"]

EXTRA_SPACE_SUFFIX = {
    "SM": ".MC",  # Spain
    "TI": ".IS",  # Turkey
    "MM": ".MX",  # Mexico
    "SP": ".SI",  # Singapore
    "TB": ".BK",  # Thailand
    "BZ": ".SA",  # Brazil
    "MK": ".KL",  # Malaysia
    "IJ": ".JK",  # Indonesia
    "IN": ".NS",  # India NSE when provider uses IN
}


def clean_symbol(value: Any) -> str:
    raw = str(value or "").strip().upper()
    if not raw:
        return ""
    raw = re.sub(r"\s+", " ", raw)
    m = re.fullmatch(r"(.+?)\s+(SM|TI|MM|SP|TB|BZ|MK|IJ|IN)", raw)
    if m:
        base, exch = m.group(1), m.group(2)
        base = base.replace("/", "-").strip(".- ")
        return base + EXTRA_SPACE_SUFFIX[exch]
    return hx.clean_symbol(raw)


def is_security(symbol: str, name: str = "", cusip: str = "") -> bool:
    s = str(symbol or "").upper().strip()
    n = str(name or "").upper().strip()
    c = str(cusip or "").upper().strip()
    if not s or s in {"CASH", "CASH&OTHER", "NAN", "--", "-"}:
        return False
    if c.startswith("CASH"):
        return False
    cash_words = ("CASH & OTHER", "US DOLLAR", "U.S. DOLLAR", "EURO", "BRITISH POUND", "SINGAPORE DOLLAR", "THAI BAHT", "TURKISH LIRA", "KOREAN WON", "HONG KONG DOLLAR", "DANISH KRONE", "NORWEGIAN KRONE")
    if any(x in n for x in cash_words):
        return False
    return True


def num(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "").replace("$", "").replace("%", "")
    if not text or text.lower() in {"nan", "none", "null", "--", "-"}:
        return None
    try:
        return float(text)
    except Exception:
        return None


def get(session: requests.Session, url: str, *, accept: str | None = None, timeout: int = 45) -> requests.Response:
    headers = dict(HEADERS)
    if accept:
        headers["Accept"] = accept
    last: Exception | None = None
    for attempt in range(4):
        try:
            r = session.get(url, headers=headers, timeout=timeout, allow_redirects=True)
            r.raise_for_status()
            return r
        except Exception as exc:
            last = exc
            time.sleep(1.25 * (attempt + 1))
    raise RuntimeError(f"GET failed {url}: {last}")


def flat(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if isinstance(out.columns, pd.MultiIndex):
        out.columns = [" ".join(str(x).strip() for x in c if str(x).lower() != "nan").strip() for c in out.columns]
    else:
        out.columns = [str(c).strip() for c in out.columns]
    return out


def col(df: pd.DataFrame, *needles: str) -> str | None:
    for c in df.columns:
        low = re.sub(r"[^a-z0-9%]+", "", str(c).lower())
        if all(re.sub(r"[^a-z0-9%]+", "", n.lower()) in low for n in needles):
            return str(c)
    return None


def standardize(ticker: str, df: pd.DataFrame, ticker_col: str, name_col: str | None, weight_col: str | None, source_url: str, provider: str, cusip_col: str | None = None) -> pd.DataFrame:
    provider_symbol = df[ticker_col].astype(str)
    names = df[name_col].astype(str) if name_col else pd.Series("", index=df.index)
    cusips = df[cusip_col].astype(str) if cusip_col else pd.Series("", index=df.index)
    out = pd.DataFrame({
        "sector_etf": ticker,
        "provider_symbol": provider_symbol,
        "symbol": provider_symbol.map(clean_symbol),
        "weight_pct": df[weight_col].map(num) if weight_col else None,
        "name": names,
        "source_url": source_url,
        "provider": provider,
    })
    keep = [is_security(s, n, c) for s, n, c in zip(out["provider_symbol"], names, cusips)]
    out = out[pd.Series(keep, index=out.index)]
    out = out[out["symbol"] != ""].drop_duplicates("symbol", keep="first").reset_index(drop=True)
    return out


def html_tables(text: str) -> list[pd.DataFrame]:
    try:
        return [flat(x) for x in pd.read_html(io.StringIO(text))]
    except Exception:
        return []


def extract_json_record_lists(html: str) -> list[list[dict[str, Any]]]:
    soup = BeautifulSoup(html, "html.parser")
    roots: list[Any] = []
    for script in soup.find_all("script"):
        text = script.string or script.get_text("", strip=False)
        if not text:
            continue
        stripped = unescape(text).strip()
        if stripped[:1] not in {"{", "["}:
            continue
        try:
            roots.append(json.loads(stripped))
        except Exception:
            continue
    lists: list[list[dict[str, Any]]] = []
    def walk(x: Any, depth: int = 0) -> None:
        if depth > 10:
            return
        if isinstance(x, list):
            rows = [r for r in x if isinstance(r, dict)]
            if len(rows) >= 5:
                symbolish = sum(1 for r in rows if any(str(k).lower() in {"ticker","symbol","stocksymbol","securityticker","holdingticker"} for k in r))
                if symbolish >= max(3, len(rows)//3):
                    lists.append(rows)
            for item in x[:30]:
                walk(item, depth + 1)
        elif isinstance(x, dict):
            for v in x.values():
                if isinstance(v, (dict, list)):
                    walk(v, depth + 1)
    for root in roots:
        walk(root)
    return lists


def records_to_frame(ticker: str, records: list[dict[str, Any]], source_url: str, provider: str) -> pd.DataFrame:
    keys = set().union(*(r.keys() for r in records)) if records else set()
    def find(names: tuple[str, ...]) -> str | None:
        lower = {str(k).lower(): k for k in keys}
        for n in names:
            if n.lower() in lower:
                return lower[n.lower()]
        for k in keys:
            nk = re.sub(r"[^a-z0-9]", "", str(k).lower())
            if any(re.sub(r"[^a-z0-9]", "", n.lower()) == nk for n in names):
                return k
        return None
    tk = find(("ticker","symbol","stockTicker","securityTicker","holdingTicker"))
    nm = find(("name","securityName","productName","holdingName","description"))
    wt = find(("weight","weighting","weightings","marketValuePercent","market_value_percent","percentNetAssets","netAssetsPercent"))
    cu = find(("cusip","securityId"))
    if tk is None:
        return pd.DataFrame()
    raw = pd.DataFrame(records)
    return standardize(ticker, raw, str(tk), None if nm is None else str(nm), None if wt is None else str(wt), source_url, provider, None if cu is None else str(cu))


def fetch_invesco(session: requests.Session, ticker: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    urls = [
        f"https://www.invesco.com/us/financial-products/etfs/holdings/main/holdings/0?audienceType=Investor&action=download&ticker={ticker}",
        f"https://www.invesco.com/us/financial-products/etfs/holdings/main/holdings/0?action=download&ticker={ticker}",
    ]
    errors = []
    for url in urls:
        try:
            r = get(session, url, accept="text/csv,text/plain,*/*", timeout=60)
            text = r.content.decode("utf-8-sig", errors="replace")
            lines = text.splitlines()
            header = next((i for i, line in enumerate(lines[:30]) if "holding ticker" in line.lower() or ("ticker" in line.lower() and "holding" in line.lower())), 0)
            df = flat(pd.read_csv(io.StringIO("\n".join(lines[header:])), engine="python"))
            tk = col(df, "holdingticker") or col(df, "ticker")
            nm = col(df, "name") or col(df, "holding")
            wt = col(df, "weight")
            cu = col(df, "cusip")
            if tk is None:
                raise RuntimeError(f"ticker column missing: {list(df.columns)}")
            out = standardize(ticker, df, tk, nm, wt, url, "INVESCO", cu)
            if len(out) < 15:
                raise RuntimeError(f"too few Invesco holdings: {len(out)}")
            return out, {"ticker": ticker, "provider": "INVESCO", "rows": len(out), "source_url": url, "status": "PASS", "quality": "EXACT_CURRENT_MEMBERSHIP"}
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
    raise RuntimeError(" | ".join(errors))


def fetch_amplify(session: requests.Session, ticker: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    urls = [f"https://amplifyetfs.com/{ticker.lower()}-holdings/", f"https://amplifyetfs.com/{ticker.lower()}/"]
    errors = []
    for url in urls:
        try:
            r = get(session, url)
            tables = html_tables(r.text)
            candidates = []
            for df in tables:
                tk = col(df, "ticker")
                nm = col(df, "name")
                wt = col(df, "marketvalue%") or col(df, "%marketvalue") or col(df, "weight")
                if tk and nm and len(df) >= 15:
                    candidates.append((len(df), df, tk, nm, wt))
            if candidates:
                _, df, tk, nm, wt = max(candidates, key=lambda x: x[0])
                out = standardize(ticker, df, tk, nm, wt, url, "AMPLIFY", col(df, "cusip"))
                if len(out) >= 15:
                    return out, {"ticker": ticker, "provider": "AMPLIFY", "rows": len(out), "source_url": url, "status": "PASS", "quality": "EXACT_CURRENT_MEMBERSHIP"}
            for records in sorted(extract_json_record_lists(r.text), key=len, reverse=True):
                out = records_to_frame(ticker, records, url, "AMPLIFY")
                if len(out) >= 15:
                    return out, {"ticker": ticker, "provider": "AMPLIFY", "rows": len(out), "source_url": url, "status": "PASS", "quality": "EXACT_CURRENT_MEMBERSHIP"}
            raise RuntimeError("full holdings not found in HTML/embedded JSON")
        except Exception as exc:
            errors.append(f"{url}: {type(exc).__name__}: {exc}")
    raise RuntimeError(" | ".join(errors))


def fetch_coinshares(session: requests.Session, ticker: str = "WGMI") -> tuple[pd.DataFrame, dict[str, Any]]:
    url = "https://coinshares.com/us/etf/wgmi/"
    r = get(session, url, timeout=60)
    for records in sorted(extract_json_record_lists(r.text), key=len, reverse=True):
        out = records_to_frame(ticker, records, url, "COINSHARES")
        if len(out) >= 20:
            return out, {"ticker": ticker, "provider": "COINSHARES", "rows": len(out), "source_url": url, "status": "PASS", "quality": "EXACT_CURRENT_MEMBERSHIP"}
    # Some builds render holdings as repeated object literals rather than valid script JSON.
    patterns = [
        re.compile(r'"productName"\s*:\s*"([^"]+)".*?"ticker"\s*:\s*"([^"]+)".*?"shares"\s*:\s*"?([0-9.,-]+)"?.*?"marketValue"\s*:\s*"?([0-9.,-]+)"?', re.I | re.S),
        re.compile(r'"name"\s*:\s*"([^"]+)".*?"ticker"\s*:\s*"([^"]+)".*?"marketValue"\s*:\s*"?([0-9.,-]+)"?', re.I | re.S),
    ]
    parsed = []
    for pat in patterns:
        for m in pat.finditer(r.text):
            vals = m.groups()
            parsed.append({"name": vals[0], "ticker": vals[1], "marketValue": vals[-1]})
        if len(parsed) >= 20:
            break
    out = records_to_frame(ticker, parsed, url, "COINSHARES") if parsed else pd.DataFrame()
    if len(out) < 20:
        raise RuntimeError(f"CoinShares full holdings not found; parsed={len(out)}")
    return out, {"ticker": ticker, "provider": "COINSHARES", "rows": len(out), "source_url": url, "status": "PASS", "quality": "EXACT_CURRENT_MEMBERSHIP"}


def fetch_boat(session: requests.Session, ticker: str = "BOAT") -> tuple[pd.DataFrame, dict[str, Any]]:
    url = "https://sonicshares.com/boat/"
    r = get(session, url, timeout=60)
    tables = html_tables(r.text)
    candidates = []
    for df in tables:
        tk = col(df, "stockticker") or col(df, "ticker")
        nm = col(df, "securityname") or col(df, "name")
        wt = col(df, "weight")
        if tk and nm and len(df) >= 15:
            candidates.append((len(df), df, tk, nm, wt))
    if not candidates:
        raise RuntimeError(f"SonicShares full holdings table not found; tables={len(tables)}")
    _, df, tk, nm, wt = max(candidates, key=lambda x: x[0])
    out = standardize(ticker, df, tk, nm, wt, url, "SONICSHARES", col(df, "cusip"))
    if len(out) < 15:
        raise RuntimeError(f"SonicShares holdings unexpectedly short: {len(out)}")
    return out, {"ticker": ticker, "provider": "SONICSHARES", "rows": len(out), "source_url": url, "status": "PASS", "quality": "EXACT_CURRENT_MEMBERSHIP"}


def fetch_jets(session: requests.Session, ticker: str = "JETS") -> tuple[pd.DataFrame, dict[str, Any]]:
    urls = ["https://www.usglobaletfs.com/fund/u-s-global-jets-etf/", "https://usglobaletfs.com/fund/u-s-global-jets-etf/"]
    errors = []
    for url in urls:
        try:
            r = get(session, url, timeout=60)
            tables = html_tables(r.text)
            candidates = []
            for df in tables:
                tk = col(df, "ticker")
                nm = col(df, "name")
                wt = col(df, "netassets") or col(df, "%netassets")
                if tk and nm and len(df) >= 15:
                    candidates.append((len(df), df, tk, nm, wt))
            if candidates:
                _, df, tk, nm, wt = max(candidates, key=lambda x: x[0])
                out = standardize(ticker, df, tk, nm, wt, url, "USGLOBAL", col(df, "cusip"))
                if len(out) >= 15:
                    return out, {"ticker": ticker, "provider": "USGLOBAL", "rows": len(out), "source_url": url, "status": "PASS", "quality": "EXACT_CURRENT_MEMBERSHIP"}
            for records in sorted(extract_json_record_lists(r.text), key=len, reverse=True):
                out = records_to_frame(ticker, records, url, "USGLOBAL")
                if len(out) >= 15:
                    return out, {"ticker": ticker, "provider": "USGLOBAL", "rows": len(out), "source_url": url, "status": "PASS", "quality": "EXACT_CURRENT_MEMBERSHIP"}
            raise RuntimeError("full holdings not found")
        except Exception as exc:
            errors.append(f"{url}: {type(exc).__name__}: {exc}")
    raise RuntimeError(" | ".join(errors))


def fetch_wcld(session: requests.Session, ticker: str = "WCLD") -> tuple[pd.DataFrame, dict[str, Any]]:
    urls = [
        "https://www.wisdomtree.com/us/products/megatrends/wcld",
        "https://www.wisdomtree.com/investments/etfs/megatrends/wcld",
    ]
    errors = []
    for url in urls:
        try:
            r = get(session, url, timeout=60)
            for records in sorted(extract_json_record_lists(r.text), key=len, reverse=True):
                out = records_to_frame(ticker, records, url, "WISDOMTREE")
                if len(out) >= 40:
                    return out, {"ticker": ticker, "provider": "WISDOMTREE", "rows": len(out), "source_url": url, "status": "PASS", "quality": "EXACT_CURRENT_MEMBERSHIP"}
            # Record candidate URLs in the exception so Actions logs expose any current Sitecore/API route.
            links = []
            for raw in re.findall(r'(?:href|src)=["\']([^"\']+)["\']', r.text, flags=re.I):
                u = urljoin(url, unescape(raw))
                if any(k in u.lower() for k in ("holding", "portfolio", "/api/", "sitecore")):
                    links.append(u)
            raise RuntimeError("embedded full holdings not found; candidates=" + " ; ".join(list(dict.fromkeys(links))[:20]))
        except Exception as exc:
            errors.append(f"{url}: {type(exc).__name__}: {exc}")
    raise RuntimeError(" | ".join(errors))


def main() -> None:
    ap = argparse.ArgumentParser(description="Repair remaining non-DRAM Theme56 exact current holdings with issuer sources")
    ap.add_argument("--output", type=Path, default=Path("leadership/research/rotation_theme56_provider_repair"))
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    session = requests.Session()

    jobs: list[tuple[str, str, Callable[[], tuple[pd.DataFrame, dict[str, Any]]]]] = [
        ("WCLD", "WISDOMTREE", lambda: fetch_wcld(session)),
        ("BLOK", "AMPLIFY", lambda: fetch_amplify(session, "BLOK")),
        ("IBUY", "AMPLIFY", lambda: fetch_amplify(session, "IBUY")),
        ("WGMI", "COINSHARES", lambda: fetch_coinshares(session)),
        ("PHO", "INVESCO", lambda: fetch_invesco(session, "PHO")),
        ("TAN", "INVESCO", lambda: fetch_invesco(session, "TAN")),
        ("PKB", "INVESCO", lambda: fetch_invesco(session, "PKB")),
        ("PEJ", "INVESCO", lambda: fetch_invesco(session, "PEJ")),
        ("BOAT", "SONICSHARES", lambda: fetch_boat(session)),
        ("JETS", "USGLOBAL", lambda: fetch_jets(session)),
    ]
    frames = []
    qa = []
    for ticker, provider, fn in jobs:
        try:
            df, diag = fn()
            frames.append(df)
            qa.append(diag)
        except Exception as exc:
            qa.append({"ticker": ticker, "provider": provider, "status": "FAIL", "error": f"{type(exc).__name__}: {exc}"})
        print(json.dumps(qa[-1], ensure_ascii=False), flush=True)

    qdf = pd.DataFrame(qa).sort_values("ticker")
    qdf.to_csv(args.output / "provider_repair_qa.csv", index=False)
    if frames:
        out = pd.concat(frames, ignore_index=True).drop_duplicates(["sector_etf", "symbol"], keep="first")
        out.to_csv(args.output / "exact_current_holdings_repair.csv", index=False)
    passed = qdf.loc[qdf["status"] == "PASS", "ticker"].tolist()
    report = {
        "schema": 1,
        "research_only": True,
        "target_count": len(TARGETS),
        "pass_count": len(passed),
        "pass_tickers": passed,
        "failures": json.loads(qdf.loc[qdf["status"] != "PASS"].where(pd.notna(qdf), None).to_json(orient="records", force_ascii=False)),
        "guardrails": [
            "Only issuer-hosted current full holdings are accepted in this repair layer.",
            "Top-10 tables are rejected.",
            "Cash/currency rows are excluded from constituent Internals.",
            "DRAM is outside this repair set and remains the explicit short-history exception.",
        ],
    }
    (args.output / "provider_repair_qa.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    if len(passed) != len(TARGETS):
        raise RuntimeError(f"Theme56 provider repair incomplete: {len(passed)}/{len(TARGETS)}")


if __name__ == "__main__":
    main()
