#!/usr/bin/env python3
"""Generate the audited TQQQ CURRENT30 + Stage56 live state.

This module ports the selected research definitions without simplifying CURRENT30
to a constant 30% sleeve:
- Stage34 CURRENT30 hierarchy/risk locks (PCUR)
- Stage56 M30_TOUCH30_F80_D10 overlay
- Stage51 5-minute QQQ -> RTH 4H bars -> Pine/Wilder RSI14 TOUCH30

The legacy ``build_dashboard.py`` is imported read-only for the same MC57 and VIX
sigma primitives used by the research code. It is never modified here.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd
import yfinance as yf

import build_dashboard as bd

START = pd.Timestamp("2011-01-03")
CURRENT_PARAMS = {
    "base": 0.30,
    "fast_dd": -0.065,
    "fast_rec": 4,
    "rg_slow": 0.50,
    "rg_fast": 0.80,
    "gb": 0.90,
    "rg_mc_slow": 40,
    "cooldown": 20,
    "panic": 1.0,
    "latch_exp": 0.0,
    "latch_mc": 999,
    "latch_confirm": 3,
    "ext_exp": 0.0,
    "ext_mc": 35,
    "ext_max": 40,
}
STAGE56_LOOKBACK = 30
STAGE56_FLOOR = 0.80
STAGE56_MAX_DAYS = 10
CACHE_SCHEMA = "v38-tqqq-live-source-cache-1"
COLOR_TO_INT = {"Red": 0, "Yellow": 1, "Green": 2, "Blue": 3}
INT_TO_COLOR = {value: key for key, value in COLOR_TO_INT.items()}


def _plain(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    if isinstance(out.columns, pd.MultiIndex):
        if len(set(out.columns.get_level_values(0))) == 1:
            out.columns = out.columns.get_level_values(1)
        elif len(set(out.columns.get_level_values(1))) == 1:
            out.columns = out.columns.get_level_values(0)
    out.index = pd.to_datetime(out.index)
    if out.index.tz is not None:
        # Research inputs are interpreted in their local exchange wall clock.
        # Drop tz metadata without converting the clock to UTC.
        out.index = out.index.tz_localize(None)
    return out.sort_index()


def download_daily(ticker: str, start: str) -> pd.DataFrame:
    raw = yf.download(
        ticker, start=start, progress=False, auto_adjust=True,
        actions=False, threads=False,
    )
    frame = _plain(raw)
    required = ["Open", "High", "Low", "Close", "Volume"]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise RuntimeError(f"{ticker} missing columns: {missing}")
    return frame[required].dropna(subset=["Open", "Close"])


def _get_json(url: str) -> Any:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 V38-TQQQ-collector/1.0"})
    try:
        with urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code}") from None
    except URLError as exc:
        raise RuntimeError(f"network error: {type(exc.reason).__name__}") from None


def download_yahoo_chart(ticker: str, *, start: str | None = None,
                         interval: str = "1d", range_text: str | None = None) -> pd.DataFrame:
    """Crumb-free Yahoo chart fallback, independent from yfinance session state."""
    params: dict[str, Any] = {
        "interval": interval,
        "includePrePost": "false",
        "events": "div,splits",
    }
    if range_text:
        params["range"] = range_text
    else:
        begin = pd.Timestamp(start or "1990-01-01", tz="UTC")
        params["period1"] = int(begin.timestamp())
        params["period2"] = int((pd.Timestamp.now(tz="UTC") + pd.Timedelta(days=2)).timestamp())
    symbol = ticker.replace("^", "%5E").replace("=", "%3D")
    payload = _get_json(
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?{urlencode(params)}"
    )
    chart = payload.get("chart", {})
    if chart.get("error"):
        raise RuntimeError(f"Yahoo chart error: {chart['error']}")
    results = chart.get("result") or []
    if not results:
        raise RuntimeError("Yahoo chart returned no result")
    result = results[0]
    timestamps = result.get("timestamp") or []
    quotes = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    if not timestamps or not quotes:
        raise RuntimeError("Yahoo chart returned no bars")
    index = pd.to_datetime(timestamps, unit="s", utc=True)
    if interval == "1d":
        exchange_tz = str((result.get("meta") or {}).get("exchangeTimezoneName") or "America/New_York")
        index = index.tz_convert(exchange_tz).tz_localize(None).normalize()
    frame = pd.DataFrame(
        {
            "Open": quotes.get("open"), "High": quotes.get("high"),
            "Low": quotes.get("low"), "Close": quotes.get("close"),
            "Volume": quotes.get("volume"),
        },
        index=index,
    ).apply(pd.to_numeric, errors="coerce")
    if interval == "1d":
        adjusted_rows = ((result.get("indicators") or {}).get("adjclose") or [{}])[0]
        adjusted = pd.to_numeric(pd.Series(adjusted_rows.get("adjclose"), index=frame.index), errors="coerce")
        ratio = adjusted / frame["Close"].replace(0, np.nan)
        for column in ("Open", "High", "Low", "Close"):
            frame[column] = frame[column] * ratio
    return frame.dropna(subset=["Open", "Close"]).sort_index()


def download_fmp_frame(ticker: str, *, start: str | None = None,
                       intraday_5m: bool = False) -> pd.DataFrame:
    api_key = os.environ.get("FMP_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("FMP_API_KEY is not configured")
    if intraday_5m:
        endpoint = "https://financialmodelingprep.com/stable/historical-chart/5min"
        params = {"symbol": ticker, "apikey": api_key}
    else:
        endpoint = "https://financialmodelingprep.com/stable/historical-price-eod/dividend-adjusted"
        params = {"symbol": ticker, "from": start or "1990-01-01", "apikey": api_key}
    payload = _get_json(f"{endpoint}?{urlencode(params)}")
    rows = payload if isinstance(payload, list) else payload.get("historical", [])
    if not rows:
        message = payload.get("Error Message") if isinstance(payload, dict) else None
        raise RuntimeError(f"FMP returned no bars: {message or 'empty response'}")
    date_key = "date"
    frame = pd.DataFrame(rows)
    required = {"open", "high", "low", "close"}
    if date_key not in frame.columns or not required.issubset(frame.columns):
        raise RuntimeError(f"FMP response missing OHLC columns: {list(frame.columns)}")
    index = pd.DatetimeIndex(pd.to_datetime(frame[date_key]))
    if intraday_5m:
        if index.tz is None:
            index = index.tz_localize("America/New_York", ambiguous="infer", nonexistent="shift_forward")
        else:
            index = index.tz_convert("America/New_York")
    out = pd.DataFrame(
        {
            "Open": frame["open"].to_numpy(), "High": frame["high"].to_numpy(),
            "Low": frame["low"].to_numpy(), "Close": frame["close"].to_numpy(),
            "Volume": frame.get("volume", pd.Series(np.nan, index=frame.index)).to_numpy(),
        },
        index=index,
    ).apply(pd.to_numeric, errors="coerce")
    return out.dropna(subset=["Open", "Close"]).sort_index()


def download_daily_resilient(ticker: str, start: str) -> tuple[pd.DataFrame, str]:
    errors: list[str] = []
    for provider, callback in (
        ("YAHOO_CHART", lambda: download_yahoo_chart(ticker, start=start)),
        ("YAHOO_YFINANCE", lambda: download_daily(ticker, start)),
        ("FMP_DIVIDEND_ADJUSTED", lambda: download_fmp_frame(ticker, start=start)),
    ):
        try:
            frame = callback()
            if frame is not None and not frame.empty:
                return frame, provider
        except Exception as exc:
            errors.append(f"{provider}={type(exc).__name__}: {exc}")
    raise RuntimeError(f"{ticker} daily sources exhausted: {' | '.join(errors)}")


def _retry(label: str, callback, attempts: int = 3):
    """Retry a small, dedicated market-data request before bulk dashboard traffic."""
    errors: list[str] = []
    for attempt in range(1, attempts + 1):
        try:
            value = callback()
            if value is None or (hasattr(value, "empty") and value.empty):
                raise RuntimeError("empty response")
            return value
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
            if attempt < attempts:
                time.sleep(2 * attempt)
    raise RuntimeError(f"{label} failed after {attempts} attempts: {' | '.join(errors)}")


def _frame_payload(frame: pd.DataFrame) -> dict[str, Any]:
    clean = frame.copy()
    clean.columns = [str(column) for column in clean.columns]
    values = clean.astype(object).where(pd.notna(clean), None).values.tolist()
    return {
        "index": [pd.Timestamp(value).isoformat() for value in clean.index],
        "columns": list(clean.columns),
        "data": values,
    }


def _frame_from_payload(payload: dict[str, Any]) -> pd.DataFrame:
    frame = pd.DataFrame(payload.get("data", []), columns=payload.get("columns", []))
    raw_index = [str(value) for value in payload.get("index", [])]
    has_timezone = any(
        value.endswith("Z") or "+" in value[10:] or "-" in value[10:]
        for value in raw_index
    )
    frame.index = pd.to_datetime(raw_index, utc=True) if has_timezone else pd.to_datetime(raw_index)
    for column in frame.columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.sort_index()


def _series_payload(series: pd.Series) -> dict[str, Any]:
    clean = pd.to_numeric(series, errors="coerce")
    return {
        "index": [pd.Timestamp(value).isoformat() for value in clean.index],
        "data": [float(value) if np.isfinite(value) else None for value in clean.to_numpy(float)],
    }


def _series_from_payload(payload: dict[str, Any]) -> pd.Series:
    values = pd.to_numeric(pd.Series(payload.get("data", [])), errors="coerce").to_numpy(float)
    return pd.Series(values, index=pd.to_datetime(payload.get("index", [])), dtype=float).sort_index()


def apply_legacy_mc57_overlay(sources: dict[str, Any], state: dict[str, Any],
                              mri_log_path: Path | None = None) -> dict[str, Any]:
    """Overlay the legacy Dashboard MC57 onto the research history.

    The long independently reconstructed series remains only as warm-up history
    for the Stage34 state machine. Persisted command-center values are canonical
    wherever available, and the current state.json value is mandatory.
    """
    if not isinstance(sources, dict) or "mc57" not in sources:
        raise RuntimeError("MC57_SOURCE_CACHE_REQUIRED")
    state_date = str(state.get("date") or "").strip()
    try:
        state_value = float(state.get("mri"))
    except (TypeError, ValueError):
        state_value = float("nan")
    if not state_date or not np.isfinite(state_value):
        raise RuntimeError("LEGACY_DASHBOARD_MC57_REQUIRED")

    points: dict[pd.Timestamp, float] = {}
    if mri_log_path is not None and Path(mri_log_path).is_file():
        try:
            log = pd.read_csv(mri_log_path)
            for _, row in log.iterrows():
                try:
                    date = pd.Timestamp(row.get("date")).normalize()
                    value = float(row.get("mri"))
                except (TypeError, ValueError):
                    continue
                if pd.notna(date) and np.isfinite(value):
                    points[date] = value
        except Exception:
            pass
    current_date = pd.Timestamp(state_date).normalize()
    points[current_date] = state_value

    merged = pd.to_numeric(sources["mc57"], errors="coerce").copy()
    merged.index = pd.to_datetime(merged.index).tz_localize(None).normalize()
    for date, value in points.items():
        merged.loc[date] = value
    merged = merged[~merged.index.duplicated(keep="last")].sort_index()

    out = dict(sources)
    out["mc57"] = merged
    providers = dict(out.get("providers") or {})
    providers["mc57_canonical"] = {
        "source": "command-center.html via state.json + daily_log.csv",
        "state_date": state_date,
        "state_value": state_value,
        "persisted_points": len(points),
        "policy": "LEGACY_DASHBOARD_CANONICAL_OVERLAY",
    }
    out["providers"] = providers
    return out


def compute_mc57(include_meta: bool = False):
    """Same MC57 construction called by the Stage56 research dependency."""
    # Use the crumb-free chart endpoint directly. yfinance's shared crumb/session
    # can be poisoned by an HTTP 429 and then stall all 57 threaded requests.
    macro: dict[str, pd.DataFrame] = {}
    source_by_ticker: dict[str, str] = {}
    def fetch_one(ticker: str) -> tuple[str, pd.DataFrame | None, str | None]:
        for provider, callback in (
            ("YAHOO_CHART", lambda ticker=ticker: download_yahoo_chart(
                ticker, start=bd.MC_LONG_HISTORY_START
            )),
            ("FMP_DIVIDEND_ADJUSTED", lambda ticker=ticker: download_fmp_frame(
                ticker, start=bd.MC_LONG_HISTORY_START
            )),
        ):
            try:
                frame = callback()
                if len(frame) >= 30:
                    return ticker, frame, provider
            except Exception:
                continue
        return ticker, None, None

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(fetch_one, ticker) for ticker in bd.MC_MARKET_TICKERS]
        for future in as_completed(futures):
            ticker, frame, provider = future.result()
            if frame is not None and provider is not None:
                macro[ticker] = frame
                source_by_ticker[ticker] = provider
    if len(macro) < 50:
        missing = [ticker for ticker in bd.MC_MARKET_TICKERS if ticker not in macro]
        raise RuntimeError(
            f"MC57 source coverage too low: {len(macro)}/{len(bd.MC_MARKET_TICKERS)} "
            f"missing={missing}"
        )
    score, _, _, _, values = bd.mri_frame(macro, W=None)
    score = pd.to_numeric(score, errors="coerce")
    score.index = pd.to_datetime(score.index).tz_localize(None)
    coverage = pd.to_numeric(values["mc_coverage"], errors="coerce")
    coverage.index = pd.to_datetime(coverage.index).tz_localize(None)
    result = (score.sort_index(), coverage.sort_index())
    if include_meta:
        meta = {
            "coverage_tickers": len(macro),
            "required_tickers": len(bd.MC_MARKET_TICKERS),
            "source_by_ticker": source_by_ticker,
        }
        return result[0], result[1], meta
    return result


def psar(high: np.ndarray, low: np.ndarray, step: float = 0.02, maximum: float = 0.08) -> np.ndarray:
    high = np.asarray(high, float)
    low = np.asarray(low, float)
    out = np.zeros(len(high), float)
    bull = True
    acceleration = step
    extreme = low[0]
    out[0] = low[0]
    for i in range(1, len(high)):
        out[i] = out[i - 1] + acceleration * (extreme - out[i - 1])
        if bull:
            if low[i] < out[i]:
                bull = False
                out[i] = extreme
                extreme = low[i]
                acceleration = step
            elif high[i] > extreme:
                extreme = high[i]
                acceleration = min(acceleration + step, maximum)
        else:
            if high[i] > out[i]:
                bull = True
                out[i] = extreme
                extreme = high[i]
                acceleration = step
            elif low[i] < extreme:
                extreme = low[i]
                acceleration = min(acceleration + step, maximum)
    return out


def daily_rsi(close: np.ndarray, n: int = 14) -> np.ndarray:
    series = pd.Series(close, dtype=float)
    delta = series.diff()
    up = delta.clip(lower=0)
    down = (-delta).clip(lower=0)
    avg_up = up.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    avg_down = down.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    ratio = avg_up / avg_down.replace(0, np.nan)
    result = 100 - 100 / (1 + ratio)
    return result.where(avg_down.ne(0), 100.0).to_numpy()


def nqsar_colors(nq: pd.DataFrame) -> pd.Series:
    close = nq["Close"].astype(float).to_numpy()
    high = nq["High"].astype(float).to_numpy()
    low = nq["Low"].astype(float).to_numpy()
    sar = psar(high, low)
    ema21 = pd.Series(close, index=nq.index).ewm(span=21, adjust=False).mean().to_numpy()
    rsi14 = daily_rsi(close)
    above = close > sar
    state = "Green" if above[0] else "Yellow"
    up_age = down_age = 99
    prior_rsi: float | None = None
    output: list[str] = []
    for i in range(len(close)):
        up_age = 0 if i > 0 and above[i] and not above[i - 1] else up_age + 1
        down_age = 0 if i > 0 and (not above[i]) and above[i - 1] else down_age + 1
        rsi_value = float(rsi14[i]) if np.isfinite(rsi14[i]) else 50.0
        rsi_delta = rsi_value - prior_rsi if prior_rsi is not None else 0.0
        if above[i]:
            if state == "Blue":
                state = "Green" if close[i] < ema21[i] else "Blue"
            else:
                state = "Blue" if rsi_value > 52 and up_age >= 2 and rsi_delta <= 3 else "Green"
        else:
            if state == "Red":
                state = "Yellow" if rsi_value > 50 else "Red"
            else:
                state = "Red" if rsi_value < 47 and down_age >= 2 and rsi_delta >= -3 else "Yellow"
        prior_rsi = rsi_value
        output.append(state)
    return pd.Series(output, index=nq.index, dtype="object")


def vix_state_series(vix: pd.DataFrame) -> tuple[pd.Series, list[dict[str, Any]]]:
    """Exact VIX state facts used by the Stage16/34 source construction."""
    frame = pd.DataFrame({
        "close": pd.to_numeric(vix["Close"], errors="coerce"),
        "high": pd.to_numeric(vix["High"], errors="coerce"),
    }).replace([np.inf, -np.inf], np.nan).dropna()
    frame = frame[(frame["close"] > 0) & (frame["high"] > 0)]
    frame = frame[frame.index >= bd.VIX_CYCLE_START].copy()
    frame["wma5"] = bd._vix_lwma(frame["high"], bd.VIX_CYCLE_FAST).to_numpy()
    frame["wma10"] = bd._vix_lwma(frame["high"], bd.VIX_CYCLE_SLOW).to_numpy()

    periods = frame.index.to_period("M")
    monthly_high = frame["high"].groupby(periods).max()
    current_period = frame.index[-1].to_period("M")
    levels: dict[pd.Period, tuple[float, float, int]] = {}
    count = 0
    total = 0.0
    total_sq = 0.0
    for period in sorted(set(periods)):
        sigma1, sigma2 = bd._vix_sigma_levels(count, total, total_sq)
        levels[period] = (sigma1, sigma2, count)
        if period < current_period and period in monthly_high.index:
            value = float(monthly_high.loc[period])
            if np.isfinite(value) and value > 0:
                logged = math.log10(value)
                count += 1
                total += logged
                total_sq += logged * logged
    frame["sigma1"] = [levels[period][0] for period in periods]
    frame["sigma2"] = [levels[period][1] for period in periods]
    frame["n_months"] = [levels[period][2] for period in periods]
    frame = frame[frame["n_months"] >= bd.VIX_CYCLE_MIN_MONTHS].copy()

    state = 0
    rollover_seen = False
    bottom_seen = False
    post_bottom_extreme = False
    prior_w5 = prior_w10 = prior_high = None
    labels: list[tuple[pd.Timestamp, str | None]] = []
    signals: list[dict[str, Any]] = []
    for date, row in frame.iterrows():
        if any(pd.isna(row[key]) for key in ("high", "wma5", "wma10", "sigma1", "sigma2")):
            labels.append((date, None))
            continue
        ds = pd.Timestamp(date).strftime("%Y-%m-%d")
        vix_high = float(row["high"])
        wma5 = float(row["wma5"])
        wma10 = float(row["wma10"])
        sigma1 = float(row["sigma1"])
        sigma2 = float(row["sigma2"])
        bottom_signal = False
        if state == 0 and prior_high is not None and prior_high <= sigma1 and sigma1 < vix_high <= sigma2:
            signals.append({"date": ds, "type": "WATCH", "value": vix_high})
        if state == 0:
            if vix_high > sigma2:
                state = 1
                rollover_seen = False
                bottom_seen = False
                post_bottom_extreme = False
                signals.append({"date": ds, "type": "EVENT", "value": vix_high})
        else:
            if not rollover_seen and prior_w5 is not None and wma5 < prior_w5:
                rollover_seen = True
                if not bottom_seen:
                    state = 2
                signals.append({"date": ds, "type": "ROLLOVER", "value": vix_high})
            cross_down = (
                prior_w5 is not None and prior_w10 is not None
                and wma5 < wma10 and prior_w5 >= prior_w10
            )
            if not bottom_seen and cross_down:
                bottom_seen = True
                state = 3
                bottom_signal = True
                signals.append({"date": ds, "type": "BOTTOM", "value": vix_high})
            if bottom_seen and not bottom_signal and not post_bottom_extreme and vix_high > sigma2:
                post_bottom_extreme = True
                signals.append({"date": ds, "type": "RE-EXTREME", "value": vix_high})
            if bottom_seen and not bottom_signal and vix_high < sigma1:
                state = 0
                rollover_seen = False
                bottom_seen = False
                post_bottom_extreme = False
                signals.append({"date": ds, "type": "REARM", "value": vix_high})
        label = (
            "NORMAL" if state == 0 else
            "EXTREME" if state == 1 else
            "ROLLOVER" if state == 2 else
            "RE-EXTREME" if post_bottom_extreme else "BOTTOM"
        )
        labels.append((pd.Timestamp(date), label))
        prior_w5, prior_w10, prior_high = wma5, wma10, vix_high
    series = pd.Series({date: label for date, label in labels}, name="vix_state", dtype="object")
    return series.sort_index(), signals


def build_daily_inputs(qqq: pd.DataFrame, tqqq: pd.DataFrame, nqraw: pd.DataFrame,
                       vix: pd.DataFrame, mc57: pd.Series) -> tuple[pd.DataFrame, dict[str, np.ndarray]]:
    """Port of Stage16 source-data block used by Stage34/56."""
    vix_state, _ = vix_state_series(vix)
    nq = nqsar_colors(nqraw)
    close = qqq["Close"].astype(float)
    high = qqq["High"].astype(float)
    low = qqq["Low"].astype(float)
    volume = qqq["Volume"].astype(float)
    previous = close.shift(1)
    true_range = pd.concat(
        [(high - low), (high - previous).abs(), (low - previous).abs()], axis=1
    ).max(axis=1)
    atr14 = true_range.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    ema10 = close.ewm(span=10, adjust=False).mean()
    ema21 = close.ewm(span=21, adjust=False).mean()
    sma50 = close.rolling(50).mean()
    sma200 = close.rolling(200).mean()
    typical = (high + low + close) / 3.0
    vwap63 = (typical * volume).rolling(63).sum() / volume.rolling(63).sum()
    vwap252 = (
        (typical * volume).rolling(252, min_periods=200).sum()
        / volume.rolling(252, min_periods=200).sum()
    )
    sma50_atr = (close - sma50) / atr14
    drawdown10 = close / close.rolling(10, min_periods=2).max() - 1.0

    index = qqq.index.intersection(tqqq.index)
    index = index[index >= START]
    frame = pd.DataFrame(index=index)
    frame["date"] = index
    frame["ret"] = tqqq["Open"].pct_change().reindex(index)
    frame["mc"] = mc57.reindex(index).ffill()
    frame["nq"] = nq.reindex(index).ffill()
    frame["panic"] = (
        vix_state.reindex(index).ffill().astype(str).isin(["BOTTOM", "RE-EXTREME"])
    )
    frame["a50"] = (close > sma50).reindex(index)
    frame["a63"] = (close > vwap63).reindex(index)
    frame["a200"] = (close > sma200).reindex(index)
    frame["a252"] = (close > vwap252).reindex(index)
    frame["gte10"] = (close > ema10).reindex(index)
    frame["lte21"] = (close < ema21).reindex(index)
    frame["s50a"] = sma50_atr.reindex(index)
    frame["dd10"] = drawdown10.reindex(index)
    frame["vix_close"] = vix["Close"].astype(float).reindex(index).ffill()
    frame["qqq_close"] = close.reindex(index)
    frame["qqq_sma50"] = sma50.reindex(index)
    frame["qqq_atr14"] = atr14.reindex(index)
    frame = frame.dropna().reset_index(drop=True)
    frame["nq_i"] = np.asarray([COLOR_TO_INT.get(str(value), 1) for value in frame["nq"]], dtype=np.int8)
    arrays = {
        "ret": frame["ret"].to_numpy(float),
        "mc": frame["mc"].to_numpy(float),
        "nq": frame["nq_i"].to_numpy(np.int8),
        "panic": frame["panic"].to_numpy(bool),
        "a50": frame["a50"].to_numpy(bool),
        "a63": frame["a63"].to_numpy(bool),
        "a200": frame["a200"].to_numpy(bool),
        "a252": frame["a252"].to_numpy(bool),
        "gte10": frame["gte10"].to_numpy(bool),
        "lte21": frame["lte21"].to_numpy(bool),
        "s50a": frame["s50a"].to_numpy(float),
        "dd10": frame["dd10"].to_numpy(float),
    }
    return frame, arrays


def current30_trace(data: dict[str, np.ndarray], params: dict[str, float] | None = None) -> dict[str, np.ndarray]:
    """Exact Stage34 ``simulate(..., PCUR, return_trace=True)`` target state machine."""
    p = CURRENT_PARAMS if params is None else params
    mc = data["mc"]
    nq = data["nq"]
    panic = data["panic"]
    a50 = data["a50"]
    a63 = data["a63"]
    a200 = data["a200"]
    a252 = data["a252"]
    gte10 = data["gte10"]
    lte21 = data["lte21"]
    s50a = data["s50a"]
    dd10 = data["dd10"]
    n = len(mc)

    raw_bear = (~a200) & (~a252)
    bear5 = np.zeros(n, bool)
    for i in range(4, n):
        bear5[i] = raw_bear[i - 4:i + 1].all()
    score3 = (
        a50.astype(int) + a63.astype(int) + (mc >= 35).astype(int) + (nq != 0).astype(int)
    ) >= 3
    fast_rec = int(p["fast_rec"])
    recovered = np.zeros(n, bool)
    for i in range(fast_rec - 1, n):
        recovered[i] = gte10[i - fast_rec + 1:i + 1].all()
    arm = np.empty(n, float)
    for i in range(n):
        arm[i] = np.min(s50a[max(0, i - 19):i + 1])

    slow_a = np.zeros(n, bool)
    fast_a = np.zeros(n, bool)
    mc_a = np.zeros(n, bool)
    slow = fast = mc_lock = False
    for i in range(n):
        if bear5[i]:
            slow = True
        if slow and (not raw_bear[i]) and score3[i] and mc[i] >= 35:
            slow = False
        if mc[i] < 25:
            mc_lock = True
        if mc_lock and mc[i] >= 35 and score3[i] and nq[i] != 0:
            mc_lock = False
        if dd10[i] <= p["fast_dd"] and lte21[i]:
            fast = True
        if fast and recovered[i]:
            fast = False
        slow_a[i] = slow
        fast_a[i] = fast
        mc_a[i] = mc_lock
    risk_lock = slow_a | fast_a | mc_a

    base = np.zeros(n, float)
    strong = np.zeros(n, bool)
    for i in range(n):
        value = 0.0 if risk_lock[i] else p["base"]
        if value > 0 and mc[i] >= 65 and nq[i] == 3 and a50[i] and a63[i] and s50a[i] <= 2.5:
            value = 1.0
            strong[i] = True
        if panic[i] and s50a[i] <= -2:
            value = max(value, p.get("panic", 1.0))
        base[i] = min(1.0, value)

    target = base.copy()
    sleeve = np.zeros(n, np.int8)
    active = 0
    entry = 0
    seen_blue = False
    cool_until = 0
    ext_entry = 0
    for i in range(1, n):
        red_green = nq[i - 1] == 0 and nq[i] == 2
        green_blue = nq[i - 1] == 2 and nq[i] == 3
        blue_green = nq[i - 1] == 3 and nq[i] == 2
        blue_yellow = nq[i - 1] == 3 and nq[i] == 1
        if active == 0:
            rg_mc = p["rg_mc_slow"] if slow_a[i] else 35
            if red_green and arm[i] <= -2 and mc[i] >= rg_mc and risk_lock[i] and i >= cool_until:
                active = 1
                entry = i + 1
                seen_blue = False
            elif green_blue and arm[i] <= -1.5 and mc[i] >= 35 and (not risk_lock[i]):
                active = 2
                entry = i + 1
                seen_blue = True
        if active == 1:
            if nq[i] == 3:
                seen_blue = True
            held = max(0, i - (entry - 1))
            exit_now = nq[i] in (0, 1) or held >= 7
            if exit_now:
                if (not seen_blue) and slow_a[i] and p["cooldown"] > 0:
                    cool_until = i + int(p["cooldown"])
                active = 0
            else:
                if (not risk_lock[i]) and nq[i] == 3:
                    active = 2
                    entry = i + 1
                    total = p["gb"]
                else:
                    total = p["rg_slow"] if slow_a[i] else p["rg_fast"]
                if base[i] >= 0.999:
                    total = 1.0
                target[i] = max(base[i], total)
                sleeve[i] = active
        elif active == 2:
            held = max(0, i - (entry - 1))
            bad = risk_lock[i] or blue_green or blue_yellow or nq[i] == 0
            if bad:
                active = 0
            elif held >= 20:
                continuation_ok = (
                    (not risk_lock[i]) and a200[i] and a50[i] and a63[i]
                    and (not lte21[i]) and nq[i] != 0 and mc[i] >= p.get("ext_mc", 35)
                )
                if p.get("ext_exp", 0) > 0 and continuation_ok:
                    active = 3
                    ext_entry = i
                    total = p["ext_exp"]
                    target[i] = max(base[i], total)
                    sleeve[i] = 3
                else:
                    active = 0
            else:
                total = p["gb"]
                if base[i] >= 0.999:
                    total = 1.0
                target[i] = max(base[i], total)
                sleeve[i] = 2
        elif active == 3:
            held = i - ext_entry
            bad = (
                risk_lock[i] or nq[i] == 0 or lte21[i] or (not a200[i]) or (not a50[i])
                or (not a63[i]) or mc[i] < p.get("ext_mc", 35) or held >= p.get("ext_max", 40)
            )
            if bad:
                active = 0
            else:
                total = p["ext_exp"]
                if base[i] >= 0.999:
                    total = 1.0
                target[i] = max(base[i], total)
                sleeve[i] = 3
    return {
        "target": np.clip(target, 0, 1),
        "risklock": risk_lock,
        "slow_lock": slow_a,
        "fast_lock": fast_a,
        "mc_lock": mc_a,
        "sleeve": sleeve,
        "strong": strong,
    }


def wilder_rsi(close: np.ndarray, n: int = 14) -> np.ndarray:
    """TradingView/Pine-style Wilder RMA seed used by Stage51."""
    values = np.asarray(close, float)
    delta = np.diff(values, prepend=np.nan)
    up = np.where(delta > 0, delta, 0.0)
    down = np.where(delta < 0, -delta, 0.0)
    avg_up = np.full(len(values), np.nan)
    avg_down = np.full(len(values), np.nan)
    if len(values) > n:
        avg_up[n] = np.nanmean(up[1:n + 1])
        avg_down[n] = np.nanmean(down[1:n + 1])
        for i in range(n + 1, len(values)):
            avg_up[i] = (avg_up[i - 1] * (n - 1) + up[i]) / n
            avg_down[i] = (avg_down[i - 1] * (n - 1) + down[i]) / n
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = avg_up / avg_down
        result = 100 - 100 / (1 + ratio)
    result[(avg_down == 0) & np.isfinite(avg_up)] = 100.0
    result[(avg_up == 0) & (avg_down == 0)] = 50.0
    return result


def build_4h_bars(raw: pd.DataFrame) -> pd.DataFrame:
    """Stage51 RTH grouping: 09:30-13:30 and 13:30-16:00 partial bar."""
    frame = raw.copy()
    if isinstance(frame.columns, pd.MultiIndex):
        frame = _plain(frame)
    index = pd.DatetimeIndex(frame.index)
    if index.tz is None:
        index = index.tz_localize("America/New_York")
    else:
        index = index.tz_convert("America/New_York")
    frame.index = index
    frame = frame[["Open", "High", "Low", "Close"]].apply(pd.to_numeric, errors="coerce").dropna()
    minutes = frame.index.hour * 60 + frame.index.minute
    frame = frame[(minutes >= 570) & (minutes < 960)].copy()
    minutes = frame.index.hour * 60 + frame.index.minute
    frame["date"] = pd.DatetimeIndex(frame.index.date)
    frame["slot"] = np.where(minutes < 810, 0, 1)
    bars = (
        frame.groupby(["date", "slot"], sort=True)
        .agg(Open=("Open", "first"), High=("High", "max"), Low=("Low", "min"),
             Close=("Close", "last"), n=("Close", "size"))
        .reset_index()
    )
    bars = bars[bars["n"] >= 6].copy().sort_values(["date", "slot"]).reset_index(drop=True)
    bars["rsi14"] = wilder_rsi(bars["Close"].to_numpy(float), 14)
    rsi_values = bars["rsi14"].to_numpy(float)
    prior = np.r_[False, rsi_values[:-1] > 30]
    bars["touch30"] = (rsi_values <= 30) & prior
    return bars


def download_qqq_5m() -> pd.DataFrame:
    raw = yf.download(
        "QQQ", period="60d", interval="5m", progress=False,
        auto_adjust=False, actions=False, prepost=False, threads=False,
    )
    if raw is None or raw.empty:
        raise RuntimeError("QQQ 5m live download returned no data")
    return raw


def download_qqq_5m_resilient() -> tuple[pd.DataFrame, str]:
    errors: list[str] = []
    for provider, callback in (
        ("YAHOO_CHART", lambda: download_yahoo_chart("QQQ", interval="5m", range_text="60d")),
        ("YAHOO_YFINANCE", download_qqq_5m),
        ("FMP_5MIN", lambda: download_fmp_frame("QQQ", intraday_5m=True)),
    ):
        try:
            frame = callback()
            if frame is not None and not frame.empty:
                return frame, provider
        except Exception as exc:
            errors.append(f"{provider}={type(exc).__name__}: {exc}")
    raise RuntimeError(f"QQQ 5m sources exhausted: {' | '.join(errors)}")


def collect_live_sources() -> dict[str, Any]:
    """Collect every Stage34/56 input on a clean request budget.

    This runs before the legacy dashboard and strict-LOO bulk downloads. The
    cache is private build state and is not in the public-site allowlist.
    """
    qqq_5m, qqq_5m_provider = _retry("QQQ 5m", download_qqq_5m_resilient)
    daily_with_provider = {
        "QQQ": _retry("QQQ daily", lambda: download_daily_resilient("QQQ", "2009-01-01")),
        "TQQQ": _retry("TQQQ daily", lambda: download_daily_resilient("TQQQ", "2010-01-01")),
        "NQ=F": _retry("NQ=F daily", lambda: download_daily_resilient("NQ=F", "2000-01-01")),
        "^VIX": _retry("^VIX daily", lambda: download_daily_resilient("^VIX", "1990-01-01")),
    }
    daily = {ticker: value[0] for ticker, value in daily_with_provider.items()}
    daily_providers = {ticker: value[1] for ticker, value in daily_with_provider.items()}
    mc57, mc_coverage, mc_meta = _retry("MC57", lambda: compute_mc57(include_meta=True))
    return {
        "schema": CACHE_SCHEMA,
        "fetched_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "daily": {ticker: _frame_payload(frame) for ticker, frame in daily.items()},
        "mc57": _series_payload(mc57),
        "mc57_coverage": _series_payload(mc_coverage),
        "qqq_5m": _frame_payload(qqq_5m),
        "coverage": {
            "daily_latest": {
                ticker: str(pd.Timestamp(frame.index.max()).date()) for ticker, frame in daily.items()
            },
            "mc57_latest": str(pd.Timestamp(mc57.dropna().index.max()).date()),
            "qqq_5m_latest": pd.Timestamp(qqq_5m.index.max()).isoformat(),
        },
        "providers": {
            "daily": daily_providers,
            "qqq_5m": qqq_5m_provider,
            "mc57": mc_meta,
        },
    }


def write_source_cache(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    temporary.replace(target)


def load_source_cache(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema") != CACHE_SCHEMA:
        raise RuntimeError(f"TQQQ_SOURCE_CACHE_SCHEMA_INVALID: {payload.get('schema')!r}")
    required_daily = ("QQQ", "TQQQ", "NQ=F", "^VIX")
    missing = [ticker for ticker in required_daily if ticker not in payload.get("daily", {})]
    if missing:
        raise RuntimeError(f"TQQQ_SOURCE_CACHE_DAILY_MISSING: {missing}")
    return {
        "fetched_at": payload.get("fetched_at"),
        "coverage": payload.get("coverage", {}),
        "providers": payload.get("providers", {}),
        "qqq": _frame_from_payload(payload["daily"]["QQQ"]),
        "tqqq": _frame_from_payload(payload["daily"]["TQQQ"]),
        "nq": _frame_from_payload(payload["daily"]["NQ=F"]),
        "vix": _frame_from_payload(payload["daily"]["^VIX"]),
        "mc57": _series_from_payload(payload["mc57"]),
        "mc_coverage": _series_from_payload(payload["mc57_coverage"]),
        "qqq_5m": _frame_from_payload(payload["qqq_5m"]),
    }


def stage56_trace(data: dict[str, np.ndarray], vix_close: np.ndarray, touch30: np.ndarray,
                  current: dict[str, np.ndarray]) -> dict[str, np.ndarray | int]:
    """Exact selected Stage56 M30_TOUCH30_F80_D10 overlay."""
    target = current["target"].copy()
    seed = (
        (data["s50a"] <= -0.50)
        & (np.asarray(vix_close, float) >= 23.0)
        & (data["dd10"] <= -0.02)
    )
    age = 10**9
    active = False
    entry = -1
    consumed = -1
    entries = 0
    active_trace = np.zeros(len(target), bool)
    held_trace = np.zeros(len(target), int)
    seed_age = np.full(len(target), 10**9, int)
    raw_bear = (~data["a200"]) & (~data["a252"])
    for i in range(len(target)):
        age = 0 if seed[i] else age + 1
        seed_age[i] = age
        recent = age <= STAGE56_LOOKBACK
        previous_seeds = np.flatnonzero(seed[:i + 1])
        seed_id = int(previous_seeds[-1]) if len(previous_seeds) else -1
        allowed = data["mc"][i] >= 20
        if (not active) and recent and bool(touch30[i]) and allowed and seed_id > consumed:
            active = True
            entry = i
            consumed = seed_id
            entries += 1
        if active:
            if seed[i]:
                consumed = max(consumed, i)
            held = i - entry
            done = held >= STAGE56_MAX_DAYS
            bad = data["mc"][i] < 20 or (raw_bear[i] and held >= 10) or done or held >= 20
            if bad:
                active = False
                entry = -1
            else:
                target[i] = max(target[i], STAGE56_FLOOR)
                active_trace[i] = True
                held_trace[i] = held
    return {
        "target": np.clip(target, 0, 1),
        "active": active_trace,
        "held": held_trace,
        "seed": seed,
        "seed_age": seed_age,
        "entries": entries,
    }


def build_live(asof_text: str, sources: dict[str, Any] | None = None) -> dict[str, Any]:
    asof = pd.Timestamp(asof_text).normalize()
    if sources is None:
        qqq = download_daily("QQQ", "2009-01-01")
        tqqq = download_daily("TQQQ", "2010-01-01")
        nq = download_daily("NQ=F", "2000-01-01")
        vix = download_daily("^VIX", "1990-01-01")
        mc57, mc_coverage = compute_mc57()
        qqq_5m = download_qqq_5m()
        source_fetched_at = None
    else:
        qqq = sources["qqq"]
        tqqq = sources["tqqq"]
        nq = sources["nq"]
        vix = sources["vix"]
        mc57 = sources["mc57"]
        mc_coverage = sources["mc_coverage"]
        qqq_5m = sources["qqq_5m"]
        source_fetched_at = sources.get("fetched_at")
    mc_clean = pd.to_numeric(mc57, errors="coerce").dropna()
    if mc_clean.empty or pd.Timestamp(mc_clean.index.max()).normalize() < asof:
        latest = str(pd.Timestamp(mc_clean.index.max()).date()) if len(mc_clean) else None
        raise RuntimeError(f"MC57_ASOF_REQUIRED requested={asof_text} latest={latest}")
    daily, data = build_daily_inputs(qqq, tqqq, nq, vix, mc57)
    daily_dates = pd.to_datetime(daily["date"]).dt.normalize()
    matches = np.flatnonzero(daily_dates.to_numpy() == asof.to_datetime64())
    if not len(matches):
        latest = str(daily_dates.iloc[-1].date()) if len(daily_dates) else None
        raise RuntimeError(f"CURRENT30_ASOF_REQUIRED requested={asof_text} latest={latest}")
    end_pos = int(matches[-1])
    daily = daily.iloc[:end_pos + 1].reset_index(drop=True)
    data = {key: values[:end_pos + 1].copy() for key, values in data.items()}
    current = current30_trace(data)

    bars = build_4h_bars(qqq_5m)
    bars = bars[pd.to_datetime(bars["date"]) <= asof].copy()
    if bars.empty:
        raise RuntimeError("QQQ_4H_RSI_DATA_REQUIRED")
    coverage_dates = pd.DatetimeIndex(pd.to_datetime(bars["date"]).unique()).sort_values()
    if len(coverage_dates) < 35:
        raise RuntimeError(f"QQQ_4H_HISTORY_INSUFFICIENT sessions={len(coverage_dates)}")
    if coverage_dates[-1].normalize() != asof:
        raise RuntimeError(
            f"QQQ_4H_ASOF_REQUIRED requested={asof_text} latest={coverage_dates[-1].date()}"
        )
    daily_signal = bars.groupby("date")["touch30"].max().astype(bool)
    signal = np.asarray([
        bool(daily_signal.get(pd.Timestamp(date).normalize(), False))
        for date in pd.to_datetime(daily["date"])
    ], dtype=bool)
    vix_close = daily["vix_close"].to_numpy(float)
    stage56 = stage56_trace(data, vix_close, signal, current)

    asof_bars = bars[pd.to_datetime(bars["date"]) <= asof]
    latest_bar = asof_bars.iloc[-1]
    prior_bar = asof_bars.iloc[-2] if len(asof_bars) >= 2 else None
    rsi4h = float(latest_bar["rsi14"]) if np.isfinite(latest_bar["rsi14"]) else None
    prior_rsi4h = (
        float(prior_bar["rsi14"]) if prior_bar is not None and np.isfinite(prior_bar["rsi14"]) else None
    )
    i = len(daily) - 1
    underlying = float(current["target"][i])
    requested = float(stage56["target"][i])
    seed_age = int(stage56["seed_age"][i]) if int(stage56["seed_age"][i]) < 10**8 else None
    active = bool(stage56["active"][i])
    held = int(stage56["held"][i]) if active else 0
    mc_value = float(data["mc"][i])
    mc_coverage_slice = mc_coverage.loc[mc_coverage.index <= asof]
    mc_cov_value = mc_coverage_slice.iloc[-1] if len(mc_coverage_slice) else np.nan
    sleeve_code = int(current["sleeve"][i])
    sleeve_name = {0: "NONE", 1: "RG", 2: "GB", 3: "GB_CONTINUATION"}.get(sleeve_code, "UNKNOWN")
    return {
        "schema": "v38-tqqq-panic-state-1",
        "asof": asof_text,
        "candidate": "M30_TOUCH30_F80_D10",
        "live_generation_status": "READY",
        "source_cache_fetched_at": source_fetched_at,
        "source_providers": sources.get("providers", {}) if sources is not None else {},
        "current30": {
            "status": "READY",
            "underlying_target_pct": underlying * 100.0,
            "normal_exposure_pct": 30,
            "risk_lock": bool(current["risklock"][i]),
            "slow_lock": bool(current["slow_lock"][i]),
            "fast_lock": bool(current["fast_lock"][i]),
            "mc_lock": bool(current["mc_lock"][i]),
            "nqsar_proxy": INT_TO_COLOR.get(int(data["nq"][i]), "UNKNOWN"),
            "sleeve": sleeve_name,
            "definition": "Stage34 PCUR hierarchy; 30% is normal exposure, not a fixed target",
        },
        "vix_close": float(vix_close[i]),
        "qqq_sma50_atr_deviation": float(data["s50a"][i]),
        "qqq_drawdown10": float(data["dd10"][i]),
        "strict_seed_today": bool(stage56["seed"][i]),
        "seed_age_sessions": seed_age,
        "rsi4h": rsi4h,
        "prior_rsi4h": prior_rsi4h,
        "touch30_today": bool(signal[i]),
        "mc57": mc_value,
        "mc57_coverage": float(mc_cov_value) if np.isfinite(mc_cov_value) else None,
        "underlying_target_pct": underlying * 100.0,
        "requested_target_pct": requested * 100.0,
        "floor_pct_when_active": 80,
        "floor_semantics": "max(CURRENT30 target, 80%)",
        "active": active,
        "held_sessions": held,
        "entry_pending_next_open": bool(active and held == 0 and signal[i]),
        "exit_rule": "MC57<20 or D10; signal at completed bar/day close, execute next session open",
        "nqsar_scope": "not a Stage56 overlay gate; NQSAR remains inside CURRENT30 hierarchy",
        "intraday": {
            "source": "Yahoo QQQ 5m live",
            "rth": "09:30-16:00 America/New_York",
            "bars": ["09:30-13:30", "13:30-16:00 partial"],
            "wilder_rsi_period": 14,
            "touch_definition": "prior RSI > 30 and current RSI <= 30",
            "coverage_start": str(coverage_dates[0].date()),
            "coverage_end": str(coverage_dates[-1].date()),
            "coverage_sessions": int(len(coverage_dates)),
        },
        "reset_desired_pct": None,
        "normal_stock_desired_pct": None,
        "gross100_priority": "RESET_TQQQ80_NORMAL_TQQQ_EXTRA",
    }


def data_required(asof: str | None, reason: str) -> dict[str, Any]:
    return {
        "schema": "v38-tqqq-panic-state-1",
        "asof": asof,
        "candidate": "M30_TOUCH30_F80_D10",
        "live_generation_status": "DATA REQUIRED",
        "reason": reason,
        "current30": {"status": "DATA REQUIRED", "underlying_target_pct": None, "normal_exposure_pct": 30},
        "underlying_target_pct": None,
        "requested_target_pct": None,
        "reset_desired_pct": None,
        "normal_stock_desired_pct": None,
        "active": False,
        "held_sessions": 0,
        "gross100_priority": "RESET_TQQQ80_NORMAL_TQQQ_EXTRA",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", default="state.json")
    parser.add_argument("--out", default="tqqq-panic-state.json")
    parser.add_argument("--cache", default=None)
    parser.add_argument("--mri-log", default="daily_log.csv")
    parser.add_argument("--prefetch-cache", default=None)
    args = parser.parse_args()
    if args.prefetch_cache:
        cache = collect_live_sources()
        write_source_cache(args.prefetch_cache, cache)
        coverage = cache.get("coverage", {})
        print(
            f"wrote {args.prefetch_cache}: {cache.get('fetched_at')} "
            f"MC57={coverage.get('mc57_latest')} 5m={coverage.get('qqq_5m_latest')}",
            flush=True,
        )
        return
    state_path = Path(args.state)
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    asof = str(state.get("date") or "") or None
    try:
        if asof is None:
            raise RuntimeError("STATE_DATE_REQUIRED")
        if not args.cache:
            raise RuntimeError("CANONICAL_MC57_CACHE_REQUIRED")
        sources = load_source_cache(args.cache)
        sources = apply_legacy_mc57_overlay(sources, state, Path(args.mri_log))
        live = build_live(asof, sources=sources)
    except Exception as exc:
        live = data_required(asof, f"{type(exc).__name__}: {exc}")
        print(f"TQQQ_LIVE_DATA_REQUIRED {type(exc).__name__}: {exc}", flush=True)
    Path(args.out).write_text(json.dumps(live, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"wrote {args.out}: {live.get('live_generation_status')} "
        f"CURRENT30={live.get('underlying_target_pct')} Stage56={live.get('requested_target_pct')}",
        flush=True,
    )


if __name__ == "__main__":
    main()
