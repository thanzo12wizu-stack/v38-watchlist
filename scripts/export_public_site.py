from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

PUBLIC_FILES = (
    "index.html",
    "command-center.html",
    "intelligence-dashboard.html",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_locked_dashboard(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    required = ("V38 Private Intelligence", "ciphertext", "PBKDF2", "AES-GCM")
    missing = [token for token in required if token not in text]
    if missing:
        raise ValueError(f"private dashboard is not a valid encrypted shell: missing {missing}")
    forbidden = (
        "発注可能候補",
        "candidate-grid",
        '"entry_candidates"',
        '"portfolio_doctor"',
    )
    leaked = [token for token in forbidden if token in text]
    if leaked:
        raise ValueError(f"private dashboard contains plaintext intelligence markers: {leaked}")


def export_public_site(root: Path, output: Path, *, source_commit: str | None = None) -> dict:
    root = root.resolve()
    output = output.resolve()
    missing = [name for name in PUBLIC_FILES if not (root / name).is_file()]
    if missing:
        raise FileNotFoundError(f"missing public site files: {missing}")

    _validate_locked_dashboard(root / "intelligence-dashboard.html")

    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)

    files = []
    for name in PUBLIC_FILES:
        source = root / name
        target = output / name
        shutil.copy2(source, target)
        files.append(
            {
                "path": name,
                "bytes": target.stat().st_size,
                "sha256": _sha256(target),
            }
        )

    (output / ".nojekyll").write_text("", encoding="utf-8")
    manifest = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source_commit": source_commit,
        "allowlist": list(PUBLIC_FILES),
        "files": files,
    }
    (output / "public-site-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    unexpected = sorted(
        str(path.relative_to(output))
        for path in output.rglob("*")
        if path.is_file()
        and path.name not in {".nojekyll", "public-site-manifest.json"}
        and str(path.relative_to(output)) not in PUBLIC_FILES
    )
    if unexpected:
        raise RuntimeError(f"unexpected files entered public export: {unexpected}")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Export only approved public V38 site artifacts")
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-commit")
    args = parser.parse_args()
    manifest = export_public_site(args.root, args.output, source_commit=args.source_commit)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
