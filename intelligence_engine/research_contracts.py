from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Protocol, Sequence

import pandas as pd

RESEARCH_SCHEMA_VERSION = "2.0"
RESEARCH_POLICY_VERSION = "1.1.0"
DEFAULT_HORIZONS = (5, 10, 21, 63)
RESEARCH_RETENTION_YEARS = 10
RESEARCH_PRIMARY_WINDOW_YEARS = 8
RESEARCH_COMPARISON_WINDOWS = (10, 8, 5, 3)


@dataclass(frozen=True)
class ResearchConfig:
    root: Path = Path("data/intelligence/research")
    years: int = RESEARCH_RETENTION_YEARS
    horizons: tuple[int, ...] = DEFAULT_HORIZONS
    analysis_windows: tuple[int, ...] = RESEARCH_COMPARISON_WINDOWS
    primary_window_years: int = RESEARCH_PRIMARY_WINDOW_YEARS
    stride: int = 1
    max_daily_signals: int = 300
    min_samples: int = 40
    bootstrap_samples: int = 300
    seed: int = 38
    persist_feature_pool: bool = False

    def __post_init__(self) -> None:
        # The workflow historically passed --years 5. Keep that interface
        # compatible while enforcing the research policy selected for production.
        object.__setattr__(self, "years", max(RESEARCH_RETENTION_YEARS, int(self.years)))
        windows = tuple(
            sorted(
                {
                    max(1, int(value))
                    for value in self.analysis_windows
                    if int(value) <= max(RESEARCH_RETENTION_YEARS, int(self.years))
                },
                reverse=True,
            )
        )
        if self.primary_window_years not in windows:
            windows = tuple(sorted(set(windows) | {self.primary_window_years}, reverse=True))
        object.__setattr__(self, "analysis_windows", windows)

    def cutoff(self, end: date) -> date:
        return end - timedelta(days=max(1, self.years) * 366)


@dataclass(frozen=True)
class FactObservation:
    ticker: str
    metric: str
    value: float
    period_start: str | None
    period_end: str
    filed_at: str | None
    available_at: str
    form: str | None = None
    accession: str | None = None
    accounting_standard: str | None = None
    source: str = "sec_companyfacts"
    provider: str = "sec"
    derived_quarter: bool = False
    confidence: float = 1.0
    schema_version: str = RESEARCH_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ResearchManifest:
    generated_at: str
    mode: str
    start_date: str | None
    end_date: str | None
    years_retained: int
    price_rows: int = 0
    fact_rows: int = 0
    signal_rows: int = 0
    outcome_rows: int = 0
    ranking_rows: int = 0
    tickers: int = 0
    data_provider: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    schema_version: str = RESEARCH_SCHEMA_VERSION
    policy_version: str = RESEARCH_POLICY_VERSION

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["primary_expectancy_window_years"] = RESEARCH_PRIMARY_WINDOW_YEARS
        payload["comparison_windows_years"] = list(RESEARCH_COMPARISON_WINDOWS)
        return payload


class FundamentalProvider(Protocol):
    name: str

    def history(self, ticker: str) -> pd.DataFrame:
        ...


class EstimateProvider(Protocol):
    name: str

    def history(self, tickers: Sequence[str]) -> pd.DataFrame:
        ...


class EventProvider(Protocol):
    name: str

    def history(self, tickers: Sequence[str]) -> pd.DataFrame:
        ...


class OwnershipProvider(Protocol):
    name: str

    def history(self, tickers: Sequence[str]) -> pd.DataFrame:
        ...
