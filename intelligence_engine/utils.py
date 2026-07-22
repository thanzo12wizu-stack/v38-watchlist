from __future__ import annotations

import json
import math
from datetime import date, datetime
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
    valid: list[tuple[str, float, float]] = []
    for key, raw_value in values.items():
        if key not in weights:
            continue
        value = finite_or_none(raw_value)
        weight = finite_or_none(weights[key])
        if value is None or weight is None or weight <= 0:
            continue
        valid.append((key, value, weight))
    if not valid:
        return None, 0.0
    weight_sum = sum(weight for _, _, weight in valid)
    if weight_sum <= 0:
        return None, 0.0
    score = sum(value * weight for _, value, weight in valid) / weight_sum
    configured_weight = sum(
        weight
        for raw_weight in weights.values()
        if (weight := finite_or_none(raw_weight)) is not None and weight > 0
    )
    confidence = weight_sum / max(configured_weight, 1e-9)
    return float(score), float(min(max(confidence, 0.0), 1.0))


def _json_safe(value: object) -> object:
    """Convert pandas/numpy and non-finite values into strict JSON values."""
    if value is None or value is pd.NA:
        return None
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, dict):
        return {
            key if isinstance(key, (str, int, float, bool)) or key is None else str(key): _json_safe(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (str, int, bool)):
        return value
    try:
        missing = pd.isna(value)
    except (TypeError, ValueError):
        missing = False
    if isinstance(missing, (bool, np.bool_)) and bool(missing):
        return None
    return value


def atomic_write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(
            _json_safe(payload),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        ),
        encoding="utf-8",
    )
    tmp.replace(path)


def safe_mean(values: Iterable[float | None]) -> float | None:
    clean = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    return sum(clean) / len(clean) if clean else None
