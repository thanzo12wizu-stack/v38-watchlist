from __future__ import annotations

import gzip
import json
import math
from datetime import date
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


def _json_ready(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (pd.Timestamp, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_ready(item) for item in value]
    if hasattr(value, "item"):
        try:
            return _json_ready(value.item())
        except (TypeError, ValueError):
            pass
    try:
        missing = pd.isna(value)
        if isinstance(missing, bool) and missing:
            return None
    except (TypeError, ValueError):
        pass
    return str(value)


def read_jsonl_gz(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    records = []
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                text = line.strip()
                if text:
                    records.append(json.loads(text))
    except (OSError, json.JSONDecodeError):
        return pd.DataFrame()
    return pd.DataFrame(records)


def write_jsonl_gz(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=6) as handle:
        for record in frame.to_dict(orient="records"):
            handle.write(
                json.dumps(
                    _json_ready(record),
                    ensure_ascii=False,
                    allow_nan=False,
                )
                + "\n"
            )
    tmp.replace(path)


def upsert_year_partitions(
    root: Path,
    dataset: str,
    frame: pd.DataFrame,
    *,
    date_column: str,
    keys: Iterable[str],
    retention_years: int = 5,
    reference_date: pd.Timestamp | None = None,
) -> dict[str, int]:
    dataset_root = root / dataset
    dataset_root.mkdir(parents=True, exist_ok=True)
    if frame is None or frame.empty:
        prune_old_partitions(
            dataset_root,
            retention_years=retention_years,
            reference_date=reference_date,
        )
        return {"rows": 0, "partitions": 0}

    work = frame.copy()
    work[date_column] = pd.to_datetime(work[date_column], errors="coerce")
    work = work.dropna(subset=[date_column])
    key_columns = [key for key in keys if key in work.columns]
    partitions = 0
    total_rows = 0
    for year, group in work.groupby(work[date_column].dt.year):
        path = dataset_root / f"year={int(year)}.jsonl.gz"
        existing = read_jsonl_gz(path)
        combined = (
            pd.concat([existing, group], ignore_index=True, sort=False)
            if not existing.empty
            else group.copy()
        )
        if key_columns:
            combined = combined.drop_duplicates(key_columns, keep="last")
        sort_columns = [
            column for column in (date_column, "ticker") if column in combined.columns
        ]
        if sort_columns:
            combined = combined.sort_values(sort_columns)
        write_jsonl_gz(path, combined)
        partitions += 1
        total_rows += int(len(combined))

    prune_old_partitions(
        dataset_root,
        retention_years=retention_years,
        reference_date=reference_date,
    )
    return {"rows": total_rows, "partitions": partitions}


def prune_old_partitions(
    root: Path,
    *,
    retention_years: int,
    reference_date: pd.Timestamp | None = None,
) -> None:
    now = pd.Timestamp(reference_date or pd.Timestamp.utcnow())
    if now.tzinfo is not None:
        now = now.tz_localize(None)
    minimum_year = int(now.year - max(1, retention_years) + 1)
    for path in root.glob("year=*.jsonl.gz"):
        try:
            year = int(path.name.split("=", 1)[1].split(".", 1)[0])
        except (IndexError, ValueError):
            continue
        if year < minimum_year:
            path.unlink(missing_ok=True)


def load_dataset(
    root: Path,
    dataset: str,
    *,
    years: Iterable[int] | None = None,
) -> pd.DataFrame:
    dataset_root = root / dataset
    allowed = set(int(year) for year in years) if years is not None else None
    frames = []
    for path in sorted(dataset_root.glob("year=*.jsonl.gz")):
        try:
            year = int(path.name.split("=", 1)[1].split(".", 1)[0])
        except (IndexError, ValueError):
            continue
        if allowed is not None and year not in allowed:
            continue
        frame = read_jsonl_gz(path)
        if not frame.empty:
            frames.append(frame)
    return (
        pd.concat(frames, ignore_index=True, sort=False)
        if frames
        else pd.DataFrame()
    )


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(
            _json_ready(payload),
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    tmp.replace(path)


def storage_bytes(root: Path) -> int:
    if not root.exists():
        return 0
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())
