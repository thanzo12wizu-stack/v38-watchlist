from pathlib import Path

from scripts.privacy_audit import audit_current_tree


LOCKED_HTML = """<!doctype html><title>V38 Private Intelligence</title>
<script>const bundle={ciphertext:'abc',kdf:'PBKDF2-SHA256',cipher:'AES-GCM'};</script>
"""


def _safe_tree(root: Path) -> None:
    (root / "index.html").write_text("<h1>Hub</h1>", encoding="utf-8")
    (root / "command-center.html").write_text("<h1>Command</h1>", encoding="utf-8")
    (root / "intelligence-dashboard.html").write_text(LOCKED_HTML, encoding="utf-8")
    (root / "research-dashboard.html").write_text(LOCKED_HTML, encoding="utf-8")
    private = root / "private"
    private.mkdir()
    (private / "research-summary.enc.json").write_text('{"ciphertext":"abc"}', encoding="utf-8")
    (private / "research-success.json").write_text('{"research_status":"PASS"}', encoding="utf-8")


def test_current_tree_privacy_passes_for_locked_allowlist(tmp_path: Path):
    _safe_tree(tmp_path)

    report = audit_current_tree(tmp_path)

    assert report["current_tree_status"] == "PASS"
    assert report["private_plaintext_file_count"] == 0
    assert report["public_plaintext_marker_count"] == 0


def test_current_tree_privacy_rejects_plaintext_data_paths(tmp_path: Path):
    _safe_tree(tmp_path)
    leaked = tmp_path / "data" / "intelligence"
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
