from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class FundamentalSnapshot:
    revenue: float | None = None
    revenue_yoy: float | None = None
    revenue_acceleration: float | None = None
    eps: float | None = None
    eps_yoy: float | None = None
    eps_acceleration: float | None = None
    gross_margin: float | None = None
    gross_margin_delta: float | None = None
    operating_margin: float | None = None
    operating_margin_delta: float | None = None
    free_cash_flow: float | None = None
    free_cash_flow_yoy: float | None = None
    shares_yoy: float | None = None
    coverage: float = 0.0
    accounting_standard: str | None = None
    latest_filing_date: str | None = None


@dataclass
class ScoreBundle:
    momentum: float | None = None
    fundamental: float | None = None
    improvement: float | None = None
    leadership: float | None = None
    quality: float | None = None
    emerging: float | None = None
    compounder: float | None = None
    breakout: float | None = None
    turnaround: float | None = None
    candidate: float | None = None
    confidence: float = 0.0


@dataclass
class StockIntelligence:
    ticker: str
    asof: str
    sector: str | None = None
    industry: str | None = None
    theme: list[str] = field(default_factory=list)
    price: float | None = None
    market_cap: float | None = None
    dollar_volume_20d: float | None = None
    adr_pct: float | None = None
    rs: dict[str, float | None] = field(default_factory=dict)
    rs_change_21d: dict[str, float | None] = field(default_factory=dict)
    distance_52w_high_pct: float | None = None
    volume_ratio_20d: float | None = None
    fundamentals: FundamentalSnapshot = field(default_factory=FundamentalSnapshot)
    scores: ScoreBundle = field(default_factory=ScoreBundle)
    tags: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    source_dates: dict[str, str] = field(default_factory=dict)
    schema_version: str = "1.0"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
