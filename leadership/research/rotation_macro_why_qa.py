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
CNN_CURRENT = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
CNN_HISTORY = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata/2024-01-01"
UA = "Mozilla/5.0 V38-Rotation-Research/1.0"
COMPONENTS = [
    "fear_and_greed",
    "market_momentum_sp500",
    "stock_price_strength",
    "stock_price_breadth",
    "put_call_options",
    "market_volatility_vix",
    "safe_haven_demand",
    "junk_bond_demand",
]


def fetch_json(session: requests.Session, url: str) -> tuple[Any | None, str | None]:
    try:
        r = session.get(url, headers={"User-Agent": UA, "Accept": "application/json,*/*"}, timeout=30)
        r.raise_for_status()
        return r.json(), None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def fetch_fred(session: requests.Session, series: str) -> tuple[pd.DataFrame | None, str | None]:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
    try:
        r = session.get(url, headers={"User-Agent": UA}, timeout=30)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text))
        if df.empty or series not in df.columns:
            raise RuntimeError(f"{series}: series column missing")
        date_col = next((c for c in df.columns if c.lower() in {"date", "observation_date"}), df.columns[0])
        df = df.rename(columns={date_col: "date"})[["date", series]].copy()
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df[series] = pd.to_numeric(df[series], errors="coerce")
        df = df.dropna(subset=["date"]).sort_values("date")
        return df, None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def point_xy(row: Any) -> tuple[Any, Any, Any]:
    if not isinstance(row, dict):
        return None, None, None
    ts = row.get("x", row.get("timestamp", row.get("date")))
    val = row.get("y", row.get("score", row.get("value")))
    rating = row.get("rating")
    return ts, val, rating


def normalize_cnn_history(payload: Any) -> pd.DataFrame:
    rows = []
    if not isinstance(payload, dict):
        return pd.DataFrame()
    for component in COMPONENTS:
        block = payload.get(component)
        if not isinstance(block, dict):
            continue
        for pt in block.get("data") or []:
            ts, val, rating = point_xy(pt)
            rows.append({"component": component, "timestamp_raw": ts, "score": val, "rating": rating})
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["score"] = pd.to_numeric(out["score"], errors="coerce")
    numts = pd.to_numeric(out["timestamp_raw"], errors="coerce")
    # CNN uses epoch milliseconds in the graph series.
    out["date"] = pd.to_datetime(numts, unit="ms", errors="coerce", utc=True).dt.tz_convert(None).dt.normalize()
    text_mask = out["date"].isna() & out["timestamp_raw"].notna()
    if text_mask.any():
        out.loc[text_mask, "date"] = pd.to_datetime(out.loc[text_mask, "timestamp_raw"], errors="coerce").dt.normalize()
    return out.dropna(subset=["date", "score"]).sort_values(["date", "component"]).reset_index(drop=True)


def current_cnn_table(payload: Any) -> pd.DataFrame:
    rows = []
    if not isinstance(payload, dict):
        return pd.DataFrame()
    for component in COMPONENTS:
        block = payload.get(component)
        if not isinstance(block, dict):
            continue
        rows.append({
            "component": component,
            "score": block.get("score"),
            "rating": block.get("rating"),
            "timestamp": block.get("timestamp"),
        })
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description="QA stable Macro WHY data inputs for Rotation Intelligence")
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    session = requests.Session()

    fred_frames = []
    fred_diag = []
    for series in FRED_SERIES:
        df, err = fetch_fred(session, series)
        if df is not None:
            fred_frames.append(df)
            valid = df.dropna(subset=[series])
            fred_diag.append({
                "series": series,
                "error": None,
                "valid_rows": int(len(valid)),
                "first_date": None if valid.empty else str(valid["date"].min().date()),
                "last_date": None if valid.empty else str(valid["date"].max().date()),
                "last_value": None if valid.empty else float(valid[series].iloc[-1]),
            })
        else:
            fred_diag.append({"series": series, "error": err, "valid_rows": 0, "first_date": None, "last_date": None, "last_value": None})
    fred = None
    for df in fred_frames:
        fred = df if fred is None else fred.merge(df, on="date", how="outer")
    if fred is not None:
        fred.sort_values("date").to_csv(args.output / "macro_fred_series.csv", index=False, date_format="%Y-%m-%d")
    fred_ok = all(x["error"] is None and x["valid_rows"] > 100 for x in fred_diag)

    price_error = None
    price_diag = None
    price_summary = []
    try:
        ohlcv, price_diag = pl.download_ohlcv(["^VIX", "DX-Y.NYB"], "2022-01-01", "2026-09-02", 10)
        close = ohlcv["close"]
        for ticker in ["^VIX", "DX-Y.NYB"]:
            x = close[ticker].dropna() if ticker in close.columns else pd.Series(dtype=float)
            price_summary.append({
                "ticker": ticker,
                "valid_rows": int(len(x)),
                "first_date": None if x.empty else str(x.index.min().date()),
                "last_date": None if x.empty else str(x.index.max().date()),
                "last_value": None if x.empty else float(x.iloc[-1]),
            })
    except Exception as exc:
        price_error = f"{type(exc).__name__}: {exc}"
    vix_ok = any(x["ticker"] == "^VIX" and x["valid_rows"] > 100 for x in price_summary)
    dxy_ok = any(x["ticker"] == "DX-Y.NYB" and x["valid_rows"] > 100 for x in price_summary)

    cnn_current, current_error = fetch_json(session, CNN_CURRENT)
    cnn_history, history_error = fetch_json(session, CNN_HISTORY)
    current_table = current_cnn_table(cnn_current)
    hist_table = normalize_cnn_history(cnn_history)
    if not current_table.empty:
        current_table.to_csv(args.output / "cnn_fear_greed_current_components.csv", index=False)
    if not hist_table.empty:
        hist_table.to_csv(args.output / "cnn_fear_greed_component_history_2024plus.csv", index=False, date_format="%Y-%m-%d")
    current_keys = set(cnn_current.keys()) if isinstance(cnn_current, dict) else set()
    history_keys = set(cnn_history.keys()) if isinstance(cnn_history, dict) else set()
    current_ok = set(COMPONENTS).issubset(current_keys) and len(current_table) == len(COMPONENTS)
    history_ok = set(COMPONENTS).issubset(history_keys) and hist_table["component"].nunique() == len(COMPONENTS) and len(hist_table) > 1000

    report = {
        "schema": 2,
        "research_only": True,
        "fred": {
            "quality": "EXACT_OFFICIAL_FRED" if fred_ok else "PARTIAL_OR_DATA_REQUIRED",
            "series": fred_diag,
        },
        "market_prices": {
            "download_error": price_error,
            "download": price_diag,
            "summary": price_summary,
            "vix_quality": "MARKET_PRICE_SERIES" if vix_ok else "DATA_REQUIRED",
            "dxy_quality": "MARKET_PRICE_SERIES" if dxy_ok else "DATA_REQUIRED",
            "note": "FRB DTWEXBGS broad-dollar series is not labeled DXY and is kept separate.",
        },
        "fear_greed": {
            "current_endpoint": CNN_CURRENT,
            "history_endpoint": CNN_HISTORY,
            "current_error": current_error,
            "history_error": history_error,
            "current_quality": "EXACT_CNN_COMPONENTS" if current_ok else "DATA_REQUIRED",
            "history_quality": "EXACT_CNN_COMPONENT_HISTORY_2024PLUS" if history_ok else "DATA_REQUIRED",
            "current_components": int(current_table["component"].nunique()) if not current_table.empty else 0,
            "history_components": int(hist_table["component"].nunique()) if not hist_table.empty else 0,
            "history_rows": int(len(hist_table)),
            "history_first": None if hist_table.empty else str(hist_table["date"].min().date()),
            "history_last": None if hist_table.empty else str(hist_table["date"].max().date()),
        },
        "macro_why_contract": {
            "us10y": {"source": "FRED", "series": "DGS10", "role": "WHY"},
            "real10y": {"source": "FRED", "series": "DFII10", "role": "WHY"},
            "broad_usd": {"source": "FRED", "series": "DTWEXBGS", "role": "WHY", "not_dxy": True},
            "ig_oas": {"source": "FRED", "series": "BAMLC0A0CM", "role": "WHY"},
            "hy_oas": {"source": "FRED", "series": "BAMLH0A0HYM2", "role": "WHY", "history_limit_note": "FRED/ICE series has a three-year observation limit from Apr 2026."},
            "vix": {"source": "market price", "ticker": "^VIX", "role": "WHY/context"},
            "dxy": {"source": "market price", "ticker": "DX-Y.NYB", "role": "WHY", "quality": "DATA_REQUIRED" if not dxy_ok else "MARKET_PRICE_SERIES"},
            "fear_greed": {"source": "CNN", "role": "WHY", "components": COMPONENTS},
        },
        "guardrail": "Macro and Fear/Greed explain consistency and cross-market splits only. They do not alter V38 Market Mode, stock Gate, exit, or TQQQ logic.",
    }
    (args.output / "macro_why_qa_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    lines = [
        "# Rotation Macro WHY Data QA",
        "",
        f"- FRED core: {report['fred']['quality']}",
        f"- VIX: {report['market_prices']['vix_quality']}",
        f"- DXY ticker: {report['market_prices']['dxy_quality']}",
        f"- CNN current 7 components + headline: {report['fear_greed']['current_quality']}",
        f"- CNN component history: {report['fear_greed']['history_quality']} ({report['fear_greed']['history_rows']} rows)",
        "",
        "Macro WHY remains explanatory context only; never a trading Gate.",
    ]
    (args.output / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("DONE MACRO WHY QA v2", flush=True)


if __name__ == "__main__":
    main()
