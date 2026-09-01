from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd
import yfinance as yf

import rotation_divergence_proxy_backtest as proxy
import validate_early_rotation as er
import validate_pioneer_leader as pl


def load_config(path: Path) -> list[dict[str, str]]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    themes = obj.get("themes") if isinstance(obj, dict) else None
    if not isinstance(themes, list) or len(themes) != 56:
        raise RuntimeError("theme56 config must contain exactly 56 themes")
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in themes:
        if not isinstance(raw, dict):
            raise RuntimeError("theme56 entry must be an object")
        ticker = str(raw.get("ticker") or "").upper().strip()
        label = str(raw.get("label") or ticker).strip()
        if not ticker or ticker in seen:
            raise RuntimeError(f"duplicate or missing ticker: {ticker!r}")
        seen.add(ticker)
        out.append({"ticker": ticker, "label": label})
    return out


def latest_num(s: pd.Series) -> float | None:
    x = pd.to_numeric(s, errors="coerce").dropna()
    return None if x.empty else float(x.iloc[-1])


def pct_rank_frame(frame: pd.DataFrame, min_count: int) -> pd.DataFrame:
    return proxy.cross_section_rank(frame, min_count=min_count)


def retry_close(ticker: str, start: str, end: str) -> pd.Series:
    ysym = er.yahoo_symbol(ticker)
    try:
        raw = yf.download(ysym, start=start, end=end, auto_adjust=True, actions=False, progress=False, threads=False, timeout=30)
    except Exception:
        return pd.Series(dtype=float)
    if raw is None or raw.empty:
        return pd.Series(dtype=float)
    if isinstance(raw.columns, pd.MultiIndex):
        if ("Close", ysym) in raw.columns:
            s = raw[("Close", ysym)]
        elif ysym in raw.columns.get_level_values(0) and "Close" in raw[ysym].columns:
            s = raw[ysym]["Close"]
        else:
            return pd.Series(dtype=float)
    elif "Close" in raw.columns:
        s = raw["Close"]
    else:
        return pd.Series(dtype=float)
    s = pd.to_numeric(s, errors="coerce")
    s.index = pd.to_datetime(s.index).tz_localize(None)
    return s


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the 56-theme ETF price/RS layer for Rotation research")
    ap.add_argument("--config", type=Path, default=Path("leadership/research/rotation_theme56_config.json"))
    ap.add_argument("--output", type=Path, default=Path("leadership/research/rotation_theme56_live"))
    ap.add_argument("--download-start", default="2025-01-01")
    ap.add_argument("--download-end", default="2026-09-02")
    args = ap.parse_args()

    themes = load_config(args.config)
    tickers = [x["ticker"] for x in themes]
    labels = {x["ticker"]: x["label"] for x in themes}
    requested = tickers + ["SPY"]

    ohlcv, diag = pl.download_ohlcv(requested, args.download_start, args.download_end, 20)
    close = ohlcv["close"].copy()
    if "SPY" not in close.columns:
        raise RuntimeError("SPY price series missing")

    initial_counts = {t: int(close[t].notna().sum()) if t in close.columns else 0 for t in tickers}
    retry_tickers = [t for t in tickers if initial_counts[t] < 190]
    retry_counts: dict[str, int] = {}
    for ticker in retry_tickers:
        s = retry_close(ticker, args.download_start, args.download_end)
        retry_counts[ticker] = int(s.notna().sum())
        if len(s.dropna()) > initial_counts[ticker]:
            close[ticker] = s.reindex(close.index)

    counts = {t: int(close[t].notna().sum()) if t in close.columns else 0 for t in tickers}
    usable = [t for t in tickers if counts[t] >= 190]
    spy = close["SPY"]
    etf = close.reindex(columns=usable)
    rel63 = etf.pct_change(63, fill_method=None).sub(spy.pct_change(63, fill_method=None), axis=0)
    rel189 = etf.pct_change(189, fill_method=None).sub(spy.pct_change(189, fill_method=None), axis=0)
    min_count = max(10, len(usable) // 2)
    rank63 = pct_rank_frame(rel63, min_count=min_count)
    rank189 = pct_rank_frame(rel189, min_count=min_count)
    price_score = (rank63 + rank189) / 2.0

    rows: list[dict[str, Any]] = []
    for ticker in tickers:
        if ticker not in usable:
            rows.append({
                "ticker": ticker,
                "label": labels[ticker],
                "quality": "DATA_REQUIRED",
                "valid_price_rows": counts[ticker],
                "close": None,
                "ret_1d_pct": None,
                "ret_5d_pct": None,
                "ret_20d_pct": None,
                "rs63_vs_spy": None,
                "rs189_vs_spy": None,
                "rs63_rank": None,
                "rs189_rank": None,
                "price_score": None,
            })
            continue
        s = close[ticker]
        sd = s.dropna()
        last = latest_num(s)
        rows.append({
            "ticker": ticker,
            "label": labels[ticker],
            "quality": "MARKET_PRICE_SERIES",
            "valid_price_rows": counts[ticker],
            "close": last,
            "ret_1d_pct": None if len(sd) < 2 else float(100.0 * (sd.iloc[-1] / sd.iloc[-2] - 1.0)),
            "ret_5d_pct": None if len(sd) < 6 else float(100.0 * (sd.iloc[-1] / sd.iloc[-6] - 1.0)),
            "ret_20d_pct": None if len(sd) < 21 else float(100.0 * (sd.iloc[-1] / sd.iloc[-21] - 1.0)),
            "rs63_vs_spy": latest_num(rel63[ticker]),
            "rs189_vs_spy": latest_num(rel189[ticker]),
            "rs63_rank": latest_num(rank63[ticker]),
            "rs189_rank": latest_num(rank189[ticker]),
            "price_score": latest_num(price_score[ticker]),
        })

    out = pd.DataFrame(rows)
    args.output.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.output / "theme56_price.csv", index=False)
    latest_dates = [close[t].dropna().index.max() for t in usable if not close[t].dropna().empty]
    asof = str(max(latest_dates).date()) if latest_dates else None
    report = {
        "schema": 2,
        "research_only": True,
        "asof": asof,
        "universe_count": len(tickers),
        "price_usable_count": len(usable),
        "data_required_count": len(tickers) - len(usable),
        "price_usable_tickers": usable,
        "data_required_tickers": [t for t in tickers if t not in usable],
        "price_rows_by_ticker": counts,
        "individual_retry_tickers": retry_tickers,
        "individual_retry_rows": retry_counts,
        "price_cross_section": "56-theme universe only; not comparable to the old 15-ETF score scale",
        "download_diagnostics": diag,
        "guardrail": "No Rotation V2 state is assigned here. The old 15-ETF state thresholds are not reused before 56-theme validation.",
        "rows": rows,
    }
    (args.output / "theme56_price.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("asof", "universe_count", "price_usable_count", "data_required_count", "data_required_tickers", "individual_retry_rows")}, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
