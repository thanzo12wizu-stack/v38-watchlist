from __future__ import annotations

import argparse
import io
import json
import math
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlencode

import pandas as pd
import requests

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

SSGA_TICKERS = {
    "XLC", "XLY", "XLP", "XLE", "XLF", "XLV", "XLI", "XLB", "XLRE", "XLK", "XLU",
    "XBI", "SPY",
}
ISHARES_TICKERS = {"SOXX", "IBB", "ICLN"}
DEFAULT_TICKERS = [
    "XLC", "XLY", "XLP", "XLE", "XLF", "XLV", "XLI", "XLB", "XLRE", "XLK", "XLU",
    "XBI", "SOXX", "IBB", "ICLN",
]

SSGA_NAV_URL = "https://www.ssga.com/library-content/products/fund-data/etfs/us/navhist-us-en-{ticker}.xlsx"
ISHARES_SCREENER_URL = (
    "https://www.ishares.com/us/product-screener/product-screener-v3.1.jsn"
    "?dcrPath=/templatedata/config/product-screener-v3/data/en/us-ishares/ishares-product-screener-backend-config"
    "&siteEntryPassthrough=true"
)
ISHARES_PRODUCT_DATA_URL = "https://www.ishares.com/varnish-api/blk-one01-product-data/product-data/api/v2/get-product-data"


@dataclass(frozen=True)
class ProviderSeries:
    ticker: str
    provider: str
    frame: pd.DataFrame
    source_url: str


def _clean_num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        x = float(value)
        return x if math.isfinite(x) else None
    text = str(value).strip()
    if not text or text in {"-", "--", "N/A", "nan", "NaN"}:
        return None
    text = re.sub(r"[$,%\s]", "", text.replace(",", ""))
    try:
        x = float(text)
    except ValueError:
        return None
    return x if math.isfinite(x) else None


def _norm_header(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _http_get(session: requests.Session, url: str, *, timeout: int = 30) -> requests.Response:
    response = session.get(url, headers={"User-Agent": UA, "Accept": "application/json,*/*"}, timeout=timeout)
    response.raise_for_status()
    return response


def fetch_ssga_nav_history(session: requests.Session, ticker: str) -> ProviderSeries:
    url = SSGA_NAV_URL.format(ticker=ticker.lower())
    response = _http_get(session, url, timeout=45)
    matrix = pd.read_excel(io.BytesIO(response.content), sheet_name=0, header=None, engine="openpyxl")

    header_idx = None
    for idx, row in matrix.iterrows():
        headers = {_norm_header(x) for x in row.tolist()}
        if "date" in headers and "nav" in headers and "shares outstanding" in headers:
            header_idx = idx
            break
    if header_idx is None:
        raise RuntimeError(f"{ticker}: SSGA NAV workbook header not found")

    headers = [_norm_header(x) for x in matrix.iloc[header_idx].tolist()]
    col_map = {name: i for i, name in enumerate(headers) if name}
    required = ["date", "nav", "shares outstanding"]
    missing = [name for name in required if name not in col_map]
    if missing:
        raise RuntimeError(f"{ticker}: SSGA missing columns {missing}")

    rows = matrix.iloc[header_idx + 1 :].copy()
    out = pd.DataFrame({
        "date": pd.to_datetime(rows.iloc[:, col_map["date"]], errors="coerce"),
        "nav": rows.iloc[:, col_map["nav"]].map(_clean_num),
        "shares_outstanding": rows.iloc[:, col_map["shares outstanding"]].map(_clean_num),
    })
    if "total net assets" in col_map:
        out["total_net_assets"] = rows.iloc[:, col_map["total net assets"]].map(_clean_num)
    else:
        out["total_net_assets"] = None

    out = out.dropna(subset=["date", "nav", "shares_outstanding"]).copy()
    out["date"] = pd.to_datetime(out["date"]).dt.normalize()
    out = out[(out["nav"] > 0) & (out["shares_outstanding"] > 0)]
    out = out.drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True)
    if out.empty:
        raise RuntimeError(f"{ticker}: SSGA NAV history empty after parsing")
    return ProviderSeries(ticker=ticker, provider="SSGA", frame=out, source_url=url)


def _ishares_disp(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict) and "d" in value:
        value = value.get("d")
    text = str(value).strip()
    return None if text in {"", "-"} else text


def _ishares_num(value: Any) -> float | None:
    if isinstance(value, dict) and "r" in value:
        value = value.get("r")
    return _clean_num(value)


def resolve_ishares_portfolio_ids(session: requests.Session, tickers: Iterable[str]) -> dict[str, int]:
    response = _http_get(session, ISHARES_SCREENER_URL, timeout=45)
    data = response.json()
    wanted = {t.upper() for t in tickers}
    result: dict[str, int] = {}
    if not isinstance(data, dict):
        return result
    for key, raw in data.items():
        if not isinstance(raw, dict) or raw.get("productType") != "ISHARES_FUND_DATA":
            continue
        ticker = (_ishares_disp(raw.get("localExchangeTicker")) or "").upper()
        if ticker not in wanted:
            continue
        pid = _ishares_num(raw.get("portfolioId"))
        if pid is None:
            try:
                pid = float(key)
            except (TypeError, ValueError):
                pid = None
        if pid is not None and float(pid).is_integer():
            result[ticker] = int(pid)
    return result


def _parallel_values(points: dict[str, Any], key: str) -> list[Any]:
    raw = points.get(key) or {}
    values = raw.get("value") if isinstance(raw, dict) else None
    return values if isinstance(values, list) else []


def fetch_ishares_nav_history(session: requests.Session, ticker: str, portfolio_id: int) -> ProviderSeries:
    params = {
        "appSubType": "ISHARES",
        "appType": "PRODUCT_PAGE",
        "component": "fundDownload",
        "locale": "en_US",
        "portfolioId": str(portfolio_id),
        "targetSite": "us-ishares",
        "userType": "individual",
        "excludeContent": "true",
    }
    url = f"{ISHARES_PRODUCT_DATA_URL}?{urlencode(params)}"
    response = _http_get(session, url, timeout=45)
    data = response.json()
    points = (
        data.get("componentsByNameMap", {})
        .get("fundDownload", {})
        .get("containersByNameMap", {})
        .get("historical", {})
        .get("dataPointsByNameMap", {})
    )
    if not isinstance(points, dict):
        raise RuntimeError(f"{ticker}: iShares historical container missing")

    dates = _parallel_values(points, "asof")
    navs = _parallel_values(points, "nav")
    shares = _parallel_values(points, "sharesOutstanding")
    n = max(len(dates), len(navs), len(shares))
    records: list[dict[str, Any]] = []
    for i in range(n):
        d = dates[i] if i < len(dates) else None
        nav = navs[i] if i < len(navs) else None
        sh = shares[i] if i < len(shares) else None
        try:
            d_int = int(float(d)) if d is not None else 0
            dt = pd.to_datetime(str(d_int), format="%Y%m%d", errors="coerce")
        except (TypeError, ValueError):
            dt = pd.NaT
        records.append({"date": dt, "nav": _clean_num(nav), "shares_outstanding": _clean_num(sh)})

    out = pd.DataFrame(records)
    out["total_net_assets"] = None
    out = out.dropna(subset=["date", "nav", "shares_outstanding"]).copy()
    out["date"] = pd.to_datetime(out["date"]).dt.normalize()
    out = out[(out["nav"] > 0) & (out["shares_outstanding"] > 0)]
    out = out.drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True)
    if out.empty:
        raise RuntimeError(f"{ticker}: iShares NAV history empty after parsing")
    return ProviderSeries(ticker=ticker, provider="ISHARES", frame=out, source_url=url)


def _nearest_canonical_ratio(value: float) -> float | None:
    candidates = (0.1, 0.2, 0.25, 1.0 / 3.0, 0.5, 2.0, 3.0, 4.0, 5.0, 10.0)
    if not math.isfinite(value) or value <= 0:
        return None
    hit = min(candidates, key=lambda x: abs(math.log(value / x)))
    return hit if abs(math.log(value / hit)) <= math.log(1.03) else None


def derive_exact_flows(series: ProviderSeries) -> tuple[pd.DataFrame, dict[str, Any]]:
    df = series.frame.copy().sort_values("date").reset_index(drop=True)
    df["ticker"] = series.ticker
    df["provider"] = series.provider
    df["source_url"] = series.source_url
    df["aum"] = pd.to_numeric(df["total_net_assets"], errors="coerce")
    fallback_aum = pd.to_numeric(df["shares_outstanding"], errors="coerce") * pd.to_numeric(df["nav"], errors="coerce")
    df["aum"] = df["aum"].where(df["aum"] > 0).fillna(fallback_aum)

    prev_shares = df["shares_outstanding"].shift(1)
    prev_nav = df["nav"].shift(1)
    share_ratio = df["shares_outstanding"] / prev_shares
    nav_ratio = df["nav"] / prev_nav

    split_ratio: list[float | None] = []
    split_flag: list[bool] = []
    for sr, nr in zip(share_ratio.tolist(), nav_ratio.tolist()):
        if pd.isna(sr) or pd.isna(nr):
            split_ratio.append(None)
            split_flag.append(False)
            continue
        canonical = _nearest_canonical_ratio(float(sr))
        product = float(sr) * float(nr)
        is_split = canonical is not None and 0.92 <= product <= 1.08
        split_ratio.append(canonical if is_split else None)
        split_flag.append(is_split)

    df["split_detected"] = split_flag
    df["split_ratio"] = split_ratio
    effective_prev_shares = prev_shares.copy()
    for idx, ratio in enumerate(split_ratio):
        if ratio is not None and idx > 0 and pd.notna(prev_shares.iloc[idx]):
            effective_prev_shares.iloc[idx] = float(prev_shares.iloc[idx]) * float(ratio)

    df["flow_usd"] = (df["shares_outstanding"] - effective_prev_shares) * df["nav"]
    df.loc[0, "flow_usd"] = math.nan
    df["flow_1d"] = df["flow_usd"]
    df["flow_5d"] = df["flow_usd"].rolling(5, min_periods=5).sum()
    df["flow_20d"] = df["flow_usd"].rolling(20, min_periods=20).sum()
    df["flow_20d_pct_aum"] = 100.0 * df["flow_20d"] / df["aum"]

    identity_rel_err = pd.Series(dtype=float)
    if pd.to_numeric(df["total_net_assets"], errors="coerce").notna().any():
        tna = pd.to_numeric(df["total_net_assets"], errors="coerce")
        calc = df["shares_outstanding"] * df["nav"]
        identity_rel_err = ((tna - calc).abs() / tna.abs()).replace([math.inf, -math.inf], math.nan).dropna()

    diagnostics = {
        "ticker": series.ticker,
        "provider": series.provider,
        "source_url": series.source_url,
        "first_date": str(df["date"].min().date()),
        "last_date": str(df["date"].max().date()),
        "rows": int(len(df)),
        "valid_flow_rows": int(df["flow_usd"].notna().sum()),
        "split_events": int(df["split_detected"].sum()),
        "split_dates": [str(x.date()) for x in df.loc[df["split_detected"], "date"].tolist()],
        "median_tna_identity_rel_error": float(identity_rel_err.median()) if not identity_rel_err.empty else None,
        "max_tna_identity_rel_error": float(identity_rel_err.max()) if not identity_rel_err.empty else None,
        "status": "EXACT_OFFICIAL_SHARES_OUTSTANDING_DERIVED",
    }
    return df, diagnostics


def main() -> None:
    parser = argparse.ArgumentParser(description="Reconstruct exact ETF fund flows from official daily NAV + shares outstanding history")
    parser.add_argument("--output", type=Path, default=Path("leadership/research/rotation_exact_flow_outputs"))
    parser.add_argument("--start", default="2022-01-01")
    parser.add_argument("--end", default=str(date.today()))
    parser.add_argument("--tickers", nargs="*", default=DEFAULT_TICKERS)
    args = parser.parse_args()

    start = pd.Timestamp(args.start).normalize()
    end = pd.Timestamp(args.end).normalize()
    tickers = [str(t).upper().strip() for t in args.tickers if str(t).strip()]
    unknown = [t for t in tickers if t not in SSGA_TICKERS and t not in ISHARES_TICKERS]
    if unknown:
        raise SystemExit(f"unsupported provider mapping for tickers: {unknown}")

    args.output.mkdir(parents=True, exist_ok=True)
    session = requests.Session()

    ishares_needed = [t for t in tickers if t in ISHARES_TICKERS]
    ishares_ids = resolve_ishares_portfolio_ids(session, ishares_needed) if ishares_needed else {}

    all_frames: list[pd.DataFrame] = []
    diagnostics: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []

    for ticker in tickers:
        try:
            if ticker in SSGA_TICKERS:
                series = fetch_ssga_nav_history(session, ticker)
            else:
                pid = ishares_ids.get(ticker)
                if pid is None:
                    raise RuntimeError(f"{ticker}: portfolioId not found in iShares screener")
                series = fetch_ishares_nav_history(session, ticker, pid)
            flow_df, diag = derive_exact_flows(series)
            flow_df = flow_df[(flow_df["date"] >= start) & (flow_df["date"] <= end)].copy()
            if flow_df.empty:
                raise RuntimeError(f"{ticker}: no rows in requested window {start.date()}..{end.date()}")
            all_frames.append(flow_df)
            diagnostics.append(diag)
            print(f"{ticker}: provider={series.provider} rows={len(flow_df)} splits={diag['split_events']} {flow_df['date'].min().date()}->{flow_df['date'].max().date()}")
        except Exception as exc:
            failures.append({"ticker": ticker, "error": f"{type(exc).__name__}: {exc}"})
            print(f"{ticker}: FAILED {type(exc).__name__}: {exc}")

    if not all_frames:
        raise RuntimeError("no exact-flow series could be built")

    flows = pd.concat(all_frames, ignore_index=True).sort_values(["date", "ticker"]).reset_index(drop=True)
    cols = [
        "date", "ticker", "provider", "nav", "shares_outstanding", "total_net_assets", "aum",
        "split_detected", "split_ratio", "flow_usd", "flow_1d", "flow_5d", "flow_20d", "flow_20d_pct_aum", "source_url",
    ]
    flows[cols].to_csv(args.output / "rotation_exact_flows.csv", index=False, date_format="%Y-%m-%d")

    latest_rows = []
    for ticker, grp in flows.groupby("ticker"):
        row = grp.sort_values("date").iloc[-1]
        latest_rows.append({
            "ticker": ticker,
            "date": str(pd.Timestamp(row["date"]).date()),
            "provider": row["provider"],
            "flow_1d": None if pd.isna(row["flow_1d"]) else float(row["flow_1d"]),
            "flow_5d": None if pd.isna(row["flow_5d"]) else float(row["flow_5d"]),
            "flow_20d": None if pd.isna(row["flow_20d"]) else float(row["flow_20d"]),
            "flow_20d_pct_aum": None if pd.isna(row["flow_20d_pct_aum"]) else float(row["flow_20d_pct_aum"]),
            "aum": None if pd.isna(row["aum"]) else float(row["aum"]),
        })

    summary = {
        "schema": 1,
        "research_only": True,
        "flow_definition": "daily net creation/redemption flow = split-normalized change in official shares outstanding multiplied by same-day official NAV",
        "quality": "EXACT_OFFICIAL_SHARES_OUTSTANDING_DERIVED",
        "requested_window": {"start": str(start.date()), "end": str(end.date())},
        "tickers_requested": tickers,
        "tickers_built": sorted(flows["ticker"].unique().tolist()),
        "failures": failures,
        "diagnostics": diagnostics,
        "latest": latest_rows,
    }
    (args.output / "rotation_exact_flow_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    md = [
        "# Rotation Exact Flow Research", "",
        "Research-only reconstruction from official fund-provider daily NAV and shares-outstanding history.", "",
        f"Requested window: {start.date()} to {end.date()}", "",
        "## Coverage", "",
        "| Ticker | Provider | Rows | First | Last | Split events | TNA identity median error |",
        "|---|---:|---:|---|---|---:|---:|",
    ]
    for d in diagnostics:
        err = d["median_tna_identity_rel_error"]
        err_text = "n/a" if err is None else f"{err:.6%}"
        md.append(f"| {d['ticker']} | {d['provider']} | {d['rows']} | {d['first_date']} | {d['last_date']} | {d['split_events']} | {err_text} |")
    if failures:
        md += ["", "## Failures", ""] + [f"- {x['ticker']}: {x['error']}" for x in failures]
    md += ["", "## Guardrail", "", "Trading volume or dollar-volume is not used as fund flow anywhere in this output."]
    (args.output / "README.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    if failures:
        print(f"completed with failures: {failures}")
    print(f"wrote {len(flows)} rows for {flows['ticker'].nunique()} tickers to {args.output}")


if __name__ == "__main__":
    main()
