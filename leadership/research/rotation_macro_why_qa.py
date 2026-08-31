from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
from typing import Any

import pandas as pd
import requests

import validate_pioneer_leader as pl

FRED_SERIES = ["DGS10", "DFII10", "DTWEXBGS", "BAMLC0A0CM", "BAMLH0A0HYM2"]
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=" + ",".join(FRED_SERIES)
CNN_CURRENT = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
CNN_HISTORY = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata/2024-01-01"
UA = "Mozilla/5.0 V38-Rotation-Research/1.0"


def safe_json_shape(value: Any, depth: int = 0) -> Any:
    if depth >= 3:
        if isinstance(value, list):
            return {"type": "list", "len": len(value)}
        return type(value).__name__
    if isinstance(value, dict):
        return {str(k): safe_json_shape(v, depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        return {"type": "list", "len": len(value), "sample_shape": safe_json_shape(value[0], depth + 1) if value else None}
    return type(value).__name__


def fetch_json(session: requests.Session, url: str) -> tuple[Any | None, str | None]:
    try:
        r = session.get(url, headers={"User-Agent": UA, "Accept": "application/json,*/*"}, timeout=30)
        r.raise_for_status()
        return r.json(), None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def main() -> None:
    ap = argparse.ArgumentParser(description="QA stable Macro WHY data inputs for Rotation Intelligence")
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    session = requests.Session()

    fred_error = None
    fred_diag = []
    try:
        r = session.get(FRED_URL, headers={"User-Agent": UA}, timeout=45)
        r.raise_for_status()
        fred = pd.read_csv(io.StringIO(r.text))
        fred["DATE"] = pd.to_datetime(fred["DATE"], errors="coerce")
        fred.to_csv(args.output / "macro_fred_series.csv", index=False)
        for s in FRED_SERIES:
            x = pd.to_numeric(fred[s], errors="coerce") if s in fred.columns else pd.Series(dtype=float)
            valid = fred.loc[x.notna(), ["DATE", s]].copy() if s in fred.columns else pd.DataFrame()
            fred_diag.append({
                "series": s,
                "present": s in fred.columns,
                "valid_rows": int(x.notna().sum()),
                "first_date": None if valid.empty else str(valid["DATE"].min().date()),
                "last_date": None if valid.empty else str(valid["DATE"].max().date()),
                "last_value": None if valid.empty else float(pd.to_numeric(valid[s], errors="coerce").iloc[-1]),
            })
    except Exception as exc:
        fred_error = f"{type(exc).__name__}: {exc}"

    price_error = None
    price_diag = None
    price_summary = []
    try:
        ohlcv, price_diag = pl.download_ohlcv(["^VIX", "DX-Y.NYB"], "2022-01-01", "2026-09-02", 10)
        close = ohlcv["close"]
        for t in ["^VIX", "DX-Y.NYB"]:
            x = close[t].dropna() if t in close.columns else pd.Series(dtype=float)
            price_summary.append({
                "ticker": t,
                "valid_rows": int(len(x)),
                "first_date": None if x.empty else str(x.index.min().date()),
                "last_date": None if x.empty else str(x.index.max().date()),
                "last_value": None if x.empty else float(x.iloc[-1]),
            })
    except Exception as exc:
        price_error = f"{type(exc).__name__}: {exc}"

    cnn_current, cnn_current_error = fetch_json(session, CNN_CURRENT)
    cnn_history, cnn_history_error = fetch_json(session, CNN_HISTORY)
    cnn_shape = {
        "current": None if cnn_current is None else safe_json_shape(cnn_current),
        "history_from_2024": None if cnn_history is None else safe_json_shape(cnn_history),
    }
    (args.output / "cnn_fear_greed_shape.json").write_text(json.dumps(cnn_shape, ensure_ascii=False, indent=2), encoding="utf-8")

    expected_components = {
        "fear_and_greed",
        "market_momentum_sp500",
        "stock_price_strength",
        "stock_price_breadth",
        "put_call_options",
        "market_volatility_vix",
        "safe_haven_demand",
        "junk_bond_demand",
    }
    current_keys = set(cnn_current.keys()) if isinstance(cnn_current, dict) else set()
    history_keys = set(cnn_history.keys()) if isinstance(cnn_history, dict) else set()
    cnn_components_current = sorted(expected_components & current_keys)
    cnn_components_history = sorted(expected_components & history_keys)

    report = {
        "schema": 1,
        "research_only": True,
        "fred": {
            "url": FRED_URL,
            "error": fred_error,
            "series": fred_diag,
            "quality": "EXACT_OFFICIAL_FRED" if fred_error is None and len(fred_diag) == len(FRED_SERIES) else "DATA_REQUIRED",
        },
        "market_prices": {
            "series": {"^VIX": "VIX spot index", "DX-Y.NYB": "US Dollar Index market quote (DXY-like ticker, kept separate from FRB broad dollar)"},
            "error": price_error,
            "download": price_diag,
            "summary": price_summary,
            "quality": "MARKET_PRICE_SERIES" if price_error is None else "DATA_REQUIRED",
        },
        "fear_greed": {
            "definition_source": "CNN Fear & Greed public page defines seven equally weighted indicators; this QA only tests data endpoint availability.",
            "current_endpoint": CNN_CURRENT,
            "history_endpoint_test": CNN_HISTORY,
            "current_error": cnn_current_error,
            "history_error": cnn_history_error,
            "current_expected_component_keys_found": cnn_components_current,
            "history_expected_component_keys_found": cnn_components_history,
            "current_has_all_expected": expected_components.issubset(current_keys),
            "history_has_all_expected": expected_components.issubset(history_keys),
            "quality": "EXACT_ENDPOINT_AVAILABLE" if expected_components.issubset(current_keys) else "DATA_REQUIRED",
            "history_quality": "EXACT_HISTORY_ENDPOINT_AVAILABLE" if expected_components.issubset(history_keys) else "DATA_REQUIRED",
        },
        "macro_why_contract": {
            "us10y": "DGS10",
            "real10y": "DFII10",
            "broad_usd": "DTWEXBGS",
            "ig_oas": "BAMLC0A0CM",
            "hy_oas": "BAMLH0A0HYM2",
            "vix": "^VIX",
            "dxy_market_quote": "DX-Y.NYB",
            "fear_greed_headline_and_components": "CNN only if endpoint QA passes; otherwise DATA REQUIRED",
        },
        "guardrail": "Macro explains consistency/WHY only. It is not a V38 normal-stock hard gate.",
    }
    (args.output / "macro_why_qa_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    lines = [
        "# Rotation Macro WHY Data QA",
        "",
        f"- FRED core: {report['fred']['quality']}",
        f"- VIX/DXY market price series: {report['market_prices']['quality']}",
        f"- CNN current components: {report['fear_greed']['quality']}",
        f"- CNN component history: {report['fear_greed']['history_quality']}",
        "",
        "Macro WHY remains explanatory context only; never a trading Gate.",
    ]
    (args.output / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("DONE MACRO WHY QA", flush=True)


if __name__ == "__main__":
    main()
