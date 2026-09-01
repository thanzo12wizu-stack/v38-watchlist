import json
import sys
from pathlib import Path

import build_v38_sleeve_refresh as refresh
from build_v38_companion import build_state


def _ready_sleeve(asof: str, normal_pct: float = 85.0, reset_pct: float = 2.9):
    return {
        "schema": "v38-sleeve-live-1",
        "asof": asof,
        "status": "READY",
        "normal_stock": {"status": "READY", "desired_pct": normal_pct},
        "rsi_reset": {
            "status": "READY",
            "strategy": "RS63_TOP3_RISE30_SIGTOP3",
            "desired_pct": reset_pct,
            "position_count": 1 if reset_pct else 0,
            "positions": ([{"symbol": "HRL", "entry_date": asof}] if reset_pct else []),
            "monitor": [],
            "download_quality": {"coverage_ok": True},
        },
    }


def _tqqq(asof: str):
    return {
        "schema": "v38-tqqq-panic-state-1",
        "asof": asof,
        "live_generation_status": "READY",
        "current30": {"status": "READY"},
        "underlying_target_pct": 30.0,
        "requested_target_pct": 30.0,
        "normal_stock_desired_pct": None,
        "reset_desired_pct": None,
    }


def _failed_runner(out: Path, asof: str):
    def runner():
        out.write_text(
            json.dumps({
                "schema": "v38-sleeve-live-1",
                "asof": asof,
                "status": "DATA REQUIRED",
                "reason": "RuntimeError: SLEEVE_PRICE_DOWNLOAD_EMPTY",
                "rsi_reset": {"status": "DATA REQUIRED", "monitor": []},
            }),
            encoding="utf-8",
        )
    return runner


def test_same_session_failure_preserves_ready_and_marks_stale(monkeypatch, tmp_path):
    out = tmp_path / "v38-sleeve-state.json"
    tqqq = tmp_path / "tqqq-panic-state.json"
    out.write_text(json.dumps(_ready_sleeve("2026-09-01")), encoding="utf-8")
    tqqq.write_text(json.dumps(_tqqq("2026-09-01")), encoding="utf-8")
    monkeypatch.setattr(
        sys, "argv",
        ["build_v38_sleeve_live.py", "--out", str(out), "--tqqq-state", str(tqqq)],
    )

    result = refresh.run_guarded_refresh(
        _failed_runner(out, "2026-09-01"),
        continue_with_previous_ready=True,
    )
    saved = json.loads(out.read_text(encoding="utf-8"))
    merged = json.loads(tqqq.read_text(encoding="utf-8"))

    assert result["status"] == "READY"
    assert saved["rsi_reset"]["positions"][0]["symbol"] == "HRL"
    assert saved["refresh"]["status"] == "STALE / LAST_READY_PRESERVED"
    assert saved["refresh"]["attempted_asof"] == "2026-09-01"
    assert saved["refresh"]["last_successful_asof"] == "2026-09-01"
    assert saved["refresh"]["preserved_previous_ready"] is True
    assert "SLEEVE_PRICE_DOWNLOAD_EMPTY" in saved["refresh"]["error"]
    assert merged["sleeve_live_status"] == "READY"
    assert merged["normal_stock_desired_pct"] == 85.0
    assert merged["reset_desired_pct"] == 2.9
    assert "LAST_READY_PRESERVED" in merged["sleeve_live_reason"]


def test_prior_session_failure_is_preserved_but_not_current_ready(monkeypatch, tmp_path):
    out = tmp_path / "v38-sleeve-state.json"
    tqqq = tmp_path / "tqqq-panic-state.json"
    out.write_text(json.dumps(_ready_sleeve("2026-08-31", 70.0, 2.9)), encoding="utf-8")
    tqqq.write_text(json.dumps(_tqqq("2026-09-01")), encoding="utf-8")
    monkeypatch.setattr(
        sys, "argv",
        ["build_v38_sleeve_live.py", "--out", str(out), "--tqqq-state", str(tqqq)],
    )

    refresh.run_guarded_refresh(
        _failed_runner(out, "2026-09-01"),
        continue_with_previous_ready=True,
    )
    saved = json.loads(out.read_text(encoding="utf-8"))
    merged = json.loads(tqqq.read_text(encoding="utf-8"))

    assert saved["asof"] == "2026-08-31"
    assert saved["refresh"]["attempted_asof"] == "2026-09-01"
    assert saved["refresh"]["last_successful_asof"] == "2026-08-31"
    assert merged["sleeve_live_status"] == "STALE / LAST_READY_PRESERVED"
    assert merged["normal_stock_desired_pct"] is None
    assert merged["reset_desired_pct"] is None


def test_companion_exposes_same_session_preserved_ready_warning(tmp_path):
    legacy = tmp_path / "command-center.html"
    legacy.write_text(
        '<script>window.CALC={"asof":"2026-09-01","color":"Yellow"};</script>'
        '<script>window.DET={};</script>',
        encoding="utf-8",
    )
    tqqq_path = tmp_path / "tqqq.json"
    tqqq_payload = _tqqq("2026-09-01")
    tqqq_payload.update({
        "normal_stock_desired_pct": 70.0,
        "reset_desired_pct": 0.0,
        "sleeve_live_status": "READY",
        "sleeve_live_reason": "STALE / LAST_READY_PRESERVED: RuntimeError: rate limit",
    })
    tqqq_path.write_text(json.dumps(tqqq_payload), encoding="utf-8")

    sleeve_path = tmp_path / "sleeve.json"
    sleeve = _ready_sleeve("2026-09-01", 70.0, 0.0)
    sleeve["refresh"] = {
        "status": "STALE / LAST_READY_PRESERVED",
        "attempted_asof": "2026-09-01",
        "last_successful_asof": "2026-09-01",
        "attempted_at_utc": "2026-09-02T00:00:00Z",
        "preserved_previous_ready": True,
        "error": "RuntimeError: rate limit",
    }
    sleeve_path.write_text(json.dumps(sleeve), encoding="utf-8")

    state = build_state(legacy, tqqq_panic_path=tqqq_path, sleeve_state_path=sleeve_path)
    gross = state["gross100_allocation"]
    assert "LAST READY PRESERVED" in gross["status"]
    assert gross["sleeve_refresh_status"] == "STALE / LAST_READY_PRESERVED"
    assert gross["sleeve_last_successful_asof"] == "2026-09-01"
    assert gross["sleeve_preserved_previous_ready"] is True
    assert "Sleeve更新失敗・前回READY継続(2026-09-01)" in state["source"]


def test_direct_sleeve_cli_is_guarded():
    source = Path("build_v38_sleeve_live.py").read_text(encoding="utf-8")
    assert "guarded_main(continue_with_previous_ready=True)" in source
