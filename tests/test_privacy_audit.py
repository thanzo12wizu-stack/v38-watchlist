from pathlib import Path

from scripts.export_public_site import PUBLIC_FILES
from scripts.privacy_audit import audit_current_tree


def _safe_stub(path: Path) -> str:
    if path.suffix == ".json":
        return "{}"
    if path.suffix == ".js":
        return "window.TEST = {};"
    if path.suffix == ".css":
        return "/* safe */"
    return "<h1>Safe public fixture</h1>"


def _safe_tree(root: Path) -> None:
    for name in PUBLIC_FILES:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_safe_stub(path), encoding="utf-8")
    private = root / "private"
    private.mkdir()
    (private / "trade-journal-state.enc.json").write_text('{"ciphertext":"abc"}', encoding="utf-8")


def test_current_tree_privacy_passes_for_locked_allowlist(tmp_path: Path):
    _safe_tree(tmp_path)

    report = audit_current_tree(tmp_path)

    assert report["current_tree_status"] == "PASS"
    assert report["private_plaintext_file_count"] == 0
    assert report["public_plaintext_marker_count"] == 0


def test_current_tree_privacy_checks_optional_leadership_when_present(tmp_path: Path):
    _safe_tree(tmp_path)
    leadership = tmp_path / "leadership" / "dist"
    leadership.mkdir(parents=True)
    (leadership / "index.html").write_text('<script>{"entry_candidates":[]}</script>', encoding="utf-8")

    report = audit_current_tree(tmp_path)

    assert report["current_tree_status"] == "FAIL"
    assert report["public_plaintext_marker_count"] == 1
    assert report["details"]["public_marker_hits"] == [
        'leadership/dist/index.html:"entry_candidates"'
    ]


def test_current_tree_privacy_rejects_plaintext_data_paths(tmp_path: Path):
    _safe_tree(tmp_path)
    leaked = tmp_path / "data" / "external"
    leaked.mkdir(parents=True)
    (leaked / "index.json").write_text('{"entry_candidates":[]}', encoding="utf-8")

    report = audit_current_tree(tmp_path)

    assert report["current_tree_status"] == "FAIL"
    assert report["forbidden_path_count"] == 1


def test_current_tree_privacy_rejects_unencrypted_private_file(tmp_path: Path):
    _safe_tree(tmp_path)
    (tmp_path / "private" / "portfolio.csv").write_text("ticker,shares\nAAA,10\n", encoding="utf-8")

    report = audit_current_tree(tmp_path)

    assert report["current_tree_status"] == "FAIL"
    assert report["private_plaintext_file_count"] == 1
