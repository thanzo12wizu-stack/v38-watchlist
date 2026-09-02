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
    "command-center-v38.html",
    "v38-live-state.json",
    "swinote/index.html",
    "swinote/live.js",
    "rotation/index.html",
    "rotation/app.css",
    "rotation/app-theme56.js",
    "rotation/market-sync.js",
)

DERIVED_PUBLIC_FILES = (
    "rotation/dashboard-market.json",
)

# Optional source -> public-target mappings. Leadership is produced by its own
# workflow and persisted independently, so the normal dashboard exporter must
# preserve it when present without making the existing dashboard depend on it.
OPTIONAL_PUBLIC_FILES = (
    ("leadership/dist/index.html", "leadership/index.html"),
    # Publishable when the live producer creates it. Optionality is deliberate:
    # allowlisting this file does not claim that CURRENT30/4H RSI generation is live.
    ("tqqq-panic-state.json", "tqqq-panic-state.json"),
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_rotation_dashboard_market(root: Path, output: Path) -> tuple[str, str]:
    """Publish only the market fields Rotation needs from private/live state.

    state.json itself stays outside the public allowlist. This derived payload is
    intentionally small and contains no picks, holdings, trade state, or other
    private dashboard details.
    """
    live = _read_json(root / "v38-live-state.json")
    state = _read_json(root / "state.json")
    market = live.get("market") if isinstance(live.get("market"), dict) else {}
    panic = live.get("panic_tqqq") if isinstance(live.get("panic_tqqq"), dict) else {}

    payload = {
        "schema": "rotation-dashboard-market-1",
        "v38_asof": live.get("asof"),
        "crowd_asof": state.get("date"),
        "market_conditions": panic.get("mc57"),
        "nqsar": market.get("nqsar"),
        "breadth50": market.get("breadth50"),
        "mode": market.get("mode"),
        "new_entry_limit": market.get("new_entry_limit"),
        "crowd_temperature": state.get("senti"),
        "vix": panic.get("vix_close"),
    }

    target_name = "rotation/dashboard-market.json"
    target = output / target_name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target_name, "derived:v38-live-state.json+state.json:selected-market-fields"


def export_public_site(root: Path, output: Path, *, source_commit: str | None = None) -> dict:
    root = root.resolve()
    output = output.resolve()
    missing = [name for name in PUBLIC_FILES if not (root / name).is_file()]
    if missing:
        raise FileNotFoundError(f"missing public site files: {missing}")

    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)

    export_items: list[tuple[str, str]] = [(name, name) for name in PUBLIC_FILES]
    export_items.extend(
        (source_name, target_name)
        for source_name, target_name in OPTIONAL_PUBLIC_FILES
        if (root / source_name).is_file()
    )

    files = []
    for source_name, target_name in export_items:
        source = root / source_name
        target = output / target_name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        files.append(
            {
                "path": target_name,
                "source_path": source_name,
                "bytes": target.stat().st_size,
                "sha256": _sha256(target),
            }
        )

    derived_target, derived_source = _write_rotation_dashboard_market(root, output)
    derived_path = output / derived_target
    files.append(
        {
            "path": derived_target,
            "source_path": derived_source,
            "bytes": derived_path.stat().st_size,
            "sha256": _sha256(derived_path),
        }
    )

    (output / ".nojekyll").write_text("", encoding="utf-8")
    public_paths = [target_name for _, target_name in export_items] + list(DERIVED_PUBLIC_FILES)
    manifest = {
        "schema_version": "1.2",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source_commit": source_commit,
        "allowlist": public_paths,
        "locked_dashboards": [],
        "files": files,
    }
    (output / "public-site-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    expected = set(public_paths) | {".nojekyll", "public-site-manifest.json"}
    actual = {
        str(path.relative_to(output))
        for path in output.rglob("*")
        if path.is_file()
    }
    unexpected = sorted(actual - expected)
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
