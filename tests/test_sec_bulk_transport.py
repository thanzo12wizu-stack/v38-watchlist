from __future__ import annotations

import io
import json
import sys
import zipfile

import pytest

from intelligence_engine import sec_bulk


def _zip_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("CIK0000000001.json", "{}")
    return buffer.getvalue()


def test_sec_request_disables_transfer_gzip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEC_USER_AGENT", "V38 test test@example.com")

    request = sec_bulk._request(sec_bulk.SEC_BULK_URL)

    assert request.get_header("User-agent") == "V38 test test@example.com"
    assert request.get_header("Accept-encoding") == "identity"


def test_sec_request_requires_explicit_user_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)

    with pytest.raises(RuntimeError, match="SEC_USER_AGENT"):
        sec_bulk._request(sec_bulk.SEC_BULK_URL)


def test_download_writes_an_integrity_checked_zip(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _zip_bytes()
    monkeypatch.setenv("SEC_USER_AGENT", "V38 test test@example.com")
    monkeypatch.setattr(sec_bulk, "_open_with_retry", lambda *args, **kwargs: io.BytesIO(payload))
    target = tmp_path / "companyfacts.zip"

    report = sec_bulk.download(sec_bulk.SEC_BULK_URL, target)

    assert report["bytes"] == len(payload)
    with zipfile.ZipFile(target) as archive:
        assert archive.namelist() == ["CIK0000000001.json"]
    assert not target.with_suffix(".zip.part").exists()


def test_load_universe_tickers_supports_tradingview_japanese_column(tmp_path) -> None:
    universe = tmp_path / "universe.csv"
    universe.write_text("シンボル,名称\nNVDA,NVIDIA\naapl,Apple\n,blank\n", encoding="utf-8")

    assert sec_bulk.load_universe_tickers(universe) == {"NVDA", "AAPL"}


def test_load_universe_tickers_supports_normalized_symbol_column(tmp_path) -> None:
    universe = tmp_path / "universe.csv"
    universe.write_text("symbol,name\nMSFT,Microsoft\n", encoding="utf-8")

    assert sec_bulk.load_universe_tickers(universe) == {"MSFT"}


def test_main_writes_failure_stage_to_report(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    universe = tmp_path / "universe.csv"
    universe.write_text("名称\nNVIDIA\n", encoding="utf-8")
    report = tmp_path / "sec-report.json"
    monkeypatch.setattr(
        sys,
        "argv",
        ["sec_bulk", "--universe", str(universe), "--report", str(report), "--skip-download"],
    )

    with pytest.raises(ValueError, match="requires ticker"):
        sec_bulk.main()

    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["status"] == "failure"
    assert payload["stage"] == "LOAD_UNIVERSE"
    assert payload["error_type"] == "ValueError"
