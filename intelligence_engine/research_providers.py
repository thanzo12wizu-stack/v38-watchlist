from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import pandas as pd

from .research_financials import extract_companyfacts_history


def _configured_research_asof() -> pd.Timestamp | None:
    raw = str(os.environ.get("RESEARCH_YEAR") or "").strip()
    if raw.isdigit() and len(raw) == 4:
        year = int(raw)
        if 1900 <= year <= 2200:
            return pd.Timestamp(year, 12, 31)
    return None


def _bounded_filing_history(
    frame: pd.DataFrame,
    *,
    asof: pd.Timestamp | None,
    filing_limit: int,
) -> pd.DataFrame:
    """Keep enough point-in-time filings for growth/acceleration without loading all SEC history."""
    if frame is None or frame.empty:
        return pd.DataFrame() if frame is None else frame
    work = frame.copy()
    work["available_at"] = pd.to_datetime(work["available_at"], errors="coerce")
    work = work.dropna(subset=["available_at"])
    if asof is not None:
        work = work[work["available_at"] <= pd.Timestamp(asof)]
    if work.empty:
        return work
    filings = pd.Index(work["available_at"].dropna().sort_values().unique())
    keep = filings[-max(8, int(filing_limit)) :]
    return work[work["available_at"].isin(keep)].reset_index(drop=True)


@dataclass
class SecCompanyFactsProvider:
    root: Path
    name: str = "sec_companyfacts"
    filing_limit: int = 12
    asof: pd.Timestamp | None = None

    def history(self, ticker: str) -> pd.DataFrame:
        path = self.root / f"{str(ticker).upper()}.json"
        if not path.exists():
            return pd.DataFrame()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return pd.DataFrame()
        frame = extract_companyfacts_history(payload, ticker=str(ticker).upper())
        return _bounded_filing_history(
            frame,
            asof=self.asof if self.asof is not None else _configured_research_asof(),
            filing_limit=self.filing_limit,
        )


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
