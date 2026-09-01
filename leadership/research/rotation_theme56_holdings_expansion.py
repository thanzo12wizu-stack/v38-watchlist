from __future__ import annotations

import io
import json
import re
from html import unescape
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin

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
    "NLR": "uranium-nuclear-energy-etf-nlr",
    "REMX": "rare-earth-strategic-metals-etf-remx",
    "PPH": "pharmaceutical-etf-pph",
    "GDX": "gold-miners-etf-gdx",
}
FIRST_TRUST_ETFS = {"CIBR", "SKYY", "GRID", "FAN"}
AMPLIFY_ETFS = {"BLOK", "IBUY"}
INVESCO_ETFS = {"PHO", "TAN", "PKB", "PEJ"}

# Bloomberg/provider exchange suffixes -> Yahoo Finance suffixes.  The original
# provider symbol is always retained separately; this is only the market-data
# lookup symbol used to calculate constituent Internals.
SPACE_SUFFIX_TO_YAHOO = {
    "KS": ".KS", "KQ": ".KQ", "HK": ".HK", "JP": ".T", "JT": ".T",
    "TT": ".TW", "GR": ".DE", "GY": ".DE", "SW": ".SW", "NA": ".AS",
    "LN": ".L", "FH": ".HE", "IM": ".MI", "FP": ".PA", "DC": ".CO",
    "PL": ".LS", "CN": ".TO", "IT": ".TA", "AU": ".AX", "SJ": ".JO",
    "NO": ".OL", "SS": ".ST",
}
DOT_SUFFIX_TO_YAHOO = {
    ".GY": ".DE", ".GR": ".DE", ".FP": ".PA", ".LN": ".L", ".IM": ".MI",
    ".DC": ".CO", ".PL": ".LS", ".CN": ".TO", ".IT": ".TA", ".JP": ".T",
    ".TT": ".TW", ".HK": ".HK", ".NA": ".AS", ".FH": ".HE", ".AU": ".AX",
    ".SJ": ".JO", ".NO": ".OL", ".SS": ".ST",
}


def _normalize_base_for_exchange(base: str, exchange: str) -> str:
    base = base.strip().upper()
    if exchange == "HK" and base.isdigit():
        base = base.zfill(4)
    # First Trust represents some London tickers as NG/.LN. Yahoo uses NG.L.
    base = base.replace("/", "-").rstrip("-")
    # Common Copenhagen B-share spelling used in provider files.
    if exchange == "DC" and base == "MAERSKB":
        base = "MAERSK-B"
    return base


def clean_symbol(value: Any) -> str:
    raw = str(value or "").strip().upper()
    if not raw or raw in {"NAN", "--", "-", "CASH&OTHER", "CASH"}:
        return ""
    raw = re.sub(r"\s+", " ", raw)
    if re.fullmatch(r"[A-Z][A-Z0-9./\-]{0,15} US", raw):
        raw = raw[:-3].strip()

    m = re.fullmatch(r"(.+?)\s+(KS|KQ|HK|JP|JT|TT|GR|GY|SW|NA|LN|FH|IM|FP|DC|PL|CN|IT|AU|SJ|NO|SS)", raw)
    if m:
        base, exchange = m.group(1), m.group(2)
        base = _normalize_base_for_exchange(base, exchange)
        return base + SPACE_SUFFIX_TO_YAHOO[exchange]

    for suffix, yahoo_suffix in DOT_SUFFIX_TO_YAHOO.items():
        if raw.endswith(suffix) and len(raw) > len(suffix):
            base = raw[:-len(suffix)]
            exchange = suffix[1:]
            base = _normalize_base_for_exchange(base, exchange)
            return base + yahoo_suffix

    # US class shares: BRK/B or BRK.B -> BRK-B for Yahoo.
    if re.fullmatch(r"[A-Z]{1,6}[/.][A-Z]", raw):
        return raw.replace("/", "-").replace(".", "-")
    return raw


def _find_csv_header(lines: list[str]) -> int:
    for i, line in enumerate(lines[:50]):
        normalized = line.replace('"', '').strip().lower()
        if "," in normalized and "ticker" in normalized and ("name" in normalized or "holding" in normalized):
            return i
    raise RuntimeError("holdings CSV header not found")


def _flat_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if isinstance(out.columns, pd.MultiIndex):
        out.columns = [" ".join(str(x).strip() for x in c if str(x) != "nan").strip() for c in out.columns]
    else:
        out.columns = [str(c).strip() for c in out.columns]
    return out


def _column(df: pd.DataFrame, *needles: str) -> str | None:
    for c in df.columns:
        low = str(c).strip().lower()
        if all(n.lower() in low for n in needles):
            return str(c)
    return None


def _num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series.astype(str).str.replace(",", "", regex=False).str.replace("%", "", regex=False).str.replace("$", "", regex=False), errors="coerce")


def _tables_from_response(r: requests.Response) -> list[pd.DataFrame]:
    return [_flat_columns(x) for x in pd.read_html(io.StringIO(r.text))]


def fetch_globalx(session: requests.Session, ticker: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    page = f"https://www.globalxetfs.com/funds/{ticker.lower()}"
    r = session.get(page, headers={"User-Agent": flowlib.UA}, timeout=45)
    r.raise_for_status()
    pattern = re.compile(rf"https://assets\.globalxetfs\.com/funds/holdings/{ticker.lower()}_full-holdings_\d{{8}}\.csv", re.I)
    hits = pattern.findall(r.text)
    if not hits:
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
    text = h.content.decode("utf-8-sig", errors="replace")
    lines = text.splitlines()
    header_idx = _find_csv_header(lines)
    df = pd.read_csv(io.StringIO("\n".join(lines[header_idx:])), engine="python")
    columns = {str(c).strip().lower(): c for c in df.columns}
    ticker_col = columns.get("ticker")
    name_col = columns.get("name") or next((c for c in df.columns if "holding name" in str(c).lower()), None)
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


def fetch_first_trust(session: requests.Session, ticker: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    url = f"https://www.ftportfolios.com/Retail/Etf/EtfHoldings.aspx?Ticker={ticker}"
    r = session.get(url, headers={"User-Agent": flowlib.UA}, timeout=45)
    r.raise_for_status()
    tables = _tables_from_response(r)
    selected = None
    for df in tables:
        if _column(df, "security", "name") and _column(df, "identifier") and _column(df, "weight"):
            selected = df
            break
    if selected is None:
        raise RuntimeError("First Trust holdings table not found")
    symbol_col = _column(selected, "identifier")
    name_col = _column(selected, "security", "name")
    weight_col = _column(selected, "weight")
    if not symbol_col or not name_col:
        raise RuntimeError(f"First Trust columns missing: {list(selected.columns)}")
    out = pd.DataFrame({
        "sector_etf": ticker,
        "provider_symbol": selected[symbol_col].astype(str),
        "symbol": selected[symbol_col].map(clean_symbol),
        "weight_pct": _num(selected[weight_col]) if weight_col else None,
        "name": selected[name_col].astype(str),
        "source_url": url,
        "provider": "FIRSTTRUST",
    })
    out = out[out["symbol"] != ""].drop_duplicates("symbol", keep="first")
    if len(out) < 5:
        raise RuntimeError(f"too few First Trust holdings parsed: {len(out)}")
    return out.reset_index(drop=True), {"ticker": ticker, "provider": "FIRSTTRUST", "rows": int(len(out)), "source_url": url, "quality": "EXACT_CURRENT_MEMBERSHIP"}


def _find_best_holdings_table(tables: list[pd.DataFrame], ticker_needles: tuple[str, ...] = ("ticker",)) -> pd.DataFrame | None:
    best: pd.DataFrame | None = None
    for df in tables:
        has_ticker = any(_column(df, x) for x in ticker_needles)
        if has_ticker and len(df) >= 5 and (best is None or len(df) > len(best)):
            best = df
    return best


def fetch_defiance_qtum(session: requests.Session, ticker: str = "QTUM") -> tuple[pd.DataFrame, dict[str, Any]]:
    url = "https://www.defianceetfs.com/qtum-full-holdings/"
    r = session.get(url, headers={"User-Agent": flowlib.UA}, timeout=45)
    r.raise_for_status()
    df = _find_best_holdings_table(_tables_from_response(r))
    if df is None:
        raise RuntimeError("Defiance full holdings table not found")
    ticker_col = _column(df, "ticker")
    name_col = _column(df, "name")
    weight_col = _column(df, "weight")
    out = pd.DataFrame({
        "sector_etf": ticker,
        "provider_symbol": df[ticker_col].astype(str),
        "symbol": df[ticker_col].map(clean_symbol),
        "weight_pct": _num(df[weight_col]) if weight_col else None,
        "name": df[name_col].astype(str) if name_col else "",
        "source_url": url,
        "provider": "DEFIANCE",
    })
    out = out[out["symbol"] != ""].drop_duplicates("symbol", keep="first")
    if len(out) < 20:
        raise RuntimeError(f"Defiance full holdings unexpectedly short: {len(out)}")
    return out.reset_index(drop=True), {"ticker": ticker, "provider": "DEFIANCE", "rows": int(len(out)), "source_url": url, "quality": "EXACT_CURRENT_MEMBERSHIP"}


def fetch_coinshares_wgmi(session: requests.Session, ticker: str = "WGMI") -> tuple[pd.DataFrame, dict[str, Any]]:
    url = "https://coinshares.com/us/etf/wgmi/"
    r = session.get(url, headers={"User-Agent": flowlib.UA}, timeout=45)
    r.raise_for_status()
    tables = _tables_from_response(r)
    df = next((x for x in tables if _column(x, "product", "name") and _column(x, "ticker") and _column(x, "marketvalue")), None)
    if df is None:
        raise RuntimeError("CoinShares WGMI holdings table not found")
    ticker_col = _column(df, "ticker")
    name_col = _column(df, "product", "name")
    mv_col = _column(df, "marketvalue")
    mv = _num(df[mv_col]) if mv_col else pd.Series(index=df.index, dtype=float)
    total = float(mv.clip(lower=0).sum()) if not mv.empty else 0.0
    weights = (100.0 * mv / total) if total > 0 else pd.Series(index=df.index, dtype=float)
    out = pd.DataFrame({
        "sector_etf": ticker,
        "provider_symbol": df[ticker_col].astype(str),
        "symbol": df[ticker_col].map(clean_symbol),
        "weight_pct": weights,
        "name": df[name_col].astype(str),
        "source_url": url,
        "provider": "COINSHARES",
    })
    out = out[out["symbol"] != ""].drop_duplicates("symbol", keep="first")
    if len(out) < 20:
        raise RuntimeError(f"CoinShares WGMI holdings unexpectedly short: {len(out)}")
    return out.reset_index(drop=True), {"ticker": ticker, "provider": "COINSHARES", "rows": int(len(out)), "source_url": url, "quality": "EXACT_CURRENT_MEMBERSHIP"}


def fetch_sonic_boat(session: requests.Session, ticker: str = "BOAT") -> tuple[pd.DataFrame, dict[str, Any]]:
    url = "https://sonicshares.com/boat/"
    r = session.get(url, headers={"User-Agent": flowlib.UA}, timeout=45)
    r.raise_for_status()
    tables = _tables_from_response(r)
    df = next((x for x in tables if _column(x, "stockticker") and _column(x, "securityname")), None)
    if df is None:
        raise RuntimeError("SonicShares BOAT holdings table not found")
    ticker_col = _column(df, "stockticker")
    name_col = _column(df, "securityname")
    weight_col = _column(df, "weight")
    out = pd.DataFrame({
        "sector_etf": ticker,
        "provider_symbol": df[ticker_col].astype(str),
        "symbol": df[ticker_col].map(clean_symbol),
        "weight_pct": _num(df[weight_col]) if weight_col else None,
        "name": df[name_col].astype(str),
        "source_url": url,
        "provider": "SONICSHARES",
    })
    out = out[out["symbol"] != ""].drop_duplicates("symbol", keep="first")
    if len(out) < 15:
        raise RuntimeError(f"SonicShares BOAT holdings unexpectedly short: {len(out)}")
    return out.reset_index(drop=True), {"ticker": ticker, "provider": "SONICSHARES", "rows": int(len(out)), "source_url": url, "quality": "EXACT_CURRENT_MEMBERSHIP"}


def fetch_usglobal_jets(session: requests.Session, ticker: str = "JETS") -> tuple[pd.DataFrame, dict[str, Any]]:
    url = "https://usglobaletfs.com/fund/u-s-global-jets-etf/"
    r = session.get(url, headers={"User-Agent": flowlib.UA}, timeout=45)
    r.raise_for_status()
    tables = _tables_from_response(r)
    df = next((x for x in tables if _column(x, "ticker") and _column(x, "net assets") and _column(x, "name")), None)
    if df is None:
        raise RuntimeError("U.S. Global JETS holdings table not found")
    ticker_col = _column(df, "ticker")
    name_col = _column(df, "name")
    weight_col = _column(df, "net assets")
    out = pd.DataFrame({
        "sector_etf": ticker,
        "provider_symbol": df[ticker_col].astype(str),
        "symbol": df[ticker_col].map(clean_symbol),
        "weight_pct": _num(df[weight_col]) if weight_col else None,
        "name": df[name_col].astype(str),
        "source_url": url,
        "provider": "USGLOBAL",
    })
    out = out[out["symbol"] != ""].drop_duplicates("symbol", keep="first")
    if len(out) < 15:
        raise RuntimeError(f"JETS holdings unexpectedly short: {len(out)}")
    return out.reset_index(drop=True), {"ticker": ticker, "provider": "USGLOBAL", "rows": int(len(out)), "source_url": url, "quality": "EXACT_CURRENT_MEMBERSHIP"}


def _extract_links(base_url: str, html: str) -> list[str]:
    links: list[str] = []
    for raw in re.findall(r"href\s*=\s*[\"']([^\"']+)[\"']", html, flags=re.I):
        url = urljoin(base_url, unescape(raw).replace("&amp;", "&"))
        if url.startswith("http"):
            links.append(url)
    return list(dict.fromkeys(links))


def _read_csv_candidate(session: requests.Session, url: str) -> pd.DataFrame:
    r = session.get(url, headers={"User-Agent": flowlib.UA, "Accept": "text/csv,application/csv,*/*"}, timeout=45)
    r.raise_for_status()
    text = r.content.decode("utf-8-sig", errors="replace")
    return pd.read_csv(io.StringIO(text), engine="python")


def fetch_arkw(session: requests.Session, ticker: str = "ARKW") -> tuple[pd.DataFrame, dict[str, Any]]:
    page = "https://www.ark-funds.com/funds/arkw"
    r = session.get(page, headers={"User-Agent": flowlib.UA}, timeout=45)
    r.raise_for_status()
    candidates = [u for u in _extract_links(page, r.text) if ".csv" in u.lower() and ("arkw" in u.lower() or "holding" in u.lower())]
    candidates += [
        "https://assets.ark-funds.com/fund-documents/funds-etf-csv/ARK_NEXT_GENERATION_INTERNET_ETF_ARKW_HOLDINGS.csv",
    ]
    errors: list[str] = []
    for url in list(dict.fromkeys(candidates)):
        try:
            df = _read_csv_candidate(session, url)
            cols = {str(c).strip().lower(): c for c in df.columns}
            ticker_col = next((c for k, c in cols.items() if k == "ticker" or k.endswith("ticker")), None)
            name_col = next((c for k, c in cols.items() if "company" in k or k == "name"), None)
            weight_col = next((c for k, c in cols.items() if "weight" in k), None)
            if ticker_col is None:
                raise RuntimeError(f"ticker column missing: {list(df.columns)}")
            out = pd.DataFrame({
                "sector_etf": ticker,
                "provider_symbol": df[ticker_col].astype(str),
                "symbol": df[ticker_col].map(clean_symbol),
                "weight_pct": _num(df[weight_col]) if weight_col else None,
                "name": df[name_col].astype(str) if name_col else "",
                "source_url": url,
                "provider": "ARK",
            })
            out = out[out["symbol"] != ""].drop_duplicates("symbol", keep="first")
            if len(out) < 15:
                raise RuntimeError(f"too few ARKW holdings: {len(out)}")
            return out.reset_index(drop=True), {"ticker": ticker, "provider": "ARK", "rows": int(len(out)), "source_url": url, "quality": "EXACT_CURRENT_MEMBERSHIP"}
        except Exception as exc:
            errors.append(f"{url}: {type(exc).__name__}: {exc}")
    raise RuntimeError(" | ".join(errors) if errors else "ARKW holdings CSV URL not found")


def fetch_wisdomtree_wcld(session: requests.Session, ticker: str = "WCLD") -> tuple[pd.DataFrame, dict[str, Any]]:
    url = "https://www.wisdomtree.com/us/products/megatrends/wcld"
    r = session.get(url, headers={"User-Agent": flowlib.UA}, timeout=45)
    r.raise_for_status()
    tables = _tables_from_response(r)
    candidates = [x for x in tables if _column(x, "name") and _column(x, "weight") and len(x) >= 15]
    if not candidates:
        raise RuntimeError("WisdomTree full holdings table is not present in server HTML")
    df = max(candidates, key=len)
    name_col = _column(df, "name")
    weight_col = _column(df, "weight")
    ticker_col = _column(df, "ticker") or _column(df, "symbol")
    if ticker_col is None:
        raise RuntimeError("WisdomTree full table lacks ticker/symbol; name-only data is not accepted")
    out = pd.DataFrame({
        "sector_etf": ticker,
        "provider_symbol": df[ticker_col].astype(str),
        "symbol": df[ticker_col].map(clean_symbol),
        "weight_pct": _num(df[weight_col]) if weight_col else None,
        "name": df[name_col].astype(str),
        "source_url": url,
        "provider": "WISDOMTREE",
    })
    out = out[out["symbol"] != ""].drop_duplicates("symbol", keep="first")
    if len(out) < 15:
        raise RuntimeError(f"WCLD holdings unexpectedly short: {len(out)}")
    return out.reset_index(drop=True), {"ticker": ticker, "provider": "WISDOMTREE", "rows": int(len(out)), "source_url": url, "quality": "EXACT_CURRENT_MEMBERSHIP"}


def fetch_amplify(session: requests.Session, ticker: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    url = f"https://amplifyetfs.com/{ticker.lower()}/"
    r = session.get(url, headers={"User-Agent": flowlib.UA}, timeout=45)
    r.raise_for_status()
    expected = None
    m = re.search(r"Holdings\s*\(view all holdings\)\s*</?[^>]*>?\s*(\d+)", r.text, flags=re.I)
    if m:
        expected = int(m.group(1))
    tables = _tables_from_response(r)
    candidates = [x for x in tables if _column(x, "ticker") and _column(x, "market value", "%")]
    if not candidates:
        raise RuntimeError("Amplify holdings table not found")
    df = max(candidates, key=len)
    if expected is not None and len(df) < max(5, expected - 2):
        raise RuntimeError(f"Amplify page exposed only partial holdings ({len(df)}/{expected})")
    if expected is None and len(df) <= 10:
        raise RuntimeError("Amplify page exposed only Top 10; refusing partial membership")
    ticker_col = _column(df, "ticker")
    name_col = _column(df, "name")
    weight_col = _column(df, "market value", "%")
    out = pd.DataFrame({
        "sector_etf": ticker,
        "provider_symbol": df[ticker_col].astype(str),
        "symbol": df[ticker_col].map(clean_symbol),
        "weight_pct": _num(df[weight_col]) if weight_col else None,
        "name": df[name_col].astype(str) if name_col else "",
        "source_url": url,
        "provider": "AMPLIFY",
    })
    out = out[out["symbol"] != ""].drop_duplicates("symbol", keep="first")
    if len(out) < 15:
        raise RuntimeError(f"Amplify holdings unexpectedly short: {len(out)}")
    return out.reset_index(drop=True), {"ticker": ticker, "provider": "AMPLIFY", "rows": int(len(out)), "source_url": url, "quality": "EXACT_CURRENT_MEMBERSHIP"}


def fetch_roundhill_dram(session: requests.Session, ticker: str = "DRAM") -> tuple[pd.DataFrame, dict[str, Any]]:
    page = "https://www.roundhillinvestments.com/etf/dram/"
    r = session.get(page, headers={"User-Agent": flowlib.UA}, timeout=45)
    r.raise_for_status()
    links = _extract_links(page, r.text)
    candidates = [u for u in links if ".csv" in u.lower() and ("dram" in u.lower() or "holding" in u.lower())]
    errors: list[str] = []
    for url in candidates:
        try:
            df = _read_csv_candidate(session, url)
            df = _flat_columns(df)
            ticker_col = _column(df, "ticker") or _column(df, "symbol")
            name_col = _column(df, "name")
            weight_col = _column(df, "weight")
            if ticker_col is None:
                raise RuntimeError("ticker/symbol column missing")
            out = pd.DataFrame({
                "sector_etf": ticker,
                "provider_symbol": df[ticker_col].astype(str),
                "symbol": df[ticker_col].map(clean_symbol),
                "weight_pct": _num(df[weight_col]) if weight_col else None,
                "name": df[name_col].astype(str) if name_col else "",
                "source_url": url,
                "provider": "ROUNDHILL",
            })
            out = out[out["symbol"] != ""].drop_duplicates("symbol", keep="first")
            if len(out) < 5:
                raise RuntimeError(f"too few DRAM holdings: {len(out)}")
            return out.reset_index(drop=True), {"ticker": ticker, "provider": "ROUNDHILL", "rows": int(len(out)), "source_url": url, "quality": "EXACT_CURRENT_MEMBERSHIP"}
        except Exception as exc:
            errors.append(f"{url}: {type(exc).__name__}: {exc}")
    raise RuntimeError(" | ".join(errors) if errors else "Roundhill DRAM download CSV URL not found in official page")


def fetch_invesco(session: requests.Session, ticker: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    slugs = {
        "PHO": "invesco-water-resources-etf",
        "TAN": "invesco-solar-etf",
        "PKB": "invesco-building-construction-etf",
        "PEJ": "invesco-leisure-and-entertainment-etf",
    }
    page = f"https://www.invesco.com/us/en/financial-products/etfs/{slugs[ticker]}.html"
    r = session.get(page, headers={"User-Agent": flowlib.UA}, timeout=45)
    r.raise_for_status()
    links = _extract_links(page, r.text)
    candidates = [u for u in links if any(ext in u.lower() for ext in (".csv", ".xlsx", ".xls")) and (ticker.lower() in u.lower() or "holding" in u.lower() or "portfolio" in u.lower())]
    errors: list[str] = []
    for url in candidates:
        try:
            rr = session.get(url, headers={"User-Agent": flowlib.UA}, timeout=45)
            rr.raise_for_status()
            if ".xls" in url.lower():
                df = pd.read_excel(io.BytesIO(rr.content), engine="openpyxl")
            else:
                df = pd.read_csv(io.BytesIO(rr.content))
            df = _flat_columns(df)
            ticker_col = _column(df, "ticker") or _column(df, "symbol")
            name_col = _column(df, "name") or _column(df, "holding")
            weight_col = _column(df, "weight") or _column(df, "net assets")
            if ticker_col is None:
                raise RuntimeError(f"ticker column missing: {list(df.columns)}")
            out = pd.DataFrame({
                "sector_etf": ticker,
                "provider_symbol": df[ticker_col].astype(str),
                "symbol": df[ticker_col].map(clean_symbol),
                "weight_pct": _num(df[weight_col]) if weight_col else None,
                "name": df[name_col].astype(str) if name_col else "",
                "source_url": url,
                "provider": "INVESCO",
            })
            out = out[out["symbol"] != ""].drop_duplicates("symbol", keep="first")
            if len(out) < 15:
                raise RuntimeError(f"too few Invesco holdings: {len(out)}")
            return out.reset_index(drop=True), {"ticker": ticker, "provider": "INVESCO", "rows": int(len(out)), "source_url": url, "quality": "EXACT_CURRENT_MEMBERSHIP"}
        except Exception as exc:
            errors.append(f"{url}: {type(exc).__name__}: {exc}")
    raise RuntimeError(" | ".join(errors) if errors else "Invesco server HTML did not expose an official holdings export URL")


def _clean_json_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    if df.empty:
        return []
    return json.loads(df.where(pd.notna(df), None).to_json(orient="records", force_ascii=False))


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="Expand Theme56 exact official current holdings and normalize provider symbols for Internals")
    ap.add_argument("--output", type=Path, default=Path("leadership/research/rotation_theme56_holdings_expansion"))
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    frames: list[pd.DataFrame] = []
    rows: list[dict[str, Any]] = []

    jobs: list[tuple[str, str, Callable[[], tuple[pd.DataFrame, dict[str, Any]]]]] = []
    for ticker in sorted(GLOBALX_ETFS):
        jobs.append((ticker, "GLOBALX", lambda t=ticker: fetch_globalx(session, t)))
    for ticker, slug in sorted(VANECK_SLUGS.items()):
        jobs.append((ticker, "VANECK", lambda t=ticker, s=slug: fetch_vaneck(session, t, s)))
    for ticker in sorted(FIRST_TRUST_ETFS):
        jobs.append((ticker, "FIRSTTRUST", lambda t=ticker: fetch_first_trust(session, t)))
    jobs += [
        ("QTUM", "DEFIANCE", lambda: fetch_defiance_qtum(session)),
        ("WGMI", "COINSHARES", lambda: fetch_coinshares_wgmi(session)),
        ("BOAT", "SONICSHARES", lambda: fetch_sonic_boat(session)),
        ("JETS", "USGLOBAL", lambda: fetch_usglobal_jets(session)),
        ("ARKW", "ARK", lambda: fetch_arkw(session)),
        ("WCLD", "WISDOMTREE", lambda: fetch_wisdomtree_wcld(session)),
        ("DRAM", "ROUNDHILL", lambda: fetch_roundhill_dram(session)),
    ]
    for ticker in sorted(AMPLIFY_ETFS):
        jobs.append((ticker, "AMPLIFY", lambda t=ticker: fetch_amplify(session, t)))
    for ticker in sorted(INVESCO_ETFS):
        jobs.append((ticker, "INVESCO", lambda t=ticker: fetch_invesco(session, t)))

    for ticker, provider, fn in jobs:
        try:
            h, d = fn()
            frames.append(h)
            rows.append({**d, "status": "PASS"})
        except Exception as exc:
            rows.append({"ticker": ticker, "provider": provider, "status": "FAIL", "error": f"{type(exc).__name__}: {exc}"})
        print(json.dumps(rows[-1], ensure_ascii=False), flush=True)

    qa = pd.DataFrame(rows).sort_values(["provider", "ticker"])
    qa.to_csv(args.output / "holdings_expansion_qa.csv", index=False)
    if frames:
        all_holdings = pd.concat(frames, ignore_index=True)
        all_holdings = all_holdings.drop_duplicates(["sector_etf", "symbol"], keep="first")
        all_holdings.to_csv(args.output / "exact_current_holdings_expansion.csv", index=False)
    passed = qa[qa["status"] == "PASS"]
    report = {
        "schema": 3,
        "research_only": True,
        "candidate_count": int(len(qa)),
        "pass_count": int(len(passed)),
        "pass_tickers": passed["ticker"].tolist(),
        "failures": _clean_json_records(qa.loc[qa["status"] != "PASS"]),
        "symbol_normalization": "Provider/Bloomberg foreign exchange symbols are normalized only for constituent market-data lookup; original provider_symbol is preserved.",
        "guardrails": [
            "Only exact current official provider membership is accepted.",
            "Partial Top-10 tables are rejected when full holdings cannot be confirmed.",
            "This expands membership for Internals only; it does not claim Exact Flow availability.",
            "No price-volume or other proxy is substituted for official fund flow.",
        ],
    }
    (args.output / "holdings_expansion_qa.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
