from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


def finite_or_none(value: object) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def percentile_rank(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.notna().sum() <= 1:
        return pd.Series(np.nan, index=series.index, dtype=float)
    return numeric.rank(pct=True, method="average") * 100.0


def weighted_available(values: dict[str, float | None], weights: dict[str, float]) -> tuple[float | None, float]:
    valid = [(k, float(v), float(weights[k])) for k, v in values.items() if v is not None and k in weights]
    if not valid:
        return None, 0.0
    weight_sum = sum(w for _, _, w in valid)
    if weight_sum <= 0:
        return None, 0.0
    score = sum(v * w for _, v, w in valid) / weight_sum
    confidence = weight_sum / max(sum(weights.values()), 1e-9)
    return float(score), float(min(max(confidence, 0.0), 1.0))


def atomic_write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
    tmp.replace(path)


def safe_mean(values: Iterable[float | None]) -> float | None:
    clean = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    return sum(clean) / len(clean) if clean else None
