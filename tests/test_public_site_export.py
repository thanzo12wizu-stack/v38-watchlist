from pathlib import Path

import pytest

from scripts.export_public_site import PUBLIC_FILES, export_public_site


def _safe_stub(path: Path) -> str:
    if path.suffix == ".json":
        return "{}"
    if path.suffix == ".js":
        return "window.TEST = {};"
    if path.suffix == ".css":
        return "/* safe */"
    return "<h1>Safe public fixture</h1>"


def _source(root: Path) -> None:
    for name in PUBLIC_FILES:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_safe_stub(path), encoding="utf-8")
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


def test_export_preserves_optional_leadership_under_public_subpath(tmp_path: Path):
    source = tmp_path / "source"
    output = tmp_path / "public"
    source.mkdir()
    _source(source)
    leadership = source / "leadership" / "dist"
    leadership.mkdir(parents=True)
    (leadership / "index.html").write_text("<h1>Leadership Command</h1>", encoding="utf-8")

    manifest = export_public_site(source, output, source_commit="lead123")

    assert "leadership/index.html" in manifest["allowlist"]
    assert (output / "leadership" / "index.html").read_text(encoding="utf-8") == "<h1>Leadership Command</h1>"
    assert not (output / "leadership" / "dist").exists()
    leadership_file = next(x for x in manifest["files"] if x["path"] == "leadership/index.html")
    assert leadership_file["source_path"] == "leadership/dist/index.html"


def test_export_includes_optional_tqqq_state_only_when_generated(tmp_path: Path):
    source = tmp_path / "source"
    output = tmp_path / "public"
    source.mkdir()
    _source(source)
    payload = '{"candidate":"M30_TOUCH30_F80_D10"}'
    (source / "tqqq-panic-state.json").write_text(payload, encoding="utf-8")

    manifest = export_public_site(source, output)

    assert "tqqq-panic-state.json" in manifest["allowlist"]
    assert (output / "tqqq-panic-state.json").read_text(encoding="utf-8") == payload


def test_export_does_not_require_tqqq_state_when_live_route_is_absent(tmp_path: Path):
    source = tmp_path / "source"
    output = tmp_path / "public"
    source.mkdir()
    _source(source)
    manifest = export_public_site(source, output)
    assert "tqqq-panic-state.json" not in manifest["allowlist"]


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
