from pathlib import Path

import pytest

from scripts.export_public_site import PUBLIC_FILES, export_public_site


LOCKED_HTML = """<!doctype html><title>V38 Private Intelligence</title>
<script>const bundle={ciphertext:'abc',kdf:'PBKDF2-SHA256',cipher:'AES-GCM'};</script>
"""


def _source(
    root: Path,
    *,
    intelligence: str = LOCKED_HTML,
    research: str = LOCKED_HTML,
) -> None:
    (root / "index.html").write_text("<h1>Hub</h1>", encoding="utf-8")
    (root / "command-center.html").write_text("<h1>Command Center</h1>", encoding="utf-8")
    (root / "intelligence-dashboard.html").write_text(intelligence, encoding="utf-8")
    (root / "research-dashboard.html").write_text(research, encoding="utf-8")
    (root / "data").mkdir()
    (root / "data" / "secret.json").write_text('{"entry_candidates":[]}', encoding="utf-8")


def test_export_copies_only_allowlisted_site_files(tmp_path: Path):
    source = tmp_path / "source"
    output = tmp_path / "public"
    source.mkdir()
    _source(source)

    manifest = export_public_site(source, output, source_commit="abc123")

    assert manifest["allowlist"] == list(PUBLIC_FILES)
    assert manifest["source_commit"] == "abc123"
    assert set(manifest["locked_dashboards"]) == {
        "intelligence-dashboard.html",
        "research-dashboard.html",
    }
    assert {path.name for path in output.iterdir()} == {
        "index.html",
        "command-center.html",
        "intelligence-dashboard.html",
        "research-dashboard.html",
        ".nojekyll",
        "public-site-manifest.json",
    }
    assert not (output / "data").exists()
    assert "entry_candidates" not in (output / "intelligence-dashboard.html").read_text(encoding="utf-8")


def test_export_refuses_plaintext_intelligence_dashboard(tmp_path: Path):
    source = tmp_path / "source"
    output = tmp_path / "public"
    source.mkdir()
    _source(
        source,
        intelligence="<h1>V38 Private Intelligence</h1><div class='candidate-grid'>発注可能候補</div>",
    )
    with pytest.raises(ValueError):
        export_public_site(source, output)


def test_export_refuses_plaintext_research_dashboard(tmp_path: Path):
    source = tmp_path / "source"
    output = tmp_path / "public"
    source.mkdir()
    _source(
        source,
        research="<h1>V38 Private Intelligence</h1><div>Research Decision</h1></div>",
    )
    with pytest.raises(ValueError):
        export_public_site(source, output)


def test_export_requires_every_public_entrypoint(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "index.html").write_text("hub", encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        export_public_site(source, tmp_path / "public")
