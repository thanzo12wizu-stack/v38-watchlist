from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Protocol, Sequence
from urllib.parse import quote
from urllib.request import Request, urlopen

import pandas as pd

from .prices import download_price_map


class PriceProvider(Protocol):
    name: str

    def download(
        self,
        tickers: Sequence[str],
        *,
        period: str = "18mo",
    ) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
        ...


@dataclass
class YFinancePriceProvider:
    name: str = "yfinance"

    def download(
        self,
        tickers: Sequence[str],
        *,
        period: str = "18mo",
    ) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
        prices, diagnostics = download_price_map(tickers, period=period)
        diagnostics["provider"] = self.name
        diagnostics["license_scope"] = "personal_research_only"
        return prices, diagnostics


@dataclass
class FMPPriceProvider:
    """Configurable adapter for a future licensed Financial Modeling Prep plan.

    The endpoint is deliberately configurable because FMP product paths and plan
    entitlements can change. The URL template must contain ``{symbol}``, ``{from}``,
    ``{to}`` and optionally ``{apikey}`` placeholders. The returned payload may be a
    JSON list or a mapping containing ``historical`` or ``data``.
    """

    api_key: str
    url_template: str
    timeout: int = 45
    request_pause_seconds: float = 0.15
    name: str = "fmp"

    @classmethod
    def from_environment(cls) -> "FMPPriceProvider":
        key = os.getenv("FMP_API_KEY", "").strip()
        template = os.getenv("V38_FMP_PRICE_URL_TEMPLATE", "").strip()
        if not key:
            raise RuntimeError("FMP_API_KEY is required for the fmp provider")
        if not template or "{symbol}" not in template:
            raise RuntimeError(
                "V38_FMP_PRICE_URL_TEMPLATE must be configured and contain {symbol}"
            )
        return cls(api_key=key, url_template=template)

    def _url(self, ticker: str, start: date, end: date) -> str:
        return self.url_template.format(
            symbol=quote(ticker),
            from_=start.isoformat(),
            **{
                "from": start.isoformat(),
                "to": end.isoformat(),
                "apikey": quote(self.api_key),
            },
        )

    def _fetch_one(self, ticker: str, start: date, end: date) -> pd.DataFrame:
        request = Request(
            self._url(ticker, start, end),
            headers={"User-Agent": "V38-Intelligence/1.0"},
        )
        with urlopen(request, timeout=self.timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if isinstance(payload, dict):
            payload = payload.get("historical") or payload.get("data") or payload.get("results") or []
        frame = pd.DataFrame(payload)
        if frame.empty:
            return frame
        mapping = {str(column).lower(): column for column in frame.columns}
        date_col = next((mapping[name] for name in ("date", "datetime", "timestamp") if name in mapping), None)
        if date_col is None:
            raise ValueError(f"FMP payload for {ticker} has no date column")
        rename = {}
        for target, names in {
            "open": ("open",),
            "high": ("high",),
            "low": ("low",),
            "close": ("adjclose", "adj_close", "close"),
            "volume": ("volume",),
        }.items():
            source = next((mapping[name] for name in names if name in mapping), None)
            if source is not None:
                rename[source] = target
        frame = frame.rename(columns=rename)
        required = {"open", "high", "low", "close", "volume"}
        if not required.issubset(frame.columns):
            raise ValueError(f"FMP payload for {ticker} missing {sorted(required - set(frame.columns))}")
        frame.index = pd.to_datetime(frame[date_col], errors="coerce")
        frame = frame.loc[frame.index.notna(), sorted(required)].sort_index()
        for column in required:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        return frame.dropna(subset=["close", "high", "low", "volume"])

    def download(
        self,
        tickers: Sequence[str],
        *,
        period: str = "18mo",
    ) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
        end = date.today()
        months = 18
        if period.endswith("mo"):
            try:
                months = max(1, int(period[:-2]))
            except ValueError:
                months = 18
        elif period.endswith("y"):
            try:
                months = max(12, int(period[:-1]) * 12)
            except ValueError:
                months = 18
        start = end - timedelta(days=int(months * 31.0 + 30))
        normalized = sorted({str(ticker).upper().strip() for ticker in tickers if str(ticker).strip()})
        prices: dict[str, pd.DataFrame] = {}
        failures: list[dict[str, str]] = []
        for ticker in normalized:
            try:
                frame = self._fetch_one(ticker, start, end)
                if not frame.empty:
                    prices[ticker] = frame
                else:
                    failures.append({"ticker": ticker, "error": "empty_response"})
            except Exception as exc:
                failures.append({"ticker": ticker, "error": f"{type(exc).__name__}: {str(exc)[:160]}"})
            time.sleep(self.request_pause_seconds)
        return prices, {
            "source": self.name,
            "provider": self.name,
            "requested": len(normalized),
            "received": len(prices),
            "coverage": len(prices) / len(normalized) if normalized else 0.0,
            "qqq_received": "QQQ" in prices,
            "failures": failures,
            "license_scope": "configured_paid_provider",
        }


def get_price_provider(name: str | None = None) -> PriceProvider:
    provider = (name or os.getenv("V38_PRICE_PROVIDER", "yfinance")).strip().lower()
    if provider in {"yfinance", "yf"}:
        return YFinancePriceProvider()
    if provider in {"fmp", "financial_modeling_prep"}:
        return FMPPriceProvider.from_environment()
    raise ValueError(f"unsupported price provider: {provider}")
