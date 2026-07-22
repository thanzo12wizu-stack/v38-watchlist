from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class EngineConfig:
    universe_csv: Path = Path("universe.csv")
    price_cache: Path = Path("prices.pkl")
    output_dir: Path = Path("data/intelligence")
    sec_cache_dir: Path = Path("data/sec_companyfacts")
    history_dir: Path = Path("data/intelligence/history")
    candidate_limit: int = 300
    detail_limit: int = 100
    min_price: float = 5.0
    min_dollar_volume: float = 10_000_000.0
    rs_windows: tuple[int, ...] = (21, 63, 126, 189, 252)
    score_weights: dict[str, float] = field(
        default_factory=lambda: {
            "momentum": 0.30,
            "fundamental": 0.30,
            "improvement": 0.20,
            "leadership": 0.10,
            "quality": 0.10,
        }
    )
