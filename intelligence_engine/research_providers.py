from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import pandas as pd

from .research_financials import extract_companyfacts_history


@dataclass
class SecCompanyFactsProvider:
    root: Path
    name: str = "sec_companyfacts"

    def history(self, ticker: str) -> pd.DataFrame:
        path = self.root / f"{str(ticker).upper()}.json"
        if not path.exists():
            return pd.DataFrame()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return pd.DataFrame()
        return extract_companyfacts_history(payload, ticker=str(ticker).upper())


@dataclass
class NullEstimateProvider:
    name: str = "none"

    def history(self, tickers: Sequence[str]) -> pd.DataFrame:
        return pd.DataFrame(columns=["ticker", "available_at", "eps_revision_30d_pct"])


@dataclass
class NullEventProvider:
    name: str = "none"

    def history(self, tickers: Sequence[str]) -> pd.DataFrame:
        return pd.DataFrame(columns=["ticker", "available_at", "event_type"])


@dataclass
class NullOwnershipProvider:
    name: str = "none"

    def history(self, tickers: Sequence[str]) -> pd.DataFrame:
        return pd.DataFrame(columns=["ticker", "available_at", "ownership_change_pct"])
