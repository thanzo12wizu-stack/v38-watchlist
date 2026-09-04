import json
from pathlib import Path

import pytest

from scripts.validate_atomic_publish import AtomicPublishError, validate_atomic_live_snapshot


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _atomic_fixture(root: Path, asof: str = "2026-09-02") -> None:
    (root / "command-center.html").write_text(
        f"<html><body>Command Center 分析基準日 {asof}</body></html>",
        encoding="utf-8",
    )
    _write(root / "state.json", {"date": asof})
    _write(
        root / "v38-live-state.json",
        {
            "schema": "v38-live-state-1",
            "asof": asof,
            "market": {"mode": "DEFENSE", "new_entry_limit": 0},
            "gross100_allocation": {"status": "LIVE ALLOCATION READY"},
            "panic_reset": {"position_count": 1, "positions": [{"symbol": "VIK"}]},
        },
    )
    _write(
        root / "tqqq-panic-state.json",
        {
            "schema": "v38-tqqq-panic-state-1",
            "asof": asof,
            "live_generation_status": "READY",
            "current30": {"status": "READY"},
            "underlying_target_pct": 30,
            "requested_target_pct": 30,
            "sleeve_live_status": "READY",
        },
    )
    _write(
        root / "v38-sleeve-state.json",
        {
            "schema": "v38-sleeve-live-1",
            "asof": asof,
            "status": "READY",
            "normal_stock": {"status": "READY", "asof": asof},
            "rsi_reset": {
                "status": "READY",
                "asof": asof,
                "position_count": 1,
                "positions": [{"symbol": "VIK"}],
                "monitor_summary": {"active_positions": 1},
                "download_quality": {"coverage_ok": True},
                "pending": {"entries": []},
            },
        },
    )
    _write(
        root / "rotation/data/status.json",
        {
            "schema": "rotation-live-status-1",
            "status": "READY",
            "asof": asof,
            "v38_asof": asof,
        },
    )
    _write(
        root / "rotation/data/rotation-theme56.json",
        {
            "asof": asof,
            "input_alignment": {"same_asof": True, "v38_asof": asof},
        },
    )


def test_atomic_publish_gate_accepts_one_ready_asof(tmp_path: Path):
    _atomic_fixture(tmp_path)
    result = validate_atomic_live_snapshot(tmp_path)
    assert result["status"] == "READY"
    assert result["asof"] == "2026-09-02"
    assert set(result["layers"].values()) == {"READY"}


def test_atomic_publish_gate_rejects_mixed_sleeve_date(tmp_path: Path):
    _atomic_fixture(tmp_path)
    sleeve = json.loads((tmp_path / "v38-sleeve-state.json").read_text(encoding="utf-8"))
    sleeve["asof"] = "2026-09-01"
    sleeve["rsi_reset"]["asof"] = "2026-09-01"
    _write(tmp_path / "v38-sleeve-state.json", sleeve)
    with pytest.raises(AtomicPublishError, match="ATOMIC_PUBLISH_ASOF_MISMATCH"):
        validate_atomic_live_snapshot(tmp_path)


def test_atomic_publish_gate_rejects_tqqq_data_required(tmp_path: Path):
    _atomic_fixture(tmp_path)
    tqqq = json.loads((tmp_path / "tqqq-panic-state.json").read_text(encoding="utf-8"))
    tqqq["live_generation_status"] = "DATA REQUIRED"
    tqqq["reason"] = "CURRENT30_ASOF_REQUIRED"
    _write(tmp_path / "tqqq-panic-state.json", tqqq)
    with pytest.raises(AtomicPublishError, match="ATOMIC_PUBLISH_TQQQ_NOT_READY"):
        validate_atomic_live_snapshot(tmp_path)


def test_atomic_publish_gate_rejects_reset_download_gap(tmp_path: Path):
    _atomic_fixture(tmp_path)
    sleeve = json.loads((tmp_path / "v38-sleeve-state.json").read_text(encoding="utf-8"))
    sleeve["rsi_reset"]["download_quality"]["coverage_ok"] = False
    _write(tmp_path / "v38-sleeve-state.json", sleeve)
    with pytest.raises(AtomicPublishError, match="ATOMIC_PUBLISH_RSI_RESET_COVERAGE_NOT_READY"):
        validate_atomic_live_snapshot(tmp_path)


def test_atomic_publish_gate_rejects_reset_active_count_mismatch(tmp_path: Path):
    _atomic_fixture(tmp_path)
    sleeve = json.loads((tmp_path / "v38-sleeve-state.json").read_text(encoding="utf-8"))
    sleeve["rsi_reset"]["monitor_summary"]["active_positions"] = 0
    _write(tmp_path / "v38-sleeve-state.json", sleeve)
    with pytest.raises(AtomicPublishError, match="ATOMIC_PUBLISH_RSI_RESET_POSITION_MISMATCH"):
        validate_atomic_live_snapshot(tmp_path)


def test_atomic_publish_gate_rejects_reset_v38_holding_mismatch(tmp_path: Path):
    _atomic_fixture(tmp_path)
    live = json.loads((tmp_path / "v38-live-state.json").read_text(encoding="utf-8"))
    live["panic_reset"] = {"position_count": 1, "positions": [{"symbol": "RCL"}]}
    _write(tmp_path / "v38-live-state.json", live)
    with pytest.raises(AtomicPublishError, match="ATOMIC_PUBLISH_RSI_RESET_V38_MISMATCH"):
        validate_atomic_live_snapshot(tmp_path)
