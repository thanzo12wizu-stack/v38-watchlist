from pathlib import Path

import pytest

from scripts.export_public_site import PUBLIC_FILES, export_public_site


def _source(root: Path) -> None:
    (root / "index.html").write_text("<h1>Hub</h1>", encoding="utf-8")
    (root / "command-center.html").write_text("<h1>Command Center</h1>", encoding="utf-8")
    swinote = root / "swinote"
    swinote.mkdir()
    (swinote / "index.html").write_text("<h1>Swinote</h1>", encoding="utf-8")
    (swinote / "live.js").write_text("window.SWINOTE = {};", encoding="utf-8")
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
    assert manifest["locked_dashboards"] == []
    actual = {
        str(path.relative_to(output))
        for path in output.rglob("*")
        if path.is_file()
    }
    assert actual == set(PUBLIC_FILES) | {".nojekyll", "public-site-manifest.json"}
    assert not (output / "data").exists()


def test_export_ignores_non_allowlisted_files(tmp_path: Path):
    source = tmp_path / "source"
    output = tmp_path / "public"
    source.mkdir()
    _source(source)
    (source / "debug.html").write_text("not public", encoding="utf-8")
    manifest = export_public_site(source, output)
    assert manifest["allowlist"] == list(PUBLIC_FILES)
    assert not (output / "debug.html").exists()


def test_export_requires_every_public_entrypoint(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "index.html").write_text("hub", encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        export_public_site(source, tmp_path / "public")
