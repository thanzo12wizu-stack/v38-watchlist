from __future__ import annotations

from pathlib import Path

import pandas as pd

import intelligence_engine.research_pipeline as research_pipeline
from intelligence_engine.research_pipeline.__main__ import _failure_payload
from intelligence_engine.research_pipeline.worker import (
    _concat_bounded,
    _merge_snapshots_indexed,
)


def test_package_preserves_legacy_research_api() -> None:
    assert callable(research_pipeline.build)
    assert callable(research_pipeline.main)
    assert research_pipeline.legacy.__name__ == "intelligence_engine._research_pipeline_legacy"


def test_bounded_concat_and_indexed_snapshot_merge() -> None:
    frames = [
        pd.DataFrame({"ticker": [f"T{index}"], "value": [index]})
        for index in range(130)
    ]
    combined = _concat_bounded(frames, batch_size=16)
    assert len(combined) == 130

    panel = pd.DataFrame(
        {
            "ticker": ["AAA", "AAA", "BBB"],
            "date": pd.to_datetime(["2026-01-02", "2026-02-02", "2026-02-02"]),
            "price": [10.0, 11.0, 20.0],
        }
    )
    snapshots = pd.DataFrame(
        {
            "ticker": ["AAA", "AAA"],
            "available_at": pd.to_datetime(["2025-12-15", "2026-01-20"]),
            "eps_yoy": [0.10, 0.25],
            "fundamental_confidence": [0.5, 0.8],
        }
    )
    merged = _merge_snapshots_indexed(panel, snapshots).sort_values(["ticker", "date"])
    aaa = merged[merged["ticker"] == "AAA"]
    bbb = merged[merged["ticker"] == "BBB"]
    assert aaa["eps_yoy"].tolist() == [0.10, 0.25]
    assert bbb["fundamental_confidence"].iloc[0] == 0.0


def test_runner_reports_sigkill_without_private_values(tmp_path: Path) -> None:
    log = tmp_path / "worker.log"
    log.write_text("private ticker and financial values must not be persisted", encoding="utf-8")
    payload = _failure_payload(137, log)
    assert payload["error_type"] == "ProcessMemoryLimit"
    assert payload["exit_code"] == 137
    assert "ticker" not in payload["error_template"].lower()
