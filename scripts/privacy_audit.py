from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts.export_public_site import LOCKED_DASHBOARDS, PUBLIC_FILES, _validate_locked_dashboard
except ModuleNotFoundError:  # direct execution: python scripts/privacy_audit.py
    from export_public_site import LOCKED_DASHBOARDS, PUBLIC_FILES, _validate_locked_dashboard

FORBIDDEN_CURRENT_PATHS = (
    "data/intelligence",
    "data/external",
    "portfolio.csv",
)

FORBIDDEN_PUBLIC_MARKERS = (
    '"entry_candidates"',
    '"portfolio_doctor"',
    "candidate-grid",
    "発注可能候補",
)


def audit_current_tree(root: Path) -> dict:
    root = root.resolve()
    forbidden_paths = [name for name in FORBIDDEN_CURRENT_PATHS if (root / name).exists()]
    missing_public = [name for name in PUBLIC_FILES if not (root / name).is_file()]
    dashboard_errors: list[str] = []
    for name in LOCKED_DASHBOARDS:
        path = root / name
        if not path.exists():
            dashboard_errors.append(f"missing:{name}")
            continue
        try:
            _validate_locked_dashboard(path)
        except ValueError as exc:
            dashboard_errors.append(f"invalid:{name}:{type(exc).__name__}")

    public_marker_hits: list[str] = []
    for name in PUBLIC_FILES:
        path = root / name
        if not path.is_file() or name == "command-center.html":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for marker in FORBIDDEN_PUBLIC_MARKERS:
            if marker in text:
                public_marker_hits.append(f"{name}:{marker}")

    private_plaintext = []
    private = root / "private"
    if private.exists():
        for path in private.rglob("*"):
            if not path.is_file():
                continue
            relative = str(path.relative_to(root))
            allowed = relative.endswith(".enc.json") or path.name in {
                "research-success.json",
                "research-error-detail.json",
            }
            if not allowed:
                private_plaintext.append(relative)

    passed = not forbidden_paths and not missing_public and not dashboard_errors and not public_marker_hits and not private_plaintext
    return {
        "schema_version": "1.0",
        "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "current_tree_status": "PASS" if passed else "FAIL",
        "forbidden_path_count": len(forbidden_paths),
        "missing_public_entrypoint_count": len(missing_public),
        "locked_dashboard_error_count": len(dashboard_errors),
        "public_plaintext_marker_count": len(public_marker_hits),
        "private_plaintext_file_count": len(private_plaintext),
        "details": {
            "forbidden_paths": forbidden_paths,
            "missing_public_entrypoints": missing_public,
            "dashboard_errors": dashboard_errors,
            "public_marker_hits": public_marker_hits,
            "private_plaintext_files": private_plaintext,
        },
        "privacy": "The report contains paths and aggregate counts only; no holdings, tickers, prices or financial values are included.",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, default=Path("privacy-audit-status.json"))
    args = parser.parse_args()
    report = audit_current_tree(args.root)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False))
    if report["current_tree_status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
