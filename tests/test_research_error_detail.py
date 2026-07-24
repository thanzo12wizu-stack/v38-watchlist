from __future__ import annotations

from intelligence_engine.research_pipeline.__main__ import _failure_payload


def test_merge_error_detail_is_persisted_without_traceback(tmp_path):
    log = tmp_path / "research.log"
    log.write_text(
        "Traceback (most recent call last):\n"
        "  File '/tmp/worker.py', line 1, in <module>\n"
        "pandas.errors.MergeError: incompatible merge keys [0] dtype('<M8[ns]') and dtype('O'), must be the same type\n",
        encoding="utf-8",
    )

    payload = _failure_payload(1, log, stage="worker")

    assert payload["schema_version"] == "2.2"
    assert payload["error_type"] == "MergeError"
    assert payload["error_detail"] == "incompatible merge keys [0] dtype('<M8[ns]') and dtype('O'), must be the same type"
    assert "Traceback" not in payload["error_detail"]
    assert "/tmp/worker.py" not in payload["error_detail"]


def test_non_merge_exception_detail_is_not_persisted(tmp_path):
    log = tmp_path / "research.log"
    log.write_text("ValueError: possibly sensitive runtime detail\n", encoding="utf-8")

    payload = _failure_payload(1, log, stage="worker")

    assert payload["error_type"] == "ValueError"
    assert "error_detail" not in payload
