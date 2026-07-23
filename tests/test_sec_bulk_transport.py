from __future__ import annotations

import io
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
