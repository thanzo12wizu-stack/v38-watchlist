import json
from pathlib import Path

from intelligence_engine.research_worker_status import build_status


def test_price_warmup_writes_aggregate_result_without_fake_research_success(tmp_path, monkeypatch):
    price_report = tmp_path / "price.json"
    price_report.write_text(
        json.dumps(
            {
                "provider": "test",
                "coverage": 0.75,
                "history_requested": 500,
                "history_batch": 250,
                "history_received": 240,
            }
        ),
        encoding="utf-8",
    )
    sec_dir = tmp_path / "sec"
    sec_dir.mkdir()
    (sec_dir / "AAA.json").write_text("{}", encoding="utf-8")
    private_dir = tmp_path / "private"
    monkeypatch.setenv("GITHUB_RUN_ID", "12345")

    result = build_status(
        action="PRICE_WARMUP",
        research_year=2026,
        price_report=price_report,
        sec_dir=sec_dir,
        research_root=tmp_path / "research",
        private_dir=private_dir,
    )

    assert result["workflow_run_id"] == "12345"
    assert result["sec_cache_ready"] is True
    assert result["sec_data_ready"] is False
    assert result["price_history_batch"] == 250
    assert (private_dir / "research-worker-result.json").exists()
    assert not (private_dir / "research-success.json").exists()


def test_year_backfill_updates_sec_and_partition_readiness(tmp_path, monkeypatch):
    price_report = tmp_path / "price.json"
    price_report.write_text('{"provider":"test","coverage":1.0}', encoding="utf-8")
    sec_dir = tmp_path / "sec"
    sec_dir.mkdir()
    (sec_dir / "AAA.json").write_text("{}", encoding="utf-8")
    research_root = tmp_path / "research"
    for dataset in ("facts", "signals", "outcomes", "rankings"):
        target = research_root / dataset
        target.mkdir(parents=True)
        (target / "year=2026.jsonl.gz").write_bytes(b"x")
    (research_root / "manifest.json").write_text("{}", encoding="utf-8")
    private_dir = tmp_path / "private"
    private_dir.mkdir()
    (private_dir / "research-summary.enc.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("GITHUB_RUN_ID", "67890")

    result = build_status(
        action="YEAR_BACKFILL",
        research_year=2026,
        price_report=price_report,
        sec_dir=sec_dir,
        research_root=research_root,
        private_dir=private_dir,
    )
    success = json.loads((private_dir / "research-success.json").read_text(encoding="utf-8"))

    assert result["sec_data_ready"] is True
    assert success["research_status"] == "PASS"
    assert success["sec_data_present"] is True
    assert success["sec_cache_file_count"] == 1
    assert success["fact_partition_count"] == 1
    assert success["last_worker_run_id"] == "67890"
