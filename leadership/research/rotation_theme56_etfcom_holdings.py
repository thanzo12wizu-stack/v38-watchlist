from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any

import pandas as pd
import requests

import rotation_theme56_holdings_expansion as hx

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122 Safari/537.36"
API_URL = "https://api-prod.etf.com/private/fund/{ticker}/holdings?type=securities&formatValues=true"
HEADERS = {
    "User-Agent": UA,
    "Accept": "application/json,text/plain,*/*",
    "Origin": "https://www.etf.com",
    "Referer": "https://www.etf.com/",
    "x-limit": "10000",
}


def load_json(path: Path) -> dict[str, Any]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return obj


def _find_record_list(obj: Any) -> list[dict[str, Any]]:
    """Find the securities list without assuming one ETF.com response wrapper."""
    candidates: list[list[dict[str, Any]]] = []

    def walk(x: Any, depth: int = 0) -> None:
        if depth > 6:
            return
        if isinstance(x, list):
            rows = [r for r in x if isinstance(r, dict)]
            if rows:
                symbolish = sum(
                    1 for r in rows
                    if any(k in r for k in ("symbol", "ticker", "securitySymbol", "holdingSymbol"))
                )
                if symbolish:
                    candidates.append(rows)
            for item in x[:5]:
                walk(item, depth + 1)
        elif isinstance(x, dict):
            for key in ("data", "results", "holdings", "securities", "items", "rows"):
                if key in x:
                    walk(x[key], depth + 1)
            if not any(k in x for k in ("data", "results", "holdings", "securities", "items", "rows")):
                for value in list(x.values())[:12]:
                    if isinstance(value, (list, dict)):
                        walk(value, depth + 1)

    walk(obj)
    if not candidates:
        return []
    return max(candidates, key=len)


def _value(row: dict[str, Any], names: tuple[str, ...]) -> Any:
    lower = {str(k).lower(): v for k, v in row.items()}
    for name in names:
        if name.lower() in lower:
            return lower[name.lower()]
    return None


def _num(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "").replace("$", "").replace("%", "")
    if not text or text.lower() in {"nan", "none", "null", "--", "-"}:
        return None
    mult = 1.0
    if text[-1:].upper() in {"K", "M", "B", "T"}:
        mult = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}[text[-1].upper()]
        text = text[:-1]
    try:
        return float(text) * mult
    except Exception:
        return None


def fetch_holdings(session: requests.Session, ticker: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    url = API_URL.format(ticker=ticker)
    last_exc: Exception | None = None
    for attempt in range(4):
        try:
            r = session.get(url, headers=HEADERS, timeout=35)
            r.raise_for_status()
            obj = r.json()
            records = _find_record_list(obj)
            if not records:
                raise RuntimeError("no securities rows in ETF.com response")
            rows: list[dict[str, Any]] = []
            for rec in records:
                raw_symbol = _value(rec, ("symbol", "ticker", "securitySymbol", "holdingSymbol"))
                symbol = hx.clean_symbol(raw_symbol)
                if not symbol:
                    continue
                name = _value(rec, ("name", "securityName", "holdingName", "description"))
                weight = _num(_value(rec, ("weight", "weighting", "portfolioWeight", "percentage")))
                as_of = _value(rec, ("as_of", "asOf", "asof", "date"))
                market_value = _num(_value(rec, ("market_value", "marketValue", "marketvalue")))
                shares = _num(_value(rec, ("shares", "share", "quantity")))
                rows.append({
                    "sector_etf": ticker,
                    "provider_symbol": str(raw_symbol or "").strip(),
                    "symbol": symbol,
                    "weight_pct": weight,
                    "name": "" if name is None else str(name).strip(),
                    "as_of": None if as_of is None else str(as_of),
                    "shares": shares,
                    "market_value": market_value,
                    "source_url": url,
                    "provider": "ETFCOM",
                    "quality": "ETFCOM_VALIDATED_CURRENT_MEMBERSHIP",
                })
            out = pd.DataFrame(rows)
            if out.empty:
                raise RuntimeError("ETF.com rows contained no usable symbols")
            out = out.drop_duplicates("symbol", keep="first").reset_index(drop=True)
            if len(out) < 5:
                raise RuntimeError(f"unexpectedly short ETF.com holdings: {len(out)}")
            asofs = out["as_of"].dropna().astype(str) if "as_of" in out else pd.Series(dtype=str)
            return out, {
                "ticker": ticker,
                "rows": int(len(out)),
                "as_of": None if asofs.empty else asofs.mode().iloc[0],
                "source_url": url,
                "status": "FETCHED",
            }
        except Exception as exc:
            last_exc = exc
            time.sleep(1.25 * (attempt + 1))
    raise RuntimeError(f"ETF.com holdings failed for {ticker}: {last_exc}")


def read_reference(paths: list[Path], universe: set[str]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path in paths:
        if not path.exists():
            continue
        df = pd.read_csv(path, usecols=lambda c: c in {"sector_etf", "symbol"})
        if not {"sector_etf", "symbol"}.issubset(df.columns):
            continue
        df["sector_etf"] = df["sector_etf"].astype(str).str.upper().str.strip()
        df["symbol"] = df["symbol"].map(hx.clean_symbol)
        df = df[df["sector_etf"].isin(universe) & (df["symbol"] != "")]
        frames.append(df[["sector_etf", "symbol"]])
    if not frames:
        raise RuntimeError("no exact-current reference holdings available")
    return pd.concat(frames, ignore_index=True).drop_duplicates(["sector_etf", "symbol"])


def compare_membership(api: pd.DataFrame, reference: pd.DataFrame, ticker: str) -> dict[str, Any]:
    a = set(api.loc[api["sector_etf"] == ticker, "symbol"].dropna().astype(str))
    b = set(reference.loc[reference["sector_etf"] == ticker, "symbol"].dropna().astype(str))
    if not b:
        return {"ticker": ticker, "reference_rows": 0, "api_rows": len(a), "status": "NO_REFERENCE"}
    inter = a & b
    union = a | b
    coverage = len(inter) / len(b) if b else 0.0
    precision = len(inter) / len(a) if a else 0.0
    jaccard = len(inter) / len(union) if union else 0.0
    # Current memberships can differ by a few creations/rebalances or by cash rows. Require
    # substantial set agreement, but do not require impossible byte-identical provider files.
    passed = len(b) >= 10 and coverage >= 0.80 and precision >= 0.75 and jaccard >= 0.68
    return {
        "ticker": ticker,
        "reference_rows": len(b),
        "api_rows": len(a),
        "intersection": len(inter),
        "reference_coverage": coverage,
        "api_precision": precision,
        "jaccard": jaccard,
        "status": "PASS" if passed else "FAIL",
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Validate ETF.com current holdings as Theme56 fallback")
    ap.add_argument("--config", type=Path, default=Path("leadership/research/rotation_theme56_config.json"))
    ap.add_argument("--issuer-holdings", type=Path, default=Path("leadership/research/rotation_theme56_provider_qa/theme56_exact_current_holdings.csv"))
    ap.add_argument("--expansion-holdings", type=Path, default=Path("leadership/research/rotation_theme56_holdings_expansion/exact_current_holdings_expansion.csv"))
    ap.add_argument("--firsttrust-holdings", type=Path, default=Path("leadership/research/rotation_theme56_firsttrust/firsttrust_exact_current_holdings.csv"))
    ap.add_argument("--output", type=Path, default=Path("leadership/research/rotation_theme56_etfcom_holdings"))
    args = ap.parse_args()

    cfg = load_json(args.config)
    tickers = [str(x.get("ticker") or "").upper().strip() for x in (cfg.get("themes") or [])]
    if len(tickers) != 56 or len(set(tickers)) != 56:
        raise RuntimeError("Theme56 config mismatch")
    universe = set(tickers)

    reference = read_reference([args.issuer_holdings, args.expansion_holdings, args.firsttrust_holdings], universe)
    session = requests.Session()
    frames: list[pd.DataFrame] = []
    fetch_diag: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for idx, ticker in enumerate(tickers, 1):
        try:
            df, diag = fetch_holdings(session, ticker)
            frames.append(df)
            fetch_diag.append(diag)
            print(f"HOLD {idx}/{len(tickers)} {ticker} rows={len(df)}", flush=True)
        except Exception as exc:
            failures.append({"ticker": ticker, "error": f"{type(exc).__name__}: {exc}"})
            print(f"HOLD {idx}/{len(tickers)} {ticker} FAIL {exc}", flush=True)

    if not frames:
        raise RuntimeError("ETF.com returned no Theme56 holdings")
    all_holdings = pd.concat(frames, ignore_index=True).drop_duplicates(["sector_etf", "symbol"], keep="first")
    reference_tickers = sorted(set(reference["sector_etf"]) & set(all_holdings["sector_etf"]))
    validations = [compare_membership(all_holdings, reference, t) for t in reference_tickers]
    vdf = pd.DataFrame(validations)
    comparable = vdf[vdf["reference_rows"] >= 10] if not vdf.empty else vdf
    pass_ratio = float((comparable["status"] == "PASS").mean()) if len(comparable) else 0.0
    median_coverage = float(pd.to_numeric(comparable["reference_coverage"], errors="coerce").median()) if len(comparable) else 0.0
    median_jaccard = float(pd.to_numeric(comparable["jaccard"], errors="coerce").median()) if len(comparable) else 0.0
    aggregate_pass = len(comparable) >= 20 and pass_ratio >= 0.85 and median_coverage >= 0.90 and median_jaccard >= 0.80

    fetched = set(all_holdings["sector_etf"])
    status = []
    for ticker in tickers:
        n = int((all_holdings["sector_etf"] == ticker).sum())
        status.append({
            "ticker": ticker,
            "rows": n,
            "status": "PASS" if aggregate_pass and n >= 5 else "DATA_REQUIRED",
        })

    args.output.mkdir(parents=True, exist_ok=True)
    all_holdings.to_csv(args.output / "theme56_etfcom_current_holdings.csv", index=False)
    vdf.to_csv(args.output / "etfcom_vs_exact_holdings_validation.csv", index=False)
    report = {
        "schema": 1,
        "research_only": True,
        "aggregate_validation_pass": aggregate_pass,
        "reference_ticker_count": int(len(comparable)),
        "reference_pass_ratio": pass_ratio,
        "median_reference_coverage": median_coverage,
        "median_jaccard": median_jaccard,
        "api_success_count": len(fetched),
        "api_success_tickers": sorted(fetched),
        "failures": failures,
        "validation": validations,
        "status": status,
        "quality_contract": "ETF.com current securities membership is accepted only as ETFCOM_VALIDATED_CURRENT_MEMBERSHIP after broad cross-source validation against exact current issuer/First Trust holdings. Issuer exact membership remains preferred.",
        "guardrails": [
            "No Top-10 page is accepted when the ETF.com full securities endpoint is unavailable.",
            "No inferred or price-based membership is created.",
            "DRAM may remain DATA_REQUIRED as the explicitly accepted short-history exception.",
        ],
    }
    (args.output / "etfcom_holdings_qa.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({
        "aggregate_validation_pass": aggregate_pass,
        "reference_ticker_count": len(comparable),
        "reference_pass_ratio": pass_ratio,
        "median_reference_coverage": median_coverage,
        "median_jaccard": median_jaccard,
        "api_success_count": len(fetched),
        "failures": len(failures),
    }, ensure_ascii=False, indent=2), flush=True)
    if not aggregate_pass:
        raise RuntimeError("ETF.com holdings fallback did not pass cross-source validation")


if __name__ == "__main__":
    main()
